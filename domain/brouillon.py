"""Maillon extraction → brouillon de facture.

Le TDR demande de « transformer une source commerciale en un projet de facture
vérifiable » et de « créer un document au statut BROUILLON ». L'extraction
produit un JSON (``domain/extraction.py``) ; les contrôles et la validation
(Larissa) lisent les tables ``invoice_drafts``, ``draft_lines`` et
``deliveries``. Ce module fait le pont, sans rien inventer :

* le client est rattaché par ``matching.match_client`` ; seuls C1 et C2 sont
  rattachés automatiquement, sinon le brouillon reste sans client et
  ``UNKNOWN_CLIENT`` / ``MISSING_MANDATORY`` le signaleront ;
* chaque ligne lue devient une ligne de brouillon. Une valeur que l'OCR n'a
  pas lue peut être **déduite** des valeurs imprimées de la même ligne
  (quantité = total ÷ PU, remise = qté × PU − total, total = qté × PU − remise)
  seulement si le calcul tombe juste ; elle est alors marquée **à confirmer**,
  jamais acceptée seule. Si la déduction est impossible, la ligne n'est pas
  créée : elle attend d'être complétée par un humain ;
* l'échéance absente reste absente (``MISSING_MANDATORY`` la réclamera) ;
* toute valeur sous son seuil de confiance devient une **confirmation**
  (table ``review_items``). ``exiger_confirmations`` refuse la validation
  tant qu'il en reste : c'est le branchement d'``extraction.exiger_revue``.

Voir docs/BROUILLON.md.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from config import horodatage
from db import new_id, transaction

from . import extraction, normalization as norm
from .audit import append_event
from .matching import NIVEAUX_RATTACHEMENT_AUTO, match_client, match_item

STATUT_BROUILLON = "BROUILLON"

# Types de confirmation (colonne review_items.type)
CHAMP_A_CONFIRMER = "CHAMP_A_CONFIRMER"   # valeur lue, confiance sous le seuil
VALEUR_DEDUITE = "VALEUR_DEDUITE"         # valeur non lue, déduite des autres valeurs imprimées
LIGNE_INCOMPLETE = "LIGNE_INCOMPLETE"     # ligne non créée : une valeur manque et ne se déduit pas

# Champs d'en-tête absents déjà réclamés par MISSING_MANDATORY (Larissa) : pas de doublon.
ABSENCES_COUVERTES = {"client.ifu", "dates.due", "dates.delivery", "client.address",
                      "client.phone", "payment_terms.method", "payment_terms.text",
                      "payment_terms.days"}
CHAMPS_LIGNE = ("description", "quantity", "unit", "unit_price_ht", "discount",
                "tax_rate", "line_total_ht")


class BrouillonError(Exception):
    """Le brouillon ne peut pas être créé ou modifié dans cet état."""


class ConfirmationsEnAttente(BrouillonError):
    """Des valeurs restent à confirmer : la validation est refusée."""

    def __init__(self, en_attente: list[dict[str, Any]]):
        self.en_attente = en_attente
        super().__init__(
            f"{len(en_attente)} valeur(s) à confirmer avant validation : "
            + ", ".join(e["chemin"] for e in en_attente[:8])
        )


# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------

def _valeur(champ: Mapping[str, Any] | None) -> Any:
    return extraction.valeur(champ) if isinstance(champ, Mapping) else None


def _decimal(valeur: Any) -> Decimal | None:
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except InvalidOperation:
        return None


def _code_fiscal(conn: sqlite3.Connection, taux: Any) -> str | None:
    """Code du référentiel pour un taux lu ; jamais de défaut à 18 %."""
    if taux is None:
        return None
    ligne = conn.execute(
        "SELECT code FROM tax_codes WHERE taux_bp=? ORDER BY code", (int(Decimal(str(taux)) * 100),)
    ).fetchone()
    # Taux hors référentiel : code explicite, INVALID_TAX le bloquera.
    return ligne["code"] if ligne else f"TAUX_INCONNU_{taux}"


def _conditions(conn: sqlite3.Connection, texte: Any, jours: Any) -> str | None:
    """Code de conditions dont le libellé correspond au texte lu, sinon le texte lu tel quel."""
    if texte is None and jours is None:
        return None
    lu = norm.normalize_text(texte)
    for ligne in conn.execute("SELECT code, libelle, delai_jours FROM payment_terms ORDER BY code"):
        if lu and norm.normalize_text(ligne["libelle"]) == lu:
            return ligne["code"]
    return str(texte) if texte is not None else None


def _priorite(chemin: str) -> str:
    seuil = extraction.seuil(chemin.split(".")[-1] if chemin.startswith("lines") else chemin)
    return "HAUTE" if seuil >= 0.90 else "NORMALE"


def _revue(conn: sqlite3.Connection, draft_id: str, type_: str, chemin: str,
           details: Mapping[str, Any]) -> None:
    # Une valeur non lue (déduite ou manquante) touche ce qui sera facturé : priorité haute.
    priorite = "HAUTE" if type_ in (VALEUR_DEDUITE, LIGNE_INCOMPLETE) else _priorite(chemin)
    conn.execute(
        "INSERT INTO review_items(id, type, entite, motif, priorite, assigne, resolution) "
        "VALUES (?, ?, ?, ?, ?, NULL, NULL)",
        (new_id("rev"), type_, f"{draft_id}|{chemin}",
         json.dumps(details, ensure_ascii=False, sort_keys=True, default=str), priorite),
    )


def _deduire(ligne: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Complète au plus une valeur numérique manquante par l'arithmétique de la ligne.

    Retourne (valeurs, champs déduits). Une déduction n'est retenue que si le
    résultat est exact (quantité entière ou décimale finie, remise ≥ 0).
    """
    q = _decimal(_valeur(ligne.get("quantity")))
    pu = _decimal(_valeur(ligne.get("unit_price_ht")))
    remise = _decimal(_valeur(ligne.get("discount")))
    total = _decimal(_valeur(ligne.get("line_total_ht")))
    deduits: list[str] = []
    if q is None and pu and total is not None and (remise is None or remise == 0):
        candidat = total / pu
        if candidat > 0 and candidat == candidat.quantize(Decimal("0.001")):
            q = candidat.normalize()
            deduits.append("quantity")
    if remise is None and q is not None and pu is not None and total is not None:
        candidat = q * pu - total
        if candidat >= 0 and candidat == candidat.to_integral_value():
            remise = candidat
            deduits.append("discount")
    if total is None and q is not None and pu is not None and remise is not None:
        total = q * pu - remise
        deduits.append("line_total_ht")
    valeurs = {"quantity": q, "unit_price_ht": pu, "discount": remise, "line_total_ht": total}
    return valeurs, deduits


