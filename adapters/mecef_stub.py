"""Code MECeF et QR **factices**.

En production, le code et le QR d'une facture normalisée sont délivrés par la
DGI via un SFE agréé. WÉMA n'est pas agréé : il fabrique ici une valeur
visiblement fictive, dérivée du contenu figé de la facture, pour montrer
l'emplacement des mentions. Rien n'est transmis à qui que ce soit.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

PREFIXE = "SIMULATION-MECEF"


def code_mecef(numero: str, snapshot: Mapping[str, Any]) -> str:
    """Code factice, stable pour un même snapshot (le PDF reste reproductible)."""
    from domain.extraction import canonical

    empreinte = hashlib.sha256(canonical(dict(snapshot)).encode("utf-8")).hexdigest()
    return f"{PREFIXE}-{numero}-{empreinte[:12].upper()}"


def contenu_qr(numero: str, snapshot: Mapping[str, Any]) -> str:
    """Contenu du QR factice : il annonce lui-même qu'il n'a aucune valeur fiscale."""
    calcul = snapshot.get("calcul") or {}
    return (f"SIMULATION WEMA - SANS VALEUR FISCALE | {numero} | TTC {calcul.get('total_ttc')} "
            f"{snapshot.get('devise', 'XOF')} | {code_mecef(numero, snapshot)}")
