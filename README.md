# Son of Anton
Jarvis-style PC agent. Tiny local model for instant talk, free cloud models for tasks, vision, male neural voice, self-improving, self-updating.

## Install (once)
```
git clone https://github.com/CipherSatoru/son-of-anton.git   # or download the zip from GitHub
cd son-of-anton
python install.py --voice --autostart
python run.py bg          # hidden in background + tray icon
python run.py open        # dashboard
```
Then in the dashboard → **Keys**: paste your free API keys (Kilo/Groq/NVIDIA/OpenRouter) and a read-only **GITHUB_TOKEN**
(GitHub → Settings → Developer settings → Fine-grained token → only this repo → Contents: Read-only). Keys live in `.env` and are never overwritten by updates.

## Commands
`python run.py` foreground · `bg` background · `stop` · `status` · `logs` · `open` · `update` (pull latest now; it also auto-checks every 30 min and restarts itself, with rollback if the self-test fails).

## Talking
Wake words: **"son of anton"**, **"anton"** (also tolerates "san antonio"). End with **"over"** (or just pause ~6s). Dashboard 🎤 uses your browser mic; phones open the *Phone mic* link (same Wi-Fi/hotspot). Untick "need wake word" on the dashboard for always-on chat. The activity log shows everything the mic hears (🎧) so you can see if recognition works. Press **Test connections** to see why a model/local brain isn't working.

## Brain
instant cache (learned + hard-coded) → local Ollama model → free cloud models (auto-failover; 👁 = vision-capable; `look_at_screen` lets it see your screen) → agent with 36+ PC tools and self-written skills.

Config overrides: `config.json` (e.g. `{"tts":{"voice":"en-US-GuyNeural"}}`, `{"local":{"model":"llama3.2:3b"}}`).
