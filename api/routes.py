"""Routes REST documentées dans docs/API.md.

Melon gère le transport, les statuts HTTP, l'idempotence et la persistance.
Aucun montant n'est calculé ici : tous les calculs, contrôles et numérotations
sont délégués aux modules déterministes de `domain/`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from adapters.email_sim import send_invoice_email
from adapters.mecef_stub import generate_mecef_stub
from adapters.whatsapp_sim import build_clarification_message, send_invoice_whatsapp
from api.auth import require_roles
from api.schemas import (
    AnomalyResolveIn,
    ClientCreateIn,
    CreditNoteCreateIn,
    DocumentTextIn,
    DraftPatchIn,
    IssueInvoiceIn,
    ItemCreateIn,
    LineCreateIn,
    LinePatchIn,
)
from config import VERSION, horodatage, settings
from db import connect, data_dir, ensure_dirs, new_id, reset as db_reset, transaction
from domain.audit import append_event, exporter_csv, verifier_chaine
from domain.controls import build_context
from domain.documents import DocumentError, DuplicateDocument
from domain.extraction import aplatir
from domain.invoices import (
    AnomaliesBloquantes,
    AvoirRefuse,
    EtatInvalide,
    ValidationError,
    create_credit_note,
    issue_invoice,
    preview_number,
    refresh_anomalies,
    registre,
    validate_draft,
)
from domain.tax import Ligne, calculer, calculer_ligne, lignes_depuis_dict
from worker.queue import enqueue_document, ingerer_document, process_document

router = APIRouter()


def _conn():
    return connect()


def _normalize_channel(raw: str | None) -> str:
    val = (raw or "email_sim").strip().lower()
    mapping = {
        "email": "email_sim",
        "email_sim": "email_sim",
        "whatsapp": "whatsapp_sim",
        "whatsapp_sim": "whatsapp_sim",
        "telechargement": "telechargement",
        "download": "telechargement",
    }
    if val not in mapping:
        raise HTTPException(status_code=422, detail=f"Canal inconnu : {raw}")
    return mapping[val]


def _serialize_document(conn, row) -> dict[str, Any]:
    doc = dict(row)
    ext = conn.execute(
        "SELECT * FROM extractions WHERE document=? ORDER BY rowid DESC LIMIT 1",
        (doc["id"],),
    ).fetchone()
    fields: dict[str, Any] = {}
    if ext and ext["brut_json"]:
        try:
            fields = aplatir(json.loads(ext["brut_json"]))
        except Exception:
            fields = {}
    if not fields and ext:
        for f in conn.execute("SELECT * FROM extracted_fields WHERE extraction=?", (ext["id"],)):
            bbox = json.loads(f["bbox"]) if f["bbox"] else None
            fields[f["chemin"]] = {
                "value": f["valeur"],
                "normalized": f["valeur_normalisee"],
                "confidence": f["confiance"],
                "page": f["page"],
                "bbox": bbox,
                "method": f["methode"],
                "motif": f["missing"],
            }
    doc["filename"] = doc["nom"]
    doc["status"] = doc["statut"]
    doc["created_at"] = doc["cree_le"]
    doc["fields"] = fields
    return doc


def _serialize_draft(conn, row) -> dict[str, Any]:
    d = dict(row)
    client_row = conn.execute("SELECT * FROM clients WHERE id=?", (d.get("client"),)).fetchone()
    client = dict(client_row) if client_row else None

    lignes = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM draft_lines WHERE draft=? ORDER BY numero", (d["id"],)
        ).fetchall()
    ]
    for l in lignes:
        code = conn.execute("SELECT taux_bp FROM tax_codes WHERE code=?", (l["tax_code"],)).fetchone()
        l["taux_bp"] = int(code["taux_bp"]) if code else 0

    imprime: dict[str, Any] = {}
    if d.get("document"):
        tot = conn.execute(
            "SELECT printed_ht, printed_vat, printed_ttc FROM document_totals WHERE document=?",
            (d["document"],),
        ).fetchone()
        if tot:
            imprime = {"ht": tot["printed_ht"], "vat": tot["printed_vat"], "ttc": tot["printed_ttc"]}

    calc = calculer(
        lignes_depuis_dict(lignes),
        imprime=imprime or None,
        tolerance=settings.tolerance_arithmetique,
    )
    deliveries = {
        int(r["numero"]): r["quantite_livree"]
        for r in conn.execute("SELECT numero, quantite_livree FROM deliveries WHERE draft=?", (d["id"],))
    }

    d["document_id"] = d.get("document")
    d["date"] = d.get("date_piece")
    d["status"] = d.get("statut")
    d["numero_previsionnel"] = preview_number(conn)
    d["client_detail"] = client
    d["lines"] = [
        {
            **l,
            "line_no": l["numero"],
            "quantity": l["quantite"],
            "delivered": deliveries.get(int(l["numero"]), l["quantite"]),
            "unit_price_ht": l["pu_ht"],
            "tax_rate": round(int(l["taux_bp"]) / 100),
            "line_total_ht": l["total_ht"],
        }
        for l in lignes
    ]
    d["printed_totals"] = imprime or {"ht": None, "vat": None, "ttc": None}
    d["recalculated_totals"] = {
        "ht": calc.total_ht,
        "vat": calc.total_tva,
        "ttc": calc.total_ttc,
    }
    d["ecart"] = dict(calc.ecarts)
    return d


def _serialize_invoice(conn, row) -> dict[str, Any]:
    inv = dict(row)
    inv["status"] = inv["statut"]
    inv["channel"] = inv.get("canal")
    inv["totals"] = {
        "ht": inv["total_ht"],
        "vat": inv["total_tva"],
        "ttc": inv["total_ttc"],
    }
    inv["lines"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM invoice_lines WHERE facture=? ORDER BY numero", (inv["id"],)
        ).fetchall()
    ]
    inv["credit_notes"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM credit_notes WHERE facture=? ORDER BY numero", (inv["id"],)
        ).fetchall()
    ]
    inv["payments"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM payments WHERE facture=? ORDER BY date", (inv["id"],)
        ).fetchall()
    ]
    inv["mecef_stub"] = generate_mecef_stub(inv["numero"], int(inv["total_ttc"]))
    return inv


# ---------------------------------------------------------------------------
# Santé
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": VERSION,
        "ai_backend": settings.ai_backend,
        "as_of": settings.as_of,
        "simulation": True,
    }


# ---------------------------------------------------------------------------
# Documents & Ingestion (E1)
# ---------------------------------------------------------------------------

@router.get("/documents")
def list_documents(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM documents ORDER BY cree_le DESC, id DESC").fetchall()
        return {"items": [_serialize_document(conn, r) for r in rows]}
    finally:
        conn.close()


@router.post("/documents")
async def create_document(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
    canal: Optional[str] = Form(default=None),
    type_piece: Optional[str] = Form(default=None),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        if idempotency_key:
            cached = conn.execute(
                "SELECT resultat FROM idempotency_keys WHERE cle=?", (f"doc:{idempotency_key}",)
            ).fetchone()
            if cached:
                return json.loads(cached["resultat"])

        tmp_path: Optional[Path] = None
        nom: Optional[str] = None
        chosen_canal = canal
        chosen_type = type_piece

        if file is not None:
            raw = await file.read()
            suffix = Path(file.filename or "upload.bin").suffix or ".bin"
            nom = file.filename or f"piece{suffix}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                tmp_path = Path(tmp.name)
        else:
            try:
                body_json = await request.json()
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Envoyez soit un fichier multipart ('file'), soit un JSON {nom, texte}.",
                ) from exc
            parsed = DocumentTextIn.model_validate(body_json)
            nom = parsed.nom if parsed.nom.endswith(".txt") else f"{parsed.nom}.txt"
            chosen_canal = parsed.canal or chosen_canal
            chosen_type = parsed.type or chosen_type or "message"
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
                tmp.write(parsed.texte)
                tmp_path = Path(tmp.name)

        try:
            with transaction(conn):
                doc = dict(ingerer_document(conn, tmp_path, canal=chosen_canal, nom=nom, type_piece=chosen_type, acteur=role))
                if idempotency_key:
                    conn.execute(
                        "INSERT INTO idempotency_keys(cle, action, resultat, date) VALUES (?, ?, ?, ?)",
                        (
                            f"doc:{idempotency_key}",
                            "import_document",
                            json.dumps(doc, sort_keys=True, ensure_ascii=False),
                            horodatage(),
                        ),
                    )
        except DuplicateDocument as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Pièce déjà importée (doublon exact de {exc.existing_id}).",
            ) from exc
        except DocumentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        # Place immédiatement en file persistante EN_ATTENTE_IA
        enqueue_document(conn, doc["id"], acteur=role)
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc["id"],)).fetchone()
        return _serialize_document(conn, row)
    finally:
        conn.close()


@router.get("/documents/{doc_id}")
def get_document(
    doc_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante", "lecture")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Pièce introuvable : {doc_id}")
        return _serialize_document(conn, row)
    finally:
        conn.close()


@router.post("/documents/{doc_id}/extract")
def extract_document_endpoint(
    doc_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Pièce introuvable : {doc_id}")
        enqueue_document(conn, doc_id, acteur=role)
        result = process_document(conn, doc_id, acteur=role)
        updated = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        out = _serialize_document(conn, updated)
        out["draft_id"] = result.get("draft_id")
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Brouillons, lignes, anomalies & clarification (E4, E5)
# ---------------------------------------------------------------------------

@router.get("/drafts")
def list_drafts(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM invoice_drafts ORDER BY cree_le DESC, id DESC").fetchall()
        return {"items": [_serialize_draft(conn, r) for r in rows]}
    finally:
        conn.close()


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante", "lecture")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Brouillon introuvable : {draft_id}")
        return _serialize_draft(conn, row)
    finally:
        conn.close()


@router.patch("/drafts/{draft_id}")
def patch_draft(
    draft_id: str,
    payload: DraftPatchIn,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        with transaction(conn):
            row = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Brouillon introuvable : {draft_id}")
            if row["statut"] == "VALIDÉ":
                raise HTTPException(status_code=409, detail="Brouillon déjà validé et figé.")

            updates = payload.model_dump(exclude_none=True)
            if updates:
                avant = {k: row[k] for k in updates}
                sets = ", ".join(f"{k}=?" for k in updates)
                vals = list(updates.values()) + [horodatage(), draft_id]
                conn.execute(
                    f"UPDATE invoice_drafts SET {sets}, version=version+1, modifie_le=? WHERE id=?",
                    vals,
                )
                append_event(conn, role, "MODIFICATION_BROUILLON", avant, updates)
            refresh_anomalies(conn, draft_id)
        updated = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
        return _serialize_draft(conn, updated)
    finally:
        conn.close()


@router.post("/drafts/{draft_id}/lines")
def add_draft_line(
    draft_id: str,
    payload: LineCreateIn,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        with transaction(conn):
            draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
            if draft is None:
                raise HTTPException(status_code=404, detail=f"Brouillon introuvable : {draft_id}")
            if draft["statut"] == "VALIDÉ":
                raise HTTPException(status_code=409, detail="Brouillon déjà validé : ajout de ligne interdit.")

            max_num = conn.execute(
                "SELECT COALESCE(MAX(numero), 0) AS m FROM draft_lines WHERE draft=?", (draft_id,)
            ).fetchone()["m"]
            numero = int(max_num) + 1
            code_row = conn.execute("SELECT taux_bp FROM tax_codes WHERE code=?", (payload.tax_code,)).fetchone()
            taux_bp = int(code_row["taux_bp"]) if code_row else 0
            calc = calculer_ligne(
                Ligne(
                    description=payload.description,
                    quantite=payload.quantite,
                    unite=payload.unite,
                    pu_ht=payload.pu_ht,
                    remise=payload.remise,
                    remise_pct=payload.remise_pct,
                    taux_bp=taux_bp,
                )
            )
            line_id = new_id("lin")
            conn.execute(
                "INSERT INTO draft_lines("
                "id, draft, numero, description, quantite, unite, pu_ht, remise, remise_pct, tax_code, total_ht, item, famille"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    line_id,
                    draft_id,
                    numero,
                    payload.description,
                    str(payload.quantite),
                    payload.unite,
                    payload.pu_ht,
                    payload.remise,
                    payload.remise_pct,
                    payload.tax_code,
                    calc.net_ht,
                    payload.item,
                    payload.famille,
                ),
            )
            append_event(conn, role, "AJOUT_LIGNE", None, {"draft_id": draft_id, "line_id": line_id, "numero": numero})
            refresh_anomalies(conn, draft_id)
        row = conn.execute("SELECT * FROM draft_lines WHERE id=?", (line_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.patch("/lines/{line_id}")
def patch_draft_line(
    line_id: str,
    payload: LinePatchIn,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        with transaction(conn):
            row = conn.execute("SELECT * FROM draft_lines WHERE id=?", (line_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Ligne introuvable : {line_id}")
            draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (row["draft"],)).fetchone()
            if draft and draft["statut"] == "VALIDÉ":
                raise HTTPException(status_code=409, detail="Brouillon déjà validé : modification de ligne interdite.")

            merged = dict(row)
            updates = payload.model_dump(exclude_none=True)
            if "quantite" in updates:
                updates["quantite"] = str(updates["quantite"])
            merged.update(updates)

            code_row = conn.execute("SELECT taux_bp FROM tax_codes WHERE code=?", (merged["tax_code"],)).fetchone()
            taux_bp = int(code_row["taux_bp"]) if code_row else 0
            calc = calculer_ligne(
                Ligne(
                    description=merged["description"],
                    quantite=merged["quantite"],
                    unite=merged["unite"],
                    pu_ht=int(merged["pu_ht"]),
                    remise=int(merged["remise"]),
                    remise_pct=int(merged["remise_pct"]),
                    taux_bp=taux_bp,
                )
            )
            updates["total_ht"] = calc.net_ht
            sets = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [line_id]
            conn.execute(f"UPDATE draft_lines SET {sets} WHERE id=?", vals)
            append_event(
                conn,
                role,
                "MODIFICATION_LIGNE",
                {k: row[k] for k in updates if k in row.keys()},
                updates,
            )
            refresh_anomalies(conn, row["draft"])
        updated = conn.execute("SELECT * FROM draft_lines WHERE id=?", (line_id,)).fetchone()
        return dict(updated)
    finally:
        conn.close()


@router.get("/drafts/{draft_id}/anomalies")
def list_anomalies(
    draft_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante", "lecture")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        draft = conn.execute("SELECT id FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Brouillon introuvable : {draft_id}")
        with transaction(conn):
            refresh_anomalies(conn, draft_id)
        rows = conn.execute("SELECT * FROM anomalies WHERE draft=? ORDER BY rowid", (draft_id,)).fetchall()
        items = [
            {
                **dict(r),
                "draft_id": r["draft"],
                "severity": r["severite"],
                "field": r["champ"],
                "status": r["statut"],
            }
            for r in rows
        ]
        return {"items": items}
    finally:
        conn.close()


@router.post("/anomalies/{anomaly_id}/resolve")
def resolve_anomaly(
    anomaly_id: str,
    payload: Optional[AnomalyResolveIn] = None,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        with transaction(conn):
            row = conn.execute("SELECT * FROM anomalies WHERE id=?", (anomaly_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Anomalie introuvable : {anomaly_id}")
            res_text = (payload.justification or payload.resolution) if payload else "Résolu manuellement"
            trace_json = json.dumps(
                {"acteur": role, "motif": res_text, "avant": row["statut"], "apres": "RESOLUE"},
                sort_keys=True,
                ensure_ascii=False,
            )
            conn.execute(
                "UPDATE anomalies SET statut='RESOLUE', resolution=?, avant=?, apres='RESOLUE' WHERE id=?",
                (trace_json, row["statut"], anomaly_id),
            )
            append_event(
                conn,
                role,
                "RESOLUTION_ANOMALIE",
                {"id": anomaly_id, "code": row["code"], "statut": row["statut"]},
                {"statut": "RESOLUE", "resolution": res_text},
            )
        updated = conn.execute("SELECT * FROM anomalies WHERE id=?", (anomaly_id,)).fetchone()
        return {
            **dict(updated),
            "draft_id": updated["draft"],
            "severity": updated["severite"],
            "field": updated["champ"],
            "status": updated["statut"],
        }
    finally:
        conn.close()


@router.post("/drafts/{draft_id}/clarification-message")
def clarification_message(
    draft_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        ctx = build_context(conn, draft_id)
        manquants: list[str] = []
        if not ctx.draft.get("client"):
            manquants.append("identification du client")
        elif not (ctx.client or {}).get("ifu"):
            manquants.append("numéro IFU du client")
        if not ctx.draft.get("date_piece"):
            manquants.append("date de la pièce")
        if not ctx.draft.get("conditions"):
            manquants.append("conditions de paiement")
        if not ctx.lignes:
            manquants.append("détail des lignes")

        ref = (ctx.document or {}).get("nom") or draft_id
        client_nom = (ctx.client or {}).get("raison_sociale")
        msg = build_clarification_message(ref, manquants, client_nom=client_nom)
        with transaction(conn):
            append_event(
                conn,
                role,
                "MESSAGE_CLARIFICATION_GENERE",
                None,
                {"draft_id": draft_id, "manquants": manquants},
            )
        return {"draft_id": draft_id, "missing": manquants, "message": msg}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Validation, factures, émission & avoirs (E6, E7)
# ---------------------------------------------------------------------------

@router.post("/drafts/{draft_id}/validate")
def validate_draft_endpoint(
    draft_id: str,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    role: str = Depends(require_roles("dirigeant")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        res = validate_draft(conn, draft_id, acteur=role, idempotency_key=idempotency_key)
        inv = conn.execute("SELECT * FROM invoices WHERE id=?", (res["invoice_id"],)).fetchone()
        out = _serialize_invoice(conn, inv) if inv else res
        out["invoice_id"] = res["invoice_id"]
        return out
    except AnomaliesBloquantes as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validation bloquée : des anomalies bloquantes restent ouvertes.",
                "anomalies": [a.to_dict() for a in exc.anomalies],
            },
        ) from exc
    except EtatInvalide as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/invoices")
def list_invoices(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM invoices ORDER BY numero DESC").fetchall()
        return {"items": [_serialize_invoice(conn, r) for r in rows]}
    finally:
        conn.close()


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante", "lecture")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Facture introuvable : {invoice_id}")
        return _serialize_invoice(conn, row)
    finally:
        conn.close()


@router.get("/invoices/{invoice_id}/pdf")
def get_invoice_pdf(
    invoice_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante", "lecture")),
):
    conn = _conn()
    try:
        row = conn.execute("SELECT numero FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Facture introuvable : {invoice_id}")
        pdf_path = data_dir() / "pdf" / f"{row['numero']}.pdf"
        if not pdf_path.is_file():
            raise HTTPException(status_code=404, detail="Fichier PDF introuvable sur le disque.")
        return FileResponse(path=str(pdf_path), media_type="application/pdf", filename=f"{row['numero']}.pdf")
    finally:
        conn.close()


@router.patch("/invoices/{invoice_id}")
def forbid_invoice_update(
    invoice_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> None:
    raise HTTPException(
        status_code=409,
        detail="INVOICE_IMMUTABLE : une facture validée ou émise ne peut plus être modifiée. Émettez un avoir lié.",
    )


@router.delete("/invoices/{invoice_id}")
def forbid_invoice_delete(
    invoice_id: str,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> None:
    raise HTTPException(
        status_code=409,
        detail="INVOICE_IMMUTABLE : une facture validée ou émise ne peut pas être supprimée. Émettez un avoir lié.",
    )


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice_endpoint(
    invoice_id: str,
    payload: IssueInvoiceIn,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    canal = _normalize_channel(payload.canal or payload.channel)
    conn = _conn()
    try:
        inv = issue_invoice(conn, invoice_id, canal=canal, acteur=role)
        dispatch_log: dict[str, Any] = {"canal": canal, "simulation": True}
        if canal == "email_sim":
            dispatch_log = send_invoice_email(inv, destinataire=payload.destinataire or "client@simulation.local")
        elif canal == "whatsapp_sim":
            dispatch_log = send_invoice_whatsapp(inv, telephone=payload.telephone or "+22900000000")
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        out = _serialize_invoice(conn, row)
        out["dispatch"] = dispatch_log
        return out
    except EtatInvalide as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/invoices/{invoice_id}/credit-notes")
def create_credit_note_endpoint(
    invoice_id: str,
    payload: CreditNoteCreateIn,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    role: str = Depends(require_roles("dirigeant")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        if payload.lignes:
            lignes_avoir = [l.model_dump() for l in payload.lignes]
        else:
            # Avoir total par défaut : reprend toutes les lignes de la facture
            rows = conn.execute(
                "SELECT * FROM invoice_lines WHERE facture=? ORDER BY numero", (invoice_id,)
            ).fetchall()
            lignes_avoir = []
            for r in rows:
                code = conn.execute("SELECT taux_bp FROM tax_codes WHERE code=?", (r["tax_code"],)).fetchone()
                lignes_avoir.append({
                    "numero": r["numero"],
                    "description": r["description"],
                    "quantite": r["quantite"],
                    "unite": r["unite"],
                    "pu_ht": r["pu_ht"],
                    "remise": r["remise"],
                    "taux_bp": int(code["taux_bp"]) if code else 1800,
                })
        return create_credit_note(
            conn,
            invoice_id=invoice_id,
            lignes_avoir=lignes_avoir,
            motif=payload.motif,
            acteur=role,
            total=payload.total or not payload.lignes,
            idempotency_key=idempotency_key,
        )
    except AvoirRefuse as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EtatInvalide as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Référentiels (E3)
# ---------------------------------------------------------------------------

@router.get("/referentials/clients")
def list_clients(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM clients ORDER BY raison_sociale").fetchall()
        return {"items": [{**dict(r), "name": r["raison_sociale"]} for r in rows]}
    finally:
        conn.close()


@router.post("/referentials/clients")
def create_client(
    payload: ClientCreateIn,
    role: str = Depends(require_roles("dirigeant")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        cid = new_id("cli")
        with transaction(conn):
            conn.execute(
                "INSERT INTO clients(id, raison_sociale, ifu, adresse, ville, telephone, conditions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, payload.raison_sociale, payload.ifu, payload.adresse, payload.ville, payload.telephone, payload.conditions),
            )
            append_event(conn, role, "CREATION_CLIENT", None, {"id": cid, "raison_sociale": payload.raison_sociale})
        row = conn.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
        return {**dict(row), "name": row["raison_sociale"]}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Impossible de créer le client : {exc}") from exc
    finally:
        conn.close()


@router.get("/referentials/items")
def list_items(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM items ORDER BY designation").fetchall()
        return {"items": [{**dict(r), "name": r["designation"], "price": r["prix_catalogue"]} for r in rows]}
    finally:
        conn.close()


@router.post("/referentials/items")
def create_item(
    payload: ItemCreateIn,
    role: str = Depends(require_roles("dirigeant", "assistante")),
) -> dict[str, Any]:
    conn = _conn()
    try:
        iid = new_id("art")
        with transaction(conn):
            conn.execute(
                "INSERT INTO items(id, reference, designation, unite, prix_catalogue, famille) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iid, payload.reference, payload.designation, payload.unite, payload.prix_catalogue, payload.famille),
            )
            append_event(conn, role, "CREATION_ARTICLE", None, {"id": iid, "reference": payload.reference})
        row = conn.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        return {**dict(row), "name": row["designation"], "price": row["prix_catalogue"]}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Impossible de créer l'article : {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Audit & Administration (E8, E10)
# ---------------------------------------------------------------------------

@router.get("/audit")
def list_audit(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM audit_events ORDER BY sequence DESC").fetchall()
        items = [
            {
                **dict(r),
                "id": f"evt-{r['sequence']}",
                "actor": r["acteur"],
                "at": r["horodatage"],
            }
            for r in rows
        ]
        return {"items": items}
    finally:
        conn.close()


@router.get("/audit/verify")
def verify_audit(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))) -> dict[str, Any]:
    conn = _conn()
    try:
        ok, erreurs = verifier_chaine(conn)
        count = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        return {
            "valid": ok,
            "events": int(count),
            "errors": erreurs,
            "detail": "Chaîne SHA-256 intacte" if ok else f"Altération détectée : {'; '.join(erreurs)}",
        }
    finally:
        conn.close()


@router.get("/audit/export.csv")
def export_audit_csv(role: str = Depends(require_roles("dirigeant", "assistante", "lecture"))):
    conn = _conn()
    try:
        csv_data = exporter_csv(conn)
        return PlainTextResponse(content=csv_data, media_type="text/csv")
    finally:
        conn.close()


@router.post("/admin/reset")
def admin_reset(role: str = Depends(require_roles("dirigeant"))) -> dict[str, Any]:
    for sub in ("pdf", "documents", "pages", "outbox"):
        target = data_dir() / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    db_reset()
    ensure_dirs()
    conn = _conn()
    try:
        with transaction(conn):
            append_event(conn, role, "RESET_DEMO", None, {"as_of": settings.as_of})
    finally:
        conn.close()
    return {"reset": True, "as_of": settings.as_of, "graine_demo": settings.graine_demo}
