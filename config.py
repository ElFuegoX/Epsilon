"""Paramètres déterministes du prototype.

Aucune fonction du domaine ne doit appeler datetime.now() : la date de
référence est toujours AS_OF. Les montants sont des entiers FCFA.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VERSION = "1.1-bwai"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    as_of: str = os.getenv("AS_OF", "2026-11-25")
    devise: str = os.getenv("DEVISE", "XOF")
    arrondi: str = os.getenv("ARRONDI", "DEMI_VERS_LE_HAUT")
    graine_demo: int = _int("GRAINE_DEMO", 20261125)
    fuseau: str = os.getenv("FUSEAU", "Africa/Porto-Novo")

    ai_backend: str = os.getenv("AI_BACKEND", "demo")
    ai_timeout_s: int = _int("AI_TIMEOUT_S", 8)

    db_path: str = os.getenv("WEMA_DB", "data/wema.db")
    data_dir: str = os.getenv("WEMA_DATA", "data")

    seuil_dirigeant: int = _int("SEUIL_DIRIGEANT", 1_000_000)
    ecart_prix_pct: int = _int("ECART_PRIX_PCT", 10)
    confiance_champ: float = _float("CONFIANCE_CHAMP", 0.80)
    confiance_fiscal: float = _float("CONFIANCE_FISCAL", 0.90)
    confiance_numero: float = _float("CONFIANCE_NUMERO", 0.95)
    tolerance_arithmetique: int = _int("TOLERANCE_ARITHMETIQUE", 0)

    max_file_bytes: int = 20 * 1024 * 1024
    max_pages: int = 20
    allowed_mimes: tuple[str, ...] = (
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "text/plain",
    )
    annee: int = int(as_of[:4])
    conservation_annees: int = 10
    delai_reprise_ia_min: int = 5
    plafond_avoirs_pct: int = 100

    serie_defaut: str = "FAC"
    prefixe_facture: str = "FAC"
    prefixe_avoir: str = "AV"


settings = Settings()


def horodatage() -> str:
    """Horodatage déterministe : le domaine ne dépend jamais de l'horloge."""
    return f"{settings.as_of}T00:00:00Z"
