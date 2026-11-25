"""Extraction structurée et provenance.

L'IA lit et propose. Un champ absent reste null avec un motif : aucune
valeur « probable », aucun IFU deviné, aucun calcul, aucune validation.

Contrat de sortie (schéme annexe A du blueprint) : chaque champ non nul
porte ``value``, ``value_normalized``, ``confidence``, ``page``, ``bbox``
et ``method``. ``bbox`` est en pourcentage de page ``[x, y, w, h]``,
compatible avec la visionneuse React.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from config import settings

from . import normalization as norm
from .jev import Noul, Score

ABSENT = "ABSENT_DE_LA_PIECE"
SCHEMA_VERSION = "1.0"
MODELE_DEMO = "wema-extract-demo-20261125"
BACKENDS = ("demo", "cpu", "cloud")
CHAMPS_FISCAUX = ("ifu", "tva", "vat", "total", "ttc", "ht", "tax_rate", "unit_price_ht")
CHAMPS_NUMERO = ("reference", "numero", "numero_facture")


class ExtractionInvalide(RuntimeError):
    """Le schéma contraint n'a pas été respecté : rien n'est conservé."""


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def combinee_confiance(ocr: float, modele: float, croisee: float,
                       logprobs: Any = None) -> float:
    """Trois signaux, jamais la confiance auto-déclarée du seul modèle."""
    return Score(float(ocr), float(modele), float(croisee), logprobs=logprobs).valeur


def seuil(chemin: str) -> float:
    base = chemin.lower()
    if any(mot in base for mot in CHAMPS_NUMERO):
        return settings.confiance_numero
    if any(mot in base for mot in CHAMPS_FISCAUX):
        return settings.confiance_fiscal
    return settings.confiance_champ


def valeur(champ: Mapping[str, Any] | None) -> Any:
    """Renvoie None pour un champ absent, sans jamais le combler."""
    if not champ:
        return None
    if champ.get("missing"):
        return None
    return champ.get("value")


def _source(bloc: Mapping[str, Any] | None) -> tuple[int, list[float], float]:
    if not bloc:
        return 1, [0.0, 0.0, 0.0, 0.0], 0.0
    bbox = bloc.get("bbox") or [0.0, 0.0, 0.0, 0.0]
    if len(bbox) != 4:
        bbox = [0.0, 0.0, 0.0, 0.0]
    return int(bloc.get("page", 1) or 1), [float(v) for v in bbox], float(bloc.get("confidence", 0.0) or 0.0)


def champ(
    brut: Any,
    bloc: Mapping[str, Any] | None,
    *,
    confiance_modele: float = 0.92,
    coherence: float = 0.92,
    normaliseur: Callable[[Any], Any] | None = None,
    absent: bool = False,
    logprobs: Any = None,
) -> dict[str, Any]:
    """Construit un champ contraint, ou un champ absent explicite."""
    page, bbox, confiance_ocr = _source(bloc)
    if absent or brut is None:
        return Noul(ABSENT).comme_champ(page=page, bbox=bbox, method="llm")
    normalise = normaliseur or (lambda v: v)
    try:
        normalise_valeur = normalise(brut)
    except (TypeError, ValueError):
        normalise_valeur = None
    if normalise_valeur is None:
        # Une écriture ambiguë n'est pas une valeur : on demande une revue.
        return champ(None, bloc, absent=True)
    return {
        "value": normalise_valeur,
        "value_normalized": normalise_valeur,
        "raw": brut,
        "confidence": combinee_confiance(confiance_ocr, confiance_modele, coherence, logprobs=logprobs),
        "page": page,
        "bbox": bbox,
        "method": "ocr+llm+croise",
    }


def _texte(brut: Any) -> str | None:
    if brut is None:
        return None
    texte = str(brut).strip()
    return texte or None


def _ifu(brut: Any) -> str | None:
    if brut is None:
        return None
    texte = re.sub(r"\s+", "", str(brut))
    return texte if re.fullmatch(r"\d{6,13}", texte) else None


def _jours(brut: Any) -> int | None:
    if brut is None:
        return None
    correspondance = re.search(r"\d+", str(brut))
    return int(correspondance.group(0)) if correspondance else None


def _pourcent_tva(brut: Any) -> int | None:
    texte = str(brut).strip()
    if "%" not in texte:
        texte += " %"  # un taux lu sans symbole reste un taux, pas une fraction
    points = norm.normalize_tax(texte)
    return None if points is None else int(points / 100)


def NORMALISEURS(champ: str) -> Callable[[Any], Any]:
    """Normaliseurs déterministes, sans calcul fiscal."""
    table: dict[str, Callable[[Any], Any]] = {
        "reference": _texte,
        "client.name": _texte,
        "client.ifu": _ifu,
        "client.address": _texte,
        "client.phone": _texte,
        "dates.issue": norm.normalize_date,
        "dates.delivery": norm.normalize_date,
        "dates.due": norm.normalize_date,
        "payment_terms.text": _texte,
        "payment_terms.days": _jours,
        "payment_terms.method": _texte,
        "description": _texte,
        "quantity": norm.normalize_quantity,
        "unit": norm.normalize_unit,
        "unit_price_ht": norm.normalize_amount,
        "discount": norm.normalize_amount,
        "tax_rate": _pourcent_tva,
        "line_total_ht": norm.normalize_amount,
        "delivered": norm.normalize_quantity,
        "ht": norm.normalize_amount,
        "vat": norm.normalize_amount,
        "ttc": norm.normalize_amount,
        "printed_ht": norm.normalize_amount,
        "printed_vat": norm.normalize_amount,
        "printed_ttc": norm.normalize_amount,
    }
    return table.get(champ, _texte)


def assembler(proposition: Mapping[str, Any], backend: str = "demo") -> dict[str, Any]:
    """Transforme une proposition brute en schéma contraint et validable.

    La proposition est produite par ``adapters.llm.proposer`` : elle contient
    des valeurs brutes et le bloc OCR d'origine, jamais de confiance finale
    ni de montant calculé.
    """
    confiance_modele = float(proposition.get("confiance_modele", 0.92))
    logprobs_global = proposition.get("logprobs")

    def convertir(item: Mapping[str, Any] | None, chemin: str) -> dict[str, Any]:
        if not item:
            return champ(None, None, absent=True)
        return champ(
            item.get("raw"),
            item.get("bloc"),
            confiance_modele=confiance_modele,
            coherence=float(item.get("coherence", 0.92)),
            normaliseur=NORMALISEURS(chemin),
            absent=bool(item.get("missing")),
            logprobs=item.get("logprobs", logprobs_global),
        )

    champs = proposition.get("fields", {})
    client = {nom: convertir(champs.get(f"client.{nom}"), f"client.{nom}")
              for nom in ("name", "ifu", "address", "phone")}
    dates = {nom: convertir(champs.get(f"dates.{nom}"), f"dates.{nom}")
             for nom in ("issue", "delivery", "due")}
    conditions = {nom: convertir(champs.get(f"payment_terms.{nom}"), f"payment_terms.{nom}")
                  for nom in ("text", "days", "method")}

    lignes: list[dict[str, Any]] = []
    for brut_ligne in proposition.get("lines", []):
        donnees = brut_ligne.get("fields", {})
        ligne: dict[str, Any] = {"line_no": int(brut_ligne.get("line_no", len(lignes) + 1))}
        for nom in ("description", "quantity", "unit", "unit_price_ht", "discount",
                    "tax_rate", "line_total_ht", "delivered"):
            if nom in donnees:
                ligne[nom] = convertir(donnees[nom], nom)
        ligne["page"], ligne["bbox"], ligne["confidence"] = _source(
            donnees.get("description", {}).get("bloc")
        )
        ligne["method"] = "ocr+llm+croise"
        lignes.append(ligne)

    totaux: dict[str, Any] = {}
    for nom in ("ht", "vat", "ttc", "printed_ht", "printed_vat", "printed_ttc"):
        item = proposition.get("totals", {}).get(nom)
        totaux[nom] = convertir(item, nom)
    # Alias lisibles : ce sont les montants imprimés, jamais un recalcul.
    for cible, source in (("ht", "printed_ht"), ("vat", "printed_vat"), ("ttc", "printed_ttc")):
        if not valeur(totaux.get(cible)):
            totaux[cible] = dict(totaux[source])

    manquants = sorted(
        chemin for chemin, item in champs.items() if item and item.get("missing")
    )
    for index, brut_ligne in enumerate(proposition.get("lines", [])):
        for nom, item in brut_ligne.get("fields", {}).items():
            if item and item.get("missing"):
                manquants.append(f"lines[{index}].{nom}")

    confiances = [
        c["confidence"] for c in
        [champs.get("reference"), *champs.values(), *totaux.values()]
        if isinstance(c, dict) and not c.get("missing") and c.get("value") is not None
    ]
    confiance_global = round(sum(confiances) / len(confiances), 4) if confiances else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "model": MODELE_DEMO,
        "backend": backend,
        "document_type": proposition.get("document_type", "commande"),
        "reference": convertir(champs.get("reference"), "reference"),
        "client": client,
        "dates": dates,
        "payment_terms": conditions,
        "lines": lignes,
        "totals": totaux,
        "missing": manquants,
        "confidence_global": confiance_global,
        "constraint_report": dict(proposition.get("constraint_report", {})),
    }


def verifier_schema(payload: Mapping[str, Any]) -> list[str]:
    """Contraintes structurelles : la sortie du modèle reste un schéma plat."""
    erreurs: list[str] = []
    for cle in ("document_type", "reference", "client", "dates", "payment_terms",
                "lines", "totals", "missing"):
        if cle not in payload:
            erreurs.append(f"champ racine absent: {cle}")
    if payload.get("document_type") not in ("devis", "commande", "bon_livraison", "message"):
        erreurs.append("document_type invalide")
    if not isinstance(payload.get("lines", []), list):
        erreurs.append("lines doit etre une liste")
    if not isinstance(payload.get("missing", []), list):
        erreurs.append("missing doit etre une liste")
    for ligne in payload.get("lines", []):
        for cle in ("description", "quantity", "unit", "unit_price_ht", "discount",
                    "tax_rate", "line_total_ht"):
            if cle not in ligne:
                erreurs.append(f"ligne: champ absent {cle}")
    return erreurs


def _parcours_champs(obj: Any, chemin: str = "") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(obj, Mapping):
        if "value" in obj and "confidence" in obj:
            yield chemin, obj
            return
        for cle, valeur in obj.items():
            yield from _parcours_champs(valeur, f"{chemin}.{cle}" if chemin else str(cle))
    elif isinstance(obj, list):
        for index, valeur in enumerate(obj):
            yield from _parcours_champs(valeur, f"{chemin}[{index}]")


def verifier_provenance(payload: Mapping[str, Any]) -> list[str]:
    """Toute valeur non nulle doit pouvoir être montrée sur la pièce."""
    problemes: list[str] = []
    for chemin, valeur_champ in _parcours_champs(payload):
        if valeur_champ.get("missing") or valeur_champ.get("value") is None:
            continue
        bbox = valeur_champ.get("bbox")
        if not valeur_champ.get("page") or not isinstance(bbox, list) or len(bbox) != 4:
            problemes.append(f"{chemin}: source manquante (page + bbox obligatoires)")
        if not valeur_champ.get("method"):
            problemes.append(f"{chemin}: méthode manquante")
    return problemes


def verifier_non_invention(payload: Mapping[str, Any]) -> list[str]:
    """Un champ absent ne doit jamais recevoir de valeur."""
    problemes: list[str] = []
    for chemin, valeur_champ in _parcours_champs(payload):
        if valeur_champ.get("missing") and valeur_champ.get("value") is not None:
            problemes.append(f"{chemin}: valeur fournie alors que le champ est marqué absent")
        if valeur_champ.get("value") is None and not valeur_champ.get("missing"):
            problemes.append(f"{chemin}: champ null sans motif ABSENT_DE_LA_PIECE")
    declares = set(payload.get("missing", []))
    if "ifu" in declares and valeur((payload.get("client") or {}).get("ifu")) is not None:
        problemes.append("ifu: présent dans client alors qu'il est déclaré manquant")
    return problemes


def valider(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Valide un JSON d'extraction et retourne la liste des problèmes."""
    problemes = verifier_schema(payload)
    problemes += verifier_provenance(payload)
    problemes += verifier_non_invention(payload)
    return {"valide": not problemes, "problemes": problemes, "payload": dict(payload)}


