"""Automate d'états et décision de doublon : règles métier seules.

Melon importe, calcule le SHA-256 et stocke la pièce ; Freud extrait. Ce module
ne copie aucun fichier, ne calcule aucun hash, ne touche pas au réseau et ne
remplace aucune donnée absente. Il dit seulement quelles transitions sont
licites et pourquoi, puis applique la transition dans la transaction fournie.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .audit import append_event
from .controls import bloquant

# Vocabulaire du blueprint §5.6. Aucun alias ASCII n'est inventé.
IMPORTE = "IMPORTÉ"
EN_ATTENTE_IA = "EN_ATTENTE_IA"
REJETE = "REJETÉ"
EXTRAIT = "EXTRAIT"
A_COMPLETER = "À_COMPLÉTER"
CONTROLE = "CONTRÔLÉ"
BROUILLON = "BROUILLON"
VALIDE = "VALIDÉ"
EMIS = "ÉMIS"
ANNULE_PAR_AVOIR = "ANNULÉ_PAR_AVOIR"

TRANSITIONS: dict[str, frozenset[str]] = {
    IMPORTE: frozenset({EN_ATTENTE_IA, EXTRAIT, REJETE}),
    EN_ATTENTE_IA: frozenset({EXTRAIT}),
    REJETE: frozenset(),
    EXTRAIT: frozenset({A_COMPLETER, CONTROLE}),
    A_COMPLETER: frozenset({EXTRAIT}),
    CONTROLE: frozenset({BROUILLON}),
    BROUILLON: frozenset({VALIDE}),
    VALIDE: frozenset({EMIS}),
    EMIS: frozenset({EMIS, ANNULE_PAR_AVOIR}),
    ANNULE_PAR_AVOIR: frozenset(),
}
ETATS: tuple[str, ...] = tuple(TRANSITIONS)
TERMINAUX: frozenset[str] = frozenset({REJETE, ANNULE_PAR_AVOIR})

MOTIFS: dict[tuple[str, str], str] = {
    (IMPORTE, EN_ATTENTE_IA): "extraction en file, service indisponible",
    (IMPORTE, EXTRAIT): "extraction disponible",
    (IMPORTE, REJETE): "pièce invalide ou doublon exact",
    (EN_ATTENTE_IA, EXTRAIT): "extraction revenue ou saisie manuelle de secours",
    (EXTRAIT, A_COMPLETER): "champ obligatoire manquant ou valeur ambiguë",
    (EXTRAIT, CONTROLE): "contrôles passés, anomalies bloquantes résolues",
    (A_COMPLETER, EXTRAIT): "pièce corrigée, extraction rejouée",
    (CONTROLE, BROUILLON): "brouillon éditable créé, sans numéro fiscal",
    (BROUILLON, VALIDE): "validation humaine : numéro attribué et snapshot figé",
    (VALIDE, EMIS): "émission simulée, montants inchangés",
    (EMIS, EMIS): "avoir partiel : la facture reste émise",
    (EMIS, ANNULE_PAR_AVOIR): "avoir total : facture conservée au registre",
}


class DocumentError(Exception):
    """Erreur de règle métier, jamais une erreur d'entrée/sortie."""


class DuplicateDocument(DocumentError):
    def __init__(self, existing_id: str):
        super().__init__(f"doublon exact de la pièce {existing_id}")
        self.existing_id = existing_id


class TransitionInterdite(DocumentError):
    def __init__(self, actuel: str, cible: str, motif: str):
        super().__init__(f"transition interdite {actuel} → {cible} : {motif}")
        self.actuel = actuel
        self.cible = cible
        self.motif = motif


@dataclass(frozen=True)
class DecisionTransition:
    actuel: str
    cible: str
    autorisee: bool
    motif: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "actuel": self.actuel,
            "cible": self.cible,
            "autorisee": self.autorisee,
            "motif": self.motif,
        }


@dataclass(frozen=True)
class DecisionDoublon:
    doublon: bool
    document_existant: str | None
    action: str
    motif: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doublon": self.doublon,
            "document_existant": self.document_existant,
            "action": self.action,
            "motif": self.motif,
        }


def classifier(nom: str, texte: str = "") -> str:
    """Classe la pièce par mots-clés ; l'IA pourra affiner ensuite."""
    brut = f"{nom} {texte}".lower()
    if "devis" in brut:
        return "devis"
    if "livraison" in brut or " bon de livraison" in brut or "bl-" in brut:
        return "bon_livraison"
    if "message" in brut or "whatsapp" in brut:
        return "message"
    return "commande"


def transitions_possibles(etat: str) -> tuple[str, ...]:
    """Transitions sortantes ; un état terminal renvoie un tuple vide."""
    cle = str(etat or "").strip()
    if cle not in TRANSITIONS:
        raise DocumentError(f"état inconnu : {cle or 'vide'}")
    return tuple(sorted(TRANSITIONS[cle]))


