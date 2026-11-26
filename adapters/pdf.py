"""Génération déterministe du PDF de facture, d'aperçu et d'avoir.

Utilise ReportLab en mode invariant si disponible, sinon un générateur PDF
minimal intégré 100 % déterministe (sans horloge système ni ID aléatoire)
afin que la régénération depuis le snapshot produise toujours le même SHA-256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


def hash_file(path: str | Path) -> str:
    """Retourne l'empreinte SHA-256 hexadécimale d'un fichier."""
    h = hashlib.sha256()
    with Path(path).open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _fmt_fcfa(value: Any) -> str:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        n = 0
    return f"{n:,}".replace(",", " ") + " FCFA"


def _ascii_safe(text: Any) -> str:
    """Convertit en latin-1 / ASCII sûr pour les polices PDF standard."""
    s = str(text or "")
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "«": '"',
        "»": '"',
        "€": "EUR",
    }
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_escape(text: str) -> str:
    safe = _ascii_safe(text)
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines_from_snapshot(snapshot: Mapping[str, Any], numero: str, brouillon: bool = False) -> list[str]:
    banner = (
        "BROUILLON - NON FISCAL (SIMULATION WEMA)"
        if brouillon
        else "SIMULATION - DOCUMENT DE DEMONSTRATION NON FISCAL"
    )
    client = snapshot.get("client") or {}
    calcul = snapshot.get("calcul") or {}
    lignes = snapshot.get("lignes") or []

    out = [
        banner,
        "=" * 72,
        f"WEMA FACTURATION - Numero : {numero}",
        f"Date piece : {snapshot.get('date') or '-'} | Echeance : {snapshot.get('echeance') or '-'}",
        f"Conditions : {snapshot.get('conditions') or '-'} | Devise : {snapshot.get('devise') or 'XOF'}",
        "-" * 72,
        f"Client : {client.get('raison_sociale') or '-'}",
        f"IFU    : {client.get('ifu') or '- absent de la piece -'}",
        f"Adresse: {client.get('adresse') or '-'}",
        "-" * 72,
        "Lignes :",
    ]
    for idx, l in enumerate(lignes, start=1):
        desc = l.get("description") or ""
        qte = l.get("quantite", 1)
        unite = l.get("unite", "pcs")
        pu = _fmt_fcfa(l.get("pu_ht", 0))
        tax = l.get("tax_code", "TVA18")
        out.append(f"  {idx}. {desc} | {qte} {unite} x {pu} ({tax})")
    out.extend([
        "-" * 72,
        f"Total HT  : {_fmt_fcfa(calcul.get('total_ht', 0))}",
        f"Total TVA : {_fmt_fcfa(calcul.get('total_tva', 0))}",
        f"Total TTC : {_fmt_fcfa(calcul.get('total_ttc', 0))}",
        "=" * 72,
        str(snapshot.get("mention") or banner),
    ])
    return out


def _build_minimal_pdf(lines: list[str], destination: Path) -> None:
    """Générateur PDF 1.4 minimal, 100 % déterministe, sans dépendance externe."""
    content_ops = ["BT", "/F1 10 Tf", "40 800 Td", "14 TL"]
    for i, line in enumerate(lines):
        escaped = _pdf_escape(line)
        if i == 0:
            content_ops.append(f"({escaped}) Tj")
        else:
            content_ops.append(f"T* ({escaped}) Tj")
    content_ops.append("ET")
    stream_bytes = ("\n".join(content_ops) + "\n").encode("latin-1", errors="replace")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"endstream\nendobj\n"
        ),
    ]

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    buf = bytearray(header)
    offsets = [0]
    for obj in objects:
        offsets.append(len(buf))
        buf.extend(obj)

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    buf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    destination.write_bytes(bytes(buf))


def _build_reportlab_pdf(lines: list[str], numero: str, destination: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(destination), pagesize=A4, invariant=1)
    c.setTitle(f"WEMA-{numero}")
    c.setAuthor("WEMA")
    c.setCreator("WEMA")
    c.setSubject("SIMULATION")

    width, height = A4
    y = height - 42
    c.setFont("Courier-Bold", 11)
    c.drawString(36, y, _ascii_safe(lines[0]))
    y -= 18
    c.setFont("Courier", 9.5)
    for line in lines[1:]:
        if y < 48:
            c.showPage()
            c.setFont("Courier", 9.5)
            y = height - 42
        c.drawString(36, y, _ascii_safe(line))
        y -= 13
    c.save()


def build_invoice_pdf(
    snapshot: Mapping[str, Any],
    numero: str,
    destination: str | Path,
    brouillon: bool = False,
) -> Path:
    """Génère un PDF déterministe pour une facture ou un brouillon."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = _lines_from_snapshot(snapshot, numero, brouillon=brouillon)
    try:
        _build_reportlab_pdf(lines, numero, dest)
    except Exception:
        _build_minimal_pdf(lines, dest)
    return dest
