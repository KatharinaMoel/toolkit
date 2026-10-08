"""Command line: resolve, list, one, file, queue add|run|status."""

import argparse
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

from . import __version__, config, feed, net, pipeline, publisher, resolve
from . import queue as q
from .backend import BACKENDS
from .ui import Abort, Terminal, clean

ui = Terminal()


def out(text=""):
    """Results to stdout - feed text included, so control characters are stripped."""
    print(clean(text))
PERSONAL_USE = "Transkripte sind nur für den persönlichen Gebrauch; nicht veröffentlichen."


# ---------- network, shown like every other step ----------
def traced_get(url):
    if url.startswith("https://open.spotify.com/"):
        why = "Spotify-Seite lesen - nur den Showtitel (og:title) und Autor, nie Audio"
    elif url.startswith("https://itunes.apple.com/search"):
        why = "Apples öffentliches Podcast-Verzeichnis nach exakt diesem Titel fragen"
    elif url.startswith("https://itunes.apple.com/lookup"):
        why = "Apples öffentliches Podcast-Verzeichnis nach der Feed-URL dieser ID fragen"
    else:
        why = "RSS-Feed laden (Titel, Copyright, Episodenliste)"
    ui.step(why, f"GET {url}")
    return net.get(url)


def fetch_show(url):
    found = resolve.resolve_url(url, traced_get)
    if found.via != "feed":
        ui.result(f"Feed: {found.feed_url}")
    show = feed.parse_feed(traced_get(found.feed_url), found.feed_url)
    audio = sum(1 for e in show.episodes if e.audio_url)
    ui.result(f"{show.title!r}: {len(show.episodes)} Episoden, {audio} mit Audio")
    if found.title and " ".join(found.title.split()).casefold() != " ".join(show.title.split()).casefold():
        ui.warn(f"Feed-Titel {show.title!r} weicht vom Verzeichnistitel {found.title!r} ab - bitte prüfen")
    return show


# ---------- permission notice ----------
def permission(show, assume_yes, stdin=None, question=True):
    stdin = sys.stdin if stdin is None else stdin
    ui.step("Rechte-Hinweis vor jedem Download")
    if show is None:
        ui.result("kein Feed - Rechte unbekannt")
    else:
        ui.result(f"Copyright laut Feed: {show.copyright}" if show.copyright
                  else "Feed hat kein <copyright> - Rechte unbekannt")
        if show.license:
            ui.result(f"Lizenz laut Feed: {show.license}")
    ui.warn(PERSONAL_USE)
    if not question or assume_yes:
        return True
    if not stdin.isatty():
        raise Abort("keine Rückfrage möglich (kein Terminal) - mit --yes bestätigen")
    print("Weiter? [J/n] ", end="", file=sys.stderr, flush=True)
    answer = stdin.readline().strip().lower()
    return answer in ("", "j", "ja", "y", "yes")


# ---------- helpers ----------
def fmt_duration(seconds):
    if seconds is None:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def load_config(args):
    cfg = config.load(args.config)
    net.configure(cfg.max_text_mb)
    if cfg.source:
        ui.step(f"Konfig geladen: {cfg.source}")
    else:
        ui.step(f"keine Konfig unter {args.config or config.default_path()} - Standardwerte")
    return cfg


def language_of(args, cfg):
    lang = args.language or cfg.language
    if lang != "auto" and not re.fullmatch(r"[a-z]{2,3}", lang):
        raise Abort(f"Sprache {lang!r}: erwartet en, de, ... oder auto")
    return lang


class Backends:
    """Load each model once per process, and only when there is work."""

    def __init__(self, cfg):
        self.cfg, self.loaded = cfg, {}

    def get(self, model):
        if model not in self.loaded:
            ui.step(f"Modell {model!r} laden (beim ersten Mal von Hugging Face geladen, danach aus dem Cache)",
                    f"WhisperModel({model!r}, device='auto', compute_type='int8', "
                    f"cpu_threads={self.cfg.cpu_threads})")
            self.loaded[model] = BACKENDS["faster-whisper"](model, cpu_threads=self.cfg.cpu_threads)
            ui.result(f"faster-whisper {self.loaded[model].version}")
        return self.loaded[model]


