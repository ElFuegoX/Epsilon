"""Canal WhatsApp simulé et générateur de message de clarification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import horodatage
from db import data_dir


def build_clarification_message(
    reference: str | None,
    champs_manquants: Iterable[str],
    client_nom: str | None = None,
) -> str:
    """Génère un message WhatsApp prêt à copier pour les champs absents."""
    manquants = [c for c in champs_manquants if c]
    ref_txt = f" concernant la pièce {reference}" if reference else ""
    salutation = f"Bonjour {client_nom}," if client_nom else "Bonjour,"
    if not manquants:
        return (
            f"{salutation} nous préparons votre facture{ref_txt}. "
            "Toutes les mentions obligatoires sont bien présentes. Merci !"
        )
    liste = ", ".join(manquants)
    return (
        f"{salutation} pour finaliser votre facture{ref_txt}, "
        f"il nous manque les informations suivantes : {liste}. "
        "Pouvez-vous nous les transmettre afin que nous puissions émettre la facture exacte ? "
        "Merci d'avance."
    )


def send_invoice_whatsapp(
    invoice: Mapping[str, Any],
    telephone: str = "+22900000000",
) -> dict[str, Any]:
    """Enregistre une trace locale d'envoi WhatsApp simulé."""
    outbox_dir = data_dir() / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    numero = str(invoice.get("numero") or invoice.get("id") or "inconnu")
    payload = {
        "canal": "whatsapp_sim",
        "simulation": True,
        "telephone": telephone,
        "message": (
            f"[SIMULATION WEMA] Facture {numero} prête — "
            f"Total TTC : {invoice.get('total_ttc', 0)} FCFA. "
            f"Réf. Mobile Money fictive : MOMO-{numero}."
        ),
        "invoice_id": invoice.get("id"),
        "numero": numero,
        "horodatage": horodatage(),
    }
    log_path: Path = outbox_dir / "whatsapp_sim.jsonl"
    with log_path.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload
