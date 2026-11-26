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
from decimal import Decimal
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
from domain import normalization as norm
from domain.jev import Choice, Noul

from . import constraints, ocr

# Libellés tolérants aux confusions OCR courantes (l/1/I, ponctuation lue « ; » ou « . »).
SEP = r"\s*(?:[:;.,]\s*){0,2}"  # « IFU: :99… » : ponctuation doublée par l'OCR
REFERENCE_RE = re.compile(r"\b((?:DEV|CMD|BL|MSG|DEG|FAC|AV)\s?-\s?\d{4}\s?-\s?\d{3,5})\b", re.I)
CLIENT_RE = re.compile(r"(?:\bC[l1I|]{1,2}[i1l]?ent|\bDestinataire)" + SEP + r"(.+?)(?:\s+[I1l][FE]U\s*[:;]|$)", re.I)
IFU_LIBELLE_RE = re.compile(r"\b[I1l][FE]U\b", re.I)
IFU_RE = re.compile(r"\b[I1l][FE]U" + SEP + r"([0-9OoIl|][0-9OoIl|\s]{5,16})(?:[^0-9OoIl|]|$)", re.I)
DATE_RE = re.compile(r"\bDate" + SEP + r"(\d{4}\s?-\s?\d{2}\s?-\s?\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I)
CONDITIONS_RE = re.compile(r"\bConditions?" + SEP + r"(.+?)(?:\s+TVA\s*:|$)", re.I)
# Confusions lettre/chiffre corrigées seulement à l'intérieur d'un champ numérique.
CHIFFRES_OCR = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})
LIGNE_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s+([a-zA-Z²]+)\s*[xX]\s*"
    r"([\d][\d\s'.,]*)\s*FCFA\s+Remise\s+([\d][\d\s'.,]*)\s*FCFA\s+"
    r"TVA\s*(\d+(?:[.,]\d+)?)\s*%\s+Total\s+([\d][\d\s'.,]*)\s*FCFA"
    r"(?:\s+Livre\s+(\d+(?:[.,]\d+)?))?",
    re.I,
)
MONTANT = r"(\d[\dOo\s'.,]*[\dOo]|\d)"  # « 1 276 0OO » : zéros lus comme des O
TOTAL_HT_RE = re.compile(r"\bTota[l1I|]\s*HT\s*(?:imprime)?" + SEP + MONTANT, re.I)
TOTAL_TVA_RE = re.compile(r"\bTVA\s*\d+(?:[.,]\d+)?\s*%" + SEP + MONTANT, re.I)
TOTAL_TTC_RE = re.compile(r"\bTota[l1I|]\s*TTC\s*(?:imprime)?" + SEP + MONTANT, re.I)
TOTAUX_RE = (TOTAL_HT_RE, TOTAL_TVA_RE, TOTAL_TTC_RE)

# En-têtes de colonnes reconnus (texte normalisé sans accents).
EN_TETES = (
    ("line_no", re.compile(r"^n[o°]?$")),
    ("description", re.compile(r"^d[eé]?sig")),
    ("quantity", re.compile(r"^([qo0]t[eéc]?|quantite|qty)$")),  # « Qte » lu « Ote » sur une photo sombre
    ("unit", re.compile(r"^unit")),
    ("unit_price_ht", re.compile(r"^(pu|p\.u|prix|puht)$")),
    ("discount", re.compile(r"^remise")),
    ("tax_rate", re.compile(r"^tva$")),
    ("line_total_ht", re.compile(r"^(total|montant|totalht)$")),
    ("delivered", re.compile(r"^livr")),
)
COLONNES_NUMERIQUES = ("quantity", "unit_price_ht", "discount", "tax_rate", "line_total_ht", "delivered")
TOLERANCE_COLONNE = 3.5  # en % de largeur de page, autour du bord droit de l'en-tête


class BackendIndisponible(RuntimeError):
    """Le backend demandé n'est pas joignable : aucune valeur de repli n'est inventée."""