# --------------------------------------------------------------------------
# Création
# --------------------------------------------------------------------------

def creer_brouillon(conn: sqlite3.Connection, document_id: str, payload: Mapping[str, Any],
                    *, acteur: str = "systeme") -> dict[str, Any]:
    """Crée le brouillon d'une pièce extraite. Idempotent : un seul brouillon par pièce.

    Ouvre sa propre transaction si l'appelant n'en a pas.
    """
    if conn.in_transaction:
        return _creer(conn, document_id, payload, acteur)
    with transaction(conn):
        return _creer(conn, document_id, payload, acteur)


def _creer(conn: sqlite3.Connection, document_id: str, payload: Mapping[str, Any],
           acteur: str) -> dict[str, Any]:
    existant = conn.execute(
        "SELECT id FROM invoice_drafts WHERE document=? ORDER BY cree_le LIMIT 1", (document_id,)
    ).fetchone()
    if existant:
        return resume(conn, existant["id"]) | {"deja_existant": True}

    clients = [dict(r) for r in conn.execute("SELECT * FROM clients")]
    articles = [dict(r) for r in conn.execute("SELECT * FROM items")]
    client = payload.get("client") or {}
    rattachement = match_client(clients, _valeur(client.get("name")), _valeur(client.get("ifu")))
    client_id = rattachement["client_id"] if rattachement["niveau"] in NIVEAUX_RATTACHEMENT_AUTO else None

    conditions = payload.get("payment_terms") or {}
    dates = payload.get("dates") or {}
    draft_id = new_id("drf")
    maintenant = horodatage()
    conn.execute(
        "INSERT INTO invoice_drafts(id, document, client, date_piece, date_echeance, conditions, "
        "version, statut, cree_le, modifie_le) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (draft_id, document_id, client_id, _valeur(dates.get("issue")), _valeur(dates.get("due")),
         _conditions(conn, _valeur(conditions.get("text")), _valeur(conditions.get("days"))),
         STATUT_BROUILLON, maintenant, maintenant),
    )

    creees, incompletes, deduites = 0, 0, 0
    for index, ligne in enumerate(payload.get("lines", [])):
        numero = int(ligne.get("line_no") or index + 1)
        valeurs, deduits = _deduire(ligne)
        description = _valeur(ligne.get("description"))
        unite = norm.normalize_unit(_valeur(ligne.get("unit"))) or _valeur(ligne.get("unit"))
        taux = _valeur(ligne.get("tax_rate"))
        manquants = [nom for nom, v in (("description", description), ("unit", unite),
                                         ("tax_rate", taux), *valeurs.items()) if v is None]
        chemin_ligne = f"lines[{index}]"
        if manquants:
            # Rien n'est inventé : la ligne attend qu'un humain la complète.
            _revue(conn, draft_id, LIGNE_INCOMPLETE, chemin_ligne, {
                "numero": numero, "manquants": manquants,
                "lu": {nom: _valeur(ligne.get(nom)) for nom in CHAMPS_LIGNE},
                "page": ligne.get("page"), "bbox": ligne.get("bbox"),
            })
            incompletes += 1
            continue
        correspondance = match_item(articles, str(description))
        conn.execute(
            "INSERT INTO draft_lines(id, draft, numero, description, quantite, unite, pu_ht, remise, "
            "remise_pct, tax_code, total_ht, item, famille) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (new_id("dl"), draft_id, numero, str(description), format(valeurs["quantity"], "f"), str(unite),
             int(valeurs["unit_price_ht"]), int(valeurs["discount"]), _code_fiscal(conn, taux),
             int(valeurs["line_total_ht"]), correspondance.get("item_id"), correspondance.get("famille")),
        )
        creees += 1
        for nom in deduits:
            deduites += 1
            _revue(conn, draft_id, VALEUR_DEDUITE, f"{chemin_ligne}.{nom}", {
                "numero": numero, "valeur": str(valeurs[nom]),
                "raison": "non lue sur la pièce, déduite des autres valeurs imprimées de la ligne",
                "page": ligne.get("page"), "bbox": ligne.get("bbox"),
            })
        livre = _valeur(ligne.get("delivered"))
        if livre is not None:
            conn.execute(
                "INSERT INTO deliveries(id, draft, numero, quantite_livree) VALUES (?, ?, ?, ?)",
                (new_id("liv"), draft_id, numero, str(livre)),
            )

    # Valeurs lues mais sous leur seuil : confirmation obligatoire (exiger_revue branché).
    a_confirmer = 0
    for chemin in extraction.exiger_revue(payload):
        objet = _objet(payload, chemin)
        if objet is None or (objet.get("missing") and (chemin in ABSENCES_COUVERTES
                                                       or chemin.startswith(("lines[", "totals.")))):
            # absences : MISSING_MANDATORY, LIGNE_INCOMPLETE ou VALEUR_DEDUITE s'en chargent ;
            # un total non imprimé n'a rien à confirmer.
            continue
        if chemin.startswith("totals.") and chemin.split(".")[-1] in ("ht", "vat", "ttc"):
            continue  # alias des totaux imprimés : déjà couverts par totals.printed_*
        _revue(conn, draft_id, CHAMP_A_CONFIRMER, chemin, {
            "valeur": objet.get("value"), "lu": objet.get("raw"),
            "confiance": objet.get("confidence"), "seuil": extraction.seuil(chemin.split(".")[-1]
                                                                           if chemin.startswith("lines")
                                                                           else chemin),
            "page": objet.get("page"), "bbox": objet.get("bbox"),
        })
        a_confirmer += 1

    append_event(conn, acteur, "BROUILLON_CREE", None, {
        "draft": draft_id, "document": document_id, "client": client_id,
        "niveau_client": rattachement["niveau"], "lignes": creees,
        "lignes_incompletes": incompletes, "valeurs_deduites": deduites, "a_confirmer": a_confirmer,
    })
    return resume(conn, draft_id) | {"niveau_client": rattachement["niveau"], "deja_existant": False}


