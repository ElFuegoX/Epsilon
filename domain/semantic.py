"""Rapprochement lexical : BM25 déterministe, embeddings optionnels, fusion RRF.

Ce module est possédé par Freud. Larissa peut l'appeler depuis
``domain/matching.py`` pour affiner **C3 et C4 seulement** : C1 (IFU), C2 (nom +
ville) et C5 (aucun candidat) restent des règles exactes et ne doivent jamais
être remplacées par un score approximatif.

Le mode sans dépendance est toujours disponible. Les embeddings ne sont chargés
que si ``sentence-transformers`` est installé et que ``WEMA_EMBED_MODEL`` est
défini ; aucun modèle n'est téléchargé automatiquement.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from .normalization import normalize_text

TOKEN = re.compile(r"[a-z0-9²]+", re.I)
K1 = 1.5
B = 0.75
RRF_K = 60

# Lexique métier déterministe : il corrige le jargon, il ne devine pas un client.
SYNONYMES = {
    "ramette": "papier a4",
    "paquet": "ramette",
    "a4": "papier a4",
    "banquette": "canape",
    "canape": "banquette",
    "chaise": "siege",
    "siege": "chaise",
    "livraison": "transport",
    "transport": "livraison",
    "forfait": "prestation",
    "prestation": "forfait",
}
STOPWORDS = {"de", "du", "des", "la", "le", "les", "et", "un", "une", "pour", "a", "au", "x"}


def _developper(texte: str) -> str:
    bas = normalize_text(texte).lower()
    for source, cible in SYNONYMES.items():
        bas = re.sub(rf"\b{re.escape(source)}s?\b", cible, bas)
    return bas


def tokens(texte: str | None) -> list[str]:
    if not texte:
        return []
    return [mot for mot in TOKEN.findall(_developper(texte)) if mot not in STOPWORDS]


def bm25(requete: str, documents: Mapping[str, str]) -> dict[str, float]:
    """BM25 pur Python, reproductible et sans modèle."""
    if not documents:
        return {}
    requete_tokens = tokens(requete)
    if not requete_tokens:
        return {}
    corpus = {cle: tokens(texte) for cle, texte in documents.items()}
    total = len(corpus)
    longueur_moyenne = sum(len(v) for v in corpus.values()) / total or 1.0
    freq_doc: Counter[str] = Counter()
    for mots in corpus.values():
        freq_doc.update(set(mots))
    scores: dict[str, float] = {}
    for cle, mots in corpus.items():
        freq = Counter(mots)
        longueur = len(mots) or 1
        score = 0.0
        for mot in set(requete_tokens):
            if mot not in freq:
                continue
            df = freq_doc.get(mot, 0)
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            f = freq[mot]
            score += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * longueur / longueur_moyenne))
        scores[cle] = round(score, 6)
    return scores


def embeddings(requete: str, documents: Mapping[str, str],
               modele: str | None = None) -> dict[str, float]:
    """Similarité cosinus optionnelle. Retourne {} si le modèle est absent."""
    nom = modele or os.getenv("WEMA_EMBED_MODEL", "").strip()
    if not nom or not documents:
        return {}
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return {}
    try:
        modele_charge = SentenceTransformer(nom)
        textes = [requete, *documents.values()]
        vecteurs = modele_charge.encode(textes, normalize_embeddings=True)
    except Exception:
        return {}
    reference = vecteurs[0]
    resultat: dict[str, float] = {}
    for (cle, _), vecteur in zip(documents.items(), vecteurs[1:]):
        try:
            similarite = float(reference @ vecteur)
        except (TypeError, ValueError):
            continue
        resultat[cle] = round(max(-1.0, min(1.0, similarite)), 6)
    return resultat


def rrf(classements: Sequence[Mapping[str, float]], k: int = RRF_K) -> dict[str, float]:
    """Fusion par rang réciproque. Deterministe, même à égalité."""
    scores: dict[str, float] = {}
    for classement in classements:
        for rang, cle in enumerate(sorted(classement, key=lambda c: (-classement[c], c)), start=1):
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (k + rang)
    return {cle: round(valeur, 6) for cle, valeur in scores.items()}


def similarite(a: str | None, b: str | None, *, avec_embeddings: bool = False,
               modele: str | None = None) -> dict[str, Any]:
    """Score unique dans [0, 1] pour C3/C4."""
    if not a or not b:
        return {"value": 0.0, "bm25": 0.0, "embedding": None, "rrf": 0.0}
    documents = {"candidat": b}
    bm = bm25(a, documents).get("candidat", 0.0)
    bm_norm = round(bm / (bm + 1.0), 4) if bm > 0 else 0.0
    emb = embeddings(a, documents, modele).get("candidat") if avec_embeddings else None
    if emb is None:
        fused = bm_norm
    else:
        classements = [{"candidat": bm_norm}, {"candidat": max(0.0, emb)}]
        fusion = rrf(classements).get("candidat", 0.0)
        # RRF est une somme de rangs : on la ramène dans [0, 1] sans écraser BM25.
        fused = round(max(bm_norm, min(1.0, fusion * (RRF_K + 1) / 2)), 4)
    return {
        "value": round(fused, 4),
        "bm25": bm_norm,
        "embedding": None if emb is None else round(emb, 4),
        "rrf": round(fused, 4),
    }
