"""Primitives Choice / Noul / Score — substitution locale du « modèle Jev ».

Aucun SDK externe « TypeSafe AI / Jev » n'est présent dans le projet ni dans le
blueprint. Ce module formalise donc les trois primitives citées avec la sémantique
déjà retenue pour WÉMA :

* ``Choice`` : arbitrage entre lectures candidates, sans jamais en inventer ;
* ``Noul`` : absence explicite, équivalent de ``ABSENT_DE_LA_PIECE`` ;
* ``Score`` : confiance calculée à partir de trois signaux, avec calibration
  optionnelle par ``logprobs`` quand le fournisseur en fournit réellement.

Si une vraie implémentation Jev est branchée plus tard, elle peut remplacer ce
module sans changer les appelants.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

ABSENT = "ABSENT_DE_LA_PIECE"
POIDS_OCR = 0.30
POIDS_MODELE = 0.40
POIDS_CROISE = 0.30
POIDS_LOGPROBS = 0.15


@dataclass(frozen=True)
class Noul:
    """Valeur absente, avec motif. Ne porte jamais de valeur de repli."""

    motif: str = ABSENT

    @property
    def value(self) -> None:
        return None

    def comme_champ(self, page: int = 1, bbox: Sequence[float] | None = None,
                    method: str = "llm") -> dict[str, Any]:
        return {
            "value": None,
            "value_normalized": None,
            "raw": None,
            "confidence": 0.0,
            "page": int(page or 1),
            "bbox": [float(v) for v in (bbox or [0.0, 0.0, 0.0, 0.0])],
            "method": method,
            "missing": self.motif,
            "motif": self.motif,
        }


@dataclass(frozen=True)
class Choice:
    """Arbitrage déterministe entre candidats ``(valeur, score)``."""

    candidats: tuple[tuple[Any, float], ...]
    seuil: float = 0.0

    @classmethod
    def depuis(cls, candidats: Iterable[tuple[Any, float]], seuil: float = 0.0) -> "Choice":
        return cls(tuple((valeur, float(score)) for valeur, score in candidats), float(seuil))

    def resoudre(self) -> Any | Noul:
        if not self.candidats:
            return Noul()
        valeur, score = max(self.candidats, key=lambda item: item[1])
        if score <= self.seuil:
            return Noul()
        return valeur

    @property
    def marge(self) -> float:
        if len(self.candidats) < 2:
            return 1.0
        tries = sorted((float(s) for _, s in self.candidats), reverse=True)
        return round(tries[0] - tries[1], 4)


def _borne(valeur: float) -> float:
    return max(0.0, min(1.0, float(valeur)))


def calibrer_logprobs(logprobs: Any) -> float | None:
    """Convertit des log-probabilités en probabilité moyenne, ou None.

    Une absence de logprobs n'est jamais remplacée par une valeur par défaut :
    on renvoie ``None`` et ``Score`` garde alors la formule à trois signaux.
    """
    if logprobs is None:
        return None
    valeurs: list[float] = []
    if isinstance(logprobs, Mapping):
        for cle in ("mean", "moyenne", "logprob", "logprobs_moyen"):
            if cle in logprobs:
                try:
                    return _borne(math.exp(float(logprobs[cle])))
                except (TypeError, ValueError, OverflowError):
                    return None
        brut = logprobs.get("token_logprobs") or logprobs.get("tokens") or []
        for item in brut:
            if isinstance(item, Mapping):
                item = item.get("logprob")
            try:
                valeurs.append(float(item))
            except (TypeError, ValueError):
                continue
    elif isinstance(logprobs, (list, tuple)):
        for item in logprobs:
            if isinstance(item, Mapping):
                item = item.get("logprob")
            try:
                valeurs.append(float(item))
            except (TypeError, ValueError):
                continue
    else:
        try:
            return _borne(math.exp(float(logprobs)))
        except (TypeError, ValueError, OverflowError):
            return None
    if not valeurs:
        return None
    try:
        return _borne(math.exp(sum(valeurs) / len(valeurs)))
    except (OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class Score:
    """Confiance : OCR 30 %, modèle 40 %, croisement 30 %.

    Si des logprobs réels sont fournis, ils pèsent 15 % et les trois signaux
    historiques 85 %. Sans logprobs, le résultat est identique à la formule
    utilisée depuis le début du projet.
    """

    ocr: float
    modele: float
    croise: float
    logprobs: float | None = None

    @property
    def base(self) -> float:
        return POIDS_OCR * _borne(self.ocr) + POIDS_MODELE * _borne(self.modele) + POIDS_CROISE * _borne(self.croise)

    @property
    def valeur(self) -> float:
        probabilite = calibrer_logprobs(self.logprobs) if self.logprobs is not None else None
        if probabilite is None:
            return round(self.base, 4)
        return round((1 - POIDS_LOGPROBS) * self.base + POIDS_LOGPROBS * probabilite, 4)