def _objet(payload: Mapping[str, Any], chemin: str) -> Mapping[str, Any] | None:
    for nom, objet in extraction._parcours_champs(payload):
        if nom == chemin:
            return objet
    return None


# --------------------------------------------------------------------------
# Confirmations
# --------------------------------------------------------------------------

def a_confirmer(conn: sqlite3.Connection, draft_id: str) -> list[dict[str, Any]]:
    """Valeurs en attente d'une décision humaine pour ce brouillon."""
    lignes = conn.execute(
        "SELECT id, type, entite, motif, priorite FROM review_items "
        "WHERE entite LIKE ? AND resolution IS NULL ORDER BY priorite, entite",
        (f"{draft_id}|%",),
    ).fetchall()
    return [{"id": r["id"], "type": r["type"], "chemin": r["entite"].split("|", 1)[1],
             "priorite": r["priorite"], "details": json.loads(r["motif"])} for r in lignes]


def confirmer(conn: sqlite3.Connection, draft_id: str, chemin: str, acteur: str, *,
              motif: str = "", corrige: Any = None) -> None:
    """Un humain confirme une valeur (ou la corrige). Tracé au journal d'audit.

    Une correction d'une valeur de ligne met à jour la ligne du brouillon.
    Pour compléter une ligne incomplète, utiliser ``completer_ligne``.
    """
    if not str(acteur or "").strip():
        raise BrouillonError("une confirmation exige un acteur")
    with transaction(conn):
        item = conn.execute(
            "SELECT id, type, motif FROM review_items WHERE entite=? AND resolution IS NULL",
            (f"{draft_id}|{chemin}",),
        ).fetchone()
        if item is None:
            raise BrouillonError(f"rien à confirmer pour {chemin}")
        if item["type"] == LIGNE_INCOMPLETE:
            raise BrouillonError("ligne incomplète : utiliser completer_ligne")
        _exiger_brouillon(conn, draft_id)
        avant = json.loads(item["motif"]).get("valeur")
        if corrige is not None and chemin.startswith("lines["):
            _corriger_ligne(conn, draft_id, json.loads(item["motif"]).get("numero"), chemin, corrige)
        trace = {"acteur": acteur, "motif": motif, "avant": avant,
                 "apres": avant if corrige is None else corrige, "date": horodatage()}
        conn.execute("UPDATE review_items SET resolution=?, assigne=? WHERE id=?",
                     (json.dumps(trace, ensure_ascii=False, default=str), acteur, item["id"]))
        append_event(conn, acteur, "VALEUR_CONFIRMEE" if corrige is None else "VALEUR_CORRIGEE",
                     {"draft": draft_id, "champ": chemin, "valeur": avant},
                     {"draft": draft_id, "champ": chemin, "valeur": trace["apres"]})


