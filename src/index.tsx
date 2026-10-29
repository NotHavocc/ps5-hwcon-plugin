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
import {
  FC,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  FaCheck,
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
  FaUndo,
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
  FanCurve,
  FanCurvePreset,
  FanHwmonStatus,
  FanPreset,
  FanSettings,
  FanSettingsUpdate,
  FanStatusData,
  FanStatusResult,
  FanUpdateResult,
  FanView,
  GovernorInfo,
  GpuSettings,
  GpuStatusData,
  LedSettingsData,
  TabId,
} from "./types";
import { t } from "./i18n";

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
const LIVE_COLOR = "#f0b44c";
const FAN_CURVE_TEMP_MIN = 20;
const FAN_CURVE_TEMP_MAX = 90;
const FAN_PWM_MAX = 255;
const FAN_MODE_FULL = 0;
const FAN_MODE_CURVE = 2;
const FAN_MODE_LABELS: Record<number, string> = {
  [FAN_MODE_FULL]: t("Full Speed"),
  1: t("Manual"),
  [FAN_MODE_CURVE]: t("Curve"),
};
const FAN_QUIET_TEMPS = [50, 60, 65, 70, 75, 80, 85, 87];
const FAN_QUIET_STOP = 45;
const FULL_SPEED_ID = "full";
const STOP_HANDLE = 0;

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
.ps5hw-note {
  font-size: 12px;
  line-height: 1.35;
  opacity: 0.7;
  padding: 4px 0;
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
  { id: "quiet", label: t("Quiet"), temp: 85 },
  { id: "default", label: t("Default"), temp: FAN_BOOT_TARGET },
  { id: "balanced", label: t("Balanced"), temp: 72 },
  { id: "cool", label: t("Cool"), temp: 65 },
  { id: "max", label: t("Max Cooling"), temp: FAN_MAX_COOLING },
];

const pwmToPercent = (pwm: number) => Math.round((pwm * 100) / FAN_PWM_MAX);
const percentToPwm = (percent: number) =>
  Math.round((percent * FAN_PWM_MAX) / 100);

const makeCurve = (stop: number, points: [number, number][]): FanCurve => ({
  stop,
  points: points.map(([temp, percent]) => [temp, percentToPwm(percent)]),
});

const FAN_CURVE_PRESETS: FanCurvePreset[] = [
  {
    id: "quiet",
    label: t("Quiet"),
    subtitle: t("Kernel default"),
    curve: null,
  },
  {
    id: "balanced",
    label: t("Balanced"),
    subtitle: t("100% at {{temperature}} °C", { temperature: 85 }),
    curve: makeCurve(40, [
      [45, 15],
      [55, 25],
      [60, 35],
      [65, 45],
      [70, 60],
      [75, 75],
      [80, 90],
      [85, 100],
    ]),
  },
  {
    id: "cool",
    label: t("Cool"),
    subtitle: t("100% at {{temperature}} °C", { temperature: 80 }),
    curve: makeCurve(35, [
      [40, 20],
      [50, 30],
      [55, 40],
      [60, 50],
      [65, 65],
      [70, 80],
      [75, 90],
      [80, 100],
    ]),
  },
];

const FULL_SPEED_PRESET: FanCurvePreset = {
  id: FULL_SPEED_ID,
  label: t("Full Speed"),
  subtitle: t("Ignores the curve"),
  curve: null,
};

const FAN_VIEWS: { id: FanView; label: string; description: string }[] = [
  { id: "target", label: t("Target"), description: t("Hold a temperature") },
  { id: "curve", label: t("Curve"), description: t("Speed per temperature") },
];

const CURATED_PRESETS: CuratedPreset[] = [
  { id: "off", label: t("Off") },
  { id: "white_bright", label: t("White Bright") },
  { id: "blue_rich", label: t("Blue Rich") },
  { id: "purple", label: t("Purple") },
  { id: "orange_breathe", label: t("Orange Breathe") },
  { id: "pink_breathe", label: t("Pink Breathe") },
];

const GOVERNORS: Record<string, GovernorInfo> = {
  performance: { label: t("Performance"), description: t("Highest clocks") },
  powersave: { label: t("Powersave"), description: t("Lowest clocks") },
  schedutil: { label: "Schedutil", description: t("Follows scheduler load") },
  ondemand: { label: "Ondemand", description: t("Jumps up under load") },
  conservative: { label: "Conservative", description: t("Ramps up gradually") },
  userspace: { label: "Userspace", description: t("Speed set by a program") },
};

const EPP_GOVERNORS: Record<string, GovernorInfo> = {
  performance: {
    label: t("Performance"),
    description: t("Biased to max clocks"),
  },
  powersave: { label: t("Powersave"), description: t("Firmware managed") },
};

const GPU_GOVERNORS: Record<string, GovernorInfo> = {
  simple_ondemand: { label: "Ondemand", description: t("Follows GPU load") },
  performance: { label: t("Performance"), description: t("Highest clock") },
  powersave: { label: t("Powersave"), description: t("Lowest clock") },
  userspace: { label: "Userspace", description: t("Clock set by a program") },
};

const TABS: { id: TabId; label: string; icon: JSX.Element }[] = [
  { id: "fan", label: t("Fan"), icon: <FaWind /> },
  { id: "cpu", label: "CPU", icon: <FaTachometerAlt /> },
  { id: "gpu", label: "GPU", icon: <FaCube /> },
  { id: "led", label: "LED", icon: <FaLightbulb /> },
];

let lastTab: TabId = "fan";
let lastFanView: FanView | null = null;
let lastCurveHandle = 1;

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

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

