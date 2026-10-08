"""~/.config/transcribe/config: plain KEY=value lines, parsed here, never shell-evaluated."""

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


KEYS = ("OUT_DIR", "CACHE_DIR", "STATE_FILE", "MODEL", "LANGUAGE", "CPU_THREADS", "KEEP_AUDIO",
        "MAX_AUDIO_MB", "MAX_TEXT_MB")
TRUE = {"yes", "true", "1", "ja", "on"}
FALSE = {"no", "false", "0", "nein", "off"}


@dataclass
class Config:
    out_dir: Path
    cache_dir: Path
    state_file: Path
    model: str
    language: str
    cpu_threads: int
    keep_audio: bool
    max_audio_mb: int = 1024
    max_text_mb: int = 50
    source: Path | None = None


def default_path(env=None):
    env = os.environ if env is None else env
    if env.get("TRANSCRIBE_CONFIG"):
        return Path(env["TRANSCRIBE_CONFIG"])
    return Path(env.get("HOME", "~"), ".config/transcribe/config")


def _expand(value, home):
    if value == "~" or value.startswith("~/"):
        return Path(home + value[1:])
    return Path(value)


def _strip_value(raw):
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end == -1:
            raise ValueError("Anführungszeichen nicht geschlossen")
        return raw[1:end]
    # inline comment only after whitespace, so 'a#b' stays a value
    for marker in (" #", "\t#"):
        if marker in raw:
            raw = raw.split(marker, 1)[0]
    return raw.strip()


def parse(text, origin="config"):
    values = {}
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ConfigError(f"{origin}:{n}: erwartet KEY=value, gefunden: {stripped!r}")
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if key not in KEYS:
            raise ConfigError(f"{origin}:{n}: unbekannter Schlüssel {key!r} (erlaubt: {', '.join(KEYS)})")
        try:
            value = _strip_value(raw)
        except ValueError as exc:
            raise ConfigError(f"{origin}:{n}: {exc}") from None
        if not value:
            raise ConfigError(f"{origin}:{n}: {key} ist leer")
        values[key] = value
    return values


def load(path=None, env=None):
    env = os.environ if env is None else env
    path = Path(path) if path else default_path(env)
    home = env.get("HOME") or str(Path.home())
    values = parse(path.read_text(encoding="utf-8"), str(path)) if path.is_file() else {}

    threads_raw = values.get("CPU_THREADS", str(os.cpu_count() or 4))
    if not threads_raw.isdigit() or int(threads_raw) < 1:
        raise ConfigError(f"CPU_THREADS muss eine positive Zahl sein, nicht {threads_raw!r}")
    limits = {}
    for key, default in (("MAX_AUDIO_MB", "1024"), ("MAX_TEXT_MB", "50")):
        raw = values.get(key, default)
        if not raw.isdigit() or int(raw) < 1:
            raise ConfigError(f"{key} muss eine positive ganze Zahl (Megabyte) sein, nicht {raw!r}")
        limits[key] = int(raw)
    keep_raw = values.get("KEEP_AUDIO", "no").lower()
    if keep_raw not in TRUE | FALSE:
        raise ConfigError(f"KEEP_AUDIO muss yes oder no sein, nicht {keep_raw!r}")

    return Config(
        out_dir=_expand(values.get("OUT_DIR", "~/transcripts"), home),
        cache_dir=_expand(values.get("CACHE_DIR", "~/.cache/transcribe"), home),
        state_file=_expand(values.get("STATE_FILE", "~/.local/state/transcribe/queue.json"), home),
        model=values.get("MODEL", "small"),
        language=values.get("LANGUAGE", "en"),
        cpu_threads=int(threads_raw),
        keep_audio=keep_raw in TRUE,
        max_audio_mb=limits["MAX_AUDIO_MB"],
        max_text_mb=limits["MAX_TEXT_MB"],
        source=path if path.is_file() else None,
    )
