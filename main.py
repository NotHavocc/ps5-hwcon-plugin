import asyncio
import configparser
import errno
import glob
import gzip
import io
import json
import os
import re
import shutil
import subprocess
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

FAN_HWMON_NAME = "ps5_fan"
FAN_HWMON_DESC = f"the {FAN_HWMON_NAME} hwmon device"
FAN_CURVE_POINTS = 8
FAN_CURVE_TEMP_MAX = 90
FAN_PWM_MAX = 255
FAN_MODE_FULL = 0
FAN_MODE_MANUAL = 1
FAN_MODE_CURVE = 2
FAN_MODE_FIRMWARE = 3

FAN_TARGET_CURVE_OFFSETS = (-12, -8, -5, -2, 0, 2, 4, 6)
FAN_TARGET_CURVE_PERCENT = (10, 15, 22, 32, 45, 60, 80, 100)
FAN_TARGET_CURVE_STOP_GAP = 5

HWMON_DIR = "/sys/class/hwmon"
HWMON_CHIP_PRIORITY = {"k10temp": 0, "ps5_fan": 1, "amdgpu": 2, "nvme": 3}
CPU_SENSOR_CHIP = "k10temp"
SENSOR_LABELS = {
    ("k10temp", "Tctl"): "CPU",
    ("k10temp", "Tdie"): "CPU Die",
    ("amdgpu", "edge"): "GPU",
    ("amdgpu", "junction"): "GPU Junction",
    ("amdgpu", "mem"): "GPU Memory",
    ("nvme", "Composite"): "SSD",
    ("ps5_fan", "MainSoC"): "SoC",
    ("ps5_fan", "Local1"): "Local 1",
    ("ps5_fan", "Local2"): "Local 2",
    ("ps5_fan", "Local3"): "Local 3",
}
SENSOR_PLAUSIBLE_MIN = -20.0
SENSOR_PLAUSIBLE_MAX = 150.0

GUARD_MIN = 80
GUARD_MAX = 100
GUARD_DEFAULT = 95
GUARD_HYSTERESIS = 10
GUARD_POLL_SECONDS = 3.0

BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
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
CLOCK_MHZ_MIN = 1
CLOCK_MHZ_MAX = 10000

DEVFREQ_DIR = "/sys/class/devfreq"
GPU_DEVFREQ_NAME = "ps5-gpufreq"
GPU_DEVFREQ_PATH = f"{DEVFREQ_DIR}/{GPU_DEVFREQ_NAME}"
GPU_KCONFIG_OPTION = "CONFIG_PS5_GPUFREQ"
CU_UNLOCK_PARAM_PATH = "/sys/module/amdgpu/parameters/ps5_cu_unlock"
CU_UNLOCK_ARG = "amdgpu.ps5_cu_unlock"
CU_UNLOCK_ALL = 3
CU_UNLOCK_PATTERN = re.compile(r"(?:^|\s+)amdgpu\.ps5[-_]cu[-_]unlock=(\S*)")
CU_MASK_PARAM_PATH = "/sys/module/amdgpu/parameters/disable_cu"
CU_MASK_ARG = "amdgpu.disable_cu"
CU_MASK_PATTERN = re.compile(r"(?:^|\s+)amdgpu\.disable[-_]cu=(\S*)")
CU_MASK_38 = "0.0.0"
CU_TARGETS = {0: (0, None), 38: (CU_UNLOCK_ALL, CU_MASK_38), 40: (CU_UNLOCK_ALL, None)}
ACTIVE_CU_PATTERN = re.compile(r"active_cu_number (\d+)")

BOOT_MOUNT = "/boot/efi"
BOOT_EFI_MOUNT = "/efi"
BOOT_RUN_MOUNT = "/run/ps5-hwcon/boot"
BOOT_SUBDIRS = ("", "PS5/Linux")
MOUNTS_PATH = "/proc/self/mounts"
BOOT_FILESYSTEMS = ("vfat", "exfat")
BOOT_CMDLINE_MAX = 2047
RUNNING_CMDLINE_PATH = "/proc/cmdline"
VRAM_TOTAL_GLOB = "/sys/class/drm/card[0-9]*/device/mem_info_vram_total"
VRAM_DEFAULT_BYTES = 512 * 1024 * 1024
VRAM_MIN_MB = 256
VRAM_MAX_MB = 12 * 1024
GTT_CHOICES_GB = (10, 12)
GTT_ARG = "ttm.pages_limit"
GTT_PATTERN = re.compile(r"(?:^|\s+)ttm\.pages[-_]limit=(\S*)")
GPU_HIDDEN_GOVERNORS = ("passive",)
MEMINFO_PATH = "/proc/meminfo"
SWAPS_PATH = "/proc/swaps"
PROC_STAT_PATH = "/proc/stat"
ZRAM_DEVICE = "zram0"
ZRAM_BLOCK_DIR = f"/sys/block/{ZRAM_DEVICE}"
ZRAM_CONFIG_PATH = "/etc/systemd/zram-generator.conf"
ZRAM_VENDOR_CONFIG_PATHS = (
    "/usr/lib/systemd/zram-generator.conf",
    "/lib/systemd/zram-generator.conf",
)
ZRAM_GENERATOR_PATHS = (
    "/usr/lib/systemd/system-generators/zram-generator",
    "/lib/systemd/system-generators/zram-generator",
)
ZRAM_SIZES = ("ram / 4", "ram / 2", "ram")
ZRAM_ALGORITHMS = ("zstd", "lz4", "lzo-rle")
ZRAM_DISABLED_CONFIG = (
    "# Written by PS5 Hardware Control: zram is off. This file masks any distro default.\n"
)
ZSWAP_DIR = "/sys/module/zswap/parameters"
ZSWAP_ENABLED_PATH = f"{ZSWAP_DIR}/enabled"
ZSWAP_ARG = "zswap.enabled"
ZSWAP_PATTERN = re.compile(r"(?:^|\s+)zswap\.enabled=(\S*)")
AMDGPU_REFCNT_PATH = "/sys/module/amdgpu/refcnt"
DISPLAY_MANAGER_PATH = "/etc/systemd/system/display-manager.service"
CU_RELOAD_UNIT = "ps5-hwcon-cu-reload"

CU_RELOAD_SCRIPT = """
value="$1"
mask="$2"
previous="$3"
previous_mask="$4"
set_consoles() {
  for console in /sys/class/vtconsole/vtcon*; do
    if grep -q 'frame buffer' "$console/name" 2>/dev/null; then
      echo "$1" >"$console/bind" 2>/dev/null
    fi
  done
}
sleep 2
systemctl stop display-manager.service
sleep 2
set_consoles 0
if timeout 60 modprobe -r amdgpu; then
  if timeout 120 modprobe amdgpu ps5_cu_unlock="$value" disable_cu="$mask"; then
    echo "amdgpu reloaded with ps5_cu_unlock=$value disable_cu=$mask"
  else
    echo "amdgpu failed to load with ps5_cu_unlock=$value disable_cu=$mask, trying $previous"
    timeout 120 modprobe amdgpu ps5_cu_unlock="$previous" disable_cu="$previous_mask"
  fi
else
  echo "amdgpu could not be unloaded, it is probably still in use"
fi
set_consoles 1
systemctl start display-manager.service
"""
GPU_HIDDEN_GOVERNORS = ("passive",)

BUZZER_DIR = "/sys/class/misc/ps5_buzzer"
BUZZER_BEEP_PATH = "/sys/class/misc/ps5_buzzer/beep"
BUZZER_SILENT = 0
BUZZER_ERROR = 2

IO_TIMEOUT_SECONDS = 5.0
UNLOAD_TIMEOUT_SECONDS = 3.0
RESTORE_TIMEOUT_SECONDS = 60.0
RESTORE_RETRY_SECONDS = 2.0
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
    "saved_curve": None,
    "guard_enabled": False,
    "guard_threshold": GUARD_DEFAULT,
    "alarm_enabled": False,
    "led_loop_enabled": False,
    "led_loop_seconds": LED_LOOP_DEFAULT,
    "led_restore_on_boot": False,
    "saved_led_preset": None,
    "saved_led_boot_id": None,
    "cpu_restore_on_boot": False,
    "saved_governor": None,
    "gpu_restore_on_boot": False,
    "saved_gpu_governor": None,
    "saved_cpu_clock": None,
    "saved_gpu_clock": None,
}

_fan_lock = asyncio.Lock()
_led_lock = asyncio.Lock()
_boot_lock = asyncio.Lock()
_cpu_lock = asyncio.Lock()
_gpu_lock = asyncio.Lock()
_buzzer_lock = asyncio.Lock()
_settings_lock = asyncio.Lock()

_settings = dict(DEFAULT_SETTINGS)
_guard = {"active": False, "kind": None, "restore_target": None, "restore_mode": None, "cpu": None}
_alarm = {"active": False}
_led = {"preset": None, "started": 0.0, "error_logged": False}
_guard_task = None
_led_loop_task = None
_restore_task = None
_settings_loaded = False


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


