"""Command line entry point.

    python -m aworld serve            run the world and the web viewer
    python -m aworld bench --years 10 measure how fast a world runs here
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from .config import load_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aworld", description="Artificial World")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the world and the web viewer")
    s.add_argument("--data", default="data", help="folder where worlds are saved")
    s.add_argument("--config", default=None, help="settings file used for NEW worlds")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--autoplay", action="store_true", help="start running immediately")

    b = sub.add_parser("bench", help="measure simulation speed on this machine")
    b.add_argument("--years", type=int, default=10)
    b.add_argument("--config", default=None)

    args = p.parse_args(argv)
    if args.cmd == "serve":
        return cmd_serve(args)
    return cmd_bench(args)


def cmd_serve(args) -> int:
    from .runner import Runner
    from .server import serve

    runner = Runner(args.data, args.config)
    runner.open_latest_or_create()
    runner.running = bool(args.autoplay)
    runner.start_thread()

    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)     # `docker stop` → save cleanly
    try:
        serve(runner, args.host, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        print("[aworld] saving and shutting down…")
        runner.shutdown()
    return 0


def cmd_bench(args) -> int:
    from .world import World

    t0 = time.perf_counter()
    world = World.create(load_config(args.config))
    t1 = time.perf_counter()
    world.run(world.dpy * args.years)
    t2 = time.perf_counter()
    per_year = (t2 - t1) / args.years
    print(f"world generation: {t1 - t0:.2f} s")
    print(f"simulation:       {per_year:.2f} s per simulated year")
    print(f"                  ≈ {3600 / per_year:,.0f} years per hour, {86400 / per_year:,.0f} years per day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