COLONNES_LIGNE = {"quantity": "quantite", "unit_price_ht": "pu_ht", "discount": "remise",
                  "line_total_ht": "total_ht", "description": "description", "unit": "unite"}


def _corriger_ligne(conn: sqlite3.Connection, draft_id: str, numero: Any, chemin: str, valeur: Any) -> None:
    nom = chemin.split(".")[-1]
    colonne = COLONNES_LIGNE.get(nom)
    if colonne is None or numero is None:
        raise BrouillonError(f"champ de ligne non corrigeable ici : {chemin}")
    conn.execute(f"UPDATE draft_lines SET {colonne}=? WHERE draft=? AND numero=?",
                 (str(valeur) if colonne in ("quantite", "description", "unite") else int(valeur),
                  draft_id, int(numero)))
    conn.execute("UPDATE invoice_drafts SET version=version+1, modifie_le=? WHERE id=?",
                 (horodatage(), draft_id))


def completer_ligne(conn: sqlite3.Connection, draft_id: str, numero: int, valeurs: Mapping[str, Any],
                    acteur: str, motif: str = "") -> None:
    """Un humain fournit les valeurs manquantes d'une ligne incomplète ; la ligne est créée."""
    with transaction(conn):
        _exiger_brouillon(conn, draft_id)
        item = None
        for candidat in conn.execute(
            "SELECT id, motif FROM review_items WHERE type=? AND entite LIKE ? AND resolution IS NULL",
            (LIGNE_INCOMPLETE, f"{draft_id}|%"),
        ):
            if json.loads(candidat["motif"]).get("numero") == numero:
                item = candidat
        if item is None:
            raise BrouillonError(f"aucune ligne incomplète n° {numero}")
        lu = json.loads(item["motif"])["lu"]
        complet = {nom: valeurs.get(nom, lu.get(nom)) for nom in CHAMPS_LIGNE}
        absents = [nom for nom, v in complet.items() if v is None]
        if absents:
            raise BrouillonError(f"valeurs encore manquantes : {', '.join(absents)}")
        conn.execute(
            "INSERT INTO draft_lines(id, draft, numero, description, quantite, unite, pu_ht, remise, "
            "remise_pct, tax_code, total_ht) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (new_id("dl"), draft_id, numero, str(complet["description"]), str(complet["quantity"]),
             str(complet["unit"]), int(complet["unit_price_ht"]), int(complet["discount"]),
             _code_fiscal(conn, complet["tax_rate"]), int(complet["line_total_ht"])),
        )
        trace = {"acteur": acteur, "motif": motif, "avant": lu, "apres": complet, "date": horodatage()}
        conn.execute("UPDATE review_items SET resolution=?, assigne=? WHERE id=?",
                     (json.dumps(trace, ensure_ascii=False, default=str), acteur, item["id"]))
        append_event(conn, acteur, "LIGNE_COMPLETEE", {"draft": draft_id, "numero": numero, "lu": lu},
                     {"draft": draft_id, "numero": numero, "valeurs": complet})


