# skill-show Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (Native, empfohlen) oder superpowers:subagent-driven-development. Schritte mit `- [ ]`.
> Nach Freigabe wird dieser Plan unverändert nach `docs/superpowers/plans/2026-10-18-skill-show-phase1.md` im Worktree kopiert (gehört zum Branch, nicht zu main).

**Goal:** `skill-show <name>` findet die Datei, die Claude Code für `/<name>` nutzt, und gibt sie byte-genau mit Pfad-Header aus; ohne Argument eine gruppierte Liste.

**Architecture:** Ein Bash-Skript nach dem Muster von `dev/recall/recall`: Config-Block, Helfer (`note`, `die`, `need`, `re_ascii`), ein Sammler, der alle Fundstellen als Datensätze (Felder mit `\037` getrennt) ausgibt, darauf aufbauend Lookup, Anzeige, Liste, TSV und Picker. Lesen nur, keine Temp-Dateien, kein Netz.

**Tech Stack:** Bash 5, coreutils, awk, sed, find, jq (optional für Plugins), fzf/bat optional. Tests: `test_skill_show.sh` im Stil von `test_recall.sh`.

**Spec:** `docs/superpowers/specs/2026-10-18-skill-show-design.md` (liegt übrigens schon in Commit `0ac7c4b` auf main und origin/main — nicht uncommitted, wie im Auftrag vermutet).

## Context

Katharina will den Text eines Skills/Commands ungefiltert sehen, ohne dass ein Modell ihn liest — vor allem per `! skill-show <name>` in Claude Code. Phase 1 = nur das CLI-Werkzeug plus Repo-Integration; recall-Gruppe (Phase 2) und Übersichten (Phase 3) bleiben draußen.

## Rahmen (aus dem Auftrag, gilt für jeden Schritt)

- Worktree per Runbook `/feature-bauen`: `git worktree add -b feat/skill-show ../toolkit-worktrees/skill-show main` (vom **lokalen** main → kein Upstream). Prüfen: `git -C ../toolkit-worktrees/skill-show rev-parse --abbrev-ref @{u}` muss scheitern. push.default ist nicht gesetzt (= simple) → blankes `git push` verweigert ohne Upstream.
- **Kein Commit, kein Push, kein Merge ohne Katharinas OK.** Die „Commit“-Schritte unten bedeuten: Nachricht nach `$SCRATCH/commit-msg-<n>.txt` schreiben, Dateien einzeln vorschlagen, auf OK warten, dann `git add <datei> …` (einzeln) und `git commit -F <datei>`. Keine Co-Authored-By-Zeilen, kein `git add -A`.
- Aus `~/ki-os` nichts lesen (auch nicht die Vault-Quelle des Runbooks, die das Runbook eigentlich verlangt; den Entscheidungslog-Schritt des Runbooks lasse ich deshalb weg und nenne die Entscheidungen stattdessen in Spec/README). Beim Handtest liest skill-show von kios-Dateien nur die Kopfzeilen (erste 2000 Bytes) und prüft Quellen nur auf Existenz.
- Merge/`worktree remove` nur vom Hauptbaum aus und erst nach Freigabe.

## Schritt 0 — Offene Fragen der Spec klären (vor jedem Code)

- [ ] **0.1 Vorrang Command vs. Skill (Live-Test, `claude -p`, Modell haiku, ~4 kurze Aufrufe):** Scratch-Repo `$SCRATCH/probe` (git init). Temporär anlegen und danach wieder löschen (mit `ls` nachweisen):
  - `~/.claude/commands/zz-skillshow-probe-a.md` → „Antworte nur: PERSONAL-COMMAND“, und `$SCRATCH/probe/.claude/skills/zz-skillshow-probe-a/SKILL.md` → „Antworte nur: PROJECT-SKILL“
  - umgekehrt `~/.claude/skills/zz-skillshow-probe-b/SKILL.md` (PERSONAL-SKILL) vs. `$SCRATCH/probe/.claude/commands/zz-skillshow-probe-b.md` (PROJECT-COMMAND)
  - Ordnername vs. `name:`: `$SCRATCH/probe/.claude/skills/zz-dir/SKILL.md` mit `name: zz-named`; `/zz-dir`, `/zz-named`, `/ZZ-NAMED` aufrufen.
  - Unterordner-Command: `$SCRATCH/probe/.claude/commands/zzsub/zz-probe-c.md`; `/zzsub:zz-probe-c` und `/zz-probe-c` aufrufen.
  - Aufruf: `cd $SCRATCH/probe && claude -p '/zz-skillshow-probe-a' --model haiku`. Falls `-p` Slash-Namen nicht auflöst (unsicher), bitte ich dich um einen Lauf in einer interaktiven Scratch-Session.
