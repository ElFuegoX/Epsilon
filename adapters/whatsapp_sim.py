"""Canal WhatsApp simulé : le message est écrit dans data/outbox/whatsapp_sim/, jamais envoyé."""

from __future__ import annotations

from typing import Any, Mapping

from .canaux import envoyer as _envoyer


def envoyer(facture: Mapping[str, Any], client: Mapping[str, Any] | None, pdf: str | None) -> dict[str, Any]:
    return _envoyer("whatsapp_sim", facture, client, pdf)
