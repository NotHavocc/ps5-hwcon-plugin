export interface BackendSuccess<T> {
  success: true;
  message: string;
  data: T;
}

export interface BackendFailure {
  success: false;
  error: string;
}

export type BackendResult<T = null> = BackendSuccess<T> | BackendFailure;

export interface FanTargetData {
  temp: number;
}

export interface TemperatureSensor {
  id: string;
  chip: string;
  label: string;
  celsius: number;
}

export interface TemperaturesData {
  sensors: TemperatureSensor[];
}

export interface GuardState {
  enabled: boolean;
  active: boolean;
  threshold: number;
  restore_target: number | null;
  cpu: number | null;
  alarm_enabled: boolean;
  alarm_active: boolean;
}

export interface FanStatusData {
  target: number | null;
  target_error: string | null;
  sensors: TemperatureSensor[];
  guard: GuardState;
}

export interface FanSettings {
  restore_on_boot: boolean;
  guard_enabled: boolean;
  guard_threshold: number;
  alarm_enabled: boolean;
  saved_target: number | null;
}

export type FanSettingsUpdate = Partial<
  Pick<FanSettings, "restore_on_boot" | "guard_enabled" | "guard_threshold" | "alarm_enabled">
>;

export interface FanSettingsData {
  settings: FanSettings;
  guard: GuardState;
}

export interface FanPreset {
  id: string;
  label: string;
  temp: number;
}

export interface LedPresetsData {
  presets: string[];
  animated: string[];
}

export interface LedSettingsData {
  loop_enabled: boolean;
  loop_seconds: number;
  preset: string | null;
  looping: boolean;
}

export interface LedPresetData extends LedSettingsData {
  preset: string;
}

export interface CpuStatusData {
  driver: string | null;
  governors: string[];
  active: string[];
  policy_count: number;
  freq_avg_mhz: number | null;
  freq_peak_mhz: number | null;
  hw_min_mhz: number | null;
  hw_max_mhz: number | null;
  available_mhz: number[];
  limit_min_mhz: number | null;
  limit_max_mhz: number | null;
  locked_mhz: number | null;
}

export interface CpuSettings {
  restore_on_boot: boolean;
  saved_governor: string | null;
  saved_clock: number | null;
}

export interface GpuStatusData {
  device: string;
  governors: string[];
  active: string | null;
  freq_mhz: number | null;
  target_mhz: number | null;
  min_mhz: number | null;
  max_mhz: number | null;
  available_mhz: number[];
  hw_min_mhz: number | null;
  hw_max_mhz: number | null;
  locked_mhz: number | null;
}

export interface GpuSettings {
  restore_on_boot: boolean;
  saved_governor: string | null;
  saved_clock: number | null;
}

export interface GovernorInfo {
  label: string;
  description: string;
}

export type FanTargetResult = BackendResult<FanTargetData>;
export type TemperaturesResult = BackendResult<TemperaturesData>;
export type FanStatusResult = BackendResult<FanStatusData>;
export type FanSettingsResult = BackendResult<FanSettingsData>;
export type LedPresetsResult = BackendResult<LedPresetsData>;
export type LedPresetResult = BackendResult<LedPresetData>;
export type LedSettingsResult = BackendResult<LedSettingsData>;
export type CpuStatusResult = BackendResult<CpuStatusData>;
export type CpuSettingsResult = BackendResult<CpuSettings>;
export type GpuStatusResult = BackendResult<GpuStatusData>;
export type GpuSettingsResult = BackendResult<GpuSettings>;

export type FanSettingsArgs = [
  restore_on_boot: boolean | null,
  guard_enabled: boolean | null,
  guard_threshold: number | null,
  alarm_enabled: boolean | null,
];

export interface BackendMethods {
  get_fan_target: { args: []; result: FanTargetResult };
  set_fan_target: { args: [temp: number]; result: FanTargetResult };
  get_temperatures: { args: []; result: TemperaturesResult };
  get_fan_status: { args: []; result: FanStatusResult };
  get_fan_settings: { args: []; result: FanSettingsResult };
  set_fan_settings: { args: FanSettingsArgs; result: FanSettingsResult };
  get_led_presets: { args: []; result: LedPresetsResult };
  set_led_preset: { args: [preset: string]; result: LedPresetResult };
  get_led_settings: { args: []; result: LedSettingsResult };
  set_led_settings: {
    args: [loop_enabled: boolean | null, loop_seconds: number | null];
    result: LedSettingsResult;
  };
  get_cpu_status: { args: []; result: CpuStatusResult };
  set_cpu_governor: { args: [governor: string]; result: CpuStatusResult };
  set_cpu_clock: { args: [mhz: number | null]; result: CpuStatusResult };
  get_cpu_settings: { args: []; result: CpuSettingsResult };
  set_cpu_settings: { args: [restore_on_boot: boolean]; result: CpuSettingsResult };
  get_gpu_status: { args: []; result: GpuStatusResult };
  set_gpu_governor: { args: [governor: string]; result: GpuStatusResult };
  set_gpu_clock: { args: [mhz: number | null]; result: GpuStatusResult };
  get_gpu_settings: { args: []; result: GpuSettingsResult };
  set_gpu_settings: { args: [restore_on_boot: boolean]; result: GpuSettingsResult };
}

export type BackendMethod = keyof BackendMethods;

export type TabId = "fan" | "cpu" | "gpu" | "led";

export interface CuratedPreset {
  id: string;
  label: string;
}