def _trouver(blocs: Sequence[Mapping[str, Any]], motif: str | re.Pattern[str]) -> Mapping[str, Any] | None:
    expression = re.compile(motif, re.I) if isinstance(motif, str) else motif
    for bloc in blocs:
        if expression.search(str(bloc.get("text", ""))):
            return bloc
    return None


def _bloc_mots(mots: Sequence[Mapping[str, Any]], parent: Mapping[str, Any]) -> dict[str, Any]:
    """Bloc de provenance couvrant exactement ces mots (une cellule, une valeur)."""
    if not mots:
        return dict(parent)
    x0 = min(float(m["bbox"][0]) for m in mots)
    y0 = min(float(m["bbox"][1]) for m in mots)
    x1 = max(float(m["bbox"][0]) + float(m["bbox"][2]) for m in mots)
    y1 = max(float(m["bbox"][1]) + float(m["bbox"][3]) for m in mots)
    return {
        "text": " ".join(str(m["text"]) for m in mots),
        "page": parent.get("page", 1),
        "bbox": [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)],
        "confidence": round(sum(float(m["confidence"]) for m in mots) / len(mots), 4),
        "method": parent.get("method"),
        "words": list(mots),
    }


def _largeur_car(mot: Mapping[str, Any]) -> float:
    return (float(mot["xr"][1]) - float(mot["xr"][0])) / max(1, len(str(mot["text"])))


