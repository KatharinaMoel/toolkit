#!/usr/bin/env bash
# test_fu_vpn.sh - checks fu-vpn (up, down, toggle, status, config) and
# install.sh in a throwaway HOME under mktemp.
#
#   bash net/fu-vpn/test_fu_vpn.sh
#
# openconnect, sudo, setsid, ip, curl, kill, notify-send and gnome-extensions
# are stubs, so no tunnel is built, sudo is never called and nothing outside
# the temp folder changes. The "link" of the tunnel is a file in the temp folder.
#
# Stub bodies and check expressions stay unexpanded on purpose: `stub` writes
# them into scripts and `check` evaluates them later, where RC, OUT and EXT are read.
# shellcheck disable=SC2016,SC2034
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FU_VPN="$HERE/fu-vpn"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/home/.config" XDG_DATA_HOME="$TMP/home/.local/share"
export STATE="$TMP/state" FU_VPN_WINDOW_SECONDS=0
mkdir -p "$HOME/.config/fu-vpn" "$STATE"
COOKIE_VALUE="secret-cookie-4711"
export COOKIE_VALUE

STUBS="$TMP/stubs"
mkdir -p "$STUBS"
stub() { printf '#!/usr/bin/env bash\n%s\n' "$2" > "$STUBS/$1"; chmod +x "$STUBS/$1"; }

# openconnect: --authenticate prints the login result (or nothing when
# $STATE/no-cookie exists); otherwise it is the tunnel: logs args and stdin,
# creates the link and writes the pid file.
stub openconnect '
printf "%s\n" "$*" >> "$STATE/openconnect.args"
if [ "$1" = --authenticate ]; then
  [ -e "$STATE/no-cookie" ] && exit 1
  [ -e "$STATE/auth-output" ] && { cat "$STATE/auth-output"; exit 0; }
  echo "COOKIE='"'"'$COOKIE_VALUE'"'"'"
  echo "HOST='"'"'vpn.example'"'"'"
  echo "CONNECT_URL='"'"'https://vpn.example/'"'"'"
  echo "FINGERPRINT='"'"'pin-sha256:abc'"'"'"
  exit 0
fi
cat > "$STATE/stdin"
while [ $# -gt 0 ]; do
  [ "$1" = --pid-file ] && { shift; echo 4242 > "$1"; }
  shift
done
touch "$STATE/link"'
stub sudo 'printf "%s\n" "$*" >> "$STATE/sudo.log"; exec "$@"'
stub setsid 'exec "$@"'
stub kill 'printf "%s\n" "$*" >> "$STATE/kill.log"; rm -f "$STATE/link"'
stub ip '
case "$*" in
  "link show fu-vpn") [ -e "$STATE/link" ] ;;
  "link set dev fu-vpn mtu "*) printf "%s\n" "$*" >> "$STATE/ip.log" ;;
  "-br addr show fu-vpn") [ -e "$STATE/link" ] && echo "fu-vpn UNKNOWN 10.0.0.2/32" ;;
  *) echo "unexpected ip $*" >&2; exit 99 ;;
esac'
stub curl 'printf "%s\n" "$*" >> "$STATE/curl.log"; printf "%s" "${CURL_CODE:-200}"'
stub notify-send 'printf "%s\n" "$*" >> "$STATE/notify.log"'
stub gnome-extensions 'printf "%s\n" "$*" >> "$STATE/gnome-extensions.log"'
export PATH="$STUBS:$PATH"

