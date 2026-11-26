"""Parcours complet d'une pièce, de l'import à l'avoir.

Une seule porte d'entrée pour l'API, le worker, la CLI et les tests :

    importer → extraire (persister + brouillon) → controler → confirmer / resoudre / corriger
             → apercu_pdf → valider (exiger_confirmations + validate_draft) → emettre → avoir

Chaque fonction vérifie le rôle (``ROLES``), tient le statut de la pièce par
l'automate de ``domain.documents`` et laisse une trace au journal d'audit.
Les règles de calcul, de contrôle et de numérotation restent celles de
Larissa ; ce module ne fait que les enchaîner. Voir docs/PARCOURS.md.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from config import horodatage, settings
from db import data_dir, new_id, transaction

from . import brouillon as brouillons
from . import documents as etats
from . import extraction, invoices
from .audit import append_event

# --------------------------------------------------------------------------
# Rôles (authentification simulée par X-Role, README)
# --------------------------------------------------------------------------

ROLES: dict[str, set[str]] = {
    "dirigeant": {"importer", "extraire", "lire", "confirmer", "resoudre", "resoudre_prix", "corriger",
                  "valider", "emettre", "avoir", "client", "apercu"},
    "assistante": {"importer", "extraire", "lire", "confirmer", "resoudre", "corriger", "emettre", "apercu"},
    "lecture": {"lire", "apercu"},
}


class AccesRefuse(Exception):
    """Le rôle n'autorise pas cette action (HTTP 403)."""


def exiger_role(role: str, action: str) -> None:
    if action not in ROLES.get(str(role or ""), set()):
        raise AccesRefuse(f"le rôle « {role} » ne peut pas : {action}")


# --------------------------------------------------------------------------
# Import et extraction
# --------------------------------------------------------------------------

MIMES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".txt": "text/plain"}


def chemin_piece(conn: sqlite3.Connection, document_id: str) -> Path:
    ligne = conn.execute("SELECT hash, nom FROM documents WHERE id=?", (document_id,)).fetchone()
    if ligne is None:
        raise etats.DocumentError(f"pièce introuvable : {document_id}")
    return data_dir() / "documents" / f"{ligne['hash']}{Path(ligne['nom']).suffix.lower()}"


def importer(conn: sqlite3.Connection, chemin: str | Path, *, role: str = "assistante",
             canal: str = "upload") -> dict[str, Any]:
    """Stocke la pièce sans la modifier. Même empreinte = même pièce, aucun nouvel import."""
    exiger_role(role, "importer")
    source = Path(chemin)
    mime = MIMES.get(source.suffix.lower())
    if mime is None or mime not in settings.allowed_mimes:
        raise etats.DocumentError(f"format refusé : {source.suffix or 'sans extension'}")
    contenu = source.read_bytes()
    if len(contenu) > settings.max_file_bytes:
        raise etats.DocumentError("pièce trop lourde")
    empreinte = hashlib.sha256(contenu).hexdigest()
    with transaction(conn):
        existant = conn.execute("SELECT id FROM documents WHERE hash=?", (empreinte,)).fetchone()
        decision = etats.decider_doublon(empreinte, existant["id"] if existant else None)
        if decision.doublon:
            append_event(conn, role, "IMPORT_DOUBLON_REFUSE", None,
                         {"document": decision.document_existant, "hash": empreinte})
            return {"document_id": decision.document_existant, "doublon": True, "hash": empreinte}
        document_id = new_id("doc")
        destination = data_dir() / "documents" / f"{empreinte}{source.suffix.lower()}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        conn.execute(
            "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (document_id, etats.classifier(source.name), source.name, mime, len(contenu), empreinte,
             canal, etats.IMPORTE, horodatage()),
        )
        append_event(conn, role, "IMPORT", None,
                     {"document": document_id, "nom": source.name, "hash": empreinte, "canal": canal})
    return {"document_id": document_id, "doublon": False, "hash": empreinte}


