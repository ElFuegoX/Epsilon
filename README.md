---
title: WEMA Facturation
emoji: 🧾
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# WÉMA — atelier de facturation vérifiable

> Prototype du cas pratique 2 (BWAI 2026). Une pièce entre — devis PDF, photo ou message WhatsApp —, une facture juste sort. **Aucune donnée manquante n'est inventée.**

**Prototype non agréé.** WÉMA prépare et simule une facture ; il n'est pas un SFE agréé par la DGI, ne transmet rien à l'administration, ne certifie rien et ne remplace ni expert-comptable ni juriste. Les QR codes et codes MECeF sont factices. Toutes les données du jeu de démonstration sont fictives.

---

## Démarrage rapide

### Option 1 — Tout-en-un sur votre PC *(sans Docker, le plus simple)*

**Prérequis :** Python 3.11+ et Node.js 18+.

1. **Première installation (une seule fois) :**
   ```bash
   pip install -r requirements.txt
   cd web && npm install && npm run build && cd ..
   python -m seed --reset --as-of 2026-11-25
   ```
   *(Sur Windows PowerShell, remplacez `&&` par `;` si vous utilisez PowerShell 5.)*

2. **Lancer l'application complète (interface + API + worker en une commande) :**
   ```bash
   python -m cli serve
   ```
   Puis ouvrez **http://localhost:7860** dans votre navigateur (et **http://localhost:7860/docs** pour la documentation API).

---

### Option 2 — Avec Docker *(une seule commande)*

Assurez-vous que **Docker Desktop** est démarré, puis lancez :

```bash
docker compose up --build
```

* Interface web : http://localhost:5173
* API & documentation interactive : http://localhost:8000/docs

---

### Option 3 — Mode développement *(rechargement automatique)*

Ouvrez 3 terminaux à la racine du dépôt :

```bash
# Terminal 1 — API FastAPI (port 8000)
python -m api.app

# Terminal 2 — Worker de file persistante (reprise après coupure)
python -m worker.run --loop

# Terminal 3 — Interface React en direct (port 5173)
cd web && npm run dev
```

---

## Déploiement gratuit (Hugging Face Spaces)

Le dépôt est prêt pour un déploiement tout-en-un à 0 € sur **Hugging Face Spaces** (l'en-tête YAML de ce `README.md` et le `Dockerfile` multi-étapes sont déjà configurés) :

1. Créez un nouveau Space sur Hugging Face en choisissant **SDK : Docker**.
2. Poussez ce dépôt sur le remote du Space (`git push <space-remote> main`).
3. Le `Dockerfile` compile automatiquement l'interface React (`web/dist`), charge l'API + le worker et expose l'application complète sur le port `7860`.

---

## Vérifier que tout fonctionne

```bash
# Exécuter toute la suite de tests (sans réseau)
python -m unittest discover -s tests -t . -v

# Vérifier l'intégrité de la chaîne d'audit SHA-256, la numérotation et les PDF
python -m cli verify

# Réinitialiser la base de démonstration au propre
python -m seed --reset --as-of 2026-11-25
```

| Commande | Effet |
|---|---|
| `python -m cli serve` | Démarre l'interface + API + worker sur http://localhost:7860 |
| `python -m seed --reset --as-of 2026-11-25` | Recharge les 120 pièces, 64 clients, 120 articles, 60 factures, 9 avoirs |
| `python -m cli verify` | Vérifie la chaîne d'audit SHA-256, la continuité des numéros et les hash PDF |
| `python -m cli clean` | Supprime la base locale et les fichiers générés |
| `make test` / `make verify` / `make reset` | Raccourcis équivalents si `make` est installé |

---

## Postes de test (rôles)

Rôle transmis par l'en-tête `X-Role` et sélectionnable directement en haut de l'interface (authentification simulée, jamais en production).

| Poste dans l'interface | Code `X-Role` | Peut | Ne peut pas |
|---|---|---|---|
| **Responsable comptable / Dirigeant** | `dirigeant` | tout, dont valider, numéroter, émettre un avoir, créer un client, réinitialiser | — |
| **Opérateur facturation / Commercial** | `assistante` | importer, préparer les brouillons, résoudre les anomalies, émettre | valider, créer un client, émettre un avoir |
| **Auditeur (Lecture seule)** | `lecture` | consulter le registre, vérifier et exporter le journal CSV | modifier |

---

## Variables d'environnement

Copier `.env.example` vers `.env` si besoin. Valeurs par défaut déterministes :

```env
AS_OF=2026-11-25
DEVISE=XOF
ARRONDI=DEMI_VERS_LE_HAUT
GRAINE_DEMO=20261125
FUSEAU=Africa/Porto-Novo
AI_BACKEND=demo        # demo | cloud | cpu
AI_TIMEOUT_S=8
```

`AI_BACKEND=demo` fonctionne **sans réseau et sans clé API** : c'est le mode garanti pour la démonstration et la réexécution par le jury.

---

## Structure du projet

```text
Epsilon/                          racine du dépôt
├── api/          routes FastAPI, schémas Pydantic, contrôle d'accès X-Role
├── domain/       documents, extraction, normalisation, matching, 9 contrôles, TVA, numérotation, audit
├── adapters/     ocr, llm, constraints, pdf déterministe, email_sim, whatsapp_sim, mecef_stub
├── worker/       file d'extraction persistante (EN_ATTENTE_IA -> EXTRAIT) et reprise
├── config.py     paramètres déterministes (AS_OF, seuils, stockage)
├── db.py         SQLite WAL, schéma et transactions BEGIN IMMEDIATE
├── schema.sql    tables et triggers d'immutabilité SQL
├── seed.py       génération du jeu de démonstration reproductible
├── cli.py        serve / verify / clean
├── web/          interface React + Vite + Tailwind, visionneuse PDF
├── seeds/        vérités terrain (120 documents) et cache OCR
├── tests/        calcul, contrôles, concurrence, immuabilité, audit, extraction, e2e
└── docs/         blueprint, rapport, fiche IA, extraction, recette, API, décisions
```

Pipeline d'extraction (corpus, OCR, cache, contrat JSON, mesures) : voir [`docs/EXTRACTION.md`](docs/EXTRACTION.md) et [`docs/FICHE_IA.md`](docs/FICHE_IA.md).

---

## Les 4 gestes que le jury peut rejouer

1. Importer deux fois le même devis → une seule pièce (hash SHA-256 identique, refus `409`).
2. Valider deux fois le même brouillon → une seule facture, un seul numéro continu.
3. Tenter de modifier une facture émise → refus `409` (`INVOICE_IMMUTABLE`).
4. Émettre un avoir total → facture conservée au registre, solde nul, numérotation continue.

## Limites assumées

Pas d'agrément e-MECeF, pas d'envoi réel à la DGI, pas de paiement réel, pas de lecture parfaite de l'écriture manuscrite, pas de gestion de stock, pas de factures fournisseurs. Voir `docs/RAPPORT_trame.md`.

---

## Répartition du travail

Tout est centralisé dans **[Plan.md](Plan.md)** : attribution nominative (Larissa, Melon, Jean-Marie, Freud), tâches, fichiers possédés, déroulé, conventions et checklist.
