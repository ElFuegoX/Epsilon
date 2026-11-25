"""OCR local et analyse de mise en page.

Contrat public : ``lire(chemin)`` retourne une liste de **lignes** ``{text,
page, bbox, confidence, method, words}``. ``bbox`` est en pourcentage de la
page ``[x, y, largeur, hauteur]``, origine en haut à gauche (format de la
visionneuse). ``words`` garde chaque mot avec sa propre bbox, sa confiance et
sa position redressée (``xr``), utilisée pour retrouver les colonnes.

Lecteurs réels :

* PDF : couche texte lue par ``pdfplumber`` (mots et coordonnées exacts) ;
  un PDF sans couche texte est rendu en image puis passé à EasyOCR ;
* image : ``EasyOCR`` (local, sans clé ; poids téléchargés une seule fois) ;
* texte : une ligne = une ligne, sans OCR.

Le mode ``demo`` rejoue un **cache de sorties OCR réelles**
(``seeds/ocr_cache/<empreinte>.json``) : il reste hors ligne et déterministe
sans que l'extraction lise jamais la vérité du générateur. Une image absente
du cache, sans EasyOCR installé, lève ``OCRIndisponible`` : la pièce reste en
``EN_ATTENTE_IA``, rien n'est inventé.

``backend="rendu"`` est une ablation de mesure (« OCR parfait ») : il relit
le ``.render.json`` du générateur. Il n'est utilisé que par ``domain.metrics``.

CLI : ``python -m adapters.ocr --warm`` remplit le cache sur le corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from config import settings

RACINE = Path(__file__).resolve().parents[1]
GENERE = RACINE / "seeds" / "generated"
CACHE = Path(os.getenv("WEMA_OCR_CACHE", str(RACINE / "seeds" / "ocr_cache")))
VERSION_CACHE = 2
# Réglages du détecteur : sans eux, les chiffres isolés (n° de ligne, quantité, remise « 0 »)
# ne sont pas détectés. Mesuré sur CMD-2026-101 le 25/11/2026.
PARAMS_EASYOCR = {"paragraph": False, "width_ths": 0.3, "min_size": 4, "low_text": 0.3, "mag_ratio": 1.5}
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
BACKENDS_OCR = ("auto", "cache", "reel", "rendu", "vlm")
CONFIANCE_COUCHE_TEXTE = 0.99  # texte lu dans le PDF, pas reconnu sur des pixels


class OCRIndisponible(RuntimeError):
    """Aucun lecteur disponible pour ce fichier : on échoue au lieu d'inventer."""


# --------------------------------------------------------------------------
# Empreintes
# --------------------------------------------------------------------------

def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def empreinte_contenu(chemin: str | Path) -> str:
    """Pixels décodés pour une image, octets sinon.

    Deux zlib différents peuvent encoder les mêmes pixels en PNG différents :
    la clé du cache doit survivre à un changement de machine.
    """
    chemin = Path(chemin)
    if chemin.suffix.lower() in IMAGES:
        from PIL import Image

        with Image.open(chemin) as image:
            image = image.convert("RGB")
            h = hashlib.sha256(f"{image.size[0]}x{image.size[1]}:".encode("ascii"))
            h.update(image.tobytes())
            return "px-" + h.hexdigest()
    return _sha256(chemin)


# --------------------------------------------------------------------------
# Lecteurs : chacun produit des pages {numero, largeur, hauteur, methode, mots}
# avec des mots {text, box: [x0, y0, x1, y1] dans l'unité de la page, confidence, angle}.
# --------------------------------------------------------------------------

def _page(numero: int, largeur: float, hauteur: float, methode: str,
          mots: list[dict[str, Any]]) -> dict[str, Any]:
    return {"numero": numero, "largeur": float(largeur), "hauteur": float(hauteur),
            "methode": methode, "mots": mots}


