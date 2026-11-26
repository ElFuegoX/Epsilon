"""Jeu de démonstration et corpus d'évaluation reproductibles (graine 20261125).

Deux jeux distincts, tous deux fictifs :

* 96 pièces de démonstration : 40 devis PDF, 30 photos de commande,
  16 messages, 10 bons de livraison ;
* 120 documents annotés pour l'évaluation : les 96 pièces ci-dessus
  plus 24 documents d'évaluation (4 messages, 10 BL, 10 photos dégradées).

Chaque pièce est rendue pour de vrai (PDF avec couche texte, image PNG
photographiée, message texte) et sa vérité terrain est écrite au même
moment. Le fichier ``<pièce>.render.json`` décrit ce que le générateur a
dessiné : il sert à la vérité terrain et à l'ablation « OCR parfait » de
``domain.metrics``, **jamais** à l'extraction. L'extraction lit le fichier.

Aucune donnée réelle, aucun réseau, aucune horloge courante.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from config import settings

RACINE = Path(__file__).resolve().parent
GENERE = RACINE / "seeds" / "generated"
DORE = RACINE / "seeds" / "golden"

PAGE_LARGEUR = 595.28
PAGE_HAUTEUR = 841.89
DPI_IMAGE = 150
ECHELLE = DPI_IMAGE / 72
DEVISE = "FCFA"
SIMULATION = "SIMULATION - DOCUMENT DE DEMONSTRATION - DONNEES FICTIVES"

PREFIXES_CLIENTS = ("Ets", "SARL", "Atelier", "Maison", "Societe", "Groupe")
NOMS_CLIENTS = (
    "Sossa Materiaux", "Kora Menuiserie", "Adjovi Textile", "Hounsa Boot en Bois",
    "Dossou Quincaillerie", "Gbaguidi Reliefs", "Ahouansou Mobile", "Tossou Aggregats",
    "Kpenou Ferraille", "Sodji Plastiques", "Loko Parfumerie", "Hinkati Sibylle",
    "Vodounon Cocotier", "Agbodjan Orfeverie", "Migan Papeterie", "Fagnon Meubles",
    "Yehouessi Tissus", "Assogba Boulangerie", "Djedje Peinture", "Kpanou Plomberie",
    "Agbossou Carreaux", "N'Da Soudure", "Sacca Electricite", "Bocco Transport",
    "Ayi Piano", "Zounon Cordes", "Gbeto Cuirs", "Sossou Cosmetiques", "Tokpo Chaussures",
    "Hodjgbedji Arcades", "Adekunle Spirales", "Kiki Telecommunications", "Kouadio Transit",
    "Dagnon Papiers", "Amedehangbe Forges", "Semavo Verres", "Vianou Robinetterie",
    "Kpodjedo Eclairages", "Gnedoua Bricolage", "Sossou Bois", "Djonou Materiaux",
    "Foli Aubaines", "Hunlede Coffrets", "Aplogan Serrures", "Gbehou Minoterie",
    "Lafia Buanderie", "Odjo Fonderie", "Yovo Distillerie", "Kpohou Engrais",
    "Kossi Chaudronnerie", "Tchobo Epicerie", "Aimou Boucherie", "Salako Maroquinerie",
    "Bokou Imprimerie", "Kpedji Verrerie", "Wanou Jouets", "Metchi Glaciers",
    "Houessou Marchands", "Domingo Reparations", "Andjingbe Plantes", "Sefa Nettoyage",
    "Gbagnon Ambulance", "Zangue Boiseries", "Koundou Artisans",
)
VILLES = ("Cotonou", "Porto-Novo", "Abomey-Calavi", "Parakou", "Bohicon")

FAMILLES_ITEMS = ("Mobilier", "Menuiserie", "Livraison", "Quincaillerie", "Textile", "Divers")
TYPES_UNITE = ("pcs", "pcs", "pcs", "m", "m²", "kg", "forfait", "jour", "ml", "h")

# Tableau des lignes : clé, titre, bord gauche, bord droit (points), alignement.
# Les colonnes numériques sont alignées à droite, comme sur un devis réel.
COLONNES = (
    ("line_no", "N°", 40, 54, "left"),
    ("description", "Désignation", 60, 215, "left"),
    ("quantity", "Qté", 222, 246, "right"),
    ("unit", "Unité", 256, 296, "left"),
    ("unit_price_ht", "PU HT", 300, 362, "right"),
    ("discount", "Remise", 370, 404, "right"),
    ("tax_rate", "TVA", 410, 432, "right"),
    ("line_total_ht", "Total HT", 440, 505, "right"),
    ("delivered", "Livré", 515, 552, "right"),
)
Y_ENTETE_TABLEAU = 136
Y_PREMIERE_LIGNE = 156
PAS_LIGNE = 20


def _arrondi(valeur: Decimal) -> int:
    return int(valeur.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fcfa(valeur: int) -> str:
    return f"{valeur:,}".replace(",", " ")


def _latin1(texte: str) -> str:
    """Les deux moteurs de rendu écrivent du Latin-1 (Helvetica WinAnsi)."""
    texte = texte.replace("×", "x").replace("–", "-").replace("—", "-").replace("²", "2")
    return texte.encode("latin-1", "replace").decode("latin-1")


# --------------------------------------------------------------------------
# Mesure du texte : chaque moteur de rendu mesure avec sa propre police, pour
# que la bbox de vérité corresponde à ce qui est réellement dessiné.
# --------------------------------------------------------------------------

def _mesure_pdf() -> Callable[[str, float], float]:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:  # repli : largeur moyenne Helvetica
        return lambda texte, taille: len(texte) * taille * 0.52
    return lambda texte, taille: float(stringWidth(texte, "Helvetica", taille))


_POLICES: dict[int, Any] = {}


def _police(taille_points: float) -> Any:
    """Police vectorielle embarquée par Pillow : identique sur toutes les machines."""
    from PIL import ImageFont

    pixels = max(8, int(round(taille_points * ECHELLE)))
    if pixels not in _POLICES:
        try:
            _POLICES[pixels] = ImageFont.load_default(size=pixels)
        except TypeError:  # Pillow < 10.1
            _POLICES[pixels] = ImageFont.load_default()
    return _POLICES[pixels]


def _sans_accents(texte: str) -> str:
    import unicodedata

    texte = texte.replace("°", "o")
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def _mesure_image(texte: str, taille: float) -> float:
    return float(_police(taille).getlength(texte)) / ECHELLE


# --------------------------------------------------------------------------
# Mise en page : une liste d'éléments {x, y, texte, taille, couleur, role}
# en points, origine en haut à gauche. Les deux moteurs la dessinent telle quelle.
# --------------------------------------------------------------------------

def _element(x: float, y: float, texte: str, taille: float, role: str,
             mesure: Callable[[str, float], float], aligne: str = "left",
             couleur: str = "noir") -> dict[str, Any]:
    texte = _latin1(texte)
    if mesure is _mesure_image:
        texte = _sans_accents(texte)  # la police embarquée de Pillow n'a pas les accents
    largeur = mesure(texte, taille)
    gauche = x - largeur if aligne == "right" else x
    return {
        "x": round(gauche, 2), "y": float(y), "texte": texte, "taille": float(taille),
        "largeur": round(largeur, 2), "role": role, "couleur": couleur,
    }


def _entete(titre: str, ref: str, issue: str, client: Mapping[str, Any], conditions: bool,
            mesure: Callable[[str, float], float], ifu_visible: bool = True) -> list[dict[str, Any]]:
    elements = [
        _element(40, 34, f"{titre} {ref}", 16, "reference", mesure),
        _element(400, 38, f"Date : {issue}", 10, "dates.issue", mesure),
        _element(40, 70, f"Client : {client['raison_sociale']}", 11, "client.name", mesure),
    ]
    if ifu_visible:
        # IFU absent : le libellé est imprimé, la valeur ne l'est pas.
        elements.append(_element(40, 88, f"IFU : {client['ifu'] or ''}".rstrip(), 10, "client.ifu", mesure))
    if conditions:
        elements.append(_element(40, 106, "Conditions : 30 jours", 10, "payment_terms.text", mesure))
    return elements


def _tableau(lignes: list[Mapping[str, Any]], mesure: Callable[[str, float], float],
             avec_livre: bool) -> list[dict[str, Any]]:
    colonnes = [c for c in COLONNES if avec_livre or c[0] != "delivered"]
    elements: list[dict[str, Any]] = []
    for cle, titre, gauche, droite, aligne in colonnes:
        x = droite if aligne == "right" else gauche
        elements.append(_element(x, Y_ENTETE_TABLEAU, titre, 9, f"entete.{cle}", mesure, aligne))
    for rang, ligne in enumerate(lignes):
        y = Y_PREMIERE_LIGNE + rang * PAS_LIGNE
        valeurs = {
            "line_no": str(ligne["line_no"]),
            "description": str(ligne["description"]),
            "quantity": str(ligne["quantity"]),
            "unit": str(ligne["unit"]),
            "unit_price_ht": _fcfa(int(ligne["unit_price_ht"])),
            "discount": _fcfa(int(ligne.get("discount", 0))),
            "tax_rate": f"{ligne['tax_rate']} %",
            "line_total_ht": _fcfa(int(ligne["line_total_ht"])),
            "delivered": str(ligne.get("delivered", "")),
        }
        for cle, _titre, gauche, droite, aligne in colonnes:
            x = droite if aligne == "right" else gauche
            elements.append(_element(x, y, valeurs[cle], 9, f"lines[{rang}].{cle}", mesure, aligne))
    return elements


def _totaux_imprimes(totaux: Mapping[str, int], quels: Iterable[str],
                     mesure: Callable[[str, float], float]) -> list[dict[str, Any]]:
    libelles = {"ht": "Total HT", "vat": "TVA 18 %", "ttc": "Total TTC"}
    elements = []
    for rang, cle in enumerate(quels):
        texte = f"{libelles[cle]} : {_fcfa(int(totaux[cle]))} FCFA"
        elements.append(_element(330, 700 + rang * 20, texte, 11, f"totals.printed_{cle}", mesure))
    return elements


def _bbox_pourcent(element: Mapping[str, Any]) -> list[float]:
    return [
        round(element["x"] / PAGE_LARGEUR * 100, 2),
        round(element["y"] / PAGE_HAUTEUR * 100, 2),
        round(element["largeur"] / PAGE_LARGEUR * 100, 2),
        round(element["taille"] * 1.2 / PAGE_HAUTEUR * 100, 2),
    ]


# --------------------------------------------------------------------------
# Moteurs de rendu
# --------------------------------------------------------------------------

def _pdf_escape(texte: str) -> bytes:
    brut = texte.encode("latin-1", "replace")
    return brut.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _ecrire_pdf(chemin: Path, elements: Iterable[Mapping[str, Any]]) -> None:
    """PDF une page avec vraie couche texte (Helvetica), sans dépendance."""
    flux = bytearray()
    flux.extend(b"1 0 0 rg\n")
    flux.extend(b"BT /F1 8 Tf 1 0 0 1 40 815 Tm (" + _pdf_escape(SIMULATION) + b") Tj ET\n")
    flux.extend(b"0 0 0 rg 0.6 w\n")
    y_filet = PAGE_HAUTEUR - (Y_ENTETE_TABLEAU + 13)
    flux.extend(f"40 {y_filet:.2f} m 555 {y_filet:.2f} l S\n".encode("ascii"))
    for element in elements:
        taille = float(element["taille"])
        y_pdf = PAGE_HAUTEUR - float(element["y"]) - taille
        flux.extend(
            b"BT /F1 " + f"{taille:g}".encode("ascii") + b" Tf "
            + f"1 0 0 1 {float(element['x']):.2f} {y_pdf:.2f} Tm (".encode("ascii")
            + _pdf_escape(str(element["texte"]))
            + b") Tj ET\n"
        )

    objets: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
         "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>" % (PAGE_LARGEUR, PAGE_HAUTEUR)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(flux)).encode("ascii") + b" >>\nstream\n" + bytes(flux) + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for numero, objet in enumerate(objets, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{numero} 0 obj\n".encode("ascii") + objet + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objets) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    chemin.write_bytes(bytes(pdf))


def _page_image(elements: Iterable[Mapping[str, Any]]) -> Any:
    from PIL import Image, ImageDraw

    largeur, hauteur = int(PAGE_LARGEUR * ECHELLE), int(PAGE_HAUTEUR * ECHELLE)
    image = Image.new("RGB", (largeur, hauteur), (250, 249, 244))
    dessin = ImageDraw.Draw(image)
    dessin.text((40 * ECHELLE, 18 * ECHELLE), SIMULATION, fill=(200, 30, 30), font=_police(8))
    y_filet = (Y_ENTETE_TABLEAU + 13) * ECHELLE
    dessin.line((40 * ECHELLE, y_filet, 555 * ECHELLE, y_filet), fill=(40, 40, 40), width=2)
    for element in elements:
        dessin.text(
            (float(element["x"]) * ECHELLE, float(element["y"]) * ECHELLE),
            str(element["texte"]), fill=(25, 25, 30), font=_police(float(element["taille"])),
        )
    return image


def _bruit(image: Any, rng: random.Random, force: int) -> Any:
    """Grain de capteur seedé (``effect_noise`` de Pillow n'est pas reproductible)."""
    from PIL import Image, ImageChops

    largeur, hauteur = image.size
    octets = rng.randbytes(largeur * hauteur)
    grain = Image.frombytes("L", (largeur, hauteur), octets).point(lambda v: 128 + (v - 128) * force // 128)
    grain = Image.merge("RGB", (grain, grain, grain))
    return ImageChops.add(image, grain, scale=1.0, offset=-128)  # image + grain centré sur 0


def _eclairage(image: Any, rng: random.Random, sombre: float) -> Any:
    """Dégradé de lumière : un coin plus sombre, comme une photo prise à la main."""
    from PIL import Image, ImageChops

    largeur, hauteur = image.size
    petit = Image.new("L", (64, 64))
    cx, cy = rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8)
    for y in range(64):
        for x in range(64):
            distance = math.hypot(x / 63 - cx, y / 63 - cy)
            petit.putpixel((x, y), int(255 * (1 - sombre * min(1.0, distance / 1.1))))
    masque = petit.resize((largeur, hauteur), Image.BILINEAR)
    return ImageChops.multiply(image, Image.merge("RGB", (masque, masque, masque)))


def _photographier(page: Any, rng: random.Random, degradation: str | None) -> Any:
    """Simule une prise de vue : fond, perspective, rotation, lumière, grain, flou."""
    from PIL import Image, ImageDraw, ImageFilter

    largeur, hauteur = page.size
    if degradation == "tampon":
        calque = Image.new("RGBA", (int(250 * ECHELLE), int(56 * ECHELLE)), (0, 0, 0, 0))
        dessin = ImageDraw.Draw(calque)
        dessin.rectangle((4, 4, calque.size[0] - 5, calque.size[1] - 5), outline=(190, 30, 40, 200), width=5)
        dessin.text((20, 22), "DUPLICATA - A VERIFIER", fill=(190, 30, 40, 200), font=_police(17))
        calque = calque.rotate(rng.uniform(-12, -6), expand=True, resample=Image.BICUBIC)
        page = page.copy()
        page.paste(calque, (int(300 * ECHELLE), int(52 * ECHELLE)), calque)

    marge = int(36 * ECHELLE)
    fond = Image.new("RGB", (largeur + 2 * marge, hauteur + 2 * marge), (92, 78, 64))
    fond.paste(page, (marge, marge))

    def jitter() -> float:
        return rng.uniform(-0.35, 0.35) * marge

    quad = (
        marge + jitter(), marge + jitter(),
        marge + jitter(), marge + hauteur + jitter(),
        marge + largeur + jitter(), marge + hauteur + jitter(),
        marge + largeur + jitter(), marge + jitter(),
    )
    image = fond.transform((largeur, hauteur), Image.QUAD, quad, resample=Image.BICUBIC)

    angle = {"rotation": rng.choice((-1, 1)) * rng.uniform(3.0, 4.5)}.get(degradation, rng.uniform(-1.4, 1.4))
    image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=(92, 78, 64))
    image = _eclairage(image, rng, 0.55 if degradation == "ombre" else 0.22)
    image = _bruit(image, rng, 34 if degradation else 22)
    return image.filter(ImageFilter.GaussianBlur(0.9 if degradation else 0.6))


