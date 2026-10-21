#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/NotHavocc/ps5-hwcon-plugin.git"
REPO_REF=""
PLUGIN_DIR_NAME="ps5-hardware-control"
NODE_IMAGE="docker.io/library/node:20"
FORCE=0
UNINSTALL=0

usage() {
  cat <<EOF
Usage: $0 [options]

  --force        Install even if the PS5 kernel interfaces are missing
  --uninstall    Remove the plugin and restart Decky
  -h, --help     Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then
  BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'
else
  BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s  !%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s  ✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
  die "Run this as your normal user, not root. It asks for sudo when it needs it."
fi
command -v sudo >/dev/null || die "sudo is required"

HOMEBREW_DIR="$HOME/homebrew"
PLUGINS_DIR="$HOMEBREW_DIR/plugins"
TARGET_DIR="$PLUGINS_DIR/$PLUGIN_DIR_NAME"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ps5-hwcon-plugin"
SRC_DIR="$CACHE_DIR/src"

restart_decky() {
  step "Restarting Decky Loader"
  sudo systemctl restart plugin_loader
  ok "plugin_loader restarted"
}

if [ "$UNINSTALL" -eq 1 ]; then
  step "Removing $TARGET_DIR"
  sudo rm -rf -- "$TARGET_DIR"
  rm -rf -- "$CACHE_DIR"
  ok "Plugin removed (settings in $HOMEBREW_DIR/settings are kept)"
  restart_decky
  exit 0
fi

step "Checking Decky Loader"
if [ ! -d "$PLUGINS_DIR" ] || ! systemctl cat plugin_loader.service >/dev/null 2>&1; then
  if command -v ujust >/dev/null; then
    die "Decky Loader is not installed. Install it with 'ujust setup-decky', reboot into Game Mode, then rerun this script."
  fi
  die "Decky Loader is not installed. See https://decky.xyz, then rerun this script."
fi
ok "Found $PLUGINS_DIR"

step "Checking PS5 kernel interfaces"
missing=0
for path in /sys/bus/platform/devices/ps5-fan/target_temp /sys/class/misc/ps5_buzzer/beep; do
  if [ -e "$path" ]; then ok "$path"; else warn "missing: $path"; missing=1; fi
done
led_nodes=(/sys/class/leds/ps5:*)
if [ -e "${led_nodes[0]}" ]; then
  ok "/sys/class/leds/ps5:*"
else
  warn "missing: /sys/class/leds/ps5:*"
  missing=1
fi
if [ "$missing" -eq 1 ]; then
  if [ "$FORCE" -eq 1 ]; then
    warn "Continuing because of --force. The plugin won't control anything until the ps5-linux-patches kernel is running."
  else
    die "The ps5-linux-patches kernel doesn't seem to be running (uname -r: $(uname -r)). Boot it first, or pass --force."
  fi
fi

step "Fetching $REPO_URL"
command -v git >/dev/null || die "git is required"
case "$REPO_URL" in
  *CHANGE-ME*) die "REPO_URL at the top of install.sh still points to the placeholder. Set it to the plugin's git URL." ;;
esac
mkdir -p "$CACHE_DIR"
if [ -d "$SRC_DIR/.git" ] && [ "$(git -C "$SRC_DIR" remote get-url origin 2>/dev/null)" = "$REPO_URL" ]; then
  git -C "$SRC_DIR" fetch --tags --prune origin
else
  rm -rf -- "$SRC_DIR"
  git clone "$REPO_URL" "$SRC_DIR"
fi
if [ -n "$REPO_REF" ]; then
  git -C "$SRC_DIR" checkout --quiet "$REPO_REF"
  if git -C "$SRC_DIR" symbolic-ref -q HEAD >/dev/null; then
    git -C "$SRC_DIR" merge --ff-only --quiet "origin/$REPO_REF"
  fi
else
  default_branch="$(git -C "$SRC_DIR" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$default_branch" ]; then
    git -C "$SRC_DIR" checkout --quiet "${default_branch#origin/}"
    git -C "$SRC_DIR" merge --ff-only --quiet "$default_branch"
  fi
fi
for file in plugin.json package.json main.py; do
  [ -f "$SRC_DIR/$file" ] || die "$file not found in the repository. Is this the right repo?"
done
ok "Source at $(git -C "$SRC_DIR" rev-parse --short HEAD)"

step "Building the frontend"
build_cmd='if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi && npm run build'
if command -v npm >/dev/null; then
  (cd "$SRC_DIR" && sh -c "$build_cmd")
else
  runtime=""
  for candidate in podman docker; do
    if command -v "$candidate" >/dev/null; then runtime="$candidate"; break; fi
  done
  [ -n "$runtime" ] || die "Building needs Node.js, or podman/docker to run it in a container. Neither was found."
  warn "Node.js not found, building inside $runtime ($NODE_IMAGE)"
  "$runtime" run --rm -v "$SRC_DIR":/src:Z -w /src "$NODE_IMAGE" sh -c "$build_cmd"
fi
[ -f "$SRC_DIR/dist/index.js" ] || die "Build finished but dist/index.js is missing"
ok "Built dist/index.js"

step "Installing to $TARGET_DIR"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf -- "$STAGE_DIR"' EXIT
mkdir -p "$STAGE_DIR/dist"
cp "$SRC_DIR/plugin.json" "$SRC_DIR/package.json" "$SRC_DIR/main.py" "$STAGE_DIR/"
for optional in README.md LICENSE; do
  [ -f "$SRC_DIR/$optional" ] && cp "$SRC_DIR/$optional" "$STAGE_DIR/"
done
cp "$SRC_DIR"/dist/index.js* "$STAGE_DIR/dist/"
sudo rm -rf -- "$TARGET_DIR"
sudo mkdir -p "$TARGET_DIR"
sudo cp -r "$STAGE_DIR"/. "$TARGET_DIR"/
sudo chown -R root:root "$TARGET_DIR"
if command -v restorecon >/dev/null; then
  sudo restorecon -R "$TARGET_DIR" >/dev/null 2>&1 || true
fi
ok "Files installed"

since="$(date '+%Y-%m-%d %H:%M:%S')"
restart_decky

step "Waiting for the plugin to load"
loaded=0
for _ in $(seq 1 20); do
  if sudo journalctl -u plugin_loader --since "$since" --no-pager 2>/dev/null | grep -q "Loaded PS5 Hardware Control"; then
    loaded=1
    break
  fi
  sleep 1
done
if [ "$loaded" -eq 1 ]; then
  ok "PS5 Hardware Control loaded"
  printf '\n%sDone.%s Open the Quick Access Menu, go to the Decky tab, then PS5 Hardware Control.\n' "$BOLD" "$RESET"
else
  warn "Didn't see the plugin load within 20 s. Recent log lines:"
  sudo journalctl -u plugin_loader --since "$since" --no-pager | tail -20 >&2 || true
  exit 1
fi