def _pages_pdf(chemin: Path) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise OCRIndisponible("PDF illisible : pdfplumber est absent (pip install pdfplumber)") from exc
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(chemin) as document:
        for numero, page in enumerate(document.pages, start=1):
            mots = [
                {"text": m["text"], "box": [m["x0"], m["top"], m["x1"], m["bottom"]],
                 "confidence": CONFIANCE_COUCHE_TEXTE, "angle": 0.0}
                for m in page.extract_words(x_tolerance=1.5, y_tolerance=2)
                if str(m.get("text", "")).strip()
            ]
            if mots:
                pages.append(_page(numero, page.width, page.height, "pdf_texte", mots))
                continue
            # PDF scanné : aucune couche texte, on lit les pixels.
            image = page.to_image(resolution=150).original
            pages.append({**_page_image(image, numero), "methode": "pdf_scan+easyocr"})
    return pages


_LECTEUR: Any = None


def easyocr_disponible() -> bool:
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return False
    return True


def _lecteur() -> Any:
    global _LECTEUR
    if _LECTEUR is None:
        try:
            import easyocr
        except ImportError as exc:
            raise OCRIndisponible(
                "image illisible : EasyOCR absent (pip install -r requirements-ocr.txt) "
                "et aucune lecture en cache"
            ) from exc
        _LECTEUR = easyocr.Reader(["fr"], gpu=False, verbose=False)
    return _LECTEUR


def _decouper(texte: str, x0: float, y0: float, x1: float, y1: float,
              confiance: float, angle: float) -> list[dict[str, Any]]:
    """EasyOCR rend parfois une expression : on la découpe en mots, à proportion des caractères."""
    morceaux = texte.split()
    if len(morceaux) <= 1:
        return [{"text": texte.strip(), "box": [x0, y0, x1, y1], "confidence": confiance, "angle": angle}]
    largeur_car = (x1 - x0) / max(1, len(texte))
    mots, position = [], 0
    for morceau in morceaux:
        debut = texte.index(morceau, position)
        position = debut + len(morceau)
        mots.append({"text": morceau,
                     "box": [x0 + debut * largeur_car, y0, x0 + position * largeur_car, y1],
                     "confidence": confiance, "angle": angle})
    return mots


def _page_image(image: Any, numero: int = 1) -> dict[str, Any]:
    lecteur = _lecteur()  # lève OCRIndisponible si EasyOCR manque
    import numpy as np  # installé avec EasyOCR

    image = image.convert("RGB")
    resultats = lecteur.readtext(np.array(image), detail=1, **PARAMS_EASYOCR)
    mots: list[dict[str, Any]] = []
    for quad, texte, confiance in resultats:
        if not str(texte).strip():
            continue
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        angle = math.degrees(math.atan2(float(quad[1][1]) - float(quad[0][1]),
                                        float(quad[1][0]) - float(quad[0][0])))
        mots.extend(_decouper(str(texte), min(xs), min(ys), max(xs), max(ys),
                              round(float(confiance), 4), round(angle, 3)))
    if not mots:
        raise OCRIndisponible("aucun texte reconnu dans l'image")
    return _page(numero, image.size[0], image.size[1], "easyocr", mots)


def _pages_image(chemin: Path) -> list[dict[str, Any]]:
    from PIL import Image

    with Image.open(chemin) as image:
        return [_page_image(image)]


def _pages_texte(chemin: Path) -> list[dict[str, Any]]:
    """Message : une ligne de texte = une ligne. Géométrie en caractères."""
    lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    largeur = max([len(l) for l in lignes] + [80])
    mots: list[dict[str, Any]] = []
    for rang, ligne in enumerate(lignes):
        mots.extend(_decouper(ligne, 0, rang * 1.5, len(ligne), rang * 1.5 + 1, 1.0, 0.0)
                    if ligne.strip() else [])
    return [_page(1, largeur, max(1.5 * len(lignes), 40), "texte", mots)]


def _pages_rendu(chemin: Path) -> list[dict[str, Any]]:
    """Ablation « OCR parfait » : le texte exact dessiné par le générateur."""
    rendu = chemin.with_name(chemin.stem + ".render.json")
    if not rendu.is_file():
        raise OCRIndisponible("aucun rendu de référence pour cette pièce")
    donnees = json.loads(rendu.read_text(encoding="utf-8"))
    mots: list[dict[str, Any]] = []
    for element in donnees.get("elements", []):
        x, y, w, h = (float(v) for v in element["bbox"])
        mots.extend(_decouper(element["texte"], x, y, x + w, y + h, 1.0, 0.0))
    return [_page(1, 100.0, 100.0, "rendu_parfait", mots)]


