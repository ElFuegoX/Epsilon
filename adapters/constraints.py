"""Couche de contrainte de sortie : schéma, réparation et logprobs.

Le blueprint demande un « LLM contraint par schéma ». On le tient ici sans
dépendance obligatoire : la proposition est validée avant assemblage, les
incohérences structurales sont réparées **sans inventer de valeur**, puis
`domain/extraction.py` refait une validation finale.

Un backend de décodage réel (``outlines``, ``llguidance``, ``xgrammar``,
``NuExtract``) peut être demandé par ``WEMA_CONSTRAINT_BACKEND``. S'il n'est
pas installé, on échoue explicitement au lieu de prétendre l'utiliser.
"""

from __future__ import annotations

import copy
import importlib.util
import os
from typing import Any, Mapping

from domain.jev import calibrer_logprobs

CHAMPS_TETE = {
    "reference", "client.name", "client.ifu", "client.address", "client.phone",
    "dates.issue", "dates.delivery", "dates.due",
    "payment_terms.text", "payment_terms.days", "payment_terms.method",
}
CHAMPS_LIGNE = {
    "description", "quantity", "unit", "unit_price_ht", "discount",
    "tax_rate", "line_total_ht", "delivered",
}
TOTAUX = {"ht", "vat", "ttc", "printed_ht", "printed_vat", "printed_ttc"}
TYPES_DOCUMENT = {"devis", "commande", "bon_livraison", "message"}
BACKENDS = ("auto", "outlines", "llguidance", "xgrammar", "nuxextract", "nuextract")


class ContrainteIndisponible(RuntimeError):
    """Le backend de décodage contraint demandé n'est pas installé."""


class PropositionInvalide(RuntimeError):
    """La proposition ne peut pas être réparée sans inventer de donnée."""


def _est_item(valeur: Any) -> bool:
    return isinstance(valeur, Mapping) and {"raw", "bloc", "missing"}.issubset(valeur.keys())


def _item_absent() -> dict[str, Any]:
    """Item vide explicite : aucune valeur, aucun bloc deviné."""
    return {"raw": None, "bloc": None, "missing": True, "coherence": 0.92}


def valider(proposition: Mapping[str, Any]) -> list[str]:
    problemes: list[str] = []
    for cle in ("document_type", "fields", "lines", "totals"):
        if cle not in proposition:
            problemes.append(f"racine: {cle} absent")
    if proposition.get("document_type") not in TYPES_DOCUMENT:
        problemes.append("document_type invalide")
    champs = proposition.get("fields")
    if not isinstance(champs, Mapping):
        problemes.append("fields doit etre un objet")
    else:
        for cle in champs:
            if cle not in CHAMPS_TETE:
                problemes.append(f"champ inconnu: {cle}")
            elif not _est_item(champs[cle]):
                problemes.append(f"champ mal forme: {cle}")
    lignes = proposition.get("lines")
    if not isinstance(lignes, list):
        problemes.append("lines doit etre une liste")
    else:
        for index, ligne in enumerate(lignes):
            if not isinstance(ligne, Mapping):
                problemes.append(f"ligne {index} mal formee")
                continue
            if not isinstance(ligne.get("line_no"), int):
                problemes.append(f"ligne {index}: line_no invalide")
            champs_ligne = ligne.get("fields")
            if not isinstance(champs_ligne, Mapping):
                problemes.append(f"ligne {index}: fields absent")
                continue
            for cle in champs_ligne:
                if cle not in CHAMPS_LIGNE:
                    problemes.append(f"ligne {index}: champ inconnu {cle}")
                elif not _est_item(champs_ligne[cle]):
                    problemes.append(f"ligne {index}: champ mal forme {cle}")
    totaux = proposition.get("totals")
    if not isinstance(totaux, Mapping):
        problemes.append("totals doit etre un objet")
    else:
        for cle in totaux:
            if cle not in TOTAUX:
                problemes.append(f"total inconnu: {cle}")
            elif not _est_item(totaux[cle]):
                problemes.append(f"total mal forme: {cle}")
    return problemes