def _sanitize_curve(raw):
    if not isinstance(raw, dict):
        return None, "expected an object"
    points = raw.get("points")
    stop = _coerce_int(raw.get("stop"))
    if not isinstance(points, (list, tuple)) or len(points) != FAN_CURVE_POINTS:
        return None, f"expected {FAN_CURVE_POINTS} points"
    if stop is None:
        return None, "missing stop temperature"
    clean = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None, "each point must be [temperature, pwm]"
        temp, pwm = (_coerce_int(value) for value in point)
        if temp is None or pwm is None:
            return None, "point values must be integers"
        if not 0 <= temp <= FAN_CURVE_TEMP_MAX:
            return None, f"temperatures must be 0-{FAN_CURVE_TEMP_MAX} °C"
        if not 0 <= pwm <= FAN_PWM_MAX:
            return None, f"PWM values must be 0-{FAN_PWM_MAX}"
        clean.append([temp, pwm])
    if not 0 <= stop < clean[0][0]:
        return None, "the stop temperature must be below the first point"
    for (temp_a, pwm_a), (temp_b, pwm_b) in zip(clean, clean[1:]):
        if temp_b <= temp_a:
            return None, "temperatures must increase from point to point"
        if pwm_b < pwm_a:
            return None, "fan speed must not drop as temperature rises"
    if clean[-1][1] != FAN_PWM_MAX:
        return None, "the last point must be full speed"
    return {"points": clean, "stop": stop}, None


def _target_curve(target):
    temps = [target + offset for offset in FAN_TARGET_CURVE_OFFSETS]
    temps[-1] = min(temps[-1], FAN_CURVE_TEMP_MAX)
    for index in range(len(temps) - 2, -1, -1):
        temps[index] = min(temps[index], temps[index + 1] - 1)
    pwms = [round(percent * FAN_PWM_MAX / 100) for percent in FAN_TARGET_CURVE_PERCENT]
    return {
        "points": [[temp, pwm] for temp, pwm in zip(temps, pwms)],
        "stop": temps[0] - FAN_TARGET_CURVE_STOP_GAP,
    }


def _curve_target(curve):
    for target in range(FAN_SAFE_MIN, FAN_SAFE_MAX + 1):
        if _target_curve(target) == curve:
            return target
    return None


def _find_fan_hwmon():
    try:
        entries = sorted(os.listdir(HWMON_DIR))
    except OSError:
        return None
    for entry in entries:
        base = os.path.join(HWMON_DIR, entry)
        try:
            if _read_sysfs(os.path.join(base, "name")) == FAN_HWMON_NAME:
                return base
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _fan_hwmon_dir():
    base = _find_fan_hwmon()
    if base is None:
        raise FileNotFoundError(errno.ENOENT, "No such device", FAN_HWMON_DESC)
    return base


def _read_hwmon_int(base, name):
    raw = _read_sysfs(os.path.join(base, name))
    value = _coerce_int(raw)
    if value is None:
        raise OSError(errno.EPROTO, f"Unexpected value {raw!r} in {name}")
    return value


def _read_fan_hwmon_sync():
    base = _fan_hwmon_dir()
    points = [
        [
            round(_read_hwmon_int(base, f"pwm1_auto_point{i}_temp") / 1000),
            _read_hwmon_int(base, f"pwm1_auto_point{i}_pwm"),
        ]
        for i in range(1, FAN_CURVE_POINTS + 1)
    ]
    stop = round(_read_hwmon_int(base, "pwm1_auto_point1_temp_hyst") / 1000)
    status = {"curve": {"points": points, "stop": stop}, "mode": None, "pwm": None, "temp": None}
    status["mode"] = _read_hwmon_int(base, "pwm1_enable")
    try:
        status["pwm"] = _read_hwmon_int(base, "pwm1")
    except OSError:
        pass
    try:
        status["temp"] = round(_read_hwmon_int(base, "temp1_input") / 1000, 1)
    except OSError:
        pass
    return status


def _curve_writes(curve):
    yield "pwm1_auto_point1_temp_hyst", curve["stop"] * 1000
    for index, (temp, pwm) in enumerate(curve["points"], 1):
        yield f"pwm1_auto_point{index}_temp", temp * 1000
        yield f"pwm1_auto_point{index}_pwm", pwm


def _write_fan_curve_sync(curve):
    base = _fan_hwmon_dir()
    pending = list(_curve_writes(curve))
    while pending:
        rejected = []
        last_error = None
        for name, value in pending:
            try:
                _write_sysfs(os.path.join(base, name), value)
            except OSError as exc:
                if exc.errno != errno.EINVAL:
                    raise
                rejected.append((name, value))
                last_error = exc
        if len(rejected) == len(pending):
            raise last_error
        pending = rejected
    return _read_fan_hwmon_sync()


def _reset_fan_curve_sync():
    _write_sysfs(os.path.join(_fan_hwmon_dir(), "curve_reset"), 1)
    return _read_fan_hwmon_sync()


def _read_fan_mode_sync():
    return _read_hwmon_int(_fan_hwmon_dir(), "pwm1_enable")


def _write_fan_mode_sync(mode):
    _write_sysfs(os.path.join(_fan_hwmon_dir(), "pwm1_enable"), mode)


async def _fan_interface():
    try:
        base = await asyncio.wait_for(_run_detached(_find_fan_hwmon), timeout=IO_TIMEOUT_SECONDS)
    except Exception:
        base = None
    if base is not None:
        return "curve"
    if os.path.exists(FAN_TARGET_PATH):
        return "target"
    return None


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
    settings["saved_curve"], _ = _sanitize_curve(raw.get("saved_curve"))
    settings["led_loop_enabled"] = raw.get("led_loop_enabled") is True
    loop_seconds = _coerce_int(raw.get("led_loop_seconds"))
    if loop_seconds is not None and LED_LOOP_MIN <= loop_seconds <= LED_LOOP_MAX:
        settings["led_loop_seconds"] = loop_seconds
    settings["led_restore_on_boot"] = raw.get("led_restore_on_boot") is True
    led_preset = raw.get("saved_led_preset")
    if isinstance(led_preset, str) and LED_PRESET_PATTERN.fullmatch(led_preset):
        settings["saved_led_preset"] = led_preset
    led_boot_id = raw.get("saved_led_boot_id")
    if isinstance(led_boot_id, str):
        settings["saved_led_boot_id"] = led_boot_id
    settings["cpu_restore_on_boot"] = raw.get("cpu_restore_on_boot") is True
    governor = raw.get("saved_governor")
    if isinstance(governor, str) and CPU_GOVERNOR_PATTERN.fullmatch(governor):
        settings["saved_governor"] = governor
    settings["gpu_restore_on_boot"] = raw.get("gpu_restore_on_boot") is True
    gpu_governor = raw.get("saved_gpu_governor")
    if isinstance(gpu_governor, str) and CPU_GOVERNOR_PATTERN.fullmatch(gpu_governor):
        settings["saved_gpu_governor"] = gpu_governor
    for key in ("saved_cpu_clock", "saved_gpu_clock"):
        clock = _coerce_int(raw.get(key))
        if clock is not None and CLOCK_MHZ_MIN <= clock <= CLOCK_MHZ_MAX:
            settings[key] = clock
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


async def _ensure_settings():
    global _settings_loaded
    async with _settings_lock:
        if not _settings_loaded:
            _settings.update(await _run_detached(_load_settings_sync))
            _settings_loaded = True


async def _remember_setting(key, value):
    await _ensure_settings()
    async with _settings_lock:
        if _settings[key] == value:
            return
        _settings[key] = value
        ok, error = await _save_settings(dict(_settings))
    if not ok:
        logger.warning(error)


