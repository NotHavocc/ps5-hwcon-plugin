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

export interface BuzzerData {
  level: number;
}

export type FanTargetResult = BackendResult<FanTargetData>;
export type TemperaturesResult = BackendResult<TemperaturesData>;
export type FanStatusResult = BackendResult<FanStatusData>;
export type FanSettingsResult = BackendResult<FanSettingsData>;
export type LedPresetsResult = BackendResult<LedPresetsData>;
export type LedPresetResult = BackendResult<LedPresetData>;
export type LedSettingsResult = BackendResult<LedSettingsData>;
export type BuzzerResult = BackendResult<BuzzerData>;
export type StopBuzzerResult = BackendResult<null>;

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
  test_buzzer: { args: [level: BuzzerLevel]; result: BuzzerResult };
  stop_buzzer: { args: []; result: StopBuzzerResult };
}

export type BackendMethod = keyof BackendMethods;

export enum BuzzerLevel {
  Short = 1,
  Error = 2,
  Long = 3,
}

export type TabId = "fan" | "led" | "buzzer";

export interface CuratedPreset {
  id: string;
  label: string;
}
