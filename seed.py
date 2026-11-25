"""Jeu de démonstration et corpus d'évaluation reproductibles (graine 20261125).

Deux jeux distincts, tous deux fictifs :

* 96 pièces de démonstration : 40 devis PDF, 30 photos de commande,
  16 messages, 10 bons de livraison ;
* 120 documents annotés pour l'évaluation : les 96 pièces ci-dessus
  plus 24 documents d'évaluation (4 messages, 10 BL, 10 cas dégradés).

Le mode `AI_BACKEND=demo` lit les blocs OCR synchrones écrits par cette
graine. Aucune donnée réelle, aucun réseau, aucune horloge courante.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import settings

RACINE = Path(__file__).resolve().parent
GENERE = RACINE / "seeds" / "generated"
DORE = RACINE / "seeds" / "golden"

PAGE_LARGEUR = 595.28
PAGE_HAUTEUR = 841.89
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


def _arrondi(valeur: Decimal) -> int:
    return int(valeur.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fcfa(valeur: int) -> str:
    return f"{valeur:,}".replace(",", " ")


def _capturer_total(blocs: list[Mapping[str, Any]], libelle: str) -> int | None:
    """Valeur imprimée uniquement : aucune inférence, aucun calcul."""
    for bloc in blocs:
        texte = str(bloc.get("texte", ""))
        if libelle not in texte:
            continue
        correspondance = re.search(r":\s*([\d\s'.,]+)", texte)
        if correspondance:
            nombre = re.sub(r"[^\d]", "", correspondance.group(1))
            return int(nombre) if nombre else None
    return None


def _latin1(texte: str) -> bytes:
    """Le générateur PDF minimal n'écrit que du Latin-1 (Helvetica)."""
    return texte.replace("×", "x").replace("–", "-").replace("—", "-").encode("latin-1", "replace")


def _pdf_escape(texte: str) -> bytes:
    return _latin1(texte).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _ecrire_pdf(chemin: Path, lignes: Iterable[Mapping[str, Any]]) -> None:
    """PDF une page, sans dépendance : assez pour PDF.js et les empreintes."""
    flux = bytearray()
    flux.extend(b"1 0 0 rg\n")
    flux.extend(b"BT /F1 9 Tf 40 805 Td (" + _pdf_escape(SIMULATION) + b") Tj ET\n")
    flux.extend(b"0 0 0 rg\n")
    for ligne in lignes:
        x = float(ligne.get("x", 40))
        y_haut = float(ligne.get("y", 40))
        taille = float(ligne.get("taille", 10))
        y_pdf = PAGE_HAUTEUR - y_haut - taille
        flux.extend(
            b"BT /F1 " + str(taille).encode("ascii") + b" Tf "
            + f"1 0 0 1 {x:.2f} {y_pdf:.2f} Tm (".encode("ascii")
            + _pdf_escape(str(ligne.get("texte", "")))
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


def _bbox(x: float, y: float, texte: str, taille: float) -> list[float]:
    largeur = max(8.0, len(texte) * taille * 0.52)
    return [
        round(x / PAGE_LARGEUR * 100, 2),
        round(y / PAGE_HAUTEUR * 100, 2),
        round(largeur / PAGE_LARGEUR * 100, 2),
        round(taille * 1.35 / PAGE_HAUTEUR * 100, 2),
    ]


def _bloc(page: int, x: float, y: float, texte: str, taille: float, confiance: float) -> dict[str, Any]:
    return {
        "texte": _latin1(texte).decode("latin-1"),
        "page": page,
        "bbox": _bbox(x, y, texte, taille),
        "confiance": round(confiance, 3),
        "methode": "ocr",
    }


def _ecrire_png(chemin: Path, lignes: Iterable[Mapping[str, Any]], degradation: str | None) -> None:
    from PIL import Image, ImageDraw, ImageFont

    echelle = 2
    image = Image.new("RGB", (int(PAGE_LARGEUR * echelle), int(PAGE_HAUTEUR * echelle)), "white")
    dessin = ImageDraw.Draw(image)
    police = ImageFont.load_default()
    dessin.text((80, 40), SIMULATION, fill="red", font=police)
    for ligne in lignes:
        x = int(float(ligne.get("x", 40)) * echelle)
        y = int(float(ligne.get("y", 40)) * echelle)
        texte = _latin1(str(ligne.get("texte", ""))).decode("latin-1")
        dessin.text((x, y), texte, fill="black", font=police)
    if degradation == "rotation":
        image = image.rotate(2.5, expand=False, fillcolor="white")
    elif degradation == "ombre":
        gris = Image.new("RGB", image.size, "white")
        image = Image.blend(image, gris, 0.32)
    elif degradation == "tampon":
        dessin = ImageDraw.Draw(image)
        dessin.rectangle((620, 120, 1020, 190), outline="red", width=3)
        dessin.text((650, 140), "DUPLICATA - A VERIFIER", fill="red", font=police)
    image.save(chemin)


def _ecrire_texte(chemin: Path, lignes: Iterable[Mapping[str, Any]]) -> None:
    contenu = [SIMULATION] + [str(ligne.get("texte", "")) for ligne in lignes]
    chemin.write_text("\n".join(contenu) + "\n", encoding="utf-8")


def _ecrire_sidecar(chemin: Path, blocs: list[dict[str, Any]], sha256: str, **extra: Any) -> None:
    payload = {
        "sha256": sha256,
        "pages": 1,
        "page_size": [PAGE_LARGEUR, PAGE_HAUTEUR],
        "bbox_unite": "pourcent",
        "blocks": blocs,
        **extra,
    }
    destination = chemin.with_name(chemin.stem + ".layout.json")
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ecrire_piece(chemin: Path, lignes: list[dict[str, Any]], blocs: list[dict[str, Any]], kind: str,
                  degradation: str | None = None, **extra: Any) -> dict[str, Any]:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        _ecrire_pdf(chemin, lignes)
    elif kind == "png":
        _ecrire_png(chemin, lignes, degradation)
    elif kind == "txt":
        _ecrire_texte(chemin, lignes)
    else:
        raise ValueError(f"format inconnu: {kind}")
    empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
    _ecrire_sidecar(chemin, blocs, empreinte, degradation=degradation, **extra)
    return {"fichier": str(chemin.relative_to(RACINE)).replace("\\", "/"), "sha256": empreinte}


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
            "conditions": ("30 jours", 30),
        })
    return clients


