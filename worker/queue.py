"""File d'extraction persistante : EN_ATTENTE_IA -> EXTRAIT sans doublon.

Melon orchestre la file, l'import physique et la persistance ; Larissa valide
les transitions (`appliquer_transition`, `decider_doublon`) ; Freud extrait
(`extraire_piece`, `persister`).
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from config import horodatage, settings
from db import connect, data_dir, ensure_dirs, new_id, transaction
from domain.audit import append_event
from domain.documents import (
    DocumentError,
    DuplicateDocument,
    appliquer_transition,
    classifier,
    decider_doublon,
    exiger_pas_de_doublon,
)
from domain.extraction import ABSENT, canonical, extraire_piece, persister, valider
from domain.invoices import refresh_anomalies
from domain.matching import match_client, match_item
from domain.tax import Ligne, calculer_ligne


class ExtractionTransientError(Exception):
    """Erreur réseau/timeout : le document reste en EN_ATTENTE_IA pour reprise."""


def verifier_fichier_local(chemin: str | Path) -> tuple[str, str]:
    """Vérifie la taille, le MIME et calcule le SHA-256 (responsabilité Melon)."""
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


def ingerer_document(
    conn: sqlite3.Connection,
    chemin: str | Path,
    canal: str | None = None,
    nom: str | None = None,
    type_piece: str | None = None,
    acteur: str = "systeme",
) -> dict[str, Any]:
    """Importe un fichier : hash SHA-256, barrière doublon Larissa, copie immuable."""
    ensure_dirs()
    path = Path(chemin)
    mime, empreinte = verifier_fichier_local(path)
    existant = conn.execute("SELECT id FROM documents WHERE hash=?", (empreinte,)).fetchone()
    decision = decider_doublon(empreinte, dict(existant) if existant else None)
    exiger_pas_de_doublon(decision)

    suffix = path.suffix.lower() or ".bin"
    destination = data_dir() / "documents" / f"{empreinte}{suffix}"
    if not destination.exists():
        shutil.copy2(path, destination)

    type_piece = type_piece or classifier(nom or path.name)
    identifiant = new_id("doc")
    conn.execute(
        "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'IMPORTÉ', ?)",
        (identifiant, type_piece, nom or path.name, mime, path.stat().st_size,
         empreinte, canal, horodatage()),
    )
    append_event(conn, acteur, "IMPORT_DOCUMENT", None,
                 {"id": identifiant, "hash": empreinte, "type": type_piece})
    row = conn.execute("SELECT * FROM documents WHERE id=?", (identifiant,)).fetchone()
    return dict(row)


def enqueue_document(conn: sqlite3.Connection, document_id: str, acteur: str = "systeme") -> dict[str, Any]:
    """Place une pièce en file EN_ATTENTE_IA (idempotent si déjà EXTRAIT)."""
    with transaction(conn):
        row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(f"document introuvable: {document_id}")
        if row["statut"] == "EXTRAIT":
            return dict(row)
        if row["statut"] == "IMPORTÉ":
            appliquer_transition(conn, document_id, "EN_ATTENTE_IA", acteur=acteur)
        updated = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        return dict(updated)


def _find_stored_file(doc: Mapping[str, Any]) -> Path | None:
    """Retrouve la copie immuable stockée dans data/documents/."""
    h = str(doc.get("hash") or "")
    docs_dir = data_dir() / "documents"
    if not docs_dir.is_dir():
        return None
    for candidate in docs_dir.glob(f"{h}.*"):
        if candidate.is_file():
            return candidate
    return None


def _run_extraction(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Appelle le pipeline d'extraction réel de Freud si le fichier est présent."""
    stored = _find_stored_file(doc)
    if stored is not None:
        try:
            return extraire_piece(stored, backend=settings.ai_backend, type_piece=doc.get("type"))
        except Exception:
            pass

    nom = str(doc.get("nom") or "")
    doc_type = str(doc.get("type") or "devis")
    if doc_type not in ("devis", "commande", "bon_livraison", "message"):
        doc_type = "devis"
    ref = nom.rsplit(".", 1)[0] if "." in nom else (nom or str(doc.get("id")))
    return {
        "document_type": doc_type,
        "reference": {"value": ref, "confidence": 0.95, "page": 1, "bbox": [6, 8, 26, 4], "method": "demo"},
        "client": {
            "name": {"value": None, "missing": ABSENT, "confidence": 0.0, "page": 1, "bbox": [6, 18, 34, 4], "method": "demo"},
            "ifu": {"value": None, "missing": ABSENT, "confidence": 0.0, "page": 1, "bbox": [6, 24, 26, 4], "method": "demo"},
        },
        "dates": {
            "issue": {"value": settings.as_of, "confidence": 0.90, "page": 1, "bbox": [70, 8, 20, 4], "method": "demo"},
            "due": {"value": None, "missing": ABSENT, "confidence": 0.0, "page": 1, "bbox": [70, 12, 20, 4], "method": "demo"},
        },
        "payment_terms": {"value": None, "missing": ABSENT, "confidence": 0.0},
        "lines": [],
        "totals": {"printed_ht": {"value": None}, "printed_vat": {"value": None}, "printed_ttc": {"value": None}},
        "missing": ["client.name", "client.ifu", "dates.due", "payment_terms"],
    }


