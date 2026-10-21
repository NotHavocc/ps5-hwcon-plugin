import asyncio
import errno
import json
import os
import re
import shutil
import threading
import time

try:
    import decky as decky_plugin
except ImportError:
    try:
        import decky_plugin
    except ImportError:
        decky_plugin = None

if decky_plugin is not None:
    logger = decky_plugin.logger
else:
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("ps5-hardware-control")


FAN_TARGET_PATH = "/sys/bus/platform/devices/ps5-fan/target_temp"
FAN_SAFE_MIN = 40
FAN_SAFE_MAX = 90
FAN_BOOT_TARGET = 80
FAN_MAX_COOLING_TARGET = 50

HWMON_DIR = "/sys/class/hwmon"
HWMON_CHIP_PRIORITY = {"k10temp": 0, "amdgpu": 1, "nvme": 2}
CPU_SENSOR_CHIP = "k10temp"
SENSOR_LABELS = {
    ("k10temp", "Tctl"): "CPU",
    ("k10temp", "Tdie"): "CPU Die",
    ("amdgpu", "edge"): "GPU",
    ("amdgpu", "junction"): "GPU Junction",
    ("amdgpu", "mem"): "GPU Memory",
    ("nvme", "Composite"): "SSD",
}
SENSOR_PLAUSIBLE_MIN = -20.0
SENSOR_PLAUSIBLE_MAX = 150.0

GUARD_MIN = 80
GUARD_MAX = 100
GUARD_DEFAULT = 95
GUARD_HYSTERESIS = 10
GUARD_POLL_SECONDS = 3.0

LED_CLASS_DIR = "/sys/class/leds"
LED_PREFIX = "ps5:"
LED_SUFFIX = ":indicator"
LED_OFF_PRESET = "off"
LED_PRESET_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
LED_ANIMATED_PATTERN = re.compile(r"breathe|pulse|anim|sunrise|_to_")
LED_LOOP_MIN = 2
LED_LOOP_MAX = 30
LED_LOOP_DEFAULT = 6
LED_LOOP_TICK_SECONDS = 0.5
LED_RETRIGGER_GAP_SECONDS = 0.05

CPUFREQ_DIR = "/sys/devices/system/cpu/cpufreq"
CPU_POLICY_PATTERN = re.compile(r"^policy(\d+)$")
CPU_GOVERNOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

BUZZER_DIR = "/sys/class/misc/ps5_buzzer"
BUZZER_BEEP_PATH = "/sys/class/misc/ps5_buzzer/beep"
BUZZER_STOP_PATH = "/sys/class/misc/ps5_buzzer/stop"
BUZZER_SILENT = 0
BUZZER_ERROR = 2
BUZZER_LEVELS = {1: "Short", 2: "Error", 3: "Long"}

IO_TIMEOUT_SECONDS = 5.0
UNLOAD_TIMEOUT_SECONDS = 3.0
LS_CANDIDATES = ("/usr/bin/ls", "/bin/ls")

SETTINGS_DIR = os.path.abspath(
    getattr(decky_plugin, "DECKY_PLUGIN_SETTINGS_DIR", None)
    or os.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
    or os.path.dirname(os.path.abspath(__file__))
)
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
DEFAULT_SETTINGS = {
    "restore_on_boot": False,
    "saved_target": None,
    "guard_enabled": False,
    "guard_threshold": GUARD_DEFAULT,
    "alarm_enabled": False,
    "led_loop_enabled": False,
    "led_loop_seconds": LED_LOOP_DEFAULT,
    "cpu_restore_on_boot": False,
    "saved_governor": None,
}

_fan_lock = asyncio.Lock()
_led_lock = asyncio.Lock()
_cpu_lock = asyncio.Lock()
_buzzer_lock = asyncio.Lock()
_settings_lock = asyncio.Lock()

_settings = dict(DEFAULT_SETTINGS)
_guard = {"active": False, "restore_target": None, "cpu": None}
_alarm = {"active": False}
_led = {"preset": None, "started": 0.0, "error_logged": False}
_guard_task = None
_led_loop_task = None


def _ok(message, data=None, log=True):
    if log:
        logger.info(message)
    return {"success": True, "message": message, "data": data}


def _fail(error):
    logger.error(error)
    return {"success": False, "error": error}


