# transcribe — podcast episodes to timestamped Markdown, locally on CPU

Turn public podcast episodes (or any audio file) into Markdown transcripts with
`[mm:ss]` stamps — on your own machine, no GPU, no cloud account — and let a
resumable queue work through a whole show for hours or days.

## The problem

You want the text of a podcast — say 107 episodes of an exam-prep show, about
34 hours of audio — to search, quote and learn from. Cloud transcription costs
money and sends the audio elsewhere; doing it by hand on a laptop means a run
of many hours that a reboot, a closed lid or a network hiccup can interrupt.

## The idea

- **The public RSS feed is the source.** A Spotify or Apple Podcasts link is
  only used to *find* the feed: Spotify gives the show title, Apple's public
  podcast directory gives the feed URL. Audio is never fetched from Spotify.
  When no feed with exactly that title (and author) exists, the tool stops —
  it never falls back to a similar show.
- **Publisher transcripts first.** Many feeds link the show's own transcript
  (`<podcast:transcript>`); that text is usually the original script, so it is
  more accurate than any recognition and takes seconds instead of minutes, with
  no audio download at all. Only when an episode has none (in a usable format)
  does the tool fall back to its own recognition.
- **Local, CPU-only** speech recognition with
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper), behind a small
  backend interface so another engine could be added later.
- **A queue that survives being killed.** State is one JSON file, written
  atomically after every change. Stop it with Ctrl-C, `kill -9` or a reboot;
  the next `queue run` continues where it stopped and skips what is done.
- **Honest metadata.** Feed titles can be wrong (one tested feed has an episode
  titled "Inside the Exam" whose audio is about global infrastructure). The title
  is stored as `title_verified: false`; the tool never claims it matches the audio.
- **Rights first.** Before any download the feed's `<copyright>` (and license tag,
  if present) is shown with the reminder that transcripts are for personal use.
- Every step is printed with a one-line explanation before it runs
  (*explain-then-run*), the same style as the other tools in this repository.

## Usage

```text
transcribe resolve <spotify-or-apple-url|feed-url>      # show title, feed URL, copyright, episode count
transcribe list <feed-url> [--limit N]                  # numbered episodes: index, date, duration, title
transcribe one <feed-url> <index|guid> [--out DIR] [--asr]   # one episode end to end
transcribe file <audio-path-or-url> [--out DIR]         # any audio, no feed
transcribe queue add <feed-url> (--all | --range 1-10) [--out DIR] [--asr]
transcribe queue run [--max N] [--asr]                  # works the queue; safe to stop and restart
transcribe queue status
transcribe queue retry [--asr] (<index|guid> | --failed)  # failed entries back to pending, attempts 0
```

Options on every command: `--model small|medium|…`, `--language en|de|auto`
(default from the config), `--yes` (confirm the rights notice without asking),
`--config FILE`. `--asr` forces Whisper even where the publisher offers a
transcript — e.g. to compare both (use a different `--out`, the file name is the same).

Episode numbers are the tool's own: **chronological, oldest = 1**, so they stay
the same when the show publishes new episodes. `list` shows them.

Explanations go to **stderr**, results to **stdout**. The rights question needs
a terminal; in scripts pass `--yes`. `queue run` never asks — you confirmed
when you added the episodes.

## What it looks like

```text
$ transcribe resolve https://open.spotify.com/show/3Kfpi2wm8bjRVL5YEV6asV

* Spotify-Seite lesen - nur den Showtitel (og:title) und Autor, nie Audio
  > GET https://open.spotify.com/show/3Kfpi2wm8bjRVL5YEV6asV

* Apples öffentliches Podcast-Verzeichnis nach exakt diesem Titel fragen
  > GET https://itunes.apple.com/search?term=Certified+-+AWS+Certified+Cloud+Practitioner+Audio+Course&media=podcast
  = Feed: https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner

* RSS-Feed laden (Titel, Copyright, Episodenliste)
  > GET https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner
  = 'Certified - AWS Certified Cloud Practitioner Audio Course': 107 Episoden, 107 mit Audio
Show:       Certified - AWS Certified Cloud Practitioner Audio Course
Feed:       https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner
Copyright:  @ 2025 BareMetalCyber
Episoden:   107

$ transcribe resolve https://open.spotify.com/show/68htxokT392uDDDkMQV4pp
...
Fehler: kein öffentlicher Feed gefunden – Spotify-exklusiv oder nicht verzeichnet; nichts wird
transkribiert (Spotify-Titel: '☁️AWS Cloud Practitioner Essentials', Autor: 'Thomas Sxt')
```