- [ ] **0.2 `!` und stderr:** kann ich nicht selbst auslösen (nur du tippst `!`); die Doku sagt nur „add its output to the session“, zu stderr nichts. Ich bitte dich einmal um `! sh -c 'echo OUT; echo ERR >&2'` und trage das Beobachtete ein.

Doku-Befunde (code.claude.com/docs, 2026-10-18 über einen Recherche-Agenten gelesen; Zitate über WebFetch-Zusammenfassung, beim Eintragen in die Spec noch einmal am Original prüfen):
- `CLAUDE_CONFIG_DIR` ist dokumentiert (env-vars) → bleibt.
- Ordnername ruft den Skill ebenfalls auf („The directory name also invokes the skill“) → beide Namen, wie Spec.
- **Unterordner in `commands/`: Aufruf `/sub:name`** („each `/` replaced by `:`“) → weicht von der Spec ab (die sagte `/name` mit Label). Folge: siehe Task 3; Spec-Abschnitt „Command name“ wird angepasst.
- `enabledPlugins`: pro Plugin-ID gewinnt die höchste Quelle: local > project > user → wie Spec.
- Nested Skills: „both stay available“ → `also loaded` wie Spec. Skills aus Elternordnern bis zur Repo-Wurzel laden ebenfalls (deckt sich mit Gruppe 4).
- `installed_plugins.json`: Feld für den Projektpfad nicht dokumentiert, lokal nur `scope: user` beobachtet → Label `(scope: <scope>, project unknown)`.
- Kein offizieller Weg, Bundled-Skill-Text auszugeben → Meldung wie Spec (offene Frage 1 erledigt).
- Groß/Klein nur für Synced-Kollisionen dokumentiert → Live-Test 0.1 entscheidet.
- [ ] **0.3** Ergebnisse + Doku-Befunde (CLAUDE_CONFIG_DIR, Unterordner in commands/, Settings-Reihenfolge, Plugin-Scopes, Groß/Klein) in die Spec unter „Open questions“ eintragen („Resolved 2026-10-18: …“, mit Quelle/Beobachtung). Weicht der Vorrang von „alle Skills vor allen Commands“ ab, ändere ich nur `RANK` (Task 3) und die Tests 3/Precedence entsprechend — und sage es dir vor dem Weiterbauen.

## Global Constraints (aus der Spec)

- `#!/usr/bin/env bash`, `set -euo pipefail`, Bash 5; `bash -n` + `shellcheck` sauber.
- Meldungen/Hilfe auf Englisch. Config `~/.config/skill-show/skill-show.conf`, optional, `source` wie recall.
- Schreibt nichts (kein mktemp, kein Cache), kein Netz, ruft kein `claude`.
- Inhalt nur per `cat -- "$file"`; nie durch `read`/`echo`.
- Exit: 0 ok · 1 nicht gefunden / unlesbar (`die`) · 2 Usage/ungültiger Name/`plugin:skill` ohne jq · 130 Picker-esc.
- Namen: ein führendes `/` weg, Split am ersten `:`, je Teil nur `[A-Za-z0-9._-]` per `re_ascii` (LC_ALL=C), kein leerer Teil, kein zweites `:`, kein `..` → sonst exit 2.
- `$CLAUDE_HOME=${CLAUDE_CONFIG_DIR:-$HOME/.claude}`; `MANAGED_DIR=${SKILL_SHOW_MANAGED_DIR:-/etc/claude-code}`; `$PROJECT` = `git rev-parse --show-toplevel` sonst `$PWD`, `--project <dir>` überschreibt.
- Config-Variablen: `SOURCE_ROOTS=()`, `EXTRA_DIRS=()`, `BUILTIN_NAMES=()`, `SYNCED_SKILL_PREFIX="anthropic-skills"`.
- Begin-Zeile `──── begin ────`; End-Zeile `──── end of <path> ────`, ohne Schluss-Newline: vorher ein `\n`, Zeile `──── end of <path> (no newline at end of file) ────`.

