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
Then in the dashboard (gear icon, Setup tab): paste your free API keys (Kilo/Groq/NVIDIA/OpenRouter). Keys live in `.env` and are never overwritten by updates. The repo is public, so updates need no token.

## Commands
`python run.py` foreground · `bg` background · `stop` · `status` · `logs` · `open` · `update` (pull latest now; it also auto-checks every 30 min and restarts itself, with rollback if the self-test fails).

## Talking
Wake words: **"son of anton"**, **"anton"** (also tolerates "san antonio"). End with **"over"** (or just pause ~6s). Dashboard 🎤 uses your browser mic; phones open the *Phone mic* link (same Wi-Fi/hotspot). Untick "need wake word" on the dashboard for always-on chat. The activity log shows everything the mic hears (🎧) so you can see if recognition works. Press **Test connections** to see why a model/local brain isn't working.

## Screen
One orb in the middle that mirrors what Anton is doing (idle, listening, thinking, searching, browsing, speaking, learning). The **Chat** button (top right) slides the conversation in; the gear opens status, models, memory and setup. Orbs: thinking-orbs by Jakub Antalik (MIT), vendored in `web/orbs-engine.js`.

## Brain
instant cache (learned + hard-coded) → instant intents (volume, apps, timers, screenshots... no model call at all) → local Ollama model → free cloud models (auto-failover; 👁 = vision-capable; `look_at_screen` lets it see your screen) → agent with 36+ PC tools and self-written skills.

Config overrides: `config.json` (e.g. `{"tts":{"voice":"en-US-GuyNeural"}}`, `{"local":{"model":"llama3.2:3b"}}`).

## Speed
Cloud calls are streamed; a dead model is dropped after ~9 s of silence instead of a full timeout, the fastest healthy model is tried first, and at most 4 models are tried per request (no more uploading the same prompt to every free model). Agent steps send only the tools a task needs, and old tool output shrinks after use.

## Stealth browser
`browser_*` tools drive Camofox (anti-detection Firefox). First use sets it up in the background (Node 22+, ~300 MB, once). Gear → Status → **Set up browser** starts that early.