PASS=0 FAIL=0
ok()   { PASS=$((PASS + 1)); echo "ok   - $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "FAIL - $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/       /'; }
check() { if eval "$2"; then ok "$1"; else bad "$1" "${OUT:-}"; fi; }
reset() { rm -f "$STATE"/*; }

conf() { printf 'PIDFILE="%s/pid"\n%s\n' "$STATE" "${1:-}" > "$HOME/.config/fu-vpn/fu-vpn.conf"; }

# ---------- up ----------
reset; conf
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "up: exit 0" '[ $RC = 0 ]'
check "up: tunnel stands with MTU 1350" '[[ $OUT == *"Tunnel fu-vpn steht (MTU 1350)."* ]]'
check "up: link exists" '[ -e "$STATE/link" ]'
check "up: MTU lowered via sudo ip" 'grep -qx "link set dev fu-vpn mtu 1350" "$STATE/ip.log"'
check "up: cookie reaches the tunnel on stdin" '[ "$(cat "$STATE/stdin")" = "$COOKIE_VALUE" ]'
check "up: cookie never on screen" '[[ $OUT != *"$COOKIE_VALUE"* ]]'
check "up: cookie never in a command line" '! grep -q "$COOKIE_VALUE" "$STATE/openconnect.args" "$STATE/sudo.log"'
check "up: tunnel detached with setsid under sudo" 'grep -q "^setsid openconnect --cookie-on-stdin" "$STATE/sudo.log"'
check "up: server cert pinned" 'grep -q -- "--servercert pin-sha256:abc" "$STATE/openconnect.args"'
check "up: every step shown before it runs" '[ "$(grep -c "^> " <<<"$OUT")" = 3 ]'
check "up: notification" 'grep -q "FU-VPN an" "$STATE/notify.log"'

# ---------- up again ----------
: > "$STATE/openconnect.args"
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "up twice: exit 0, says it runs" '[ $RC = 0 ] && [[ $OUT == *"laeuft schon"* ]]'
check "up twice: no second login" '[ ! -s "$STATE/openconnect.args" ]'

# ---------- status ----------
OUT=$("$FU_VPN" status 2>&1); RC=$?
check "status without CHECK_URL: tunnel line only" '[ $RC = 0 ] && [[ $OUT == *"fu-vpn UNKNOWN"* ]] && [ ! -e "$STATE/curl.log" ]'
conf 'CHECK_URL=https://git.example/users/sign_in
CHECK_NAME="Test-GitLab"'
OUT=$("$FU_VPN" status 2>&1)
check "status with CHECK_URL: HTTP code" '[[ $OUT == *"Test-GitLab (HTTPS): 200"* ]]'
OUT=$(CURL_CODE=000 "$FU_VPN" status 2>&1)
check "status: 000 means unreachable" '[[ $OUT == *"Test-GitLab (HTTPS): nicht erreichbar"* ]]'

# ---------- down ----------
OUT=$("$FU_VPN" down 2>&1); RC=$?
check "down: exit 0" '[ $RC = 0 ] && [[ $OUT == *"Tunnel getrennt."* ]]'
check "down: kills the pid from the pid file" 'grep -qx 4242 "$STATE/kill.log"'
check "down: link gone" '[ ! -e "$STATE/link" ]'
OUT=$("$FU_VPN" status 2>&1)
check "status after down: off" '[[ $OUT == *"Tunnel fu-vpn: aus"* ]]'

reset; conf
OUT=$("$FU_VPN" down 2>&1); RC=$?
check "down without pid file: exit 1" '[ $RC = 1 ] && [[ $OUT == *"fehlt"* ]]'

# ---------- toggle ----------
reset; conf
"$FU_VPN" toggle >/dev/null 2>&1
check "toggle from off: up" '[ -e "$STATE/link" ]'
"$FU_VPN" toggle >/dev/null 2>&1
check "toggle from on: down" '[ ! -e "$STATE/link" ]'

# ---------- config ----------
reset; conf 'MTU=1300
SERVER=vpn.other.example'
"$FU_VPN" up >/dev/null 2>&1
check "config: MTU" 'grep -qx "link set dev fu-vpn mtu 1300" "$STATE/ip.log"'
check "config: SERVER" 'head -1 "$STATE/openconnect.args" | grep -q "vpn.other.example$"'

# ---------- failures ----------
reset; conf; touch "$STATE/no-cookie"
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "login without cookie: exit 1, no tunnel" '[ $RC = 1 ] && [[ $OUT == *"kein Cookie"* ]] && [ ! -e "$STATE/link" ]'

# Server-controlled login output is parsed, never executed.
reset; conf
cat > "$STATE/auth-output" <<EOF2
COOKIE='a'\\''b'; touch $STATE/pwned1
CONNECT_URL='https://vpn.example/'
FINGERPRINT='pin-sha256:abc'
EVIL=\$(touch $STATE/pwned2)
\$(touch $STATE/pwned3)
EOF2
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "login output: nothing from it runs as a command" '[ ! -e "$STATE/pwned1" ] && [ ! -e "$STATE/pwned2" ] && [ ! -e "$STATE/pwned3" ]'

reset; conf
printf '%s\n' "COOKIE='it'\\''s'" "CONNECT_URL='https://vpn.example/'" "FINGERPRINT='pin-sha256:abc'" > "$STATE/auth-output"
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "login output: shell quoting removed" '[ $RC = 0 ] && [ "$(cat "$STATE/stdin")" = "it'"'"'s" ]'

reset; conf
printf '%s\n' "COOKIE='c'" "CONNECT_URL='https://vpn.example/ --script=/tmp/x'" "FINGERPRINT='pin-sha256:abc'" > "$STATE/auth-output"
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "login output: odd CONNECT_URL stops before sudo" '[ $RC = 1 ] && [[ $OUT == *"CONNECT_URL"* ]] && [ ! -e "$STATE/sudo.log" ]'

reset; conf
printf '%s\n' "COOKIE='c'" "CONNECT_URL='https://vpn.example/'" "FINGERPRINT='abc; rm -rf x'" > "$STATE/auth-output"
OUT=$("$FU_VPN" up 2>&1); RC=$?
check "login output: odd FINGERPRINT stops before sudo" '[ $RC = 1 ] && [[ $OUT == *"FINGERPRINT"* ]] && [ ! -e "$STATE/sudo.log" ]'

OUT=$("$FU_VPN" bogus 2>&1); RC=$?
check "unknown command: exit 2 with usage" '[ $RC = 2 ] && [[ $OUT == *"Aufruf: fu-vpn"* ]]'

reset; conf; touch "$STATE/no-cookie"
OUT=$("$FU_VPN" up --window 2>&1 <<<""); RC=$?
# read -p prints its prompt only on a terminal, so check the exit code and the error.
check "--window: error keeps the window, exit 0" '[ $RC = 0 ] && [[ $OUT == *"kein Cookie"* ]]'

# ---------- install.sh ----------
reset
INSTALL="$HERE/install.sh"
BIN="$HOME/.local/bin/fu-vpn"
DESKTOP="$XDG_DATA_HOME/applications/fu-vpn.desktop"
EXT="$XDG_DATA_HOME/gnome-shell/extensions/fu-vpn-indicator@toolkit.local"

OUT=$(bash "$INSTALL" --dry-run 2>&1); RC=$?
check "install --dry-run: exit 0, changes nothing" '[ $RC = 0 ] && [ ! -e "$HOME/.local" ]'

mkdir -p "$(dirname "$DESKTOP")"
echo "foreign" > "$DESKTOP"
OUT=$(bash "$INSTALL" 2>&1); RC=$?
check "install: exit 0" '[ $RC = 0 ]'
check "install: bin is a symlink into the repo" '[ "$(readlink "$BIN")" = "$FU_VPN" ]'
check "install: extension is a symlink into the repo" '[ "$(readlink "$EXT")" = "$HERE/extension/fu-vpn-indicator@toolkit.local" ]'
check "install: desktop file points to bin" 'grep -qx "Exec=ptyxis -s --title=FU-VPN -- $BIN toggle --window" "$DESKTOP"'
check "install: foreign desktop file kept aside" '[ "$(cat "$DESKTOP.pre-toolkit")" = foreign ]'
check "install: extension enabled" 'grep -qx "enable fu-vpn-indicator@toolkit.local" "$STATE/gnome-extensions.log"'
check "install: no placeholder left" '! grep -q "@" "$DESKTOP" || ! grep -q "@BIN@\|@TERMINAL@" "$DESKTOP"'

OUT=$(bash "$INSTALL" --terminal "kgx --" 2>&1); RC=$?
check "install again: exit 0, own files reused" '[ $RC = 0 ] && [[ $OUT == *"zeigt schon auf"* ]] && [ ! -e "$BIN.pre-toolkit" ]'
check "install again: desktop file rewritten, not set aside again" 'grep -q "^Exec=kgx -- -- $BIN toggle" "$DESKTOP" && [ "$(cat "$DESKTOP.pre-toolkit")" = foreign ]'

rm "$BIN"; echo "old script" > "$BIN"; echo "older" > "$BIN.pre-toolkit"
OUT=$(bash "$INSTALL" 2>&1); RC=$?
check "install: stops instead of overwriting an old .pre-toolkit" '[ $RC = 1 ] && [ "$(cat "$BIN.pre-toolkit")" = older ] && [ "$(cat "$BIN")" = "old script" ]'

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