def exiger_revue(payload: Mapping[str, Any]) -> list[str]:
    """Champs à regarder : absents ou sous leur seuil de confiance."""
    a_revoir: list[str] = []
    for chemin, valeur_champ in _parcours_champs(payload):
        if valeur_champ.get("missing"):
            a_revoir.append(chemin)
        elif float(valeur_champ.get("confidence", 0.0)) < seuil(chemin):
            a_revoir.append(chemin)
    return sorted(set(a_revoir))


def _bbox_objet(bbox: Any) -> dict[str, float]:
    if isinstance(bbox, Mapping):
        return {k: float(bbox.get(k, 0)) for k in ("x", "y", "w", "h")}
    valeurs = list(bbox or [0, 0, 0, 0])
    valeurs += [0] * (4 - len(valeurs))
    return {
        "x": float(valeurs[0]), "y": float(valeurs[1]),
        "w": float(valeurs[2]), "h": float(valeurs[3]),
    }


def aplatir(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Vue plate attendue par la visionneuse : clé -> champ cliquable."""
    aplati: dict[str, dict[str, Any]] = {}

    def ajouter(cle: str, valeur_champ: Mapping[str, Any] | None) -> None:
        if not valeur_champ:
            return
        item = {
            "value": valeur_champ.get("value"),
            "raw": valeur_champ.get("raw"),
            "page": valeur_champ.get("page"),
            "bbox": _bbox_objet(valeur_champ.get("bbox")),
            "method": valeur_champ.get("method"),
            "confidence": valeur_champ.get("confidence"),
        }
        if valeur_champ.get("missing"):
            item["motif"] = valeur_champ["missing"]
        aplati[cle] = item

    ajouter("reference", payload.get("reference"))
    ajouter("date", (payload.get("dates") or {}).get("issue"))
    for cle in ("name", "ifu"):
        ajouter(f"client_{cle}", (payload.get("client") or {}).get(cle))
    for cle in ("printed_ht", "printed_vat", "printed_ttc"):
        ajouter(cle, (payload.get("totals") or {}).get(cle))
    for ligne in payload.get("lines", []):
        numero = ligne.get("line_no", 0)
        noms = {
            "description": "description",
            "quantity": "quantity",
            "unit": "unit",
            "unit_price_ht": "price",
            "tax_rate": "tax",
            "line_total_ht": "total",
            "delivered": "delivered",
        }
        for source, cible in noms.items():
            if source in ligne:
                ajouter(f"line_{numero}_{cible}", ligne[source])
    return aplati


def extraire_piece(chemin: str | Path, backend: str | None = None,
                   type_piece: str | None = None) -> dict[str, Any]:
    """Pipeline complet : OCR -> proposition -> schéma contraint -> validation."""
    from adapters.llm import extraire as extraire_llm
    return extraire_llm(chemin, backend=backend, doc_type_hint=type_piece)
