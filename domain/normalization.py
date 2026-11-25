"""Normalisation : produit une valeur comparable sans toucher à la valeur brute."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from config import settings

MOIS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
NOMBRES = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}
UNITES = {
    "pcs": "pcs", "pc": "pcs", "pièce": "pcs", "pièces": "pcs", "pieces": "pcs",
    "unité": "pcs", "unités": "pcs", "unite": "pcs", "unit": "pcs",
    "m": "m", "ml": "ml", "m2": "m²", "m²": "m²", "kg": "kg",
    "forfait": "forfait", "jour": "jour", "h": "h",
}


def reference_date() -> date:
    return date.fromisoformat(settings.as_of)


def normalize_date(value: object, reference: date | None = None) -> str | None:
    """ISO 8601. L'année est déduite de AS_OF, jamais du jour courant."""
    if value is None:
        return None
    texte = str(value).strip().lower().replace("\u00a0", " ")
    ref = reference or reference_date()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texte):
        return texte
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})", texte)
    if match:
        jour, mois, annee = (int(x) for x in match.groups())
        if annee < 100:
            annee += 2000 if annee <= ref.year % 100 + 10 else 1900
        try:
            return date(annee, mois, jour).isoformat()
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", texte)
    if match:
        jour, mois = (int(x) for x in match.groups())
        try:
            return date(ref.year, mois, jour).isoformat()
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", texte)
    if match and match.group(2) in MOIS:
        jour, mois, annee = int(match.group(1)), MOIS[match.group(2)], int(match.group(3))
        try:
            return date(annee, mois, jour).isoformat()
        except ValueError:
            return None
    return None


def normalize_amount(value: object) -> int | None:
    """Entier FCFA. Renvoie None si l'écriture est ambiguë."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if isinstance(value, int):
        return value
    texte = str(value).strip()
    texte = re.sub(r"(?i)\b(fcfa|f\.cfa|francs?|xof)\b\.?", "", texte)
    texte = texte.replace("\u00a0", " ").replace(" ", "").replace("'", "")
    texte = texte.strip("Ff")
    if not texte:
        return None
    if "." in texte and "," in texte:
        return None  # plusieurs interprétations possibles
    if "," in texte:
        parties = texte.split(",")
        if len(parties) == 2 and len(parties[1]) in (1, 2):
            texte = parties[0].replace(".", "") + "." + parties[1]
        else:
            texte = texte.replace(",", "")
    elif texte.count(".") > 1:
        texte = texte.replace(".", "")
    try:
        return int(Decimal(texte).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def normalize_quantity(value: object) -> str | None:
    """Décimale à trois chiffres maximum, unité séparée."""
    if value is None:
        return None
    texte = str(value).strip().lower().replace("\u00a0", " ")
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:pcs|pièces?|unités?|m²|m2|m|kg|ml|forfait|h)?", texte)
    if match:
        nombre = Decimal(match.group(1).replace(",", "."))
    elif texte in NOMBRES:
        nombre = Decimal(NOMBRES[texte])
    else:
        return None
    if -nombre.as_tuple().exponent > 3:
        return None
    return format(nombre.normalize(), "f")


def normalize_unit(value: object) -> str | None:
    if value is None:
        return None
    texte = str(value).strip().lower().replace("\u00a0", "")
    return UNITES.get(texte, None)


def normalize_tax(value: object) -> int | None:
    """Taux en points de base. None = taux hors référentiel (à bloquer)."""
    if value is None:
        return None
    texte = str(value).strip().lower().replace(",", ".")
    if any(mot in texte for mot in ("exon", "0 %", "0%")):
        return 0
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", texte)
    if match:
        return int(Decimal(match.group(1)) * 100)
    if re.fullmatch(r"\d+(?:\.\d+)?", texte):
        nombre = Decimal(texte)
        return int(nombre * 100) if nombre <= 1 else int(nombre)
    return None


def normalize_text(value: object) -> str:
    """Forme comparaison : minuscules, sans accents ni ponctuation."""
    import unicodedata

    if value is None:
        return ""
    texte = str(value).lower()
    texte = "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()
