import asyncio, os, sys, webbrowser
from . import config, tools, tray
from .bus import Bus
from .store import Store
from .llm import Cloud, Local
from .brain import Brain
from .idle import SelfImprover
from .wake import Wake
from .server import Server
from .voice import PcMic, Speaker

EXIT = {"code": 0}


async def amain(open_browser=True, use_tray=False):
    cfg = config.load()
    loop = asyncio.get_running_loop()
    bus = Bus()
    bus.loop = loop
    store = Store(config.DATA / "soa.db")
    cloud, local = Cloud(cfg), Local(cfg)
    brain = Brain(cfg, store, cloud, local, bus)
    tools.CTX.update(store=store, cfg=cfg, notify=lambda m: bus.emit("reply", to="all", text=m, route="notify", ms=0),
                     vision=lambda q, b: asyncio.run_coroutine_threadsafe(cloud.vision(q, b), loop).result(90),
                     run_task=lambda t: asyncio.run_coroutine_threadsafe(brain.handle(t, "dashboard"), loop))
    skills = tools.load_skills()
    improver = SelfImprover(cfg, store, cloud, brain, bus)
    srv = Server(cfg, store, cloud, local, brain, improver, Wake(cfg), bus)
    main_task = asyncio.current_task()

    def restart():
        EXIT["code"] = 75
        main_task.cancel()
    srv.restart = restart
    runner = await srv.start()

    url = f"http://localhost:{cfg['port']}/?token={srv.token}"
    print(f"\n  {cfg['name']} v{config.version()} online. {len(tools.TOOLS)} tools, skills: {skills}")
    print(f"  Dashboard : {url}\n  Phone mic : {srv.state()['phone_url']}\n")
    if use_tray:
        tray.start(url, lambda: asyncio.run_coroutine_threadsafe(srv.do_update(True), loop), lambda: os._exit(0))

    if cfg["tts_local"]:
        sp = Speaker()
        emit = bus.emit
        bus.emit = lambda t, **k: (sp.say(k["text"]) if t == "reply" and k.get("to") in ("dashboard", "pc", "all") else None, emit(t, **k))[1]
    if cfg["pc_mic"] or (config.DATA / "vosk").exists():
        srv.pc_mic = True
        PcMic(lambda t: loop.call_soon_threadsafe(srv.on_speech, "pc", t), print).start()

    async def boot():
        await cloud.refresh()
        print("  Cloud models:", [f'{e["provider"]}:{e["model"]}' for e in cloud.entries] or "NONE - add keys in the dashboard (Keys panel)")
        for line in await cloud.test():
            print("   ", line)
        if await local.check():
            await local.warm()
        print("  Local brain :", local.status, local.model)
        await srv.pregen()
        if cfg["update"]["auto"]:
            while True:
                r = await srv.do_update(True)
                await asyncio.sleep(cfg["update"]["check_minutes"] * 60)
    tasks = [asyncio.create_task(boot()), asyncio.create_task(improver.loop()), asyncio.create_task(local.keepalive())]

    async def periodic():
        while True:
            await asyncio.sleep(900)
            await cloud.refresh()
    tasks.append(asyncio.create_task(periodic()))
    if open_browser:
        webbrowser.open(url)
    try:
        await asyncio.Event().wait()
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(lambda l, c: None if isinstance(c.get("exception"), (ConnectionResetError, asyncio.CancelledError, OSError)) else l.default_exception_handler(c))
    task = loop.create_task(amain("--no-browser" not in sys.argv, "--tray" in sys.argv))
    try:
        loop.run_until_complete(task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        try:
            if not task.done():
                task.cancel()
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except BaseException:
            pass
    if EXIT["code"] == 0:
        print("\n  Son of Anton stopped.")
    os._exit(EXIT["code"])
