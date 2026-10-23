import { call as callBackend, definePlugin, toaster } from "@decky/api";
import {
  ButtonItem,
  DialogButton,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SliderField,
  Spinner,
  staticClasses,
  TextField,
  ToggleField,
} from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FaCube,
  FaExclamationTriangle,
  FaLightbulb,
  FaLock,
  FaMicrochip,
  FaRedo,
  FaShieldAlt,
  FaSyncAlt,
  FaTachometerAlt,
  FaThermometerHalf,
  FaUnlock,
  FaWind,
} from "react-icons/fa";
import {
  BackendMethod,
  BackendMethods,
  BackendResult,
  CpuSettings,
  CpuStatusData,
  CuratedPreset,
  FanPreset,
  FanSettings,
  FanSettingsUpdate,
  FanStatusData,
  FanStatusResult,
  GovernorInfo,
  GpuSettings,
  GpuStatusData,
  LedSettingsData,
  TabId,
} from "./types";

const PLUGIN_TITLE = "PS5 Hardware Control";
const FAN_MIN = 40;
const FAN_MAX = 90;
const FAN_DEFAULT = 65;
const FAN_BOOT_TARGET = 80;
const FAN_MAX_COOLING = 50;
const GUARD_MIN = 80;
const GUARD_MAX = 100;
const GUARD_DEFAULT = 95;
const GUARD_HYSTERESIS = 10;
const LED_LOOP_MIN = 2;
const LED_LOOP_MAX = 30;
const LED_LOOP_DEFAULT = 6;
const CPU_CLOCK_STEP = 100;
const GPU_CLOCK_STEP = 25;
const STATUS_POLL_MS = 2000;
const THRESHOLD_SAVE_DELAY_MS = 600;
const ACCENT = "#1a9fff";

const STYLES = `
.ps5hw-grid {
  display: grid;
  gap: 6px;
  padding: 2px 0;
  width: 100%;
  box-sizing: border-box;
  container-type: inline-size;
}
.ps5hw-grid > .ps5hw-btn {
  min-width: 0 !important;
  width: 100%;
  height: 100%;
  min-height: 40px;
  margin: 0 !important;
  padding: 8px 4px !important;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  line-height: 1.25;
  font-size: 13px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.ps5hw-grid > .ps5hw-wide {
  grid-column: 1 / -1;
}
.ps5hw-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5em;
  min-width: 0;
  max-width: 100%;
}
.ps5hw-label > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ps5hw-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
  max-width: 100%;
}
.ps5hw-sub {
  font-size: 11px;
  opacity: 0.7;
}
@container (max-width: 300px) {
  .ps5hw-tabs > .ps5hw-btn .ps5hw-label {
    flex-direction: column;
    gap: 2px;
  }
  .ps5hw-tabs > .ps5hw-btn {
    font-size: 12px;
    padding: 6px 2px !important;
  }
}
@container (max-width: 240px) {
  .ps5hw-grid > .ps5hw-btn {
    font-size: 12px;
    padding: 6px 2px !important;
  }
}
`;

const FAN_PRESETS: FanPreset[] = [
  { id: "quiet", label: "Quiet", temp: 85 },
  { id: "default", label: "Default", temp: FAN_BOOT_TARGET },
  { id: "balanced", label: "Balanced", temp: 72 },
  { id: "cool", label: "Cool", temp: 65 },
  { id: "max", label: "Max Cooling", temp: FAN_MAX_COOLING },
];

const CURATED_PRESETS: CuratedPreset[] = [
  { id: "off", label: "Off" },
  { id: "white_bright", label: "White Bright" },
  { id: "blue_rich", label: "Blue Rich" },
  { id: "purple", label: "Purple" },
  { id: "orange_breathe", label: "Orange Breathe" },
  { id: "pink_breathe", label: "Pink Breathe" },
];

const GOVERNORS: Record<string, GovernorInfo> = {
  performance: { label: "Performance", description: "Highest clocks" },
  powersave: { label: "Powersave", description: "Lowest clocks" },
  schedutil: { label: "Schedutil", description: "Follows scheduler load" },
  ondemand: { label: "Ondemand", description: "Jumps up under load" },
  conservative: { label: "Conservative", description: "Ramps up gradually" },
  userspace: { label: "Userspace", description: "Speed set by a program" },
};

// With EPP drivers the hardware picks clocks itself; the governor only sets a bias.
const EPP_GOVERNORS: Record<string, GovernorInfo> = {
  performance: { label: "Performance", description: "Biased to max clocks" },
  powersave: { label: "Powersave", description: "Firmware managed" },
};

// devfreq governors, as exposed by the ps5-gpufreq driver.
const GPU_GOVERNORS: Record<string, GovernorInfo> = {
  simple_ondemand: { label: "Ondemand", description: "Follows GPU load" },
  performance: { label: "Performance", description: "Highest clock" },
  powersave: { label: "Powersave", description: "Lowest clock" },
  userspace: { label: "Userspace", description: "Clock set by a program" },
};

