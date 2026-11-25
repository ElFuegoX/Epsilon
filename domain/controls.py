"""Les neuf contrôles, dans un ordre fixe.

Une anomalie bloquante empêche la validation. Elle n'est pas une impasse :
elle exige une décision humaine tracée (corriger, rattacher, exclure, justifier).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping

from config import settings
from .extraction import canonical
from .normalization import normalize_text
from .tax import ResultatCalcul, arrondi_fcfa, lignes_depuis_dict

BLOQUANT = "BLOQUANT"
AVERTISSEMENT = "AVERTISSEMENT"
RESOLU = "RESOLUE"

CODES = (
    "MISSING_MANDATORY",
    "UNKNOWN_CLIENT",
    "UNKNOWN_ITEM",
    "UNUSUAL_PRICE",
    "DUPLICATE_DOCUMENT",
    "DUPLICATE_INVOICE",
    "QUANTITY_MISMATCH",
    "ARITHMETIC_MISMATCH",
    "INVALID_TAX",
)


@dataclass(frozen=True)
class Anomalie:
    code: str
    severite: str
    champ: str
    message: str
    resolution: str
    statut: str = "OUVERTE"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code, "severite": self.severite, "champ": self.champ,
            "message": self.message, "resolution": self.resolution, "statut": self.statut,
        }


@dataclass
class ContexteControle:
    draft: Mapping[str, Any]
    client: Mapping[str, Any] | None = None
    client_match: Mapping[str, Any] | None = None
    lignes: list[Mapping[str, Any]] = field(default_factory=list)
    document: Mapping[str, Any] | None = None
    doublon_document: bool = False
    doublon_facture: bool = False
    livree: Mapping[int, Any] = field(default_factory=dict)
    imprime: Mapping[str, Any] = field(default_factory=dict)
    calcule: ResultatCalcul | None = None
    taux_connus: Iterable[str] = field(default_factory=tuple)
    prix_ref: Mapping[str, int] = field(default_factory=dict)
    resolus: Iterable[str] = field(default_factory=tuple)


def _anomalie(ctx: ContexteControle, code: str, champ: str, message: str, resolution: str,
              severite: str = BLOQUANT) -> Anomalie:
    statut = RESOLU if code in ctx.resolus else "OUVERTE"
    return Anomalie(code, RESOLU if statut == RESOLU else severite, champ, message, resolution, statut)


def empreinte_metier(client: str | None, date: str | None, lignes: Iterable[Mapping[str, Any]]) -> str:
    """Empreinte utilisée pour DUPLICATE_INVOICE."""
    brut = canonical({
        "client": client,
        "date": date,
        "lignes": [
            {
                "description": normalize_text(l.get("description")),
                "quantite": str(l.get("quantite")),
                "pu_ht": l.get("pu_ht"),
                "tax_code": l.get("tax_code"),
            }
            for l in lignes
        ],
    })
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def run_controls(ctx: ContexteControle) -> list[Anomalie]:
    anomalies: list[Anomalie] = []

    # 1 · MISSING_MANDATORY
    manquants: list[str] = []
    if not ctx.draft.get("client"):
        manquants.append("client")
    elif not (ctx.client or {}).get("ifu"):
        manquants.append("IFU client")
    if not ctx.draft.get("date_piece"):
        manquants.append("date")
    if not ctx.lignes:
        manquants.append("au moins une ligne")
    if not ctx.draft.get("conditions"):
        manquants.append("conditions de paiement")
    if manquants:
        anomalies.append(_anomalie(
            ctx, "MISSING_MANDATORY", ", ".join(manquants),
            f"Mentions obligatoires absentes : {', '.join(manquants)}. Aucune valeur n'a été proposée.",
            "Compléter depuis la pièce ou le référentiel ; jamais depuis une supposition.",
        ))

    # 2 · UNKNOWN_CLIENT
    confiance = float((ctx.client_match or {}).get("confiance", 0.0))
    if ctx.client is None or confiance < 0.80:
        anomalies.append(_anomalie(
            ctx, "UNKNOWN_CLIENT", "client",
            f"Aucun client reconnu avec une confiance >= 0,80 (niveau {(ctx.client_match or {}).get('niveau', 'C5')}).",
            "Créer le client avec son IFU, ou le rattacher à un client existant.",
        ))

    # 3 · UNKNOWN_ITEM
    for ligne in ctx.lignes:
        if not ligne.get("item") and not ligne.get("famille"):
            anomalies.append(_anomalie(
                ctx, "UNKNOWN_ITEM", f"ligne {ligne.get('numero')}",
                f"« {ligne.get('description')} » n'est rattachée à aucun article ni famille.",
                "Rattacher, créer une prestation sur mesure ou laisser une ligne libre justifiée.",
                AVERTISSEMENT,
            ))

    # 4 · UNUSUAL_PRICE
    for ligne in ctx.lignes:
        cle = str(ligne.get("item") or ligne.get("famille") or "")
        ref = ctx.prix_ref.get(cle)
        prix = int(ligne.get("pu_ht") or 0)
        if ref and prix and abs(prix - ref) * 100 > settings.ecart_prix_pct * ref:
            ecart = round((prix - ref) * 100 / ref)
            anomalies.append(_anomalie(
                ctx, "UNUSUAL_PRICE", f"ligne {ligne.get('numero')}",
                f"Prix {prix} FCFA, écart de {ecart:+d} % par rapport au tarif de référence {ref} FCFA.",
                "Justifier (sur-mesure, matière, urgence) ; validation du dirigeant au-delà du seuil.",
                AVERTISSEMENT,
            ))

    # 5 · DUPLICATE_DOCUMENT
    if ctx.doublon_document:
        anomalies.append(_anomalie(
            ctx, "DUPLICATE_DOCUMENT", "document",
            "Ce fichier a déjà été importé (hash identique).",
            "Ouvrir la pièce existante ; aucun nouvel import.",
        ))

    # 6 · DUPLICATE_INVOICE
    if ctx.doublon_facture:
        anomalies.append(_anomalie(
            ctx, "DUPLICATE_INVOICE", "facture",
            "Une facture avec la même empreinte métier existe déjà au registre.",
            "Vérifier le registre ; annuler le brouillon ou confirmer une facture distincte avec motif.",
        ))

    # 7 · QUANTITY_MISMATCH
    for ligne in ctx.lignes:
        numero = int(ligne.get("numero") or 0)
        facturee = Decimal(str(ligne.get("quantite") or 0))
        livree = Decimal(str(ctx.livree.get(numero, 0)))
        if facturee > livree:
            anomalies.append(_anomalie(
                ctx, "QUANTITY_MISMATCH", f"ligne {numero}",
                f"« {ligne.get('description')} » : {facturee} commandée(s)/facturée(s), {livree} livrée(s).",
                "Exclure la ligne, réduire la quantité ou joindre un justificatif de livraison.",
            ))

    # 8 · ARITHMETIC_MISMATCH
    if ctx.calcule:
        for cle, ecart in ctx.calcule.ecarts.items():
            if abs(ecart) <= settings.tolerance_arithmetique:
                continue
            anomalies.append(_anomalie(
                ctx, "ARITHMETIC_MISMATCH", f"totaux.{cle}",
                f"Total imprimé et total recalculé diffèrent de {ecart:+d} FCFA ({cle}).",
                "Corriger la ligne fautive ou choisir le total recalculé avec justification.",
            ))

    # 9 · INVALID_TAX
    connus = set(ctx.taux_connus)
    for ligne in ctx.lignes:
        code = str(ligne.get("tax_code") or "")
        base = arrondi_fcfa(Decimal(str(ligne.get("quantite") or 0)) * int(ligne.get("pu_ht") or 0))
        if code not in connus:
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {ligne.get('numero')}",
                f"Code fiscal « {code or 'absent'} » hors référentiel.",
                "Choisir un code fiscal valide ou documenter l'exonération.",
            ))
        elif base < 0:
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {ligne.get('numero')}",
                "TVA calculée sur un montant négatif.",
                "Corriger la quantité, le prix ou la remise.",
            ))
        elif code == "TVA0" and not ligne.get("justification"):
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {ligne.get('numero')}",
                "Exonération non justifiée.",
                "Documenter l'exonération ou appliquer le taux normal.",
            ))

    return anomalies


def bloquant(anomalies: Iterable[Anomalie]) -> bool:
    return any(a.severite == BLOQUANT for a in anomalies)


def build_context(conn: sqlite3.Connection, draft_id: str) -> ContexteControle:
    """Construit le contexte de contrôle depuis la base."""
    draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise KeyError(f"brouillon introuvable: {draft_id}")
    d = dict(draft)
    client_row = conn.execute("SELECT * FROM clients WHERE id=?", (d.get("client"),)).fetchone()
    client = dict(client_row) if client_row else None
    lignes = [dict(r) for r in conn.execute(
        "SELECT * FROM draft_lines WHERE draft=? ORDER BY numero", (draft_id,)
    )]
    for l in lignes:
        code = conn.execute("SELECT taux_bp FROM tax_codes WHERE code=?", (l["tax_code"],)).fetchone()
        l["taux_bp"] = int(code["taux_bp"]) if code else 0
    document = None
    if d.get("document"):
        row = conn.execute("SELECT * FROM documents WHERE id=?", (d["document"],)).fetchone()
        document = dict(row) if row else None
    livree = {
        int(r["numero"]): r["quantite_livree"]
        for r in conn.execute("SELECT numero, quantite_livree FROM deliveries WHERE draft=?", (draft_id,))
    }
    # Si aucune table de livraison n'est renseignée, on considère que tout est livré
    # sauf les lignes explicitement exclues (décision humaine).
    if not livree:
        livree = {int(l["numero"]): l["quantite"] for l in lignes}
    taux_connus = [r["code"] for r in conn.execute("SELECT code FROM tax_codes")]
    prix_ref: dict[str, int] = {}
    for r in conn.execute("SELECT id, prix_catalogue, famille FROM items"):
        prix_ref[r["id"]] = int(r["prix_catalogue"])
        prix_ref[r["famille"]] = int(r["prix_catalogue"])
    resolus = [
        r["code"] for r in conn.execute(
            "SELECT code FROM anomalies WHERE draft=? AND statut='RESOLUE'", (draft_id,)
        )
    ]
    imprime: dict[str, int] = {}
    if document:
        totaux = conn.execute(
            "SELECT printed_ht, printed_vat, printed_ttc FROM document_totals WHERE document=?",
            (document["id"],),
        ).fetchone()
        if totaux:
            imprime = {
                "ht": totaux["printed_ht"],
                "vat": totaux["printed_vat"],
                "ttc": totaux["printed_ttc"],
            }
    empreinte = empreinte_metier(d.get("client"), d.get("date_piece"), lignes)
    doublon = conn.execute("SELECT 1 FROM invoices WHERE empreinte=? LIMIT 1", (empreinte,)).fetchone() is not None
    resultat = None
    if lignes:
        from .tax import calculer

        resultat = calculer(
            lignes_depuis_dict(lignes),
            imprime=imprime or None,
            tolerance=settings.tolerance_arithmetique,
        )
    match = {"niveau": "C1", "confiance": 1.0} if client else {"niveau": "C5", "confiance": 0.0}
    return ContexteControle(
        draft=d,
        client=client,
        client_match=match,
        lignes=lignes,
        document=document,
        doublon_document=False,
        doublon_facture=doublon,
        livree=livree,
        imprime=imprime,
        calcule=resultat,
        taux_connus=taux_connus,
        prix_ref=prix_ref,
        resolus=resolus,
    )
