"""The one place that talks HTTP for metadata (feeds, directory lookups, pages, transcripts).

Audio downloads go through curl in pipeline.py so the command can be shown.
Every read is capped (MAX_TEXT_MB in the config) so a broken or hostile
server cannot fill the memory of an unattended run. Tests replace `get`.
"""

import urllib.request

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) transcribe/0.1 (personal use)"
TIMEOUT = 30  # seconds per socket operation
LIMIT_BYTES = 50 * 1024 * 1024
LIMIT_NAME = "MAX_TEXT_MB=50"


class TooLarge(Exception):
    pass


def configure(max_text_mb):
    global LIMIT_BYTES, LIMIT_NAME
    LIMIT_BYTES = int(max_text_mb * 1024 * 1024)
    LIMIT_NAME = f"MAX_TEXT_MB={max_text_mb}"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read(LIMIT_BYTES + 1)
    if len(data) > LIMIT_BYTES:
        raise TooLarge(f"Antwort von {url} ist größer als {LIMIT_NAME} - abgelehnt")
    return data
