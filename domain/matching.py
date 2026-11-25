"""Rapprochement tolérant mais jamais silencieux (niveaux C1 à C5)."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from .normalization import normalize_text

BLOQUANT = "BLOQUANT"


def similarite(a: str, b: str) -> float:
    return round(SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio(), 4)


def match_client(
    clients: Sequence[Mapping[str, Any]],
    nom: str | None,
    ifu: str | None = None,
    telephone: str | None = None,
    ville: str | None = None,
) -> dict[str, Any]:
    """C1 à C5. Aucun rattachement sur IFU absent ni sur homonyme douteux."""
    if not nom and not ifu:
        return {"client_id": None, "niveau": "C5", "confiance": 0.0, "action": "CREATION_DIRIGEANT"}

    if ifu:
        for c in clients:
            if c.get("ifu") and str(c["ifu"]).strip() == str(ifu).strip():
                return {
                    "client_id": c["id"], "niveau": "C1", "confiance": 1.0,
                    "action": "RATTACHEMENT_AUTO",
                }

    nom_norm = normalize_text(nom)
    for c in clients:
        if nom_norm and normalize_text(c.get("raison_sociale")) == nom_norm:
            if not ville or not c.get("ville") or normalize_text(ville) == normalize_text(c["ville"]):
                return {
                    "client_id": c["id"], "niveau": "C2", "confiance": 0.95,
                    "action": "RATTACHEMENT_AUTO_JOURNALISE",
                }

    if telephone:
        for c in clients:
            if c.get("telephone") and str(c["telephone"]).strip() == str(telephone).strip():
                if similarite(nom or "", c.get("raison_sociale", "")) >= 0.70:
                    return {
                        "client_id": c["id"], "niveau": "C3", "confiance": 0.80,
                        "action": "SUGGESTION_A_CONFIRMER",
                    }

    candidats = [c for c in clients if similarite(nom or "", c.get("raison_sociale", "")) >= 0.85]
    if candidats:
        return {
            "client_id": None, "niveau": "C4", "confiance": 0.50,
            "action": "REVUE_HUMAINE", "candidats": [c["id"] for c in candidats],
        }

    return {"client_id": None, "niveau": "C5", "confiance": 0.0, "action": "CREATION_DIRIGEANT"}


def match_item(
    items: Sequence[Mapping[str, Any]],
    description: str,
    famille: str | None = None,
) -> dict[str, Any]:
    """Les prestations sur mesure restent libres, rattachées à une famille."""
    for item in items:
        if normalize_text(description) == normalize_text(item.get("designation")):
            return {"item_id": item["id"], "famille": item.get("famille"), "confiance": 1.0}
    candidats = sorted(
        ((similarite(description, i.get("designation", "")), i) for i in items),
        key=lambda t: t[0],
        reverse=True,
    )
    if candidats and candidats[0][0] >= 0.85:
        item = candidats[0][1]
        return {"item_id": None, "famille": item.get("famille"), "confiance": 0.50,
                "action": "SUGGESTION_A_CONFIRMER"}
    if famille:
        return {"item_id": None, "famille": famille, "confiance": 0.30, "action": "LIGNE_LIBRE_JUSTIFIEE"}
    return {"item_id": None, "famille": None, "confiance": 0.0, "action": "A_RATTACHER"}
