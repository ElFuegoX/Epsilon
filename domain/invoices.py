"""Validation, numérotation, immutabilité, émission et avoirs.

Le numéro est attribué dans la même transaction que le gel du brouillon :
une seule facture, un seul numéro, deux réponses identiques en cas de double clic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping

from config import horodatage, settings
from db import data_dir, new_id, transaction
from .audit import append_event
from .controls import (
    BLOQUANT,
    RESOLU,
    Anomalie,
    Resolution,
    build_context,
    empreinte_metier,
    run_controls,
)
from .extraction import canonical
from .numbering import apercu, reserver
from .tax import CodeFiscal, ResultatCalcul, calculer, lignes_depuis_dict

GenerateurPDF = Callable[[Mapping[str, Any], str, Any], None]
HacheurPDF = Callable[[Any], str]


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


def _generateur_pdf(
    injecte: tuple[GenerateurPDF, HacheurPDF] | None = None,
) -> tuple[GenerateurPDF, HacheurPDF]:
    """Injectable pour les tests ; sinon délégué à adapters.pdf (Melon)."""
    if injecte is not None:
        return injecte
    from adapters import pdf

    manquants = [nom for nom in ("build_invoice_pdf", "hash_file") if not hasattr(pdf, nom)]
    if manquants:
        raise EtatInvalide("générateur PDF indisponible (TODO Melon) : " + ", ".join(manquants))
    return pdf.build_invoice_pdf, pdf.hash_file


def _quantite_exacte(valeur: Any) -> Decimal:
    """Quantité décimale exacte : jamais de flottant monétaire."""
    if isinstance(valeur, bool) or isinstance(valeur, float):
        raise ValidationError("quantité flottante interdite : fournir un entier ou une chaîne")
    try:
        return Decimal(str(valeur if valeur not in (None, "") else 0))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"quantité invalide : {valeur}") from exc


def _resolutions_depuis_base(conn: sqlite3.Connection, draft_id: str) -> dict[str, Resolution]:
    """Relit les traces enregistrées dans `anomalies.resolution` (JSON)."""
    retrouvees: dict[str, Resolution] = {}
    for row in conn.execute(
        "SELECT code, champ, resolution, avant, apres FROM anomalies "
        "WHERE draft=? AND statut='RESOLUE'",
        (draft_id,),
    ):
        try:
            donnees = json.loads(row["resolution"] or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(donnees, dict):
            continue
        donnees = dict(donnees)
        donnees.setdefault("avant", row["avant"] or "")
        donnees.setdefault("apres", row["apres"] or "")
        try:
            trace = Resolution.depuis(donnees)
        except ValueError:
            continue
        cle = f"{row['code']}:{row['champ']}" if row["champ"] else row["code"]
        retrouvees[cle] = trace
    return retrouvees


def refresh_anomalies(
    conn: sqlite3.Connection,
    draft_id: str,
    resolutions: Mapping[str, Any] | None = None,
) -> list[Anomalie]:
    """Recalcule les anomalies ouvertes ; les résolues restent tracées."""
    traces = _resolutions_depuis_base(conn, draft_id)
    if resolutions:
        traces.update({str(code): Resolution.depuis(v) for code, v in resolutions.items()})
    ctx = build_context(conn, draft_id, resolutions=traces)
    anomalies = run_controls(ctx)
    conn.execute("DELETE FROM anomalies WHERE draft=? AND statut='OUVERTE'", (draft_id,))
    for anomalie in anomalies:
        if anomalie.statut == "OUVERTE":
            conn.execute(
                "INSERT INTO anomalies(id, draft, code, severite, champ, message, statut, resolution) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("ano"), draft_id, anomalie.code, anomalie.severite, anomalie.champ,
                 anomalie.message, anomalie.statut, anomalie.resolution),
            )
            continue
        trace = Resolution(anomalie.acteur, anomalie.motif, anomalie.avant, anomalie.apres)
        enregistree = conn.execute(
            "SELECT 1 FROM anomalies WHERE draft=? AND code=? AND champ=? AND statut='RESOLUE' LIMIT 1",
            (draft_id, anomalie.code, anomalie.champ),
        ).fetchone()
        payload = json.dumps(
            {"acteur": trace.acteur, "motif": trace.motif, "avant": trace.avant, "apres": trace.apres},
            sort_keys=True,
            ensure_ascii=False,
        )
        if enregistree:
            conn.execute(
                "UPDATE anomalies SET resolution=?, avant=?, apres=? "
                "WHERE draft=? AND code=? AND champ=? AND statut='RESOLUE'",
                (payload, trace.avant, trace.apres, draft_id, anomalie.code, anomalie.champ),
            )
        else:
            conn.execute(
                "INSERT INTO anomalies(id, draft, code, severite, champ, message, statut, "
                "resolution, avant, apres) VALUES (?, ?, ?, ?, ?, ?, 'RESOLUE', ?, ?, ?)",
                (new_id("ano"), draft_id, anomalie.code, anomalie.severite, anomalie.champ,
                 anomalie.message, payload, trace.avant, trace.apres),
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
    *,
    resolutions: Mapping[str, Any] | None = None,
    generateur_pdf: tuple[GenerateurPDF, HacheurPDF] | None = None,
) -> dict[str, Any]:
    """Acte humain : contrôle final, numéro, snapshot, PDF, engagement."""
    cle = idempotency_key or f"validate:{draft_id}"
    with transaction(conn):
        # La clé est lue DANS la transaction : un second appel attend le premier
        # et reçoit exactement la même réponse sans consommer de numéro.
        deja = conn.execute("SELECT resultat FROM idempotency_keys WHERE cle=?", (cle,)).fetchone()
        if deja:
            return json.loads(deja["resultat"])

        draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
        if draft is None:
            raise EtatInvalide(f"brouillon introuvable: {draft_id}")
        if draft["statut"] not in ("BROUILLON", "CONTRÔLÉ"):
            raise EtatInvalide(f"statut non validable: {draft['statut']}")

        anomalies = refresh_anomalies(conn, draft_id, resolutions=resolutions)
        bloquantes = [
            a for a in anomalies if a.severite == BLOQUANT and a.statut != RESOLU
        ]
        if bloquantes:
            raise AnomaliesBloquantes(bloquantes)

        ctx = build_context(conn, draft_id, resolutions=resolutions)
        if ctx.calcule is None:
            raise ValidationError("calcul indisponible : corriger le code fiscal avant validation")
        resultat = ctx.calcule
        client = ctx.client
        lignes = ctx.lignes

        # Tout est vérifié avant d'attribuer le numéro.
        numero = reserver(conn, prefixe=settings.prefixe_facture)
        snapshot = construire_snapshot(dict(draft), lignes, resultat, client, numero)
        snapshot_json = canonical(snapshot)
        hash_snapshot = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

        construire_pdf, hacher_pdf = _generateur_pdf(generateur_pdf)
        destination = data_dir() / "pdf" / f"{numero}.pdf"
        construire_pdf(snapshot, numero, destination)
        hash_pdf = hacher_pdf(destination)

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


def bornes_avoir(
    lignes_facturees: Mapping[int, Mapping[str, Any]],
    items: Iterable[Mapping[str, Any]],
    avoirs_precedents: Mapping[int, Any] | None = None,
) -> None:
    """Borne chaque ligne d'avoir par la ligne facturée et par le cumul déjà émis.

    `avoirs_precedents` (numéro de ligne → quantité déjà avoirée) doit être
    fourni par l'API dès que le schéma exposera `credit_note_lines`.
    """
    precedents = avoirs_precedents or {}
    for ligne in items:
        numero = int(ligne.get("numero") or 0)
        cible = lignes_facturees.get(numero)
        if cible is None:
            raise AvoirRefuse(f"ligne {numero} absente de la facture")
        demande = _quantite_exacte(ligne.get("quantite", 0))
        facturee = _quantite_exacte(cible.get("quantite", 0))
        deja = _quantite_exacte(precedents.get(numero, 0))
        if demande <= 0:
            raise AvoirRefuse(f"quantité d'avoir non positive sur la ligne {numero}")
        if demande > facturee:
            raise AvoirRefuse(f"quantité d'avoir supérieure à la ligne {numero}")
        if deja + demande > facturee:
            raise AvoirRefuse(
                f"cumul des avoirs {deja + demande} supérieur à la ligne {numero} ({facturee})"
            )


def create_credit_note(
    conn: sqlite3.Connection,
    invoice_id: str,
    lignes_avoir: Iterable[Mapping[str, Any]],
    motif: str,
    acteur: str = "dirigeant",
    total: bool = False,
    idempotency_key: str | None = None,
    *,
    avoirs_precedents: Mapping[int, Any] | None = None,
) -> dict[str, Any]:
    """Avoir lié, numéroté, borné : somme <= TTC et ligne <= ligne facturée."""
    items = list(lignes_avoir)
    cle = idempotency_key or f"credit:{invoice_id}:{canonical(items)}:{motif}"
    with transaction(conn):
        deja_cle = conn.execute(
            "SELECT resultat FROM idempotency_keys WHERE cle=?", (cle,)
        ).fetchone()
        if deja_cle:
            return json.loads(deja_cle["resultat"])

        facture = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if facture is None or facture["statut"] not in ("ÉMIS", "VALIDÉ"):
            raise EtatInvalide("facture non émise ou introuvable")
        lignes_facturees = {
            int(r["numero"]): dict(r) for r in conn.execute(
                "SELECT * FROM invoice_lines WHERE facture=?", (invoice_id,)
            )
        }
        bornes_avoir(lignes_facturees, items, avoirs_precedents=avoirs_precedents)

        referentiel = {
            r["code"]: CodeFiscal(r["code"], int(r["taux_bp"]), bool(r["exoneration"]))
            for r in conn.execute("SELECT code, taux_bp, exoneration FROM tax_codes")
        }
        items_normalises: list[dict[str, Any]] = []
        for ligne in items:
            copie = dict(ligne)
            cible = lignes_facturees[int(copie.get("numero") or 0)]
            copie.setdefault("tax_code", cible["tax_code"])
            items_normalises.append(copie)
        calcul = calculer(
            lignes_depuis_dict(items_normalises, referentiel=referentiel),
            referentiel=referentiel,
        )

        deja_emis = conn.execute(
            "SELECT COALESCE(SUM(total_ttc), 0) AS s FROM credit_notes WHERE facture=?", (invoice_id,)
        ).fetchone()["s"]
        plat = int(deja_emis) + calcul.total_ttc
        if plat > int(facture["total_ttc"]):
            raise AvoirRefuse(
                f"cumul des avoirs {plat} FCFA supérieur au TTC {facture['total_ttc']} FCFA"
            )

        numero_avoir = reserver(conn, prefixe=settings.prefixe_avoir)
        avoir_id = new_id("av")
        conn.execute(
            "INSERT INTO credit_notes(id, numero, serie, annee, facture, motif, total_ht, "
            "total_tva, total_ttc, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'EMIS', ?)",
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


def verifier_pdf(
    conn: sqlite3.Connection,
    invoice_id: str,
    *,
    generateur_pdf: tuple[GenerateurPDF, HacheurPDF] | None = None,
) -> bool:
    """Une régénération depuis le snapshot doit donner le même hash."""
    construire_pdf, hacher_pdf = _generateur_pdf(generateur_pdf)
    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if row is None:
        raise EtatInvalide("facture introuvable")
    destination = data_dir() / "pdf" / f"verify-{row['numero']}.pdf"
    construire_pdf(json.loads(row["snapshot"]), row["numero"], destination)
    return hacher_pdf(destination) == row["hash_pdf"]