def print_log(rows):
    out(f"{'Nr':>4}  {'Audio-min':>9}  {'Rechen-s':>8}  {'Faktor':>6}  {'Quelle':<9} Status")
    for r in rows:
        a, c = r.get("audio_seconds"), r.get("compute_seconds")
        ratio = f"{c / a:.2f}" if a and c is not None else "-"
        idx = r["index"] if r["index"] is not None else "-"
        mins = f"{a / 60:.1f}" if a else "-"
        secs = f"{c:.0f}" if c is not None else "-"
        source = {"publisher-transcript": "Herausg."}.get(r.get("backend"), "ASR" if r.get("backend") else "-")
        out(f"{idx:>4}  {mins:>9}  {secs:>8}  {ratio:>6}  {source:<9} "
              f"{r['status']}" + (f"  ({r['error']})" if r.get("error") else ""))


def source_for(transcripts, force_asr):
    """The publisher transcript to use, or None for ASR (forced, or none usable)."""
    if force_asr:
        return None
    items = [t if isinstance(t, feed.Transcript) else feed.Transcript(**t) for t in transcripts or []]
    return publisher.choose(items)


def announce_source(transcripts, chosen, force_asr):
    if chosen:
        ui.step(f"Transkript des Herausgebers vorhanden ({publisher.base_type(chosen.type)}) - "
                "wird statt eigener Erkennung genutzt; kein Audio, kein Modell (--asr erzwingt Whisper)")
    elif force_asr and transcripts:
        ui.step("--asr: eigene Erkennung mit Whisper, obwohl der Herausgeber ein Transkript anbietet")
    elif transcripts:
        types = ", ".join(sorted({t["type"] if isinstance(t, dict) else t.type for t in transcripts}))
        ui.step(f"Herausgeber-Transkript nur in nicht unterstütztem Format ({types}) - eigene Erkennung")


def job_from_episode(show, ep, out_dir, language):
    return pipeline.Job(show=show.title, feed_url=show.feed_url, guid=ep.guid, index=ep.index, title=ep.title,
                        published=ep.published, audio_url=ep.audio_url, copyright=show.copyright,
                        out_dir=Path(out_dir), language=language, transcripts=list(ep.transcripts))


def run_one(job, cfg, model):
    pipeline.check_tools(ui)
    backend = Backends(cfg).get(model)
    result = pipeline.process(job, pipeline.Settings(cfg.cache_dir, cfg.keep_audio, cfg.max_audio_mb), backend, ui)
    ui.note("Protokoll")
    print_log([{"index": job.index, "status": "done", **result}])
    return result


def run_publisher(job, transcript):
    result = pipeline.process_publisher(job, transcript, ui)
    ui.note("Protokoll")
    print_log([{"index": job.index, "status": "done", **result}])
    return result


# ---------- commands ----------
def cmd_resolve(args, cfg):
    show = fetch_show(args.url)
    no_audio = sum(1 for e in show.episodes if not e.audio_url)
    out(f"Show:       {show.title}")
    out(f"Feed:       {show.feed_url}")
    out(f"Copyright:  {show.copyright or '- (nicht angegeben)'}")
    if show.license:
        out(f"Lizenz:     {show.license}")
    out(f"Episoden:   {len(show.episodes)}" + (f" (davon {no_audio} ohne Audio)" if no_audio else ""))
    return 0


def cmd_list(args, cfg):
    show = fetch_show(args.feed_url)
    episodes = show.episodes[: args.limit] if args.limit else show.episodes
    for ep in episodes:
        date = (ep.published or "")[:10] or "-" * 10
        extra = "" if ep.audio_url else "  [kein Audio]"
        chosen = publisher.choose(ep.transcripts)
        if chosen:
            extra += f"  [Transkript: {publisher.base_type(chosen.type)}]"
        out(f"{ep.index:>3}  {date}  {fmt_duration(ep.duration_seconds):>7}  {ep.title}{extra}")
    ui.warn("Titel stammen aus dem Feed und sind ungeprüft - sie können falsch sein")
    return 0


