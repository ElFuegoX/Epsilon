"""Validation, numérotation, immutabilité, émission et avoirs.

Le numéro est attribué dans la même transaction que le gel du brouillon :
une seule facture, un seul numéro, deux réponses identiques en cas de double clic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Iterable, Mapping

from config import horodatage, settings
from db import data_dir, new_id, transaction
from .audit import append_event, hash_chaine
from .controls import (
    Anomalie,
    bloquant,
    build_context,
    empreinte_metier,
    run_controls,
)
from .extraction import canonical
from .numbering import apercu, reserver
from .tax import ResultatCalcul, calculer, lignes_depuis_dict


class ValidationError(Exception):
    pass


class EtatInvalide(ValidationError):
    pass


class AnomaliesBloquantes(ValidationError):
    def __init__(self, anomalies: Iterable[Anomalie]):
        super().__init__("anomalies bloquantes non résolues")
        self.anomalies = list(anomalies)


class AvoirRefuse(ValidationError):
    pass


def refresh_anomalies(conn: sqlite3.Connection, draft_id: str) -> list[Anomalie]:
    """Recalcule les anomalies ouvertes ; les résolues restent tracées."""
    ctx = build_context(conn, draft_id)
    anomalies = run_controls(ctx)
    conn.execute("DELETE FROM anomalies WHERE draft=? AND statut='OUVERTE'", (draft_id,))
    for a in anomalies:
        if a.statut == "OUVERTE":
            conn.execute(
                "INSERT INTO anomalies(id, draft, code, severite, champ, message, statut, resolution) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("ano"), draft_id, a.code, a.severite, a.champ, a.message, a.statut, a.resolution),
            )
    return anomalies


def construire_snapshot(
    draft: Mapping[str, Any],
    lignes: Iterable[Mapping[str, Any]],
    resultat: ResultatCalcul,
    client: Mapping[str, Any] | None,
    numero: str,
) -> dict[str, Any]:
    return {
        "numero": numero,
        "date": draft.get("date_piece"),
        "echeance": draft.get("date_echeance"),
        "conditions": draft.get("conditions"),
        "client": {
            "id": client.get("id") if client else None,
            "raison_sociale": client.get("raison_sociale") if client else None,
            "ifu": client.get("ifu") if client else None,
            "adresse": client.get("adresse") if client else None,
        },
        "lignes": [dict(l) for l in lignes],
        "calcul": resultat.to_dict(),
        "devise": settings.devise,
        "as_of": settings.as_of,
        "mention": "SIMULATION — document de démonstration, non utilisable pour une déclaration fiscale",
    }


def validate_draft(
    conn: sqlite3.Connection,
    draft_id: str,
    acteur: str = "dirigeant",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Acte humain : contrôle final, numéro, snapshot, PDF, engagement."""
    cle = idempotency_key or f"validate:{draft_id}"
    deja = conn.execute("SELECT resultat FROM idempotency_keys WHERE cle=?", (cle,)).fetchone()
    if deja:
        return json.loads(deja["resultat"])

    with transaction(conn):
        draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
        if draft is None:
            raise EtatInvalide(f"brouillon introuvable: {draft_id}")
        if draft["statut"] not in ("BROUILLON", "CONTRÔLÉ"):
            raise EtatInvalide(f"statut non validable: {draft['statut']}")

        anomalies = refresh_anomalies(conn, draft_id)
        bloquantes = [a for a in anomalies if a.severite == "BLOQUANT"]
        if bloquantes:
            raise AnomaliesBloquantes(bloquantes)

        ctx = build_context(conn, draft_id)
        client = ctx.client
        lignes = ctx.lignes
        resultat = ctx.calcule or calculer([])

        numero = reserver(conn, prefixe=settings.prefixe_facture)
        snapshot = construire_snapshot(dict(draft), lignes, resultat, client, numero)
        snapshot_json = canonical(snapshot)
        hash_snapshot = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

        from adapters.pdf import build_invoice_pdf, hash_file

        destination = data_dir() / "pdf" / f"{numero}.pdf"
        build_invoice_pdf(snapshot, numero, destination)
        hash_pdf = hash_file(destination)

        empreinte = empreinte_metier(draft["client"], draft["date_piece"], lignes)
        invoice_id = new_id("inv")
        conn.execute(
            "INSERT INTO invoices(id, numero, serie, annee, snapshot, hash_snapshot, hash_pdf, "
            "date, statut, client, empreinte, total_ht, total_tva, total_ttc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VALIDÉ', ?, ?, ?, ?, ?)",
            (invoice_id, numero, settings.serie_defaut, settings.annee, snapshot_json,
             hash_snapshot, hash_pdf, settings.as_of, draft["client"], empreinte,
             resultat.total_ht, resultat.total_tva, resultat.total_ttc),
        )
        for i, (ligne, calc) in enumerate(zip(lignes, resultat.lignes), start=1):
            conn.execute(
                "INSERT INTO invoice_lines(id, facture, numero, description, quantite, unite, pu_ht, "
                "remise, tax_code, total_ht, tva) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("invl"), invoice_id, i, ligne["description"], ligne["quantite"],
                 ligne["unite"], ligne["pu_ht"], ligne["remise"], ligne["tax_code"],
                 calc.net_ht, calc.tva),
            )
        conn.execute(
            "UPDATE invoice_drafts SET statut='VALIDÉ', version=version+1, modifie_le=? WHERE id=?",
            (horodatage(), draft_id),
        )
        append_event(conn, acteur, "VALIDATION_BROUILLON", {"id": draft_id, "version": draft["version"]},
                     {"statut": "VALIDÉ"})
        append_event(conn, acteur, "NUMERO_ATTRIBUE", None, {"numero": numero, "serie": settings.serie_defaut})
        append_event(conn, "systeme", "PDF_GENERE", None, {"numero": numero, "hash": hash_pdf})

        resultat_final = {
            "invoice_id": invoice_id, "numero": numero, "statut": "VALIDÉ",
            "hash_snapshot": hash_snapshot, "hash_pdf": hash_pdf,
            "total_ht": resultat.total_ht, "total_tva": resultat.total_tva,
            "total_ttc": resultat.total_ttc,
        }
        conn.execute(
            "INSERT INTO idempotency_keys(cle, action, resultat, date) VALUES (?, ?, ?, ?)",
            (cle, "validate", json.dumps(resultat_final, sort_keys=True), horodatage()),
        )
    return resultat_final