def _ecrire_png(chemin: Path, elements: list[Mapping[str, Any]], rng: random.Random,
                degradation: str | None) -> None:
    image = _photographier(_page_image(elements), rng, degradation)
    image.save(chemin, optimize=False, compress_level=6)


def _texte_ligne(ligne: Mapping[str, Any]) -> str:
    """Une ligne de commande écrite dans un message, sur une seule ligne."""
    return (
        f"{ligne['line_no']}  {ligne['description']}  {ligne['quantity']} {ligne['unit']} "
        f"x {_fcfa(int(ligne['unit_price_ht']))} FCFA Remise 0 FCFA "
        f"TVA {ligne['tax_rate']} % Total {_fcfa(int(ligne['line_total_ht']))} FCFA"
    )


def _ecrire_texte(chemin: Path, elements: list[Mapping[str, Any]]) -> None:
    contenu = [SIMULATION] + [str(element["texte"]) for element in elements]
    chemin.write_text("\n".join(contenu) + "\n", encoding="utf-8")


def empreinte_contenu(chemin: Path) -> str:
    """Clé du cache OCR (pixels pour une image) : une seule définition, dans l'adaptateur."""
    from adapters.ocr import empreinte_contenu as calculer

    return calculer(chemin)


def _ecrire_piece(chemin: Path, elements: list[dict[str, Any]], kind: str, rng: random.Random,
                  degradation: str | None = None, **extra: Any) -> dict[str, Any]:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        _ecrire_pdf(chemin, elements)
    elif kind == "png":
        _ecrire_png(chemin, elements, rng, degradation)
    elif kind == "txt":
        _ecrire_texte(chemin, elements)
    else:
        raise ValueError(f"format inconnu: {kind}")
    sha256 = hashlib.sha256(chemin.read_bytes()).hexdigest()
    rendu = {
        "role": "verite_de_rendu",
        "avertissement": "Ce que le générateur a dessiné. Jamais lu par l'extraction.",
        "sha256": sha256,
        "empreinte_contenu": empreinte_contenu(chemin),
        "pages": 1,
        "page_size": [PAGE_LARGEUR, PAGE_HAUTEUR],
        "bbox_unite": "pourcent",
        "bbox_note": "Page avant prise de vue pour les photos." if kind == "png" else None,
        "degradation": degradation,
        "elements": [
            {"texte": e["texte"], "role": e["role"], "page": 1, "bbox": _bbox_pourcent(e)}
            for e in elements
        ],
        **extra,
    }
    destination = chemin.with_name(chemin.stem + ".render.json")
    destination.write_text(json.dumps(rendu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"fichier": str(chemin.relative_to(RACINE)).replace("\\", "/"), "sha256": sha256}


# --------------------------------------------------------------------------
# Données métier fictives
# --------------------------------------------------------------------------

def _clients(rng: random.Random) -> list[dict[str, Any]]:
    clients: list[dict[str, Any]] = []
    for index, nom in enumerate(NOMS_CLIENTS):
        prefixe = PREFIXES_CLIENTS[index % len(PREFIXES_CLIENTS)]
        raison = f"{prefixe} {nom}"
        ifu = None if index in (0, 7, 21) else f"99{rng.randrange(10**7, 10**8):07d}"
        clients.append({
            "id": f"cli-{index + 1:03d}",
            "raison_sociale": raison,
            "ifu": ifu,
            "adresse": f"{rng.randrange(1, 200)} rue des {nom.split()[0]}",
            "ville": VILLES[index % len(VILLES)],
            "telephone": f"+229 9{rng.randrange(10**8, 10**9):08d}",
            "conditions": "30J",
        })
    return clients


def _articles(rng: random.Random) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for index in range(120):
        famille = FAMILLES_ITEMS[index % len(FAMILLES_ITEMS)]
        unite = TYPES_UNITE[index % len(TYPES_UNITE)]
        articles.append({
            "id": f"art-{index + 1:03d}",
            "reference": f"REF-{index + 1:04d}",
            "designation": f"Article {famille.lower()} {index + 1:03d}",
            "unite": unite,
            "prix_catalogue": rng.randrange(5, 200) * 1000,
            "famille": famille,
        })
    return articles


def _totaux(lignes: list[Mapping[str, Any]], anomalie: str | None) -> dict[str, dict[str, int]]:
    ht = sum(int(l["line_total_ht"]) for l in lignes)
    tva = _arrondi(Decimal(ht) * Decimal("0.18"))
    recalcule = {"ht": ht, "vat": tva, "ttc": ht + tva}
    if anomalie == "arithmetique":
        imprime_ht = ht - 20_000
        imprime_tva = _arrondi(Decimal(imprime_ht) * Decimal("0.18"))
        imprime = {"ht": imprime_ht, "vat": imprime_tva, "ttc": imprime_ht + imprime_tva}
    else:
        imprime = dict(recalcule)
    ecart = {cle: recalcule[cle] - imprime[cle] for cle in ("ht", "vat", "ttc")}
    return {"printed": imprime, "recalculated": recalcule, "ecart": ecart}


def _lignes_quote(rng: random.Random, articles: list[Mapping[str, Any]], nombre: int) -> list[dict[str, Any]]:
    resultat: list[dict[str, Any]] = []
    for index in range(nombre):
        article = articles[(index * 7) % len(articles)]
        quantite = rng.randrange(1, 6)
        prix = int(article["prix_catalogue"])
        resultat.append({
            "line_no": index + 1,
            "description": str(article["designation"]),
            "quantity": str(quantite),
            "unit": str(article["unite"]),
            "unit_price_ht": prix,
            "discount": 0,
            "tax_rate": 18,
            "line_total_ht": quantite * prix,
            "delivered": str(quantite),
        })
    return resultat


def _lignes_temoins() -> list[dict[str, Any]]:
    return [
        {"line_no": 1, "description": "Banquette 3 places", "quantity": "4", "unit": "pcs",
         "unit_price_ht": 185000, "discount": 0, "tax_rate": 18, "line_total_ht": 740000, "delivered": "4"},
        {"line_no": 2, "description": "Table basse chêne", "quantity": "2", "unit": "pcs",
         "unit_price_ht": 120000, "discount": 0, "tax_rate": 18, "line_total_ht": 240000, "delivered": "2"},
        {"line_no": 3, "description": "Livraison et installation", "quantity": "1", "unit": "forfait",
         "unit_price_ht": 60000, "discount": 0, "tax_rate": 18, "line_total_ht": 60000, "delivered": "0"},
    ]


def _split(index: int) -> str:
    reste = index % 5
    if reste == 3:
        return "validation"
    if reste == 4:
        return "test"
    return "dev"


def _verifier_split(truths: list[dict[str, Any]]) -> None:
    comptes = {nom: 0 for nom in ("dev", "validation", "test")}
    for truth in truths:
        comptes[truth["split"]] += 1
    if comptes != {"dev": 72, "validation": 24, "test": 24}:
        raise AssertionError(f"split inattendu: {comptes}")


def _sans_livre(lignes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une commande ou un message ne porte pas de quantité livrée."""
    return [{k: v for k, v in ligne.items() if k != "delivered"} for ligne in lignes]


# --------------------------------------------------------------------------
# Génération du corpus
# --------------------------------------------------------------------------

def generer(reset: bool = False, as_of: str | None = None, force: bool = False,
            out: Path | None = None) -> dict[str, Any]:
    """Génère le corpus. Idempotent : mêmes arguments -> mêmes pièces."""
    as_of = as_of or settings.as_of
    racine_sortie = Path(out) if out else GENERE
    racine_doree = racine_sortie.parent / "golden" if out else DORE
    racine_sortie.mkdir(parents=True, exist_ok=True)
    racine_doree.mkdir(parents=True, exist_ok=True)

    rng = random.Random(settings.graine_demo)
    rng_image = random.Random(settings.graine_demo + 1)  # séparé : le rendu ne décale pas les données
    clients = _clients(rng)
    articles = _articles(rng)
    date_ref = date.fromisoformat(as_of)
    annee = date_ref.year
    mesure_pdf = _mesure_pdf()

    devis_refs = ["DEV-2026-041"] + [f"DEV-{annee}-{n:03d}" for n in range(1, 40)]
    refs_photos = [f"CMD-{annee}-{n:03d}" for n in range(101, 131)]
    refs_messages = [f"MSG-{annee}-{n:03d}" for n in range(201, 221)]
    refs_bl = [f"BL-{annee}-{n:03d}" for n in range(301, 321)]
    refs_degrades = [f"DEG-{annee}-{n:03d}" for n in range(401, 411)]

    proofs: list[dict[str, Any]] = []
    index = 0

    def enregistrer(ref: str, client: Mapping[str, Any], lignes: list[dict[str, Any]],
                    type_piece: str, famille: str, fichier: Path, kind: str,
                    elements: list[dict[str, Any]], totaux: dict[str, dict[str, int]],
                    imprimes: tuple[str, ...], anomalie: str | None = None,
                    degradation: str | None = None, notes: str = "",
                    issue: str | None = None, canal: str = "upload") -> None:
        nonlocal index
        meta = _ecrire_piece(
            fichier, elements, kind, rng_image, degradation,
            reference=ref, document_type=type_piece, split=_split(index),
        )
        roles = {e["role"] for e in elements}
        conditions_presentes = "payment_terms.text" in roles
        manquants = []
        if client.get("ifu") is None:
            manquants.append("ifu")
        if type_piece in ("devis", "commande", "message"):
            manquants.append("dates.due")  # aucune pièce du corpus n'imprime d'échéance
        if not conditions_presentes:
            manquants.extend(["payment_terms.text", "payment_terms.days"])
        anomalies = [anomalie] if anomalie else []
        if client.get("ifu") is None:
            anomalies.append("MISSING_MANDATORY")
        date_piece = issue or (date_ref - timedelta(days=index % 20)).isoformat()
        truth = {
            "id": f"doc-{ref}",
            "reference": ref,
            "document_type": type_piece,
            "family": famille,
            "canal": canal,
            "source_file": meta["fichier"],
            "sha256": meta["sha256"],
            "split": _split(index),
            "quality": "degraded" if degradation else "clean",
            "degradation": degradation,
            "date": date_piece,
            "client": {
                "name": client["raison_sociale"],
                "ifu": client.get("ifu"),
                "missing": ["ifu"] if client.get("ifu") is None else [],
            },
            "fields": {
                "reference": ref,
                "client.name": client["raison_sociale"],
                "client.ifu": client.get("ifu"),
                "dates.issue": date_piece,
                "dates.delivery": None,
                "dates.due": None,
                "payment_terms.text": "30 jours" if conditions_presentes else None,
                "payment_terms.days": 30 if conditions_presentes else None,
            },
            "lines": lignes,
            "printed_totals": {
                cle: (totaux["printed"][cle] if cle in imprimes else None)
                for cle in ("ht", "vat", "ttc")
            },
            "recalculated_totals": totaux["recalculated"],
            "expected_ecart": totaux["ecart"],
            "missing": manquants,
            "injected_anomalies": anomalies,
            "notes": notes,
        }
        if type_piece in ("devis", "bon_livraison") and all("delivered" in l for l in lignes):
            truth["delivery"] = {str(l["line_no"]): l["delivered"] for l in lignes}
            truth["missing_line"] = next(
                (l["line_no"] for l in lignes if l["quantity"] != l["delivered"]), None
            )
        (racine_doree / f"{ref}.truth.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        proofs.append({"id": truth["id"], "reference": ref, "type": type_piece, "family": famille,
                       "split": truth["split"], "truth": f"golden/{ref}.truth.json",
                       "fichier": meta["fichier"], "canal": canal,
                       "demo": "/demo/" in meta["fichier"]})
        index += 1

    # 40 devis PDF, témoin DEV-2026-041 en premier.
    for numero, ref in enumerate(devis_refs):
        client = clients[0] if ref == "DEV-2026-041" else clients[numero % len(clients)]
        if ref == "DEV-2026-041":
            lignes = _lignes_temoins()
            anomalie = "arithmetique"
        else:
            lignes = _lignes_quote(rng, articles, 2 + numero % 3)
            anomalie = "arithmetique" if numero % 7 == 2 else None
            if lignes and numero % 5 == 1:
                lignes[-1]["delivered"] = "0"
        totaux = _totaux(lignes, anomalie)
        issue = "2026-11-18" if ref == "DEV-2026-041" else (date_ref - timedelta(days=numero % 20)).isoformat()
        elements = (
            _entete("DEVIS", ref, issue, client, True, mesure_pdf)
            + _tableau(lignes, mesure_pdf, avec_livre=True)
            + _totaux_imprimes(totaux["printed"], ("ht", "vat", "ttc"), mesure_pdf)
        )
        enregistrer(ref, client, lignes, "devis", "devis",
                    racine_sortie / "demo" / "devis" / f"{ref}.pdf", "pdf",
                    elements, totaux, ("ht", "vat", "ttc"), anomalie,
                    notes="IFU absent, ecart d'addition et installation non livree."
                    if ref == "DEV-2026-041" else "Devis synthetique.",
                    issue=issue, canal="email")

    # 30 photos de commande.
    for numero, ref in enumerate(refs_photos):
        client = clients[(numero + 3) % len(clients)]
        lignes = _sans_livre(_lignes_quote(rng, articles, 2 + numero % 2))
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        elements = (
            _entete("COMMANDE", ref, issue, client, False, _mesure_image)
            + _tableau(lignes, _mesure_image, avec_livre=False)
            + _totaux_imprimes(totaux["printed"], ("ht",), _mesure_image)
        )
        enregistrer(ref, client, lignes, "commande", "photo",
                    racine_sortie / "demo" / "photos" / f"{ref}.png", "png",
                    elements, totaux, ("ht",),
                    notes="Photo de bon de commande : perspective, lumière et grain simulés.",
                    issue=issue, canal="whatsapp")

    # 20 messages (16 de démonstration + 4 d'évaluation).
    for numero, ref in enumerate(refs_messages):
        client = {**clients[(numero + 8) % len(clients)], "ifu": None}  # un message ne porte pas d'IFU
        lignes = _sans_livre(_lignes_quote(rng, articles, 1 + numero % 2))
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        elements = [
            _element(40, 34, f"MESSAGE {ref}", 15, "reference", mesure_pdf),
            _element(40, 58, f"Client : {client['raison_sociale']}", 11, "client.name", mesure_pdf),
            _element(40, 74, "Objet : commande de mobilier", 10, "objet", mesure_pdf),
            _element(40, 90, f"Date : {issue}", 10, "dates.issue", mesure_pdf),
        ] + [
            _element(40, 110 + rang * 16, _texte_ligne(ligne), 10, f"lines[{rang}]", mesure_pdf)
            for rang, ligne in enumerate(lignes)
        ]
        dossier = "demo" if numero < 16 else "eval"
        enregistrer(ref, client, lignes, "message", "message",
                    racine_sortie / dossier / "messages" / f"{ref}.txt", "txt",
                    elements, totaux, (),
                    notes="Message libre : aucun IFU n'est present dans la piece.",
                    issue=issue, canal="whatsapp")

    # 20 bons de livraison (10 de démonstration + 10 d'évaluation).
    for numero, ref in enumerate(refs_bl):
        client = clients[(numero + 11) % len(clients)]
        lignes = _lignes_quote(rng, articles, 2)
        if numero % 3 == 0:
            lignes[-1]["delivered"] = "0"
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        elements = (
            _entete("BON DE LIVRAISON", ref, issue, client, False, mesure_pdf)
            + _tableau(lignes, mesure_pdf, avec_livre=True)
        )
        dossier = "demo" if numero < 10 else "eval"
        anomalie = "QUANTITY_MISMATCH" if numero % 3 == 0 else None
        enregistrer(ref, client, lignes, "bon_livraison", "bon_livraison",
                    racine_sortie / dossier / "livraisons" / f"{ref}.pdf", "pdf",
                    elements, totaux, (), anomalie,
                    notes="Ligne non livree : decision humaine obligatoire."
                    if anomalie else "Bon de livraison synthetique.",
                    issue=issue, canal="upload")

    # 10 photos dégradées : la dégradation est appliquée à l'image, pas au texte.
    degradations = ("rotation", "ombre", "tampon") * 4
    for numero, ref in enumerate(refs_degrades):
        client = clients[(numero + 17) % len(clients)]
        lignes = _sans_livre(_lignes_quote(rng, articles, 2 + numero % 2))
        anomalie = "arithmetique" if numero % 4 == 0 else None
        totaux = _totaux(lignes, anomalie)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        elements = (
            _entete("DEVIS", ref, issue, client, False, _mesure_image)
            + _tableau(lignes, _mesure_image, avec_livre=False)
            + _totaux_imprimes(totaux["printed"], ("ht",), _mesure_image)
        )
        enregistrer(ref, client, lignes, "devis", "degrade",
                    racine_sortie / "eval" / "degrades" / f"{ref}.png", "png",
                    elements, totaux, ("ht",), anomalie, degradations[numero],
                    notes=f"Photo degradee : {degradations[numero]}. "
                          "La verite terrain reste celle de la piece imprimee.",
                    issue=issue, canal="whatsapp")

    _verifier_split(proofs)

    # Référentiels et historique, chargés en base par ``charger_base``.
    factures = []
    for index_facture in range(60):
        client = clients[index_facture % len(clients)]
        ht = 150_000 + (index_facture % 12) * 45_000
        tva = _arrondi(Decimal(ht) * Decimal("0.18"))
        factures.append({
            "id": f"fac-{index_facture + 1:03d}",
            "numero": f"FAC-{annee}-{index_facture + 1:05d}",
            "client": client["id"],
            "date": (date_ref - timedelta(days=30 + index_facture * 3)).isoformat(),
            "total_ht": ht, "total_tva": tva, "total_ttc": ht + tva,
            "statut": "ÉMIS",
        })
    avoirs = []
    for index_avoir in range(9):
        facture = factures[index_avoir * 5]
        ht = facture["total_ht"] // 10
        tva = _arrondi(Decimal(ht) * Decimal("0.18"))
        avoirs.append({
            "id": f"av-{index_avoir + 1:03d}",
            "numero": f"AV-{annee}-{index_avoir + 1:05d}",
            "facture": facture["id"],
            "motif": "avoir partiel simule",
            "total_ht": ht, "total_tva": tva, "total_ttc": ht + tva,
            "date": facture["date"],
            "statut": "ÉMIS",
        })
    paiements = [{
        "id": f"pay-{index_paiement + 1:03d}",
        "facture": factures[index_paiement * 3]["id"],
        "montant": factures[index_paiement * 3]["total_ttc"],
        "date": (date_ref - timedelta(days=index_paiement * 2)).isoformat(),
        "canal": ("virement", "especes", "mobile")[index_paiement % 3],
    } for index_paiement in range(18)]

    for nom, valeur in (
        ("clients.json", clients),
        ("items.json", articles),
        ("invoices.json", factures),
        ("credit_notes.json", avoirs),
        ("payments.json", paiements),
    ):
        (racine_sortie / nom).write_text(
            json.dumps(valeur, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    manifest = {
        "graine": settings.graine_demo,
        "as_of": as_of,
        "rendu": "v2 : colonnes, police vectorielle Pillow, photos simulées",
        "demonstration": {"pieces": 96, "devis_pdf": 40, "photos": 30, "messages": 16, "bons_livraison": 10},
        "evaluation": {
            "documents": len(proofs),
            "familles": {fam: sum(1 for p in proofs if p["family"] == fam)
                         for fam in ("devis", "photo", "message", "bon_livraison", "degrade")},
            "split": {nom: sum(1 for p in proofs if p["split"] == nom)
                      for nom in ("dev", "validation", "test")},
        },
        "referentiels": {"clients": len(clients), "articles": len(articles),
                         "factures": len(factures), "avoirs": len(avoirs), "paiements": len(paiements)},
        "documents": [{k: v for k, v in p.items() if k not in ("fichier", "canal", "demo")} for p in proofs],
    }
    manifest["empreinte"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    (racine_sortie / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest["_pieces"] = proofs
    manifest["_donnees"] = {"clients": clients, "articles": articles, "factures": factures,
                            "avoirs": avoirs, "paiements": paiements}

    if reset and not out:
        charger_base(manifest)
    return manifest


# --------------------------------------------------------------------------
# Chargement de la base de démonstration
# --------------------------------------------------------------------------

MIMES = {".pdf": "application/pdf", ".png": "image/png", ".txt": "text/plain"}


def charger_base(manifest: Mapping[str, Any], extraire: bool = True,
                 db_path: str | None = None) -> dict[str, int]:
    """Réinitialise la base puis charge référentiels, historique et 96 pièces.

    Les factures historiques sont insérées avec des numéros continus et les
    séquences avancées en conséquence : la prochaine validation obtient
    FAC-AAAA-00061. Les pièces sont extraites si l'OCR est disponible ; sinon
    elles restent ``EN_ATTENTE_IA`` (aucune valeur n'est inventée).
    """
    import db
    from domain import documents as etats
    from domain.extraction import canonical

    db.reset(db_path)
    db.ensure_dirs()
    donnees = manifest["_donnees"]
    annee = int(str(manifest["as_of"])[:4])
    horodatage = f"{manifest['as_of']}T00:00:00Z"
    comptes = {"documents": 0, "extraits": 0, "en_attente": 0}

    conn = db.connect(db_path)
    try:
        with db.transaction(conn):
            conn.executemany(
                "INSERT INTO clients(id, raison_sociale, ifu, adresse, ville, telephone, conditions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(c["id"], c["raison_sociale"], c["ifu"], c["adresse"], c["ville"], c["telephone"],
                  c["conditions"]) for c in donnees["clients"]],
            )
            conn.executemany(
                "INSERT INTO items(id, reference, designation, unite, prix_catalogue, famille) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(a["id"], a["reference"], a["designation"], a["unite"], a["prix_catalogue"],
                  a["famille"]) for a in donnees["articles"]],
            )
            for facture in donnees["factures"]:
                snapshot = canonical({"historique": True, **facture})
                conn.execute(
                    "INSERT INTO invoices(id, numero, serie, annee, snapshot, hash_snapshot, hash_pdf, "
                    "date, statut, canal, client, empreinte, total_ht, total_tva, total_ttc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (facture["id"], facture["numero"], settings.serie_defaut, annee, snapshot,
                     hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), "HISTORIQUE_SANS_PDF",
                     facture["date"], facture["statut"], "historique", facture["client"], None,
                     facture["total_ht"], facture["total_tva"], facture["total_ttc"]),
                )
            for avoir in donnees["avoirs"]:
                conn.execute(
                    "INSERT INTO credit_notes(id, numero, serie, annee, facture, motif, total_ht, "
                    "total_tva, total_ttc, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (avoir["id"], avoir["numero"], settings.serie_defaut, annee, avoir["facture"],
                     avoir["motif"], avoir["total_ht"], avoir["total_tva"], avoir["total_ttc"],
                     avoir["statut"], avoir["date"]),
                )
            conn.executemany(
                "INSERT INTO payments(id, facture, montant, date, canal, reference) VALUES (?, ?, ?, ?, ?, ?)",
                [(p["id"], p["facture"], p["montant"], p["date"], p["canal"], None)
                 for p in donnees["paiements"]],
            )
            for prefixe, nombre in ((settings.prefixe_facture, len(donnees["factures"])),
                                    (settings.prefixe_avoir, len(donnees["avoirs"]))):
                conn.execute(
                    "UPDATE number_sequences SET prochaine=? WHERE serie=? AND annee=? AND prefixe=?",
                    (nombre + 1, settings.serie_defaut, annee, prefixe),
                )

            for piece in manifest["_pieces"]:
                if not piece["demo"]:
                    continue
                chemin = RACINE / piece["fichier"]
                empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
                # Copie immuable au même endroit que l'import réel : le worker
                # retrouve ainsi la pièce, et l'API peut la servir à la visionneuse.
                destination = db.data_dir() / "documents" / f"{empreinte}{chemin.suffix.lower()}"
                if not destination.exists():
                    shutil.copy2(chemin, destination)
                conn.execute(
                    "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (piece["id"], piece["type"], chemin.name, MIMES[chemin.suffix.lower()],
                     chemin.stat().st_size, empreinte, 1,
                     piece["canal"], etats.IMPORTE, horodatage),
                )
                comptes["documents"] += 1
    finally:
        conn.close()

    if extraire:
        comptes.update(_extraire_pieces(manifest, db_path))
    return comptes


def _extraire_pieces(manifest: Mapping[str, Any], db_path: str | None) -> dict[str, int]:
    import db
    from adapters.ocr import OCRIndisponible
    from domain import documents as etats
    from domain.extraction import ExtractionInvalide, extraire_piece, persister

    comptes = {"extraits": 0, "en_attente": 0}
    conn = db.connect(db_path)
    try:
        for piece in manifest["_pieces"]:
            if not piece["demo"]:
                continue
            try:
                payload = extraire_piece(RACINE / piece["fichier"], backend="demo", ocr_backend="cache",
                                         clients=manifest["_donnees"]["clients"])
            except (OCRIndisponible, ExtractionInvalide):
                statut = etats.EN_ATTENTE_IA
                comptes["en_attente"] += 1
                with db.transaction(conn):
                    conn.execute("UPDATE documents SET statut=? WHERE id=?", (statut, piece["id"]))
                continue
            with db.transaction(conn):
                persister(conn, piece["id"], payload)
                conn.execute("UPDATE documents SET statut=? WHERE id=?", (etats.EXTRAIT, piece["id"]))
            comptes["extraits"] += 1
    finally:
        conn.close()
    return comptes


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Génère le jeu WÉMA reproductible")
    parser.add_argument("--reset", action="store_true",
                        help="réinitialise la base et y charge référentiels, historique et 96 pièces")
    parser.add_argument("--as-of", default=settings.as_of, help="date de référence ISO")
    parser.add_argument("--force", action="store_true", help="autorise l'écrasement sans --reset")
    parser.add_argument("--sans-extraction", action="store_true",
                        help="avec --reset : charge les pièces sans les extraire")
    args = parser.parse_args(argv)
    manifest = generer(reset=False, as_of=args.as_of, force=args.force)
    print(
        f"Corpus WÉMA : {manifest['evaluation']['documents']} documents annotés "
        f"({manifest['evaluation']['split']['dev']} dev / "
        f"{manifest['evaluation']['split']['validation']} validation / "
        f"{manifest['evaluation']['split']['test']} test), "
        f"{manifest['referentiels']['clients']} clients, "
        f"{manifest['referentiels']['articles']} articles."
    )
    print(f"Empreinte : {manifest['empreinte']}")
    if args.reset:
        comptes = charger_base(manifest, extraire=not args.sans_extraction)
        print(
            f"Base : {comptes['documents']} pièces chargées, {comptes.get('extraits', 0)} extraites, "
            f"{comptes.get('en_attente', 0)} en attente d'OCR ; 60 factures, 9 avoirs, 18 paiements."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
