"""Extraction structurée et provenance.

L'IA lit et propose. Un champ absent reste null avec un motif : aucune
valeur « probable », aucun IFU deviné, aucun calcul, aucune validation.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from config import settings

ABSENT = "ABSENT_DE_LA_PIECE"
CHAMPS_FISCAUX = ("ifu", "tva", "total", "ttc", "ht", "tax_rate")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def combinee_confiance(ocr: float, modele: float, croisee: float) -> float:
    """Trois signaux, jamais la confiance auto-déclarée du seul modèle."""
    return round(0.30 * float(ocr) + 0.40 * float(modele) + 0.30 * float(croisee), 4)


def seuil(chemin: str) -> float:
    base = chemin.lower()
    if "numero" in base or "reference" in base and "facture" in base:
        return settings.confiance_numero
    if any(mot in base for mot in CHAMPS_FISCAUX):
        return settings.confiance_fiscal
    return settings.confiance_champ


def valeur(champ: Mapping[str, Any] | None) -> Any:
    """Renvoie None pour un champ absent, sans jamais le combler."""
    if not champ:
        return None
    if champ.get("missing"):
        return None
    return champ.get("value")


def verifier_schema(payload: Mapping[str, Any]) -> list[str]:
    """Contraintes structurelles : la sortie du modèle reste un schéma plat."""
    erreurs: list[str] = []
    for cle in ("document_type", "reference", "client", "dates", "payment_terms", "lines", "totals", "missing"):
        if cle not in payload:
            erreurs.append(f"champ racine absent: {cle}")
    if payload.get("document_type") not in ("devis", "commande", "bon_livraison", "message"):
        erreurs.append("document_type invalide")
    if not isinstance(payload.get("lines", []), list):
        erreurs.append("lines doit etre une liste")
    if not isinstance(payload.get("missing", []), list):
        erreurs.append("missing doit etre une liste")
    for ligne in payload.get("lines", []):
        for cle in ("description", "quantity", "unit", "unit_price_ht", "tax_rate", "line_total_ht"):
            if cle not in ligne:
                erreurs.append(f"ligne: champ absent {cle}")
    return erreurs


def verifier_provenance(payload: Mapping[str, Any]) -> list[str]:
    """Toute valeur non nulle doit pouvoir être montrée sur la pièce."""
    problemes: list[str] = []
    champs = [
        ("reference", payload.get("reference")),
        ("client.name", (payload.get("client") or {}).get("name")),
        ("client.ifu", (payload.get("client") or {}).get("ifu")),
    ]
    for ligne in payload.get("lines", []):
        champs.append((f"ligne {ligne.get('line_no')}", ligne))
    for chemin, champ in champs:
        if not isinstance(champ, Mapping):
            continue
        if champ.get("missing"):
            continue
        if champ.get("value") is None:
            continue
        source = champ.get("source") or {}
        if not source.get("page") or not source.get("bbox"):
            problemes.append(f"{chemin}: source manquante (page + bbox obligatoires)")
    return problemes


def verifier_non_invention(payload: Mapping[str, Any]) -> list[str]:
    """Un champ absent ne doit jamais recevoir de valeur."""
    problemes: list[str] = []
    client = payload.get("client") or {}
    for chemin, champ in (("ifu", client.get("ifu")), ("dates.due", (payload.get("dates") or {}).get("due"))):
        if isinstance(champ, Mapping) and champ.get("missing") and champ.get("value") is not None:
            problemes.append(f"{chemin}: valeur fournie alors que le champ est marque absent")
    if "ifu" in payload.get("missing", []) and client.get("ifu"):
        problemes.append("ifu: present dans client alors qu'il est declare manquant")
    return problemes


def valider(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Valide un JSON d'extraction et retourne la liste des problèmes."""
    problemes = verifier_schema(payload)
    problemes += verifier_provenance(payload)
    problemes += verifier_non_invention(payload)
    return {"valide": not problemes, "problemes": problemes, "payload": dict(payload)}
