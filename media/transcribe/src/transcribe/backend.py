"""Speech-to-text backends behind one small interface.

A backend has `name`, `model` and
    transcribe(wav_path, language) -> (segments, info)
where segments is a list of dicts with at least start, end, text (seconds,
str) and info a dict with at least language and duration. Only faster-whisper
is implemented; another backend (e.g. a cloud service) would add a class here.
"""


class FasterWhisper:
    """faster-whisper on CPU, int8.

    Uses only calls documented in faster-whisper 1.2.1's docstrings:
      WhisperModel(model_size_or_path, device="auto", compute_type="int8", cpu_threads=N)
      WhisperModel.transcribe(audio, language=..., beam_size=5) -> (segments generator, TranscriptionInfo)
    The import happens here, not at module level, so the rest of the tool
    (and its tests) runs without the package installed.
    """

    name = "faster-whisper"

    def __init__(self, model, cpu_threads):
        try:
            import faster_whisper
        except ImportError as exc:
            raise RuntimeError("faster-whisper ist nicht installiert - siehe README, Abschnitt Install "
                               f"({exc})") from None
        self.model = model
        self.version = getattr(faster_whisper, "__version__", "unknown")
        self._model = faster_whisper.WhisperModel(model, device="auto", compute_type="int8",
                                                  cpu_threads=cpu_threads)

    def transcribe(self, wav_path, language):
        segments, info = self._model.transcribe(str(wav_path), language=language, beam_size=5)
        rows = []
        for s in segments:  # the generator does the actual work, segment by segment
            rows.append({"id": s.id, "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text,
                         "avg_logprob": round(s.avg_logprob, 4), "no_speech_prob": round(s.no_speech_prob, 4),
                         "compression_ratio": round(s.compression_ratio, 3), "temperature": s.temperature})
        return rows, {"language": info.language, "language_probability": round(info.language_probability, 4),
                      "duration": info.duration}


BACKENDS = {"faster-whisper": FasterWhisper}