def extraire(conn: sqlite3.Connection, document_id: str, *, role: str = "assistante",
             ocr_backend: str | None = None) -> dict[str, Any]:
    """Extrait, persiste et crée le brouillon. Service OCR indisponible → EN_ATTENTE_IA, rien d'inventé."""
    exiger_role(role, "extraire")
    from adapters.ocr import OCRIndisponible

    statut = conn.execute("SELECT statut FROM documents WHERE id=?", (document_id,)).fetchone()
    if statut is None:
        raise etats.DocumentError(f"pièce introuvable : {document_id}")
    if statut["statut"] not in (etats.IMPORTE, etats.EN_ATTENTE_IA):
        brouillon = conn.execute("SELECT id FROM invoice_drafts WHERE document=?", (document_id,)).fetchone()
        return {"document_id": document_id, "statut": statut["statut"], "deja_extrait": True,
                "draft_id": brouillon["id"] if brouillon else None}
    try:
        payload = extraction.extraire_piece(chemin_piece(conn, document_id), ocr_backend=ocr_backend,
                                            clients=extraction.clients_depuis_base(conn))
    except (OCRIndisponible, extraction.ExtractionInvalide) as erreur:
        with transaction(conn):
            if statut["statut"] == etats.IMPORTE:
                etats.appliquer_transition(conn, document_id, etats.EN_ATTENTE_IA, "systeme",
                                           motif=f"extraction impossible : {erreur}")
        return {"document_id": document_id, "statut": etats.EN_ATTENTE_IA, "erreur": str(erreur)}
    with transaction(conn):
        extraction.persister(conn, document_id, payload)
        etats.appliquer_transition(conn, document_id, etats.EXTRAIT, "systeme")
        resume = brouillons.creer_brouillon(conn, document_id, payload)
    return {"document_id": document_id, "statut": etats.EXTRAIT, "draft_id": resume["draft_id"],
            "brouillon": resume, "type": payload["document_type"]}


def reprendre(conn: sqlite3.Connection, *, role: str = "assistante") -> list[dict[str, Any]]:
    """Reprise après interruption : relance chaque pièce restée IMPORTÉ ou EN_ATTENTE_IA, sans doublon."""
    en_attente = [r["id"] for r in conn.execute(
        "SELECT id FROM documents WHERE statut IN (?, ?) ORDER BY cree_le, id",
        (etats.IMPORTE, etats.EN_ATTENTE_IA))]
    return [extraire(conn, document_id, role=role) for document_id in en_attente]


# --------------------------------------------------------------------------
# Contrôles, corrections, décisions humaines
# --------------------------------------------------------------------------

def _anomalies(liste: Any) -> list[dict[str, Any]]:
    return [a.to_dict() for a in liste]


def controler(conn: sqlite3.Connection, draft_id: str, *, role: str = "lecture") -> list[dict[str, Any]]:
    exiger_role(role, "lire")
    with transaction(conn):
        return _anomalies(invoices.refresh_anomalies(conn, draft_id))


def resoudre(conn: sqlite3.Connection, draft_id: str, cle: str, *, role: str, motif: str,
             avant: str, apres: str) -> list[dict[str, Any]]:
    """Décision humaine tracée sur une anomalie (clé ``CODE`` ou ``CODE:champ``)."""
    exiger_role(role, "resoudre_prix" if cle.startswith("UNUSUAL_PRICE") else "resoudre")
    trace = {"acteur": role, "motif": motif, "avant": avant, "apres": apres}
    with transaction(conn):
        anomalies = invoices.refresh_anomalies(conn, draft_id, resolutions={cle: trace})
        append_event(conn, role, "ANOMALIE_RESOLUE", {"draft": draft_id, "cle": cle, "avant": avant},
                     {"draft": draft_id, "cle": cle, "apres": apres, "motif": motif})
    return _anomalies(anomalies)


def _brouillon_modifiable(conn: sqlite3.Connection, draft_id: str) -> sqlite3.Row:
    draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise brouillons.BrouillonError(f"brouillon introuvable : {draft_id}")
    if draft["statut"] not in (brouillons.STATUT_BROUILLON, "CONTRÔLÉ"):
        raise invoices.EtatInvalide(f"brouillon figé ({draft['statut']}) : toute correction passe par un avoir")
    return draft


def modifier_brouillon(conn: sqlite3.Connection, draft_id: str, *, role: str, motif: str,
                       date_echeance: str | None = None, conditions: str | None = None,
                       client: str | None = None) -> dict[str, Any]:
    """Correction humaine de l'en-tête (échéance obtenue du client, conditions, rattachement client)."""
    exiger_role(role, "client" if client is not None else "corriger")
    with transaction(conn):
        draft = _brouillon_modifiable(conn, draft_id)
        changements = {k: v for k, v in (("date_echeance", date_echeance), ("conditions", conditions),
                                         ("client", client)) if v is not None}
        if not changements:
            return dict(draft)
        for colonne, valeur in changements.items():
            conn.execute(f"UPDATE invoice_drafts SET {colonne}=? WHERE id=?", (valeur, draft_id))
        conn.execute("UPDATE invoice_drafts SET version=version+1, modifie_le=? WHERE id=?",
                     (horodatage(), draft_id))
        append_event(conn, role, "BROUILLON_CORRIGE",
                     {"draft": draft_id, **{k: draft[k] for k in changements}},
                     {"draft": draft_id, **changements, "motif": motif})
        return dict(conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone())


