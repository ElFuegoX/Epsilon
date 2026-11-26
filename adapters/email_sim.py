"""Canal e-mail simulé : le message est écrit dans data/outbox/email_sim/, jamais envoyé."""

from __future__ import annotations

from typing import Any, Mapping

from .canaux import envoyer as _envoyer


def envoyer(facture: Mapping[str, Any], client: Mapping[str, Any] | None, pdf: str | None) -> dict[str, Any]:
    return _envoyer("email_sim", facture, client, pdf)
