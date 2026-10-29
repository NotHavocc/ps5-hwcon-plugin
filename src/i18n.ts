/**
 * Small, dependency-free catalog for the Decky plugin bundle.
 *
 * The English source text is the fallback. To add a language, add an entry to
 * `catalogs`; no component code needs to change. The active language follows
 * the browser locale supplied by Decky.
 */
type Values = Record<string, string | number>;

const sv: Record<string, string> = {
  "Full Speed": "Full fart",
  Manual: "Manuell",
  Curve: "Kurva",
  Quiet: "Tyst",
  Default: "Standard",
  Balanced: "Balanserad",
  Cool: "Sval",
  "Max Cooling": "Maximal kylning",
  "Kernel default": "Kärnans standardvärde",
  "100% at {{temperature}} °C": "100 % vid {{temperature}} °C",
  "Ignores the curve": "Ignorerar kurvan",
  Target: "Målvärde",
  "Hold a temperature": "Håll en temperatur",
  "Speed per temperature": "Hastighet per temperatur",
  Off: "Av",
  "White Bright": "Klarvit",
  "Blue Rich": "Klarblå",
  Purple: "Lila",
  "Orange Breathe": "Orange andning",
  "Pink Breathe": "Rosa andning",
  Performance: "Prestanda",
  Powersave: "Energisparläge",
  "Highest clocks": "Högsta klockfrekvenser",
  "Lowest clocks": "Lägsta klockfrekvenser",
  "Follows scheduler load": "Följer schemaläggarens belastning",
  "Jumps up under load": "Ökar snabbt vid belastning",
  "Ramps up gradually": "Ökar gradvis",
  "Speed set by a program": "Hastighet som anges av ett program",
  "Biased to max clocks": "Prioriterar högsta klockfrekvenser",
  "Firmware managed": "Styrs av inbyggd programvara",
  "Follows GPU load": "Följer GPU-belastningen",
  "Highest clock": "Högsta klockfrekvens",
  "Lowest clock": "Lägsta klockfrekvens",
  "Clock set by a program": "Klockfrekvens som anges av ett program",
  Fan: "Fläkt",
  "Manual Clock": "Manuell klockfrekvens",
  "Clock Lock": "Lås klockfrekvens",
  Automatic: "Automatiskt",
  "Clock (MHz)": "Klockfrekvens (MHz)",
  "Lock Clock": "Lås klockfrekvens",
  Unknown: "Okänd",
  "Edit Point": "Redigera punkt",
  Stop: "Stopp",
  "Stop Temperature": "Stopptemperatur",
  Temperature: "Temperatur",
  "Fan Speed": "Fläkthastighet",
  Revert: "Återställ",
  "Apply Curve": "Tillämpa kurva",
  "Fan curves need a kernel with the ps5_fan hwmon driver.":
    "Fläktkurvor kräver en kärna med drivrutinen ps5_fan hwmon.",
  "Custom curve": "Anpassad kurva",
  "Cooling · full speed": "Kyler · full fart",
  "Overheated · alarm sounded": "Överhettad · larmet ljöd",
  Standby: "Vänteläge",
  Temperatures: "Temperaturer",
  "Reading sensors": "Läser av sensorer",
  "No temperature sensors found": "Inga temperatursensorer hittades",
  "Fan Target": "Fläktmål",
  Overheat: "Överhettning",
  Cooling: "Kyler",
  "Alarm sounded": "Larmet ljöd",
  "Fan Control": "Fläktstyrning",
  Presets: "Förinställningar",
  "Manual Target": "Manuellt mål",
  "Target Temperature (°C)": "Måltemperatur (°C)",
  "Lower targets ramp the fan earlier and louder.":
    "Lägre målvärden gör att fläkten ökar tidigare och låter mer.",
  "Apply Target": "Tillämpa mål",
  "Curve Presets": "Kurvförinställningar",
  "Fan Curve": "Fläktkurva",
  "Fan curve": "Fläktkurva",
  Advanced: "Avancerat",
  "Restore on Startup": "Återställ vid start",
  "Thermal Guard": "Temperaturskydd",
  "Overheat Alarm": "Överhettningslarm",
  "Overheat Threshold": "Överhettningsgräns",
  "CPU temperature used by Thermal Guard and Overheat Alarm.":
    "CPU-temperatur som används av temperaturskyddet och överhettningslarmet.",
  "Protection Status": "Skyddsstatus",
  "CPU Frequency": "CPU-frekvens",
  Governor: "Regulator",
  Frequency: "Frekvens",
  Driver: "Drivrutin",
  Governors: "Regulatorer",
  "GPU Frequency": "GPU-frekvens",
  Device: "Enhet",
  "LED Presets": "LED-förinställningar",
  "Active Preset": "Aktiv förinställning",
  "Refresh Presets": "Uppdatera förinställningar",
  Animations: "Animationer",
  "Loop Animations": "Upprepa animationer",
  "Replays breathe, pulse and other animated presets so they keep going.":
    "Upprepar andnings-, puls- och andra animerade förinställningar så att de fortsätter.",
  "Replay Every": "Upprepa var",
  "Match this to how long the animation runs.":
    "Anpassa detta till hur länge animationen körs.",
  "Loop Status": "Upprepningsstatus",
  "Waiting for an animated preset": "Väntar på en animerad förinställning",
  Active: "Aktiv",
  Animated: "Animerad",
  "Fan stops below {{temperature}} °C":
    "Fläkten stannar under {{temperature}} °C",
  "Point {{point}}: {{temperature}} °C → {{percent}}%":
    "Punkt {{point}}: {{temperature}} °C → {{percent}} %",
  "Allowed {{minimum}}–{{maximum}}%": "Tillåtet: {{minimum}}–{{maximum}} %",
  "Allowed {{minimum}}–{{maximum}} °C": "Tillåtet: {{minimum}}–{{maximum}} °C",
  "The last point always runs the fan at full speed.":
    "Den sista punkten kör alltid fläkten med full fart.",
  "The diamond is where the fan stops. Above {{temperature}} °C the kernel always runs it at full speed.":
    "Diamanten visar var fläkten stannar. Över {{temperature}} °C kör kärnan alltid fläkten med full fart.",
  Unavailable: "Inte tillgänglig",
  Mixed: "Blandad",
  "Cooling · restores {{temperature}} °C":
    "Kyler · återställer {{temperature}} °C",
  "Standby · CPU {{temperature}}": "Vänteläge · CPU {{temperature}}",
  "Run the fan at full speed when the CPU reaches the threshold, then go back to the previous mode once it is {{degrees}} °C cooler.":
    "Kör fläkten med full fart när CPU:n når gränsvärdet och återgå sedan till föregående läge när den har svalnat {{degrees}} °C.",
  "Switch to Max Cooling ({{maximum}} °C) when the CPU reaches the threshold, then restore your target once it is {{degrees}} °C cooler.":
    "Byt till maximal kylning ({{maximum}} °C) när CPU:n når gränsvärdet och återställ sedan ditt mål när den har svalnat {{degrees}} °C.",
  "{{count}} frequency policies": "{{count}} frekvensprinciper",
  "Governors ({{count}})": "Regulatorer ({{count}})",
  "Pins every CPU to this clock, whatever the governor.":
    "Låser varje CPU till denna klockfrekvens, oavsett regulator.",
  "Pins the GPU to this clock, whatever the governor. The firmware still overrides it while the CPU boosts.":
    "Låser GPU:n till denna klockfrekvens, oavsett regulator. Den inbyggda programvaran åsidosätter den ändå när CPU:n använder turbofrekvens.",
  "Looping {{preset}}": "Upprepar {{preset}}",
  "Active · looping": "Aktiv · upprepas",
  "All Presets ({{count}})": "Alla förinställningar ({{count}})",
  Filter: "Filtrera",
  Apply: "Tillämpa",
  "No presets match": "Inga förinställningar matchar",
  "Mode {{mode}}": "Läge {{mode}}",
  "Kernel governor": "Kärnregulator",
  "This kernel controls the fan by curve, so a target is applied as a curve that reaches full speed just above it. Editing the curve replaces the target.":
    "Den här kärnan styr fläkten med en kurva, så ett målvärde tillämpas som en kurva som når full fart strax över målvärdet. Om du redigerar kurvan ersätter den målvärdet.",
  "Re-applies your saved target or fan curve when Decky starts. The kernel resets the curve to its quiet default at boot.":
    "Återställer ditt sparade mål eller din fläktkurva när Decky startar. Kärnan återställer kurvan till det tysta standardvärdet vid uppstart.",
  "Re-applies the last target or curve you apply when Decky starts. The kernel resets the curve to its quiet default at boot.":
    "Återställer det senaste mål eller den senaste kurva du tillämpar när Decky startar. Kärnan återställer kurvan till det tysta standardvärdet vid uppstart.",
  "Re-applies {{temperature}} °C when Decky starts. The kernel resets the target to {{default}} °C at boot.":
    "Återställer {{temperature}} °C när Decky startar. Kärnan återställer målvärdet till {{default}} °C vid uppstart.",
  "Re-applies your last target when Decky starts. The kernel resets the target to {{default}} °C at boot.":
    "Återställer ditt senaste målvärde när Decky startar. Kärnan återställer målvärdet till {{default}} °C vid uppstart.",
  Clock: "Klockfrekvens",
  "{{frequency}} clock lock": "klockfrekvenslås på {{frequency}}",
  " and ": " och ",
  "Re-applies {{settings}} when Decky starts. The kernel picks its default governor and clock range at boot.":
    "Återställer {{settings}} när Decky startar. Kärnan väljer sin standardregulator och sitt klockfrekvensintervall vid uppstart.",
  "Re-applies your last governor and clock lock when Decky starts. The kernel picks its default governor and clock range at boot.":
    "Återställer din senaste regulator och ditt senaste klockfrekvenslås när Decky startar. Kärnan väljer sin standardregulator och sitt klockfrekvensintervall vid uppstart.",
  "Re-applies {{settings}} when Decky starts. The kernel starts the GPU on Ondemand at boot.":
    "Återställer {{settings}} när Decky startar. Kärnan startar GPU:n med Ondemand vid uppstart.",
  "Re-applies your last GPU governor and clock lock when Decky starts. The kernel starts the GPU on Ondemand at boot.":
    "Återställer din senaste GPU-regulator och ditt senaste klockfrekvenslås när Decky startar. Kärnan startar GPU:n med Ondemand vid uppstart.",
  "Re-applies {{preset}} when Decky starts. The kernel picks its default LED at boot.":
    "Återställer {{preset}} när Decky startar. Kärnan väljer sin standard-LED vid uppstart.",
  "Re-applies your last LED preset when Decky starts. The kernel picks its default LED at boot.":
    "Återställer din senaste LED-förinställning när Decky startar. Kärnan väljer sin standard-LED vid uppstart.",
};

const catalogs: Record<string, Record<string, string>> = { sv };

function currentLanguage(): string {
  if (typeof navigator === "undefined") return "en";
  const locale = navigator.languages?.[0] ?? navigator.language ?? "en";
  return locale.toLowerCase().split("-")[0];
}

/** Returns a localized UI string, with English as a safe fallback. */
export function t(source: string, values: Values = {}): string {
  const template = catalogs[currentLanguage()]?.[source] ?? source;
  return template.replace(/{{(\w+)}}/g, (match, name: string) =>
    String(values[name] ?? match),
  );
}

export const supportedLocales = ["en", ...Object.keys(catalogs)];