```text
$ transcribe one https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner 1 --asr

* Episode 1 gewählt (Feed-Titel, ungeprüft): Episode 1: Welcome to the AWS CCP PrepCast & Why It Matters

* Rechte-Hinweis vor jedem Download
  = Copyright laut Feed: @ 2025 BareMetalCyber
  ! Transkripte sind nur für den persönlichen Gebrauch; nicht veröffentlichen.
Weiter? [J/n]

* --asr: eigene Erkennung mit Whisper, obwohl der Herausgeber ein Transkript anbietet

* Modell 'small' laden (beim ersten Mal von Hugging Face geladen, danach aus dem Cache)
  > WhisperModel('small', device='auto', compute_type='int8', cpu_threads=16)
  = faster-whisper 1.2.1

* Audio herunterladen (in den Cache; .part bis vollständig; Grenzen für Größe und Stillstand)
  > curl -fL --globoff --proto =http,https --proto-redir =http,https --speed-limit 1024
      --speed-time 60 --max-filesize 1073741824 --retry 3 --retry-delay 5 --silent --show-error
      -o ~/.cache/transcribe/378c95fbe0cea54f.mp3.part https://media.transistor.fm/40bdbda8/00dbc723.mp3
  = 18.207.151 Bytes, sha256 6c13575171edb187…

* auf Mono 16 kHz WAV normalisieren - das Format, mit dem Whisper rechnet
  > ffmpeg -nostdin -hide_banner -loglevel error -y -i ~/.cache/transcribe/378c95fbe0cea54f.mp3
      -ac 1 -ar 16000 -c:a pcm_s16le ~/.cache/transcribe/378c95fbe0cea54f.wav
  = 18.9 min Audio

* transkribieren mit faster-whisper small (Sprache: en) - dauert Minuten pro Episode; ein Fortschritt wird nicht angezeigt

* WAV aus dem Cache löschen (KEEP_AUDIO=no)
  = 276 Segmente in 126 s (Faktor 0.11 der Audiodauer), erkannte Sprache: en

* Markdown und Roh-Segmente schreiben (atomar: erst Temp-Datei, dann umbenennen)
  = ~/transcripts/certified-aws-certified-cloud-practitioner-audio-course/001-episode-1-welcome-to-the-aws-ccp-prepcast-why-it-matters.md

* heruntergeladenes Audio aus dem Cache löschen (KEEP_AUDIO=no)

* Protokoll
  Nr  Audio-min  Rechen-s  Faktor  Quelle    Status
   1       18.9       126    0.11  ASR       done
```

A second `queue run` on a finished queue:

```text
* Queue lesen: ~/.local/state/transcribe/queue.json
  = 0 pending, 0 running, 2 done, 0 failed

* Nichts zu tun: 2 erledigt, 0 endgültig fehlgeschlagen (nach 3 Versuchen). Kein Download, kein Modell geladen.
```

## Publisher transcripts

Per episode the tool picks, in this order: `text/vtt` or `application/x-subrip`
(they keep timestamps → `[mm:ss]` paragraphs), then `text/plain`, then
`text/html` (tags stripped). `application/json` is skipped — there is no
verified sample of that format here, so the tool uses its own recognition
rather than guess. The rights notice still comes before the transcript download.
`list` marks episodes with a usable transcript, e.g. `[Transkript: text/plain]`.

```text
$ transcribe one https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner 3

* Rechte-Hinweis vor jedem Download
  = Copyright laut Feed: @ 2025 BareMetalCyber
  ! Transkripte sind nur für den persönlichen Gebrauch; nicht veröffentlichen.
Weiter? [J/n]

* Transkript des Herausgebers vorhanden (text/plain) - wird statt eigener Erkennung genutzt; kein Audio, kein Modell (--asr erzwingt Whisper)

* Transkript des Herausgebers laden - kein Audio-Download nötig
  > GET https://share.transistor.fm/s/39a65862/transcript.txt
  = 17.713 Bytes, sha256 c3dd19540fa13164…

* 29 Absätze (text/plain, ohne Zeitmarken) - Markdown ohne Stempel schreiben
  = ~/transcripts/certified-aws-certified-cloud-practitioner-audio-course/003-episode-3-inside-the-exam-domains-scoring-question-types.md
```

