"""Moteur de calcul déterministe — fonction pure, sans réseau ni modèle.

- unité monétaire : entier FCFA, aucune décimale flottante ;
- arrondi : demi-vers-le-haut, au niveau de la ligne, puis somme ;
- taux : **jamais de défaut silencieux**. Il vient soit d'un code fiscal résolu
  depuis un référentiel passé en paramètre, soit d'un `taux_bp` explicitement
  fourni par l'appelant. Une ligne sans taux lève `TauxFiscalInconnu` ;
- remise : par ligne (montant ou pourcentage), puis remise globale répartie au
  prorata des brut par ligne (plus grand reste), le tout avant TVA ;
- TVA : calculée par ligne sur le net, selon le taux résolu.

Le moteur ne corrige jamais silencieusement : il produit un résultat ET les
écarts avec les montants imprimés sur la pièce. Écart = imprimé − recalculé.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


class TauxFiscalInconnu(ValueError):
    """Le taux d'une ligne n'a pas pu être résolu sans inventer de valeur."""


def _decimal(value: Any) -> Decimal:
    """Conversion stricte : jamais de flottant monétaire."""
    if isinstance(value, bool):
        raise TypeError("un booléen n'est pas un montant")
    if isinstance(value, float):
        raise TypeError("montant flottant interdit : utiliser un entier FCFA ou une chaîne décimale")
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
class CodeFiscal:
    """Entrée du référentiel fiscal fourni par l'appelant."""

    code: str
    taux_bp: int
    exoneration: bool = False


ReferentielFiscal = Mapping[str, CodeFiscal]


def resoudre_taux(code: Any, referentiel: ReferentielFiscal | None) -> CodeFiscal:
    """Résout un code fiscal. Aucun défaut : code absent => exception."""
    cle = str(code or "").strip()
    if not cle:
        raise TauxFiscalInconnu("code fiscal absent : aucun taux par défaut n'est appliqué")
    if not referentiel or cle not in referentiel:
        raise TauxFiscalInconnu(f"code fiscal « {cle} » absent du référentiel")
    return referentiel[cle]


@dataclass(frozen=True)
class Ligne:
    description: str
    quantite: Any = 1
    unite: str = "pcs"
    pu_ht: int = 0
    remise: int = 0            # montant FCFA
    remise_pct: int = 0        # pourcentage entier, prioritaire sur remise
    taux_bp: int | None = None  # taux explicitement résolu ; None = non résolu
    code_fiscal: str = ""

    def code_resolu(self, referentiel: ReferentielFiscal | None) -> CodeFiscal | None:
        if self.code_fiscal:
            return resoudre_taux(self.code_fiscal, referentiel)
        return None

    def taux_resolu(self, referentiel: ReferentielFiscal | None) -> int:
        code = self.code_resolu(referentiel)
        if code is not None:
            return int(code.taux_bp)
        if self.taux_bp is None:
            raise TauxFiscalInconnu(
                f"ligne « {self.description} » : ni code fiscal ni taux explicite"
            )
        return int(self.taux_bp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantite": str(_decimal(self.quantite)),
            "unite": self.unite,
            "pu_ht": self.pu_ht,
            "remise": self.remise,
            "remise_pct": self.remise_pct,
            "code_fiscal": self.code_fiscal,
            "taux_bp": self.taux_bp,
        }


@dataclass(frozen=True)
class ResultatLigne:
    brut_ht: int
    remise: int
    net_ht: int
    tva: int
    total_ttc: int
    remise_globale: int = 0
    taux_bp: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "brut_ht": self.brut_ht,
            "remise": self.remise,
            "remise_globale": self.remise_globale,
            "net_ht": self.net_ht,
            "taux_bp": self.taux_bp,
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
    remise_globale: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lignes": [l.to_dict() for l in self.lignes],
            "total_ht": self.total_ht,
            "total_tva": self.total_tva,
            "total_ttc": self.total_ttc,
            "ecarts": dict(self.ecarts),
            "hash_calcul": self.hash_calcul,
            "remise_globale": self.remise_globale,
        }