## Review Focus

1. Pfade mit Leerzeichen (Vault „Mein Vault“, Skill-Ordner) → Header und `> cat '<path>'` korrekt, Lookup klappt. → Test in Task 2 (Skill-Ordner mit Leerzeichen über Symlink-Ziel) und Task 4 (`SOURCE_ROOTS` mit Leerzeichen).
2. Leere Datei (0 Bytes) → Begin- und End-Zeile direkt nacheinander, kein „no newline“-Vermerk, exit 0. → Task 2.
3. `SKILL.md` ohne Front Matter bzw. mit `name:` in Anführungszeichen → Ordnername bzw. Wert ohne Quotes. → Task 2.
4. Aufruf außerhalb jedes Git-Repos (Projekt = `$PWD`, keine Nested-Suche) → kein Fehler. → Task 3.
5. Kaputtes `installed_plugins.json` (kein JSON) → Hinweis auf stderr, lokale Einträge funktionieren weiter, exit nicht durch `set -e` abgebrochen. → Task 5.

---

## Dateien

- Create: `dev/skill-show/skill-show` (ausführbar), `dev/skill-show/test_skill_show.sh`, `dev/skill-show/README.md`, `dev/skill-show/example.conf`, `docs/superpowers/plans/2026-10-18-skill-show-phase1.md`
- Modify: `README.md` (Tools-Tabelle), `.github/workflows/ci.yml` (lint-Job: `bash -n`, `shellcheck`, Testschritt), `.githooks/pre-commit` (`is_ci_shell`), Spec (Schritt 0.3)

## Interner Datensatz (alle Tasks)

`collect` gibt pro Fundstelle eine Zeile aus, Felder mit `\037` getrennt:

`rank \037 invocation \037 kind(skill|command) \037 group \037 name \037 dirname \037 file \037 label \037 kios_raw \037 description \037 heading`

- `rank`: Zahl aus `RANK[group]` (managed 1, personal-skill 2, project-skill 3, nested 4, extra 5, personal-command 6, project-command 7, claude-ai-skill 8, plugin 9, claude-ai-plugin 10); Nested bekommt `4.<tiefe>` (nächster Ordner zuerst).
- `invocation`: `/name` bzw. `/prefix:name`. `dirname`: Skill-Ordner (für Ordnernamen-Treffer), leer bei Commands.
- `label`: Unterordner bei Commands, `(disabled)`, `(scope: x, project unknown)`.
- `heading`: Gruppen-Überschrift der Liste (z. B. `plugin superpowers 7.0.0  <installPath>`).
- Matching für unpräfixierte Namen: Feld `name` == Name **oder** `dirname` == Name, nur Gruppen 1–7 ohne Unterordner-Commands. Präfixiert: `invocation` == `/p:s` oder `/p:<dirname>` in Gruppen 8–10 **und** Unterordner-Commands (`/sub:name`, Gruppen 6–7). Kollidieren beide (Unterordner `engineering/` und Plugin `engineering`), werden beide gezeigt mit dem Hinweis `cannot tell which one Claude Code uses`.
- Ohne jq: präfixierter Name, der einen Unterordner-Command trifft → zeigen + Hinweis „plugins not checked: jq is missing“; sonst exit 2 (Spec-Regel).

---

### Task 1: Gerüst, Testharness, CLI, Namensprüfung, CI

**Files:** Create `dev/skill-show/skill-show`, `dev/skill-show/test_skill_show.sh`; Modify `.github/workflows/ci.yml`, `.githooks/pre-commit`

