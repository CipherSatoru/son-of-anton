NAME = "system_report"
DESCRIPTION = "One-line spoken-friendly report of CPU, RAM and battery"
ARGS = {}


def run(**kwargs):
    import psutil
    b = psutil.sensors_battery()
    return (f"CPU {psutil.cpu_percent(interval=0.5):.0f}%, RAM {psutil.virtual_memory().percent:.0f}%"
            + (f", battery {b.percent:.0f}%" if b else ""))
