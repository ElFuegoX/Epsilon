"""PDF de facture validée et PDF d'aperçu de brouillon (ReportLab).

* ``build_invoice_pdf(snapshot, numero, destination)`` : facture figée, appelée par
  ``invoices.validate_draft`` ; mentions de l'annexe B du blueprint, bandeau
  SIMULATION, code MECeF et QR **factices**.
* ``build_draft_pdf(conn, draft_id, destination)`` : aperçu exportable d'un
  brouillon, bandeau « BROUILLON — NON FISCAL », sans numéro (exigence du TDR :
  « un brouillon exportable en PDF »).
* ``hash_file(path)`` : SHA-256 du fichier.

Le rendu est **déterministe** (``invariant=1`` : ni date de création, ni
identifiant aléatoire). Régénérer une facture depuis son snapshot redonne
exactement le même hash : c'est ce que vérifie ``invoices.verifier_pdf``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from config import settings

# Émetteur fictif de la démonstration (annexe B : raison sociale, adresse, contact, RCCM, IFU).
EMETTEUR = {
    "raison_sociale": "Atelier WÉMA Meubles (fictif)",
    "adresse": "Lot 12, quartier Fidjrossè, Cotonou",
    "contact": "+229 01 00 00 00 · contact@wema.example",
    "rccm": "RB/COT/00 A 0000 (fictif)",
    "ifu": "0000000000000 (fictif)",
}
MENTION = "Document de démonstration — ne pas utiliser pour une déclaration fiscale"


def hash_file(path: Any) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _fcfa(valeur: Any) -> str:
    if valeur is None or valeur == "":
        return "—"
    return f"{int(valeur):,}".replace(",", " ") + " F"


def _taux(ligne: Mapping[str, Any], calcul: Mapping[str, Any] | None) -> str:
    if calcul and calcul.get("taux_bp") is not None:
        return f"{int(calcul['taux_bp']) // 100} %"
    return str(ligne.get("tax_code") or "—")


def _document(destination: Path, titre: str, bandeau: str, numero: str | None,
              entete: Mapping[str, Any], client: Mapping[str, Any], lignes: list[Mapping[str, Any]],
              calcul: Mapping[str, Any], pied: list[str], qr: str | None) -> None:
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    destination.parent.mkdir(parents=True, exist_ok=True)
    largeur, hauteur = A4
    c = canvas.Canvas(str(destination), pagesize=A4, invariant=1)
    c.setTitle(f"{titre} {numero or ''}".strip())
    c.setAuthor("WÉMA (prototype)")

    # Bandeau
    c.setFillColor(colors.HexColor("#B3261E"))
    c.rect(0, hauteur - 26, largeur, 26, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(largeur / 2, hauteur - 17, bandeau)
    c.setFillColor(colors.black)

    # Émetteur
    y = hauteur - 56
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, EMETTEUR["raison_sociale"])
    c.setFont("Helvetica", 8.5)
    for texte in (EMETTEUR["adresse"], EMETTEUR["contact"],
                  f"RCCM {EMETTEUR['rccm']} · IFU {EMETTEUR['ifu']}"):
        y -= 12
        c.drawString(40, y, texte)

    # Identification
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(largeur - 40, hauteur - 58, titre)
    c.setFont("Helvetica", 9)
    yi = hauteur - 76
    for libelle, valeur in entete.items():
        c.drawRightString(largeur - 40, yi, f"{libelle} : {valeur if valeur not in (None, '') else '— absent —'}")
        yi -= 12

    # Client
    y = min(y, yi) - 22
    c.setStrokeColor(colors.HexColor("#999999"))
    c.rect(40, y - 46, 260, 56, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(48, y, "Client")
    c.setFont("Helvetica", 9)
    c.drawString(48, y - 13, str(client.get("raison_sociale") or "— client non rattaché —"))
    c.drawString(48, y - 26, str(client.get("adresse") or ""))
    c.drawString(48, y - 39, f"IFU : {client.get('ifu') or '— absent —'}")

    # Lignes
    y -= 74
    colonnes = [(40, "Désignation", "l"), (290, "Qté", "r"), (300, "Unité", "l"), (395, "PU HT", "r"),
                (445, "Remise", "r"), (480, "TVA", "r"), (555, "Total HT", "r")]
    c.setFillColor(colors.HexColor("#EEEEEE"))
    c.rect(36, y - 4, largeur - 72, 16, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8.5)
    for x, titre_col, sens in colonnes:
        (c.drawRightString if sens == "r" else c.drawString)(x, y, titre_col)
    c.setFont("Helvetica", 8.5)
    calculs = list((calcul or {}).get("lignes") or [])
    for index, ligne in enumerate(lignes):
        y -= 16
        detail = calculs[index] if index < len(calculs) else None
        valeurs = [str(ligne.get("description") or "")[:48], str(ligne.get("quantite") or ""),
                   str(ligne.get("unite") or ""), _fcfa(ligne.get("pu_ht")), _fcfa(ligne.get("remise") or 0),
                   _taux(ligne, detail), _fcfa(detail["net_ht"] if detail else ligne.get("total_ht"))]
        for (x, _, sens), valeur in zip(colonnes, valeurs):
            (c.drawRightString if sens == "r" else c.drawString)(x, y, valeur)
    c.line(36, y - 8, largeur - 36, y - 8)

    # Totaux
    y -= 28
    c.setFont("Helvetica", 9.5)
    for libelle, valeur, gras in (("Total HT", calcul.get("total_ht"), False),
                                  ("TVA", calcul.get("total_tva"), False),
                                  ("Total TTC", calcul.get("total_ttc"), True),
                                  ("Net à payer", calcul.get("total_ttc"), True)):
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 9.5)
        c.drawString(380, y, libelle)
        c.drawRightString(largeur - 40, y, _fcfa(valeur))
        y -= 14

    # QR factice
    if qr:
        widget = QrCodeWidget(qr)
        x0, y0, x1, y1 = widget.getBounds()
        taille = 78
        dessin = Drawing(taille, taille, transform=[taille / (x1 - x0), 0, 0, taille / (y1 - y0), 0, 0])
        dessin.add(widget)
        renderPDF.draw(dessin, c, 40, 70)
        c.setFont("Helvetica", 7)
        c.drawString(40, 62, "QR factice — sans valeur fiscale")

    # Pied
    c.setFont("Helvetica", 7.5)
    yp = 140
    for texte in pied:
        c.drawString(130 if qr else 40, yp, texte)
        yp -= 11
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawCentredString(largeur / 2, 30, MENTION)
    c.showPage()
    c.save()


def build_invoice_pdf(snapshot: Mapping[str, Any], numero: str, destination: Any) -> None:
    """Facture validée, depuis son snapshot figé (appelée dans la transaction de validation)."""
    from .mecef_stub import code_mecef, contenu_qr

    client = snapshot.get("client") or {}
    _document(
        Path(destination), "FACTURE", "SIMULATION — FACTURE NORMALISÉE FICTIVE — AUCUNE TRANSMISSION À LA DGI",
        numero,
        {"N°": numero, "Date d'émission": snapshot.get("date"), "Échéance": snapshot.get("echeance"),
         "Conditions": snapshot.get("conditions"), "Devise": snapshot.get("devise", settings.devise)},
        client, list(snapshot.get("lignes") or []), snapshot.get("calcul") or {},
        [f"Code MECeF : {code_mecef(numero, snapshot)}",
         "Mode de paiement : virement ou mobile money (simulé)",
         "Toute correction de cette facture passe par un avoir lié."],
        contenu_qr(numero, snapshot),
    )


def build_draft_pdf(conn: Any, draft_id: str, destination: Any) -> dict[str, Any]:
    """Aperçu exportable d'un brouillon : montants recalculés, aucun numéro fiscal."""
    from domain.controls import build_context

    ctx = build_context(conn, draft_id)
    draft = dict(ctx.draft)
    calcul = ctx.calcule.to_dict() if ctx.calcule else {}
    pied = ["Aperçu de travail : aucun numéro n'est attribué avant la validation humaine."]
    if not ctx.calcule:
        pied.append("Calcul indisponible : un code fiscal doit être corrigé.")
    _document(
        Path(destination), "BROUILLON", "BROUILLON — NON FISCAL — NE PAS ENVOYER AU CLIENT", None,
        {"Brouillon": draft_id, "Version": draft.get("version"), "Date de pièce": draft.get("date_piece"),
         "Échéance": draft.get("date_echeance"), "Conditions": draft.get("conditions")},
        dict(ctx.client or {}), [dict(l) for l in ctx.lignes], calcul, pied, None,
    )
    return {"chemin": str(destination), "hash": hash_file(destination)}