def _led_brightness_path(preset):
    return f"{LED_CLASS_DIR}/{LED_PREFIX}{preset}{LED_SUFFIX}/brightness"


def _coerce_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    return None


def _describe_os_error(exc, path):
    if exc.errno == errno.ENODEV:
        return f"Hardware not ready (ICC link not initialised) at {path}"
    if exc.errno == errno.EINVAL:
        return f"Value rejected by driver at {path}"
    if exc.errno == errno.ERANGE:
        return f"Value out of driver range at {path}"
    if exc.errno == errno.EIO:
        return f"I/O error talking to hardware at {path}"
    if exc.errno is not None:
        return f"{os.strerror(exc.errno)} at {path}"
    return f"{exc} at {path}"


def _read_sysfs(path):
    with open(path, "r", encoding="ascii") as handle:
        return handle.read().strip()


def _write_sysfs(path, value):
    payload = f"{value}\n".encode("ascii")
    fd = os.open(path, os.O_WRONLY)
    try:
        written = os.write(fd, payload)
    finally:
        os.close(fd)
    if written != len(payload):
        raise OSError(errno.EIO, "Short write")


def _settle(future, result, exc):
    if future.done():
        return
    if exc is not None:
        future.set_exception(exc)
    else:
        future.set_result(result)


def _run_detached(func, *args):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def runner():
        try:
            outcome = (func(*args), None)
        except BaseException as exc:
            outcome = (None, exc)
        try:
            loop.call_soon_threadsafe(_settle, future, *outcome)
        except RuntimeError:
            pass

    threading.Thread(target=runner, name=f"ps5hw-{func.__name__}", daemon=True).start()
    return future


async def _guarded_io(action, path, func, *args):
    try:
        result = await asyncio.wait_for(
            _run_detached(func, *args), timeout=IO_TIMEOUT_SECONDS
        )
        return True, result
    except FileNotFoundError:
        return False, (
            f"{action} failed: {path} does not exist. "
            "Is the ps5-linux-patches kernel running?"
        )
    except PermissionError:
        return False, f"{action} failed: permission denied on {path}"
    except asyncio.TimeoutError:
        return False, f"{action} failed: hardware did not respond within {IO_TIMEOUT_SECONDS:.0f}s"
    except OSError as exc:
        return False, f"{action} failed: {_describe_os_error(exc, path)}"
    except Exception as exc:
        return False, f"{action} failed: unexpected error: {exc}"


def _scan_temperatures():
    sensors = []
    try:
        chip_dirs = sorted(os.listdir(HWMON_DIR))
    except OSError:
        return sensors

    for chip_dir in chip_dirs:
        base = os.path.join(HWMON_DIR, chip_dir)
        try:
            chip = _read_sysfs(os.path.join(base, "name"))
            entries = sorted(os.listdir(base))
        except (OSError, UnicodeDecodeError):
            continue

        for entry in entries:
            match = re.fullmatch(r"temp(\d+)_input", entry)
            if not match:
                continue
            index = match.group(1)
            try:
                celsius = int(_read_sysfs(os.path.join(base, entry))) / 1000.0
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not SENSOR_PLAUSIBLE_MIN <= celsius <= SENSOR_PLAUSIBLE_MAX:
                continue
            try:
                raw_label = _read_sysfs(os.path.join(base, f"temp{index}_label"))
            except (OSError, UnicodeDecodeError):
                raw_label = f"temp{index}"
            sensors.append(
                {
                    "id": f"{chip_dir}/temp{index}",
                    "chip": chip,
                    "label": SENSOR_LABELS.get((chip, raw_label), f"{chip} {raw_label}"),
                    "celsius": round(celsius, 1),
                }
            )

    sensors.sort(key=lambda s: (HWMON_CHIP_PRIORITY.get(s["chip"], 99), s["id"]))
    return sensors


async def _read_temperatures():
    try:
        return await asyncio.wait_for(
            _run_detached(_scan_temperatures), timeout=IO_TIMEOUT_SECONDS
        )
    except Exception as exc:
        logger.error(f"Reading temperatures failed: {exc}")
        return []


def _cpu_temperature(sensors):
    readings = [s["celsius"] for s in sensors if s["chip"] == CPU_SENSOR_CHIP]
    return max(readings) if readings else None