const TABS: { id: TabId; label: string; icon: JSX.Element }[] = [
  { id: "fan", label: "Fan", icon: <FaWind /> },
  { id: "cpu", label: "CPU", icon: <FaTachometerAlt /> },
  { id: "gpu", label: "GPU", icon: <FaCube /> },
  { id: "led", label: "LED", icon: <FaLightbulb /> },
];

let lastTab: TabId = "fan";

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const chunk = <T,>(items: T[], size: number): T[][] => {
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    rows.push(items.slice(i, i + size));
  }
  return rows;
};

const formatTemp = (celsius: number) => `${Math.round(celsius)} °C`;

const prettifyPreset = (id: string) =>
  id
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const formatFreq = (mhz: number) =>
  mhz >= 1000 ? `${(mhz / 1000).toFixed(2)} GHz` : `${mhz} MHz`;

const isEppDriver = (driver: string | null) =>
  driver !== null && (driver.endsWith("-epp") || driver === "intel_pstate");

const governorInfo = (id: string, driver: string | null): GovernorInfo =>
  (isEppDriver(driver) ? EPP_GOVERNORS[id] : undefined) ??
  GOVERNORS[id] ?? { label: prettifyPreset(id), description: "Kernel governor" };

const gpuGovernorInfo = (id: string): GovernorInfo =>
  GPU_GOVERNORS[id] ?? { label: prettifyPreset(id), description: "Kernel governor" };

const InlineSpinner: FC = () => (
  <Spinner style={{ width: "1.2em", height: "1.2em", verticalAlign: "middle" }} />
);

const ButtonLabel: FC<{ icon: JSX.Element; label: string; busy?: boolean }> = ({
  icon,
  label,
  busy,
}) => (
  <div className="ps5hw-label">
    {busy ? <InlineSpinner /> : icon}
    <span>{label}</span>
  </div>
);

const ButtonGrid: FC<{ columns: number; className?: string; children: ReactNode }> = ({
  columns,
  className,
  children,
}) => (
  <PanelSectionRow>
    <Focusable
      flow-children="horizontal"
      className={className ? `ps5hw-grid ${className}` : "ps5hw-grid"}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {children}
    </Focusable>
  </PanelSectionRow>
);

const gridButtonClass = (index: number, count: number, columns: number) =>
  index === count - 1 && count % columns !== 0 ? "ps5hw-btn ps5hw-wide" : "ps5hw-btn";

const nearest = (value: number, choices: number[]) =>
  choices.reduce((best, choice) => (Math.abs(choice - value) < Math.abs(best - value) ? choice : best), value);

const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));

const ClockLockSection: FC<{
  description: string;
  hwMin: number | null;
  hwMax: number | null;
  steps: number[];
  fallbackStep: number;
  locked: number | null;
  busy: boolean;
  applying: string | null;
  onApply: (mhz: number | null) => Promise<void>;
}> = ({ description, hwMin, hwMax, steps, fallbackStep, locked, busy, applying, onApply }) => {
  const [slider, setSlider] = useState<number | null>(null);
  const touched = useRef<boolean>(false);

  useEffect(() => {
    if (!touched.current && hwMin !== null && hwMax !== null) {
      setSlider(clamp(nearest(locked ?? hwMax, steps), hwMin, hwMax));
    }
  }, [locked, hwMin, hwMax, steps]);

  const apply = async (mhz: number | null) => {
    await onApply(mhz);
    touched.current = false;
  };

  if (hwMin === null || hwMax === null || hwMin >= hwMax || slider === null) {
    return null;
  }

  // Uneven frequency tables still get a slider step that lands on every entry.
  const step =
    steps.length > 1 ? steps.slice(1).reduce((acc, mhz, i) => gcd(acc, mhz - steps[i]), 0) || fallbackStep : fallbackStep;

  return (
    <PanelSection title="Manual Clock">
      <PanelSectionRow>
        <Field label="Clock Lock" icon={locked !== null ? <FaLock /> : <FaUnlock />}>
          {locked !== null ? formatFreq(locked) : "Automatic"}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Clock (MHz)"
          description={description}
          value={slider}
          min={hwMin}
          max={hwMax}
          step={step}
          showValue
          valueSuffix=" MHz"
          resetValue={hwMax}
          notchCount={2}
          notchLabels={[
            { notchIndex: 0, label: formatFreq(hwMin), value: hwMin },
            { notchIndex: 1, label: formatFreq(hwMax), value: hwMax },
          ]}
          disabled={busy}
          onChange={(value) => {
            touched.current = true;
            setSlider(steps.length ? nearest(value, steps) : value);
          }}
        />
      </PanelSectionRow>
      <ButtonGrid columns={2}>
        <DialogButton
          className="ps5hw-btn"
          disabled={busy || slider === locked}
          onClick={() => apply(slider)}
        >
          <ButtonLabel icon={<FaLock />} label="Lock Clock" busy={applying === "clock"} />
        </DialogButton>
        <DialogButton
          className="ps5hw-btn"
          disabled={busy || locked === null}
          onClick={() => apply(null)}
        >
          <ButtonLabel icon={<FaUnlock />} label="Automatic" busy={applying === "clock-auto"} />
        </DialogButton>
      </ButtonGrid>
    </PanelSection>
  );
};

