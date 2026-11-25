"""Ingestion : trois formats, un seul pipeline, fichier source immuable."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from config import horodatage, settings
from db import data_dir, ensure_dirs, new_id
from .audit import append_event


class DocumentError(Exception):
    pass


class DuplicateDocument(DocumentError):
    def __init__(self, existing_id: str):
        super().__init__(f"doublon exact de la pièce {existing_id}")
        self.existing_id = existing_id


def sha256_file(chemin: str | Path) -> str:
    h = hashlib.sha256()
    with Path(chemin).open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def classifier(nom: str, texte: str = "") -> str:
    """Classe la pièce par mots-clés ; l'IA pourra affiner ensuite."""
    brut = f"{nom} {texte}".lower()
    if "devis" in brut:
        return "devis"
    if "livraison" in brut or " bon de livraison" in brut or "bl-" in brut:
        return "bon_livraison"
    if "message" in brut or "whatsapp" in brut:
        return "message"
    return "commande"


def verifier_fichier(chemin: str | Path) -> tuple[str, str]:
    path = Path(chemin)
    if not path.is_file():
        raise DocumentError("fichier introuvable")
    taille = path.stat().st_size
    if taille > settings.max_file_bytes:
        raise DocumentError(
            f"fichier trop volumineux: {taille} octets (limite {settings.max_file_bytes})"
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if mime not in settings.allowed_mimes:
        raise DocumentError(f"type non autorisé: {mime}")
    return mime, hashlib.sha256(path.read_bytes()).hexdigest()


def ingerer(
    conn: sqlite3.Connection,
    chemin: str | Path,
    canal: str | None = None,
    nom: str | None = None,
    type_piece: str | None = None,
) -> Mapping[str, Any]:
    """Stocke une copie immuable, hashée, et refuse les doublons exacts."""
    ensure_dirs()
    path = Path(chemin)
    mime, empreinte = verifier_fichier(path)
    existe = conn.execute("SELECT id FROM documents WHERE hash=?", (empreinte,)).fetchone()
    if existe:
        raise DuplicateDocument(existe["id"])

    suffix = path.suffix.lower() or ".bin"
    destination = data_dir() / "documents" / f"{empreinte}{suffix}"
    if not destination.exists():
        shutil.copy2(path, destination)

    type_piece = type_piece or classifier(path.name)
    identifiant = new_id("doc")
    statut = "IMPORTÉ"
    conn.execute(
        "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (identifiant, type_piece, nom or path.name, mime, path.stat().st_size,
         empreinte, canal, statut, horodatage()),
    )
    append_event(conn, "systeme", "IMPORT_DOCUMENT", None,
                 {"id": identifiant, "hash": empreinte, "type": type_piece})
    row = conn.execute("SELECT * FROM documents WHERE id=?", (identifiant,)).fetchone()
    return dict(row)


def changer_statut(conn: sqlite3.Connection, document_id: str, statut: str, acteur: str = "systeme") -> None:
    avant = conn.execute("SELECT statut FROM documents WHERE id=?", (document_id,)).fetchone()
    conn.execute("UPDATE documents SET statut=? WHERE id=?", (statut, document_id))
    append_event(conn, acteur, "CHANGEMENT_STATUT_DOCUMENT",
                 {"statut": avant["statut"] if avant else None}, {"statut": statut})