def exiger_confirmations(conn: sqlite3.Connection, draft_id: str) -> None:
    """À appeler avant ``invoices.validate_draft`` : refuse s'il reste des valeurs à confirmer."""
    en_attente = a_confirmer(conn, draft_id)
    if en_attente:
        raise ConfirmationsEnAttente(en_attente)


def _exiger_brouillon(conn: sqlite3.Connection, draft_id: str) -> None:
    ligne = conn.execute("SELECT statut FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if ligne is None:
        raise BrouillonError(f"brouillon introuvable : {draft_id}")
    if ligne["statut"] not in (STATUT_BROUILLON, "CONTRÔLÉ"):
        raise BrouillonError(f"brouillon figé (statut {ligne['statut']}) : passer par un avoir")


def resume(conn: sqlite3.Connection, draft_id: str) -> dict[str, Any]:
    draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise BrouillonError(f"brouillon introuvable : {draft_id}")
    attente = a_confirmer(conn, draft_id)
    compte: dict[str, int] = {}
    for item in attente:
        compte[item["type"]] = compte.get(item["type"], 0) + 1
    return {
        "draft_id": draft_id, "document": draft["document"], "client": draft["client"],
        "statut": draft["statut"],
        "lignes": conn.execute("SELECT COUNT(*) FROM draft_lines WHERE draft=?", (draft_id,)).fetchone()[0],
        "a_confirmer": compte,
    }


def creer_pour_documents(conn: sqlite3.Connection, payloads: Iterable[tuple[str, Mapping[str, Any]]],
                         acteur: str = "systeme") -> list[dict[str, Any]]:
    return [creer_brouillon(conn, document_id, payload, acteur=acteur) for document_id, payload in payloads]
