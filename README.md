<h1 align="center">ps5-hwcon-plugin</h1>

<p align="center">
  <img src="docs/screenshot-fan.png" alt="Fan tab" width="30%">
  &nbsp;
  <img src="docs/screenshot-led.png" alt="LED tab" width="30%">
  &nbsp;
  <img src="docs/screenshot-buzzer.png" alt="Buzzer tab" width="30%">
</p>

<p align="center">
  A <a href="https://decky.xyz">Decky Loader</a> plugin for PS5 Linux: fan target temperature, live temperatures, indicator LED presets and the chassis buzzer, all from the Quick Access Menu.
</p>

---

## Install

Run this on the PS5 as your normal user (not root):

```sh
curl -fsSL https://raw.githubusercontent.com/NotHavocc/ps5-hwcon-plugin/main/install.sh | bash
```

The installer:
- checks for Decky and the PS5 kernel interfaces
- clones this repo and builds the plugin. If Node.js isn't installed, as on stock Bazzite, it builds inside a podman or docker container.
- installs the plugin to `~/homebrew/plugins/ps5-hardware-control`
- restarts Decky and waits for the plugin to load

Run the same command again to update. Your settings are kept.

To uninstall:

```sh
curl -fsSL https://raw.githubusercontent.com/NotHavocc/ps5-hwcon-plugin/main/install.sh | bash -s -- --uninstall
```

### Requirements

- A PS5 running Linux with the [ps5-linux-patches](https://github.com/rmuxnet/ps5-linux-patches-1) kernel booted. The plugin only talks to the sysfs interfaces that kernel adds.
- [Decky Loader](https://decky.xyz) 3.0 or newer. On Bazzite: `ujust setup-decky`.
- `git`, plus either Node.js 18+ or podman/docker for the build.

## Features

### Fan

- **Temperatures**: live CPU (`k10temp`) readings, plus any other hwmon sensors, refreshed every 2 s.
- **Presets**: Quiet 85 °C, Default 80 °C, Balanced 72 °C, Cool 65 °C and Max Cooling 50 °C. A lower target spins the fan up earlier and louder.
- **Manual Target**: any target from 40 to 90 °C.
- **Restore on Startup**: re-applies your last target when Decky starts. The kernel resets it to 80 °C on every boot.
- **Thermal Guard**: when the CPU reaches the Overheat Threshold (80–100 °C, default 95), the fan switches to Max Cooling. Your target comes back once the CPU is 10 °C cooler.
- **Overheat Alarm**: plays the console's error beep once when the CPU reaches the threshold, and re-arms after it cools down.

Thermal Guard and Overheat Alarm run in the background, even with the menu closed.

### LED

- Quick buttons for Off, White Bright, Blue Rich, Purple, Orange Breathe and Pink Breathe.
- A searchable list of every preset the kernel exposes.
- **Loop Animations**: the firmware plays breathe and pulse animations once. This option replays them on an interval you choose (2–30 s), and keeps going in the background.

### Buzzer

- Short, Error and Long test beeps, plus Stop.

logs/PS5 Hardware Control/`.

## Credits

- [rmuxnet/ps5-linux-patches](https://github.com/rmuxnet/ps5-linux-patches-1) for the kernel drivers this plugin builds on.
- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
