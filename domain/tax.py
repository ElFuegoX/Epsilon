"""Moteur de calcul déterministe — fonction pure, sans réseau ni modèle.

- unité monétaire : entier FCFA, aucune décimale ;
- arrondi : demi-vers-le-haut, au niveau de la ligne, puis somme ;
- remise : avant TVA, montant ou pourcentage ;
- TVA : par ligne, selon le code fiscal (taux en points de base).

Le moteur ne corrige jamais silencieusement : il produit un résultat ET
les écarts avec les montants imprimés sur la pièce.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal(0)
    return Decimal(str(value).replace(" ", "").replace("\u00a0", ""))


def arrondi_fcfa(value: Any) -> int:
    """Arrondi demi-vers-le-haut au franc le plus proche."""
    return int(_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def demi_vers_le_haut(numerateur: int, denominateur: int) -> int:
    """Version entière de l'arrondi, testable sans flottant."""
    if denominateur == 0:
        raise ValueError("diviseur nul")
    return arrondi_fcfa(Decimal(numerateur) / Decimal(denominateur))


@dataclass(frozen=True)
class Ligne:
    description: str
    quantite: Any = 1
    unite: str = "pcs"
    pu_ht: int = 0
    remise: int = 0            # montant FCFA
    remise_pct: int = 0        # pourcentage entier, prioritaire sur remise
    taux_bp: int = 1800        # 18 % = 1800 points de base

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantite": str(_decimal(self.quantite)),
            "unite": self.unite,
            "pu_ht": self.pu_ht,
            "remise": self.remise,
            "remise_pct": self.remise_pct,
            "taux_bp": self.taux_bp,
        }


@dataclass(frozen=True)
class ResultatLigne:
    brut_ht: int
    remise: int
    net_ht: int
    tva: int
    total_ttc: int

    def to_dict(self) -> dict[str, int]:
        return {
            "brut_ht": self.brut_ht,
            "remise": self.remise,
            "net_ht": self.net_ht,
            "tva": self.tva,
            "total_ttc": self.total_ttc,
        }


@dataclass(frozen=True)
class ResultatCalcul:
    lignes: tuple[ResultatLigne, ...]
    total_ht: int
    total_tva: int
    total_ttc: int
    ecarts: Mapping[str, int] = field(default_factory=dict)
    hash_calcul: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lignes": [l.to_dict() for l in self.lignes],
            "total_ht": self.total_ht,
            "total_tva": self.total_tva,
            "total_ttc": self.total_ttc,
            "ecarts": dict(self.ecarts),
            "hash_calcul": self.hash_calcul,
        }


def calculer_ligne(ligne: Ligne) -> ResultatLigne:
    brut = _decimal(ligne.quantite) * _decimal(ligne.pu_ht)
    if ligne.remise_pct:
        remise = arrondi_fcfa(brut * _decimal(ligne.remise_pct) / Decimal(100))
    else:
        remise = int(ligne.remise)
    net = arrondi_fcfa(brut - remise)
    tva = arrondi_fcfa(Decimal(net) * Decimal(ligne.taux_bp) / Decimal(10000))
    return ResultatLigne(
        brut_ht=arrondi_fcfa(brut),
        remise=remise,
        net_ht=net,
        tva=tva,
        total_ttc=net + tva,
    )


def comparer(
    imprime: Mapping[str, Any] | None,
    calcule: Mapping[str, int],
    tolerance: int = 0,
) -> dict[str, int]:
    """Écart = imprimé − recalculé. Tolérance zéro FCFA par défaut."""
    if not imprime:
        return {}
    ecarts: dict[str, int] = {}
    for cle, cible in (("ht", "total_ht"), ("vat", "total_tva"), ("ttc", "total_ttc")):
        valeur = imprime.get(cle)
        if valeur is None:
            continue
        ecart = arrondi_fcfa(valeur) - calcule[cible]
        if abs(ecart) > tolerance:
            ecarts[cle] = ecart
    return ecarts


def calculer(
    lignes: Iterable[Ligne],
    imprime: Mapping[str, Any] | None = None,
    tolerance: int = 0,
) -> ResultatCalcul:
    """Calcule les totaux et les écarts. Aucun effet de bord, aucun modèle."""
    resultats = tuple(calculer_ligne(l) for l in lignes)
    total_ht = sum(r.net_ht for r in resultats)
    total_tva = sum(r.tva for r in resultats)
    total_ttc = total_ht + total_tva
    calc = {
        "total_ht": total_ht,
        "total_tva": total_tva,
        "total_ttc": total_ttc,
    }
    ecarts = comparer(imprime, calc, tolerance)
    payload = {
        "lignes": [l.to_dict() for l in lignes],
        "resultat": calc,
        "ecarts": ecarts,
    }
    h = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return ResultatCalcul(resultats, total_ht, total_tva, total_ttc, ecarts, h)


def lignes_depuis_dict(rows: Iterable[Mapping[str, Any]]) -> list[Ligne]:
    """Conversion des lignes de brouillon (quantité en texte décimal)."""
    return [
        Ligne(
            description=str(r.get("description", "")),
            quantite=r.get("quantite", 1),
            unite=str(r.get("unite", "pcs")),
            pu_ht=int(r.get("pu_ht", 0) or 0),
            remise=int(r.get("remise", 0) or 0),
            remise_pct=int(r.get("remise_pct", 0) or 0),
            taux_bp=int(r.get("taux_bp", 1800) or 1800),
        )
        for r in rows
    ]