def cmd_one(args, cfg):
    show = fetch_show(args.feed_url)
    ep = feed.select(show, args.episode)
    ui.step(f"Episode {ep.index} gewählt (Feed-Titel, ungeprüft): {ep.title}")
    if not permission(show, args.yes):
        raise Abort("abgebrochen - nichts heruntergeladen")
    job = job_from_episode(show, ep, args.out or cfg.out_dir, language_of(args, cfg))
    chosen = source_for(ep.transcripts, args.asr)
    announce_source(ep.transcripts, chosen, args.asr)
    if chosen:
        if args.model:
            ui.warn(f"--model {args.model} wird nicht verwendet (Transkript des Herausgebers; --asr erzwingt Whisper)")
        try:
            run_publisher(job, chosen)
            return 0
        except pipeline.PublisherUnusable as exc:
            ui.warn(f"Herausgeber-Transkript unbrauchbar ({exc}) - eigene Erkennung")
    run_one(job, cfg, args.model or cfg.model)
    return 0


def cmd_file(args, cfg):
    job = pipeline.file_job(args.source, args.out or cfg.out_dir, language_of(args, cfg))
    is_url = job.audio_url.startswith(("http://", "https://"))
    if not permission(None, args.yes, question=is_url):
        raise Abort("abgebrochen - nichts heruntergeladen")
    run_one(job, cfg, args.model or cfg.model)
    return 0


def cmd_queue_add(args, cfg):
    show = fetch_show(args.feed_url)
    indices = (list(range(1, len(show.episodes) + 1)) if args.all
               else feed.parse_range(args.range, len(show.episodes)))
    if not permission(show, args.yes):
        raise Abort("abgebrochen - nichts eingeplant")
    language, model = language_of(args, cfg), args.model or cfg.model
    out_dir = str(args.out or cfg.out_dir)
    ui.step("Episoden in die Queue eintragen (bestehende Einträge bleiben unverändert)")
    ui.result(f"Queue: {cfg.state_file}")
    added = existing = no_audio = 0
    with q.locked(cfg.state_file):
        state = q.Queue(cfg.state_file)
        for ep in show.episodes:
            if ep.index not in indices:
                continue
            if not ep.audio_url:
                no_audio += 1
                ui.warn(f"Episode {ep.index} hat kein Audio im Feed - übersprungen")
                continue
            fields = {"feed_url": show.feed_url, "guid": ep.guid, "index": ep.index, "title": ep.title,
                      "show": show.title, "published": ep.published, "audio_url": ep.audio_url,
                      "copyright": show.copyright, "out_dir": out_dir, "model": model, "language": language,
                      "transcripts": [vars(t) for t in ep.transcripts], "force_asr": bool(args.asr)}
            if state.add(fields):
                added += 1
            else:
                existing += 1
        state.save()
    ui.result(f"{added} neu, {existing} schon in der Queue, {no_audio} ohne Audio übersprungen")
    ui.note("Abarbeiten mit: transcribe queue run")
    return 0