def renseigner_ifu(conn: sqlite3.Connection, client_id: str, ifu: str, *, role: str, motif: str) -> None:
    """IFU obtenu du client (réponse au message de clarification). Réservé au dirigeant."""
    exiger_role(role, "client")
    with transaction(conn):
        avant = conn.execute("SELECT ifu FROM clients WHERE id=?", (client_id,)).fetchone()
        if avant is None:
            raise etats.DocumentError(f"client introuvable : {client_id}")
        conn.execute("UPDATE clients SET ifu=? WHERE id=?", (ifu, client_id))
        append_event(conn, role, "CLIENT_IFU_RENSEIGNE", {"client": client_id, "ifu": avant["ifu"]},
                     {"client": client_id, "ifu": ifu, "motif": motif})


def exclure_ligne(conn: sqlite3.Connection, draft_id: str, numero: int, *, role: str, motif: str) -> None:
    """Décision « exclure la ligne » (ligne non livrée) : la ligne sort du brouillon, la trace reste."""
    exiger_role(role, "corriger")
    with transaction(conn):
        _brouillon_modifiable(conn, draft_id)
        ligne = conn.execute("SELECT * FROM draft_lines WHERE draft=? AND numero=?", (draft_id, numero)).fetchone()
        if ligne is None:
            raise brouillons.BrouillonError(f"ligne {numero} absente du brouillon")
        conn.execute("DELETE FROM draft_lines WHERE draft=? AND numero=?", (draft_id, numero))
        conn.execute("DELETE FROM deliveries WHERE draft=? AND numero=?", (draft_id, numero))
        conn.execute("UPDATE invoice_drafts SET version=version+1, modifie_le=? WHERE id=?",
                     (horodatage(), draft_id))
        append_event(conn, role, "LIGNE_EXCLUE", {"draft": draft_id, "ligne": dict(ligne)},
                     {"draft": draft_id, "numero": numero, "motif": motif})


def message_clarification(conn: sqlite3.Connection, draft_id: str) -> str:
    """Message à copier pour le client : seulement les champs manquants, aucune valeur proposée."""
    draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise brouillons.BrouillonError(f"brouillon introuvable : {draft_id}")
    reference = conn.execute(
        "SELECT valeur FROM extracted_fields WHERE chemin='reference' AND extraction IN "
        "(SELECT id FROM extractions WHERE document=?) ORDER BY extraction DESC LIMIT 1",
        (draft["document"],)).fetchone()
    manquants = [a["champ"] for a in conn.execute(
        "SELECT champ FROM anomalies WHERE draft=? AND code='MISSING_MANDATORY' AND statut='OUVERTE'",
        (draft_id,))]
    if not manquants:
        return ""
    piece = reference["valeur"] if reference else "votre pièce"
    return (f"Bonjour, pour établir la facture correspondant à {piece}, il nous manque : "
            f"{'; '.join(manquants)}. Pourriez-vous nous les communiquer ? Merci.")


def apercu_pdf(conn: sqlite3.Connection, draft_id: str, *, role: str = "lecture") -> dict[str, Any]:
    """Brouillon exportable en PDF (bandeau BROUILLON — NON FISCAL, aucun numéro)."""
    exiger_role(role, "apercu")
    from adapters.pdf import build_draft_pdf

    return build_draft_pdf(conn, draft_id, data_dir() / "pdf" / f"brouillon-{draft_id}.pdf")


# --------------------------------------------------------------------------
# Validation, émission, avoir
# --------------------------------------------------------------------------

def _suivre(conn: sqlite3.Connection, document_id: str | None, cibles: list[str], acteur: str,
            **preuves: Any) -> None:
    """Fait avancer le statut de la pièce, sans jamais reculer ni sauter une règle."""
    if not document_id:
        return
    for cible in cibles:
        actuel = conn.execute("SELECT statut FROM documents WHERE id=?", (document_id,)).fetchone()
        if actuel is None or actuel["statut"] == cible or cible not in etats.TRANSITIONS.get(actuel["statut"], ()):
            continue
        etats.appliquer_transition(conn, document_id, cible, acteur, **preuves)


