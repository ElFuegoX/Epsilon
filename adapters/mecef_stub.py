"""Stub e-MECeF : faux code et faux QR clairement marqués SIMULATION.

Aucun appel réel à la DGI, aucun agrément revendiqué.
"""

from __future__ import annotations

import hashlib
from typing import Any

from config import settings


def generate_mecef_stub(numero: str, total_ttc: int) -> dict[str, Any]:
    """Produit une référence e-MECeF factice et déterministe pour la démo."""
    seed_str = f"SIM-MECEF|{numero}|{total_ttc}|{settings.as_of}"
    digest = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:16].upper()
    code = f"SIM-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"
    return {
        "simulation": True,
        "code_mecef": code,
        "nim": "SIM-NIM-000000",
        "qr_payload": f"SIMULATION|WEMA|{numero}|{total_ttc}|{code}",
        "mention": "SIMULATION - Aucun appel DGI, non valide fiscalement",
    }
