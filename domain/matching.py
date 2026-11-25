"""Rapprochement tolérant mais jamais silencieux (niveaux C1 à C5).

Le domaine propose un niveau de confiance ; il ne crée ni client ni article,
ne remplace jamais une donnée absente et ne rattache rien sur un doute.
Les seuils sont explicites et déterministes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from .normalization import normalize_text

BLOQUANT = "BLOQUANT"

SEUIL_NOM_PROCHE = 0.70   # C3 : « nom proche »
SEUIL_CANDIDATS = 0.85    # C4 : similarité de raison sociale
NIVEAUX_RATTACHEMENT_AUTO = ("C1", "C2")


def similarite(a: str, b: str) -> float:
    return round(SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio(), 4)


def _texte(valeur: Any) -> str:
    return str(valeur or "").strip()


def _contact(valeur: Any) -> str:
    """Téléphone : chiffres significatifs, ponctuation et espaces ignorés."""
    return normalize_text(valeur).replace(" ", "")


def _email(valeur: Any) -> str:
    return _texte(valeur).casefold()


def _ville_coherente(ville: Any, reference: Any) -> bool:
    """Une ville absente n'infirme pas la cohérence ; une ville différente si."""
    v, r = normalize_text(ville), normalize_text(reference)
    return not v or not r or v == r


