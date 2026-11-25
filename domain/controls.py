"""Les neuf contrôles, dans un ordre fixe.

Une anomalie bloquante empêche la validation. Elle n'est pas une impasse :
elle exige une décision humaine tracée (corriger, rattacher, exclure, justifier).
La sévérité d'origine n'est jamais écrasée : seule la trace de résolution
change le statut de l'anomalie.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping

from config import settings
from .extraction import canonical
from .matching import NIVEAUX_RATTACHEMENT_AUTO, compare_quantites, match_client
from .normalization import normalize_text
from .tax import (
    CodeFiscal,
    ResultatCalcul,
    TauxFiscalInconnu,
    arrondi_fcfa,
    calculer,
    calculer_ligne,
    lignes_depuis_dict,
)

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
class Resolution:
    """Trace recevable d'une décision humaine : les quatre champs sont obligatoires."""

    acteur: str
    motif: str
    avant: str
    apres: str

    @classmethod
    def depuis(cls, valeur: Any) -> Resolution:
        if isinstance(valeur, Resolution):
            return valeur
        if not isinstance(valeur, Mapping):
            raise ValueError("résolution invalide : acteur, motif, avant et apres requis")
        champs = {
            cle: str(valeur.get(cle) or "").strip()
            for cle in ("acteur", "motif", "avant", "apres")
        }
        manquants = [cle for cle, valeur_champ in champs.items() if not valeur_champ]
        if manquants:
            raise ValueError(f"résolution incomplète : {', '.join(manquants)}")
        return cls(**champs)


@dataclass(frozen=True)
class Anomalie:
    code: str
    severite: str
    champ: str
    message: str
    resolution: str
    statut: str = "OUVERTE"
    acteur: str = ""
    motif: str = ""
    avant: str = ""
    apres: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code, "severite": self.severite, "champ": self.champ,
            "message": self.message, "resolution": self.resolution, "statut": self.statut,
            "acteur": self.acteur, "motif": self.motif,
            "avant": self.avant, "apres": self.apres,
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
    doublons_proches: tuple[str, ...] = ()
    livree: Mapping[int, Any] = field(default_factory=dict)
    imprime: Mapping[str, Any] = field(default_factory=dict)
    calcule: ResultatCalcul | None = None
    taux_connus: Iterable[str] = field(default_factory=tuple)
    referentiel_fiscal: Mapping[str, CodeFiscal] = field(default_factory=dict)
    prix_ref: Mapping[str, int] = field(default_factory=dict)
    resolus: Mapping[str, Resolution | Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.resolus, Mapping):
            self.resolus = {str(code): Resolution.depuis(trace) for code, trace in self.resolus.items()}
        else:
            # Ancien format (codes seuls) : sans les quatre champs, ce n'est pas une résolution recevable.
            self.resolus = {}


def _anomalie(ctx: ContexteControle, code: str, champ: str, message: str, resolution: str,
              severite: str = BLOQUANT) -> Anomalie:
    """Crée une anomalie. La sévérité est conservée, même si la trace existe."""
    trace = (ctx.resolus or {}).get(code) or (ctx.resolus or {}).get(f"{code}:{champ}")
    if trace is None:
        return Anomalie(code, severite, champ, message, resolution)
    return Anomalie(
        code, severite, champ, message, resolution, RESOLU,
        trace.acteur, trace.motif, trace.avant, trace.apres,
    )


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