def _segments(bloc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Coupe une ligne là où les mots s'écartent : « Client : X » n'est pas le tampon voisin."""
    mots = list(bloc.get("words") or [])
    if not mots:
        return [dict(bloc)]
    groupes, courant = [], [mots[0]]
    for precedent, mot in zip(mots, mots[1:]):
        ecart = float(mot["xr"][0]) - float(precedent["xr"][1])
        if ecart > max(4.0, 4 * _largeur_car(precedent)):
            groupes.append(courant)
            courant = [mot]
        else:
            courant.append(mot)
    groupes.append(courant)
    return [_bloc_mots(groupe, bloc) for groupe in groupes]


def _sous_bloc(segment: Mapping[str, Any], debut: int, fin: int) -> dict[str, Any]:
    """Mots du segment qui couvrent les caractères [debut, fin) de son texte."""
    mots = segment.get("words") or []
    if not mots:
        return dict(segment)
    retenus, position = [], 0
    for mot in mots:
        longueur = len(str(mot["text"]))
        if position < fin and position + longueur > debut:
            retenus.append(mot)
        position += longueur + 1
    return _bloc_mots(retenus or mots, segment)


def _capturer(segments: Sequence[Mapping[str, Any]], expression: re.Pattern[str],
              groupe: int = 1) -> tuple[str | None, Mapping[str, Any] | None]:
    for segment in segments:
        correspondance = expression.search(str(segment.get("text", "")))
        if correspondance:
            valeur = correspondance.group(groupe).strip()
            return valeur, _sous_bloc(segment, correspondance.start(groupe), correspondance.end(groupe))
    return None, None


def _item(brut: Any, bloc: Mapping[str, Any] | None, *, absent: bool = False,
          coherence: float | None = None, modele: float | None = None) -> dict[str, Any]:
    """Valeur brute + bloc d'origine + deux signaux de confiance.

    ``modele`` : solidité de la règle qui a trouvé la valeur (voir docs/CONFIANCE.md).
    ``coherence`` : la valeur se tient-elle avec le reste de la pièce et le référentiel ?
    """
    item = {"raw": brut, "bloc": bloc, "missing": absent,
            "coherence": float(coherence if coherence is not None else 0.9)}
    if modele is not None:
        item["modele"] = round(float(modele), 4)
    return item


# --------------------------------------------------------------------------
# Signal « modèle » : solidité de la règle qui a trouvé la valeur.
# Le structureur est fait de règles : il n'a pas de probabilité à fournir,
# mais il sait s'il a trouvé la valeur proprement ou en rattrapant une
# lecture imparfaite. Barème documenté dans docs/CONFIANCE.md.
# --------------------------------------------------------------------------

MODELE_NET = 0.95          # libellé lu tel quel, valeur au format attendu
MODELE_TOLERANT = 0.75     # libellé reconnu seulement grâce à la tolérance OCR (« Cllent », « 1FU »)
MODELE_CORRIGE = 0.65      # valeur dont des lettres ont été converties en chiffres (« 192 OOO »)
MODELE_POSITION_MIN = 0.70  # cellule rangée dans sa colonne à la limite de la tolérance
MODELE_DESCRIPTION = 0.90  # texte libre : la règle ne peut pas le vérifier
MODELE_UNITE_INCONNUE = 0.60

LIBELLES_NETS = {
    "client.name": re.compile(r"\b(?:Client|Destinataire)\s*:", re.I),
    "client.ifu": re.compile(r"\bIFU\s*:\s*\d"),
    "dates.issue": re.compile(r"\bDate\s*:\s*\d{4}-\d{2}-\d{2}\b"),
    "payment_terms.text": re.compile(r"\bConditions\s*:", re.I),
    "printed_ht": re.compile(r"\bTotal HT\s*:\s*\d[\d ]*\d\b"),
    "printed_vat": re.compile(r"\bTVA \d+ %\s*:\s*\d[\d ]*\d\b"),
    "printed_ttc": re.compile(r"\bTotal TTC\s*:\s*\d[\d ]*\d\b"),
}
EN_TETES_NETS = {"n", "no", "designation", "qte", "quantite", "unite", "pu", "prix",
                 "remise", "tva", "total", "montant", "livre", "ht"}


def _modele_libelle(chemin: str, segment: Mapping[str, Any] | None) -> float:
    """0,95 si le libellé et la valeur sont lus nets, 0,75 s'il a fallu la tolérance OCR."""
    if not segment:
        return MODELE_TOLERANT
    motif = LIBELLES_NETS.get(chemin)
    texte = " ".join(str(m["text"]) for m in segment.get("words") or []) or str(segment.get("text", ""))
    if motif is None or motif.search(texte):
        return MODELE_NET
    return MODELE_TOLERANT


def _modele_cellule(distance: float | None, mots: Sequence[Mapping[str, Any]],
                    colonne_nette: bool) -> float:
    """Cellule numérique : position sous l'en-tête, en-tête lu net, chiffres non corrigés."""
    score = MODELE_NET
    if distance is not None and distance > 1.0:
        # 0,95 à 1 % du bord de colonne, 0,70 à la limite de tolérance (3,5 %)
        ecart = min(1.0, (distance - 1.0) / (TOLERANCE_COLONNE - 1.0))
        score = MODELE_NET - ecart * (MODELE_NET - MODELE_POSITION_MIN)
    if not colonne_nette:
        score = min(score, 0.85)
    if any("lu" in mot for mot in mots):
        score = min(score, MODELE_CORRIGE)
    return score


# --------------------------------------------------------------------------
# Cohérence avec le référentiel clients
# --------------------------------------------------------------------------

COHERENCE_CONNUE = 0.98      # identique à un client du référentiel
COHERENCE_PRESQUE = 0.30     # ressemble à un client connu sans être identique : lecture suspecte
COHERENCE_NOUVELLE = 0.70    # ne ressemble à aucun client : client nouveau possible
COHERENCE_CONTRADICTION = 0.30  # IFU d'un client, nom d'un autre
COHERENCE_SANS_REFERENTIEL = 0.90  # rien à comparer : signal neutre
SEUIL_RESSEMBLANCE = 0.80


def _coherence_client(nom: str | None, ifu: str | None,
                      clients: Sequence[Mapping[str, Any]] | None) -> tuple[float, float, dict[str, Any]]:
    """Cohérence du nom et de l'IFU lus avec le référentiel clients.

    Ne corrige rien et ne rattache rien : le rattachement reste à
    ``matching.match_client`` (Larissa). On mesure seulement si la lecture
    est plausible. Un nom à 90 % identique à un client connu est presque
    toujours une lecture fautive (« Malson » pour « Maison ») : on le fait
    regarder. Retourne (cohérence du nom, cohérence de l'IFU, diagnostic).
    """
    if not clients:
        return COHERENCE_SANS_REFERENTIEL, 0.95, {"referentiel": False}
    from domain.matching import similarite

    nom_norm = norm.normalize_text(nom)
    par_nom = {norm.normalize_text(c.get("raison_sociale")): c for c in clients}
    par_ifu = {str(c["ifu"]): c for c in clients if c.get("ifu")}
    diagnostic: dict[str, Any] = {"referentiel": True}

    client_nom = par_nom.get(nom_norm) if nom_norm else None
    if not nom_norm:
        coherence_nom = COHERENCE_SANS_REFERENTIEL
    elif client_nom is not None:
        coherence_nom = COHERENCE_CONNUE
        diagnostic["nom"] = "identique"
    else:
        meilleur = max(clients, key=lambda c: similarite(nom or "", c.get("raison_sociale") or ""))
        ressemblance = similarite(nom or "", meilleur.get("raison_sociale") or "")
        diagnostic["ressemblance"] = ressemblance
        if ressemblance >= SEUIL_RESSEMBLANCE:
            coherence_nom = COHERENCE_PRESQUE
            diagnostic["nom"] = "presque_identique"
        else:
            coherence_nom = COHERENCE_NOUVELLE
            diagnostic["nom"] = "inconnu"

    if not ifu:
        coherence_ifu = 0.95
    elif ifu in par_ifu:
        client_ifu = par_ifu[ifu]
        if client_nom is not None and client_nom.get("id") != client_ifu.get("id"):
            coherence_ifu = COHERENCE_CONTRADICTION
            coherence_nom = min(coherence_nom, COHERENCE_CONTRADICTION)
            diagnostic["ifu"] = "contradiction_nom"
        else:
            coherence_ifu = COHERENCE_CONNUE
            diagnostic["ifu"] = "connu"
    else:
        coherence_ifu = COHERENCE_NOUVELLE
        diagnostic["ifu"] = "inconnu"
    return coherence_nom, coherence_ifu, diagnostic


def classer(blocs: Sequence[Mapping[str, Any]], indice: str | None = None) -> str:
    """Arbitre le type de pièce avec ``Choice`` ; ``commande`` reste le repli.

    Le texte est une donnée, jamais une instruction. Les scores sont des
    signaux de lecture, pas une confiance comptable.
    """
    texte = " ".join(str(b.get("text", "")) for b in blocs).lower() + " " + (indice or "").lower()
    livraison = "bon de livraison" in texte or ("livraison" in texte and "bl-" in texte)
    candidats = (
        ("bon_livraison", 4 if livraison else 0),
        ("devis", 3 if "devis" in texte else 0),
        ("message", 2 if ("message" in texte or "whatsapp" in texte) else 0),
        ("commande", 1),
    )
    choix = Choice.depuis(candidats, seuil=0).resoudre()
    if isinstance(choix, Noul):
        return "commande"
    return str(choix)


# --------------------------------------------------------------------------
# Tableau des lignes : colonnes retrouvées à partir de l'en-tête
# --------------------------------------------------------------------------

NOMBRE_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


def _entete_tableau(blocs: Sequence[Mapping[str, Any]]) -> tuple[int, dict[str, list[float]]] | None:
    """Repère la ligne d'en-tête et la position (redressée) de chaque colonne."""
    for index, bloc in enumerate(blocs):
        colonnes: dict[str, Any] = {}
        nettes: set[str] = set()  # en-têtes lus tels quels, sans tolérance OCR
        derniere: str | None = None
        for mot in bloc.get("words") or []:
            texte = norm.normalize_text(mot["text"])
            if texte == "ht" and derniere in ("unit_price_ht", "line_total_ht"):
                colonnes[derniere][1] = float(mot["xr"][1])  # « PU HT », « Total HT »
                continue
            derniere = None
            for cle, motif in EN_TETES:
                if cle not in colonnes and motif.match(texte):
                    colonnes[cle] = [float(mot["xr"][0]), float(mot["xr"][1])]
                    if texte in EN_TETES_NETS:
                        nettes.add(cle)
                    derniere = cle
                    break
        if "description" in colonnes and ({"unit_price_ht", "line_total_ht"} & colonnes.keys()):
            colonnes["_nettes"] = nettes
            return index, colonnes
    return None


def _chiffres(texte: str, apres_nombre: bool) -> str:
    """« OOO » après « 192 » est « 000 » ; « O0OO » contient un chiffre : c'est un nombre mal lu.

    Un mot sans aucun chiffre n'est converti que s'il fait trois caractères et
    suit un nombre (groupe des milliers). « Article » ou « No » restent du texte.
    """
    converti = texte.translate(CHIFFRES_OCR)
    if converti == texte or not NOMBRE_RE.match(converti):
        return texte
    if any(c.isdigit() for c in texte) or (apres_nombre and len(texte) == 3):
        return converti
    return texte


def _normaliser_mots(mots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copie des mots d'une ligne de tableau avec les confusions lettre/chiffre corrigées.

    Le texte lu d'origine reste dans ``lu`` : la provenance montre ce que l'OCR a vu.
    """
    resultat: list[dict[str, Any]] = []
    for mot in mots:
        texte = str(mot["text"]).strip()
        apres = bool(resultat) and NOMBRE_RE.match(resultat[-1]["text"]) is not None
        corrige = _chiffres(texte, apres)
        resultat.append({**mot, "text": corrige, "lu": texte} if corrige != texte else dict(mot))
    return resultat


def _groupes_numeriques(mots: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    """Regroupe « 185 » + « 000 » en un montant, et « 18 » + « % » en un taux."""
    groupes: list[list[int]] = []
    for index, mot in enumerate(mots):
        texte = str(mot["text"]).strip()
        suite = bool(groupes) and groupes[-1][-1] == index - 1
        if texte == "%":
            if suite:
                groupes[-1].append(index)
            continue
        if texte.endswith("%") and NOMBRE_RE.match(texte[:-1].strip() or "x"):
            groupes.append([index])
            continue
        if not NOMBRE_RE.match(texte):
            continue
        if suite and re.fullmatch(r"\d{3}", texte):
            precedent = mots[index - 1]
            ecart = float(mot["xr"][0]) - float(precedent["xr"][1])
            if not str(precedent["text"]).endswith("%") and ecart < 2.5 * _largeur_car(precedent):
                groupes[-1].append(index)
                continue
        groupes.append([index])
    return groupes


def _coherence_ligne(cellules: Mapping[str, str | None]) -> float:
    """Troisième signal : la ligne se tient-elle (qté × PU − remise = total) ?

    C'est un contrôle de lecture, pas un calcul de facture : aucune valeur
    n'est produite ni corrigée ici.
    """
    quantite = norm.normalize_quantity(cellules.get("quantity"))
    prix = norm.normalize_amount(cellules.get("unit_price_ht"))
    total = norm.normalize_amount(cellules.get("line_total_ht"))
    remise = norm.normalize_amount(cellules.get("discount")) or 0
    if quantite is None or prix is None or total is None:
        return 0.7
    return 0.98 if int(Decimal(quantite) * prix) - remise == total else 0.55


def _lignes_tableau(blocs: Sequence[Mapping[str, Any]], debut: int,
                    colonnes: Mapping[str, Any]) -> list[dict[str, Any]]:
    lignes: list[dict[str, Any]] = []
    nettes = colonnes.get("_nettes", set())
    for bloc in blocs[debut + 1:]:
        texte = str(bloc.get("text", ""))
        if any(expression.search(texte) for expression in TOTAUX_RE):
            break
        mots = _normaliser_mots(bloc.get("words") or [])
        if not mots:
            continue
        pris: set[int] = set()
        cellules: dict[str, list[int]] = {}
        distances: dict[str, float] = {}
        for groupe in _groupes_numeriques(mots):
            droite = float(mots[groupe[-1]]["xr"][1])
            meilleure, distance = None, TOLERANCE_COLONNE
            for cle in COLONNES_NUMERIQUES:
                if cle in colonnes and abs(droite - colonnes[cle][1]) <= distance:
                    meilleure, distance = cle, abs(droite - colonnes[cle][1])
            if meilleure and distance <= distances.get(meilleure, TOLERANCE_COLONNE + 1):
                if meilleure in cellules:
                    pris.difference_update(cellules[meilleure])
                cellules[meilleure] = groupe
                distances[meilleure] = distance
                pris.update(groupe)
        premier = mots[0]
        limite_numero = colonnes.get("description", [premier["xr"][1] + 1])[0]
        if 0 not in pris and re.fullmatch(r"\d{1,3}", str(premier["text"])) \
                and float(premier["xr"][1]) <= limite_numero + 0.5:
            cellules["line_no"] = [0]
            pris.add(0)
        bord_unite = colonnes["unit"][0] - 1.5 if "unit" in colonnes else None
        description, unite = [], []
        for index, mot in enumerate(mots):
            if index in pris:
                continue
            if bord_unite is not None and float(mot["xr"][0]) >= bord_unite:
                unite.append(index)
            else:
                description.append(index)
        if description:
            cellules["description"] = description
        if unite:
            cellules["unit"] = unite
        numeriques = [c for c in COLONNES_NUMERIQUES if c in cellules]
        if "description" not in cellules or len(numeriques) < 2:
            continue  # bruit (tampon, griffonnage) : pas une ligne de commande
        textes = {cle: " ".join(str(mots[i]["text"]) for i in idx) for cle, idx in cellules.items()}
        coherence = _coherence_ligne(textes)
        numero = int(textes["line_no"]) if "line_no" in textes else len(lignes) + 1
        champs: dict[str, Any] = {}
        for cle in ("description", "quantity", "unit", "unit_price_ht", "discount",
                    "tax_rate", "line_total_ht", "delivered"):
            if cle in cellules:
                mots_cellule = [mots[i] for i in cellules[cle]]
                cellule = _bloc_mots(mots_cellule, bloc)
                brut = textes[cle]
                if cle == "tax_rate":
                    brut = brut.replace(" ", "")
                if cle in COLONNES_NUMERIQUES:
                    modele = _modele_cellule(distances.get(cle), mots_cellule, cle in nettes)
                elif cle == "unit":
                    modele = MODELE_NET if norm.normalize_unit(brut) else MODELE_UNITE_INCONNUE
                else:
                    modele = MODELE_DESCRIPTION
                champs[cle] = _item(brut, cellule, modele=modele,
                                    coherence=coherence if cle in COLONNES_NUMERIQUES else 0.9)
            else:
                champs[cle] = _item(None, bloc, absent=True, coherence=coherence)
        lignes.append({"line_no": numero, "fields": champs})
    return lignes


def _lignes_texte(blocs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Message libre : une commande écrite sur une ligne de texte."""
    lignes: list[dict[str, Any]] = []
    for bloc in blocs:
        correspondance = LIGNE_RE.match(str(bloc.get("text", "")))
        if not correspondance:
            continue
        numero, description, quantite, unite, prix, remise, tva, total, livre = correspondance.groups()
        coherence = _coherence_ligne({"quantity": quantite, "unit_price_ht": prix,
                                      "discount": remise, "line_total_ht": total})
        segment = _segments(bloc)[0] if bloc.get("words") else bloc

        def cellule(groupe: int) -> dict[str, Any]:
            return _sous_bloc(segment, correspondance.start(groupe), correspondance.end(groupe))

        modele_unite = MODELE_NET if norm.normalize_unit(unite) else MODELE_UNITE_INCONNUE
        champs = {
            "description": _item(description, cellule(2), coherence=0.9, modele=MODELE_DESCRIPTION),
            "quantity": _item(quantite, cellule(3), coherence=coherence, modele=MODELE_NET),
            "unit": _item(unite, cellule(4), coherence=0.9, modele=modele_unite),
            "unit_price_ht": _item(prix, cellule(5), coherence=coherence, modele=MODELE_NET),
            "discount": _item(remise, cellule(6), coherence=coherence, modele=MODELE_NET),
            "tax_rate": _item(tva, cellule(7), coherence=coherence, modele=MODELE_NET),
            "line_total_ht": _item(total, cellule(8), coherence=coherence, modele=MODELE_NET),
            "delivered": (_item(livre, cellule(9), coherence=coherence, modele=MODELE_NET)
                          if livre is not None
                          else _item(None, bloc, absent=True, coherence=coherence)),
        }
        lignes.append({"line_no": int(numero), "fields": champs})
    return lignes


def _lire(segments: Sequence[Mapping[str, Any]], expression: re.Pattern[str],
          groupe: int = 1) -> tuple[str | None, Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """Comme ``_capturer``, mais rend aussi le segment entier (libellé compris) pour juger la règle."""
    for segment in segments:
        correspondance = expression.search(str(segment.get("text", "")))
        if correspondance:
            valeur = correspondance.group(groupe).strip()
            return valeur, _sous_bloc(segment, correspondance.start(groupe),
                                      correspondance.end(groupe)), segment
    return None, None, None


def proposer(blocs: Sequence[Mapping[str, Any]], backend: str | None = None,
             doc_type_hint: str | None = None,
             clients: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Produit une proposition brute : valeurs lues + bloc d'origine de chaque valeur.

    Aucun champ n'est comblé. Une valeur absente est marquée ``missing``
    avec le bloc du libellé, pour que la visionneuse puisse montrer l'endroit
    où la donnée devrait être.

    ``clients`` (référentiel, optionnel) sert uniquement au signal de
    cohérence du nom et de l'IFU : il ne corrige ni ne rattache rien.
    """
    backend = backend or settings.ai_backend
    if backend not in BACKENDS:
        raise BackendIndisponible(f"backend inconnu : {backend}")
    if backend == "cloud":
        proposition = _proposer_cloud(blocs, doc_type_hint)
        return constraints.appliquer(proposition, logprobs=proposition.get("logprobs"))

    type_piece = classer(blocs, doc_type_hint)
    segments = [segment for bloc in blocs for segment in _segments(bloc)]
    champs: dict[str, Any] = {}

    reference, bloc_reference, segment = _lire(segments, REFERENCE_RE)
    modele_reference = MODELE_NET
    if reference:
        compacte = re.sub(r"\s+", "", reference).upper()
        if compacte != reference:
            modele_reference = MODELE_TOLERANT  # « DEV - 2026-041 » : espaces lus par l'OCR
        reference = compacte
    champs["reference"] = _item(reference, bloc_reference, absent=reference is None,
                                coherence=0.95, modele=modele_reference)

    client_brut, bloc_client, segment_client = _lire(segments, CLIENT_RE)
    ifu_brut, bloc_ifu, segment_ifu = _lire(segments, IFU_RE)
    modele_ifu = _modele_libelle("client.ifu", segment_ifu)
    if ifu_brut is not None:
        corrige = ifu_brut.translate(CHIFFRES_OCR)
        if corrige != ifu_brut:
            modele_ifu = MODELE_CORRIGE  # lettre lue au milieu d'un identifiant
        ifu_brut = re.sub(r"\s+", "", corrige)
    coherence_nom, coherence_ifu, _ = _coherence_client(client_brut, ifu_brut, clients)
    champs["client.name"] = _item(client_brut, bloc_client, absent=client_brut is None,
                                  coherence=coherence_nom,
                                  modele=_modele_libelle("client.name", segment_client))
    champs["client.ifu"] = _item(
        ifu_brut, bloc_ifu or _trouver(segments, IFU_LIBELLE_RE),
        absent=ifu_brut is None, coherence=coherence_ifu, modele=modele_ifu,
    )
    champs["client.address"] = _item(None, None, absent=True)
    champs["client.phone"] = _item(None, None, absent=True)

    issue, bloc_issue, segment_date = _lire(segments, DATE_RE)
    modele_date = _modele_libelle("dates.issue", segment_date)
    if issue:
        compacte = re.sub(r"\s+", "", issue)
        if compacte != issue:
            modele_date = MODELE_TOLERANT  # « 2026- 11-25 »
        issue = compacte
    champs["dates.issue"] = _item(issue, bloc_issue, absent=issue is None, coherence=0.95,
                                  modele=modele_date)
    champs["dates.delivery"] = _item(None, _trouver(segments, r"\bLivr"), absent=True)
    champs["dates.due"] = _item(None, _trouver(segments, r"\b[EÉ]ch[eé]ance\b"), absent=True)

    conditions, bloc_conditions, segment_conditions = _lire(segments, CONDITIONS_RE)
    modele_conditions = _modele_libelle("payment_terms.text", segment_conditions)
    champs["payment_terms.text"] = _item(conditions, bloc_conditions, absent=conditions is None,
                                         modele=modele_conditions)
    jours = None
    if conditions:
        correspondance = re.search(r"\d+\s*jours?", conditions, re.I)
        jours = correspondance.group(0) if correspondance else None
    champs["payment_terms.days"] = _item(jours, bloc_conditions, absent=jours is None,
                                         modele=modele_conditions)
    champs["payment_terms.method"] = _item(None, None, absent=True)

    entete = _entete_tableau(blocs)
    lignes = _lignes_tableau(blocs, *entete) if entete else _lignes_texte(blocs)

    somme_lignes = 0
    lignes_completes = bool(lignes)
    for ligne in lignes:
        montant = norm.normalize_amount((ligne["fields"].get("line_total_ht") or {}).get("raw"))
        if montant is None:
            lignes_completes = False
        else:
            somme_lignes += montant

    totaux: dict[str, Any] = {}
    for nom, expression in (("printed_ht", TOTAL_HT_RE), ("printed_vat", TOTAL_TVA_RE),
                            ("printed_ttc", TOTAL_TTC_RE)):
        brut, bloc, segment = _lire(segments, expression)
        modele = _modele_libelle(nom, segment)
        if brut is not None:
            corrige = brut.translate(CHIFFRES_OCR)  # à l'intérieur d'un montant, « O » est un zéro
            if corrige != brut:
                modele = MODELE_CORRIGE
            brut = corrige
        coherence = 0.9
        if nom == "printed_ht" and brut is not None and lignes_completes:
            # Un total imprimé qui contredit ses lignes reste lu tel quel, mais on le fait regarder.
            coherence = 0.98 if norm.normalize_amount(brut) == somme_lignes else 0.6
        totaux[nom] = _item(brut, bloc, absent=brut is None, coherence=coherence, modele=modele)

    proposition = {
        "backend": backend,
        "document_type": type_piece,
        "fields": champs,
        "lines": lignes,
        "totals": totaux,
        "confiance_modele": 0.96 if backend == "demo" else 0.90,
        "model": MODELE_DEMO,
    }
    return constraints.appliquer(proposition)


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
             doc_type_hint: str | None = None,
             ocr_backend: str | None = None,
             clients: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Lit une pièce, produit un schéma valide ou lève une exception."""
    backend = backend or settings.ai_backend
    blocs = ocr.lire(chemin, backend=ocr_backend)
    if not blocs:
        raise ExtractionInvalide("aucun bloc OCR : extraction impossible")
    proposition = proposer(blocs, backend=backend, doc_type_hint=doc_type_hint, clients=clients)
    payload = assembler(proposition, backend=backend)
    resultat = valider(payload)
    if not resultat["valide"]:
        raise ExtractionInvalide("; ".join(resultat["problemes"]))
    return payload
