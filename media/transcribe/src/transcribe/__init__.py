"""transcribe - local, CPU-only podcast/audio transcription to timestamped Markdown.

Nothing in this package imports faster_whisper at module level; the backend
loads it on first use, so tests and `list`/`resolve` work without it.
"""

__version__ = "0.1.0"
