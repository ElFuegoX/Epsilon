"""OCR local et analyse de mise en page.

Contrat public : ``lire(chemin)`` retourne une liste de blocs
``{text, page, bbox, confidence, method}``. ``bbox`` est exprimé en
pourcentage de la page : ``[x, y, largeur, hauteur]`` avec origine en haut
à gauche. Ce format est celui qu'affiche la visionneuse de Jean-Marie.

Le mode ``demo`` ne dépend d'aucun service : il relit les blocs OCR
enregistrés par ``seed.py`` à côté de chaque pièce synthétique. Pour un
fichier inconnu, on essaie successivement PyMuPDF, pypdf, Tesseract puis
un découpage déterministe du texte brut.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
GENERE = RACINE / "seeds" / "generated"

_INDEX: dict[str, Path] | None = None


class OCRIndisponible(RuntimeError):
    """Aucun moteur OCR local disponible pour ce fichier."""


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _index_sidecars() -> dict[str, Path]:
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        for chemin in GENERE.rglob("*.layout.json"):
            try:
                donnees = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            empreinte = donnees.get("sha256")
            if empreinte:
                _INDEX.setdefault(empreinte, chemin)
    return _INDEX


def _sidecar(chemin: Path) -> Path | None:
    direct = chemin.with_name(chemin.stem + ".layout.json")
    if direct.is_file():
        return direct
    return _index_sidecars().get(_sha256(chemin))


def _pourcent(x0: float, y0: float, x1: float, y1: float, largeur: float, hauteur: float) -> list[float]:
    if not largeur or not hauteur:
        return [0.0, 0.0, 100.0, 100.0]
    return [
        round(max(0.0, min(100.0, x0 / largeur * 100)), 2),
        round(max(0.0, min(100.0, y0 / hauteur * 100)), 2),
        round(max(0.0, min(100.0, (x1 - x0) / largeur * 100)), 2),
        round(max(0.0, min(100.0, (y1 - y0) / hauteur * 100)), 2),
    ]


def _bloc(texte: str, page: int, bbox: list[float], confidence: float, method: str) -> dict[str, Any]:
    return {
        "text": str(texte).strip(),
        "page": int(page),
        "bbox": [float(v) for v in bbox],
        "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
        "method": method,
    }


def _depuis_sidecar(chemin: Path, sidecar: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    donnees = json.loads(sidecar.read_text(encoding="utf-8"))
    blocs: list[dict[str, Any]] = []
    for brut in donnees.get("blocks", []):
        texte = brut.get("texte", brut.get("text", ""))
        if not texte:
            continue
        blocs.append(_bloc(
            texte,
            brut.get("page", 1),
            brut.get("bbox", [0, 0, 100, 4]),
            brut.get("confiance", brut.get("confidence", 0.9)),
            brut.get("methode", brut.get("method", "ocr")),
        ))
    blocs.sort(key=lambda b: (b["page"], b["bbox"][1], b["bbox"][0]))
    metadonnees = {
        "sha256": donnees.get("sha256", _sha256(chemin)),
        "page_size": donnees.get("page_size"),
        "bbox_unite": "pourcent",
        "degradation": donnees.get("degradation"),
        "reference": donnees.get("reference"),
        "document_type": donnees.get("document_type"),
        "split": donnees.get("split"),
    }
    return blocs, metadonnees


def _depuis_pdf(chemin: Path) -> list[dict[str, Any]]:
    try:
        import fitz  # PyMuPDF, optionnel
    except ImportError:
        fitz = None
    if fitz is not None:
        blocs: list[dict[str, Any]] = []
        with fitz.open(chemin) as document:
            for numero, page in enumerate(document, start=1):
                largeur, hauteur = page.rect.width, page.rect.height
                for x0, y0, x1, y1, texte, *_ in page.get_text("blocks"):
                    if not str(texte).strip():
                        continue
                    blocs.append(_bloc(
                        texte, numero,
                        _pourcent(x0, y0, x1, y1, largeur, hauteur),
                        0.88, "mise_en_page",
                    ))
        if blocs:
            return blocs

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise OCRIndisponible("PDF illisible : PyMuPDF et pypdf sont absents") from exc
    lecteur = PdfReader(str(chemin))
    blocs = []
    for numero, page in enumerate(lecteur.pages, start=1):
        for rang, ligne in enumerate((page.extract_text() or "").splitlines()):
            if not ligne.strip():
                continue
            y = 4 + rang * 4
            blocs.append(_bloc(ligne, numero, [4, y, 92, 3.2], 0.72, "pypdf"))
    return blocs


def _depuis_image(chemin: Path) -> list[dict[str, Any]]:
    try:
        import pytesseract
        from PIL import Image
        from pytesseract import Output
    except ImportError as exc:
        raise OCRIndisponible("image illisible : pytesseract/Pillow sont absents") from exc
    with Image.open(chemin) as image:
        largeur, hauteur = image.size
        données = pytesseract.image_to_data(image, output_type=Output.DICT)
    blocs: list[dict[str, Any]] = []
    for index, texte in enumerate(données.get("text", [])):
        if not str(texte).strip():
            continue
        try:
            confiance = float(données["conf"][index]) / 100
        except (TypeError, ValueError, IndexError):
            confiance = 0.5
        bbox = _pourcent(
            float(données["left"][index]), float(données["top"][index]),
            float(données["left"][index]) + float(données["width"][index]),
            float(données["top"][index]) + float(données["height"][index]),
            largeur, hauteur,
        )
        blocs.append(_bloc(texte, 1, bbox, confiance, "tesseract"))
    if not blocs:
        raise OCRIndisponible("aucun texte reconnu dans l'image")
    return blocs


def _depuis_texte(chemin: Path) -> list[dict[str, Any]]:
    blocs = []
    for rang, ligne in enumerate(chemin.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not ligne.strip():
            continue
        blocs.append(_bloc(ligne, 1, [4, 4 + rang * 4.5, 92, 3.5], 1.0, "texte"))
    return blocs


def lire(chemin: str | Path) -> list[dict[str, Any]]:
    """Lit une pièce et retourne ses blocs OCR avec provenance."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise FileNotFoundError(f"pièce introuvable : {chemin}")
    sidecar = _sidecar(chemin)
    if sidecar is not None:
        blocs, _ = _depuis_sidecar(chemin, sidecar)
        if blocs:
            return blocs
    suffixe = chemin.suffix.lower()
    if suffixe == ".pdf":
        return _depuis_pdf(chemin)
    if suffixe in (".png", ".jpg", ".jpeg", ".webp"):
        return _depuis_image(chemin)
    if suffixe in (".txt", ".md"):
        return _depuis_texte(chemin)
    raise OCRIndisponible(f"format non pris en charge : {suffixe or 'sans extension'}")


def metadonnees(chemin: str | Path) -> dict[str, Any]:
    """Informations de provenance du fichier, sans déclencher d'OCR."""
    chemin = Path(chemin)
    sidecar = _sidecar(chemin)
    if sidecar is None:
        return {"sha256": _sha256(chemin), "bbox_unite": "inconnue"}
    _, donnees = _depuis_sidecar(chemin, sidecar)
    return donnees