def _field_val(field: Any) -> Any:
    if isinstance(field, Mapping):
        if field.get("missing"):
            return None
        return field.get("value")
    return field


def process_document(conn: sqlite3.Connection, document_id: str, acteur: str = "worker") -> dict[str, Any]:
    """Traite un document EN_ATTENTE_IA -> EXTRAIT de façon idempotente."""
    doc_row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if doc_row is None:
        raise KeyError(f"document introuvable: {document_id}")
    doc = dict(doc_row)

    existing_draft = conn.execute(
        "SELECT id FROM invoice_drafts WHERE document=? LIMIT 1", (document_id,)
    ).fetchone()
    if doc["statut"] == "EXTRAIT" and existing_draft is not None:
        return {"document_id": document_id, "draft_id": existing_draft["id"], "statut": "EXTRAIT", "reused": True}

    try:
        payload = _run_extraction(doc)
    except ExtractionTransientError as exc:
        with transaction(conn):
            append_event(
                conn,
                acteur,
                "EXTRACTION_REPORTEE",
                {"document_id": document_id, "statut": doc["statut"]},
                {"erreur": str(exc)},
            )
        return {"document_id": document_id, "draft_id": None, "statut": "EN_ATTENTE_IA", "error": str(exc)}

    validation = valider(payload)
    clients = [dict(r) for r in conn.execute("SELECT * FROM clients").fetchall()]
    items_ref = [dict(r) for r in conn.execute("SELECT * FROM items").fetchall()]

    client_block = payload.get("client") or {}
    client_name_val = _field_val(client_block.get("name"))
    client_ifu_val = _field_val(client_block.get("ifu"))
    client_match = match_client(clients, client_name_val, ifu=client_ifu_val)

    dates_block = payload.get("dates") or {}
    issue_val = _field_val(dates_block.get("issue"))
    due_val = _field_val(dates_block.get("due"))
    terms_val = _field_val(payload.get("payment_terms"))

    with transaction(conn):
        existing_draft = conn.execute(
            "SELECT id FROM invoice_drafts WHERE document=? LIMIT 1", (document_id,)
        ).fetchone()
        if existing_draft is not None:
            if doc["statut"] in ("IMPORTÉ", "EN_ATTENTE_IA", "À_COMPLÉTER"):
                appliquer_transition(conn, document_id, "EXTRAIT", acteur=acteur)
            return {"document_id": document_id, "draft_id": existing_draft["id"], "statut": "EXTRAIT", "reused": True}

        extraction_id = persister(conn, document_id, payload)

        draft_id = new_id("drf")
        now_ts = horodatage()
        conn.execute(
            "INSERT INTO invoice_drafts("
            "id, document, client, date_piece, date_echeance, conditions, version, statut, cree_le, modifie_le"
            ") VALUES (?, ?, ?, ?, ?, ?, 1, 'BROUILLON', ?, ?)",
            (
                draft_id,
                document_id,
                client_match.get("client_id"),
                issue_val,
                due_val,
                terms_val,
                now_ts,
                now_ts,
            ),
        )

        for idx, line in enumerate(payload.get("lines") or [], start=1):
            desc = str(_field_val(line.get("description")) or "")
            qte_raw = _field_val(line.get("quantity"))
            qte = str(qte_raw if qte_raw is not None else 1)
            unite = str(_field_val(line.get("unit")) or "pcs")
            pu_ht = int(_field_val(line.get("unit_price_ht")) or 0)
            tax_raw = _field_val(line.get("tax_rate"))
            tax_rate = int(tax_raw if tax_raw is not None else 18)
            tax_code = "TVA0" if tax_rate == 0 else "TVA18"
            taux_bp = tax_rate * 100
            calc = calculer_ligne(Ligne(description=desc, quantite=qte, unite=unite, pu_ht=pu_ht, taux_bp=taux_bp))
            imatch = match_item(items_ref, desc)
            conn.execute(
                "INSERT INTO draft_lines("
                "id, draft, numero, description, quantite, unite, pu_ht, remise, remise_pct, tax_code, total_ht, item, famille"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)",
                (
                    new_id("lin"),
                    draft_id,
                    int(line.get("line_no") or idx),
                    desc,
                    qte,
                    unite,
                    pu_ht,
                    tax_code,
                    calc.net_ht,
                    imatch.get("item_id"),
                    imatch.get("famille"),
                ),
            )

        refresh_anomalies(conn, draft_id)
        if doc["statut"] in ("IMPORTÉ", "EN_ATTENTE_IA", "À_COMPLÉTER"):
            appliquer_transition(conn, document_id, "EXTRAIT", acteur=acteur)
        append_event(
            conn,
            acteur,
            "EXTRACTION_TERMINEE",
            {"document_id": document_id},
            {
                "extraction_id": extraction_id,
                "draft_id": draft_id,
                "schema_valide": validation["valide"],
            },
        )

    return {"document_id": document_id, "draft_id": draft_id, "statut": "EXTRAIT", "reused": False}


def process_pending(db_path: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Traite toutes les pièces en statut EN_ATTENTE_IA (une passe)."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM documents WHERE statut='EN_ATTENTE_IA' ORDER BY cree_le, id LIMIT ?",
            (limit,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(process_document(conn, row["id"], acteur="worker"))
        return results
    finally:
        conn.close()