**Produces:** `usage()`, `note()`, `die()` (exit 1), `usage_error()` (Usage auf stderr, exit 2), `re_ascii()`, `parse_name <arg>` → setzt `NAME_PREFIX`, `NAME_BARE`; Optionsflags `OPT_ALL OPT_PATH OPT_RAW OPT_PRETTY OPT_LIST OPT_TSV`, `PROJECT`.

- [ ] **Test-Harness schreiben** (nach `test_recall.sh`): `mktemp -d`, `HOME=$TMP/home NO_COLOR=1`, `unset CLAUDE_CONFIG_DIR`, `SKILL_SHOW_MANAGED_DIR=$TMP/etc-claude-code`; `$SYS` mit Links auf `bash env cat sed awk sort cut stat realpath readlink basename dirname printf grep head tail tr wc find git od cmp sha256sum mkdir ln chmod`, jq als separater Link (für Task 5 entfernbar); Stubs `fzf bat curl wget claude` loggen Argumente; `ok/fail/expect_eq/expect_has/expect_not`; `run <args>` setzt `OUT`, `ERR`, `RC` (stdout/stderr in Dateien unter `$TMP`). Am Anfang Checksum-Liste von `$HOME` und `$TMP/proj` (`find … -type f -exec sha256sum {} + | sort`), am Ende Vergleich (Spec-Fall 21) und Asserts: `curl.log`, `wget.log`, `claude.log` existieren nicht.
- [ ] **Tests:** `--help` exit 0 und enthält `skill-show <name>`; `--bogus` exit 2, stderr enthält `usage`; ungültige Namen `../x`, `a/b`, `a:b:c`, `''`, `ä`, `a:`, `:b` → exit 2, stdout leer (Fall 15); `bash -n` und (falls vorhanden) `shellcheck` auf beide Skripte (Fall 23).
- [ ] Laufen lassen → FAIL (Skript fehlt).
- [ ] **Implementieren:** Kopf/Helfer wie recall (Farben nur bei `[ -t 1 ]` und ohne `NO_COLOR`), Config-Block + `source`, Option-Parser (`--all --path --raw --pretty --list --tsv --project <dir> --help`, ein Positionsargument), `parse_name`.
- [ ] Laufen lassen → PASS.
- [ ] CI: in `ci.yml` `bash -n dev/skill-show/skill-show dev/skill-show/test_skill_show.sh`, `shellcheck …` und Step `skill-show tests: bash dev/skill-show/test_skill_show.sh`; in `.githooks/pre-commit` die beiden Pfade in `is_ci_shell` ergänzen.
- [ ] Commit vorschlagen: `add skill-show skeleton with name checks and test harness`.

### Task 2: Persönliche/Projekt-Skills und -Commands anzeigen (Byte-Treue)

**Files:** Modify `dev/skill-show/skill-show`, `test_skill_show.sh`

**Consumes:** Task 1. **Produces:** `file_meta <file>...` (ein awk-Lauf; je Datei `file\037name\037description\037kios_raw`, Front Matter nur erster Block, Quotes entfernt; kios aus den ersten 2000 Bytes — Feld bleibt in Task 2 noch ungenutzt), `collect_local` (Gruppen personal-skill, project-skill, personal-command, project-command), `show_entry <record> <status>`, `print_content <file>`.

