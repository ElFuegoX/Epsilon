"""Adaptateur d'extraction : sortie contrainte par le schéma de domain/extraction.py.

``demo`` et ``cpu`` sont déterministes et hors ligne. ``cloud`` est un point
d'entrée optionnel : sans URL configurée il lève une exception, ce qui permet
au worker de laisser la pièce en ``EN_ATTENTE_IA`` au lieu d'inventer.

Le texte de la pièce est une donnée, jamais une instruction : aucun outil,
aucun calcul de TVA, aucune numérotation, aucune validation.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from config import settings
from domain.extraction import (
    BACKENDS,
    MODELE_DEMO,
    ExtractionInvalide,
    assembler,
    valider,
)

from . import ocr

REFERENCE_RE = re.compile(r"\b((?:DEV|CMD|BL|MSG|DEG|FAC|AV)-\d{4}-\d{3,5})\b", re.I)
CLIENT_RE = re.compile(r"(?:Client|Destinataire)\s*:\s*(.+?)(?:\s+IFU\s*:|$)", re.I)
IFU_RE = re.compile(r"\bIFU\s*:\s*([0-9][0-9\s]{5,12})(?:\D|$)", re.I)
DATE_RE = re.compile(r"\bDate\s*:\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I)
CONDITIONS_RE = re.compile(r"\bConditions\s*:\s*(.+?)(?:\s+TVA\s*:|$)", re.I)
LIGNE_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s+([a-zA-Z²]+)\s*[xX]\s*"
    r"([\d][\d\s'.,]*)\s*FCFA\s+Remise\s+([\d][\d\s'.,]*)\s*FCFA\s+"
    r"TVA\s*(\d+(?:[.,]\d+)?)\s*%\s+Total\s+([\d][\d\s'.,]*)\s*FCFA"
    r"(?:\s+Livre\s+(\d+(?:[.,]\d+)?))?",
    re.I,
)
TOTAL_HT_RE = re.compile(r"\bTotal\s+HT\s*(?:imprime)?\s*:\s*([\d][\d\s'.,]*)", re.I)
TOTAL_TVA_RE = re.compile(r"\bTVA\s*\d+(?:[.,]\d+)?\s*%\s*:\s*([\d][\d\s'.,]*)", re.I)
TOTAL_TTC_RE = re.compile(r"\bTotal\s+TTC\s*(?:imprime)?\s*:\s*([\d][\d\s'.,]*)", re.I)


class BackendIndisponible(RuntimeError):
    """Le backend demandé n'est pas joignable : aucune valeur de repli n'est inventée."""


def _trouver(blocs: Sequence[Mapping[str, Any]], motif: str) -> Mapping[str, Any] | None:
    expression = re.compile(motif, re.I)
    for bloc in blocs:
        if expression.search(str(bloc.get("text", ""))):
            return bloc
    return None


def _capturer(blocs: Sequence[Mapping[str, Any]], expression: re.Pattern[str],
              groupe: int = 1) -> tuple[str | None, Mapping[str, Any] | None]:
    for bloc in blocs:
        correspondance = expression.search(str(bloc.get("text", "")))
        if correspondance:
            return correspondance.group(groupe).strip(), bloc
    return None, None


def _item(brut: Any, bloc: Mapping[str, Any] | None, *, absent: bool = False,
          coherence: float | None = None) -> dict[str, Any]:
    signal = coherence if coherence is not None else (_coherence(bloc) if bloc else 0.92)
    return {"raw": brut, "bloc": bloc, "missing": absent, "coherence": float(signal)}


def classer(blocs: Sequence[Mapping[str, Any]], indice: str | None = None) -> str:
    """Classe la pièce par mots-clés ; l'indice de l'ingestion peut aider."""
    texte = " ".join(str(b.get("text", "")) for b in blocs).lower() + " " + (indice or "").lower()
    if "bon de livraison" in texte or "livraison" in texte and "bl-" in texte:
        return "bon_livraison"
    if "devis" in texte:
        return "devis"
    if "message" in texte or "whatsapp" in texte:
        return "message"
    return "commande"


def _coherence(bloc: Mapping[str, Any] | None) -> float:
    """Troisième signal : la qualité de la zone croise les deux autres."""
    confiance = float((bloc or {}).get("confidence", 0.0) or 0.0)
    return round(0.72 + 0.25 * confiance, 3)


def proposer(blocs: Sequence[Mapping[str, Any]], backend: str | None = None,
             doc_type_hint: str | None = None) -> dict[str, Any]:
    """Produit une proposition brute : valeurs lues + blocs d'origine.

    Aucun champ n'est comblé. Une valeur absente est marquée ``missing``
    avec le bloc du libellé, pour que la visionneuse puisse montrer l'endroit
    où la donnée devrait être.
    """
    backend = backend or settings.ai_backend
    if backend not in BACKENDS:
        raise BackendIndisponible(f"backend inconnu : {backend}")
    if backend == "cloud":
        return _proposer_cloud(blocs, doc_type_hint)

    type_piece = classer(blocs, doc_type_hint)
    champs: dict[str, Any] = {}

    reference, bloc_reference = _capturer(blocs, REFERENCE_RE)
    champs["reference"] = _item(reference, bloc_reference, absent=reference is None)

    client_brut, bloc_client = _capturer(blocs, CLIENT_RE)
    champs["client.name"] = _item(client_brut, bloc_client, absent=client_brut is None)
    ifu_brut, bloc_ifu = _capturer(blocs, IFU_RE)
    champs["client.ifu"] = _item(
        ifu_brut, bloc_ifu or _trouver(blocs, r"\bIFU\s*:"), absent=ifu_brut is None
    )
    champs["client.address"] = _item(None, None, absent=True)
    champs["client.phone"] = _item(None, None, absent=True)

    issue, bloc_issue = _capturer(blocs, DATE_RE)
    champs["dates.issue"] = _item(issue, bloc_issue, absent=issue is None)
    champs["dates.delivery"] = _item(None, _trouver(blocs, r"\bLivre\b"), absent=True)
    champs["dates.due"] = _item(None, _trouver(blocs, r"\bEcheance\b|\bÉchéance\b"), absent=True)

    conditions, bloc_conditions = _capturer(blocs, CONDITIONS_RE)
    champs["payment_terms.text"] = _item(
        conditions, bloc_conditions, absent=conditions is None
    )
    jours = None
    if conditions:
        correspondance = re.search(r"\d+\s*jours?", conditions, re.I)
        jours = correspondance.group(0) if correspondance else None
    champs["payment_terms.days"] = _item(jours, bloc_conditions, absent=jours is None)
    champs["payment_terms.method"] = _item(None, None, absent=True)

    lignes: list[dict[str, Any]] = []
    for bloc in blocs:
        texte = str(bloc.get("text", ""))
        correspondance = LIGNE_RE.match(texte)
        if not correspondance:
            continue
        numero, description, quantite, unite, prix, remise, tva, total, livre = correspondance.groups()
        coherence = _coherence(bloc)
        champs_ligne = {
            "description": _item(description, bloc, coherence=coherence),
            "quantity": _item(quantite, bloc, coherence=coherence),
            "unit": _item(unite, bloc, coherence=coherence),
            "unit_price_ht": _item(prix, bloc, coherence=coherence),
            "discount": _item(remise, bloc, coherence=coherence),
            "tax_rate": _item(tva, bloc, coherence=coherence),
            "line_total_ht": _item(total, bloc, coherence=coherence),
        }
        if livre is not None:
            champs_ligne["delivered"] = _item(livre, bloc, coherence=coherence)
        else:
            champs_ligne["delivered"] = _item(None, bloc, absent=True, coherence=coherence)
        lignes.append({"line_no": int(numero), "fields": champs_ligne})

    totaux: dict[str, Any] = {}
    for nom, expression in (
        ("printed_ht", TOTAL_HT_RE),
        ("printed_vat", TOTAL_TVA_RE),
        ("printed_ttc", TOTAL_TTC_RE),
    ):
        brut, bloc = _capturer(blocs, expression)
        totaux[nom] = _item(brut, bloc, absent=brut is None, coherence=_coherence(bloc))

    return {
        "backend": backend,
        "document_type": type_piece,
        "fields": champs,
        "lines": lignes,
        "totals": totaux,
        "confiance_modele": 0.96 if backend == "demo" else 0.90,
        "model": MODELE_DEMO,
    }


def _proposer_cloud(blocs: Sequence[Mapping[str, Any]], doc_type_hint: str | None) -> dict[str, Any]:
    url = os.getenv("WEMA_LLM_URL", "").strip()
    if not url:
        raise BackendIndisponible("AI_BACKEND=cloud sans WEMA_LLM_URL : aucun appel réel")
    corps = json.dumps(
        {"model": MODELE_DEMO, "doc_type_hint": doc_type_hint, "blocks": list(blocs)},
        ensure_ascii=False,
    ).encode("utf-8")
    en_tetes = {"Content-Type": "application/json"}
    cle = os.getenv("WEMA_LLM_KEY", "").strip()
    if cle:
        en_tetes["Authorization"] = f"Bearer {cle}"
    requete = urllib.request.Request(url, data=corps, headers=en_tetes, method="POST")
    try:
        with urllib.request.urlopen(requete, timeout=settings.ai_timeout_s) as reponse:
            proposition = json.loads(reponse.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise BackendIndisponible(f"service IA indisponible : {exc}") from exc
    for cle_requise in ("document_type", "fields", "lines", "totals"):
        if cle_requise not in proposition:
            raise ExtractionInvalide(f"réponse cloud sans {cle_requise}")
    return proposition


def extraire(chemin: str | Path, backend: str | None = None,
             doc_type_hint: str | None = None) -> dict[str, Any]:
    """Lit une pièce, produit un schéma valide ou lève une exception."""
    backend = backend or settings.ai_backend
    blocs = ocr.lire(chemin)
    if not blocs:
        raise ExtractionInvalide("aucun bloc OCR : extraction impossible")
    proposition = proposer(blocs, backend=backend, doc_type_hint=doc_type_hint)
    payload = assembler(proposition, backend=backend)
    resultat = valider(payload)
    if not resultat["valide"]:
        raise ExtractionInvalide("; ".join(resultat["problemes"]))
    return payload
