"""One episode (or audio file) end to end: download, normalise, transcribe, write."""

import functools
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, markdown, net, publisher
from .ui import Silent  # noqa: F401  (re-exported for callers and tests)


class PipelineError(Exception):
    pass


class PublisherUnusable(Exception):
    """The publisher transcript could not be fetched or read; the caller falls back to ASR."""


@dataclass
class Job:
    show: str | None
    feed_url: str | None
    guid: str | None
    index: int | None
    title: str
    published: str | None
    audio_url: str          # http(s) URL or local path
    copyright: str | None
    out_dir: Path
    language: str           # "auto" = let the model detect it
    transcripts: list = field(default_factory=list)  # feed.Transcript items of the episode


@dataclass
class Settings:
    cache_dir: Path
    keep_audio: bool
    max_audio_mb: int = 1024


def file_job(source, out_dir, language):
    """A Job for `transcribe file`: a local path or an audio URL, no feed."""
    is_url = urlparse(source).scheme in ("http", "https")
    if not is_url and not Path(source).is_file():
        raise PipelineError(f"Datei nicht gefunden: {source}")
    name = Path(urlparse(source).path).stem if is_url else Path(source).stem
    return Job(show=None, feed_url=None, guid=None, index=None, title=name or "audio", published=None,
               audio_url=source if is_url else str(Path(source).resolve()), copyright=None,
               out_dir=Path(out_dir), language=language)


def output_for(job):
    if job.index is None:
        # short hash of the absolute path or URL: two 'talk.mp3' in different folders never collide
        tag = hashlib.sha1(job.audio_url.encode()).hexdigest()[:8]
        return Path(job.out_dir) / "files" / f"{markdown.slugify(job.title)}-{tag}.md"
    return markdown.output_path(job.out_dir, job.show, job.index, job.title)


STALL_BYTES_PER_S = 1024
STALL_SECONDS = 60
MB = 1024 * 1024


def curl_command(url, tmp, max_bytes):
    # --globoff: [] and {} in a feed URL are literal, never a curl range/list
    # --speed-limit/--speed-time: give up when a server trickles (< 1 KB/s for 60 s)
    # --max-filesize: refuse audio above MAX_AUDIO_MB instead of filling the disk
    return ["curl", "-fL", "--globoff", "--proto", "=http,https", "--proto-redir", "=http,https",
            "--speed-limit", str(STALL_BYTES_PER_S), "--speed-time", str(STALL_SECONDS),
            "--max-filesize", str(max_bytes), "--retry", "3", "--retry-delay", "5",
            "--silent", "--show-error", "-o", str(tmp), url]


def curl_download(url, dest, ui, max_bytes=1024 * MB):
    tmp = dest.with_name(dest.name + ".part")
    cmd = curl_command(url, tmp, max_bytes)
    ui.step("Audio herunterladen (in den Cache; .part bis vollständig; Grenzen für Größe und Stillstand)", cmd)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        # curl exit codes: 63 = maximum file size exceeded, 28 = operation timeout (speed limit)
        if exc.returncode == 63:
            raise PipelineError(f"Audio größer als MAX_AUDIO_MB={max_bytes // MB} - Download abgebrochen") from None
        if exc.returncode == 28:
            raise PipelineError(f"Download stockt: unter {STALL_BYTES_PER_S} Bytes/s für {STALL_SECONDS} s "
                                "- abgebrochen") from None
        raise
    os.replace(tmp, dest)


def ffmpeg_normalise(src, dst, ui):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    ui.step("auf Mono 16 kHz WAV normalisieren - das Format, mit dem Whisper rechnet", cmd)
    subprocess.run(cmd, check=True)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return round(w.getnframes() / w.getframerate(), 2)


def _cache_name(job):
    ident = f"{job.feed_url}#{job.guid}" if job.feed_url else job.audio_url
    stem = hashlib.sha1(ident.encode()).hexdigest()[:16]
    ext = Path(urlparse(job.audio_url).path).suffix.lower()
    return stem, (ext if ext and len(ext) <= 5 else ".audio")


