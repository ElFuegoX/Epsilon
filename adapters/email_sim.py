"""Canal d'email simulé : journalise l'envoi sans aucun trafic réseau réel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from config import horodatage
from db import data_dir


def send_invoice_email(
    invoice: Mapping[str, Any],
    destinataire: str = "client@simulation.local",
) -> dict[str, Any]:
    """Enregistre une trace locale d'envoi email simulé."""
    outbox_dir = data_dir() / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    numero = str(invoice.get("numero") or invoice.get("id") or "inconnu")
    payload = {
        "canal": "email_sim",
        "simulation": True,
        "destinataire": destinataire,
        "objet": f"[SIMULATION WEMA] Facture {numero}",
        "corps": (
            f"Bonjour,\n\nVeuillez trouver ci-joint la facture {numero} "
            f"d'un montant TTC de {invoice.get('total_ttc', 0)} FCFA.\n"
            "Mention : SIMULATION - document de demonstration.\n"
        ),
        "invoice_id": invoice.get("id"),
        "numero": numero,
        "horodatage": horodatage(),
    }
    log_path: Path = outbox_dir / "email_sim.jsonl"
    with log_path.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload
