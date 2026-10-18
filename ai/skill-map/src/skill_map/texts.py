"""Which texts can be shown 1:1, and which are withheld with a reason. Texts are
never altered: a text that cannot be shown unchanged is withheld instead."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .paths import UUID_RE, tilde

DEFAULT_REASON = "enthält persönliche Angaben"
SENSITIVE_REASON = "als vertraulich eingestuft"
INVALID_UTF8_REASON = "keine gültige UTF-8-Datei, Wortlaut nicht unverändert darstellbar"
ACCOUNT_ID_REASON = "enthält eine Konto-ID"


@dataclass
class TextResult:
    status: str             # "shown" or "withheld"
    text: str | None        # the file decoded as UTF-8, unchanged (shown only)
    withheld: str | None    # German reason plus the local path (withheld only)
    sha256: str             # of the file bytes, also for withheld texts


# Fail closed: any classification line in the head of a file whose value is not
# explicitly public or internal withholds the text (BOM, case, comments, lists and
# front matter that never closes cannot let a sensitive text through).
_CLASSIFICATION = re.compile(r"^\s*classification\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
SHOWABLE_CLASSES = ("public", "internal")


def _classified(data: bytes) -> bool:
    head = data[:4096].decode("utf-8", "replace")
    for m in _CLASSIFICATION.finditer(head):
        value = m.group(1).split("#", 1)[0].strip().strip("[]").strip().strip("\"'").strip().lower()
        if value not in SHOWABLE_CLASSES:
            return True
    return False


def _withheld_text(reason: str, path: Path) -> str:
    return f"Der Wortlaut wird hier bewusst nicht gezeigt: {reason}. Volltext lokal: {tilde(path)}"


def text_for(key: str, path: Path, cfg: Config, source_note: Path | None) -> TextResult:
    """Decide by the rules in this order: config, classification of the file or of the
    kios source note, valid UTF-8, no account id. The first rule that applies wins."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    reason = None
    text = None
    if key in cfg.withhold_text:
        reason = cfg.withhold_text[key] or DEFAULT_REASON
    elif _classified(data) or (source_note is not None and source_note.is_file()
                               and _classified(source_note.read_bytes()[:4096])):
        reason = SENSITIVE_REASON
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            reason = INVALID_UTF8_REASON
        else:
            if UUID_RE.search(text):
                reason, text = ACCOUNT_ID_REASON, None
    if reason is not None:
        return TextResult("withheld", None, _withheld_text(reason, path), sha)
    return TextResult("shown", text, None, sha)