def _net_ht(ctx: ContexteControle, index: int, ligne: Mapping[str, Any]) -> int:
    """Base TVA déjà calculée, ou recalculée sans effet de bord."""
    if ctx.calcule is not None and index < len(ctx.calcule.lignes):
        return ctx.calcule.lignes[index].net_ht
    try:
        objet = lignes_depuis_dict([ligne], referentiel=ctx.referentiel_fiscal)[0]
        return calculer_ligne(objet, referentiel=ctx.referentiel_fiscal).net_ht
    except (TauxFiscalInconnu, ValueError, TypeError):
        return 0


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
    if not ctx.draft.get("date_echeance"):
        manquants.append("échéance")
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

    # 2 · UNKNOWN_CLIENT — C1/C2 seulement ; C3, C4 et C5 exigent une décision.
    correspondance = ctx.client_match or {}
    niveau = str(correspondance.get("niveau", "C5"))
    confiance = float(correspondance.get("confiance", 0.0) or 0.0)
    if (ctx.client is None or niveau not in NIVEAUX_RATTACHEMENT_AUTO
            or confiance < settings.confiance_champ):
        anomalies.append(_anomalie(
            ctx, "UNKNOWN_CLIENT", "client",
            f"Client non reconnu sans ambiguïté (niveau {niveau}, confiance {confiance:.2f}). "
            "Aucun rattachement automatique sur homonyme douteux.",
            "Créer le client avec son IFU, ou rattacher avec une décision journalisée.",
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

    # 4 · UNUSUAL_PRICE — écart strictement supérieur au seuil, calcul exact.
    seuil = Decimal(settings.ecart_prix_pct)
    for ligne in ctx.lignes:
        cle = str(ligne.get("item") or ligne.get("famille") or "")
        ref = ctx.prix_ref.get(cle)
        prix = int(ligne.get("pu_ht") or 0)
        if ref and prix:
            ecart = (Decimal(prix) - Decimal(ref)) * Decimal(100) / Decimal(ref)
            if abs(ecart) > seuil:
                pourcent = arrondi_fcfa(ecart)
                message = (
                    f"Prix {prix} FCFA, écart de {pourcent:+d} % par rapport au tarif de "
                    f"référence {ref} FCFA."
                )
                if prix >= settings.seuil_dirigeant:
                    message += " Validation du dirigeant exigée avant passage à l'état suivant."
                anomalies.append(_anomalie(
                    ctx, "UNUSUAL_PRICE", f"ligne {ligne.get('numero')}",
                    message,
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

    # 6 · DUPLICATE_INVOICE — empreinte, puis client + montant + date à ±3 jours.
    if ctx.doublon_facture:
        anomalies.append(_anomalie(
            ctx, "DUPLICATE_INVOICE", "facture",
            "Une facture avec la même empreinte métier existe déjà au registre.",
            "Vérifier le registre ; annuler le brouillon ou confirmer une facture distincte avec motif.",
        ))
    elif ctx.doublons_proches:
        anomalies.append(_anomalie(
            ctx, "DUPLICATE_INVOICE", "date/montant",
            "Facture(s) du même client pour le même montant à ±3 jours : "
            + ", ".join(ctx.doublons_proches) + ".",
            "Vérifier le registre ; confirmer une facture distincte avec motif.",
        ))

    # 7 · QUANTITY_MISMATCH — rapprochement commandé / livré / facturé.
    for comparaison in compare_quantites(ctx.lignes, ctx.livree):
        if comparaison.statut == "LIVRAISON_INCONNUE":
            anomalies.append(_anomalie(
                ctx, "QUANTITY_MISMATCH", f"ligne {comparaison.numero}",
                f"« {comparaison.description} » : commandée {comparaison.commandee}, "
                f"facturée {comparaison.facturee}, livraison inconnue. Aucune quantité n'est supposée.",
                "Renseigner la livraison, exclure la ligne, réduire la quantité ou joindre un justificatif.",
            ))
        elif comparaison.statut == "LIVREE_INFERIEURE":
            anomalies.append(_anomalie(
                ctx, "QUANTITY_MISMATCH", f"ligne {comparaison.numero}",
                f"« {comparaison.description} » : commandée {comparaison.commandee}, "
                f"{comparaison.facturee} facturée(s), {comparaison.livree} livrée(s).",
                "Exclure la ligne, réduire la quantité ou joindre un justificatif de livraison.",
            ))
        elif comparaison.statut == "LIVREE_SUPERIEURE":
            anomalies.append(_anomalie(
                ctx, "QUANTITY_MISMATCH", f"ligne {comparaison.numero}",
                f"« {comparaison.description} » : {comparaison.livree} livrée(s) pour "
                f"{comparaison.facturee} facturée(s) : sous-facturation possible.",
                "Vérifier la commande et corriger la quantité facturée.",
                AVERTISSEMENT,
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

    # 9 · INVALID_TAX — référentiel et base nette, jamais un code littéral.
    for index, ligne in enumerate(ctx.lignes):
        numero = ligne.get("numero")
        code = str(ligne.get("tax_code") or "").strip()
        fiche = ctx.referentiel_fiscal.get(code)
        if fiche is None:
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {numero}",
                f"Code fiscal « {code or 'absent'} » absent du référentiel : aucun taux appliqué.",
                "Choisir un code fiscal du référentiel ; aucun défaut 18 % n'est appliqué.",
            ))
            continue
        if fiche.exoneration and not str(ligne.get("justification") or "").strip():
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {numero}",
                f"Code « {code} » exonéré sans justification documentée.",
                "Documenter l'exonération ou appliquer un code taxable.",
            ))
            continue
        base = _net_ht(ctx, index, ligne)
        if base < 0:
            anomalies.append(_anomalie(
                ctx, "INVALID_TAX", f"ligne {numero}",
                f"Base TVA négative ({base} FCFA) : remise supérieure au brut.",
                "Corriger la quantité, le prix ou la remise.",
            ))

    return anomalies


def bloquant(anomalies: Iterable[Anomalie]) -> bool:
    """Une anomalie résolue ne bloque plus, mais garde sa sévérité d'origine."""
    return any(a.severite == BLOQUANT and a.statut != RESOLU for a in anomalies)


def _champ_extrait(conn: sqlite3.Connection, document_id: Any, chemin: str) -> str | None:
    if not document_id:
        return None
    row = conn.execute(
        "SELECT valeur, valeur_normalisee FROM extracted_fields WHERE extraction IN "
        "(SELECT id FROM extractions WHERE document=?) AND chemin=? "
        "ORDER BY extraction DESC LIMIT 1",
        (document_id, chemin),
    ).fetchone()
    if row is None:
        return None
    return row["valeur_normalisee"] or row["valeur"]


def _doublons_proches(
    conn: sqlite3.Connection,
    client: Any,
    date_piece: Any,
    montant: int,
) -> tuple[str, ...]:
    """Même client + même montant + date à ±3 jours (blueprint §5.8)."""
    if not client or not date_piece or not montant:
        return ()
    try:
        base = date.fromisoformat(str(date_piece)[:10])
    except ValueError:
        return ()
    trouves: list[str] = []
    for decalage in range(-3, 4):
        jour = (base + timedelta(days=decalage)).isoformat()
        for row in conn.execute(
            "SELECT numero, total_ttc FROM invoices WHERE client=? AND substr(date,1,10)=?",
            (client, jour),
        ):
            if int(row["total_ttc"]) == int(montant):
                trouves.append(str(row["numero"]))
    return tuple(dict.fromkeys(trouves))


def build_context(
    conn: sqlite3.Connection,
    draft_id: str,
    *,
    client_match: Mapping[str, Any] | None = None,
    doublon_document: bool = False,
    resolutions: Mapping[str, Any] | None = None,
) -> ContexteControle:
    """Construit le contexte de contrôle depuis la base, sans rien inventer.

    - aucune quantité livrée par défaut ;
    - correspondance client calculée depuis les champs extraits réels ;
    - taux résolus depuis `tax_codes`, jamais par défaut ;
    - résolutions acceptées seulement avec acteur, motif, avant et après.
    """
    draft = conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise KeyError(f"brouillon introuvable: {draft_id}")
    d = dict(draft)
    client_row = conn.execute("SELECT * FROM clients WHERE id=?", (d.get("client"),)).fetchone()
    client = dict(client_row) if client_row else None
    lignes = [dict(r) for r in conn.execute(
        "SELECT * FROM draft_lines WHERE draft=? ORDER BY numero", (draft_id,)
    )]
    referentiel = {
        r["code"]: CodeFiscal(
            code=r["code"],
            taux_bp=int(r["taux_bp"]),
            exoneration=bool(r["exoneration"]),
        )
        for r in conn.execute("SELECT code, taux_bp, exoneration FROM tax_codes")
    }
    document = None
    if d.get("document"):
        row = conn.execute("SELECT * FROM documents WHERE id=?", (d["document"],)).fetchone()
        document = dict(row) if row else None
    livree = {
        int(r["numero"]): r["quantite_livree"]
        for r in conn.execute(
            "SELECT numero, quantite_livree FROM deliveries WHERE draft=?", (draft_id,)
        )
    }
    prix_ref: dict[str, int] = {}
    for r in conn.execute("SELECT id, prix_catalogue, famille FROM items"):
        prix_ref[r["id"]] = int(r["prix_catalogue"])
        prix_ref[r["famille"]] = int(r["prix_catalogue"])
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
    resultat = None
    if lignes:
        try:
            resultat = calculer(
                lignes_depuis_dict(lignes, referentiel=referentiel),
                imprime=imprime or None,
                tolerance=settings.tolerance_arithmetique,
                referentiel=referentiel,
            )
        except TauxFiscalInconnu:
            # INVALID_TAX signalera la ligne fautive ; on n'invente pas de taux.
            resultat = None

    if client_match is None:
        clients = [dict(r) for r in conn.execute("SELECT * FROM clients")]
        nom = _champ_extrait(conn, d.get("document"), "client.name")
        ifu = _champ_extrait(conn, d.get("document"), "client.ifu")
        telephone = (
            _champ_extrait(conn, d.get("document"), "client.phone")
            or _champ_extrait(conn, d.get("document"), "client.telephone")
        )
        ville = _champ_extrait(conn, d.get("document"), "client.ville")
        email = _champ_extrait(conn, d.get("document"), "client.email")
        if not nom and client:
            nom = client.get("raison_sociale")
        match = match_client(clients, nom, ifu, telephone, ville, email)
    else:
        match = dict(client_match)

    empreinte = empreinte_metier(d.get("client"), d.get("date_piece"), lignes)
    doublon = conn.execute(
        "SELECT 1 FROM invoices WHERE empreinte=? LIMIT 1", (empreinte,)
    ).fetchone() is not None
    montant = resultat.total_ttc if resultat else int(imprime.get("ttc") or 0)
    proches = _doublons_proches(conn, d.get("client"), d.get("date_piece"), montant)

    resolus: dict[str, Resolution] = {}
    if resolutions is not None:
        resolus = {str(code): Resolution.depuis(trace) for code, trace in resolutions.items()}

    return ContexteControle(
        draft=d,
        client=client,
        client_match=match,
        lignes=lignes,
        document=document,
        doublon_document=bool(doublon_document),
        doublon_facture=doublon,
        doublons_proches=proches,
        livree=livree,
        imprime=imprime,
        calcule=resultat,
        taux_connus=tuple(referentiel),
        referentiel_fiscal=referentiel,
        prix_ref=prix_ref,
        resolus=resolus,
    )
