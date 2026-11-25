# WÉMA — atelier de facturation vérifiable

> Prototype du cas pratique 2 (BWAI 2026). Une pièce entre — devis PDF, photo ou message —, une facture juste sort. **Aucune donnée manquante n'est inventée.**

**⚠️ Prototype non agréé.** WÉMA prépare et simule une facture ; il n'est pas un SFE agréé par la DGI, ne transmet rien à l'administration, ne certifie rien et ne remplace ni expert-comptable ni juriste. Les QR codes et codes MECeF sont factices. Toutes les données du jeu de démonstration sont fictives.

---

## Démarrage en une commande

```bash
docker compose up --build
```

API : http://localhost:8000 · Interface : http://localhost:5173 · Docs API : http://localhost:8000/docs

Sans Docker (développement) :

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt -r requirements-dev.txt
python -m seed --reset --as-of 2026-11-25
python -m api.app                 # API
cd web && npm install && npm run dev
```

## Commandes utiles

| Commande | Effet |
|---|---|
| `make seed` | Charge 96 pièces, 64 clients, 120 articles, 60 factures, 9 avoirs |
| `make reset` | Réinitialise complètement la démo (`AS_OF=2026-11-25`) |
| `make test` | Tests de calcul, provenance, concurrence, immuabilité, audit |
| `make verify` | Vérifie la chaîne d'audit et les hash des PDF |
| `make demo` | Lance l'API en mode démo déterministe (`AI_BACKEND=demo`) |
| `git tag v1.1-bwai` | Étiquette de version du dépôt |

## Comptes de test (rôles)

Rôle transmis par l'en-tête `X-Role` (authentification simulée, jamais en production).

| Rôle | Peut | Ne peut pas |
|---|---|---|
| `dirigeant` | tout, dont valider, émettre un avoir, créer un client, réinitialiser | — |
| `assistante` | importer, corriger, résoudre (sauf prix), émettre | valider, créer un client, émettre un avoir |
| `lecture` | lire et exporter le journal | modifier |

## Variables d'environnement

Copier `.env.example` vers `.env`. Valeurs par défaut déterministes :

```
AS_OF=2026-11-25
DEVISE=XOF
ARRONDI=DEMI_VERS_LE_HAUT
GRAINE_DEMO=20261125
FUSEAU=Africa/Porto-Novo
AI_BACKEND=demo        # demo | cloud | cpu
AI_TIMEOUT_S=8
```

`AI_BACKEND=demo` fonctionne **sans réseau et sans clé API** : c'est le mode de la démonstration.

## Structure

```
Epsilon/                          racine du dépôt, on travaille toujours ici
├── api/          routes, schémas, rôles
├── domain/       documents, extraction, normalisation, matching, contrôles, taxe, numérotation, audit
├── adapters/     ocr, llm, pdf, email_sim, whatsapp_sim, mecef_stub
├── worker/       file d'extraction persistante et reprise
├── config.py     paramètres déterministes (AS_OF, seuils, stockage)
├── db.py         SQLite WAL, schéma et transactions
├── schema.sql    tables et triggers d'immutabilité
├── seed.py       génération du jeu de démonstration
├── cli.py        make verify / make clean
├── web/          React, visionneuse PDF, 10 écrans
├── seeds/        pièces et vérité terrain
├── tests/        calcul, concurrence, immuabilité, extraction
└── docs/         blueprint, rapport, fiche IA, recette, API, décisions
```

Les sous-dossiers du backend sont directement à la racine : il n'y a plus de dossier `wema/`.
Les imports se font donc en absolu (`from config import settings`, `from db import transaction`, `from adapters.pdf import ...`).

## Les 4 gestes que le jury peut rejouer

1. Importer deux fois le même devis → une seule pièce (hash identique).
2. Valider deux fois le même brouillon → une seule facture, un seul numéro.
3. Tenter de modifier une facture émise → refus (409).
4. Émettre un avoir total → facture conservée, solde nul, numérotation continue.

## Limites assumées

Pas d'agrément e-MECeF, pas d'envoi réel à la DGI, pas de paiement réel, pas de lecture parfaite de l'écriture manuscrite, pas de gestion de stock, pas de factures fournisseurs. Voir `docs/RAPPORT_trame.md`.

---

## Répartition du travail (tout le monde code)

| Personne | Piste | Tâche |
|---|---|---|
| **Larissa** | Règles métier | Moteurs TVA, 9 contrôles, numérotation, facture/avoir, `domain/**` et leurs tests |
| **Melon** | API & infrastructure | SQLite, endpoints, worker, audit, rôles, adaptateurs de sortie, `api/**`, `db.py`, `worker/**` |
| **Jean-Marie** | Frontend | Les 10 écrans React, visionneuse PDF et provenance cliquable, `web/**` |
| **Freud** | Données & IA | Corpus 120 pièces, vérité terrain, extraction OCR/LLM, `seed.py`, `domain/extraction.py`, `adapters/ocr.py`, `adapters/llm.py` |

La présentation, le pitch, la vidéo et le rapport ne sont pas assignés maintenant : ils seront faits **quand l'outil sera prêt**.

**Plan détaillé, tâches et critères de fin : [Plan.md](Plan.md).**