def match_client(
    clients: Sequence[Mapping[str, Any]],
    nom: str | None,
    ifu: str | None = None,
    telephone: str | None = None,
    ville: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """C1 à C5. Aucun rattachement sur IFU vide ni sur homonyme douteux."""
    nom_texte = _texte(nom)
    ifu_texte = _texte(ifu)
    if not nom_texte and not ifu_texte:
        return {"client_id": None, "niveau": "C5", "confiance": 0.0, "action": "CREATION_DIRIGEANT"}

    if ifu_texte:
        for client in clients:
            ifu_ref = _texte(client.get("ifu"))
            if ifu_ref and ifu_ref == ifu_texte:
                return {
                    "client_id": client["id"], "niveau": "C1", "confiance": 1.0,
                    "action": "RATTACHEMENT_AUTO",
                }

    nom_norm = normalize_text(nom_texte)
    for client in clients:
        if (nom_norm
                and normalize_text(client.get("raison_sociale")) == nom_norm
                and _ville_coherente(ville, client.get("ville"))):
            return {
                "client_id": client["id"], "niveau": "C2", "confiance": 0.95,
                "action": "RATTACHEMENT_AUTO_JOURNALISE",
            }

    telephone_norm = _contact(telephone)
    email_norm = _email(email)
    for client in clients:
        meme_contact = bool(
            (telephone_norm and _contact(client.get("telephone")) == telephone_norm)
            or (email_norm and _email(client.get("email") or client.get("e_mail")) == email_norm)
        )
        if meme_contact and similarite(nom_texte, client.get("raison_sociale", "")) >= SEUIL_NOM_PROCHE:
            return {
                "client_id": client["id"], "niveau": "C3", "confiance": 0.80,
                "action": "SUGGESTION_A_CONFIRMER",
            }

    candidats = [
        client for client in clients
        if similarite(nom_texte, client.get("raison_sociale", "")) >= SEUIL_CANDIDATS
    ]
    if candidats:
        return {
            "client_id": None, "niveau": "C4", "confiance": 0.50,
            "action": "REVUE_HUMAINE", "candidats": [c["id"] for c in candidats],
        }

    return {"client_id": None, "niveau": "C5", "confiance": 0.0, "action": "CREATION_DIRIGEANT"}


def match_item(
    items: Sequence[Mapping[str, Any]],
    description: str,
    famille: str | None = None,
) -> dict[str, Any]:
    """Les prestations sur mesure restent libres, rattachées à une famille."""
    description_norm = normalize_text(description)
    for item in items:
        designation = normalize_text(item.get("designation"))
        if description_norm and designation and description_norm == designation:
            return {
                "item_id": item["id"], "famille": item.get("famille"),
                "confiance": 1.0, "action": "RATTACHEMENT_AUTO",
            }
    if items:
        score, item = max(
            (
                (similarite(description, i.get("designation", "")), i)
                for i in items if normalize_text(i.get("designation"))
            ),
            key=lambda couple: couple[0],
            default=(0.0, None),
        )
        if item is not None and score >= SEUIL_CANDIDATS:
            return {
                "item_id": None, "famille": item.get("famille"), "confiance": 0.50,
                "action": "SUGGESTION_A_CONFIRMER",
            }
    if famille:
        return {
            "item_id": None, "famille": famille, "confiance": 0.30,
            "action": "LIGNE_LIBRE_JUSTIFIEE",
        }
    return {"item_id": None, "famille": None, "confiance": 0.0, "action": "A_RATTACHER"}


def _quantite_exacte(valeur: Any) -> Decimal:
    """Décimale exacte : jamais un flottant monétaire, jamais NaN/infini."""
    if isinstance(valeur, bool) or isinstance(valeur, float):
        raise TypeError("quantité flottante interdite : fournir un entier ou une chaîne")
    try:
        quantite = Decimal(str(valeur if valeur not in (None, "") else 0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"quantité invalide : {valeur}") from exc
    if not quantite.is_finite():
        raise ValueError(f"quantité invalide : {valeur}")
    return quantite


@dataclass(frozen=True)
class ComparaisonQuantite:
    """Commandé / livré / facturé d'une ligne. `livree=None` = inconnue.

    Les trois écarts sont exposés séparément : le domaine affiche, il ne
    corrige jamais une quantité.
    """

    numero: int
    description: str
    commandee: Decimal
    livree: Decimal | None
    facturee: Decimal
    statut: str
    ecart_livre_commande: Decimal | None = None
    ecart_livre_facture: Decimal | None = None
    ecart_facture_commande: Decimal = Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero": self.numero,
            "description": self.description,
            "commandee": str(self.commandee),
            "livree": None if self.livree is None else str(self.livree),
            "facturee": str(self.facturee),
            "statut": self.statut,
            "ecart_livre_commande": (
                None if self.ecart_livre_commande is None else str(self.ecart_livre_commande)
            ),
            "ecart_livre_facture": (
                None if self.ecart_livre_facture is None else str(self.ecart_livre_facture)
            ),
            "ecart_facture_commande": str(self.ecart_facture_commande),
        }


def compare_quantites(
    lignes: Sequence[Mapping[str, Any]],
    livree: Mapping[int, Any],
) -> list[ComparaisonQuantite]:
    """Compare les trois quantités sans jamais inventer une livraison absente.

    Une ligne absente de `livree` donne `livree=None` et le statut
    `LIVRAISON_INCONNUE`, avec des écarts de livraison à `None`. Les champs
    optionnels `quantite_commandee` et `quantite_facturee` permettent de
    distinguer commandé et facturé quand le contrat API les fournit ; sinon
    `quantite` sert aux deux.
    """
    livree_normalisee = {int(cle): valeur for cle, valeur in livree.items()}
    comparaisons: list[ComparaisonQuantite] = []
    for ligne in lignes:
        numero = int(ligne.get("numero") or 0)
        base = ligne.get("quantite")
        commandee = _quantite_exacte(
            ligne.get("quantite_commandee")
            if ligne.get("quantite_commandee") not in (None, "") else base
        )
        facturee = _quantite_exacte(
            ligne.get("quantite_facturee")
            if ligne.get("quantite_facturee") not in (None, "") else base
        )
        valeur = livree_normalisee.get(numero)
        quantite_livree = None if valeur is None or valeur == "" else _quantite_exacte(valeur)
        if quantite_livree is None:
            statut = "LIVRAISON_INCONNUE"
        elif quantite_livree < facturee:
            statut = "LIVREE_INFERIEURE"
        elif quantite_livree > facturee:
            statut = "LIVREE_SUPERIEURE"
        else:
            statut = "OK"
        comparaisons.append(
            ComparaisonQuantite(
                numero=numero,
                description=str(ligne.get("description") or ""),
                commandee=commandee,
                livree=quantite_livree,
                facturee=facturee,
                statut=statut,
                ecart_livre_commande=(
                    None if quantite_livree is None else quantite_livree - commandee
                ),
                ecart_livre_facture=(
                    None if quantite_livree is None else quantite_livree - facturee
                ),
                ecart_facture_commande=facturee - commandee,
            )
        )
    return comparaisons