def verifier_transition(
    actuel: str,
    cible: str,
    *,
    anomalies: Iterable[Any] = (),
    decision_humaine: bool = False,
    acteur: str | None = None,
    type_avoir: str | None = None,
    canal: str | None = None,
    doublon: bool = False,
    motif: str | None = None,
) -> DecisionTransition:
    """Décide sans écrire. Les preuves sont fournies, jamais devinées."""
    source = str(actuel or "").strip()
    destination = str(cible or "").strip()
    if source not in TRANSITIONS:
        raise DocumentError(f"état actuel inconnu : {source or 'vide'}")
    if destination not in ETATS:
        raise DocumentError(f"état cible inconnu : {destination or 'vide'}")

    reason = str(motif or "").strip() or MOTIFS.get((source, destination), "transition autorisée")

    def refuse(pourquoi: str) -> DecisionTransition:
        return DecisionTransition(source, destination, False, pourquoi)

    if doublon:
        if destination != REJETE:
            return refuse("doublon exact : seul REJETÉ est autorisé, aucun nouvel import")
        return DecisionTransition(source, destination, True, "doublon exact : pièce rejetée")

    if destination not in TRANSITIONS[source]:
        return refuse(f"transition interdite depuis {source}")

    if bloquant(anomalies) and destination not in (A_COMPLETER, REJETE):
        return refuse("anomalie bloquante non résolue")

    if destination == VALIDE:
        acteur_texte = str(acteur or "").strip().casefold()
        if not decision_humaine or acteur_texte in ("", "systeme", "système", "auto"):
            return refuse("validation humaine explicite requise avant attribution du numéro")

    if destination == EMIS and source == VALIDE and not str(canal or "").strip():
        return refuse("canal d'émission simulée requis")

    if destination == EMIS and source == EMIS and type_avoir != "partiel":
        return refuse("le maintien en ÉMIS exige un avoir partiel")

    if destination == ANNULE_PAR_AVOIR:
        if type_avoir != "total":
            return refuse("ANNULÉ_PAR_AVOIR exige un avoir total")

    return DecisionTransition(source, destination, True, reason)


def decider_doublon(
    empreinte: str,
    existant: str | Mapping[str, Any] | None,
) -> DecisionDoublon:
    """Décide à partir du hash transmis par Melon et de la pièce existante.

    Aucun hash n'est calculé ici : Melon détecte l'unicité à l'import et transmet
    le résultat. Une absence d'information n'est pas une preuve d'absence de
    doublon.
    """
    hash_texte = str(empreinte or "").strip()
    if not hash_texte:
        raise DocumentError("hash manquant : Melon doit transmettre l'empreinte SHA-256")
    if existant is None:
        return DecisionDoublon(False, None, "IMPORTER", "aucune pièce existante transmise")

    identifiant = existant.get("id") if isinstance(existant, Mapping) else existant
    identifiant_texte = str(identifiant or "").strip()
    if not identifiant_texte:
        raise DocumentError("identifiant de la pièce existante manquant")
    return DecisionDoublon(
        True, identifiant_texte, "OUVRIR_EXISTANT",
        f"doublon exact pour le hash {hash_texte} : aucun nouvel import",
    )


def exiger_pas_de_doublon(decision: DecisionDoublon) -> None:
    """Barrière métier à l'import : lève avant toute écriture."""
    if decision.doublon:
        raise DuplicateDocument(decision.document_existant or "")


def appliquer_transition(
    conn: sqlite3.Connection,
    document_id: str,
    statut: str,
    acteur: str = "systeme",
    *,
    anomalies: Iterable[Any] = (),
    decision_humaine: bool = False,
    type_avoir: str | None = None,
    canal: str | None = None,
    doublon: bool = False,
    motif: str | None = None,
) -> DecisionTransition:
    """Applique la transition dans la transaction, ou ne touche à rien."""
    ligne = conn.execute("SELECT statut FROM documents WHERE id=?", (document_id,)).fetchone()
    if ligne is None:
        raise DocumentError(f"pièce introuvable : {document_id}")
    decision = verifier_transition(
        ligne["statut"],
        statut,
        anomalies=anomalies,
        decision_humaine=decision_humaine,
        acteur=acteur,
        type_avoir=type_avoir,
        canal=canal,
        doublon=doublon,
        motif=motif,
    )
    if not decision.autorisee:
        raise TransitionInterdite(decision.actuel, decision.cible, decision.motif)

    conn.execute("UPDATE documents SET statut=? WHERE id=?", (statut, document_id))
    apres: dict[str, Any] = {"statut": decision.cible, "motif": decision.motif}
    if decision_humaine:
        apres["decision_humaine"] = True
    if type_avoir:
        apres["type_avoir"] = type_avoir
    if canal:
        apres["canal"] = canal
    append_event(
        conn,
        acteur,
        "CHANGEMENT_STATUT_DOCUMENT",
        {"statut": decision.actuel},
        apres,
    )
    return decision


def changer_statut(
    conn: sqlite3.Connection,
    document_id: str,
    statut: str,
    acteur: str = "systeme",
    **preuves: Any,
) -> DecisionTransition:
    """Compatibilité d'appel : toute transition passe désormais par la règle."""
    return appliquer_transition(conn, document_id, statut, acteur, **preuves)
