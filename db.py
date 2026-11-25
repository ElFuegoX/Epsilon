"""Connexion SQLite, schéma et transactions.

Toute opération qui attribue un numéro ou fige un brouillon utilise
BEGIN IMMEDIATE : un seul validateur à la fois, aucun numéro consommé
en cas d'échec.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import settings, horodatage
from schema import SCHEMA_SQL


def new_id(prefix: str) -> str:
    """Identifiant technique interne (UUID court), jamais un numéro fiscal."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction exclusive : verrou la séquence dès le début."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def initialize(db_path: str | None = None) -> None:
    """Crée le schéma et les référentiels minimaux, de façon idempotente."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            "INSERT OR IGNORE INTO tax_codes(code, libelle, taux_bp, exoneration, compte) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("TVA18", "TVA normale 18 %", 1800, 0, "445200"),
                ("TVA0", "TVA exonérée", 0, 1, "445000"),
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO payment_terms(code, libelle, delai_jours, echeancier) "
            "VALUES (?, ?, ?, ?)",
            [
                ("COMPTANT", "Paiement à la commande", 0, "unique"),
                ("30J", "30 jours", 30, "unique"),
                ("30JFM", "30 jours fin de mois", 30, "fin_de_mois"),
            ],
        )
        conn.execute(
            "INSERT OR IGNORE INTO number_sequences(serie, annee, prefixe, prochaine, version) "
            "VALUES (?, ?, ?, ?, 0)",
            (settings.serie_defaut, settings.annee, settings.prefixe_facture, 1),
        )
        conn.execute(
            "INSERT OR IGNORE INTO number_sequences(serie, annee, prefixe, prochaine, version) "
            "VALUES (?, ?, ?, ?, 0)",
            (settings.serie_defaut, settings.annee, settings.prefixe_avoir, 1),
        )
    finally:
        conn.close()


def reset(db_path: str | None = None) -> None:
    """Repart d'une base vierge ; les pièces générées sont remplacées."""
    path = db_path or settings.db_path
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(path + suffix)
        if candidate.exists():
            candidate.unlink()
    initialize(path)


def data_dir() -> Path:
    path = Path(settings.data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "documents").mkdir(exist_ok=True)
    (data_dir() / "pages").mkdir(exist_ok=True)
    (data_dir() / "pdf").mkdir(exist_ok=True)
    (data_dir() / "eval").mkdir(exist_ok=True)
