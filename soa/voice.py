import json, queue, threading
from . import config


class PcMic(threading.Thread):
    """Optional offline PC microphone via Vosk. Feeds FINAL segments to on_final(text)."""
    def __init__(self, on_final, log=print):
        super().__init__(daemon=True)
        self.on_final, self.log = on_final, log

    def run(self):
        try:
            import sounddevice as sd, vosk
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(config.DATA / "vosk"))
            rec = vosk.KaldiRecognizer(model, 16000)
            q = queue.Queue()
            with sd.RawInputStream(samplerate=16000, blocksize=4000, dtype="int16", channels=1,
                                   callback=lambda d, f, t, s: q.put(bytes(d))):
                self.log("PC mic listening (vosk)")
                while True:
                    if rec.AcceptWaveform(q.get()):
                        text = json.loads(rec.Result()).get("text", "")
                        if text:
                            self.on_final(text)
        except Exception as e:
            self.log(f"PC mic disabled ({e}). Run: python install.py --voice")


class Speaker:
    """Optional local TTS (pyttsx3). Browser TTS is the default."""
    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text):
        self.q.put(text)

    def _run(self):
        try:
            import pyttsx3
            eng = pyttsx3.init()
        except Exception:
            return
        while True:
            eng.say(self.q.get())
            eng.runAndWait()