Such a file has `backend: "publisher-transcript"`, `model: null`, the
`audio_*` fields `null`, and `transcript_url`, `transcript_type`,
`transcript_sha256` set; its note says *"Transkript des Herausgebers, nicht von
uns erzeugt, ungeprüft"*. Plain text and HTML have no timestamps, so their
paragraphs carry no stamps. (For a recognised episode it is the other way round:
`transcript_*` are `null`.)

## Output

`<OUT_DIR>/<show-slug>/<NNN>-<title-slug>.md` (for `file`: `<OUT_DIR>/files/<name>-<hash8>.md`, the hash of the absolute
path or URL, so two `talk.mp3` from different folders never overwrite each other):

```markdown
---
title: "Episode 1: Welcome to the AWS CCP PrepCast & Why It Matters"
title_verified: false
show: "Certified - AWS Certified Cloud Practitioner Audio Course"
feed_url: "https://feeds.transistor.fm/certified-aws-certified-cloud-practitioner"
episode_guid: "23073a0a-d51e-4f1e-8871-5e4103080823"
episode_index: 1
published: "2025-08-30T17:34:03-05:00"
audio_url: "https://media.transistor.fm/40bdbda8/00dbc723.mp3"
audio_sha256: "6c13575171edb1873b05677f42b63d8d167ea14921cdf5caaf4f46fb9efeeb67"
audio_bytes: 18207151
audio_seconds: 1133.82
transcript_url: null
transcript_type: null
transcript_sha256: null
copyright: "@ 2025 BareMetalCyber"
backend: "faster-whisper"
model: "small"
language: "en"
transcribed_at: "2026-10-08T09:55:56Z"
tool_version: "0.1.0"
source_tier: "hypothesis"
use: "personal-only"
---

> Automatic transcript (faster-whisper small), unchecked. The title comes from the feed and was not verified against the audio. Personal use only.

[00:00] Welcome to the AWS Certified Cloud Practitioner Prepcast, where we guide you …

[01:01] The goal is not only to prepare you for an exam, but also to help you feel …
```

- One stamp per paragraph of about a minute (recognised audio, VTT/SRT) (a paragraph ends at the first
  sentence end after 60 s, at the latest after 90 s). Minutes keep counting past
  59 (`[62:03]`), so every stamp has the same format.
- Frontmatter values are JSON scalars, which any YAML parser also reads.
- Next to it, `<same>.segments.json` holds the raw segments (start, end, text,
  `avg_logprob`, `no_speech_prob`, …) for tools that want finer timing.

## The queue

`queue add` writes one entry per (feed, episode guid) into `STATE_FILE`, with
status `pending`. Adding the same episode again changes nothing. `queue run`:

1. takes a lock — a second `queue run`, or a `queue add`, on the same queue
   stops with "die Queue ist gerade gesperrt"; add episodes before or after a run;
2. puts entries a killed run left on `running` back to `pending` — the killed
   attempt counts, so an episode that crashes the process every time (out of
   memory, a segfault) ends as `failed` after 3 attempts instead of blocking
   every restart;
3. checks every `done` entry: its Markdown must exist and carry the sha256 the
   queue recorded — `transcript_sha256` for publisher entries, `audio_sha256`
   for recognised ones — otherwise the episode is redone;
4. works `pending` entries (and `failed` ones, up to 3 attempts), oldest first,
   saving the state after every change (temp file + rename);
5. prints one log line per episode: index, audio minutes, compute seconds,
   ratio, source (`Herausg.` or `ASR`), status.

Each entry records which backend actually produced it (`backend`) and, after a
fallback, why (`fallback_reason`). `queue add --asr` stores the choice per
entry; `queue run --asr` forces Whisper for the entries this run works
(pending/failed) — `done` entries stay as they are.

If a publisher transcript exists but cannot be used — 404, timeout, empty,
unparseable, larger than `MAX_TEXT_MB` — the tool prints
`! Herausgeber-Transkript unbrauchbar (…) - eigene Erkennung` and runs Whisper
in the same attempt.

A failed episode does not stop the run; the error text is stored and shown by
`queue status`. Exit code is 1 if any episode failed in this run. After 3
attempts an entry stays `failed`; `transcribe queue retry --failed` (or
`queue retry <index|guid>`, optionally with `--asr`) puts it back to `pending`
with a fresh attempt count.