def repartir_remise_globale(montant: int, bruts: Iterable[int]) -> list[int]:
    """Répartit une remise globale au prorata des brut, plus grand reste.

    La somme des parts est exactement égale à `montant` (aucun FCFA perdu ni
    créé). Les départages sont résolus par l'ordre des lignes : déterministe.
    """
    bruts = tuple(int(b) for b in bruts)
    total = sum(bruts)
    if montant == 0 or total == 0:
        return [0] * len(bruts)
    if montant < 0:
        raise ValueError("remise globale négative")
    exacts = [Decimal(montant) * Decimal(b) / Decimal(total) for b in bruts]
    parts = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exacts]
    reste = montant - sum(parts)
    ordre = sorted(
        range(len(bruts)),
        key=lambda i: (exacts[i] - Decimal(parts[i]), -i),
        reverse=True,
    )
    for i in ordre[:reste]:
        parts[i] += 1
    return parts


def calculer_ligne(
    ligne: Ligne,
    referentiel: ReferentielFiscal | None = None,
    remise_globale: int = 0,
) -> ResultatLigne:
    """Calcule une ligne. Tous les montants retournés sont des entiers FCFA."""
    taux = ligne.taux_resolu(referentiel)
    brut = arrondi_fcfa(_decimal(ligne.quantite) * _decimal(ligne.pu_ht))
    remise_ligne = (
        arrondi_fcfa(Decimal(brut) * _decimal(ligne.remise_pct) / Decimal(100))
        if ligne.remise_pct
        else arrondi_fcfa(ligne.remise)
    )
    net = brut - remise_ligne - int(remise_globale)
    tva = arrondi_fcfa(Decimal(net) * Decimal(taux) / Decimal(10000))
    return ResultatLigne(
        brut_ht=brut,
        remise=remise_ligne,
        net_ht=net,
        tva=tva,
        total_ttc=net + tva,
        remise_globale=int(remise_globale),
        taux_bp=taux,
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
    remise_globale: int = 0,
    referentiel: ReferentielFiscal | None = None,
) -> ResultatCalcul:
    """Calcule les totaux et les écarts. Aucun effet de bord, aucun modèle."""
    lignes = tuple(lignes)
    bruts = tuple(arrondi_fcfa(_decimal(l.quantite) * _decimal(l.pu_ht)) for l in lignes)
    parts = repartir_remise_globale(remise_globale, bruts)
    resultats = tuple(
        calculer_ligne(l, referentiel=referentiel, remise_globale=p)
        for l, p in zip(lignes, parts)
    )
    total_ht = sum(r.net_ht for r in resultats)
    total_tva = sum(r.tva for r in resultats)
    total_ttc = total_ht + total_tva
    calc = {
        "total_ht": total_ht,
        "total_tva": total_tva,
        "total_ttc": total_ttc,
    }
    ecarts = comparer(imprime, calc, tolerance)
    charge = {
        "lignes": [l.to_dict() for l in lignes],
        "resultats": [r.to_dict() for r in resultats],
        "remise_globale": int(remise_globale),
        "totaux": calc,
        "ecarts": ecarts,
    }
    h = hashlib.sha256(
        json.dumps(charge, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return ResultatCalcul(
        lignes=resultats,
        total_ht=total_ht,
        total_tva=total_tva,
        total_ttc=total_ttc,
        ecarts=ecarts,
        hash_calcul=h,
        remise_globale=int(remise_globale),
    )


def lignes_depuis_dict(
    rows: Iterable[Mapping[str, Any]],
    referentiel: ReferentielFiscal | None = None,
) -> list[Ligne]:
    """Conversion des lignes de brouillon (quantité en texte décimal).

    Aucun taux par défaut : si ni `code_fiscal`/`tax_code` ni `taux_bp` ne sont
    fournis, le calcul lèvera `TauxFiscalInconnu`. Quand un référentiel est
    passé, la résolution est vérifiée immédiatement (fail fast).
    """
    lignes: list[Ligne] = []
    for r in rows:
        code = str(r.get("code_fiscal") or r.get("tax_code") or "").strip()
        brut_taux = r.get("taux_bp")
        taux_bp = None if brut_taux in (None, "") else arrondi_fcfa(brut_taux)
        ligne = Ligne(
            description=str(r.get("description", "")),
            quantite=r.get("quantite", 1),
            unite=str(r.get("unite", "pcs")),
            pu_ht=arrondi_fcfa(r.get("pu_ht", 0)),
            remise=arrondi_fcfa(r.get("remise", 0)),
            remise_pct=arrondi_fcfa(r.get("remise_pct", 0)),
            taux_bp=taux_bp,
            code_fiscal=code,
        )
        if referentiel is not None:
            ligne.taux_resolu(referentiel)
        lignes.append(ligne)
    return lignes