const fanModeLabel = (mode: number | null) =>
  mode === null
    ? t("Unknown")
    : (FAN_MODE_LABELS[mode] ?? t("Mode {{mode}}", { mode }));

const curvesEqual = (a: FanCurve, b: FanCurve) =>
  a.stop === b.stop &&
  a.points.length === b.points.length &&
  a.points.every(
    ([temp, pwm], i) => temp === b.points[i][0] && pwm === b.points[i][1],
  );

const curvePresetId = (curve: FanCurve) => {
  for (const preset of FAN_CURVE_PRESETS) {
    if (preset.curve === null) {
      const temps = curve.points.map(([temp]) => temp);
      if (
        curve.stop === FAN_QUIET_STOP &&
        temps.join() === FAN_QUIET_TEMPS.join()
      ) {
        return preset.id;
      }
    } else if (curvesEqual(curve, preset.curve)) {
      return preset.id;
    }
  }
  return null;
};

const handleBounds = (curve: FanCurve, handle: number) => {
  const { points, stop } = curve;
  if (handle === STOP_HANDLE) {
    return {
      tempLow: Math.min(FAN_CURVE_TEMP_MIN, stop),
      tempHigh: points[0][0] - 1,
      pwmLow: 0,
      pwmHigh: 0,
    };
  }
  const index = handle - 1;
  const last = points.length - 1;
  return {
    tempLow: index > 0 ? points[index - 1][0] + 1 : stop + 1,
    tempHigh: index < last ? points[index + 1][0] - 1 : FAN_CURVE_TEMP_MAX,
    pwmLow: index > 0 ? points[index - 1][1] : 0,
    pwmHigh: index < last ? points[index + 1][1] : FAN_PWM_MAX,
  };
};

const moveHandle = (
  curve: FanCurve,
  handle: number,
  temp: number,
  percent: number,
): FanCurve | null => {
  const bounds = handleBounds(curve, handle);
  const nextTemp = clamp(temp, bounds.tempLow, bounds.tempHigh);
  if (handle === STOP_HANDLE) {
    return nextTemp === curve.stop ? null : { ...curve, stop: nextTemp };
  }
  const [oldTemp, oldPwm] = curve.points[handle - 1];
  const nextPwm =
    pwmToPercent(oldPwm) === percent
      ? oldPwm
      : clamp(percentToPwm(percent), bounds.pwmLow, bounds.pwmHigh);
  if (nextTemp === oldTemp && nextPwm === oldPwm) {
    return null;
  }
  const points = curve.points.map((point, i): [number, number] =>
    i === handle - 1 ? [nextTemp, nextPwm] : point,
  );
  return { ...curve, points };
};

const isEppDriver = (driver: string | null) =>
  driver !== null && (driver.endsWith("-epp") || driver === "intel_pstate");

const governorInfo = (id: string, driver: string | null): GovernorInfo =>
  (isEppDriver(driver) ? EPP_GOVERNORS[id] : undefined) ??
  GOVERNORS[id] ?? {
    label: prettifyPreset(id),
    description: t("Kernel governor"),
  };

const gpuGovernorInfo = (id: string): GovernorInfo =>
  GPU_GOVERNORS[id] ?? {
    label: prettifyPreset(id),
    description: t("Kernel governor"),
  };