def _write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp creates 0600; transcripts are ordinary files
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def process(job, settings, backend, ui, fetch=None, normalise=ffmpeg_normalise):
    """Returns {output, audio_sha256, audio_seconds, compute_seconds, download_seconds}."""
    fetch = fetch or functools.partial(curl_download, max_bytes=settings.max_audio_mb * MB)
    cache = Path(settings.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    stem, ext = _cache_name(job)
    local_input = urlparse(job.audio_url).scheme not in ("http", "https")
    if local_input and job.feed_url is not None:
        raise PipelineError(f"Audio-URL aus dem Feed ist keine http(s)-URL: {job.audio_url!r}")

    t0 = time.monotonic()
    if local_input:
        audio = Path(job.audio_url)
        ui.step("lokale Datei verwenden (wird nie gelöscht)")
        ui.result(str(audio))
    else:
        audio = cache / (stem + ext)
        if audio.exists():
            ui.step("Audio liegt schon im Cache (von einem früheren Versuch) - kein neuer Download")
            ui.result(str(audio))
        else:
            fetch(job.audio_url, audio, ui)
    download_seconds = round(time.monotonic() - t0, 1)
    size = audio.stat().st_size
    digest = sha256_of(audio)
    ui.result(f"{size:,} Bytes".replace(",", ".") + f", sha256 {digest[:16]}…")

    wav = cache / (stem + ".wav")
    normalise(audio, wav, ui)
    seconds = wav_seconds(wav)
    ui.result(f"{seconds / 60:.1f} min Audio")

    ui.step(f"transkribieren mit {backend.name} {backend.model} (Sprache: {job.language}) - "
            "dauert Minuten pro Episode; ein Fortschritt wird nicht angezeigt")
    t1 = time.monotonic()
    try:
        segments, info = backend.transcribe(wav, None if job.language == "auto" else job.language)
    finally:
        if wav.exists() and not settings.keep_audio:
            ui.step("WAV aus dem Cache löschen (KEEP_AUDIO=no)")
            wav.unlink()
    compute = round(time.monotonic() - t1, 1)
    ui.result(f"{len(segments)} Segmente in {compute:.0f} s (Faktor {compute / max(seconds, 1):.2f} "
              f"der Audiodauer), erkannte Sprache: {info.get('language')}")

    out = output_for(job)
    meta = {
        "title": job.title, "title_verified": False, "show": job.show, "feed_url": job.feed_url,
        "episode_guid": job.guid, "episode_index": job.index, "published": job.published,
        "audio_url": job.audio_url, "audio_sha256": digest, "audio_bytes": size, "audio_seconds": seconds,
        "transcript_url": None, "transcript_type": None, "transcript_sha256": None,
        "copyright": job.copyright, "backend": backend.name, "model": backend.model,
        "language": info.get("language") or job.language,
        "transcribed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_version": __version__, "source_tier": "hypothesis", "use": "personal-only",
    }
    ui.step("Markdown und Roh-Segmente schreiben (atomar: erst Temp-Datei, dann umbenennen)")
    _write_atomic(markdown.segments_path(out), json.dumps(
        {"meta": meta, "info": info, "segments": segments}, ensure_ascii=False, indent=1) + "\n")
    _write_atomic(out, markdown.render(meta, segments))
    ui.result(str(out))

    if not local_input and not settings.keep_audio:
        ui.step("heruntergeladenes Audio aus dem Cache löschen (KEEP_AUDIO=no)")
        audio.unlink()
    return {"output": str(out), "backend": backend.name, "audio_sha256": digest, "audio_bytes": size,
            "audio_seconds": seconds,
            "compute_seconds": compute, "download_seconds": download_seconds}


def _traced(ui):
    def get(url):
        ui.step("Transkript des Herausgebers laden - kein Audio-Download nötig", f"GET {url}")
        return net.get(url)
    return get


def process_publisher(job, transcript, ui, get=None):
    """Use the publisher's own transcript instead of ASR: no audio, no model."""
    if urlparse(transcript.url).scheme not in ("http", "https"):
        raise PipelineError(f"Transkript-URL ist keine http(s)-URL: {transcript.url!r}")
    get = get or _traced(ui)
    t0 = time.monotonic()
    try:
        data = get(transcript.url)
        digest = hashlib.sha256(data).hexdigest()
        ui.result(f"{len(data):,} Bytes".replace(",", ".") + f", sha256 {digest[:16]}…")
        parsed = publisher.parse(data, transcript.type)
    except (publisher.TranscriptError, net.TooLarge, OSError, http.client.HTTPException, ValueError) as exc:
        # OSError covers urllib's URLError/HTTPError and socket timeouts
        raise PublisherUnusable(f"{type(exc).__name__}: {exc}") from exc
    kind = publisher.base_type(transcript.type)
    elapsed = round(time.monotonic() - t0, 1)
    language = transcript.language or (None if job.language == "auto" else job.language)

    out = output_for(job)
    meta = {
        "title": job.title, "title_verified": False, "show": job.show, "feed_url": job.feed_url,
        "episode_guid": job.guid, "episode_index": job.index, "published": job.published,
        "audio_url": None, "audio_sha256": None, "audio_bytes": None, "audio_seconds": None,
        "transcript_url": transcript.url, "transcript_type": kind, "transcript_sha256": digest,
        "copyright": job.copyright, "backend": markdown.PUBLISHER, "model": None, "language": language,
        "transcribed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_version": __version__, "source_tier": "hypothesis", "use": "personal-only",
    }
    seg_file = markdown.segments_path(out)
    if "segments" in parsed:
        ui.step(f"{len(parsed['segments'])} Zeitmarken-Abschnitte ({kind}) - Markdown mit [mm:ss] schreiben")
        _write_atomic(seg_file, json.dumps({"meta": meta, "segments": parsed["segments"]},
                                           ensure_ascii=False, indent=1) + "\n")
        text = markdown.render(meta, parsed["segments"])
    else:
        ui.step(f"{len(parsed['paragraphs'])} Absätze ({kind}, ohne Zeitmarken) - Markdown ohne Stempel schreiben")
        if seg_file.exists():
            seg_file.unlink()  # a segments file from an earlier ASR run would not match this text
        text = markdown.render(meta, paragraphs_plain=parsed["paragraphs"])
    _write_atomic(out, text)
    ui.result(str(out))
    return {"output": str(out), "backend": markdown.PUBLISHER, "transcript_sha256": digest,
            "audio_sha256": None, "audio_bytes": None, "audio_seconds": None, "compute_seconds": elapsed,
            "download_seconds": elapsed}


def check_tools(ui):
    missing = [t for t in ("curl", "ffmpeg") if shutil.which(t) is None]
    if missing:
        raise PipelineError(f"fehlende Programme: {', '.join(missing)} (z.B. 'sudo dnf install ffmpeg')")