def cmd_queue_run(args, cfg):
    if args.model or args.language:
        ui.note("Hinweis: --model/--language gelten in diesem Lauf für alle Einträge statt der eingeplanten Werte")
    language_override = language_of(args, cfg) if args.language else None
    backends = {}  # created on first ASR entry only
    settings = pipeline.Settings(cfg.cache_dir, cfg.keep_audio, cfg.max_audio_mb)
    nothing = {"flag": False}

    def force(entry):
        return bool(args.asr or entry.get("force_asr"))

    def on_plan(state, stale, reopened, todo):
        ui.step(f"Queue lesen: {cfg.state_file}")
        counts = {s: sum(1 for e in state.entries.values() if e["status"] == s) for s in q.STATUSES}
        ui.result(", ".join(f"{n} {s}" for s, n in counts.items()))
        for k in stale:
            ui.warn(f"Episode {state.get(k).get('index')} war 'running' (abgebrochener Lauf) - wieder pending")
        for k in reopened:
            ui.warn(f"Episode {state.get(k).get('index')}: Ausgabe fehlt oder sha256 passt nicht - wird neu erstellt")
        if not todo:
            nothing["flag"] = True
            ui.note(f"Nichts zu tun: {counts['done']} erledigt, {counts['failed']} endgültig fehlgeschlagen "
                    f"(nach {q.MAX_ATTEMPTS} Versuchen). Kein Download, kein Modell geladen.")
        else:
            limit = f", davon in diesem Lauf höchstens {args.max}" if args.max else ""
            ui.result(f"{len(todo)} zu bearbeiten{limit}")
            if any(source_for(state.get(k).get("transcripts"), force(state.get(k))) is None for k in todo):
                pipeline.check_tools(ui)  # curl/ffmpeg only needed when ASR will run

    def work(entry):
        ui.note(f"Episode {entry['index']} (Feed-Titel, ungeprüft): {entry['title']}")
        ui.result(f"Rechte laut Feed: {entry.get('copyright') or 'unbekannt'} - {PERSONAL_USE}")
        job = pipeline.Job(show=entry["show"], feed_url=entry["feed_url"], guid=entry["guid"],
                           index=entry["index"], title=entry["title"], published=entry.get("published"),
                           audio_url=entry["audio_url"], copyright=entry.get("copyright"),
                           out_dir=Path(entry["out_dir"]), language=language_override or entry["language"],
                           transcripts=entry.get("transcripts") or [])
        chosen = source_for(job.transcripts, force(entry))
        announce_source(job.transcripts, chosen, force(entry))
        reason = None
        if chosen:
            try:
                return pipeline.process_publisher(job, chosen, ui)
            except pipeline.PublisherUnusable as exc:
                reason = str(exc)
                ui.warn(f"Herausgeber-Transkript unbrauchbar ({reason}) - eigene Erkennung")
        if "b" not in backends:
            pipeline.check_tools(ui)
            backends["b"] = Backends(cfg)
        result = pipeline.process(job, settings, backends["b"].get(args.model or entry["model"]), ui)
        return {**result, "fallback_reason": reason}

    rows = q.run(cfg.state_file, work, max_items=args.max, ui=ui, on_plan=on_plan)
    if rows:
        ui.note("Protokoll dieses Laufs")
        print_log(rows)
    return 1 if any(r["status"] == "failed" for r in rows) else 0


def cmd_queue_retry(args, cfg):
    path = cfg.state_file
    ui.step("fehlgeschlagene Einträge wieder einplanen (Versuche zurück auf 0)")
    with q.locked(path):
        state = q.Queue(path)
        if args.failed:
            keys = [k for k, e in state.ordered() if e["status"] == "failed"]
        else:
            ref = args.ref.strip()
            keys = [k for k, e in state.ordered()
                    if (ref.isdigit() and e.get("index") == int(ref)) or e.get("guid") == ref]
            if not keys:
                raise Abort(f"{ref!r} ist nicht in der Queue ('transcribe queue status' zeigt sie)")
            if len(keys) > 1:
                raise Abort(f"{ref!r} passt auf {len(keys)} Einträge (mehrere Feeds) - guid angeben")
            e = state.get(keys[0])
            if e["status"] != "failed":
                raise Abort(f"Episode {ref} ist nicht fehlgeschlagen (Status: {e['status']}) - nichts zurückgesetzt")
        if not keys:
            ui.result("keine fehlgeschlagenen Einträge")
            return 0
        state.retry(keys, force_asr=args.asr)
        state.save()
    ui.result(f"{len(keys)} Einträge wieder pending" + (" (mit --asr: Whisper erzwungen)" if args.asr else ""))
    ui.note("Abarbeiten mit: transcribe queue run")
    return 0


def cmd_queue_status(args, cfg):
    path = cfg.state_file
    ui.step(f"Queue lesen: {path}")
    state = q.Queue(path)
    if not state.entries:
        ui.result("Queue ist leer")
        return 0
    for _, e in state.ordered():
        t = e.get("timings") or {}
        mins = f"{t['audio_seconds'] / 60:.1f} min" if t.get("audio_seconds") else ""
        err = f"  ({e['error']})" if e.get("error") else ""
        out(f"{e.get('index') or '-':>4}  {e['status']:<8} {e['attempts']}x  {mins:>9}  {e['title']}{err}")
    counts = {s: sum(1 for e in state.entries.values() if e["status"] == s) for s in q.STATUSES}
    ui.result(", ".join(f"{n} {s}" for s, n in counts.items()))
    if counts["running"]:
        try:
            with q.locked(path):
                ui.warn(f"{counts['running']} Eintrag/Einträge auf 'running', aber kein Lauf aktiv "
                        "(Prozess beendet) - der nächste 'queue run' plant sie neu ein")
        except q.QueueError:
            ui.result("ein Lauf ist gerade aktiv")
    return 0