def _pages_vlm(chemin: Path) -> list[dict[str, Any]]:
    """Backend VLM optionnel (PaddleOCR-VL, MinerU, Docling…) via un endpoint.

    Le service répond avec des blocs en pourcentage de page. Sans endpoint,
    on échoue au lieu de retomber silencieusement sur un autre lecteur.
    """
    endpoint = os.getenv("WEMA_VLM_ENDPOINT", "").strip()
    if not endpoint:
        raise OCRIndisponible("WEMA_VLM_ENDPOINT absent : backend vlm non utilisable")
    corps = json.dumps(
        {"path": str(chemin), "bbox_unite": "pourcent", "model": os.getenv("WEMA_VLM_MODEL", "auto")},
        ensure_ascii=False,
    ).encode("utf-8")
    requete = urllib.request.Request(
        endpoint, data=corps, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(requete, timeout=settings.ai_timeout_s) as reponse:
            donnees = json.loads(reponse.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise OCRIndisponible(f"service VLM indisponible : {exc}") from exc
    mots: list[dict[str, Any]] = []
    for item in donnees.get("blocks", donnees.get("blocs", [])):
        texte = str((item or {}).get("text", (item or {}).get("texte", ""))).strip()
        if not texte:
            continue
        x, y, w, h = (float(v) for v in item.get("bbox", [0.0, 0.0, 100.0, 100.0]))
        mots.extend(_decouper(texte, x, y, x + w, y + h,
                              float(item.get("confidence", item.get("confiance", 0.5))), 0.0))
    if not mots:
        raise OCRIndisponible("le service VLM n'a renvoyé aucun bloc")
    return [_page(1, 100.0, 100.0, "vlm", mots)]


# --------------------------------------------------------------------------
# Cache des lectures réelles
# --------------------------------------------------------------------------

def _chemin_cache(cle: str) -> Path:
    return CACHE / f"{cle}.json"


def _lire_cache(cle: str) -> list[dict[str, Any]] | None:
    chemin = _chemin_cache(cle)
    if not chemin.is_file():
        return None
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    if donnees.get("version") != VERSION_CACHE:
        return None
    return donnees["pages"]


def _ecrire_cache(cle: str, source: Path, pages: list[dict[str, Any]], duree_s: float) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        import easyocr
        moteur = f"easyocr {easyocr.__version__}"
    except ImportError:
        moteur = "inconnu"
    contenu = {
        "version": VERSION_CACHE,
        "source": source.name,
        "moteur": moteur,
        "parametres": PARAMS_EASYOCR,
        "duree_s": round(duree_s, 2),
        "pages": [{**p, "mots": [{**m, "box": [round(v, 2) for v in m["box"]]} for m in p["mots"]]}
                  for p in pages],
    }
    _chemin_cache(cle).write_text(json.dumps(contenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _pages_reelles(chemin: Path) -> list[dict[str, Any]]:
    suffixe = chemin.suffix.lower()
    if suffixe == ".pdf":
        return _pages_pdf(chemin)
    if suffixe in IMAGES:
        return _pages_image(chemin)
    if suffixe in (".txt", ".md"):
        return _pages_texte(chemin)
    raise OCRIndisponible(f"format non pris en charge : {suffixe or 'sans extension'}")


def lire_pages(chemin: str | Path, backend: str | None = None) -> list[dict[str, Any]]:
    """Mots bruts par page, selon le backend (voir le docstring du module)."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise FileNotFoundError(f"pièce introuvable : {chemin}")
    choix = (backend or os.getenv("WEMA_OCR_BACKEND", "auto")).strip().lower()
    if choix not in BACKENDS_OCR:
        raise OCRIndisponible(f"backend OCR inconnu : {choix}")
    if choix == "vlm":
        return _pages_vlm(chemin)
    if choix == "rendu":
        return _pages_rendu(chemin)

    suffixe = chemin.suffix.lower()
    couteux = suffixe in IMAGES  # seules les images passent par EasyOCR
    cle = empreinte_contenu(chemin) if couteux else None
    if couteux and choix in ("auto", "cache"):
        en_cache = _lire_cache(cle)
        if en_cache is not None:
            return en_cache
        if choix == "cache":
            raise OCRIndisponible("image absente du cache OCR et lecture réelle désactivée")
    debut = time.perf_counter()
    pages = _pages_reelles(chemin)
    if couteux:
        _ecrire_cache(cle, chemin, pages, time.perf_counter() - debut)
    return pages


# --------------------------------------------------------------------------
# Mise en page : mots -> lignes, avec redressement de l'inclinaison
# --------------------------------------------------------------------------

def _chainer(mots: list[dict[str, Any]], hauteur_type: float, pente: float) -> list[list[dict[str, Any]]]:
    """Regroupe les mots en lignes, de gauche à droite.

    Chaque mot rejoint la ligne dont le dernier mot est à sa hauteur, en tenant
    compte de la pente : sur une photo en perspective, la droite d'une rangée
    peut être une demi-rangée plus haut que sa gauche. Un regroupement par
    hauteur globale couperait alors l'en-tête du tableau en deux.
    """
    chaines: list[list[dict[str, Any]]] = []
    for mot in sorted(mots, key=lambda m: (m["x0"], m["yc"])):
        meilleure, meilleur_ecart = None, 0.6 * hauteur_type
        for chaine in chaines:
            dernier = chaine[-1]
            if dernier["x1"] > mot["x0"] + 0.5 * hauteur_type:
                continue  # chevauchement horizontal : ce sont deux lignes empilées
            attendu = dernier["yc"] + pente * (mot["xc"] - dernier["xc"])
            ecart = abs(mot["yc"] - attendu)
            if ecart < meilleur_ecart:
                meilleure, meilleur_ecart = chaine, ecart
        if meilleure is None:
            chaines.append([mot])
        else:
            meilleure.append(mot)
    return chaines


def _pente(chaines: list[list[dict[str, Any]]], largeur: float) -> float:
    """Pente médiane des lignes longues (dy/dx), mesurée sur les mots eux-mêmes.

    EasyOCR rend presque toujours des rectangles droits : l'angle de ses boîtes
    ne dit rien de l'inclinaison de la photo.
    """
    pentes = []
    for chaine in chaines:
        if len(chaine) < 3 or chaine[-1]["xc"] - chaine[0]["xc"] < 0.15 * largeur:
            continue
        xs = [m["xc"] for m in chaine]
        ys = [m["yc"] for m in chaine]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        variance = sum((x - mx) ** 2 for x in xs)
        if variance:
            pentes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / variance)
    return statistics.median(pentes) if pentes else 0.0


def lignes_depuis_pages(pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    lignes: list[dict[str, Any]] = []
    for page in pages:
        largeur, hauteur = page["largeur"], page["hauteur"]
        prepares = []
        for mot in page["mots"]:
            x0, y0, x1, y1 = (float(v) for v in mot["box"])
            prepares.append({**mot, "x0": x0, "x1": x1, "xc": (x0 + x1) / 2, "yc": (y0 + y1) / 2,
                             "h": max(1e-6, y1 - y0)})
        if not prepares:
            continue
        hauteur_type = statistics.median(m["h"] for m in prepares)
        # La bonne pente est celle qui regroupe les mots en le moins de lignes
        # (±0,1, soit environ ±6°) ; on l'affine ensuite par régression sur ces lignes.
        candidates = [i * 0.005 for i in range(-20, 21)]
        grossiere = min(candidates, key=lambda p: (len(_chainer(prepares, hauteur_type, p)), abs(p)))
        pente = _pente(_chainer(prepares, hauteur_type, grossiere), largeur) or grossiere
        groupes = _chainer(prepares, hauteur_type, pente)
        theta = math.atan(pente)
        cos, sin = math.cos(theta), math.sin(theta)
        cx, cy = largeur / 2, hauteur / 2
        for mot in prepares:
            mx, my = mot["xc"] - cx, mot["yc"] - cy
            # rotation inverse : position horizontale « page d'aplomb », pour les colonnes
            xr = mx * cos + my * sin + cx
            demi = (mot["x1"] - mot["x0"]) / 2
            mot["xr0"], mot["xr1"] = xr - demi, xr + demi
        for groupe in groupes:
            groupe.sort(key=lambda m: m["xr0"])
            x0 = min(m["box"][0] for m in groupe)
            y0 = min(m["box"][1] for m in groupe)
            x1 = max(m["box"][2] for m in groupe)
            y1 = max(m["box"][3] for m in groupe)
            lignes.append({
                "text": " ".join(str(m["text"]).strip() for m in groupe),
                "page": int(page["numero"]),
                "bbox": _pourcent(x0, y0, x1, y1, largeur, hauteur),
                "confidence": round(statistics.fmean(float(m["confidence"]) for m in groupe), 4),
                "method": page["methode"],
                "words": [{
                    "text": str(m["text"]).strip(),
                    "bbox": _pourcent(*m["box"], largeur, hauteur),
                    "confidence": round(float(m["confidence"]), 4),
                    "xr": [round(m["xr0"] / largeur * 100, 2), round(m["xr1"] / largeur * 100, 2)],
                    "h": round(m["h"] / hauteur * 100, 3),
                } for m in groupe],
            })
    lignes.sort(key=lambda l: (l["page"], l["bbox"][1], l["bbox"][0]))
    return lignes


def _pourcent(x0: float, y0: float, x1: float, y1: float, largeur: float, hauteur: float) -> list[float]:
    if not largeur or not hauteur:
        return [0.0, 0.0, 100.0, 100.0]
    return [
        round(max(0.0, min(100.0, x0 / largeur * 100)), 2),
        round(max(0.0, min(100.0, y0 / hauteur * 100)), 2),
        round(max(0.0, min(100.0, (x1 - x0) / largeur * 100)), 2),
        round(max(0.0, min(100.0, (y1 - y0) / hauteur * 100)), 2),
    ]


def lire(chemin: str | Path, backend: str | None = None) -> list[dict[str, Any]]:
    """Lit une pièce et retourne ses lignes avec provenance."""
    return lignes_depuis_pages(lire_pages(chemin, backend))


def metadonnees(chemin: str | Path) -> dict[str, Any]:
    """Informations de provenance du fichier, sans déclencher d'OCR."""
    chemin = Path(chemin)
    infos: dict[str, Any] = {"sha256": _sha256(chemin), "empreinte_contenu": empreinte_contenu(chemin),
                             "bbox_unite": "pourcent"}
    rendu = chemin.with_name(chemin.stem + ".render.json")
    if rendu.is_file():
        donnees = json.loads(rendu.read_text(encoding="utf-8"))
        for cle in ("reference", "document_type", "split", "degradation", "page_size"):
            infos[cle] = donnees.get(cle)
    return infos


# --------------------------------------------------------------------------
# CLI : remplir le cache sur le corpus généré
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Cache OCR réel du corpus WÉMA")
    parser.add_argument("--warm", action="store_true", help="lit toutes les images du corpus et met en cache")
    parser.add_argument("--force", action="store_true", help="relit même ce qui est déjà en cache")
    parser.add_argument("chemins", nargs="*", help="fichiers précis (sinon tout seeds/generated)")
    args = parser.parse_args(argv)
    if not args.warm and not args.chemins:
        parser.print_help()
        return 1
    fichiers = [Path(c) for c in args.chemins] or sorted(
        p for p in GENERE.rglob("*") if p.suffix.lower() in IMAGES
    )
    for numero, fichier in enumerate(fichiers, start=1):
        cle = empreinte_contenu(fichier)
        if not args.force and _lire_cache(cle) is not None:
            print(f"[{numero}/{len(fichiers)}] {fichier.name} : déjà en cache")
            continue
        debut = time.perf_counter()
        pages = lire_pages(fichier, backend="reel")
        print(f"[{numero}/{len(fichiers)}] {fichier.name} : {sum(len(p['mots']) for p in pages)} mots "
              f"en {time.perf_counter() - debut:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
