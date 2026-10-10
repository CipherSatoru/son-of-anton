"""Offline text-to-speech. Tries Piper (neural, British male 'alan') then the OS voice (pyttsx3). Used when edge-tts has no internet."""
import threading, wave
from pathlib import Path
from . import config

MODEL = config.DATA / "piper" / "en_GB-alan-medium.onnx"
_voice = None
_lock = threading.Lock()


def _piper(text, out):
    global _voice
    from piper import PiperVoice
    if _voice is None:
        _voice = PiperVoice.load(str(MODEL))
    with wave.open(str(out), "wb") as w:
        try:
            _voice.synthesize_wav(text, w)
        except AttributeError:
            _voice.synthesize(text, w)


def _sapi(text, out):
    import pyttsx3
    e = pyttsx3.init()
    vs = e.getProperty("voices") or []
    pick = next((v for v in vs if any(k in v.name.lower() for k in ("david", "mark", "george", "james", "ryan", "guy"))), None) \
        or next((v for v in vs if not any(k in v.name.lower() for k in ("zira", "hazel", "susan", "female"))), None)
    if pick:
        e.setProperty("voice", pick.id)
    e.setProperty("rate", 170)
    e.save_to_file(text, str(out))
    e.runAndWait()


def synth(text, out):
    """Write a .wav to `out`. Returns True on success. Blocking: call from an executor."""
    out = Path(out)
    with _lock:
        for fn in ((_piper,) if MODEL.exists() else ()) + (_sapi,):
            try:
                out.unlink(missing_ok=True)
                fn(text, out)
                if out.exists() and out.stat().st_size > 200:
                    return True
            except Exception:
                continue
        out.unlink(missing_ok=True)
        return False