def valider(conn: sqlite3.Connection, draft_id: str, *, role: str = "dirigeant",
            idempotency_key: str | None = None) -> dict[str, Any]:
    """Validation humaine : confirmations faites, anomalies résolues, puis numéro, snapshot et PDF."""
    exiger_role(role, "valider")
    brouillons.exiger_confirmations(conn, draft_id)
    resultat = invoices.validate_draft(conn, draft_id, acteur=role, idempotency_key=idempotency_key)
    ligne = conn.execute("SELECT document FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    document = ligne["document"] if ligne else None
    with transaction(conn):
        _lier(conn, resultat["invoice_id"], draft_id, document)
        _suivre(conn, document, [etats.CONTROLE, etats.BROUILLON], "systeme")
        _suivre(conn, document, [etats.VALIDE], role, decision_humaine=True)
    return resultat


def _facture(conn: sqlite3.Connection, invoice_id: str) -> sqlite3.Row:
    facture = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if facture is None:
        raise invoices.EtatInvalide("facture introuvable")
    return facture


def _lier(conn: sqlite3.Connection, invoice_id: str, draft_id: str, document_id: str | None) -> None:
    """La table invoices ne garde pas son brouillon : le lien facture → brouillon → pièce est noté ici."""
    import json

    conn.execute(
        "INSERT OR IGNORE INTO idempotency_keys(cle, action, resultat, date) VALUES (?, 'lien', ?, ?)",
        (f"lien:{invoice_id}", json.dumps({"draft": draft_id, "document": document_id}), horodatage()),
    )


def _document_de(conn: sqlite3.Connection, facture: sqlite3.Row) -> str | None:
    import json

    ligne = conn.execute("SELECT resultat FROM idempotency_keys WHERE cle=?",
                         (f"lien:{facture['id']}",)).fetchone()
    return json.loads(ligne["resultat"]).get("document") if ligne else None


def emettre(conn: sqlite3.Connection, invoice_id: str, canal: str, *, role: str = "dirigeant") -> dict[str, Any]:
    """Émission simulée : statut ÉMIS, message écrit dans data/outbox/, rien n'est envoyé."""
    exiger_role(role, "emettre")
    from adapters import canaux

    facture = invoices.issue_invoice(conn, invoice_id, canal, acteur=role)
    client = conn.execute("SELECT * FROM clients WHERE id=?", (facture["client"],)).fetchone()
    pdf = data_dir() / "pdf" / f"{facture['numero']}.pdf"
    message = canaux.envoyer(canal, facture, dict(client) if client else None,
                             str(pdf) if pdf.exists() else None)
    with transaction(conn):
        _suivre(conn, _document_de(conn, _facture(conn, invoice_id)), [etats.EMIS], role, canal=canal)
    return {"facture": facture, "message": message}


def avoir(conn: sqlite3.Connection, invoice_id: str, *, role: str = "dirigeant", motif: str,
          lignes: list[Mapping[str, Any]] | None = None, total: bool = False,
          idempotency_key: str | None = None) -> dict[str, Any]:
    """Avoir lié. ``total=True`` reprend toutes les lignes : la facture reste au registre, solde nul."""
    exiger_role(role, "avoir")
    if total and lignes is None:
        lignes = [{"numero": r["numero"], "quantite": r["quantite"], "pu_ht": r["pu_ht"],
                   "remise": r["remise"], "tax_code": r["tax_code"], "description": r["description"]}
                  for r in conn.execute("SELECT * FROM invoice_lines WHERE facture=? ORDER BY numero",
                                        (invoice_id,))]
    resultat = invoices.create_credit_note(conn, invoice_id, lignes or [], motif, acteur=role,
                                           total=total, idempotency_key=idempotency_key)
    facture = _facture(conn, invoice_id)
    with transaction(conn):
        document = _document_de(conn, facture)
        if facture["statut"] == "ANNULÉ_PAR_AVOIR":
            _suivre(conn, document, [etats.ANNULE_PAR_AVOIR], role, type_avoir="total")
    return resultat


def etat(conn: sqlite3.Connection, draft_id: str) -> dict[str, Any]:
    """Vue d'ensemble d'un brouillon pour un écran ou la CLI."""
    resume = brouillons.resume(conn, draft_id)
    resume["anomalies_ouvertes"] = [dict(r) for r in conn.execute(
        "SELECT code, severite, champ, message FROM anomalies WHERE draft=? AND statut='OUVERTE'",
        (draft_id,))]
    statut_piece = conn.execute("SELECT statut FROM documents WHERE id=?", (resume["document"],)).fetchone()
    resume["statut_piece"] = statut_piece["statut"] if statut_piece else None
    return resume
