# wt.zsh - Shell-Integration fuer wt. In ~/.zshrc:  source <toolkit>/dev/wt/wt.zsh
#
# Ein Skript laeuft als Kindprozess und kann das Verzeichnis der aufrufenden Shell
# nicht wechseln. Diese Funktion umhuellt das Skript, fragt es nach dem Pfad
# (wt path) und macht den cd selbst - angezeigt wie jeder andere Schritt.
#
#   wt new ...        wie bisher, endet im neuen Worktree (zurueck: cd -)
#   wt cd <nr|slug>   in einen vorhandenen Worktree wechseln
#   alles andere      unveraendert ans Skript

wt() {
  # Nicht-interaktiv (Agenten, Skripte, Hooks): nie den cwd verschieben.
  if [[ ! -o interactive ]]; then command wt "$@"; return; fi

  local target="" p
  case "${1:-}" in
    cd)
      [[ -n "${2:-}" ]] || { print -u2 "wt cd braucht <nr> oder <kuerzel>"; return 1; }
      target="$2"
      ;;
    new)
      # WT_SHELL=1: das Skript laesst die 'cd ...'-Zeile im Abschlusshinweis weg.
      WT_SHELL=1 command wt "$@" || return
      shift
      while (( $# )); do
        case "$1" in
          --mr|--branch) target="$2"; shift 2 ;;
          *)             shift ;;
        esac
      done
      [[ -n "$target" ]] || return 0
      ;;
    *)
      command wt "$@"; return
      ;;
  esac

  p=$(command wt path "$target") || return
  printf '\n\033[1m>\033[0m In den Worktree wechseln (zurueck: cd -)\n  $ cd %s\n' "$p" >&2
  cd "$p" || return
}