def issue_invoice(
    conn: sqlite3.Connection,
    invoice_id: str,
    canal: str,
    acteur: str = "dirigeant",
) -> dict[str, Any]:
    """Émission simulée : statut et canal uniquement, jamais les montants."""
    with transaction(conn):
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if row is None:
            raise EtatInvalide("facture introuvable")
        if row["statut"] not in ("VALIDÉ", "ÉMIS"):
            raise EtatInvalide(f"statut non émettable: {row['statut']}")
        if canal not in ("email_sim", "whatsapp_sim", "telechargement"):
            raise ValidationError(f"canal inconnu: {canal}")
        reference = f"SIM-{row['numero']}-{settings.as_of.replace('-', '')}"
        conn.execute(
            "UPDATE invoices SET statut='ÉMIS', canal=?, mecef_ref=? WHERE id=?",
            (canal, reference, invoice_id),
        )
        append_event(conn, acteur, "EMISSION_SIMULEE", {"statut": row["statut"]},
                     {"statut": "ÉMIS", "canal": canal, "mecef_ref": reference})
    return dict(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone())


def create_credit_note(
    conn: sqlite3.Connection,
    invoice_id: str,
    lignes_avoir: Iterable[Mapping[str, Any]],
    motif: str,
    acteur: str = "dirigeant",
    total: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Avoir lié, numéroté, borné : somme <= TTC et ligne <= ligne facturée."""
    items = list(lignes_avoir)
    cle = idempotency_key or f"credit:{invoice_id}:{canonical(items)}:{motif}"
    deja = conn.execute("SELECT resultat FROM idempotency_keys WHERE cle=?", (cle,)).fetchone()
    if deja:
        import json
        return json.loads(deja["resultat"])

    with transaction(conn):
        facture = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if facture is None or facture["statut"] not in ("ÉMIS", "VALIDÉ"):
            raise EtatInvalide("facture non émise ou introuvable")
        lignes_facturees = {
            int(r["numero"]): dict(r) for r in conn.execute(
                "SELECT * FROM invoice_lines WHERE facture=?", (invoice_id,)
            )
        }
        deja_emis = conn.execute(
            "SELECT COALESCE(SUM(total_ttc), 0) AS s FROM credit_notes WHERE facture=?", (invoice_id,)
        ).fetchone()["s"]
        for ligne in items:
            numero = int(ligne.get("numero", 0))
            cible = lignes_facturees.get(numero)
            if cible is None:
                raise AvoirRefuse(f"ligne {numero} absente de la facture")
            quantite = float(ligne.get("quantite", 0))
            if quantite > float(cible["quantite"]):
                raise AvoirRefuse(f"quantité d'avoir supérieure à la ligne {numero}")
        calcul = calculer(lignes_depuis_dict(items))
        plat = int(deja_emis) + calcul.total_ttc
        if plat > int(facture["total_ttc"]):
            raise AvoirRefuse(
                f"cumul des avoirs {plat} FCFA supérieur au TTC {facture['total_ttc']} FCFA"
            )
        numero_avoir = reserver(conn, prefixe=settings.prefixe_avoir)
        avoir_id = new_id("av")
        conn.execute(
            "INSERT INTO credit_notes(id, numero, serie, annee, facture, motif, total_ht, total_tva, "
            "total_ttc, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'EMIS', ?)",
            (avoir_id, numero_avoir, settings.serie_defaut, settings.annee, invoice_id, motif,
             calcul.total_ht, calcul.total_tva, calcul.total_ttc, horodatage()),
        )
        if total or plat == int(facture["total_ttc"]):
            conn.execute("UPDATE invoices SET statut='ANNULÉ_PAR_AVOIR' WHERE id=?", (invoice_id,))
        append_event(conn, acteur, "AVOIR_EMIS", {"facture": facture["numero"]},
                     {"avoir": numero_avoir, "motif": motif, "ttc": calcul.total_ttc})
        resultat = {
            "credit_note_id": avoir_id, "numero": numero_avoir, "facture": facture["numero"],
            "total_ttc": calcul.total_ttc, "solde": int(facture["total_ttc"]) - plat,
        }
        import json
        conn.execute(
            "INSERT INTO idempotency_keys(cle, action, resultat, date) VALUES (?, ?, ?, ?)",
            (cle, "credit", json.dumps(resultat, sort_keys=True), horodatage()),
        )
    return resultat


def add_payment(
    conn: sqlite3.Connection,
    invoice_id: str,
    montant: int,
    canal: str,
    reference: str,
    acteur: str = "assistante",
) -> dict[str, Any]:
    """Règlement simulé : somme <= net à payer."""
    with transaction(conn):
        facture = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if facture is None:
            raise EtatInvalide("facture introuvable")
        paye = conn.execute(
            "SELECT COALESCE(SUM(montant), 0) AS s FROM payments WHERE facture=?", (invoice_id,)
        ).fetchone()["s"]
        avoirs = conn.execute(
            "SELECT COALESCE(SUM(total_ttc), 0) AS s FROM credit_notes WHERE facture=?", (invoice_id,)
        ).fetchone()["s"]
        net = int(facture["total_ttc"]) - int(avoirs)
        if int(paye) + int(montant) > net:
            raise ValidationError("encaissement supérieur au net à payer")
        identifiant = new_id("pay")
        conn.execute(
            "INSERT INTO payments(id, facture, montant, date, canal, reference) VALUES (?, ?, ?, ?, ?, ?)",
            (identifiant, invoice_id, montant, settings.as_of, canal, reference),
        )
        append_event(conn, acteur, "PAIEMENT_SIMULE", None,
                     {"facture": facture["numero"], "montant": montant})
    return {"payment_id": identifiant, "solde": net - int(paye) - int(montant)}


def preview_number(conn: sqlite3.Connection, prefixe: str | None = None) -> str:
    return apercu(conn, prefixe=prefixe)


def registre(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, numero, date, statut, client, total_ht, total_tva, total_ttc, canal, mecef_ref "
        "FROM invoices ORDER BY numero"
    ).fetchall()
    return [dict(r) for r in rows]


def verifier_pdf(conn: sqlite3.Connection, invoice_id: str) -> bool:
    """Une régénération depuis le snapshot doit donner le même hash."""
    import hashlib

    from adapters.pdf import build_invoice_pdf, hash_file

    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if row is None:
        raise EtatInvalide("facture introuvable")
    import json

    destination = data_dir() / "pdf" / f"verify-{row['numero']}.pdf"
    build_invoice_pdf(json.loads(row["snapshot"]), row["numero"], destination)
    return hash_file(destination) == row["hash_pdf"]