# ---------- argument parsing ----------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", help="faster-whisper-Modell (small, medium, ...); Standard aus der Konfig")
    common.add_argument("--language", help="en, de, ... oder auto; Standard aus der Konfig")
    common.add_argument("--yes", action="store_true", help="Rechte-Rückfrage ohne Nachfrage bestätigen")
    common.add_argument("--config", type=Path, help="Konfig-Datei (Standard: ~/.config/transcribe/config)")
    asr = argparse.ArgumentParser(add_help=False)
    asr.add_argument("--asr", action="store_true",
                     help="eigene Erkennung (Whisper) erzwingen, auch wenn der Herausgeber ein Transkript anbietet")
    out = argparse.ArgumentParser(add_help=False)
    out.add_argument("--out", type=Path, help="Ausgabeordner (Standard: OUT_DIR aus der Konfig)")

    p = argparse.ArgumentParser(prog="transcribe", description=(
        "Podcast-Episoden lokal auf der CPU in Markdown mit Zeitstempeln umwandeln. "
        "Erklärungen gehen auf stderr, Ergebnisse auf stdout."))
    p.add_argument("--version", action="version", version=f"transcribe {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("resolve", parents=[common], help="Spotify/Apple/Feed-URL -> öffentlicher Feed")
    s.add_argument("url")
    s = sub.add_parser("list", parents=[common], help="Episoden nummeriert anzeigen")
    s.add_argument("feed_url")
    s.add_argument("--limit", type=int)
    s = sub.add_parser("one", parents=[common, out, asr], help="eine Episode komplett")
    s.add_argument("feed_url")
    s.add_argument("episode", help="Nummer aus 'transcribe list' oder guid")
    s = sub.add_parser("file", parents=[common, out], help="beliebiges Audio, ohne Feed")
    s.add_argument("source", help="Pfad oder http(s)-URL")

    qp = sub.add_parser("queue", help="Warteschlange für lange Läufe")
    qsub = qp.add_subparsers(dest="qcmd", required=True)
    s = qsub.add_parser("add", parents=[common, out, asr], help="Episoden einplanen")
    s.add_argument("feed_url")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--range", help="z.B. 1-10")
    s = qsub.add_parser("run", parents=[common, asr], help="Queue abarbeiten; abbrechen und neu starten ist sicher")
    s.add_argument("--max", type=int, help="höchstens N Episoden in diesem Lauf")
    qsub.add_parser("status", parents=[common], help="Stand der Queue")
    s = qsub.add_parser("retry", parents=[common, asr], help="fehlgeschlagene Einträge wieder einplanen")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("ref", nargs="?", help="Nummer oder guid eines fehlgeschlagenen Eintrags")
    g.add_argument("--failed", action="store_true", help="alle fehlgeschlagenen Einträge")
    return p


COMMANDS = {"resolve": cmd_resolve, "list": cmd_list, "one": cmd_one, "file": cmd_file,
            ("queue", "add"): cmd_queue_add, ("queue", "run"): cmd_queue_run,
            ("queue", "status"): cmd_queue_status, ("queue", "retry"): cmd_queue_retry}

EXPECTED = (Abort, config.ConfigError, feed.FeedError, resolve.ResolveError, q.QueueError,
            pipeline.PipelineError, urllib.error.URLError, subprocess.CalledProcessError, OSError, RuntimeError)


def main(argv=None):
    args = build_parser().parse_args(argv)
    command = COMMANDS[(args.cmd, args.qcmd) if args.cmd == "queue" else args.cmd]
    try:
        cfg = load_config(args)
        return command(args, cfg)
    except KeyboardInterrupt:
        ui.error("abgebrochen (Strg-C) - 'transcribe queue run' setzt später an derselben Stelle fort")
        return 130
    except EXPECTED as exc:
        ui.error(str(exc))
        return 1