const InlineSpinner: FC = () => (
  <Spinner
    style={{ width: "1.2em", height: "1.2em", verticalAlign: "middle" }}
  />
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

const ButtonGrid: FC<{
  columns: number;
  className?: string;
  children: ReactNode;
}> = ({ columns, className, children }) => (
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
  index === count - 1 && count % columns !== 0
    ? "ps5hw-btn ps5hw-wide"
    : "ps5hw-btn";

const nearest = (value: number, choices: number[]) =>
  choices.reduce(
    (best, choice) =>
      Math.abs(choice - value) < Math.abs(best - value) ? choice : best,
    value,
  );

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
}> = ({
  description,
  hwMin,
  hwMax,
  steps,
  fallbackStep,
  locked,
  busy,
  applying,
  onApply,
}) => {
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

  const step =
    steps.length > 1
      ? steps.slice(1).reduce((acc, mhz, i) => gcd(acc, mhz - steps[i]), 0) ||
        fallbackStep
      : fallbackStep;

  return (
    <PanelSection title={t("Manual Clock")}>
      <PanelSectionRow>
        <Field
          label={t("Clock Lock")}
          icon={locked !== null ? <FaLock /> : <FaUnlock />}
        >
          {locked !== null ? formatFreq(locked) : t("Automatic")}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label={t("Clock (MHz)")}
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
          <ButtonLabel
            icon={<FaLock />}
            label={t("Lock Clock")}
            busy={applying === "clock"}
          />
        </DialogButton>
        <DialogButton
          className="ps5hw-btn"
          disabled={busy || locked === null}
          onClick={() => apply(null)}
        >
          <ButtonLabel
            icon={<FaUnlock />}
            label={t("Automatic")}
            busy={applying === "clock-auto"}
          />
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
        const result = await callBackend<
          BackendMethods[M]["args"],
          BackendMethods[M]["result"]
        >(method, ...args);
        if (result === null || typeof result !== "object") {
          return {
            success: false,
            error: `Unexpected response from ${method}`,
          } as BackendMethods[M]["result"];
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

const TabBar: FC<{ active: TabId; onChange: (tab: TabId) => void }> = ({
  active,
  onChange,
}) => (
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

const GRAPH_WIDTH = 300;
const GRAPH_HEIGHT = 170;
const GRAPH_LEFT = 32;
const GRAPH_RIGHT = 8;
const GRAPH_TOP = 8;
const GRAPH_BOTTOM = 20;

const CurveGraph: FC<{
  curve: FanCurve;
  selected: number;
  liveTemp: number | null;
  livePwm: number | null;
  dimmed: boolean;
}> = ({ curve, selected, liveTemp, livePwm, dimmed }) => {
  const plotWidth = GRAPH_WIDTH - GRAPH_LEFT - GRAPH_RIGHT;
  const plotHeight = GRAPH_HEIGHT - GRAPH_TOP - GRAPH_BOTTOM;
  const bottom = GRAPH_TOP + plotHeight;
  const right = GRAPH_LEFT + plotWidth;
  const x = (temp: number) =>
    GRAPH_LEFT +
    ((clamp(temp, FAN_CURVE_TEMP_MIN, FAN_CURVE_TEMP_MAX) -
      FAN_CURVE_TEMP_MIN) /
      (FAN_CURVE_TEMP_MAX - FAN_CURVE_TEMP_MIN)) *
      plotWidth;
  const y = (percent: number) => bottom - (percent / 100) * plotHeight;
  const color = dimmed ? "#67707b" : ACCENT;

  const points = curve.points.map(
    ([temp, pwm]) => [x(temp), y(pwmToPercent(pwm))] as const,
  );
  const [firstX, firstY] = points[0];
  const lastY = points[points.length - 1][1];
  const line = [
    ...points.map(([px, py]) => `${px},${py}`),
    `${right},${lastY}`,
  ].join(" ");
  const stopX = x(curve.stop);

  const tempTicks: number[] = [];
  for (let temp = FAN_CURVE_TEMP_MIN; temp <= FAN_CURVE_TEMP_MAX; temp += 10) {
    tempTicks.push(temp);
  }

  return (
    <svg
      viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
      style={{ width: "100%", height: "auto", display: "block" }}
      fontSize={9}
    >
      <rect
        x={GRAPH_LEFT}
        y={GRAPH_TOP}
        width={plotWidth}
        height={plotHeight}
        fill="rgba(255,255,255,0.04)"
      />
      {tempTicks.map((temp) => (
        <g key={`t${temp}`}>
          <line
            x1={x(temp)}
            x2={x(temp)}
            y1={GRAPH_TOP}
            y2={bottom}
            stroke="rgba(255,255,255,0.08)"
          />
          <text
            x={x(temp)}
            y={GRAPH_HEIGHT - 6}
            fill="#8b929a"
            textAnchor="middle"
          >
            {temp}°
          </text>
        </g>
      ))}
      {[0, 25, 50, 75, 100].map((percent) => (
        <g key={`p${percent}`}>
          <line
            x1={GRAPH_LEFT}
            x2={right}
            y1={y(percent)}
            y2={y(percent)}
            stroke="rgba(255,255,255,0.08)"
          />
          <text
            x={GRAPH_LEFT - 4}
            y={y(percent) + 3}
            fill="#8b929a"
            textAnchor="end"
          >
            {percent}%
          </text>
        </g>
      ))}
      {}
      <rect
        x={stopX}
        y={GRAPH_TOP}
        width={Math.max(0, firstX - stopX)}
        height={plotHeight}
        fill={color}
        opacity={0.12}
      />
      <path
        d={`M ${firstX},${bottom} L ${line} L ${right},${bottom} Z`}
        fill={color}
        opacity={0.18}
      />
      <line
        x1={firstX}
        x2={firstX}
        y1={bottom}
        y2={firstY}
        stroke={color}
        strokeDasharray="3 3"
      />
      <polyline points={line} fill="none" stroke={color} strokeWidth={2} />
      {liveTemp !== null && (
        <>
          <line
            x1={x(liveTemp)}
            x2={x(liveTemp)}
            y1={GRAPH_TOP}
            y2={bottom}
            stroke={LIVE_COLOR}
            strokeDasharray="1 3"
          />
          {livePwm !== null && (
            <circle
              cx={x(liveTemp)}
              cy={y(pwmToPercent(livePwm))}
              r={3.5}
              fill={LIVE_COLOR}
            />
          )}
        </>
      )}
      <polygon
        points={`${stopX},${bottom - 6} ${stopX + 6},${bottom} ${stopX},${bottom + 6} ${stopX - 6},${bottom}`}
        fill={selected === STOP_HANDLE ? color : "#23262e"}
        stroke={selected === STOP_HANDLE ? "#ffffff" : color}
        strokeWidth={2}
      />
      {points.map(([px, py], index) => {
        const active = selected === index + 1;
        return (
          <circle
            key={index}
            cx={px}
            cy={py}
            r={active ? 6 : 4.5}
            fill={active ? color : "#23262e"}
            stroke={active ? "#ffffff" : color}
            strokeWidth={2}
          />
        );
      })}
    </svg>
  );
};

const FanCurveEditor: FC<{
  curve: FanCurve;
  fan: FanHwmonStatus;
  busy: boolean;
  applying: string | null;
  onChange: (curve: FanCurve) => void;
  onApply: () => void;
  onRevert: () => void;
}> = ({ curve, fan, busy, applying, onChange, onApply, onRevert }) => {
  const [selected, setSelected] = useState<number>(lastCurveHandle);
  const bounds = handleBounds(curve, selected);
  const isStop = selected === STOP_HANDLE;
  const [temp, pwm] = isStop ? [curve.stop, 0] : curve.points[selected - 1];
  const percent = pwmToPercent(pwm);
  const edited = !curvesEqual(curve, fan.curve);

  const select = (handle: number) => {
    lastCurveHandle = handle;
    setSelected(handle);
  };

  const move = (nextTemp: number, nextPercent: number) => {
    const next = moveHandle(curve, selected, nextTemp, nextPercent);
    if (next !== null) {
      onChange(next);
    }
  };

  const pointDescription = isStop
    ? t("Fan stops below {{temperature}} °C", { temperature: curve.stop })
    : t("Point {{point}}: {{temperature}} °C → {{percent}}%", {
        point: selected,
        temperature: temp,
        percent,
      });

  let speedDescription = t("Allowed {{minimum}}–{{maximum}}%", {
    minimum: pwmToPercent(bounds.pwmLow),
    maximum: pwmToPercent(bounds.pwmHigh),
  });
  if (selected === curve.points.length) {
    speedDescription = t("The last point always runs the fan at full speed.");
  }

  return (
    <>
      <PanelSectionRow>
        <CurveGraph
          curve={curve}
          selected={selected}
          liveTemp={fan.temp}
          livePwm={fan.pwm}
          dimmed={busy}
        />
        <div className="ps5hw-note">
          {fan.temp !== null && (
            <span style={{ color: LIVE_COLOR }}>
              SoC {formatTemp(fan.temp)}
              {fan.pwm !== null ? ` · fan ${pwmToPercent(fan.pwm)}%` : ""}
              {" · "}
            </span>
          )}
          {t(
            "The diamond is where the fan stops. Above {{temperature}} °C the kernel always runs it at full speed.",
            { temperature: FAN_CURVE_TEMP_MAX },
          )}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label={t("Edit Point")}
          description={pointDescription}
          value={selected}
          min={STOP_HANDLE}
          max={curve.points.length}
          step={1}
          notchCount={curve.points.length + 1}
          notchLabels={[STOP_HANDLE, ...curve.points.map((_, i) => i + 1)].map(
            (handle) => ({
              notchIndex: handle,
              label: handle === STOP_HANDLE ? t("Stop") : `${handle}`,
              value: handle,
            }),
          )}
          notchTicksVisible
          disabled={busy}
          onChange={select}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label={isStop ? t("Stop Temperature") : t("Temperature")}
          description={t("Allowed {{minimum}}–{{maximum}} °C", {
            minimum: bounds.tempLow,
            maximum: bounds.tempHigh,
          })}
          value={temp}
          min={Math.min(FAN_CURVE_TEMP_MIN, temp)}
          max={FAN_CURVE_TEMP_MAX}
          step={1}
          showValue
          valueSuffix=" °C"
          disabled={busy}
          onChange={(value) => move(value, percent)}
        />
      </PanelSectionRow>
      {!isStop && (
        <PanelSectionRow>
          <SliderField
            label={t("Fan Speed")}
            description={speedDescription}
            value={percent}
            min={0}
            max={100}
            step={1}
            showValue
            valueSuffix="%"
            disabled={busy || bounds.pwmLow === bounds.pwmHigh}
            onChange={(value) => move(temp, value)}
          />
        </PanelSectionRow>
      )}
      <ButtonGrid columns={2}>
        <DialogButton
          className="ps5hw-btn"
          disabled={busy || !edited}
          onClick={onRevert}
        >
          <ButtonLabel icon={<FaUndo />} label={t("Revert")} />
        </DialogButton>
        <DialogButton
          className="ps5hw-btn"
          disabled={busy || (!edited && fan.mode === FAN_MODE_CURVE)}
          onClick={onApply}
        >
          <ButtonLabel
            icon={<FaCheck />}
            label={t("Apply Curve")}
            busy={applying === "custom"}
          />
        </DialogButton>
      </ButtonGrid>
    </>
  );
};

const FanTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({
  backend,
}) => {
  const { call, notify } = backend;
  const [status, setStatus] = useState<FanStatusData | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [slider, setSlider] = useState<number>(FAN_DEFAULT);
  const [curveDraft, setCurveDraft] = useState<FanCurve | null>(null);
  const [view, setView] = useState<FanView | null>(lastFanView);
  const [applying, setApplying] = useState<string | null>(null);
  const [settings, setSettings] = useState<FanSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const [threshold, setThreshold] = useState<number>(GUARD_DEFAULT);
  const alive = useRef<boolean>(true);
  const polling = useRef<boolean>(false);
  const sliderTouched = useRef<boolean>(false);
  const curveTouched = useRef<boolean>(false);
  const thresholdTimer = useRef<number | undefined>(undefined);

  const refreshStatus =
    useCallback(async (): Promise<FanStatusResult | null> => {
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
        setStatusError(result.data.fan_error ?? result.data.target_error);
        if (!sliderTouched.current && result.data.target !== null) {
          setSlider(clamp(result.data.target, FAN_MIN, FAN_MAX));
        }
        if (!curveTouched.current && result.data.fan !== null) {
          setCurveDraft(result.data.fan.curve);
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

  const mergeFan = (
    data: { curve?: FanCurve; mode?: number | null } | null,
  ) => {
    if (!data) {
      return;
    }
    setStatus((prev) =>
      prev?.fan
        ? {
            ...prev,
            fan: {
              ...prev.fan,
              ...(data.curve !== undefined ? { curve: data.curve } : {}),
              ...(data.mode !== undefined ? { mode: data.mode } : {}),
            },
          }
        : prev,
    );
    if (data.curve !== undefined) {
      setCurveDraft(data.curve);
      curveTouched.current = false;
    }
  };

  const applyTarget = async (source: string, temp: number) => {
    setApplying(source);
    const result = await call("set_fan_target", temp);
    if (!alive.current) {
      return;
    }
    if (result.success) {
      setStatus((prev) =>
        prev ? { ...prev, target: result.data.temp } : prev,
      );
      mergeFan(result.data);
      setSlider(temp);
      sliderTouched.current = false;
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const runFanUpdate = async (
    source: string,
    request: () => Promise<FanUpdateResult>,
  ) => {
    setApplying(source);
    const result = await request();
    if (!alive.current) {
      return;
    }
    if (result.success) {
      mergeFan(result.data);
    }
    notify(result);
    setApplying(null);
    refreshStatus();
  };

  const applyCurve = (source: string, curve: FanCurve | null) =>
    runFanUpdate(source, () =>
      curve === null ? call("reset_fan_curve") : call("set_fan_curve", curve),
    );

  const applyFullSpeed = () =>
    runFanUpdate(FULL_SPEED_ID, () => call("set_fan_mode", FAN_MODE_FULL));

  const editCurve = (curve: FanCurve) => {
    curveTouched.current = true;
    setCurveDraft(curve);
  };

  const revertCurve = () => {
    if (status?.fan) {
      setCurveDraft(status.fan.curve);
    }
    curveTouched.current = false;
  };

  const selectView = (next: FanView) => {
    lastFanView = next;
    setView(next);
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
      setStatus((prev) =>
        prev ? { ...prev, guard: result.data.guard } : prev,
      );
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
  const curveMode = status?.interface === "curve";
  const fan = curveMode ? (status?.fan ?? null) : null;
  const fullSpeed = fan?.mode === FAN_MODE_FULL;

  let activeView: FanView = "target";
  if (curveMode) {
    activeView = view ?? (target !== null ? "target" : "curve");
  }
  const targetView = activeView === "target";

  let viewNote: string | null = null;
  if (status !== null && !curveMode) {
    viewNote = t("Fan curves need a kernel with the ps5_fan hwmon driver.");
  } else if (curveMode && targetView) {
    viewNote = t(
      "This kernel controls the fan by curve, so a target is applied as a curve that reaches full speed just above it. Editing the curve replaces the target.",
    );
  }

  let selectedCurvePreset: string | null = null;
  if (fan?.mode === FAN_MODE_FULL) {
    selectedCurvePreset = FULL_SPEED_ID;
  } else if (fan?.mode === FAN_MODE_CURVE) {
    selectedCurvePreset = curvePresetId(fan.curve);
  }

  let targetValue: ReactNode = t("Unavailable");
  if (loading) {
    targetValue = <InlineSpinner />;
  } else if (target !== null) {
    targetValue = `${target} °C`;
  } else if (fan !== null) {
    targetValue = t("Custom curve");
  }

  let guardStatus = t("Off");
  if (guardEnabled && guard?.active && guard.kind === "curve") {
    guardStatus = t("Cooling · full speed");
  } else if (guardEnabled && guard?.active) {
    guardStatus = t("Cooling · restores {{temperature}} °C", {
      temperature: guard.restore_target ?? FAN_BOOT_TARGET,
    });
  } else if (alarmEnabled && guard?.alarm_active) {
    guardStatus = t("Overheated · alarm sounded");
  } else if (protectionEnabled && guard?.cpu != null) {
    guardStatus = t("Standby · CPU {{temperature}}", {
      temperature: formatTemp(guard.cpu),
    });
  } else if (protectionEnabled) {
    guardStatus = t("Standby");
  }

  let restoreDescription: string;
  let guardDescription: string;
  if (curveMode) {
    restoreDescription = settings?.saved_curve
      ? t(
          "Re-applies your saved target or fan curve when Decky starts. The kernel resets the curve to its quiet default at boot.",
        )
      : t(
          "Re-applies the last target or curve you apply when Decky starts. The kernel resets the curve to its quiet default at boot.",
        );
    guardDescription = t(
      "Run the fan at full speed when the CPU reaches the threshold, then go back to the previous mode once it is {{degrees}} °C cooler.",
      { degrees: GUARD_HYSTERESIS },
    );
  } else {
    restoreDescription =
      settings?.saved_target != null
        ? t(
            "Re-applies {{temperature}} °C when Decky starts. The kernel resets the target to {{default}} °C at boot.",
            { temperature: settings.saved_target, default: FAN_BOOT_TARGET },
          )
        : t(
            "Re-applies your last target when Decky starts. The kernel resets the target to {{default}} °C at boot.",
            { default: FAN_BOOT_TARGET },
          );
    guardDescription = t(
      "Switch to Max Cooling ({{maximum}} °C) when the CPU reaches the threshold, then restore your target once it is {{degrees}} °C cooler.",
      { maximum: FAN_MAX_COOLING, degrees: GUARD_HYSTERESIS },
    );
  }

  return (
    <>
      <PanelSection title={t("Temperatures")}>
        {loading && (
          <PanelSectionRow>
            <Field label={t("Reading sensors")}>
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
            <Field
              label={t("No temperature sensors found")}
              icon={<FaThermometerHalf />}
            />
          </PanelSectionRow>
        )}
        {curveMode ? (
          <PanelSectionRow>
            <Field
              label={t("Fan")}
              icon={<FaWind />}
              description={
                statusError ??
                (fan !== null ? `Mode: ${fanModeLabel(fan.mode)}` : undefined)
              }
            >
              {fan?.pwm != null
                ? `${pwmToPercent(fan.pwm)}%`
                : t("Unavailable")}
            </Field>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <Field
              label={t("Fan Target")}
              icon={<FaWind />}
              description={statusError ?? undefined}
            >
              {targetValue}
            </Field>
          </PanelSectionRow>
        )}
        {(guard?.active || guard?.alarm_active) && (
          <PanelSectionRow>
            <Field label={t("Overheat")} icon={<FaExclamationTriangle />}>
              {guard?.active ? t("Cooling") : t("Alarm sounded")}
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>
      {status !== null && (
        <PanelSection title={t("Fan Control")}>
          <ButtonGrid columns={2}>
            {FAN_VIEWS.map((option) => (
              <DialogButton
                key={option.id}
                className="ps5hw-btn"
                disabled={busy || (!curveMode && option.id === "curve")}
                onClick={() => selectView(option.id)}
                style={{
                  borderBottom: `2px solid ${activeView === option.id ? ACCENT : "transparent"}`,
                }}
              >
                <div className="ps5hw-stack">
                  <span>{option.label}</span>
                  <span className="ps5hw-sub">{option.description}</span>
                </div>
              </DialogButton>
            ))}
          </ButtonGrid>
          {viewNote && (
            <PanelSectionRow>
              <div className="ps5hw-note">{viewNote}</div>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}
      {targetView && (
        <>
          <PanelSection title={t("Presets")}>
            {curveMode && (
              <PanelSectionRow>
                <Field label={t("Fan Target")} icon={<FaWind />}>
                  {fullSpeed ? t("Full Speed") : targetValue}
                </Field>
              </PanelSectionRow>
            )}
            {chunk(FAN_PRESETS, 2).map((row, rowIndex) => (
              <ButtonGrid key={row.map((p) => p.id).join("|")} columns={2}>
                {row.map((preset, index) => {
                  const selected = target === preset.temp && !fullSpeed;
                  return (
                    <DialogButton
                      key={preset.id}
                      className={gridButtonClass(
                        rowIndex * 2 + index,
                        FAN_PRESETS.length,
                        2,
                      )}
                      disabled={busy}
                      onClick={() => applyTarget(preset.id, preset.temp)}
                      style={{
                        borderBottom: `2px solid ${selected ? ACCENT : "transparent"}`,
                      }}
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
          <PanelSection title={t("Manual Target")}>
            <PanelSectionRow>
              <SliderField
                label={t("Target Temperature (°C)")}
                description={t(
                  "Lower targets ramp the fan earlier and louder.",
                )}
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
                disabled={busy || loading || (slider === target && !fullSpeed)}
                onClick={() => applyTarget("manual", slider)}
              >
                <ButtonLabel
                  icon={<FaWind />}
                  label={t("Apply Target")}
                  busy={applying === "manual"}
                />
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        </>
      )}
      {!targetView && (
        <>
          <PanelSection title={t("Curve Presets")}>
            <ButtonGrid columns={2}>
              {[...FAN_CURVE_PRESETS, FULL_SPEED_PRESET].map((preset) => (
                <DialogButton
                  key={preset.id}
                  className="ps5hw-btn"
                  disabled={busy || fan === null}
                  onClick={() =>
                    preset.id === FULL_SPEED_ID
                      ? applyFullSpeed()
                      : applyCurve(preset.id, preset.curve)
                  }
                  style={{
                    borderBottom: `2px solid ${selectedCurvePreset === preset.id ? ACCENT : "transparent"}`,
                  }}
                >
                  {applying === preset.id ? (
                    <InlineSpinner />
                  ) : (
                    <div className="ps5hw-stack">
                      <span>{preset.label}</span>
                      <span className="ps5hw-sub">{preset.subtitle}</span>
                    </div>
                  )}
                </DialogButton>
              ))}
            </ButtonGrid>
          </PanelSection>
          <PanelSection title={t("Fan Curve")}>
            {fan !== null && curveDraft !== null ? (
              <FanCurveEditor
                curve={curveDraft}
                fan={fan}
                busy={busy}
                applying={applying}
                onChange={editCurve}
                onApply={() => applyCurve("custom", curveDraft)}
                onRevert={revertCurve}
              />
            ) : (
              <PanelSectionRow>
                <Field
                  label={t("Fan curve")}
                  description={statusError ?? undefined}
                >
                  {statusError ? t("Unavailable") : <InlineSpinner />}
                </Field>
              </PanelSectionRow>
            )}
          </PanelSection>
        </>
      )}
      <PanelSection title={t("Advanced")}>
        <PanelSectionRow>
          <ToggleField
            label={t("Restore on Startup")}
            description={restoreDescription}
            checked={settings?.restore_on_boot ?? false}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ restore_on_boot: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label={t("Thermal Guard")}
            description={guardDescription}
            checked={guardEnabled}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ guard_enabled: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label={t("Overheat Alarm")}
            description={`Play the console's error beep when the CPU reaches the threshold. It re-arms once the CPU is ${GUARD_HYSTERESIS} °C cooler.`}
            checked={alarmEnabled}
            disabled={settings === null || savingSettings}
            onChange={(checked) => saveSettings({ alarm_enabled: checked })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label={t("Overheat Threshold")}
            description={t(
              "CPU temperature used by Thermal Guard and Overheat Alarm.",
            )}
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
          <Field label={t("Protection Status")} icon={<FaShieldAlt />}>
            {guardStatus}
          </Field>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

const CpuTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({
  backend,
}) => {
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
      setSettings((prev) =>
        prev ? { ...prev, saved_governor: governor } : prev,
      );
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
      setSettings((prev) =>
        prev ? { ...prev, saved_clock: result.data.locked_mhz } : prev,
      );
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

  let governorValue: ReactNode = t("Unavailable");
  if (loading) {
    governorValue = <InlineSpinner />;
  } else if (current) {
    governorValue = governorInfo(current, driver).label;
  } else if (active.length > 1) {
    governorValue = t("Mixed");
  }

  const locked = status?.locked_mhz ?? null;
  const freqDescription = [
    status?.freq_peak_mhz != null
      ? `Peak ${formatFreq(status.freq_peak_mhz)}`
      : null,
    locked !== null
      ? `Locked at ${formatFreq(locked)}`
      : status?.hw_min_mhz != null && status?.hw_max_mhz != null
        ? `Range ${formatFreq(status.hw_min_mhz)} – ${formatFreq(status.hw_max_mhz)}`
        : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const savedParts = [
    settings?.saved_governor != null
      ? governorInfo(settings.saved_governor, driver).label
      : null,
    settings?.saved_clock != null
      ? t("{{frequency}} clock lock", {
          frequency: formatFreq(settings.saved_clock),
        })
      : null,
  ].filter(Boolean);
  const restoreDescription = savedParts.length
    ? t(
        "Re-applies {{settings}} when Decky starts. The kernel picks its default governor and clock range at boot.",
        { settings: savedParts.join(t(" and ")) },
      )
    : t(
        "Re-applies your last governor and clock lock when Decky starts. The kernel picks its default governor and clock range at boot.",
      );

  return (
    <>
      <PanelSection title={t("CPU Frequency")}>
        <PanelSectionRow>
          <Field
            label={t("Governor")}
            icon={<FaTachometerAlt />}
            description={
              statusError ??
              (active.length > 1 ? `CPUs use ${active.join(", ")}` : undefined)
            }
          >
            {governorValue}
          </Field>
        </PanelSectionRow>
        {status !== null && (
          <>
            <PanelSectionRow>
              <Field
                label={t("Frequency")}
                icon={<FaMicrochip />}
                description={freqDescription || undefined}
              >
                {status.freq_avg_mhz != null
                  ? formatFreq(status.freq_avg_mhz)
                  : t("Unknown")}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field
                label={t("Driver")}
                description={t("{{count}} frequency policies", {
                  count: status.policy_count,
                })}
              >
                {driver ?? t("Unknown")}
              </Field>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      {governors.length > 0 && (
        <PanelSection
          title={t("Governors ({{count}})", { count: governors.length })}
        >
          {chunk(governors, 2).map((row, rowIndex) => (
            <ButtonGrid key={row.join("|")} columns={2}>
              {row.map((id, index) => {
                const info = governorInfo(id, driver);
                return (
                  <DialogButton
                    key={id}
                    className={gridButtonClass(
                      rowIndex * 2 + index,
                      governors.length,
                      2,
                    )}
                    disabled={busy}
                    onClick={() => applyGovernor(id)}
                    style={{
                      borderBottom: `2px solid ${current === id ? ACCENT : "transparent"}`,
                    }}
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
        description={t("Pins every CPU to this clock, whatever the governor.")}
        hwMin={status?.hw_min_mhz ?? null}
        hwMax={status?.hw_max_mhz ?? null}
        steps={status?.available_mhz ?? []}
        fallbackStep={CPU_CLOCK_STEP}
        locked={locked}
        busy={busy}
        applying={applying}
        onApply={applyClock}
      />
      <PanelSection title={t("Advanced")}>
        <PanelSectionRow>
          <ToggleField
            label={t("Restore on Startup")}
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

const GpuTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({
  backend,
}) => {
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
      setSettings((prev) =>
        prev ? { ...prev, saved_governor: governor } : prev,
      );
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
      setSettings((prev) =>
        prev ? { ...prev, saved_clock: result.data.locked_mhz } : prev,
      );
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

  let governorValue: ReactNode = t("Unavailable");
  if (loading) {
    governorValue = <InlineSpinner />;
  } else if (current) {
    governorValue = gpuGovernorInfo(current).label;
  }

  const locked = status?.locked_mhz ?? null;
  const freqDescription = [
    status?.target_mhz != null
      ? `Target ${formatFreq(status.target_mhz)}`
      : null,
    locked !== null
      ? `Locked at ${formatFreq(locked)}`
      : status?.min_mhz != null && status?.max_mhz != null
        ? `Range ${formatFreq(status.min_mhz)} – ${formatFreq(status.max_mhz)}`
        : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const savedParts = [
    settings?.saved_governor != null
      ? gpuGovernorInfo(settings.saved_governor).label
      : null,
    settings?.saved_clock != null
      ? t("{{frequency}} clock lock", {
          frequency: formatFreq(settings.saved_clock),
        })
      : null,
  ].filter(Boolean);
  const restoreDescription = savedParts.length
    ? t(
        "Re-applies {{settings}} when Decky starts. The kernel starts the GPU on Ondemand at boot.",
        { settings: savedParts.join(t(" and ")) },
      )
    : t(
        "Re-applies your last GPU governor and clock lock when Decky starts. The kernel starts the GPU on Ondemand at boot.",
      );

  return (
    <>
      <PanelSection title={t("GPU Frequency")}>
        <PanelSectionRow>
          <Field
            label={t("Governor")}
            icon={<FaTachometerAlt />}
            description={statusError ?? undefined}
          >
            {governorValue}
          </Field>
        </PanelSectionRow>
        {status !== null && (
          <>
            <PanelSectionRow>
              <Field
                label={t("Clock")}
                icon={<FaCube />}
                description={freqDescription || undefined}
              >
                {status.freq_mhz != null
                  ? formatFreq(status.freq_mhz)
                  : t("Unknown")}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label={t("Device")}>{status.device}</Field>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      {governors.length > 0 && (
        <PanelSection
          title={t("Governors ({{count}})", { count: governors.length })}
        >
          {chunk(governors, 2).map((row, rowIndex) => (
            <ButtonGrid key={row.join("|")} columns={2}>
              {row.map((id, index) => {
                const info = gpuGovernorInfo(id);
                return (
                  <DialogButton
                    key={id}
                    className={gridButtonClass(
                      rowIndex * 2 + index,
                      governors.length,
                      2,
                    )}
                    disabled={busy}
                    onClick={() => applyGovernor(id)}
                    style={{
                      borderBottom: `2px solid ${current === id ? ACCENT : "transparent"}`,
                    }}
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
        description={t(
          "Pins the GPU to this clock, whatever the governor. The firmware still overrides it while the CPU boosts.",
        )}
        hwMin={status?.hw_min_mhz ?? null}
        hwMax={status?.hw_max_mhz ?? null}
        steps={status?.available_mhz ?? []}
        fallbackStep={GPU_CLOCK_STEP}
        locked={locked}
        busy={busy}
        applying={applying}
        onApply={applyClock}
      />
      <PanelSection title={t("Advanced")}>
        <PanelSectionRow>
          <ToggleField
            label={t("Restore on Startup")}
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

const LedTab: FC<{ backend: ReturnType<typeof useBackend> }> = ({
  backend,
}) => {
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

  const saveLoop = async (
    enabled: boolean | null,
    seconds: number | null,
    restore: boolean | null = null,
  ) => {
    setSavingLoop(true);
    const result = await call("set_led_settings", enabled, seconds, restore);
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
    loopTimer.current = window.setTimeout(
      () => saveLoop(null, value),
      THRESHOLD_SAVE_DELAY_MS,
    );
  };

  const available = useMemo(() => new Set(presets ?? []), [presets]);
  const isAvailable = (id: string) =>
    presets === null || available.has(id) || id === "off";
  const busy = loading || pending !== null;
  const loopEnabled = loop?.loop_enabled ?? false;

  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return (presets ?? []).filter(
      (id) =>
        !query ||
        id.includes(query) ||
        prettifyPreset(id).toLowerCase().includes(query),
    );
  }, [presets, filter]);

  let loopStatus = t("Off");
  if (loopEnabled && loop?.looping && active) {
    loopStatus = t("Looping {{preset}}", { preset: prettifyPreset(active) });
  } else if (loopEnabled) {
    loopStatus = t("Waiting for an animated preset");
  }

  const savedPreset = loop?.saved_preset ?? null;
  const restoreDescription = savedPreset
    ? t(
        "Re-applies {{preset}} when Decky starts. The kernel picks its default LED at boot.",
        { preset: prettifyPreset(savedPreset) },
      )
    : t(
        "Re-applies your last LED preset when Decky starts. The kernel picks its default LED at boot.",
      );

  const presetDescription = (id: string) => {
    const tags: string[] = [];
    if (active === id) {
      tags.push(
        loopEnabled && animated.has(id) ? t("Active · looping") : t("Active"),
      );
    } else if (animated.has(id)) {
      tags.push(t("Animated"));
    }
    return tags.length ? tags.join(" · ") : undefined;
  };

  return (
    <>
      <PanelSection title={t("LED Presets")}>
        <PanelSectionRow>
          <Field
            label={t("Active Preset")}
            icon={<FaLightbulb />}
            description={error ?? undefined}
          >
            {loading ? (
              <InlineSpinner />
            ) : active ? (
              prettifyPreset(active)
            ) : (
              t("Unknown")
            )}
          </Field>
        </PanelSectionRow>
        {chunk(CURATED_PRESETS, 2).map((row, rowIndex) => (
          <ButtonGrid key={row.map((p) => p.id).join("|")} columns={2}>
            {row.map((preset, index) => {
              const selected = active === preset.id;
              return (
                <DialogButton
                  key={preset.id}
                  className={gridButtonClass(
                    rowIndex * 2 + index,
                    CURATED_PRESETS.length,
                    2,
                  )}
                  disabled={busy || !isAvailable(preset.id)}
                  onClick={() => apply(preset.id)}
                  style={{
                    borderBottom: `2px solid ${selected ? ACCENT : "transparent"}`,
                  }}
                >
                  {pending === preset.id ? <InlineSpinner /> : preset.label}
                </DialogButton>
              );
            })}
          </ButtonGrid>
        ))}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            onClick={() => refresh(false)}
          >
            <ButtonLabel
              icon={<FaSyncAlt />}
              label={t("Refresh Presets")}
              busy={loading}
            />
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={t("Animations")}>
        <PanelSectionRow>
          <ToggleField
            label={t("Loop Animations")}
            description={t(
              "Replays breathe, pulse and other animated presets so they keep going.",
            )}
            checked={loopEnabled}
            disabled={loop === null || savingLoop}
            onChange={(checked) => saveLoop(checked, null)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label={t("Replay Every")}
            description={t("Match this to how long the animation runs.")}
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
          <Field label={t("Loop Status")} icon={<FaRedo />}>
            {loopStatus}
          </Field>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={t("Advanced")}>
        <PanelSectionRow>
          <ToggleField
            label={t("Restore on Startup")}
            description={restoreDescription}
            checked={loop?.restore_on_boot ?? false}
            disabled={loop === null || savingLoop}
            onChange={(checked) => saveLoop(null, null, checked)}
          />
        </PanelSectionRow>
      </PanelSection>
      {presets !== null && presets.length > 0 && (
        <PanelSection
          title={t("All Presets ({{count}})", { count: presets.length })}
        >
          <PanelSectionRow>
            <TextField
              label={t("Filter")}
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
                {pending === id ? <InlineSpinner /> : t("Apply")}
              </ButtonItem>
            </PanelSectionRow>
          ))}
          {filtered.length === 0 && (
            <PanelSectionRow>
              <Field label={t("No presets match")} focusable={false} />
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
