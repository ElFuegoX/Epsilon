"""Commandes CLI d'exploitation WÉMA : verify, clean, serve.

Usage :
  python -m cli verify   # Vérifie chaîne d'audit SHA-256, continuité numéros et hash PDF
  python -m cli clean    # Supprime la base locale et les fichiers générés
  python -m cli serve    # Démarre worker + API dans un même conteneur (Hugging Face Spaces)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from config import settings
from db import connect, data_dir, ensure_dirs, initialize
from domain.audit import verifier_chaine
from domain.invoices import verifier_pdf
from domain.numbering import verifier_continuite
from worker.queue import process_pending


def cmd_verify(db_path: str | None = None) -> int:
    initialize(db_path)
    conn = connect(db_path)
    ok_all = True
    try:
        audit_ok, audit_err = verifier_chaine(conn)
        if audit_ok:
            count = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
            print(f"[OK] Chaîne d'audit SHA-256 intacte ({count} événement(s)).")
        else:
            ok_all = False
            print(f"[ECHEC] Chaîne d'audit altérée : {'; '.join(audit_err)}", file=sys.stderr)

        num_ok, num_err = verifier_continuite(conn)
        if num_ok:
            print("[OK] Continuité de la numérotation vérifiée.")
        else:
            ok_all = False
            print(f"[ECHEC] Continuité des numéros : {'; '.join(num_err)}", file=sys.stderr)

        invoices = conn.execute("SELECT id, numero FROM invoices ORDER BY numero").fetchall()
        for inv in invoices:
            if verifier_pdf(conn, inv["id"]):
                print(f"[OK] PDF {inv['numero']} : hash SHA-256 conforme au snapshot.")
            else:
                ok_all = False
                print(f"[ECHEC] PDF {inv['numero']} : hash non conforme au snapshot.", file=sys.stderr)
    finally:
        conn.close()
    return 0 if ok_all else 1


def cmd_clean(db_path: str | None = None) -> int:
    path = db_path or settings.db_path
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(path + suffix)
        if candidate.exists():
            candidate.unlink()
    for sub in ("documents", "pages", "pdf", "eval", "outbox"):
        target = data_dir() / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    print("[OK] Base locale et fichiers générés nettoyés.")
    return 0


def cmd_serve() -> int:
    """Lance le worker en arrière-plan et l'API FastAPI (mode Hugging Face Spaces)."""
    import uvicorn

    ensure_dirs()
    initialize()

    interval = float(os.getenv("WORKER_INTERVAL_S", "2.0"))

    def _worker_loop() -> None:
        while True:
            try:
                process_pending()
            except Exception as exc:
                print(f"[worker] erreur transitoire : {exc}", file=sys.stderr)
            time.sleep(max(0.5, interval))

    t = threading.Thread(target=_worker_loop, name="wema-worker", daemon=True)
    t.start()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("api.app:app", host=host, port=port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLI d'exploitation WÉMA")
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="Vérifie chaîne d'audit, numérotation et hash PDF")
    p_verify.add_argument("--db", type=str, default=None)

    p_clean = sub.add_parser("clean", help="Nettoie la base et les fichiers générés")
    p_clean.add_argument("--db", type=str, default=None)

    sub.add_parser("serve", help="Démarre worker + API + interface (Hugging Face Spaces)")

    args = parser.parse_args(argv)
    if args.command == "verify":
        return cmd_verify(args.db)
    if args.command == "clean":
        return cmd_clean(args.db)
    if args.command == "serve":
        return cmd_serve()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