def _sanitize_settings(raw):
    settings = dict(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings
    settings["restore_on_boot"] = raw.get("restore_on_boot") is True
    settings["guard_enabled"] = raw.get("guard_enabled") is True
    settings["alarm_enabled"] = raw.get("alarm_enabled") is True
    threshold = _coerce_int(raw.get("guard_threshold"))
    if threshold is not None and GUARD_MIN <= threshold <= GUARD_MAX:
        settings["guard_threshold"] = threshold
    saved = _coerce_int(raw.get("saved_target"))
    if saved is not None and FAN_SAFE_MIN <= saved <= FAN_SAFE_MAX:
        settings["saved_target"] = saved
    settings["led_loop_enabled"] = raw.get("led_loop_enabled") is True
    loop_seconds = _coerce_int(raw.get("led_loop_seconds"))
    if loop_seconds is not None and LED_LOOP_MIN <= loop_seconds <= LED_LOOP_MAX:
        settings["led_loop_seconds"] = loop_seconds
    settings["cpu_restore_on_boot"] = raw.get("cpu_restore_on_boot") is True
    governor = raw.get("saved_governor")
    if isinstance(governor, str) and CPU_GOVERNOR_PATTERN.fullmatch(governor):
        settings["saved_governor"] = governor
    return settings


def _load_settings_sync():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            return _sanitize_settings(json.load(handle))
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError) as exc:
        logger.warning(f"Ignoring unreadable settings at {SETTINGS_PATH}: {exc}")
        return dict(DEFAULT_SETTINGS)


def _save_settings_sync(settings):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    temp_path = f"{SETTINGS_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, SETTINGS_PATH)


async def _save_settings(settings):
    try:
        await _run_detached(_save_settings_sync, settings)
        return True, None
    except PermissionError:
        return False, f"Permission denied writing {SETTINGS_PATH}"
    except OSError as exc:
        return False, f"Saving settings failed: {_describe_os_error(exc, SETTINGS_PATH)}"
    except Exception as exc:
        return False, f"Saving settings failed: unexpected error: {exc}"


async def _remember_target(target):
    async with _settings_lock:
        if _settings["saved_target"] == target:
            return
        _settings["saved_target"] = target
        ok, error = await _save_settings(dict(_settings))
    if not ok:
        logger.warning(error)


async def _remember_governor(governor):
    async with _settings_lock:
        if _settings["saved_governor"] == governor:
            return
        _settings["saved_governor"] = governor
        ok, error = await _save_settings(dict(_settings))
    if not ok:
        logger.warning(error)


def _guard_snapshot():
    return {
        "enabled": _settings["guard_enabled"],
        "active": _guard["active"],
        "threshold": _settings["guard_threshold"],
        "restore_target": _guard["restore_target"],
        "cpu": _guard["cpu"],
        "alarm_enabled": _settings["alarm_enabled"],
        "alarm_active": _alarm["active"],
    }


async def _write_fan_target_locked(action, target):
    ok, error = await _guarded_io(action, FAN_TARGET_PATH, _write_sysfs, FAN_TARGET_PATH, target)
    if not ok:
        return False, error
    ok, readback = await _guarded_io(
        "Verifying fan target", FAN_TARGET_PATH, _read_sysfs, FAN_TARGET_PATH
    )
    confirmed = _coerce_int(readback) if ok else None
    if confirmed is None:
        return True, target
    if confirmed != target:
        return False, f"{action}: write accepted but driver reports {confirmed} °C"
    return True, confirmed


async def _guard_engage(cpu):
    async with _fan_lock:
        if _guard["active"]:
            return
        ok, current = await _guarded_io(
            "Reading fan target", FAN_TARGET_PATH, _read_sysfs, FAN_TARGET_PATH
        )
        previous = _coerce_int(current) if ok else None
        ok, result = await _write_fan_target_locked(
            "Engaging thermal guard", FAN_MAX_COOLING_TARGET
        )
        if not ok:
            logger.error(result)
            return
        _guard["active"] = True
        _guard["restore_target"] = (
            previous if previous is not None else _settings["saved_target"] or FAN_BOOT_TARGET
        )
    logger.warning(
        f"Thermal guard engaged at CPU {cpu:.1f} °C: fan target {FAN_MAX_COOLING_TARGET} °C"
    )