def reparer(proposition: Mapping[str, Any], problemes: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Remet la proposition en forme. Aucune valeur n'est créée."""
    propre = copy.deepcopy(dict(proposition))
    reparations: list[str] = []

    champs = propre.get("fields")
    if isinstance(champs, Mapping):
        for cle in list(champs):
            if cle not in CHAMPS_TETE:
                champs.pop(cle)
                reparations.append(f"champ inconnu retire: {cle}")
            elif not _est_item(champs[cle]):
                champs[cle] = _item_absent()
                reparations.append(f"champ mal forme remplace par absent: {cle}")
        for cle in sorted(CHAMPS_TETE - set(champs)):
            champs[cle] = _item_absent()
            reparations.append(f"champ absent ajoute explicitement: {cle}")

    lignes = propre.get("lines")
    if isinstance(lignes, list):
        lignes_propres: list[dict[str, Any]] = []
        for index, ligne in enumerate(lignes):
            if not isinstance(ligne, Mapping) or not isinstance(ligne.get("line_no"), int):
                reparations.append(f"ligne {index} retiree : numero invalide")
                continue
            copie = copy.deepcopy(dict(ligne))
            champs_ligne = copie.get("fields")
            if not isinstance(champs_ligne, Mapping):
                copie["fields"] = {}
                champs_ligne = copie["fields"]
            for cle in list(champs_ligne):
                if cle not in CHAMPS_LIGNE:
                    champs_ligne.pop(cle)
                    reparations.append(f"ligne {ligne['line_no']}: champ inconnu retire {cle}")
                elif not _est_item(champs_ligne[cle]):
                    champs_ligne[cle] = _item_absent()
                    reparations.append(f"ligne {ligne['line_no']}: champ mal forme remplace par absent {cle}")
            lignes_propres.append(copie)
        propre["lines"] = lignes_propres

    totaux = propre.get("totals")
    if isinstance(totaux, Mapping):
        for cle in list(totaux):
            if cle not in TOTAUX:
                totaux.pop(cle)
                reparations.append(f"total inconnu retire: {cle}")
            elif not _est_item(totaux[cle]):
                totaux[cle] = _item_absent()
                reparations.append(f"total mal forme remplace par absent: {cle}")
        for cle in sorted(TOTAUX - set(totaux)):
            totaux[cle] = _item_absent()
            reparations.append(f"total absent ajoute explicitement: {cle}")

    restants = [p for p in problemes if "document_type" in p or "racine" in p or "lines doit" in p or "fields doit" in p or "totals doit" in p]
    return propre, reparations + restants


def backend_demande() -> str:
    return os.getenv("WEMA_CONSTRAINT_BACKEND", "auto").strip().lower() or "auto"


def verifier_backend(nom: str | None = None) -> str:
    """Vérifie qu'un backend de décodage contraint est réellement disponible."""
    backend = (nom or backend_demande()).lower()
    if backend not in BACKENDS:
        raise ContrainteIndisponible(f"backend de contrainte inconnu: {backend}")
    if backend == "auto":
        return backend
    module = {"outlines": "outlines", "llguidance": "llguidance",
              "xgrammar": "xgrammar", "nuxextract": "nuxextract",
              "nuextract": "nuxextract"}[backend]
    if importlib.util.find_spec(module) is None:
        raise ContrainteIndisponible(f"{backend} demande mais non installe")
    return backend


def appliquer(proposition: Mapping[str, Any], backend: str | None = None,
              logprobs: Any = None) -> dict[str, Any]:
    """Valide, répare sans inventer, et joint un rapport de contrainte."""
    choix_backend = verifier_backend(backend)
    problemes = valider(proposition)
    propre, reparations = reparer(proposition, problemes)
    restants = valider(propre)
    if restants:
        raise PropositionInvalide("; ".join(restants))
    probabilite = calibrer_logprobs(logprobs)
    propre["constraint_report"] = {
        "backend": choix_backend,
        "schema": "wema-extraction-1.0",
        "problemes_initiaux": problemes,
        "reparations": reparations,
        "logprobs_present": probabilite is not None,
        "logprobs_calibres": probabilite,
    }
    return propre
