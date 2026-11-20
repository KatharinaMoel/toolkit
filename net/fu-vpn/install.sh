#!/usr/bin/env bash
# install.sh - richtet fu-vpn fuer den eigenen Benutzer ein (kein sudo):
#   ~/.local/bin/fu-vpn                     -> Symlink auf das Skript im Repo
#   ~/.local/share/applications/fu-vpn.desktop  App-Symbol (aus fu-vpn.desktop.in)
#   ~/.local/share/gnome-shell/extensions/<uuid> -> Symlink auf die Erweiterung
#
#   bash install.sh [--dry-run] [--terminal "<befehl>"]
#
# Symlinks statt Kopien: Nach `git pull` gilt sofort der neue Stand.
# Vorhandene Dateien, die kein solcher Symlink sind, werden nicht geloescht,
# sondern nach <datei>.pre-toolkit verschoben.
# Jeder Schritt wird vorher mit Erklaerung gezeigt; --dry-run zeigt nur.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UUID=fu-vpn-indicator@toolkit.local
TERMINAL_CMD="ptyxis -s --title=FU-VPN"
DRY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --terminal) shift; TERMINAL_CMD="${1:?--terminal braucht einen Befehl}" ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/fu-vpn"
DESKTOP="$DATA/applications/fu-vpn.desktop"
EXT_DIR="$DATA/gnome-shell/extensions"

run() {
    local why=$1
    shift
    printf '> %s\n  $ %s\n' "$why" "$*"
    [ "$DRY" = 1 ] || "$@"
}

# Ziel frei machen: eigener Symlink bleibt, alles andere wird beiseitegelegt.
make_room() {
    local target=$1 source=$2
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
        return 0
    fi
    if [ -e "$target" ] || [ -L "$target" ]; then
        if [ -e "$target.pre-toolkit" ] || [ -L "$target.pre-toolkit" ]; then
            echo "$target.pre-toolkit gibt es schon - bitte erst ansehen und wegraeumen." >&2
            exit 1
        fi
        run "Vorhandenes $target beiseitelegen (nicht loeschen)" \
            mv -T "$target" "$target.pre-toolkit"
    fi
}

link() {
    local source=$1 target=$2
    make_room "$target" "$source"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
        echo "= $target zeigt schon auf $source"
        return 0
    fi
    run "Symlink anlegen" ln -s "$source" "$target"
}

if [ "$(git -C "$HERE" rev-parse --path-format=absolute --git-dir 2>/dev/null)" != \
     "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ]; then
    echo "Achtung: $HERE liegt in einem Git-Worktree. Die Symlinks zeigen dorthin" \
         "und brechen, wenn der Worktree entfernt wird." >&2
fi

run "Ordner anlegen" mkdir -p "$BIN_DIR" "$DATA/applications" "$EXT_DIR"

link "$HERE/fu-vpn" "$BIN"

# Ein frueher von install.sh geschriebenes App-Symbol wird ueberschrieben,
# ein fremdes beiseitegelegt.
if ! grep -qs '^X-Toolkit-Source=net/fu-vpn$' "$DESKTOP"; then
    make_room "$DESKTOP" "-"
fi
printf '> %s\n  $ %s\n' "App-Symbol aus der Vorlage schreiben" \
    "sed -e s#@BIN@#$BIN# -e s#@TERMINAL@#$TERMINAL_CMD# fu-vpn.desktop.in > $DESKTOP"
if [ "$DRY" = 0 ]; then
    sed -e "s#@BIN@#$BIN#g" -e "s#@TERMINAL@#$TERMINAL_CMD#g" \
        "$HERE/fu-vpn.desktop.in" > "$DESKTOP"
fi

link "$HERE/extension/$UUID" "$EXT_DIR/$UUID"

if command -v gnome-extensions >/dev/null 2>&1; then
    if [ "$DRY" = 1 ]; then
        printf '> %s\n  $ %s\n' "Leistensymbol einschalten" "gnome-extensions enable $UUID"
    elif ! run "Leistensymbol einschalten" gnome-extensions enable "$UUID" 2>/dev/null; then
        echo "  GNOME kennt die Erweiterung erst nach Ab- und Anmelden (Wayland)." \
             "Danach: gnome-extensions enable $UUID"
    fi
else
    echo "gnome-extensions fehlt - Leistensymbol uebersprungen."
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Hinweis: $BIN_DIR steht nicht in PATH." ;;
esac
echo "Fertig. Konfig (optional): ~/.config/fu-vpn/fu-vpn.conf, Vorlage: $HERE/example.conf"
