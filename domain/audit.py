"""Journal d'audit chaîné : hash(n) = SHA-256(hash(n-1) || JSON_canonique(n)).

Modifier une ligne passée casse la chaîne. Le journal est append-only :
aucune API ne permet de l'éditer.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from typing import Any, Mapping

from config import horodatage
from .extraction import canonical


def hash_chaine(hash_precedent: str, evenement: Mapping[str, Any]) -> str:
    brut = hash_precedent + canonical(evenement)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def dernier_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
    return row["hash"] if row else "0" * 64


def append_event(
    conn: sqlite3.Connection,
    acteur: str,
    action: str,
    avant: Any = None,
    apres: Any = None,
) -> str:
    """Ajoute un événement. À appeler dans la transaction métier."""
    evenement = {
        "acteur": acteur,
        "action": action,
        "avant": avant,
        "apres": apres,
        "horodatage": horodatage(),
    }
    hash_precedent = dernier_hash(conn)
    h = hash_chaine(hash_precedent, evenement)
    conn.execute(
        "INSERT INTO audit_events(acteur, action, avant, apres, horodatage, hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            acteur,
            action,
            None if avant is None else canonical(avant),
            None if apres is None else canonical(apres),
            evenement["horodatage"],
            h,
        ),
    )
    return h


def verifier_chaine(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    """Recalcule toute la chaîne et renvoie la première cassure."""
    hash_precedent = "0" * 64
    erreurs: list[str] = []
    for row in conn.execute("SELECT * FROM audit_events ORDER BY sequence"):
        evenement = {
            "acteur": row["acteur"],
            "action": row["action"],
            "avant": json.loads(row["avant"]) if row["avant"] else None,
            "apres": json.loads(row["apres"]) if row["apres"] else None,
            "horodatage": row["horodatage"],
        }
        attendu = hash_chaine(hash_precedent, evenement)
        if attendu != row["hash"]:
            erreurs.append(f"sequence {row['sequence']}: hash attendu {attendu}, trouve {row['hash']}")
            break
        hash_precedent = row["hash"]
    return (not erreurs), erreurs


def exporter_csv(conn: sqlite3.Connection) -> str:
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie)
    ecrivain.writerow(["sequence", "acteur", "action", "avant", "apres", "horodatage", "hash"])
    for row in conn.execute("SELECT * FROM audit_events ORDER BY sequence"):
        ecrivain.writerow([row[k] for k in (
            "sequence", "acteur", "action", "avant", "apres", "horodatage", "hash"
        )])
    return sortie.getvalue()
