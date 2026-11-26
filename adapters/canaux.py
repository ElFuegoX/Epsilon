"""Canaux d'émission **simulés** : rien ne quitte la machine.

Un envoi écrit un message dans ``data/outbox/<canal>/<numero>.json`` : le
texte qui aurait été envoyé, le destinataire et le PDF joint. La démo peut
l'ouvrir pour montrer ce que le client aurait reçu.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from config import horodatage, settings


def _boite(canal: str) -> Path:
    dossier = Path(settings.data_dir) / "outbox" / canal
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _montant(valeur: Any) -> str:
    return f"{int(valeur):,}".replace(",", " ")


def envoyer(canal: str, facture: Mapping[str, Any], client: Mapping[str, Any] | None,
            pdf: str | None) -> dict[str, Any]:
    client = client or {}
    numero = facture["numero"]
    if canal == "whatsapp_sim":
        destinataire = client.get("telephone") or "— numéro absent du référentiel —"
        texte = (f"Bonjour {client.get('raison_sociale') or ''}, voici votre facture {numero} "
                 f"d'un montant de {_montant(facture['total_ttc'])} FCFA TTC. Merci. "
                 "[SIMULATION — aucun message réel envoyé]")
    elif canal == "email_sim":
        destinataire = client.get("email") or "— e-mail absent du référentiel —"
        texte = (f"Objet : Facture {numero}\n\nBonjour,\n\nVeuillez trouver ci-joint la facture {numero}, "
                 f"montant TTC {_montant(facture['total_ttc'])} FCFA.\n\nCordialement.\n\n"
                 "[SIMULATION — aucun e-mail réel envoyé]")
    elif canal == "telechargement":
        destinataire, texte = "téléchargement local", f"Facture {numero} téléchargée."
    else:
        raise ValueError(f"canal inconnu : {canal}")
    message = {"canal": canal, "numero": numero, "destinataire": destinataire, "texte": texte,
               "piece_jointe": pdf, "date": horodatage(), "simulation": True}
    chemin = _boite(canal) / f"{numero}.json"
    chemin.write_text(json.dumps(message, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**message, "fichier": str(chemin)}