async def _guard_release(reason):
    async with _fan_lock:
        if not _guard["active"]:
            return
        target = _guard["restore_target"] or _settings["saved_target"] or FAN_BOOT_TARGET
        ok, result = await _write_fan_target_locked("Releasing thermal guard", target)
        if not ok:
            logger.error(result)
            return
        _guard["active"] = False
        _guard["restore_target"] = None
    logger.info(f"Thermal guard released ({reason}): fan target {target} °C")


async def _alarm_sound(cpu):
    async with _buzzer_lock:
        if _alarm["active"]:
            return
        _alarm["active"] = True
        ok, error = await _guarded_io(
            "Sounding overheat alarm", BUZZER_BEEP_PATH, _write_sysfs, BUZZER_BEEP_PATH, BUZZER_ERROR
        )
    if ok:
        logger.warning(f"Overheat alarm: CPU {cpu:.1f} °C")
    else:
        logger.error(error)


async def _alarm_clear(reason):
    async with _buzzer_lock:
        if not _alarm["active"]:
            return
        _alarm["active"] = False
        ok, error = await _guarded_io(
            "Silencing overheat alarm", BUZZER_BEEP_PATH, _write_sysfs, BUZZER_BEEP_PATH, BUZZER_SILENT
        )
    if ok:
        logger.info(f"Overheat alarm cleared ({reason})")
    else:
        logger.warning(error)


async def _guard_tick():
    guard_on = _settings["guard_enabled"]
    alarm_on = _settings["alarm_enabled"]
    if not guard_on and _guard["active"]:
        await _guard_release("guard disabled")
    if not alarm_on and _alarm["active"]:
        await _alarm_clear("alarm disabled")
    if not (guard_on or alarm_on):
        _guard["cpu"] = None
        return

    cpu = _cpu_temperature(await _read_temperatures())
    _guard["cpu"] = cpu
    if cpu is None:
        return

    threshold = _settings["guard_threshold"]
    hot = cpu >= threshold
    cooled = cpu <= threshold - GUARD_HYSTERESIS

    if guard_on:
        if hot and not _guard["active"]:
            await _guard_engage(cpu)
        elif cooled and _guard["active"]:
            await _guard_release(f"CPU cooled to {cpu:.1f} °C")

    if alarm_on:
        if hot and not _alarm["active"]:
            await _alarm_sound(cpu)
        elif cooled and _alarm["active"]:
            await _alarm_clear(f"CPU cooled to {cpu:.1f} °C")


async def _guard_loop():
    while True:
        await asyncio.sleep(GUARD_POLL_SECONDS)
        try:
            await _guard_tick()
        except Exception as exc:
            logger.error(f"Thermal guard error: {exc}")


def _is_animated(preset):
    return bool(preset) and preset != LED_OFF_PRESET and bool(LED_ANIMATED_PATTERN.search(preset))


def _led_settings_snapshot():
    return {
        "loop_enabled": _settings["led_loop_enabled"],
        "loop_seconds": _settings["led_loop_seconds"],
        "preset": _led["preset"],
        "looping": _settings["led_loop_enabled"] and _is_animated(_led["preset"]),
    }


def _retrigger_sync(path):
    _write_sysfs(path, 0)
    time.sleep(LED_RETRIGGER_GAP_SECONDS)
    _write_sysfs(path, 1)


async def _led_loop_tick():
    preset = _led["preset"]
    if not (_settings["led_loop_enabled"] and _is_animated(preset)):
        return
    if time.monotonic() - _led["started"] < _settings["led_loop_seconds"]:
        return
    path = _led_brightness_path(preset)
    async with _led_lock:
        if _led["preset"] != preset:
            return
        ok, error = await _guarded_io(
            f"Replaying LED animation '{preset}'", path, _retrigger_sync, path
        )
        _led["started"] = time.monotonic()
    if ok:
        _led["error_logged"] = False
    elif not _led["error_logged"]:
        _led["error_logged"] = True
        logger.error(error)


async def _led_loop():
    while True:
        await asyncio.sleep(LED_LOOP_TICK_SECONDS)
        try:
            await _led_loop_tick()
        except Exception as exc:
            logger.error(f"LED loop error: {exc}")


async def _cancel_task(task):
    if task is None:
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception as exc:
        logger.error(f"Background task ended with an error: {exc}")


def _subprocess_env():
    env = dict(os.environ)
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    env["LC_ALL"] = "C"
    return env


def _resolve_ls():
    for candidate in LS_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("ls")


async def _list_led_entries():
    if not os.path.isdir(LED_CLASS_DIR):
        raise FileNotFoundError(errno.ENOENT, "No such directory", LED_CLASS_DIR)

    ls_binary = _resolve_ls()
    if ls_binary is None:
        logger.warning("ls not found, falling back to os.listdir")
        return await _run_detached(os.listdir, LED_CLASS_DIR)

    process = await asyncio.create_subprocess_exec(
        ls_binary,
        "-1",
        LED_CLASS_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=IO_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise

    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise OSError(errno.EIO, f"ls exited with {process.returncode}: {message}")

    return stdout.decode("utf-8", errors="replace").splitlines()


def _parse_presets(entries):
    presets = []
    for entry in entries:
        name = entry.strip()
        if not (name.startswith(LED_PREFIX) and name.endswith(LED_SUFFIX)):
            continue
        preset = name[len(LED_PREFIX) : -len(LED_SUFFIX)]
        if not LED_PRESET_PATTERN.fullmatch(preset):
            continue
        if not os.path.exists(_led_brightness_path(preset)):
            continue
        presets.append(preset)
    return sorted(set(presets), key=lambda p: (p != LED_OFF_PRESET, p))


async def _discover_presets():
    try:
        entries = await _list_led_entries()
    except FileNotFoundError:
        return False, f"{LED_CLASS_DIR} does not exist. Is the LED class available?"
    except PermissionError:
        return False, f"Permission denied listing {LED_CLASS_DIR}"
    except asyncio.TimeoutError:
        return False, f"Listing {LED_CLASS_DIR} timed out"
    except OSError as exc:
        return False, f"Listing LED presets failed: {_describe_os_error(exc, LED_CLASS_DIR)}"
    except Exception as exc:
        return False, f"Listing LED presets failed: unexpected error: {exc}"

    presets = _parse_presets(entries)
    if not presets:
        return False, (
            "No ps5:*:indicator LEDs found. "
            "Is the ps5-led driver loaded in the ps5-linux-patches kernel?"
        )
    return True, presets


def _cpu_policy_dirs():
    policies = []
    for entry in os.listdir(CPUFREQ_DIR):
        match = CPU_POLICY_PATTERN.fullmatch(entry)
        if match:
            policies.append((int(match.group(1)), os.path.join(CPUFREQ_DIR, entry)))
    if not policies:
        raise FileNotFoundError(errno.ENOENT, "No cpufreq policies", CPUFREQ_DIR)
    return [path for _, path in sorted(policies)]


def _read_policy_value(base, name):
    try:
        return _read_sysfs(os.path.join(base, name))
    except (OSError, UnicodeDecodeError):
        return None


def _read_policy_mhz(base, name):
    khz = _coerce_int(_read_policy_value(base, name))
    return round(khz / 1000) if khz is not None and khz > 0 else None


def _scan_cpufreq():
    governors = None
    active = []
    drivers = []
    current = []
    hw_min = []
    hw_max = []
    policies = _cpu_policy_dirs()

    for base in policies:
        names = (_read_policy_value(base, "scaling_available_governors") or "").split()
        if governors is None:
            governors = names
        else:
            governors = [g for g in governors if g in names]
        governor = _read_policy_value(base, "scaling_governor")
        if governor and governor not in active:
            active.append(governor)
        driver = _read_policy_value(base, "scaling_driver")
        if driver and driver not in drivers:
            drivers.append(driver)
        for values, name in (
            (current, "scaling_cur_freq"),
            (hw_min, "cpuinfo_min_freq"),
            (hw_max, "cpuinfo_max_freq"),
        ):
            mhz = _read_policy_mhz(base, name)
            if mhz is not None:
                values.append(mhz)

    return {
        "driver": ", ".join(drivers) or None,
        "governors": [g for g in governors or [] if CPU_GOVERNOR_PATTERN.fullmatch(g)],
        "active": active,
        "policy_count": len(policies),
        "freq_avg_mhz": round(sum(current) / len(current)) if current else None,
        "freq_peak_mhz": max(current) if current else None,
        "hw_min_mhz": min(hw_min) if hw_min else None,
        "hw_max_mhz": max(hw_max) if hw_max else None,
    }


def _write_governor_sync(governor):
    failures = []
    for base in _cpu_policy_dirs():
        try:
            _write_sysfs(os.path.join(base, "scaling_governor"), governor)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise failures[0]


async def _read_cpufreq():
    if not os.path.isdir(CPUFREQ_DIR):
        return False, (
            f"{CPUFREQ_DIR} does not exist. No cpufreq driver is loaded "
            "(check that amd_pstate or acpi-cpufreq is enabled in the kernel)"
        )
    ok, result = await _guarded_io("Reading CPU frequency", CPUFREQ_DIR, _scan_cpufreq)
    if ok and not result["governors"]:
        return False, f"The {result['driver'] or 'cpufreq'} driver exposes no governors"
    return ok, result


async def _apply_governor_locked(action, governor):
    ok, status = await _read_cpufreq()
    if not ok:
        return False, status
    if governor not in status["governors"]:
        available = ", ".join(status["governors"])
        return False, f"Governor '{governor}' is not available. The kernel offers: {available}"

    ok, error = await _guarded_io(action, CPUFREQ_DIR, _write_governor_sync, governor)
    if not ok:
        return False, error
    ok, confirmed = await _read_cpufreq()
    if not ok:
        return True, {**status, "active": [governor]}
    status = confirmed
    if status["active"] != [governor]:
        return False, f"{action}: write accepted but CPUs report {', '.join(status['active'])}"
    return True, status


def _cpu_settings_snapshot():
    return {
        "restore_on_boot": _settings["cpu_restore_on_boot"],
        "saved_governor": _settings["saved_governor"],
    }


async def _unload_hardware():
    if _guard["active"]:
        await _guard_release("plugin unloading")
    if _alarm["active"]:
        await _alarm_clear("plugin unloading")


class Plugin:
    async def get_fan_target(self):
        async with _fan_lock:
            ok, value = await _guarded_io(
                "Reading fan target", FAN_TARGET_PATH, _read_sysfs, FAN_TARGET_PATH
            )
        if not ok:
            return _fail(value)
        temp = _coerce_int(value)
        if temp is None:
            return _fail(f"Unexpected fan target value: {value!r}")
        return _ok(f"Fan target is {temp} °C", {"temp": temp})

    async def set_fan_target(self, temp):
        target = _coerce_int(temp)
        if target is None:
            return _fail(f"Invalid temperature: {temp!r}")
        if not FAN_SAFE_MIN <= target <= FAN_SAFE_MAX:
            return _fail(
                f"Temperature {target} °C is outside the safe range "
                f"{FAN_SAFE_MIN}-{FAN_SAFE_MAX} °C"
            )

        async with _fan_lock:
            if _guard["active"]:
                _guard["restore_target"] = target
                deferred = True
            else:
                deferred = False
                ok, result = await _write_fan_target_locked("Setting fan target", target)
                if not ok:
                    return _fail(result)

        await _remember_target(target)
        if deferred:
            return _ok(
                f"Thermal guard is cooling. {target} °C will apply once the CPU cools down",
                {"temp": FAN_MAX_COOLING_TARGET},
            )
        return _ok(f"Fan target set to {result} °C", {"temp": result})

    async def get_temperatures(self):
        sensors = await _read_temperatures()
        if not sensors:
            return _fail(f"No temperature sensors found under {HWMON_DIR}")
        return _ok(f"Read {len(sensors)} temperature sensors", {"sensors": sensors}, log=False)

    async def get_fan_status(self):
        async with _fan_lock:
            ok, value = await _guarded_io(
                "Reading fan target", FAN_TARGET_PATH, _read_sysfs, FAN_TARGET_PATH
            )
        target = _coerce_int(value) if ok else None
        target_error = None
        if not ok:
            target_error = value
        elif target is None:
            target_error = f"Unexpected fan target value: {value!r}"

        sensors = await _read_temperatures()
        return _ok(
            "Fan status updated",
            {
                "target": target,
                "target_error": target_error,
                "sensors": sensors,
                "guard": _guard_snapshot(),
            },
            log=False,
        )

    async def get_fan_settings(self):
        return _ok(
            "Fan settings loaded",
            {"settings": dict(_settings), "guard": _guard_snapshot()},
            log=False,
        )

    async def set_fan_settings(
        self, restore_on_boot=None, guard_enabled=None, guard_threshold=None, alarm_enabled=None
    ):
        updates = {}
        if restore_on_boot is not None:
            if not isinstance(restore_on_boot, bool):
                return _fail(f"Invalid restore_on_boot value: {restore_on_boot!r}")
            updates["restore_on_boot"] = restore_on_boot
        if guard_enabled is not None:
            if not isinstance(guard_enabled, bool):
                return _fail(f"Invalid guard_enabled value: {guard_enabled!r}")
            updates["guard_enabled"] = guard_enabled
        if alarm_enabled is not None:
            if not isinstance(alarm_enabled, bool):
                return _fail(f"Invalid alarm_enabled value: {alarm_enabled!r}")
            updates["alarm_enabled"] = alarm_enabled
        if guard_threshold is not None:
            threshold = _coerce_int(guard_threshold)
            if threshold is None or not GUARD_MIN <= threshold <= GUARD_MAX:
                return _fail(
                    f"Guard threshold must be between {GUARD_MIN} and {GUARD_MAX} °C"
                )
            updates["guard_threshold"] = threshold
        if not updates:
            return _fail("No settings provided")

        async with _settings_lock:
            candidate = dict(_settings)
            candidate.update(updates)
            ok, error = await _save_settings(candidate)
            if not ok:
                return _fail(error)
            _settings.update(updates)

        if updates.get("guard_enabled") is False and _guard["active"]:
            await _guard_release("guard disabled")
        if updates.get("alarm_enabled") is False and _alarm["active"]:
            await _alarm_clear("alarm disabled")
        if not (_settings["guard_enabled"] or _settings["alarm_enabled"]):
            _guard["cpu"] = None

        return _ok(
            "Fan settings saved",
            {"settings": dict(_settings), "guard": _guard_snapshot()},
        )

    async def get_led_presets(self):
        async with _led_lock:
            ok, result = await _discover_presets()
        if not ok:
            return _fail(result)
        return _ok(
            f"Found {len(result)} LED presets",
            {"presets": result, "animated": [p for p in result if _is_animated(p)]},
        )

    async def get_led_settings(self):
        return _ok("LED settings loaded", _led_settings_snapshot(), log=False)

    async def set_led_settings(self, loop_enabled=None, loop_seconds=None):
        updates = {}
        if loop_enabled is not None:
            if not isinstance(loop_enabled, bool):
                return _fail(f"Invalid loop_enabled value: {loop_enabled!r}")
            updates["led_loop_enabled"] = loop_enabled
        if loop_seconds is not None:
            seconds = _coerce_int(loop_seconds)
            if seconds is None or not LED_LOOP_MIN <= seconds <= LED_LOOP_MAX:
                return _fail(
                    f"Loop interval must be between {LED_LOOP_MIN} and {LED_LOOP_MAX} seconds"
                )
            updates["led_loop_seconds"] = seconds
        if not updates:
            return _fail("No settings provided")

        async with _settings_lock:
            candidate = dict(_settings)
            candidate.update(updates)
            ok, error = await _save_settings(candidate)
            if not ok:
                return _fail(error)
            _settings.update(updates)

        return _ok("LED settings saved", _led_settings_snapshot())

    async def set_led_preset(self, preset):
        if not isinstance(preset, str) or not LED_PRESET_PATTERN.fullmatch(preset):
            return _fail(f"Invalid preset name: {preset!r}")

        async with _led_lock:
            ok, available = await _discover_presets()
            if not ok:
                return _fail(available)

            if preset in available:
                path = _led_brightness_path(preset)
                value = 1
            elif preset == LED_OFF_PRESET:
                path = _led_brightness_path(available[0])
                value = 0
            else:
                return _fail(f"Preset '{preset}' is not exposed by the kernel")

            ok, error = await _guarded_io(
                f"Applying LED preset '{preset}'", path, _write_sysfs, path, value
            )
            if ok:
                _led["preset"] = preset
                _led["started"] = time.monotonic()
                _led["error_logged"] = False
        if not ok:
            return _fail(error)
        return _ok(f"LED preset '{preset}' applied", {"preset": preset, **_led_settings_snapshot()})

    async def get_cpu_status(self):
        async with _cpu_lock:
            ok, result = await _read_cpufreq()
        if not ok:
            return _fail(result)
        return _ok("CPU status updated", result, log=False)

    async def set_cpu_governor(self, governor):
        if not isinstance(governor, str) or not CPU_GOVERNOR_PATTERN.fullmatch(governor):
            return _fail(f"Invalid governor name: {governor!r}")

        async with _cpu_lock:
            ok, result = await _apply_governor_locked("Setting CPU governor", governor)
        if not ok:
            return _fail(result)

        await _remember_governor(governor)
        return _ok(f"CPU governor set to {governor}", result)

    async def get_cpu_settings(self):
        return _ok("CPU settings loaded", _cpu_settings_snapshot(), log=False)

    async def set_cpu_settings(self, restore_on_boot=None):
        if not isinstance(restore_on_boot, bool):
            return _fail(f"Invalid restore_on_boot value: {restore_on_boot!r}")

        async with _settings_lock:
            candidate = dict(_settings)
            candidate["cpu_restore_on_boot"] = restore_on_boot
            ok, error = await _save_settings(candidate)
            if not ok:
                return _fail(error)
            _settings["cpu_restore_on_boot"] = restore_on_boot

        return _ok("CPU settings saved", _cpu_settings_snapshot())

    async def test_buzzer(self, level):
        value = _coerce_int(level)
        if value not in BUZZER_LEVELS:
            return _fail(f"Invalid buzzer level: {level!r}. Expected 1, 2 or 3")

        async with _buzzer_lock:
            ok, error = await _guarded_io(
                f"{BUZZER_LEVELS[value]} beep",
                BUZZER_BEEP_PATH,
                _write_sysfs,
                BUZZER_BEEP_PATH,
                value,
            )
        if not ok:
            return _fail(error)
        return _ok(f"{BUZZER_LEVELS[value]} beep sent", {"level": value})

    async def stop_buzzer(self):
        async with _buzzer_lock:
            stop_ok, stop_error = await _guarded_io(
                "Stopping buzzer pattern", BUZZER_STOP_PATH, _write_sysfs, BUZZER_STOP_PATH, 1
            )
            silence_ok, silence_error = await _guarded_io(
                "Silencing buzzer", BUZZER_BEEP_PATH, _write_sysfs, BUZZER_BEEP_PATH, BUZZER_SILENT
            )

        if silence_ok:
            if not stop_ok:
                logger.warning(stop_error)
            return _ok("Buzzer stopped")
        if stop_ok:
            return _fail(f"Pattern stopped, but {silence_error}")
        return _fail(f"{stop_error}; {silence_error}")

    async def _main(self):
        global _guard_task, _led_loop_task
        logger.info("PS5 Hardware Control loaded")
        for label, path in (
            ("Fan", FAN_TARGET_PATH),
            ("Temperature sensors", HWMON_DIR),
            ("LED class", LED_CLASS_DIR),
            ("CPU frequency", CPUFREQ_DIR),
            ("Buzzer", BUZZER_DIR),
        ):
            if os.path.exists(path):
                logger.info(f"{label} interface found at {path}")
            else:
                logger.warning(f"{label} interface missing at {path}")

        loaded = await _run_detached(_load_settings_sync)
        async with _settings_lock:
            _settings.update(loaded)

        saved = _settings["saved_target"]
        if _settings["restore_on_boot"] and saved is not None and os.path.exists(FAN_TARGET_PATH):
            async with _fan_lock:
                ok, result = await _write_fan_target_locked("Restoring fan target", saved)
            if ok:
                logger.info(f"Restored fan target to {result} °C")
            else:
                logger.error(result)

        governor = _settings["saved_governor"]
        if _settings["cpu_restore_on_boot"] and governor and os.path.isdir(CPUFREQ_DIR):
            async with _cpu_lock:
                ok, result = await _apply_governor_locked("Restoring CPU governor", governor)
            if ok:
                logger.info(f"Restored CPU governor to {governor}")
            else:
                logger.error(result)

        _guard_task = asyncio.create_task(_guard_loop())
        _led_loop_task = asyncio.create_task(_led_loop())

    async def _unload(self):
        global _guard_task, _led_loop_task
        await _cancel_task(_led_loop_task)
        _led_loop_task = None
        await _cancel_task(_guard_task)
        _guard_task = None

        try:
            await asyncio.wait_for(_unload_hardware(), timeout=UNLOAD_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Hardware cleanup timed out during unload")
        logger.info("PS5 Hardware Control unloaded")