Downloads are bounded so an unattended run cannot hang or fill the disk: curl
gives up below 1024 bytes/s for 60 s and refuses audio above `MAX_AUDIO_MB`;
feeds, pages and transcripts above `MAX_TEXT_MB` are refused. Each refusal
names the limit.

## Running in the background

```bash
mkdir -p ~/.local/state/transcribe
nohup transcribe queue run > ~/.local/state/transcribe/run.log 2>&1 &
tail -f ~/.local/state/transcribe/run.log      # watch; Ctrl-C stops only tail
```

Or as a systemd user service (example only — the tool does not install it).
`~/.config/systemd/user/transcribe-queue.service`:

```ini
[Unit]
Description=transcribe: work the podcast transcription queue

[Service]
Type=exec
ExecStart=%h/.local/bin/transcribe queue run
Nice=10
CPUWeight=20
IOSchedulingClass=idle
```

```bash
systemctl --user daemon-reload
systemctl --user start transcribe-queue      # runs until the queue is done, then exits
journalctl --user -u transcribe-queue -f     # follow the output
```

Why low priority: transcription keeps every core busy for hours, and at normal
priority the laptop gets sluggish for everything else. With `Nice=10`, a low
`CPUWeight` and idle I/O scheduling, your interactive work always comes first
and the queue only uses what is left over — it just takes a bit longer.

## Configuration

`~/.config/transcribe/config` (or `--config FILE`, or `$TRANSCRIBE_CONFIG`):
plain `KEY=value` lines, read by Python, never evaluated by a shell. Every key
is optional; see [example.conf](example.conf).

| Key | Default | Meaning |
|---|---|---|
| `OUT_DIR` | `~/transcripts` | where transcripts go |
| `CACHE_DIR` | `~/.cache/transcribe` | downloaded audio and the WAV while working |
| `STATE_FILE` | `~/.local/state/transcribe/queue.json` | queue state |
| `MODEL` | `small` | faster-whisper model (`tiny` … `large-v3`) |
| `LANGUAGE` | `en` | spoken language, or `auto` |
| `CPU_THREADS` | all cores | threads for the model |
| `KEEP_AUDIO` | `no` | `yes` keeps MP3 and WAV after success |
| `MAX_AUDIO_MB` | `1024` | refuse larger audio downloads (curl `--max-filesize`) |
| `MAX_TEXT_MB` | `50` | refuse larger feeds, pages, publisher transcripts |

Unknown keys or unreadable values stop the tool with the line number.
A local file passed to `transcribe file` is never deleted.

## Speed and memory

Measured on one laptop (16 cores, 23 GB RAM, no GPU, Python 3.14, 2026-10-08) —
your numbers will differ:

| Model | Compute per audio minute | Peak memory |
|---|---|---|
| `small` | ~6.8 s (≈ 0.11 × real time; 126 s for a 19-minute episode) | ~1.4–1.5 GB |
| `medium` | ~17.6 s | ~2.0 GB |

At `small`, 34 hours of audio take roughly 4 hours of compute.

## Requirements

- Linux, Python ≥ 3.12 (tested with 3.14; the tests also run on 3.12)
- `curl` and `ffmpeg` on `PATH` (Fedora: `sudo dnf install ffmpeg`)
- Disk for the model in `~/.cache/huggingface`, downloaded on first use: about 460 MB
  for `small`, 1.5 GB for `medium`
- [requirements.txt](requirements.txt): `faster-whisper==1.2.1` and `av<17` —
  faster-whisper 1.2.1 failed with PyAV 19 (`TypeError: open() got an unexpected
  keyword argument 'metadata_errors'`), PyAV 16 works

## Install

From this directory:

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
# or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

mkdir -p ~/.local/bin ~/.config/transcribe
ln -s "$(pwd)/transcribe" ~/.local/bin/transcribe      # ~/.local/bin on PATH
cp example.conf ~/.config/transcribe/config            # optional, then edit
```

The launcher follows its symlink to this directory and uses `.venv` next to
it (or the venv in `$TRANSCRIBE_VENV`).

## Tests

```bash
python3 -m pytest -q tests        # stdlib + pytest only: no network, no model
```

## Limits

- Publisher transcripts in `application/json` are not read (fallback to recognition).
- Only public RSS feeds. Spotify-exclusive shows cannot be transcribed and are refused.
- Transcripts are unchecked machine output (`source_tier: hypothesis`) and for
  personal use; the tool does not check what the copyright allows.
- No progress bar during transcription; the log line comes when an episode is done.
