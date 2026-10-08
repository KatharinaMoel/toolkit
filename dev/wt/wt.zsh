# wt.zsh - Shell-Integration fuer wt. In ~/.zshrc:  source <toolkit>/dev/wt/wt.zsh
#
# Ein Skript laeuft als Kindprozess und kann das Verzeichnis der aufrufenden Shell
# nicht wechseln. Diese Funktion umhuellt das Skript, fragt es nach dem Pfad
# (wt path / wt pick) und macht den cd selbst - angezeigt wie jeder andere Schritt.
#
#   wt new ... [--ide]        wie bisher, endet im neuen Worktree (zurueck: cd -)
#   wt cd [--ide] [<x>]       wechseln; <x> = nr, kuerzel oder . (Hauptordner);
#                             ohne <x>: Auswahlliste (fzf); --ide oeffnet auch die IDE
#   alles andere              unveraendert ans Skript

wt() {
  # Nicht-interaktiv (Agenten, Skripte, Hooks): nie den cwd verschieben.
  if [[ ! -o interactive ]]; then command wt "$@"; return; fi

  local target="" p b ide=0
  case "${1:-}" in
    cd)
      shift
      while (( $# )); do
        case "$1" in
          --ide) ide=1 ;;
          *)     target="$1" ;;
        esac
        shift
      done
      if [[ -n "$target" ]]; then
        p=$(command wt path "$target") || return
      else
        p=$(command wt pick) || return
      fi
      ;;
    new)
      # WT_SHELL=1: das Skript laesst die 'cd ...'-Zeile im Abschlusshinweis weg.
      # --ide erledigt das Skript selbst.
      WT_SHELL=1 command wt "$@" || return
      shift
      while (( $# )); do
        case "$1" in
          --mr|--branch) target="$2"; shift 2 ;;
          *)             shift ;;
        esac
      done
      [[ -n "$target" ]] || return 0
      p=$(command wt path "$target") || return
      ;;
    *)
      command wt "$@"; return
      ;;
  esac

  # Branch mit anzeigen: ein Worktree ist ein Ordner, der Branch das, was darin ausgecheckt ist.
  b=$(git -C "$p" branch --show-current 2>/dev/null)
  b="[${b:-detached}]"
  if [[ -t 2 && -z "${NO_COLOR:-}" ]]; then
    printf '\n\033[1;36m* Wechseln nach %s %s (zurueck: cd -)\033[0m\n\033[2m  > cd %s\033[0m\n' "${p:t}" "$b" "$p" >&2
  else
    printf '\n* Wechseln nach %s %s (zurueck: cd -)\n  > cd %s\n' "${p:t}" "$b" "$p" >&2
  fi
  cd "$p" || return
  if (( ide )); then command wt ide "$p"; fi
}