def _articles(rng: random.Random) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for index in range(120):
        famille = FAMILLES_ITEMS[index % len(FAMILLES_ITEMS)]
        unite = TYPES_UNITE[index % len(TYPES_UNITE)]
        descriptif = f"Article {famille.lower()} {index + 1:03d}"
        prix = rng.randrange(5, 200) * 1000
        articles.append({
            "id": f"art-{index + 1:03d}",
            "reference": f"REF-{index + 1:04d}",
            "designation": descriptif,
            "unite": unite,
            "prix_catalogue": prix,
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
    # Écart positif = recalculé - imprimé, comme dans la vérité terrain témoin.
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


def _lignes_visuelles(lignes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Texte imprimé : chaque valeur nécessaire est présente, rien n'est déduit."""
    visuelles = [
        {"x": 40, "y": 44, "texte": "TABLEAU DES LIGNES", "taille": 10},
        {"x": 40, "y": 62, "texte": "N Designation Qte Unite PU HT Remise TVA Total HT", "taille": 9},
    ]
    for ligne in lignes:
        texte = (
            f"{ligne['line_no']}  {ligne['description']}  {ligne['quantity']} {ligne['unit']} "
            f"x {_fcfa(int(ligne['unit_price_ht']))} FCFA Remise 0 FCFA "
            f"TVA {ligne['tax_rate']} % Total {_fcfa(int(ligne['line_total_ht']))} FCFA"
        )
        if "delivered" in ligne:
            texte += f" Livre {ligne['delivered']}"
        visuelles.append({"x": 40, "y": 82 + int(ligne["line_no"]) * 20, "texte": texte, "taille": 9})
    return visuelles


def _blocs_lignes(lignes: list[Mapping[str, Any]], confiance: float) -> list[dict[str, Any]]:
    blocs: list[dict[str, Any]] = []
    for ligne in lignes:
        texte = (
            f"{ligne['line_no']}  {ligne['description']}  {ligne['quantity']} {ligne['unit']} "
            f"x {_fcfa(int(ligne['unit_price_ht']))} FCFA Remise 0 FCFA "
            f"TVA {ligne['tax_rate']} % Total {_fcfa(int(ligne['line_total_ht']))} FCFA"
        )
        if "delivered" in ligne:
            texte += f" Livre {ligne['delivered']}"
        blocs.append(_bloc(1, 40, 82 + int(ligne["line_no"]) * 20, texte, 9, confiance))
    return blocs


def _degrader_blocs(blocs: list[dict[str, Any]], degradation: str, rng: random.Random) -> None:
    """Simule des lectures OCR ambiguës : la pièce reste juste, la lecture non."""
    cibles = [b for b in blocs if " FCFA" in b["texte"] and "Total" in b["texte"]]
    if not cibles:
        return
    cible = cibles[rng.randrange(len(cibles))]
    if degradation == "ombre":
        cible["texte"] = re.sub(r"(\d) 000", r"\1 900", cible["texte"], count=1)
    elif degradation == "rotation":
        cible["texte"] = re.sub(r"\b4 pcs\b", "9 pcs", cible["texte"], count=1)
        if cible["texte"] == blocs[0]["texte"]:
            cible["texte"] = re.sub(r"\b2 pcs\b", "7 pcs", cible["texte"], count=1)
    elif degradation == "tampon":
        for bloc in blocs:
            if "Client :" in bloc["texte"]:
                bloc["texte"] = re.sub(r"Materiaux|Menuiserie|Textile", "Mater.", bloc["texte"], count=1)
                break
    for bloc in blocs:
        bloc["confiance"] = round(bloc["confiance"] * 0.55, 3)


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


def generer(reset: bool = False, as_of: str | None = None, force: bool = False,
            out: Path | None = None) -> dict[str, Any]:
    """Génère le corpus. Idempotent : mêmes arguments -> mêmes octets."""
    as_of = as_of or settings.as_of
    racine_sortie = Path(out) if out else GENERE
    racine_doree = racine_sortie.parent / "golden" if out else DORE
    if reset and not out:
        import db
        db.reset()
    racine_sortie.mkdir(parents=True, exist_ok=True)
    racine_doree.mkdir(parents=True, exist_ok=True)

    rng = random.Random(settings.graine_demo)
    clients = _clients(rng)
    articles = _articles(rng)
    date_ref = date.fromisoformat(as_of)
    annee = date_ref.year

    devis_refs = ["DEV-2026-041"] + [f"DEV-{annee}-{n:03d}" for n in range(1, 40)]
    refs_photos = [f"CMD-{annee}-{n:03d}" for n in range(101, 131)]
    refs_messages = [f"MSG-{annee}-{n:03d}" for n in range(201, 221)]
    refs_bl = [f"BL-{annee}-{n:03d}" for n in range(301, 321)]
    refs_degrades = [f"DEG-{annee}-{n:03d}" for n in range(401, 411)]

    proofs: list[dict[str, Any]] = []
    index = 0

    def enregistrer(ref: str, client: Mapping[str, Any], lignes: list[dict[str, Any]],
                    type_piece: str, famille: str, fichier: Path, kind: str,
                    blocs: list[dict[str, Any]], visuelles: list[dict[str, Any]],
                    totaux: dict[str, dict[str, int]], anomalie: str | None = None,
                    degradation: str | None = None, notes: str = "",
                    issue: str | None = None) -> None:
        nonlocal index
        meta = _ecrire_piece(
            fichier, visuelles, blocs, kind, degradation,
            reference=ref, document_type=type_piece, split=_split(index),
        )
        manquants = []
        if client.get("ifu") is None:
            manquants.append("ifu")
        if type_piece in ("devis", "commande", "message") and not any(
            "Echeance" in b["texte"] or "Échéance" in b["texte"] for b in blocs
        ):
            manquants.append("dates.due")
        conditions_presentes = any("Conditions :" in b["texte"] for b in blocs)
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
                "ht": _capturer_total(blocs, "Total HT") if any("Total HT imprime" in b["texte"] for b in blocs) else None,
                "vat": _capturer_total(blocs, "TVA 18") if any(re.search(r"TVA 18\s*%\s*:", b["texte"]) for b in blocs) else None,
                "ttc": _capturer_total(blocs, "Total TTC") if any("Total TTC imprime" in b["texte"] for b in blocs) else None,
            },
            "recalculated_totals": totaux["recalculated"],
            "expected_ecart": totaux["ecart"],
            "missing": manquants,
            "injected_anomalies": anomalies,
            "notes": notes,
        }
        if type_piece in ("devis", "bon_livraison"):
            truth["delivery"] = {
                str(l["line_no"]): l["delivered"] for l in lignes
            }
            truth["missing_line"] = next(
                (l["line_no"] for l in lignes if l["quantity"] != l["delivered"]), None
            )
        (racine_doree / f"{ref}.truth.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        proofs.append({"id": truth["id"], "reference": ref, "type": type_piece,
                       "family": famille, "split": truth["split"], "truth": f"golden/{ref}.truth.json"})
        index += 1

    # 40 devis PDF, témoin DEV-2026-041 en premier.
    for numero, ref in enumerate(devis_refs):
        client = clients[0] if ref == "DEV-2026-041" else clients[numero % len(clients)]
        if ref == "DEV-2026-041":
            lignes = _lignes_temoins()
            anomaly = "arithmetique"
        else:
            lignes = _lignes_quote(rng, articles, 2 + numero % 3)
            anomaly = "arithmetique" if numero % 7 == 2 else None
            if lignes and numero % 5 == 1:
                lignes[-1]["delivered"] = "0"
        totaux = _totaux(lignes, anomaly)
        issue = "2026-11-18" if ref == "DEV-2026-041" else (date_ref - timedelta(days=numero % 20)).isoformat()
        visuelles = [
            {"x": 40, "y": 34, "texte": f"DEVIS {ref}", "taille": 16},
            {"x": 400, "y": 36, "texte": f"Date : {issue}", "taille": 10},
            {"x": 40, "y": 62, "texte": f"Client : {client['raison_sociale']}", "taille": 11},
            {"x": 40, "y": 78, "texte": f"IFU : {client['ifu'] or '- absent de la piece -'}", "taille": 10},
            {"x": 40, "y": 94, "texte": "Conditions : 30 jours", "taille": 10},
        ] + _lignes_visuelles(lignes) + [
            {"x": 330, "y": 700, "texte": f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", "taille": 11},
            {"x": 330, "y": 720, "texte": f"TVA 18 % : {_fcfa(totaux['printed']['vat'])} FCFA", "taille": 11},
            {"x": 330, "y": 740, "texte": f"Total TTC imprime : {_fcfa(totaux['printed']['ttc'])} FCFA", "taille": 11},
        ]
        blocs = [
            _bloc(1, 40, 34, f"DEVIS {ref}", 16, 0.98),
            _bloc(1, 400, 36, f"Date : {issue}", 10, 0.97),
            _bloc(1, 40, 62, f"Client : {client['raison_sociale']}", 11, 0.95),
            _bloc(1, 40, 78, f"IFU : {client['ifu'] or '- absent de la piece -'}", 10, 0.96),
            _bloc(1, 40, 94, "Conditions : 30 jours", 10, 0.96),
            *_blocs_lignes(lignes, 0.94),
            _bloc(1, 330, 700, f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", 11, 0.96),
            _bloc(1, 330, 720, f"TVA 18 % : {_fcfa(totaux['printed']['vat'])} FCFA", 11, 0.95),
            _bloc(1, 330, 740, f"Total TTC imprime : {_fcfa(totaux['printed']['ttc'])} FCFA", 11, 0.96),
        ]
        enregistrer(ref, client, lignes, "devis", "devis",
                    racine_sortie / "demo" / "devis" / f"{ref}.pdf", "pdf",
                    blocs, visuelles, totaux, anomaly,
                    notes="IFU absent, ecart d'addition et installation non livree."
                    if ref == "DEV-2026-041" else "Devis synthetique.",
                    issue=issue)

    # 30 photos de commande.
    for numero, ref in enumerate(refs_photos):
        client = clients[(numero + 3) % len(clients)]
        lignes = _lignes_quote(rng, articles, 2 + numero % 2)
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        visuelles = [
            {"x": 40, "y": 34, "texte": f"COMMANDE {ref}", "taille": 16},
            {"x": 40, "y": 62, "texte": f"Client : {client['raison_sociale']}", "taille": 11},
            {"x": 40, "y": 78, "texte": f"IFU : {client['ifu'] or '- absent de la piece -'}", "taille": 10},
            {"x": 400, "y": 36, "texte": f"Date : {issue}", "taille": 10},
        ] + _lignes_visuelles(lignes) + [
            {"x": 330, "y": 700, "texte": f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", "taille": 11},
        ]
        blocs = [
            _bloc(1, 40, 34, f"COMMANDE {ref}", 16, 0.93),
            _bloc(1, 40, 62, f"Client : {client['raison_sociale']}", 11, 0.90),
            _bloc(1, 40, 78, f"IFU : {client['ifu'] or '- absent de la piece -'}", 10, 0.90),
            _bloc(1, 400, 36, f"Date : {issue}", 10, 0.92),
            *_blocs_lignes(lignes, 0.88),
            _bloc(1, 330, 700, f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", 11, 0.90),
        ]
        enregistrer(ref, client, lignes, "commande", "photo",
                    racine_sortie / "demo" / "photos" / f"{ref}.png", "png",
                    blocs, visuelles, totaux,
                    notes="Photo de commande synthetique, lecture OCR locale.",
                    issue=issue)

    # 20 messages (16 de démonstration + 4 d'évaluation).
    for numero, ref in enumerate(refs_messages):
        client = clients[(numero + 8) % len(clients)]
        lignes = _lignes_quote(rng, articles, 1 + numero % 2)
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        visuelles = [
            {"x": 40, "y": 34, "texte": f"MESSAGE {ref}", "taille": 15},
            {"x": 40, "y": 58, "texte": f"Client : {client['raison_sociale']}", "taille": 11},
            {"x": 40, "y": 74, "texte": "Objet : commande de mobilier", "taille": 10},
            {"x": 400, "y": 36, "texte": f"Date : {issue}", "taille": 10},
        ] + _lignes_visuelles(lignes)
        blocs = [
            _bloc(1, 40, 34, f"MESSAGE {ref}", 15, 0.98),
            _bloc(1, 40, 58, f"Client : {client['raison_sociale']}", 11, 0.94),
            _bloc(1, 40, 74, "Objet : commande de mobilier", 10, 0.95),
            _bloc(1, 400, 36, f"Date : {issue}", 10, 0.96),
            *_blocs_lignes(lignes, 0.91),
        ]
        dossier = "demo" if numero < 16 else "eval"
        # Un message libre ne porte pas d'IFU : la vérité doit le dire aussi.
        client = {**client, "ifu": None}
        enregistrer(ref, client, lignes, "message", "message",
                    racine_sortie / dossier / "messages" / f"{ref}.txt", "txt",
                    blocs, visuelles, totaux,
                    notes="Message libre : aucun IFU n'est present dans la piece.",
                    issue=issue)

    # 20 bons de livraison (10 de démonstration + 10 d'évaluation).
    for numero, ref in enumerate(refs_bl):
        client = clients[(numero + 11) % len(clients)]
        lignes = _lignes_quote(rng, articles, 2)
        if numero % 3 == 0:
            lignes[-1]["delivered"] = "0"
        totaux = _totaux(lignes, None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        visuelles = [
            {"x": 40, "y": 34, "texte": f"BON DE LIVRAISON {ref}", "taille": 15},
            {"x": 40, "y": 62, "texte": f"Client : {client['raison_sociale']}", "taille": 11},
            {"x": 40, "y": 78, "texte": f"IFU : {client['ifu'] or '- absent de la piece -'}", "taille": 10},
            {"x": 400, "y": 36, "texte": f"Date : {issue}", "taille": 10},
        ] + _lignes_visuelles(lignes)
        blocs = [
            _bloc(1, 40, 34, f"BON DE LIVRAISON {ref}", 15, 0.97),
            _bloc(1, 40, 62, f"Client : {client['raison_sociale']}", 11, 0.94),
            _bloc(1, 40, 78, f"IFU : {client['ifu'] or '- absent de la piece -'}", 10, 0.95),
            _bloc(1, 400, 36, f"Date : {issue}", 10, 0.96),
            *_blocs_lignes(lignes, 0.92),
        ]
        dossier = "demo" if numero < 10 else "eval"
        anomalie = "QUANTITY_MISMATCH" if numero % 3 == 0 else None
        enregistrer(ref, client, lignes, "bon_livraison", "bon_livraison",
                    racine_sortie / dossier / "livraisons" / f"{ref}.pdf", "pdf",
                    blocs, visuelles, totaux, anomalie,
                    notes="Ligne non livree : decision humaine obligatoire."
                    if anomalie else "Bon de livraison synthetique.",
                    issue=issue)

    # 10 cas dégradés : mêmes champs, lecture OCR ambiguë simulée.
    degradations = ("rotation", "ombre", "tampon") * 4
    for numero, ref in enumerate(refs_degrades):
        client = clients[(numero + 17) % len(clients)]
        lignes = _lignes_quote(rng, articles, 2 + numero % 2)
        totaux = _totaux(lignes, "arithmetique" if numero % 4 == 0 else None)
        issue = (date_ref - timedelta(days=numero % 20)).isoformat()
        visuelles = [
            {"x": 40, "y": 34, "texte": f"DEVIS DEGRADE {ref}", "taille": 15},
            {"x": 40, "y": 62, "texte": f"Client : {client['raison_sociale']}", "taille": 11},
            {"x": 40, "y": 78, "texte": f"IFU : {client['ifu'] or '- absent de la piece -'}", "taille": 10},
            {"x": 400, "y": 36, "texte": f"Date : {issue}", "taille": 10},
        ] + _lignes_visuelles(lignes) + [
            {"x": 330, "y": 700, "texte": f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", "taille": 11},
        ]
        blocs = [
            _bloc(1, 40, 34, f"DEVIS DEGRADE {ref}", 15, 0.72),
            _bloc(1, 40, 62, f"Client : {client['raison_sociale']}", 11, 0.70),
            _bloc(1, 40, 78, f"IFU : {client['ifu'] or '- absent de la piece -'}", 10, 0.72),
            _bloc(1, 400, 36, f"Date : {issue}", 10, 0.74),
            *_blocs_lignes(lignes, 0.68),
            _bloc(1, 330, 700, f"Total HT imprime : {_fcfa(totaux['printed']['ht'])} FCFA", 11, 0.70),
        ]
        _degrader_blocs(blocs, degradations[numero], rng)
        anomalie = "arithmetique" if numero % 4 == 0 else None
        enregistrer(ref, client, lignes, "devis", "degrade",
                    racine_sortie / "eval" / "degrades" / f"{ref}.pdf", "pdf",
                    blocs, visuelles, totaux, anomalie, degradations[numero],
                    notes=f"Cas degrade : {degradations[numero]}. La verite terrain reste celle de la piece imprimee.",
                    issue=issue)

    _verifier_split(proofs)

    # Référentiels et données historiques, pour Melon.
    factures = []
    for index in range(60):
        client = clients[index % len(clients)]
        ht = 150_000 + (index % 12) * 45_000
        tva = _arrondi(Decimal(ht) * Decimal("0.18"))
        factures.append({
            "id": f"fac-{index + 1:03d}",
            "numero": f"FAC-{annee}-{index + 1:05d}",
            "client": client["id"],
            "date": (date_ref - timedelta(days=30 + index * 3)).isoformat(),
            "total_ht": ht, "total_tva": tva, "total_ttc": ht + tva,
            "statut": "EMISE",
        })
    avoirs = [{
        "id": f"av-{index + 1:03d}",
        "numero": f"AV-{annee}-{index + 1:05d}",
        "facture": factures[index * 5]["id"],
        "motif": "avoir partiel simule",
        "total_ttc": factures[index * 5]["total_ttc"] // 10,
        "statut": "EMIS",
    } for index in range(9)]
    paiements = [{
        "id": f"pay-{index + 1:03d}",
        "facture": factures[index * 3]["id"],
        "montant": factures[index * 3]["total_ttc"],
        "date": (date_ref - timedelta(days=index * 2)).isoformat(),
        "canal": ("virement", "especes", "mobile")[index % 3],
    } for index in range(18)]

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
        "modele": "wema-extract-demo-20261125",
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
        "documents": proofs,
    }
    manifest["empreinte"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    (racine_sortie / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère le jeu WÉMA reproductible")
    parser.add_argument(
        "--reset", action="store_true", help="réinitialise la base puis régénère les pièces"
    )
    parser.add_argument("--as-of", default=settings.as_of, help="date de référence ISO")
    parser.add_argument("--force", action="store_true", help="autorise l'écrasure sans --reset")
    args = parser.parse_args(argv)
    manifest = generer(reset=args.reset, as_of=args.as_of, force=args.force)
    print(
        f"Corpus WÉMA : {manifest['evaluation']['documents']} documents annotés "
        f"({manifest['evaluation']['split']['dev']} dev / "
        f"{manifest['evaluation']['split']['validation']} validation / "
        f"{manifest['evaluation']['split']['test']} test), "
        f"{manifest['referentiels']['clients']} clients, "
        f"{manifest['referentiels']['articles']} articles."
    )
    print(f"Empreinte : {manifest['empreinte']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