def _guard_snapshot():
    return {
        "enabled": _settings["guard_enabled"],
        "active": _guard["active"],
        "threshold": _settings["guard_threshold"],
        "kind": _guard["kind"],
        "restore_target": _guard["restore_target"],
        "restore_mode": _guard["restore_mode"],
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


async def _set_fan_mode_locked(action, mode):
    if _guard["active"] and _guard["kind"] == "curve":
        _guard["restore_mode"] = mode
        return True, True
    ok, error = await _guarded_io(action, FAN_HWMON_DESC, _write_fan_mode_sync, mode)
    return ok, (False if ok else error)


async def _guard_engage_curve(cpu):
    async with _fan_lock:
        if _guard["active"]:
            return
        ok, current = await _guarded_io("Reading fan mode", FAN_HWMON_DESC, _read_fan_mode_sync)
        previous = current if ok else None
        ok, error = await _guarded_io(
            "Engaging thermal guard", FAN_HWMON_DESC, _write_fan_mode_sync, FAN_MODE_FULL
        )
        if not ok:
            logger.error(error)
            return
        _guard["active"] = True
        _guard["kind"] = "curve"
        _guard["restore_mode"] = previous if previous is not None else FAN_MODE_CURVE
    logger.warning(f"Thermal guard engaged at CPU {cpu:.1f} °C: fan at full speed")


async def _guard_engage(cpu):
    if await _fan_interface() == "curve":
        await _guard_engage_curve(cpu)
        return
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
        _guard["kind"] = "target"
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
        if _guard["kind"] == "curve":
            mode = _guard["restore_mode"]
            if mode is None:
                mode = FAN_MODE_CURVE
            ok, error = await _guarded_io(
                "Releasing thermal guard", FAN_HWMON_DESC, _write_fan_mode_sync, mode
            )
            if not ok:
                logger.error(error)
                return
            _guard["active"] = False
            _guard["kind"] = None
            _guard["restore_mode"] = None
            logger.info(f"Thermal guard released ({reason}): fan mode {mode}")
            return
        target = _guard["restore_target"] or _settings["saved_target"] or FAN_BOOT_TARGET
        ok, result = await _write_fan_target_locked("Releasing thermal guard", target)
        if not ok:
            logger.error(result)
            return
        _guard["active"] = False
        _guard["kind"] = None
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


def _current_boot_id():
    try:
        return _read_sysfs(BOOT_ID_PATH)
    except (OSError, UnicodeDecodeError):
        return None


async def _remember_led_preset(preset):
    await _remember_setting("saved_led_preset", preset)
    await _remember_setting("saved_led_boot_id", _current_boot_id())


def _resume_led_preset():
    boot_id = _current_boot_id()
    if boot_id and boot_id == _settings["saved_led_boot_id"]:
        _led["preset"] = _settings["saved_led_preset"]


def _led_settings_snapshot():
    return {
        "loop_enabled": _settings["led_loop_enabled"],
        "loop_seconds": _settings["led_loop_seconds"],
        "preset": _led["preset"],
        "looping": _settings["led_loop_enabled"] and _is_animated(_led["preset"]),
        "restore_on_boot": _settings["led_restore_on_boot"],
        "saved_preset": _settings["saved_led_preset"],
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


async def _apply_led_preset_locked(action, preset):
    ok, available = await _discover_presets()
    if not ok:
        return False, available

    if preset in available:
        path = _led_brightness_path(preset)
        value = 1
    elif preset == LED_OFF_PRESET:
        path = _led_brightness_path(available[0])
        value = 0
    else:
        return False, f"Preset '{preset}' is not exposed by the kernel"

    ok, error = await _guarded_io(f"{action} '{preset}'", path, _write_sysfs, path, value)
    if not ok:
        return False, error
    _led["preset"] = preset
    _led["started"] = time.monotonic()
    _led["error_logged"] = False
    return True, None


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


def _nearest(value, choices):
    return min(choices, key=lambda choice: (abs(choice - value), choice)) if choices else value


def _scan_cpufreq():
    governors = None
    available = None
    active = []
    drivers = []
    current = []
    hw_min = []
    hw_max = []
    limits = []
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
        limits.append(
            (_read_policy_mhz(base, "scaling_min_freq"), _read_policy_mhz(base, "scaling_max_freq"))
        )
        listed = (_read_policy_value(base, "scaling_available_frequencies") or "").split()
        steps = {round(khz / 1000) for khz in map(_coerce_int, listed) if khz is not None and khz > 0}
        available = steps if available is None else available & steps

    hw_range = (min(hw_min), max(hw_max)) if hw_min and hw_max else None
    locked = None
    if hw_range and hw_range[0] != hw_range[1] and len(set(limits)) == 1:
        low, high = limits[0]
        if low is not None and low == high:
            locked = low

    return {
        "driver": ", ".join(drivers) or None,
        "governors": [g for g in governors or [] if CPU_GOVERNOR_PATTERN.fullmatch(g)],
        "active": active,
        "policy_count": len(policies),
        "freq_avg_mhz": round(sum(current) / len(current)) if current else None,
        "freq_peak_mhz": max(current) if current else None,
        "hw_min_mhz": min(hw_min) if hw_min else None,
        "hw_max_mhz": max(hw_max) if hw_max else None,
        "available_mhz": sorted(available or []),
        "limit_min_mhz": min((low for low, _ in limits if low is not None), default=None),
        "limit_max_mhz": max((high for _, high in limits if high is not None), default=None),
        "locked_mhz": locked,
    }


def _write_cpu_clock_sync(mhz):
    failures = []
    for base in _cpu_policy_dirs():
        hw_min = _read_sysfs(os.path.join(base, "cpuinfo_min_freq"))
        hw_max = _read_sysfs(os.path.join(base, "cpuinfo_max_freq"))
        if mhz is None:
            writes = (("scaling_min_freq", hw_min), ("scaling_max_freq", hw_max))
        else:
            khz = mhz * 1000
            writes = (("scaling_min_freq", hw_min), ("scaling_max_freq", khz), ("scaling_min_freq", khz))
        try:
            for name, value in writes:
                _write_sysfs(os.path.join(base, name), value)
        except OSError as exc:
            failures.append(exc)
    if failures:
        raise failures[0]


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


async def _apply_cpu_clock_locked(action, mhz):
    ok, status = await _read_cpufreq()
    if not ok:
        return False, status
    if mhz is not None:
        low, high = status["hw_min_mhz"], status["hw_max_mhz"]
        if low is None or high is None:
            return False, f"{action} failed: the CPU does not report its clock range"
        if not low <= mhz <= high:
            return False, f"{mhz} MHz is outside the CPU range {low}-{high} MHz"
        mhz = _nearest(mhz, status["available_mhz"])

    ok, error = await _guarded_io(action, CPUFREQ_DIR, _write_cpu_clock_sync, mhz)
    if not ok:
        return False, error
    ok, confirmed = await _read_cpufreq()
    if not ok:
        return True, {**status, "locked_mhz": mhz}
    if mhz is not None and confirmed["locked_mhz"] is None:
        return False, (
            f"{action}: write accepted but CPUs report "
            f"{confirmed['limit_min_mhz']}-{confirmed['limit_max_mhz']} MHz"
        )
    return True, confirmed


def _read_devfreq_mhz(base, name):
    hz = _coerce_int(_read_policy_value(base, name))
    return round(hz / 1_000_000) if hz is not None and hz > 0 else None


def _scan_gpufreq():
    base = GPU_DEVFREQ_PATH
    if not os.path.isdir(base):
        raise FileNotFoundError(errno.ENOENT, "No such device", base)
    names = (_read_policy_value(base, "available_governors") or "").split()
    listed = (_read_policy_value(base, "available_frequencies") or "").split()
    available = sorted(
        {round(hz / 1_000_000) for hz in map(_coerce_int, listed) if hz is not None and hz > 0}
    )
    min_mhz = _read_devfreq_mhz(base, "min_freq")
    max_mhz = _read_devfreq_mhz(base, "max_freq")
    locked = min_mhz if len(available) > 1 and min_mhz is not None and min_mhz == max_mhz else None
    return {
        "device": GPU_DEVFREQ_NAME,
        "governors": [
            g
            for g in names
            if CPU_GOVERNOR_PATTERN.fullmatch(g) and g not in GPU_HIDDEN_GOVERNORS
        ],
        "active": _read_policy_value(base, "governor"),
        "freq_mhz": _read_devfreq_mhz(base, "cur_freq"),
        "target_mhz": _read_devfreq_mhz(base, "target_freq"),
        "min_mhz": min_mhz,
        "max_mhz": max_mhz,
        "available_mhz": available,
        "hw_min_mhz": available[0] if available else None,
        "hw_max_mhz": available[-1] if available else None,
        "locked_mhz": locked,
    }


def _write_gpu_governor_sync(governor):
    _write_sysfs(os.path.join(GPU_DEVFREQ_PATH, "governor"), governor)


def _write_gpu_clock_sync(mhz):
    min_path = os.path.join(GPU_DEVFREQ_PATH, "min_freq")
    max_path = os.path.join(GPU_DEVFREQ_PATH, "max_freq")
    if mhz is None:
        writes = ((min_path, 0), (max_path, 0))
    else:
        hz = mhz * 1_000_000
        writes = ((min_path, 0), (max_path, hz), (min_path, hz))
    for path, value in writes:
        _write_sysfs(path, value)


def _kernel_config_paths():
    release = os.uname().release
    return (
        "/proc/config.gz",
        f"/boot/config-{release}",
        f"/usr/lib/modules/{release}/config",
        f"/lib/modules/{release}/config",
    )


def _read_kernel_option_sync(option):
    prefix = f"{option}="
    unset = f"# {option} is not set"
    for path in _kernel_config_paths():
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith(prefix):
                        return line[len(prefix) :].strip('"')
                    if line == unset:
                        return "n"
        except (OSError, EOFError):
            continue
        return "n"
    return None


async def _describe_missing_gpufreq():
    try:
        value = await asyncio.wait_for(
            _run_detached(_read_kernel_option_sync, GPU_KCONFIG_OPTION),
            timeout=IO_TIMEOUT_SECONDS,
        )
    except Exception:
        value = None
    if value == "n":
        return (
            f"This kernel was built without {GPU_KCONFIG_OPTION}, "
            "so GPU governors and clock locks aren't available."
        )
    if value == "m":
        return (
            f"{GPU_KCONFIG_OPTION} is a module, but {GPU_DEVFREQ_NAME} is not registered. "
            "Is the module loaded?"
        )
    if value == "y":
        return (
            f"{GPU_KCONFIG_OPTION} is built in, but {GPU_DEVFREQ_NAME} is not registered. "
            "Check dmesg for probe errors."
        )
    return f"{GPU_DEVFREQ_PATH} does not exist. Is the kernel built with {GPU_KCONFIG_OPTION}?"


BOOT_FILES_MISSING = "The boot partition wasn't found. Mount it at /boot/efi and try again."
_boot_problem = None


def _boot_missing():
    if _boot_problem:
        return f"The boot partition wasn't found. {_boot_problem}"
    return BOOT_FILES_MISSING


def _boot_file_in(mount, name):
    for subdir in BOOT_SUBDIRS:
        path = os.path.join(mount, subdir, name)
        if os.path.isfile(path):
            return path
    return None


def _run_command(*args):
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=IO_TIMEOUT_SECONDS,
            env=_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _command_ok(*args):
    result = _run_command(*args)
    return result is not None and result.returncode == 0


def _command_error(result, name):
    if result is None:
        return f"{name} couldn't be run."
    return f"{name} failed: {result.stderr.strip() or f'exit code {result.returncode}'}."


def _root_argument(line):
    match = re.search(r"(?:^|\s)root=(\S+)", line)
    return match.group(1) if match else None


def _running_root():
    try:
        return _root_argument(_read_sysfs(RUNNING_CMDLINE_PATH))
    except (OSError, UnicodeDecodeError):
        return None


def _cmdline_root(mount):
    path = _boot_file_in(mount, "cmdline.txt")
    try:
        return _root_argument(_split_cmdline(_read_cmdline_sync(path))[0])
    except OSError:
        return None

def _fat_mounts():
    mounts = [BOOT_MOUNT, BOOT_EFI_MOUNT]
    try:
        with open(MOUNTS_PATH, encoding="utf-8", errors="replace") as handle:
            rows = [row.split() for row in handle]
    except OSError:
        return mounts
    for row in rows:
        if len(row) >= 3 and row[2] in BOOT_FILESYSTEMS:
            mounts.append(_unescape_octal(row[1]))
    return mounts

def _boot_mount():
    mounts = [mount for mount in _fat_mounts() if _boot_file_in(mount, "cmdline.txt")]
    root = _running_root()
    matching = [mount for mount in mounts if _cmdline_root(mount) == root]
    return (matching or mounts or [None])[0]


def _boot_file(name):
    mount = _boot_mount()
    return _boot_file_in(mount, name) if mount else None


def _boot_partitions(problems):
    result = _run_command("lsblk", "-rpno", "NAME,FSTYPE")
    if result is None or result.returncode != 0:
        problems.append(_command_error(result, "lsblk"))
        return []
    rows = (row.split() for row in result.stdout.splitlines())
    return [row[0] for row in rows if len(row) == 2 and row[1] in BOOT_FILESYSTEMS]


def _boot_mount_target():
    for path in (BOOT_MOUNT, BOOT_RUN_MOUNT):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            continue
        if not os.path.ismount(os.path.realpath(path)):
            return path
    return None


def _probe_boot_partition(device, target, roots, problems):
    result = _run_command("mount", "-o", "ro", device, target)
    if result is None or result.returncode != 0:
        problems.append(_command_error(result, f"Mounting {device}"))
        return
    try:
        if _boot_file_in(target, "cmdline.txt"):
            roots[device] = _cmdline_root(target)
        else:
            problems.append(f"{device} has no cmdline.txt.")
    finally:
        _command_ok("umount", target)


def _ensure_boot_mounted_sync():
    global _boot_problem
    _boot_problem = None
    root = _running_root()
    found = _boot_mount()
    if found and _cmdline_root(found) == root:
        return
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        if not found:
            _boot_problem = "Looking for it needs root."
        return
    if not os.path.ismount(os.path.realpath(BOOT_MOUNT)):
        _command_ok("mount", BOOT_MOUNT)
        found = _boot_mount()
        if found and _cmdline_root(found) == root:
            return

    target = _boot_mount_target()
    if target is None:
        _boot_problem = f"Nowhere to mount it: {BOOT_MOUNT} and {BOOT_RUN_MOUNT} are in use."
        return
    problems = []
    partitions = _boot_partitions(problems)
    roots = {}
    for device in partitions:
        _probe_boot_partition(device, target, roots, problems)
    matching = [device for device, value in roots.items() if value == root]
    if found and not matching:
        return
    choices = matching or list(roots)
    if len(choices) == 1:
        result = _run_command("mount", "-o", "ro", choices[0], target)
        if result is None or result.returncode != 0:
            _boot_problem = _command_error(result, f"Mounting {choices[0]}")
    elif choices:
        logger.warning(f"Not mounting a boot partition, several could match: {choices}")
        _boot_problem = f"Several partitions could be it: {', '.join(choices)}."
    elif problems:
        _boot_problem = " ".join(problems)
    elif not partitions:
        _boot_problem = "No FAT partition is connected. Is the boot USB drive plugged in?"


async def _ensure_boot_mounted():
    try:
        await _run_detached(_ensure_boot_mounted_sync)
    except Exception as exc:
        logger.warning(f"Mounting the boot partition failed: {exc}")


def _with_writable_boot(func, *args):
    mount = _boot_mount()
    read_only = bool(os.statvfs(mount).f_flag & os.ST_RDONLY)
    if read_only and not _command_ok("mount", "-o", "remount,rw", mount):
        return f"{mount} couldn't be made writable"
    try:
        return func(*args)
    finally:
        if read_only and not _command_ok("mount", "-o", "remount,ro", mount):
            logger.warning(f"{mount} couldn't be made read-only again")


def _split_cmdline(text):
    match = re.search(r"[\r\n]", text)
    end = match.start() if match else len(text)
    return text[:end], text[end:]


def _read_cmdline_sync(path):
    with open(path, "rb") as handle:
        return handle.read().decode("latin-1")


def _write_file_synced(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_file_sync(path, data, backup=None):
    if backup is not None:
        _write_file_synced(f"{path}.bak", backup)
    temporary = f"{path}.tmp"
    _write_file_synced(temporary, data)
    os.replace(temporary, path)
    directory = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _set_cmdline_args_sync(path, changes):
    original = _read_cmdline_sync(path)
    line, rest = _split_cmdline(original)
    if not line.strip():
        return f"{path} has no kernel command line on its first line"
    updated = line
    for pattern, argument in changes:
        updated = pattern.sub("", updated).strip()
        if argument:
            updated = f"{updated} {argument}"
    if len(updated) > BOOT_CMDLINE_MAX:
        return f"{path} would exceed the loader's {BOOT_CMDLINE_MAX} character limit"
    if updated == line:
        return None
    _replace_file_sync(path, (updated + rest).encode("latin-1"), original.encode("latin-1"))
    return None


def _parse_vram(text):
    match = re.match(r"\s*(?:0[xX])?([0-9a-fA-F]+)", text)
    return (int(match.group(1), 16) if match else 0) or VRAM_DEFAULT_BYTES


def _write_vram_sync(path, size):
    original = None
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            original = handle.read()
    data = f"{size:x}\n".encode("ascii")
    if data != original:
        _replace_file_sync(path, data, original)


def _cmdline_pages(line):
    values = GTT_PATTERN.findall(line)
    return _coerce_int(values[-1]) if values else None


def _read_running_vram():
    for path in sorted(glob.glob(VRAM_TOTAL_GLOB)):
        try:
            return _coerce_int(_read_sysfs(path))
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _read_gpu_memory_sync():
    cmdline_path = _boot_file("cmdline.txt")
    vram_path = _boot_file("vram.txt")
    vram = VRAM_DEFAULT_BYTES
    if vram_path is not None:
        vram = _parse_vram(_read_sysfs(vram_path))
    gtt_pages = None
    if cmdline_path is not None:
        gtt_pages = _cmdline_pages(_split_cmdline(_read_cmdline_sync(cmdline_path))[0])
    try:
        booted_pages = _cmdline_pages(_read_sysfs(RUNNING_CMDLINE_PATH))
    except (OSError, UnicodeDecodeError):
        booted_pages = gtt_pages
    return {
        "boot_ready": cmdline_path is not None,
        "boot_error": None if cmdline_path else _boot_missing(),
        "vram_running": _read_running_vram(),
        "vram_configured": vram,
        "gtt_pages": gtt_pages,
        "gtt_pending": gtt_pages != booted_pages,
    }


def _format_megabytes(megabytes):
    return f"{megabytes / 1024:g} GB" if megabytes >= 1024 else f"{megabytes} MB"


def _unescape_octal(text):
    return re.sub(r"\\(\d{3})", lambda code: chr(int(code.group(1), 8)), text)


def _kernel_bool(value):
    return value.strip().lower() in ("1", "y", "yes", "on", "true")


def _read_meminfo():
    values = {}
    with open(MEMINFO_PATH, encoding="ascii", errors="replace") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields and fields[0].isdigit():
                values[key] = int(fields[0]) * 1024
    return values


def _read_swaps():
    with open(SWAPS_PATH, encoding="utf-8", errors="replace") as handle:
        rows = [row.split() for row in handle.read().splitlines()[1:]]
    return [
        {
            "name": _unescape_octal(row[0]),
            "type": row[1],
            "size": int(row[2]) * 1024,
            "used": int(row[3]) * 1024,
        }
        for row in rows
        if len(row) >= 4 and row[2].isdigit() and row[3].isdigit()
    ]


def _read_zram_running():
    if not os.path.isdir(ZRAM_BLOCK_DIR):
        return None
    algorithms = _read_sysfs(f"{ZRAM_BLOCK_DIR}/comp_algorithm").split()
    selected = next((name.strip("[]") for name in algorithms if name.startswith("[")), None)
    stats = _read_sysfs(f"{ZRAM_BLOCK_DIR}/mm_stat").split()
    return {
        "disksize": _coerce_int(_read_sysfs(f"{ZRAM_BLOCK_DIR}/disksize")) or 0,
        "algorithm": selected,
        "original": _coerce_int(stats[0]) if stats else None,
        "compressed": _coerce_int(stats[1]) if len(stats) > 1 else None,
    }


def _read_zswap_running():
    if not os.path.isdir(ZSWAP_DIR):
        return None

    def parameter(name):
        try:
            return _read_sysfs(f"{ZSWAP_DIR}/{name}")
        except OSError:
            return None

    return {
        "enabled": _kernel_bool(parameter("enabled") or ""),
        "compressor": parameter("compressor"),
        "max_pool_percent": _coerce_int(parameter("max_pool_percent") or ""),
    }


def _zram_swap_active(swaps):
    return any(os.path.basename(swap["name"]) == ZRAM_DEVICE for swap in swaps)


def _read_memory_status_sync():
    meminfo = _read_meminfo()
    swaps = _read_swaps()
    return {
        "ram_total": meminfo.get("MemTotal"),
        "ram_available": meminfo.get("MemAvailable"),
        "swap_total": meminfo.get("SwapTotal"),
        "swap_free": meminfo.get("SwapFree"),
        "swaps": swaps,
        "zram": _read_zram_running() if _zram_swap_active(swaps) else None,
        "zswap": _read_zswap_running(),
    }


def _changed_since_boot(path):
    try:
        with open(PROC_STAT_PATH, encoding="ascii", errors="replace") as handle:
            booted = next(int(line.split()[1]) for line in handle if line.startswith("btime "))
        return os.path.getmtime(path) > booted
    except (OSError, StopIteration, ValueError, IndexError):
        return False


def _zram_vendor_config():
    return next((path for path in ZRAM_VENDOR_CONFIG_PATHS if os.path.isfile(path)), None)


def _load_zram_config(path):
    parser = configparser.ConfigParser(interpolation=None)
    if path is not None:
        with open(path, encoding="utf-8", errors="replace") as handle:
            parser.read_string(handle.read(), source=path)
    return parser


def _read_swap_settings_sync():
    source = ZRAM_CONFIG_PATH if os.path.isfile(ZRAM_CONFIG_PATH) else _zram_vendor_config()
    zram_error = None
    try:
        config = _load_zram_config(source)
    except configparser.Error as exc:
        config = configparser.ConfigParser(interpolation=None)
        zram_error = f"{source} couldn't be parsed: {exc}"
    section = config[ZRAM_DEVICE] if config.has_section(ZRAM_DEVICE) else None
    algorithm = section.get("compression-algorithm") if section else None
    swaps = _read_swaps()
    running = _read_zram_running() if _zram_swap_active(swaps) else None

    cmdline_path = _boot_file("cmdline.txt")
    zswap_configured = None
    if cmdline_path is not None:
        values = ZSWAP_PATTERN.findall(_split_cmdline(_read_cmdline_sync(cmdline_path))[0])
        zswap_configured = _kernel_bool(values[-1]) if values else None
    configured_algorithm = algorithm.split()[0] if algorithm else None
    return {
        "zram_generator": any(os.path.isfile(path) for path in ZRAM_GENERATOR_PATHS),
        "zram_source": source,
        "zram_error": zram_error,
        "zram_enabled": section is not None,
        "zram_size": section.get("zram-size") if section else None,
        "zram_algorithm": configured_algorithm,
        "zram_pending": (section is not None) != (running is not None)
        or (source == ZRAM_CONFIG_PATH and _changed_since_boot(source))
        or bool(
            running
            and configured_algorithm
            and running["algorithm"]
            and configured_algorithm != running["algorithm"]
        ),
        "zswap_configured": zswap_configured,
        "boot_ready": cmdline_path is not None,
        "boot_error": None if cmdline_path else _boot_missing(),
    }


def _write_zram_config_sync(enabled, size, algorithm):
    original = None
    if os.path.isfile(ZRAM_CONFIG_PATH):
        with open(ZRAM_CONFIG_PATH, "rb") as handle:
            original = handle.read()
    if enabled:
        config = _load_zram_config(ZRAM_CONFIG_PATH if original else _zram_vendor_config())
        if not config.has_section(ZRAM_DEVICE):
            config.add_section(ZRAM_DEVICE)
        config[ZRAM_DEVICE]["zram-size"] = size
        config[ZRAM_DEVICE]["compression-algorithm"] = algorithm
        buffer = io.StringIO()
        buffer.write("# Written by PS5 Hardware Control\n")
        config.write(buffer)
        data = buffer.getvalue()
    else:
        data = ZRAM_DISABLED_CONFIG
    if data.encode("utf-8") == original:
        return
    os.makedirs(os.path.dirname(ZRAM_CONFIG_PATH), exist_ok=True)
    _replace_file_sync(ZRAM_CONFIG_PATH, data.encode("utf-8"), original)


def _read_active_cus():
    result = _run_command("dmesg")
    if result is None:
        return None
    counts = ACTIVE_CU_PATTERN.findall(result.stdout)
    return int(counts[-1]) if counts else None


def _cu_reload_blocker():
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return "Reloading the GPU driver needs root."
    if not os.path.exists(AMDGPU_REFCNT_PATH):
        return "amdgpu is built into this kernel, so it can't be reloaded."
    if shutil.which("systemd-run") is None:
        return "Reloading the GPU driver needs systemd."
    if not os.path.exists(DISPLAY_MANAGER_PATH):
        return "No display manager was found, so the display couldn't be restarted safely."
    return None


def _start_cu_reload_sync(value, mask, previous, previous_mask):
    result = subprocess.run(
        [
            "systemd-run",
            f"--unit={CU_RELOAD_UNIT}",
            "--collect",
            "--quiet",
            "/bin/sh",
            "-c",
            CU_RELOAD_SCRIPT,
            "sh",
            str(value),
            mask or "",
            str(previous),
            previous_mask or "",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=IO_TIMEOUT_SECONDS,
        env=_subprocess_env(),
    )
    if result.returncode != 0:
        return f"Starting the GPU driver reload failed: {result.stderr.strip()}"
    return None


def _read_running_cu_mask():
    try:
        mask = _read_sysfs(CU_MASK_PARAM_PATH)
    except (OSError, UnicodeDecodeError):
        return None
    return None if mask in ("", "(null)") else mask


def _cu_target(mode, mask):
    for target, wanted in CU_TARGETS.items():
        if (mode, mask) == wanted:
            return target
    return None


def _read_cu_unlock_sync():
    try:
        running = _coerce_int(_read_sysfs(CU_UNLOCK_PARAM_PATH))
    except (OSError, UnicodeDecodeError):
        running = None
    running_mask = _read_running_cu_mask()
    path = _boot_file("cmdline.txt")
    configured = None
    configured_mask = None
    if path is not None:
        line, _rest = _split_cmdline(_read_cmdline_sync(path))
        values = CU_UNLOCK_PATTERN.findall(line)
        configured = (_coerce_int(values[-1]) if values else 0) or 0
        masks = CU_MASK_PATTERN.findall(line)
        configured_mask = (masks[-1] if masks else None) or None
    return {
        "running": running,
        "running_mask": running_mask,
        "running_target": _cu_target(running, running_mask),
        "configured": configured,
        "configured_mask": configured_mask,
        "configured_target": _cu_target(configured, configured_mask),
        "pending": (configured, configured_mask) != (running, running_mask),
        "cmdline_path": path,
        "boot_error": None if path else _boot_missing(),
        "active_cus": _read_active_cus(),
        "reload_blocker": _cu_reload_blocker(),
    }


async def _read_gpufreq():
    if not os.path.isdir(GPU_DEVFREQ_PATH):
        return False, await _describe_missing_gpufreq()
    ok, result = await _guarded_io("Reading GPU frequency", GPU_DEVFREQ_PATH, _scan_gpufreq)
    if ok and not result["governors"]:
        return False, f"{GPU_DEVFREQ_NAME} exposes no governors"
    return ok, result


async def _apply_gpu_governor_locked(action, governor):
    ok, status = await _read_gpufreq()
    if not ok:
        return False, status
    if governor not in status["governors"]:
        available = ", ".join(status["governors"])
        return False, f"GPU governor '{governor}' is not available. The kernel offers: {available}"

    ok, error = await _guarded_io(action, GPU_DEVFREQ_PATH, _write_gpu_governor_sync, governor)
    if not ok:
        return False, error
    ok, confirmed = await _read_gpufreq()
    if not ok:
        return True, {**status, "active": governor}
    if confirmed["active"] != governor:
        return False, f"{action}: write accepted but the GPU reports {confirmed['active']}"
    return True, confirmed


async def _apply_gpu_clock_locked(action, mhz):
    ok, status = await _read_gpufreq()
    if not ok:
        return False, status
    if mhz is not None:
        if not status["available_mhz"]:
            return False, f"{GPU_DEVFREQ_NAME} does not list its available frequencies"
        low, high = status["hw_min_mhz"], status["hw_max_mhz"]
        if not low <= mhz <= high:
            return False, f"{mhz} MHz is outside the GPU range {low}-{high} MHz"
        mhz = _nearest(mhz, status["available_mhz"])

    ok, error = await _guarded_io(action, GPU_DEVFREQ_PATH, _write_gpu_clock_sync, mhz)
    if not ok:
        return False, error
    ok, confirmed = await _read_gpufreq()
    if not ok:
        return True, {**status, "locked_mhz": mhz}
    if mhz is not None and confirmed["locked_mhz"] != mhz:
        return False, (
            f"{action}: write accepted but the GPU reports "
            f"{confirmed['min_mhz']}-{confirmed['max_mhz']} MHz"
        )
    return True, confirmed


def _gpu_settings_snapshot():
    return {
        "restore_on_boot": _settings["gpu_restore_on_boot"],
        "saved_governor": _settings["saved_gpu_governor"],
        "saved_clock": _settings["saved_gpu_clock"],
    }


def _cpu_settings_snapshot():
    return {
        "restore_on_boot": _settings["cpu_restore_on_boot"],
        "saved_governor": _settings["saved_governor"],
        "saved_clock": _settings["saved_cpu_clock"],
    }


async def _unload_hardware():
    if _guard["active"]:
        await _guard_release("plugin unloading")
    if _alarm["active"]:
        await _alarm_clear("plugin unloading")


async def _restore_fan():
    target = _settings["saved_target"]
    curve = _settings["saved_curve"]
    if not _settings["restore_on_boot"] or (target is None and curve is None):
        return True, None
    interface = await _fan_interface()
    if interface == "curve":
        if curve is None:
            curve = _target_curve(target)
        async with _fan_lock:
            ok, result = await _guarded_io(
                "Restoring fan curve", FAN_HWMON_DESC, _write_fan_curve_sync, curve
            )
            if ok:
                ok, result = await _set_fan_mode_locked("Switching fan to curve mode", FAN_MODE_CURVE)
        if not ok:
            return False, result
        restored = _curve_target(curve)
        return True, f"Restored fan target {restored} °C" if restored else "Restored fan curve"
    if interface == "target":
        if target is None:
            return True, "Saved fan curve skipped: this kernel only takes a target temperature"
        async with _fan_lock:
            if _guard["active"]:
                _guard["restore_target"] = target
                return True, f"Fan target {target} °C will apply once Thermal Guard releases the fan"
            ok, result = await _write_fan_target_locked("Restoring fan target", target)
        return (True, f"Restored fan target to {result} °C") if ok else (False, result)
    return False, f"Fan interface missing ({FAN_HWMON_DESC} or {FAN_TARGET_PATH})"


async def _restore_cpu_governor():
    governor = _settings["saved_governor"]
    if not _settings["cpu_restore_on_boot"] or not governor:
        return True, None
    if not os.path.isdir(CPUFREQ_DIR):
        return False, f"CPU frequency interface missing at {CPUFREQ_DIR}"
    async with _cpu_lock:
        ok, result = await _apply_governor_locked("Restoring CPU governor", governor)
    return (True, f"Restored CPU governor to {governor}") if ok else (False, result)


async def _restore_cpu_clock():
    clock = _settings["saved_cpu_clock"]
    if not _settings["cpu_restore_on_boot"] or not clock:
        return True, None
    if not os.path.isdir(CPUFREQ_DIR):
        return False, f"CPU frequency interface missing at {CPUFREQ_DIR}"
    async with _cpu_lock:
        ok, result = await _apply_cpu_clock_locked("Restoring CPU clock", clock)
    if not ok:
        return False, result
    return True, f"Restored CPU clock lock at {result['locked_mhz']} MHz"


async def _restore_gpu_governor():
    governor = _settings["saved_gpu_governor"]
    if not _settings["gpu_restore_on_boot"] or not governor:
        return True, None
    if not os.path.isdir(GPU_DEVFREQ_PATH):
        return False, await _describe_missing_gpufreq()
    async with _gpu_lock:
        ok, result = await _apply_gpu_governor_locked("Restoring GPU governor", governor)
    return (True, f"Restored GPU governor to {governor}") if ok else (False, result)


async def _restore_gpu_clock():
    clock = _settings["saved_gpu_clock"]
    if not _settings["gpu_restore_on_boot"] or not clock:
        return True, None
    if not os.path.isdir(GPU_DEVFREQ_PATH):
        return False, await _describe_missing_gpufreq()
    async with _gpu_lock:
        ok, result = await _apply_gpu_clock_locked("Restoring GPU clock", clock)
    if not ok:
        return False, result
    return True, f"Restored GPU clock lock at {result['locked_mhz']} MHz"


async def _restore_led():
    preset = _settings["saved_led_preset"]
    if not _settings["led_restore_on_boot"] or not preset:
        return True, None
    if not os.path.isdir(LED_CLASS_DIR):
        return False, f"LED class interface missing at {LED_CLASS_DIR}"
    async with _led_lock:
        ok, error = await _apply_led_preset_locked("Restoring LED preset", preset)
    if not ok:
        return False, error
    await _remember_led_preset(preset)
    return True, f"Restored LED preset '{preset}'"


_RESTORES = (
    ("fan", _restore_fan),
    ("CPU governor", _restore_cpu_governor),
    ("CPU clock", _restore_cpu_clock),
    ("GPU governor", _restore_gpu_governor),
    ("GPU clock", _restore_gpu_clock),
    ("LED preset", _restore_led),
)


async def _restore_round(pending):
    failed = []
    for label, restore in pending:
        try:
            ok, message = await restore()
        except Exception as exc:
            ok, message = False, f"unexpected error: {exc}"
        if ok:
            if message:
                logger.info(message)
        else:
            failed.append((label, restore, message))
    return failed


async def _restore_retry_loop(failed):
    deadline = time.monotonic() + RESTORE_TIMEOUT_SECONDS
    logged = None
    while failed:
        waiting = ", ".join(label for label, _restore, _message in failed)
        if waiting != logged:
            logger.info(f"Waiting to restore: {waiting}")
            logged = waiting
        if time.monotonic() >= deadline:
            for label, _restore, message in failed:
                logger.error(f"Gave up restoring the {label} after {RESTORE_TIMEOUT_SECONDS:.0f} s: {message}")
            return
        await asyncio.sleep(RESTORE_RETRY_SECONDS)
        failed = await _restore_round([(label, restore) for label, restore, _message in failed])


def _interfaces():
    return (
        ("Fan", _find_fan_hwmon() or FAN_TARGET_PATH),
        ("Temperature sensors", HWMON_DIR),
        ("LED class", LED_CLASS_DIR),
        ("CPU frequency", CPUFREQ_DIR),
        ("GPU frequency", GPU_DEVFREQ_PATH),
        ("Buzzer", BUZZER_DIR),
    )


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

        if await _fan_interface() == "curve":
            return await self._set_fan_target_curve(target)

        async with _fan_lock:
            if _guard["active"]:
                _guard["restore_target"] = target
                deferred = True
            else:
                deferred = False
                ok, result = await _write_fan_target_locked("Setting fan target", target)
                if not ok:
                    return _fail(result)

        await _remember_setting("saved_target", target)
        if deferred:
            return _ok(
                f"Thermal guard is cooling. {target} °C will apply once the CPU cools down",
                {"temp": FAN_MAX_COOLING_TARGET},
            )
        return _ok(f"Fan target set to {result} °C", {"temp": result})

    async def _set_fan_target_curve(self, target):
        curve = _target_curve(target)
        async with _fan_lock:
            ok, status = await _guarded_io(
                "Setting fan target", FAN_HWMON_DESC, _write_fan_curve_sync, curve
            )
            if not ok:
                return _fail(status)
            if status["curve"] != curve:
                return _fail("Setting fan target: write accepted but the driver reports another curve")
            ok, deferred = await _set_fan_mode_locked("Switching fan to curve mode", FAN_MODE_CURVE)
            if not ok:
                return _fail(deferred)

        await _remember_setting("saved_target", target)
        await _remember_setting("saved_curve", curve)
        data = {"temp": target, "curve": status["curve"]}
        if deferred:
            return _ok(f"Thermal guard is cooling. {target} °C will apply once the CPU cools down", data)
        return _ok(f"Fan target set to {target} °C", {**data, "mode": FAN_MODE_CURVE})

    async def get_temperatures(self):
        sensors = await _read_temperatures()
        if not sensors:
            return _fail(f"No temperature sensors found under {HWMON_DIR}")
        return _ok(f"Read {len(sensors)} temperature sensors", {"sensors": sensors}, log=False)

    async def get_fan_status(self):
        interface = await _fan_interface()
        target = target_error = fan = fan_error = None
        if interface == "curve":
            async with _fan_lock:
                ok, value = await _guarded_io(
                    "Reading fan curve", FAN_HWMON_DESC, _read_fan_hwmon_sync
                )
            if ok:
                fan = value
                target = _curve_target(fan["curve"])
            else:
                fan_error = value
        else:
            async with _fan_lock:
                ok, value = await _guarded_io(
                    "Reading fan target", FAN_TARGET_PATH, _read_sysfs, FAN_TARGET_PATH
                )
            target = _coerce_int(value) if ok else None
            if not ok:
                target_error = value
            elif target is None:
                target_error = f"Unexpected fan target value: {value!r}"

        sensors = await _read_temperatures()
        return _ok(
            "Fan status updated",
            {
                "interface": interface,
                "target": target,
                "target_error": target_error,
                "fan": fan,
                "fan_error": fan_error,
                "sensors": sensors,
                "guard": _guard_snapshot(),
            },
            log=False,
        )

    async def set_fan_curve(self, curve):
        clean, problem = _sanitize_curve(curve)
        if clean is None:
            return _fail(f"Invalid fan curve: {problem}")

        async with _fan_lock:
            ok, status = await _guarded_io(
                "Setting fan curve", FAN_HWMON_DESC, _write_fan_curve_sync, clean
            )
            if not ok:
                return _fail(status)
            if status["curve"] != clean:
                return _fail("Setting fan curve: write accepted but the driver reports another curve")
            ok, deferred = await _set_fan_mode_locked("Switching fan to curve mode", FAN_MODE_CURVE)
            if not ok:
                return _fail(deferred)

        await _remember_setting("saved_curve", clean)
        if deferred:
            return _ok("Fan curve saved. It takes over once Thermal Guard releases the fan", status)
        return _ok("Fan curve applied", {**status, "mode": FAN_MODE_CURVE})

    async def reset_fan_curve(self):
        async with _fan_lock:
            ok, status = await _guarded_io(
                "Resetting fan curve", FAN_HWMON_DESC, _reset_fan_curve_sync
            )
            if not ok:
                return _fail(status)
            ok, deferred = await _set_fan_mode_locked("Switching fan to curve mode", FAN_MODE_CURVE)
            if not ok:
                return _fail(deferred)

        await _remember_setting("saved_curve", None)
        await _remember_setting("saved_target", None)
        if deferred:
            return _ok("Default curve restored. It takes over once Thermal Guard releases the fan", status)
        return _ok("Default fan curve restored", {**status, "mode": FAN_MODE_CURVE})

    async def set_fan_mode(self, mode):
        value = _coerce_int(mode)
        if value not in (FAN_MODE_FULL, FAN_MODE_CURVE, FAN_MODE_FIRMWARE):
            return _fail(f"Invalid fan mode: {mode!r}")
        async with _fan_lock:
            ok, deferred = await _set_fan_mode_locked("Setting fan mode", value)
        if not ok:
            return _fail(deferred)
        label = {FAN_MODE_FULL: "full speed", FAN_MODE_CURVE: "curve", FAN_MODE_FIRMWARE: "console firmware"}[value]
        if deferred:
            return _ok(f"Thermal guard is cooling. The fan switches to {label} once the CPU cools down")
        return _ok(f"Fan set to {label}", {"mode": value})

    async def get_fan_settings(self):
        await _ensure_settings()
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

        await _ensure_settings()
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
        await _ensure_settings()
        return _ok("LED settings loaded", _led_settings_snapshot(), log=False)

    async def set_led_settings(self, loop_enabled=None, loop_seconds=None, restore_on_boot=None):
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
        if restore_on_boot is not None:
            if not isinstance(restore_on_boot, bool):
                return _fail(f"Invalid restore_on_boot value: {restore_on_boot!r}")
            updates["led_restore_on_boot"] = restore_on_boot
        if not updates:
            return _fail("No settings provided")

        await _ensure_settings()
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
            ok, error = await _apply_led_preset_locked("Applying LED preset", preset)
        if not ok:
            return _fail(error)

        await _remember_led_preset(preset)
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

        await _remember_setting("saved_governor", governor)
        return _ok(f"CPU governor set to {governor}", result)

    async def set_cpu_clock(self, mhz):
        clock = None if mhz is None else _coerce_int(mhz)
        if mhz is not None and (clock is None or not CLOCK_MHZ_MIN <= clock <= CLOCK_MHZ_MAX):
            return _fail(f"Invalid CPU clock: {mhz!r}")

        async with _cpu_lock:
            action = "Resetting CPU clock" if clock is None else "Locking CPU clock"
            ok, result = await _apply_cpu_clock_locked(action, clock)
        if not ok:
            return _fail(result)

        await _remember_setting("saved_cpu_clock", result["locked_mhz"])
        if clock is None:
            return _ok("CPU clock back to automatic", result)
        return _ok(f"CPU clock locked at {result['locked_mhz']} MHz", result)

    async def get_cpu_settings(self):
        await _ensure_settings()
        return _ok("CPU settings loaded", _cpu_settings_snapshot(), log=False)

    async def set_cpu_settings(self, restore_on_boot=None):
        if not isinstance(restore_on_boot, bool):
            return _fail(f"Invalid restore_on_boot value: {restore_on_boot!r}")

        await _ensure_settings()
        async with _settings_lock:
            candidate = dict(_settings)
            candidate["cpu_restore_on_boot"] = restore_on_boot
            ok, error = await _save_settings(candidate)
            if not ok:
                return _fail(error)
            _settings["cpu_restore_on_boot"] = restore_on_boot

        return _ok("CPU settings saved", _cpu_settings_snapshot())

    async def get_gpu_status(self):
        async with _gpu_lock:
            ok, result = await _read_gpufreq()
        if not ok:
            return _fail(result)
        return _ok("GPU status updated", result, log=False)

    async def set_gpu_governor(self, governor):
        if not isinstance(governor, str) or not CPU_GOVERNOR_PATTERN.fullmatch(governor):
            return _fail(f"Invalid governor name: {governor!r}")

        async with _gpu_lock:
            ok, result = await _apply_gpu_governor_locked("Setting GPU governor", governor)
        if not ok:
            return _fail(result)

        await _remember_setting("saved_gpu_governor", governor)
        return _ok(f"GPU governor set to {governor}", result)

    async def set_gpu_clock(self, mhz):
        clock = None if mhz is None else _coerce_int(mhz)
        if mhz is not None and (clock is None or not CLOCK_MHZ_MIN <= clock <= CLOCK_MHZ_MAX):
            return _fail(f"Invalid GPU clock: {mhz!r}")

        async with _gpu_lock:
            action = "Resetting GPU clock" if clock is None else "Locking GPU clock"
            ok, result = await _apply_gpu_clock_locked(action, clock)
        if not ok:
            return _fail(result)

        await _remember_setting("saved_gpu_clock", result["locked_mhz"])
        if clock is None:
            return _ok("GPU clock back to automatic", result)
        return _ok(f"GPU clock locked at {result['locked_mhz']} MHz", result)

    async def get_gpu_settings(self):
        await _ensure_settings()
        return _ok("GPU settings loaded", _gpu_settings_snapshot(), log=False)

    async def set_gpu_settings(self, restore_on_boot=None):
        if not isinstance(restore_on_boot, bool):
            return _fail(f"Invalid restore_on_boot value: {restore_on_boot!r}")

        await _ensure_settings()
        async with _settings_lock:
            candidate = dict(_settings)
            candidate["gpu_restore_on_boot"] = restore_on_boot
            ok, error = await _save_settings(candidate)
            if not ok:
                return _fail(error)
            _settings["gpu_restore_on_boot"] = restore_on_boot

        return _ok("GPU settings saved", _gpu_settings_snapshot())

    async def get_cu_unlock(self):
        async with _boot_lock:
            await _ensure_boot_mounted()
            ok, result = await _guarded_io(
                "Reading CU unlock", CU_UNLOCK_PARAM_PATH, _read_cu_unlock_sync
            )
        if not ok:
            return _fail(result)
        return _ok("CU unlock read", result, log=False)

    async def set_cu_unlock(self, target):
        if target not in CU_TARGETS:
            return _fail(f"Unsupported CU count: {target!r}")
        mode, mask = CU_TARGETS[target]
        async with _boot_lock:
            if not os.path.exists(CU_UNLOCK_PARAM_PATH):
                return _fail(f"This kernel doesn't support {CU_UNLOCK_ARG}")
            await _ensure_boot_mounted()
            path = _boot_file("cmdline.txt")
            if path is None:
                return _fail(_boot_missing())
            changes = (
                (CU_UNLOCK_PATTERN, f"{CU_UNLOCK_ARG}={mode}" if mode else None),
                (CU_MASK_PATTERN, f"{CU_MASK_ARG}={mask}" if mask else None),
            )
            ok, result = await _guarded_io(
                "Updating cmdline.txt",
                path,
                _with_writable_boot,
                _set_cmdline_args_sync,
                path,
                changes,
            )
            if not ok or result:
                return _fail(result)
            ok, status = await _guarded_io(
                "Reading CU unlock", CU_UNLOCK_PARAM_PATH, _read_cu_unlock_sync
            )
        if not ok:
            return _fail(status)
        state = f"set to {target} CUs" if target else "disabled"
        return _ok(f"CU unlock {state} in cmdline.txt. Reboot to apply.", status)

    async def get_gpu_memory(self):
        async with _boot_lock:
            await _ensure_boot_mounted()
            ok, result = await _guarded_io(
                "Reading GPU memory settings", BOOT_MOUNT, _read_gpu_memory_sync
            )
        if not ok:
            return _fail(result)
        return _ok("GPU memory read", result, log=False)

    async def set_vram(self, megabytes):
        megabytes = _coerce_int(megabytes)
        if megabytes is None or not VRAM_MIN_MB <= megabytes <= VRAM_MAX_MB:
            return _fail(
                f"VRAM must be between {_format_megabytes(VRAM_MIN_MB)} and "
                f"{_format_megabytes(VRAM_MAX_MB)}"
            )
        async with _boot_lock:
            await _ensure_boot_mounted()
            cmdline_path = _boot_file("cmdline.txt")
            if cmdline_path is None:
                return _fail(_boot_missing())
            path = _boot_file("vram.txt") or os.path.join(
                os.path.dirname(cmdline_path), "vram.txt"
            )
            ok, error = await _guarded_io(
                "Updating vram.txt",
                path,
                _with_writable_boot,
                _write_vram_sync,
                path,
                megabytes * 1024 * 1024,
            )
            if not ok or error:
                return _fail(error)
            ok, status = await _guarded_io(
                "Reading GPU memory settings", path, _read_gpu_memory_sync
            )
        if not ok:
            return _fail(status)
        return _ok(
            f"VRAM set to {_format_megabytes(megabytes)} in vram.txt. Reboot to apply.", status
        )

    async def set_gtt_limit(self, gigabytes):
        if gigabytes is not None and gigabytes not in GTT_CHOICES_GB:
            return _fail(f"Unsupported GTT limit: {gigabytes!r}")
        argument = None
        if gigabytes is not None:
            argument = f"{GTT_ARG}={gigabytes * 1024 * 1024 // 4}"
        async with _boot_lock:
            await _ensure_boot_mounted()
            path = _boot_file("cmdline.txt")
            if path is None:
                return _fail(_boot_missing())
            ok, result = await _guarded_io(
                "Updating cmdline.txt",
                path,
                _with_writable_boot,
                _set_cmdline_args_sync,
                path,
                ((GTT_PATTERN, argument),),
            )
            if not ok or result:
                return _fail(result)
            ok, status = await _guarded_io(
                "Reading GPU memory settings", path, _read_gpu_memory_sync
            )
        if not ok:
            return _fail(status)
        return _ok("GTT limit saved in cmdline.txt. Reboot to apply.", status)

    async def get_memory_status(self):
        ok, result = await _guarded_io(
            "Reading memory status", MEMINFO_PATH, _read_memory_status_sync
        )
        if not ok:
            return _fail(result)
        return _ok("Memory status read", result, log=False)

    async def get_swap_settings(self):
        async with _boot_lock:
            await _ensure_boot_mounted()
            ok, result = await _guarded_io(
                "Reading swap settings", ZRAM_CONFIG_PATH, _read_swap_settings_sync
            )
        if not ok:
            return _fail(result)
        return _ok("Swap settings read", result, log=False)

    async def set_zram(self, enabled, size=None, algorithm=None):
        if not isinstance(enabled, bool):
            return _fail(f"Invalid zram state: {enabled!r}")
        if enabled and size not in ZRAM_SIZES:
            return _fail(f"Unsupported zram size: {size!r}")
        if enabled and algorithm not in ZRAM_ALGORITHMS:
            return _fail(f"Unsupported zram compression: {algorithm!r}")
        if enabled and not any(os.path.isfile(path) for path in ZRAM_GENERATOR_PATHS):
            return _fail("zram-generator isn't installed. Install it with your package manager.")
        async with _boot_lock:
            ok, error = await _guarded_io(
                "Updating the zram config",
                ZRAM_CONFIG_PATH,
                _write_zram_config_sync,
                enabled,
                size,
                algorithm,
            )
            if not ok:
                return _fail(error)
            ok, status = await _guarded_io(
                "Reading swap settings", ZRAM_CONFIG_PATH, _read_swap_settings_sync
            )
        if not ok:
            return _fail(status)
        state = f"set to {size} with {algorithm}" if enabled else "turned off"
        return _ok(f"zram {state}. Reboot to apply.", status)

    async def set_zswap(self, enabled):
        if not isinstance(enabled, bool):
            return _fail(f"Invalid zswap state: {enabled!r}")
        if not os.path.isdir(ZSWAP_DIR):
            return _fail("This kernel doesn't include zswap")
        ok, error = await _guarded_io(
            "Updating zswap",
            ZSWAP_ENABLED_PATH,
            _write_sysfs,
            ZSWAP_ENABLED_PATH,
            "Y" if enabled else "N",
        )
        if not ok:
            return _fail(error)
        async with _boot_lock:
            await _ensure_boot_mounted()
            path = _boot_file("cmdline.txt")
            persisted = path is not None
            if persisted:
                ok, result = await _guarded_io(
                    "Updating cmdline.txt",
                    path,
                    _with_writable_boot,
                    _set_cmdline_args_sync,
                    path,
                    ((ZSWAP_PATTERN, f"{ZSWAP_ARG}={1 if enabled else 0}"),),
                )
                if not ok or result:
                    return _fail(f"zswap changed for this boot, but {result}")
            ok, status = await _guarded_io(
                "Reading swap settings", ZRAM_CONFIG_PATH, _read_swap_settings_sync
            )
        if not ok:
            return _fail(status)
        state = "on" if enabled else "off"
        if not persisted:
            return _ok(f"zswap turned {state} until reboot. {_boot_missing()}", status)
        return _ok(f"zswap turned {state} and saved in cmdline.txt", status)

    async def reload_cu_unlock(self):
        async with _boot_lock:
            ok, state = await _guarded_io(
                "Reading CU unlock", CU_UNLOCK_PARAM_PATH, _read_cu_unlock_sync
            )
            if not ok:
                return _fail(state)
            if state["running"] is None or state["configured"] is None:
                return _fail("CU unlock isn't available on this system")
            if not state["pending"]:
                return _fail("There is no CU unlock change to apply")
            if state["reload_blocker"]:
                return _fail(state["reload_blocker"])
            ok, error = await _guarded_io(
                "Starting the GPU driver reload",
                CU_RELOAD_UNIT,
                _start_cu_reload_sync,
                state["configured"],
                state["configured_mask"],
                state["running"],
                state["running_mask"],
            )
            if not ok or error:
                return _fail(error)
        return _ok("GPU driver reload started")

    async def _main(self):
        global _guard_task, _led_loop_task, _restore_task
        logger.info("PS5 Hardware Control loaded")
        for label, path in _interfaces():
            if os.path.exists(path):
                logger.info(f"{label} interface found at {path}")
            else:
                logger.warning(f"{label} interface missing at {path}")
        if not os.path.isdir(GPU_DEVFREQ_PATH):
            logger.warning(await _describe_missing_gpufreq())

        await _ensure_settings()
        _resume_led_preset()
        failed = await _restore_round(_RESTORES)
        if failed:
            _restore_task = asyncio.create_task(_restore_retry_loop(failed))
        _guard_task = asyncio.create_task(_guard_loop())
        _led_loop_task = asyncio.create_task(_led_loop())

    async def _unload(self):
        global _guard_task, _led_loop_task, _restore_task
        await _cancel_task(_restore_task)
        _restore_task = None
        await _cancel_task(_led_loop_task)
        _led_loop_task = None
        await _cancel_task(_guard_task)
        _guard_task = None

        try:
            await asyncio.wait_for(_unload_hardware(), timeout=UNLOAD_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Hardware cleanup timed out during unload")
        logger.info("PS5 Hardware Control unloaded")