- [ ] **Fixture** laut Spec (alpha, renamed/`name: beta`, Symlink-Ordner nach `$TMP/outside/link skill/` mit Leerzeichen, `.trash/old`, Ordner mit `REFERENCE.md` + `scripts/x.sh`, Commands `plain.md`, `alpha.md`, `sub/nested-cmd.md`, Projekt `$TMP/proj` als git-Repo) plus Byte-Fälle: Datei ohne Schluss-Newline, CRLF, `\n`-Sequenz + Tab, Zeile > 10 000 Zeichen, Zeile `──── end of /x ────` im Inhalt, leere Datei, SKILL.md ohne Front Matter, `name: "quoted"`.
- [ ] **Tests:** Fall 1 (Block nach Begin-Zeile == Datei + ggf. `\n` + End-Zeile, per `cmp`; Hilfsfunktion `after_begin` mit `grep -n -m1 -Fx` + `tail -n +N`); `--raw` == Datei (`cmp`); Fall 2 (`/alpha` == `alpha`, aus `$TMP` ohne Repo); Fall 4 (`beta` und `renamed`); Fall 5 (`link:` mit realpath); Fall 6 (`old` nicht gefunden); `more:` listet `REFERENCE.md` und `scripts/x.sh` als volle Pfade, sortiert, Skill ohne Extras → `none`; Header enthält `> cat '<path>'`; Fall 16 Teil 1 (`--path` genau eine Zeile); Fall 22 (`chmod 000` → exit 1, stderr nennt Pfad, stdout leer; übersprungen als root); Review Focus 2 und 3.
- [ ] FAIL bestätigen.
- [ ] **Implementieren.** Header (stdout): `==> <invocation> · <kind> · <group words> · <status>`, `    file:    <path>`, optional `    link:    <realpath>` (nur wenn `realpath` ≠ Pfad), bei Skills `    more:    …` (find im Skill-Ordner `-L`, ohne SKILL.md, sortiert, max. 50 + `… n more`), `    > cat '<path>'`. Lesbarkeit vor jeder Ausgabe prüfen (`[ -r ]` und `head -c0`), sonst `die`. Schluss-Newline: `tail -c1 -- "$f" | od -An -c` bzw. `[ -s f ] && [ "$(tail -c1 -- f | wc -l)" = 0 ]`.
- [ ] PASS. Commit vorschlagen: `show personal and project skills and commands byte for byte`.

### Task 3: Vorrang, Schattierung, managed/nested/extra, Unterordner, `--all`, `--pretty`

**Produces:** `RANK` (assoziatives Array, **einzige** Stelle der Reihenfolge), `lookup <bare>` → sortierte Treffer, `status_for` (`active`, `shadowed by <group>`, `also loaded`), Ausgabe der Schatten-Zeilen `    shadowed: /<name> · <kind> · <group> · <path>`.

- [ ] **Fixture:** `$TMP/etc-claude-code/.claude/skills/mgd/SKILL.md`, Projekt-Skill `alpha` und `projonly`, `pkg/.claude/skills/nest/SKILL.md` plus `pkg/.claude/skills/projonly/SKILL.md`, `EXTRA_DIRS` mit `$TMP/extra/.claude/skills/xtra`.
- [ ] **Tests:** Fall 3 (aus `$TMP/proj`: personal skill active, project skill + `alpha.md` als shadowed); `projonly` aus `$TMP/proj/pkg` → project active, nested `also loaded`; `mgd` gefunden; `xtra` nur mit Config; `sub:nested-cmd` gefunden (Header `/sub:nested-cmd`), bare `nested-cmd` → exit 1 mit Vorschlag `/sub:nested-cmd` (sofern Schritt 0.1 die Doku bestätigt); Review Focus 4 (aus `$TMP` ohne Repo, `--project $TMP/proj` liefert Projektfund); Fall 16 Teil 2 (`--path --all` eine Zeile pro Treffer, Reihenfolge = Vorrang); `--all` zeigt alle Blöcke; Header bei Command-vs-Skill-über-Ebenen enthält `active (by the precedence in the README)` (falls Schritt 0.1 den Fall nicht klärt); Fall 19 (`--pretty` → bat-Stub mit `--language=markdown --style=plain --paging=never` und Pfad; Header nicht durch bat; ohne bat Hinweis auf stderr, Inhalt plain).
- [ ] FAIL → implementieren → PASS. Commit vorschlagen: `add precedence, shadowed matches, --all and --pretty`.

### Task 4: kios-Quelle

**Produces:** `kios_raw` aus `file_meta` (Suche nach `kios:generated | Quelle: ` in den ersten 2000 Bytes, Wert bis zum nächsten ` |`), `resolve_source <raw>` → `realpath` des ersten `<root>/<raw>` in `SOURCE_ROOTS` oder leer.

