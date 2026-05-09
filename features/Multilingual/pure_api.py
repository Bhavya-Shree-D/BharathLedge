"""Google free-tier wrappers: translate, TTS, STT."""

from __future__ import annotations

import io
import time
import wave
import logging
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

SUPPORTED = frozenset({"en", "hi", "te", "kn"})
_STT_LOCALE = {"en": "en-IN", "hi": "hi-IN", "te": "te-IN", "kn": "kn-IN"}

_TIMEOUT = 15
_RETRIES = 2
_BACKOFF = 0.6

_WAV_RATE = 16_000
_WAV_CH = 1
_WAV_WIDTH = 2

T = TypeVar("T")


def _lang(code: str | None) -> str:
    code = (code or "en").lower().strip()
    return code if code in SUPPORTED else "en"


def _retry(fn: Callable[[], T], label: str) -> T | None:
    for i in range(_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            if i == _RETRIES:
                log.error("%s failed: %s", label, e)
                return None
            time.sleep(_BACKOFF * (2 ** i))
    return None


def _is_target_wav(b: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(b)) as w:
            return (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (
                _WAV_RATE, _WAV_CH, _WAV_WIDTH
            )
    except (wave.Error, EOFError):
        return False


def _to_wav(b: bytes) -> bytes | None:
    if _is_target_wav(b):
        return b
    try:
        from pydub import AudioSegment
    except ImportError:
        log.error("pydub missing")
        return None
    try:
        seg = AudioSegment.from_file(io.BytesIO(b))
        seg = seg.set_frame_rate(_WAV_RATE).set_channels(_WAV_CH).set_sample_width(_WAV_WIDTH)
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception as e:
        log.error("audio convert: %s", e)
        return None


# public 

def translate(text: str, src: str, tgt: str) -> str:
    if not text or not text.strip():
        return text
    src, tgt = _lang(src), _lang(tgt)
    if src == tgt:
        return text

    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        log.error("deep-translator missing")
        return text

    def call() -> str:
        out = GoogleTranslator(source=src, target=tgt).translate(text)
        if not isinstance(out, str) or not out.strip():
            raise ValueError("empty result")
        return out

    return _retry(call, f"translate {src}->{tgt}") or text

def translate_batch(texts: list[str], src: str, tgt: str) -> list[str]:
    """Translate many strings in one HTTP call. Returns input on failure."""
    if not texts:
        return texts
    src, tgt = _lang(src), _lang(tgt)
    if src == tgt:
        return texts

    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        log.error("deep-translator missing")
        return texts

    # Filter out empties so we don't waste payload, but preserve positions.
    payload_idx = [i for i, s in enumerate(texts) if s and s.strip()]
    payload     = [texts[i] for i in payload_idx]
    if not payload:
        return texts

    def call() -> list[str]:
        out = GoogleTranslator(source=src, target=tgt).translate_batch(payload)
        if not isinstance(out, list) or len(out) != len(payload):
            raise ValueError(f"bad batch result: {out!r}")
        return out

    translated = _retry(call, f"translate_batch {src}->{tgt} n={len(payload)}")
    if translated is None:
        return texts

    result = list(texts)
    for i, val in zip(payload_idx, translated):
        result[i] = val if isinstance(val, str) and val.strip() else texts[i]
    return result

def synthesize(text: str, lang: str = "en") -> bytes:
    if not text or not text.strip():
        return b""
    lang = _lang(lang)

    try:
        from gtts import gTTS
    except ImportError:
        log.error("gTTS missing")
        return b""

    def call() -> bytes:
        buf = io.BytesIO()
        gTTS(text=text, lang=lang, timeout=_TIMEOUT).write_to_fp(buf)
        data = buf.getvalue()
        if not data:
            raise ValueError("empty audio")
        return data

    return _retry(call, f"tts {lang}") or b""


def transcribe(audio: bytes, lang: str = "en") -> str:
    if not audio:
        return ""
    lang = _lang(lang)
    locale = _STT_LOCALE.get(lang, "en-IN")

    wav = _to_wav(audio)
    if not wav:
        return ""

    try:
        import speech_recognition as sr
    except ImportError:
        log.error("SpeechRecognition missing")
        return ""

    r = sr.Recognizer()
    r.operation_timeout = _TIMEOUT

    try:
        with sr.AudioFile(io.BytesIO(wav)) as src:
            data = r.record(src)
    except Exception as e:
        log.error("stt load: %s", e)
        return ""

    def call() -> str:
        try:
            text = r.recognize_google(data, language=locale)
        except sr.UnknownValueError:
            return ""
        return text.strip() if isinstance(text, str) else ""

    return _retry(call, f"stt {locale}") or ""