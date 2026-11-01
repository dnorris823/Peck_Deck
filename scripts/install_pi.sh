#!/usr/bin/env bash
# Install or reinstall a Peck Deck feeder on a Raspberry Pi.
#
# One run sets up system packages, the venv, the models,
# raspberry_pi_code/.env, the device token, MediaMTX, and the peck-deck and
# mediamtx systemd units. It also saves the Wi-Fi networks for the feeder's
# house. docs/feeder-onboarding.md says when to run it. SETUP.md has each step
# by hand.
#
#   scripts/install_pi.sh            install, or reinstall
#   scripts/install_pi.sh --dry-run  show what it would change, change nothing
#   scripts/install_pi.sh --wifi     only save the Wi-Fi networks
#
# It is safe to run twice. Every saved answer is the default, so Enter keeps
# it. DEVICE_TOKEN and every .env key it does not own stay as they are.
#
# Run it as the user the service runs as, not as root. It calls sudo itself.
# Answers come from prompts, never from arguments, so no password lands in
# shell history. No secret goes on a sudo command line either, because sudo
# logs its command lines to the journal.

set -euo pipefail

MEDIAMTX_VERSION=v1.21.3
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PI_ENV=$REPO/raspberry_pi_code/.env
VENV=$REPO/.venv
# The tests point these at a temp dir, so the script runs off a Pi.
ETC_DIR=${PECK_ETC_DIR:-/etc/peck_deck}
UNIT_DIR=${PECK_UNIT_DIR:-/etc/systemd/system}
MEDIAMTX_DIR=${PECK_MEDIAMTX_DIR:-/opt/mediamtx}

# The Pi's .env example ships this cache path. The feeder guide uses one in the
# user's home instead, which needs no sudo.
EXAMPLE_CACHE_DIR=/var/lib/peck_deck/cache
# NetworkManager profile names this script owns. The home network wins over the
# rescue hotspot when both are in range.
HOME_WIFI=peck-home
RESCUE_WIFI=peck-rescue
RESCUE_PRIORITY=-10

DRY_RUN=0
WIFI_ONLY=0
WARNINGS=()

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

say() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() {
  printf '    WARNING: %s\n' "$*" >&2
  WARNINGS+=("$*")
}
die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

# Hide every secret value in text the dry run prints.
mask() {
  sed -E 's/^([A-Za-z0-9_]*(PASS|PASSWORD|PSK|TOKEN)[A-Za-z0-9_]*=).+/\1********/'
}