- [ ] **Fixture:** `gen4.md` (Marker Zeile 4), `gen5.md` (Zeile 5), Projekt `gen1.md` (Zeile 1, vor Front Matter), Vault `$TMP/Mein Vault/40-runbooks/x.md`, Config mit `SOURCE_ROOTS=("$TMP/Mein Vault")`.
- [ ] **Tests (Fall 7):** alle drei Marker erkannt; auflösbar → `    source:  <voller Pfad> (kios sync: edit the source, not this file)`; nicht auflösbar → `source:  templates/merken.md (kios; not found under SOURCE_ROOTS)`; ohne Config → roher Wert + Hinweis `set SOURCE_ROOTS in ~/.config/skill-show/skill-show.conf`; Inhalt der Vault-Datei (Marker-String `VAULT-SECRET`) erscheint nie in stdout.
- [ ] FAIL → implementieren → PASS. Commit vorschlagen: `name the kios source note of generated commands`.

### Task 5: Plugins, claude.ai-Skills und -Plugins, präfixierte Namen, jq fehlt

**Produces:** `collect_plugins` (genau **zwei** jq-Aufrufe: einer über `installed_plugins.json` + die drei Settings-Dateien → `key, prefix-fallback, marketplace, installPath, version, scope, disabled`; einer über alle `plugin.json` per `input_filename`), `collect_synced_skills`, `collect_synced_plugins`, `have_jq`.

- [ ] **Fixture** laut Spec (superpowers 7.0.0 + veraltete 6.4.1 + `temp_subdir_1_x.clone`, pydantic-ai mit `"name": "ai"`, `settings.json` mit einem `false`, synced Skills mit Manifest + `.bucket-x`, synced Plugin `engineering` Gen. 3 + alte Version + `.in_use`), plus ein Eintrag `scope: "project"`.
- [ ] **Tests:** Fall 8 (7.0.0-Inhalt, nie 6.4.1/temp); Fall 9 (`ai:…` ok, `pydantic-ai:…` exit 1); Fall 10 (Manifest → `~g3`; ohne Manifest → `.in_use`-Ordner; beides weg → Hinweis stderr); Fall 11 (`anthropic-skills:pdf`); Fall 12 (`(disabled)` im Header); Projekt-Scope → Label `(scope: project, project unknown)` (oder laut Doku-Befund); zwei Plugins gleichen Namens aus zwei Marketplaces → beide Blöcke, Header-Hinweis `cannot tell which one Claude Code uses`, exit 0; Fall 20 (jq-Link entfernt: `alpha` ok + Hinweis `sudo dnf install jq` auf stderr; `superpowers:brainstorming` exit 2); Review Focus 5 (kaputtes JSON).
- [ ] FAIL → implementieren → PASS. Commit vorschlagen: `look up plugin and claude.ai skills by their invoked prefix`.

### Task 6: Nicht gefunden, Bundled-Hinweis, Vorschläge

**Produces:** `not_found <bare|prefixed>` (stderr, exit 1).

- [ ] **Tests:** Fall 13 (`brainstorming` bare: exit 1, stdout leer, stderr `Plugin skills with this name: /superpowers:brainstorming`); Fall 14 (`simplify`: `most likely a bundled skill`; mit `BUILTIN_NAMES=(simplify)`: `is a bundled skill or built-in command of Claude Code`).
Vorschläge umfassen auch Unterordner-Commands (`Commands in a subfolder with this name: /sub:nested-cmd`).
- [ ] FAIL → implementieren (Text wie Spec-Beispiel) → PASS. Commit vorschlagen: `explain names without a file instead of a bare not found`.

### Task 7: Liste, `--tsv`, Picker

**Produces:** `print_list`, `print_tsv`, `want_picker` (stdin+stdout TTY oder `SKILL_SHOW_FORCE_TTY=1`, fzf in PATH, kein `--list`), `pick`.