function useBackend() {
  const call = useCallback(
    async <M extends BackendMethod>(
      method: M,
      ...args: BackendMethods[M]["args"]
    ): Promise<BackendMethods[M]["result"]> => {
      try {
        const result = await callBackend<BackendMethods[M]["args"], BackendMethods[M]["result"]>(
          method,
          ...args,
        );
        if (result === null || typeof result !== "object") {
          return { success: false, error: `Unexpected response from ${method}` } as BackendMethods[M]["result"];
        }
        return result;
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : String(e),
        } as BackendMethods[M]["result"];
      }
    },
    [],
  );

  const notify = useCallback(<T,>(result: BackendResult<T>, quiet = false) => {
    if (result.success) {
      if (!quiet) {
        toaster.toast({ title: PLUGIN_TITLE, body: result.message });
      }
    } else {
      toaster.toast({
        title: PLUGIN_TITLE,
        body: result.error,
        icon: <FaExclamationTriangle />,
        critical: true,
      });
    }
  }, []);

  return useMemo(() => ({ call, notify }), [call, notify]);
}

const TabBar: FC<{ active: TabId; onChange: (tab: TabId) => void }> = ({ active, onChange }) => (
  <ButtonGrid columns={TABS.length} className="ps5hw-tabs">
    {TABS.map((tab) => {
      const selected = tab.id === active;
      return (
        <DialogButton
          key={tab.id}
          className="ps5hw-btn"
          onClick={() => onChange(tab.id)}
          style={{
            borderBottom: `2px solid ${selected ? ACCENT : "transparent"}`,
            color: selected ? "#ffffff" : undefined,
          }}
        >
          <ButtonLabel icon={tab.icon} label={tab.label} />
        </DialogButton>
      );
    })}
  </ButtonGrid>
);

const FanTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({ backend }) => {
  const { call, notify } = backend;
  const [status, setStatus] = useState<FanStatusData | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [slider, setSlider] = useState<number>(FAN_DEFAULT);
  const [applying, setApplying] = useState<string | null>(null);
  const [settings, setSettings] = useState<FanSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const [threshold, setThreshold] = useState<number>(GUARD_DEFAULT);
  const alive = useRef<boolean>(true);
  const polling = useRef<boolean>(false);
  const sliderTouched = useRef<boolean>(false);
  const thresholdTimer = useRef<number | undefined>(undefined);

  const refreshStatus = useCallback(async (): Promise<FanStatusResult | null> => {
    if (polling.current) {
      return null;
    }
    polling.current = true;
    const result = await call("get_fan_status");
    polling.current = false;
    if (!alive.current) {
      return null;
    }
    if (result.success) {
      setStatus(result.data);
      setStatusError(result.data.target_error);
      if (!sliderTouched.current && result.data.target !== null) {
        setSlider(clamp(result.data.target, FAN_MIN, FAN_MAX));
      }
    } else {
      setStatusError(result.error);
    }
    return result;
  }, [call]);

  useEffect(() => {
    alive.current = true;
    (async () => {
      const [statusResult, settingsResult] = await Promise.all([
        refreshStatus(),
        call("get_fan_settings"),
      ]);
      if (!alive.current) {
        return;
      }
      if (statusResult) {
        notify(statusResult, true);
      }
      if (settingsResult.success) {
        setSettings(settingsResult.data.settings);
        setThreshold(settingsResult.data.settings.guard_threshold);
      } else {
        notify(settingsResult);
      }
    })();
    const timer = window.setInterval(refreshStatus, STATUS_POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
      window.clearTimeout(thresholdTimer.current);
    };
  }, [refreshStatus, call, notify]);

  const applyTarget = async (source: string, temp: number) => {
    setApplying(source);
    const result = await call("set_fan_target", temp);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus((prev) => (prev ? { ...prev, target: result.data.temp } : prev));
      setSlider(temp);
      sliderTouched.current = false;
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const saveSettings = async (update: FanSettingsUpdate) => {
    setSavingSettings(true);
    const result = await call(
      "set_fan_settings",
      update.restore_on_boot ?? null,
      update.guard_enabled ?? null,
      update.guard_threshold ?? null,
      update.alarm_enabled ?? null,
    );
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setSettings(result.data.settings);
      setStatus((prev) => (prev ? { ...prev, guard: result.data.guard } : prev));
    }
    notify(result, true);
    setSavingSettings(false);
  };

  const changeThreshold = (value: number) => {
    setThreshold(value);
    window.clearTimeout(thresholdTimer.current);
    thresholdTimer.current = window.setTimeout(
      () => saveSettings({ guard_threshold: value }),
      THRESHOLD_SAVE_DELAY_MS,
    );
  };

  const loading = status === null && statusError === null;
  const target = status?.target ?? null;
  const guard = status?.guard ?? null;
  const busy = applying !== null;
  const guardEnabled = settings?.guard_enabled ?? false;
  const alarmEnabled = settings?.alarm_enabled ?? false;
  const protectionEnabled = guardEnabled || alarmEnabled;

  let guardStatus = "Off";
  if (guardEnabled && guard?.active) {
    guardStatus = `Cooling · restores ${guard.restore_target ?? FAN_BOOT_TARGET} °C`;
  } else if (alarmEnabled && guard?.alarm_active) {
    guardStatus = "Overheated · alarm sounded";
  } else if (protectionEnabled && guard?.cpu != null) {
    guardStatus = `Standby · CPU ${formatTemp(guard.cpu)}`;
  } else if (protectionEnabled) {
    guardStatus = "Standby";
  }

  const restoreDescription =
    settings?.saved_target != null
      ? `Re-applies ${settings.saved_target} °C when Decky starts. The kernel resets the target to ${FAN_BOOT_TARGET} °C at boot.`
      : `Re-applies your last target when Decky starts. The kernel resets the target to ${FAN_BOOT_TARGET} °C at boot.`;

  return (
    <>
      <PanelSection title="Temperatures">
        {loading && (
          <PanelSectionRow>
            <Field label="Reading sensors">
              <InlineSpinner />
            </Field>
          </PanelSectionRow>
        )}
        {status?.sensors.map((sensor) => (
          <PanelSectionRow key={sensor.id}>
            <Field label={sensor.label} icon={<FaThermometerHalf />}>
              {formatTemp(sensor.celsius)}
            </Field>
          </PanelSectionRow>
        ))}
        {status !== null && status.sensors.length === 0 && (
          <PanelSectionRow>
            <Field label="No temperature sensors found" icon={<FaThermometerHalf />} />
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <Field label="Fan Target" icon={<FaWind />} description={statusError ?? undefined}>
            {loading ? <InlineSpinner /> : target !== null ? `${target} °C` : "Unavailable"}
          </Field>
        </PanelSectionRow>
        {(guard?.active || guard?.alarm_active) && (
          <PanelSectionRow>
            <Field label="Overheat" icon={<FaExclamationTriangle />}>
              {guard?.active ? "Cooling" : "Alarm sounded"}
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title="Presets">
        {chunk(FAN_PRESETS, 2).map((row, rowIndex) => (
          <ButtonGrid key={row.map((p) => p.id).join("|")} columns={2}>
            {row.map((preset, index) => {
              const selected = target === preset.temp;
              return (
                <DialogButton
                  key={preset.id}
                  className={gridButtonClass(rowIndex * 2 + index, FAN_PRESETS.length, 2)}
                  disabled={busy}
                  onClick={() => applyTarget(preset.id, preset.temp)}
                  style={{ borderBottom: `2px solid ${selected ? ACCENT : "transparent"}` }}
                >
                  {applying === preset.id ? (
                    <InlineSpinner />
                  ) : (
                    <div className="ps5hw-stack">
                      <span>{preset.label}</span>
                      <span className="ps5hw-sub">{preset.temp} °C</span>
                    </div>
                  )}
                </DialogButton>
              );
            })}
          </ButtonGrid>
        ))}
      </PanelSection>
      <PanelSection title="Manual Target">
        <PanelSectionRow>
          <SliderField
            label="Target Temperature (°C)"
            description="Lower targets ramp the fan earlier and louder."
            value={slider}
            min={FAN_MIN}
            max={FAN_MAX}
            step={1}
            showValue
            valueSuffix=" °C"
            resetValue={FAN_DEFAULT}
            notchCount={2}
            notchLabels={[
              { notchIndex: 0, label: `${FAN_MIN}`, value: FAN_MIN },
              { notchIndex: 1, label: `${FAN_MAX}`, value: FAN_MAX },
            ]}
            disabled={busy}
            onChange={(value) => {
              sliderTouched.current = true;
              setSlider(value);
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy || loading || slider === target}
            onClick={() => applyTarget("manual", slider)}
          >
            <ButtonLabel icon={<FaWind />} label="Apply Target" busy={applying === "manual"} />
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Advanced">
        <PanelSectionRow>
          <ToggleField
            label="Restore on Startup"
            description={restoreDescription}
            checked={settings?.restore_on_boot ?? false}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ restore_on_boot: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Thermal Guard"
            description={`Switch to Max Cooling (${FAN_MAX_COOLING} °C) when the CPU reaches the threshold, then restore your target once it is ${GUARD_HYSTERESIS} °C cooler.`}
            checked={guardEnabled}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ guard_enabled: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Overheat Alarm"
            description={`Play the console's error beep when the CPU reaches the threshold. It re-arms once the CPU is ${GUARD_HYSTERESIS} °C cooler.`}
            checked={alarmEnabled}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ alarm_enabled: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Overheat Threshold"
            description="CPU temperature used by Thermal Guard and Overheat Alarm."
            value={threshold}
            min={GUARD_MIN}
            max={GUARD_MAX}
            step={1}
            showValue
            valueSuffix=" °C"
            resetValue={GUARD_DEFAULT}
            disabled={!protectionEnabled}
            onChange={changeThreshold}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Protection Status" icon={<FaShieldAlt />}>
            {guardStatus}
          </Field>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

const CpuTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({ backend }) => {
  const { call, notify } = backend;
  const [status, setStatus] = useState<CpuStatusData | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [settings, setSettings] = useState<CpuSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const alive = useRef<boolean>(true);
  const polling = useRef<boolean>(false);

  const refreshStatus = useCallback(async () => {
    if (polling.current) {
      return null;
    }
    polling.current = true;
    const result = await call("get_cpu_status");
    polling.current = false;
    if (!alive.current) {
      return null;
    }
    if (result.success) {
      setStatus(result.data);
      setStatusError(null);
    } else {
      setStatusError(result.error);
    }
    return result;
  }, [call]);

  useEffect(() => {
    alive.current = true;
    (async () => {
      const [statusResult, settingsResult] = await Promise.all([
        refreshStatus(),
        call("get_cpu_settings"),
      ]);
      if (!alive.current) {
        return;
      }
      if (statusResult) {
        notify(statusResult, true);
      }
      if (settingsResult.success) {
        setSettings(settingsResult.data);
      } else {
        notify(settingsResult);
      }
    })();
    const timer = window.setInterval(refreshStatus, STATUS_POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refreshStatus, call, notify]);

  const applyGovernor = async (governor: string) => {
    setApplying(governor);
    const result = await call("set_cpu_governor", governor);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus(result.data);
      setSettings((prev) => (prev ? { ...prev, saved_governor: governor } : prev));
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const applyClock = async (mhz: number | null) => {
    setApplying(mhz === null ? "clock-auto" : "clock");
    const result = await call("set_cpu_clock", mhz);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus(result.data);
      setSettings((prev) => (prev ? { ...prev, saved_clock: result.data.locked_mhz } : prev));
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const saveRestore = async (checked: boolean) => {
    setSavingSettings(true);
    const result = await call("set_cpu_settings", checked);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setSettings(result.data);
    }
    notify(result, true);
    setSavingSettings(false);
  };

  const loading = status === null && statusError === null;
  const driver = status?.driver ?? null;
  const governors = status?.governors ?? [];
  const active = status?.active ?? [];
  const current = active.length === 1 ? active[0] : null;
  const busy = applying !== null;

  let governorValue: ReactNode = "Unavailable";
  if (loading) {
    governorValue = <InlineSpinner />;
  } else if (current) {
    governorValue = governorInfo(current, driver).label;
  } else if (active.length > 1) {
    governorValue = "Mixed";
  }

  const locked = status?.locked_mhz ?? null;
  const freqDescription = [
    status?.freq_peak_mhz != null ? `Peak ${formatFreq(status.freq_peak_mhz)}` : null,
    locked !== null
      ? `Locked at ${formatFreq(locked)}`
      : status?.hw_min_mhz != null && status?.hw_max_mhz != null
        ? `Range ${formatFreq(status.hw_min_mhz)} – ${formatFreq(status.hw_max_mhz)}`
        : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const savedParts = [
    settings?.saved_governor != null ? governorInfo(settings.saved_governor, driver).label : null,
    settings?.saved_clock != null ? `the ${formatFreq(settings.saved_clock)} clock lock` : null,
  ].filter(Boolean);
  const restoreDescription = savedParts.length
    ? `Re-applies ${savedParts.join(" and ")} when Decky starts. The kernel picks its default governor and clock range at boot.`
    : "Re-applies your last governor and clock lock when Decky starts. The kernel picks its default governor and clock range at boot.";

  return (
    <>
      <PanelSection title="CPU Frequency">
        <PanelSectionRow>
          <Field
            label="Governor"
            icon={<FaTachometerAlt />}
            description={
              statusError ?? (active.length > 1 ? `CPUs use ${active.join(", ")}` : undefined)
            }
          >
            {governorValue}
          </Field>
        </PanelSectionRow>
        {status !== null && (
          <>
            <PanelSectionRow>
              <Field label="Frequency" icon={<FaMicrochip />} description={freqDescription || undefined}>
                {status.freq_avg_mhz != null ? formatFreq(status.freq_avg_mhz) : "Unknown"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Driver" description={`${status.policy_count} frequency policies`}>
                {driver ?? "Unknown"}
              </Field>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      {governors.length > 0 && (
        <PanelSection title={`Governors (${governors.length})`}>
          {chunk(governors, 2).map((row, rowIndex) => (
            <ButtonGrid key={row.join("|")} columns={2}>
              {row.map((id, index) => {
                const info = governorInfo(id, driver);
                return (
                  <DialogButton
                    key={id}
                    className={gridButtonClass(rowIndex * 2 + index, governors.length, 2)}
                    disabled={busy}
                    onClick={() => applyGovernor(id)}
                    style={{ borderBottom: `2px solid ${current === id ? ACCENT : "transparent"}` }}
                  >
                    {applying === id ? (
                      <InlineSpinner />
                    ) : (
                      <div className="ps5hw-stack">
                        <span>{info.label}</span>
                        <span className="ps5hw-sub">{info.description}</span>
                      </div>
                    )}
                  </DialogButton>
                );
              })}
            </ButtonGrid>
          ))}
        </PanelSection>
      )}
      <ClockLockSection
        description="Pins every CPU to this clock, whatever the governor."
        hwMin={status?.hw_min_mhz ?? null}
        hwMax={status?.hw_max_mhz ?? null}
        steps={status?.available_mhz ?? []}
        fallbackStep={CPU_CLOCK_STEP}
        locked={locked}
        busy={busy}
        applying={applying}
        onApply={applyClock}
      />
      <PanelSection title="Advanced">
        <PanelSectionRow>
          <ToggleField
            label="Restore on Startup"
            description={restoreDescription}
            checked={settings?.restore_on_boot ?? false}
            disabled={settings === null || savingSettings}
            onChange={saveRestore}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

const GpuTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({ backend }) => {
  const { call, notify } = backend;
  const [status, setStatus] = useState<GpuStatusData | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [settings, setSettings] = useState<GpuSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const alive = useRef<boolean>(true);
  const polling = useRef<boolean>(false);

  const refreshStatus = useCallback(async () => {
    if (polling.current) {
      return null;
    }
    polling.current = true;
    const result = await call("get_gpu_status");
    polling.current = false;
    if (!alive.current) {
      return null;
    }
    if (result.success) {
      setStatus(result.data);
      setStatusError(null);
    } else {
      setStatusError(result.error);
    }
    return result;
  }, [call]);

  useEffect(() => {
    alive.current = true;
    (async () => {
      const [statusResult, settingsResult] = await Promise.all([
        refreshStatus(),
        call("get_gpu_settings"),
      ]);
      if (!alive.current) {
        return;
      }
      if (statusResult) {
        notify(statusResult, true);
      }
      if (settingsResult.success) {
        setSettings(settingsResult.data);
      } else {
        notify(settingsResult);
      }
    })();
    const timer = window.setInterval(refreshStatus, STATUS_POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refreshStatus, call, notify]);

  const applyGovernor = async (governor: string) => {
    setApplying(governor);
    const result = await call("set_gpu_governor", governor);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus(result.data);
      setSettings((prev) => (prev ? { ...prev, saved_governor: governor } : prev));
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const applyClock = async (mhz: number | null) => {
    setApplying(mhz === null ? "clock-auto" : "clock");
    const result = await call("set_gpu_clock", mhz);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus(result.data);
      setSettings((prev) => (prev ? { ...prev, saved_clock: result.data.locked_mhz } : prev));
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const saveRestore = async (checked: boolean) => {
    setSavingSettings(true);
    const result = await call("set_gpu_settings", checked);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setSettings(result.data);
    }
    notify(result, true);
    setSavingSettings(false);
  };

  const loading = status === null && statusError === null;
  const governors = status?.governors ?? [];
  const current = status?.active ?? null;
  const busy = applying !== null;

  let governorValue: ReactNode = "Unavailable";
  if (loading) {
    governorValue = <InlineSpinner />;
  } else if (current) {
    governorValue = gpuGovernorInfo(current).label;
  }

  const locked = status?.locked_mhz ?? null;
  const freqDescription = [
    status?.target_mhz != null ? `Target ${formatFreq(status.target_mhz)}` : null,
    locked !== null
      ? `Locked at ${formatFreq(locked)}`
      : status?.min_mhz != null && status?.max_mhz != null
        ? `Range ${formatFreq(status.min_mhz)} – ${formatFreq(status.max_mhz)}`
        : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const savedParts = [
    settings?.saved_governor != null ? gpuGovernorInfo(settings.saved_governor).label : null,
    settings?.saved_clock != null ? `the ${formatFreq(settings.saved_clock)} clock lock` : null,
  ].filter(Boolean);
  const restoreDescription = savedParts.length
    ? `Re-applies ${savedParts.join(" and ")} when Decky starts. The kernel starts the GPU on Ondemand at boot.`
    : "Re-applies your last GPU governor and clock lock when Decky starts. The kernel starts the GPU on Ondemand at boot.";

  return (
    <>
      <PanelSection title="GPU Frequency">
        <PanelSectionRow>
          <Field label="Governor" icon={<FaTachometerAlt />} description={statusError ?? undefined}>
            {governorValue}
          </Field>
        </PanelSectionRow>
        {status !== null && (
          <>
            <PanelSectionRow>
              <Field label="Clock" icon={<FaCube />} description={freqDescription || undefined}>
                {status.freq_mhz != null ? formatFreq(status.freq_mhz) : "Unknown"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Device">{status.device}</Field>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      {governors.length > 0 && (
        <PanelSection title={`Governors (${governors.length})`}>
          {chunk(governors, 2).map((row, rowIndex) => (
            <ButtonGrid key={row.join("|")} columns={2}>
              {row.map((id, index) => {
                const info = gpuGovernorInfo(id);
                return (
                  <DialogButton
                    key={id}
                    className={gridButtonClass(rowIndex * 2 + index, governors.length, 2)}
                    disabled={busy}
                    onClick={() => applyGovernor(id)}
                    style={{ borderBottom: `2px solid ${current === id ? ACCENT : "transparent"}` }}
                  >
                    {applying === id ? (
                      <InlineSpinner />
                    ) : (
                      <div className="ps5hw-stack">
                        <span>{info.label}</span>
                        <span className="ps5hw-sub">{info.description}</span>
                      </div>
                    )}
                  </DialogButton>
                );
              })}
            </ButtonGrid>
          ))}
        </PanelSection>
      )}
      <ClockLockSection
        description="Pins the GPU to this clock, whatever the governor. The firmware still overrides it while the CPU boosts."
        hwMin={status?.hw_min_mhz ?? null}
        hwMax={status?.hw_max_mhz ?? null}
        steps={status?.available_mhz ?? []}
        fallbackStep={GPU_CLOCK_STEP}
        locked={locked}
        busy={busy}
        applying={applying}
        onApply={applyClock}
      />
      <PanelSection title="Advanced">
        <PanelSectionRow>
          <ToggleField
            label="Restore on Startup"
            description={restoreDescription}
            checked={settings?.restore_on_boot ?? false}
            disabled={settings === null || savingSettings}
            onChange={saveRestore}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

const LedTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({ backend }) => {
  const { call, notify } = backend;
  const [presets, setPresets] = useState<string[] | null>(null);
  const [animated, setAnimated] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<boolean>(true);
  const [pending, setPending] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loop, setLoop] = useState<LedSettingsData | null>(null);
  const [loopSeconds, setLoopSeconds] = useState<number>(LED_LOOP_DEFAULT);
  const [savingLoop, setSavingLoop] = useState<boolean>(false);
  const alive = useRef<boolean>(true);
  const loopTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(
    async (quiet: boolean) => {
      setLoading(true);
      const result = await call("get_led_presets");
      if (!alive.current) {
        return;
      }
      if (result.success) {
        setPresets(result.data.presets);
        setAnimated(new Set(result.data.animated));
        setError(null);
      } else {
        setPresets(null);
        setError(result.error);
      }
      notify(result, quiet);
      setLoading(false);
    },
    [call, notify],
  );

  useEffect(() => {
    alive.current = true;
    refresh(true);
    (async () => {
      const result = await call("get_led_settings");
      if (!alive.current) {
        return;
      }
      if (result.success) {
        setLoop(result.data);
        setLoopSeconds(result.data.loop_seconds);
        setActive(result.data.preset);
      } else {
        notify(result);
      }
    })();
    return () => {
      alive.current = false;
      window.clearTimeout(loopTimer.current);
    };
  }, [refresh, call, notify]);

  const apply = async (preset: string) => {
    setPending(preset);
    const result = await call("set_led_preset", preset);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setActive(result.data.preset);
      setLoop(result.data);
    }
    notify(result);
    setPending(null);
  };

  const saveLoop = async (enabled: boolean | null, seconds: number | null) => {
    setSavingLoop(true);
    const result = await call("set_led_settings", enabled, seconds);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setLoop(result.data);
    }
    notify(result, true);
    setSavingLoop(false);
  };

  const changeLoopSeconds = (value: number) => {
    setLoopSeconds(value);
    window.clearTimeout(loopTimer.current);
    loopTimer.current = window.setTimeout(() => saveLoop(null, value), THRESHOLD_SAVE_DELAY_MS);
  };

  const available = useMemo(() => new Set(presets ?? []), [presets]);
  const isAvailable = (id: string) => presets === null || available.has(id) || id === "off";
  const busy = loading || pending !== null;
  const loopEnabled = loop?.loop_enabled ?? false;

  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return (presets ?? []).filter(
      (id) => !query || id.includes(query) || prettifyPreset(id).toLowerCase().includes(query),
    );
  }, [presets, filter]);

  let loopStatus = "Off";
  if (loopEnabled && loop?.looping && active) {
    loopStatus = `Looping ${prettifyPreset(active)}`;
  } else if (loopEnabled) {
    loopStatus = "Waiting for an animated preset";
  }

  const presetDescription = (id: string) => {
    const tags: string[] = [];
    if (active === id) {
      tags.push(loopEnabled && animated.has(id) ? "Active · looping" : "Active");
    } else if (animated.has(id)) {
      tags.push("Animated");
    }
    return tags.length ? tags.join(" · ") : undefined;
  };

  return (
    <>
      <PanelSection title="LED Presets">
        <PanelSectionRow>
          <Field
            label="Active Preset"
            icon={<FaLightbulb />}
            description={error ?? undefined}
          >
            {loading ? <InlineSpinner /> : active ? prettifyPreset(active) : "Unknown"}
          </Field>
        </PanelSectionRow>
        {chunk(CURATED_PRESETS, 2).map((row, rowIndex) => (
          <ButtonGrid key={row.map((p) => p.id).join("|")} columns={2}>
            {row.map((preset, index) => {
              const selected = active === preset.id;
              return (
                <DialogButton
                  key={preset.id}
                  className={gridButtonClass(rowIndex * 2 + index, CURATED_PRESETS.length, 2)}
                  disabled={busy || !isAvailable(preset.id)}
                  onClick={() => apply(preset.id)}
                  style={{ borderBottom: `2px solid ${selected ? ACCENT : "transparent"}` }}
                >
                  {pending === preset.id ? <InlineSpinner /> : preset.label}
                </DialogButton>
              );
            })}
          </ButtonGrid>
        ))}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => refresh(false)}>
            <ButtonLabel icon={<FaSyncAlt />} label="Refresh Presets" busy={loading} />
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Animations">
        <PanelSectionRow>
          <ToggleField
            label="Loop Animations"
            description="Replays breathe, pulse and other animated presets so they keep going."
            checked={loopEnabled}
            disabled={loop === null || savingLoop}
            onChange={(checked) => saveLoop(checked, null)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Replay Every"
            description="Match this to how long the animation runs."
            value={loopSeconds}
            min={LED_LOOP_MIN}
            max={LED_LOOP_MAX}
            step={1}
            showValue
            valueSuffix=" s"
            resetValue={LED_LOOP_DEFAULT}
            disabled={!loopEnabled}
            onChange={changeLoopSeconds}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Loop Status" icon={<FaRedo />}>
            {loopStatus}
          </Field>
        </PanelSectionRow>
      </PanelSection>
      {presets !== null && presets.length > 0 && (
        <PanelSection title={`All Presets (${presets.length})`}>
          <PanelSectionRow>
            <TextField
              label="Filter"
              value={filter}
              bShowClearAction
              onChange={(e) => setFilter(e.target.value)}
            />
          </PanelSectionRow>
          {filtered.map((id) => (
            <PanelSectionRow key={id}>
              <ButtonItem
                layout="inline"
                label={prettifyPreset(id)}
                description={presetDescription(id)}
                disabled={busy}
                onClick={() => apply(id)}
              >
                {pending === id ? <InlineSpinner /> : "Apply"}
              </ButtonItem>
            </PanelSectionRow>
          ))}
          {filtered.length === 0 && (
            <PanelSectionRow>
              <Field label="No presets match" focusable={false} />
            </PanelSectionRow>
          )}
        </PanelSection>
      )}
    </>
  );
};

const Content: FC = () => {
  const backend = useBackend();
  const [tab, setTab] = useState<TabId>(lastTab);

  const selectTab = (next: TabId) => {
    lastTab = next;
    setTab(next);
  };

  return (
    <>
      <style>{STYLES}</style>
      <PanelSection>
        <TabBar active={tab} onChange={selectTab} />
      </PanelSection>
      {tab === "fan" && <FanTab backend={backend} />}
      {tab === "cpu" && <CpuTab backend={backend} />}
      {tab === "gpu" && <GpuTab backend={backend} />}
      {tab === "led" && <LedTab backend={backend} />}
    </>
  );
};

export default definePlugin(() => ({
  name: PLUGIN_TITLE,
  titleView: <div className={staticClasses.Title}>{PLUGIN_TITLE}</div>,
  content: <Content />,
  icon: <FaMicrochip />,
}));