# Run a command that changes the system. The dry run prints it instead.
run() {
  if ((DRY_RUN)); then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# --- Env files --------------------------------------------------------------

# Print KEY's value from env file text on stdin. Empty if the key is absent.
env_get() {
  local key=$1 line
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      printf '%s' "${line#*=}"
      return
    fi
  done
}

# Print FILE with KEY set to VALUE. Every other line stays as it was.
env_set() {
  local file=$1 key=$2 value=$3 line found=0
  while IFS= read -r line || [[ -n $line ]]; do
    if [[ $line == "$key="* ]]; then
      if ((!found)); then
        printf '%s=%s\n' "$key" "$value"
      fi
      found=1
    else
      printf '%s\n' "$line"
    fi
  done <"$file"
  if ((!found)); then
    printf '%s=%s\n' "$key" "$value"
  fi
}

# A root-only file's text, or nothing if it does not exist. Read-only, so the
# dry run does it too.
root_read() {
  sudo cat "$1" 2>/dev/null || true
}

# Install SOURCE at DEST as root with MODE, if the content differs.
# Returns 0 if it changed DEST, 1 if DEST already matched.
install_root_file() {
  local source=$1 dest=$2 mode=$3
  if [[ "$(root_read "$dest")" == "$(cat "$source")" ]]; then
    info "$dest is up to date"
    return 1
  fi
  if ((DRY_RUN)); then
    info "would write $dest, mode $mode:"
    mask <"$source" | sed 's/^/      | /'
  else
    sudo install -m "$mode" "$source" "$dest"
    info "wrote $dest"
  fi
  return 0
}

# --- Prompts ----------------------------------------------------------------

# An env file holds VALUE unquoted, so it must not need quoting.
valid_env_value() {
  local v=$1
  if [[ -z $v ]]; then
    echo "This cannot be empty."
    return 1
  fi
  if [[ $v == *[\"\'\\]* ]]; then
    echo "Quotes and backslashes do not survive the env file. Change it in the app, then try again."
    return 1
  fi
  if [[ $v =~ ^[[:space:]] || $v =~ [[:space:]]$ ]]; then
    echo "It cannot start or end with a space."
    return 1
  fi
}

valid_host() {
  if [[ ! $1 =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "Give an address such as 100.101.102.103, with no http:// and no port."
    return 1
  fi
}

valid_optional() {
  if [[ -n $1 && $1 =~ ^[[:space:]]|[[:space:]]$ ]]; then
    echo "It cannot start or end with a space."
    return 1
  fi
}

# WPA2 personal passwords are 8 to 63 characters.
valid_psk() {
  if ((${#1} < 8 || ${#1} > 63)); then
    echo "A Wi-Fi password has 8 to 63 characters."
    return 1
  fi
}

valid_psk_or_keep() {
  if [[ -n $1 ]]; then
    valid_psk "$1"
  fi
}

# ask VAR PROMPT DEFAULT [secret] [VALIDATOR]
# Enter takes DEFAULT. A secret prompt does not echo, and never shows DEFAULT.
ask() {
  local var=$1 prompt=$2 default=$3 secret=${4:-} validate=${5:-} reply hint msg
  while true; do
    if [[ -n $secret ]]; then
      hint=${default:+ (Enter keeps the saved one)}
      read -rs -p "$prompt$hint: " reply || die "No answer for: $prompt"
      # -s swallows the Enter, so end the prompt's line.
      if [[ -t 0 ]]; then
        echo >&2
      fi
    else
      hint=${default:+ [$default]}
      read -r -p "$prompt$hint: " reply || die "No answer for: $prompt"
    fi
    reply=${reply:-$default}
    if [[ -n $validate ]] && ! msg=$("$validate" "$reply"); then
      printf '    %s\n' "$msg" >&2
      continue
    fi
    printf -v "$var" '%s' "$reply"
    return
  done
}

# --- Wi-Fi ------------------------------------------------------------------

profile_exists() {
  nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq "$1"
}

profile_ssid() {
  nmcli -g 802-11-wireless.ssid connection show "$1" 2>/dev/null || true
}

# Save a Wi-Fi network for later. It never connects to it, so the link this
# Pi uses now stays up. NetworkManager joins a saved network on its own when
# the current one goes away.
#
# The password goes to nmcli through stdin and a root shell, not on sudo's
# command line, which the journal records.
save_wifi() {
  local name=$1 ssid=$2 psk=$3 priority=$4 verb=add
  if profile_exists "$name"; then
    verb=modify
  fi
  if ((DRY_RUN)); then
    info "would $verb Wi-Fi profile $name: network \"$ssid\", priority $priority"
    return
  fi
  # shellcheck disable=SC2016 # $1 to $5 belong to the inner shell.
  printf '%s\n' "$psk" | sudo sh -c '
    IFS= read -r psk
    if [ "$1" = add ]; then
      nmcli connection add type wifi con-name "$2" ssid "$3" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" \
        connection.autoconnect yes connection.autoconnect-priority "$4" >/dev/null
    else
      nmcli connection modify "$2" 802-11-wireless.ssid "$3" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" \
        connection.autoconnect yes connection.autoconnect-priority "$4"
    fi
  ' sh "$verb" "$name" "$ssid" "$priority"
  info "saved Wi-Fi profile $name for \"$ssid\""
}

# Ask for one network and save it. Enter on the name skips it.
setup_wifi() {
  local name=$1 label=$2 priority=$3 ssid psk old_ssid
  old_ssid=$(profile_ssid "$name")
  ask ssid "$label name, or Enter to skip" "$old_ssid" "" valid_optional
  if [[ -z $ssid ]]; then
    info "skipped $label"
    return
  fi
  if [[ $ssid == "$old_ssid" ]]; then
    ask psk "$label password, or Enter to keep it" "" secret valid_psk_or_keep
    if [[ -z $psk ]]; then
      info "kept $label \"$ssid\""
      return
    fi
  else
    ask psk "$label password" "" secret valid_psk
  fi
  save_wifi "$name" "$ssid" "$psk" "$priority"
}

wifi_step() {
  say "Wi-Fi at the feeder's house"
  if ! command -v nmcli >/dev/null; then
    warn "nmcli is missing, so no Wi-Fi was saved. Raspberry Pi OS Bookworm has it."
    return
  fi
  info "Saved networks are used later. The Pi stays on the network it uses now."
  setup_wifi "$HOME_WIFI" "Home Wi-Fi" 0
  info "The rescue hotspot is the phone hotspot of the person at that house."
  info "If their Wi-Fi changes, they turn it on, and the feeder comes back online."
  setup_wifi "$RESCUE_WIFI" "Rescue phone hotspot" "$RESCUE_PRIORITY"
}

# --- Arguments --------------------------------------------------------------

while (($#)); do
  case $1 in
    --dry-run) DRY_RUN=1 ;;
    --wifi) WIFI_ONLY=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "Unknown argument: $1. Try --help." ;;
  esac
  shift
done

if ((EUID == 0)); then
  die "Run this as the user the feeder runs as, not as root. It calls sudo itself."
fi
if [[ $REPO =~ [[:space:]] ]]; then
  die "The repo path $REPO has a space in it. systemd units cannot hold that. Clone it to ~/peck_deck."
fi
if ((DRY_RUN)); then
  say "Dry run. Nothing on this Pi changes."
fi

# Ask for the sudo password once, up front.
sudo -v

if ((WIFI_ONLY)); then
  wifi_step
  exit 0
fi

# --- Questions --------------------------------------------------------------

say "Checking the tailnet"
command -v tailscale >/dev/null || die "Tailscale is not installed. Do step 2 of docs/feeder-onboarding.md first."
PI_TAILNET_IP=$(tailscale ip -4 2>/dev/null | head -n 1 || true)
[[ -n $PI_TAILNET_IP ]] || die "This Pi is not on the tailnet. Run 'sudo tailscale up' and sign in first."
info "this Pi is $PI_TAILNET_IP on the tailnet"

say "Questions. Enter keeps the value in brackets."
OLD_PI_ENV=""
if [[ -f $PI_ENV ]]; then
  OLD_PI_ENV=$(cat "$PI_ENV")
fi
OLD_OWNER_ENV=$(root_read "$ETC_DIR/owner.env")
OLD_MTX_ENV=$(root_read "$ETC_DIR/mediamtx.env")

old_backend=$(env_get BACKEND_URL <<<"$OLD_PI_ENV")
old_pc=${old_backend#*://}
old_pc=${old_pc%%[:/]*}
# The example's placeholder address is not a real answer.
if [[ $old_pc == 192.168.1.100 ]]; then
  old_pc=""
fi
old_name=$(env_get DEVICE_NAME <<<"$OLD_OWNER_ENV")

ask PC_ADDRESS "Gaming PC tailnet address (run 'tailscale ip -4' on the PC)" "$old_pc" "" valid_host
ask FEEDER_NAME "Feeder name, exactly as registered in the app" "${old_name:-$(hostname)}" "" valid_env_value
ask ACCOUNT_EMAIL "App email of the person at the feeder's house" \
  "$(env_get PECK_OWNER_EMAIL <<<"$OLD_OWNER_ENV")" "" valid_env_value
ask ACCOUNT_PASSWORD "Their app password" \
  "$(env_get PECK_OWNER_PASSWORD <<<"$OLD_OWNER_ENV")" secret valid_env_value
ask LIVE_USER "Live video user, LIVE_READ_USER in the backend .env" \
  "$(env_get MTX_AUTHINTERNALUSERS_1_USER <<<"$OLD_MTX_ENV")" "" valid_env_value
ask LIVE_PASSWORD "Live video password, LIVE_READ_PASSWORD in the backend .env" \
  "$(env_get MTX_AUTHINTERNALUSERS_1_PASS <<<"$OLD_MTX_ENV")" secret valid_env_value

BACKEND_URL=http://$PC_ADDRESS:8000
INFERENCE_URL=http://$PC_ADDRESS:8001

# --- Packages, venv, models -------------------------------------------------

say "System packages"
run sudo apt-get update -q
run sudo apt-get install -y -q git curl python3-venv python3-picamera2

say "Python environment"
# --system-site-packages, because picamera2 comes from apt.
if [[ -x $VENV/bin/python ]]; then
  info "$VENV exists"
else
  run python3 -m venv --system-site-packages "$VENV"
fi
run "$VENV/bin/python" -m pip install -q tflite-runtime -r "$REPO/raspberry_pi_code/requirements.txt"

say "Models"
# It skips a model that is already there.
run "$VENV/bin/python" "$REPO/scripts/fetch_models.py"

say "Camera"
if ! command -v rpicam-hello >/dev/null; then
  warn "rpicam-hello is missing, so the camera was not checked."
elif rpicam-hello --list-cameras 2>&1 | grep -q 'Available cameras'; then
  info "found a camera"
else
  warn "No camera found. Check the ribbon cable, then run 'rpicam-hello --list-cameras'."
fi

# --- The Pi's .env ----------------------------------------------------------

say "raspberry_pi_code/.env"
cache_dir=$(env_get CACHE_DIR <<<"$OLD_PI_ENV")
if [[ -z $cache_dir || $cache_dir == "$EXAMPLE_CACHE_DIR" ]]; then
  cache_dir=$HOME/peck_deck_cache
fi
new_env=$WORK/pi.env
if [[ -f $PI_ENV ]]; then
  cp "$PI_ENV" "$new_env"
else
  cp "$REPO/raspberry_pi_code/.env.example" "$new_env"
fi
for pair in "BACKEND_URL=$BACKEND_URL" "INFERENCE_SERVER_URL=$INFERENCE_URL" "CACHE_DIR=$cache_dir"; do
  env_set "$new_env" "${pair%%=*}" "${pair#*=}" >"$new_env.next"
  mv "$new_env.next" "$new_env"
done
if [[ -f $PI_ENV ]] && cmp -s "$new_env" "$PI_ENV"; then
  info "$PI_ENV is up to date"
elif ((DRY_RUN)); then
  info "would write $PI_ENV with:"
  printf '      | %s\n' "BACKEND_URL=$BACKEND_URL" "INFERENCE_SERVER_URL=$INFERENCE_URL" "CACHE_DIR=$cache_dir"
else
  cp "$new_env" "$PI_ENV"
  info "wrote $PI_ENV"
fi
# It holds the device token.
run chmod 600 "$PI_ENV"
run mkdir -p "$cache_dir"

# --- Root-only credential files ---------------------------------------------

say "$ETC_DIR"
run sudo install -d -m 700 "$ETC_DIR"
# Not the Pi's .env, on purpose. See SETUP.md section 9.
cat >"$WORK/owner.env" <<EOF
PECK_OWNER_EMAIL=$ACCOUNT_EMAIL
PECK_OWNER_PASSWORD=$ACCOUNT_PASSWORD
DEVICE_NAME=$FEEDER_NAME
EOF
install_root_file "$WORK/owner.env" "$ETC_DIR/owner.env" 600 || true

# Every feeder's MediaMTX uses the backend's one read user, or offers fail
# with 502. Only the tailnet address is known in advance at another house.
cat >"$WORK/mediamtx.env" <<EOF
MTX_AUTHINTERNALUSERS_1_USER=$LIVE_USER
MTX_AUTHINTERNALUSERS_1_PASS=$LIVE_PASSWORD
MTX_WEBRTCADDITIONALHOSTS=$PI_TAILNET_IP
EOF
install_root_file "$WORK/mediamtx.env" "$ETC_DIR/mediamtx.env" 600 || true

# --- MediaMTX ---------------------------------------------------------------

say "MediaMTX $MEDIAMTX_VERSION"
if [[ -x $MEDIAMTX_DIR/mediamtx ]] && "$MEDIAMTX_DIR/mediamtx" --version 2>/dev/null | grep -qF "$MEDIAMTX_VERSION"; then
  info "already installed"
elif ((DRY_RUN)); then
  info "would download, check and unpack $MEDIAMTX_VERSION into $MEDIAMTX_DIR"
else
  tarball=mediamtx_${MEDIAMTX_VERSION}_linux_arm64.tar.gz
  base=https://github.com/bluenviron/mediamtx/releases/download/$MEDIAMTX_VERSION
  (
    cd "$WORK"
    curl -fsSLO "$base/$tarball"
    curl -fsSLO "$base/checksums.sha256"
    grep -F "$tarball" checksums.sha256 | sha256sum -c - >/dev/null
  ) || die "The MediaMTX download failed its checksum. Nothing was installed. Run this again."
  sudo install -d "$MEDIAMTX_DIR"
  sudo tar -xzf "$WORK/$tarball" -C "$MEDIAMTX_DIR"
  info "installed $("$MEDIAMTX_DIR/mediamtx" --version)"
fi

# --- systemd units ----------------------------------------------------------

say "systemd units"
SERVICE_USER=$(id -un)
cat >"$WORK/peck-deck.service" <<EOF
# Written by scripts/install_pi.sh. SETUP.md section 9 explains each line.
[Unit]
Description=Peck Deck Pi Service
After=network-online.target
Wants=network-online.target
# A refused token makes the service exit non-zero, which re-runs the pre-step.
# These bound that restart loop.
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
User=$SERVICE_USER
WorkingDirectory=$REPO
# Root-only credentials for the pre-step. systemd reads them before it drops
# to User=. The leading - lets the service start without the file.
EnvironmentFile=-$ETC_DIR/owner.env
# Fetch the device token on every start. The leading - lets the Pi start and
# queue sightings while the gaming PC is off.
ExecStartPre=-$VENV/bin/python scripts/provision_device.py
ExecStart=$VENV/bin/python -m raspberry_pi_code.main
Restart=on-failure
RestartSec=10
# /run/peck-deck, for the live video demand socket.
RuntimeDirectory=peck-deck

[Install]
WantedBy=multi-user.target
EOF

cat >"$WORK/mediamtx.service" <<EOF
# Written by scripts/install_pi.sh. SETUP.md section 9 explains each line.
[Unit]
Description=MediaMTX live video for Peck Deck
After=network-online.target
Wants=network-online.target

[Service]
# The same user as peck-deck, so live_demand can open the demand socket.
User=$SERVICE_USER
WorkingDirectory=$REPO
# No leading -. Without the file, the unit fails rather than run with no
# reader able to log in.
EnvironmentFile=$ETC_DIR/mediamtx.env
ExecStart=$MEDIAMTX_DIR/mediamtx $REPO/raspberry_pi_code/live/mediamtx.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

UNITS_CHANGED=0
for unit in peck-deck.service mediamtx.service; do
  if install_root_file "$WORK/$unit" "$UNIT_DIR/$unit" 644; then
    UNITS_CHANGED=1
  fi
done
if ((UNITS_CHANGED)); then
  run sudo systemctl daemon-reload
fi

# --- Wi-Fi ------------------------------------------------------------------

wifi_step

# --- Reach the gaming PC ----------------------------------------------------

say "Gaming PC at $PC_ADDRESS"
if curl -fsS -m 5 -o /dev/null "$BACKEND_URL/ready"; then
  info "backend answers"
else
  die "The backend at $BACKEND_URL does not answer /ready. Start it on the gaming PC, then run this again. Your answers are saved."
fi
if curl -fsS -m 5 -o /dev/null "$INFERENCE_URL/health"; then
  info "Tier 2 answers"
else
  warn "Tier 2 at $INFERENCE_URL does not answer. The feeder classifies on the Pi until it does."
fi

# --- Device token -----------------------------------------------------------

say "Device token"
if ((DRY_RUN)); then
  info "would fetch the device token for \"$FEEDER_NAME\" as $ACCOUNT_EMAIL"
else
  # Assignments before the command put the credentials in its environment,
  # not on its command line.
  if ! out=$(cd "$REPO" && PECK_OWNER_EMAIL=$ACCOUNT_EMAIL PECK_OWNER_PASSWORD=$ACCOUNT_PASSWORD \
    DEVICE_NAME=$FEEDER_NAME "$VENV/bin/python" scripts/provision_device.py 2>&1); then
    printf '%s\n' "$out" | sed 's/^/    | /'
    die "Fetching the device token failed. Check the email, password and feeder name, then run this again."
  fi
  printf '%s\n' "$out" | sed 's/^/    | /'
  if grep -q 'registered new device' <<<"$out"; then
    warn "That account had no feeder named \"$FEEDER_NAME\", so this registered a new one." \
      "If you registered it in the app under another name, remove the extra feeder under Feeders." \
      "Set this one's City and State under Feeders, Details."
  fi
fi

# --- Start ------------------------------------------------------------------

say "Starting the services"
run sudo systemctl enable peck-deck mediamtx
run sudo systemctl restart peck-deck mediamtx
if ((!DRY_RUN)); then
  for unit in peck-deck mediamtx; do
    info "$unit: $(systemctl is-active "$unit" 2>/dev/null || true)"
  done
fi

if ((DRY_RUN)); then
  say "Dry run done. Nothing changed."
  exit 0
fi
say "Done"
if ((${#WARNINGS[@]})); then
  printf '    Read these before you hand the feeder over:\n'
  printf '    - %s\n' "${WARNINGS[@]}"
fi
info "Follow the logs: journalctl -u peck-deck -f"
info "Then run the desk test in SETUP.md section 10."