- [ ] **Tests:** Fall 17 (ohne TTY: jeder Fixture-Eintrag genau einmal, Gruppenüberschriften, `(shadowed by personal skill)`, `beta [renamed]`, kios roh, keine `.trash`/`.bucket`-Einträge, Schlusszeile `not files: bundled skills…`; `--tsv`: jede Zeile genau 8 Felder, keine Kopfzeile, Status-Werte aus `active|shadowed|also-loaded|disabled`); Fall 18 (`SKILL_SHOW_FORCE_TTY=1` + fzf-Stub `PICK alpha` → stdout = normale Ausgabe von `alpha`; Stub-Eingabe enthält die Einträge; Stub `ESC` → exit 130, stdout leer; ohne Force-TTY → fzf-Log leer); `--list` mit Force-TTY → kein fzf.
- [ ] FAIL → implementieren. fzf nur mit bereits in recall genutzten Optionen: `--ansi --exact --no-sort --delimiter=$'\t' --with-nth=… --layout=reverse --border=rounded --border-label=' skill-show ' --preview="'$SELF' --raw {1}" --preview-window='right,55%,wrap'`. Reihenfolge in Plugin-Gruppen: Plugin-Name, Skills vor Commands, Name. → PASS. Commit vorschlagen: `list every skill and command, as text, tsv or picker`.

### Task 8: Doku, example.conf, Handtest, Abschluss

- [ ] `dev/skill-show/README.md` (Aufbau wie `dev/recall/README.md`): Usage, Requirements (`sudo dnf install jq fzf bat`), Setup (`ln -s …`, Config), Where it looks (Tabelle), Precedence (mit Ergebnis aus Schritt 0 und Datum; unverifizierte Fälle markiert), claude.ai-Gruppen best-effort, TSV-Bereinigung, `!`-Verhalten zu stderr, Tests, `SKILL_SHOW_FORCE_TTY`/`SKILL_SHOW_MANAGED_DIR` als Test-Hooks.
- [ ] `dev/skill-show/example.conf` anonymisiert (`SOURCE_ROOTS=("$HOME/notes" "$HOME/src/kios/templates/agent/system-commands")`, `EXTRA_DIRS=()`, `BUILTIN_NAMES=(simplify code-review loop fewer-permission-prompts …)`, `SYNCED_SKILL_PREFIX`).
- [ ] Zeile in Top-`README.md` Tools-Tabelle (siehe Abschluss).
- [ ] Plan nach `docs/superpowers/plans/2026-10-18-skill-show-phase1.md`.
- [ ] Verifikation (siehe unten), dann superpowers:requesting-code-review (ein Reviewer über den ganzen Branch), Befunde einarbeiten.
- [ ] Commit vorschlagen: `document skill-show and wire it into README and CI`. Merge nach main nur auf dein Wort (vom Hauptbaum, `--no-ff`), dann Worktree entfernen.

## Ausführung

Empfehlung **Native** (ich setze Task für Task selbst um, am Ende ein unabhängiger Reviewer über den ganzen Branch): Alle Tasks bauen auf demselben Datensatz-Format und derselben Datei auf, und ein Subagent pro Task müsste diesen Kontext jedes Mal neu lernen. Nach Schritt 0 melde ich mich mit den Ergebnissen und dem Spec-Diff, **bevor** Task 1 beginnt.

## Verifikation

1. `bash dev/skill-show/test_skill_show.sh` → `all tests passed`; `bash -n` + `shellcheck` auf beide Skripte sauber; recall- und wt-Tests unverändert grün.
2. Handtest aus dem Worktree (echter HOME, nur lesend): `dev/skill-show/skill-show teamwork-tasks`, `zeiterfassung` (link:), `superpowers:brainstorming`, `anthropic-skills:pdf`, `engineering:code-review`, `simplify` (exit 1), ohne Argument | head, `--tsv | awk -F'\t' 'NF!=8'` leer, `time skill-show --list` deutlich < 1 s; danach `git status` im Repo sauber, `~/.claude` unverändert (Checksum vorher/nachher).
3. Du einmal in Claude Code: `! dev/skill-show/skill-show feature-bauen` (bzw. nach Setup `! skill-show feature-bauen`).

## Abschluss-Antwort (Inhalt)

- Nutzung: `ln -s "$PWD/dev/skill-show/skill-show" ~/.local/bin/skill-show`, dann in Claude Code `! skill-show <name>` / `! skill-show /plugin:skill` / `! skill-show` (Liste) / `! skill-show <name> --path`.
- README-Zeile: `| [dev/skill-show](dev/skill-show/) | dev | Shows the file behind a Claude Code skill or slash command byte for byte, with its path and the precedence among same-named ones — no model reads it for you |`
