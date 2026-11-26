"""Boucle du worker d'extraction persistante.

Usage :
  python -m worker.run --once
  python -m worker.run --loop --interval 2
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from db import initialize
from worker.queue import process_pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker persistant WEMA (EN_ATTENTE_IA -> EXTRAIT)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Traite la file une fois puis quitte")
    mode.add_argument("--loop", action="store_true", help="Boucle continue sur la file")
    parser.add_argument("--interval", type=float, default=2.0, help="Pause entre deux cycles (secondes)")
    parser.add_argument("--db", type=str, default=None, help="Chemin explicite de la base SQLite")
    args = parser.parse_args(argv)

    initialize(args.db)

    if args.once or not args.loop:
        results = process_pending(db_path=args.db)
        print(f"[worker] {len(results)} piece(s) traitee(s).")
        return 0

    running = True

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"[worker] demarre en boucle (intervalle={args.interval}s)")
    while running:
        try:
            results = process_pending(db_path=args.db)
            if results:
                print(f"[worker] {len(results)} piece(s) traitee(s).")
        except Exception as exc:
            print(f"[worker] erreur transitoire: {exc}", file=sys.stderr)
        time.sleep(max(0.2, args.interval))
    print("[worker] arret propre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
