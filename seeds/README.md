# Jeu de pièces — WÉMA

Toutes les données sont **fictives**. Aucun nom, IFU ou montant réel.

Génération du corpus : `python -m seed --as-of 2026-11-25` (responsable Freud).
Avec `--reset`, la base est aussi réinitialisée et chargée (référentiels, historique,
96 pièces extraites). La graine `20261125` et la date de référence produisent
toujours les mêmes pièces.

## Deux jeux distincts

| Jeu | Pièces | Usage |
|---|---:|---|
| Démonstration (`generated/demo/`) | 96 | interface, parcours, vidéo |
| Évaluation annotée (`generated/eval/` + les 96 pièces) | 120 | mesures reproductibles |

| Famille | Démo | Ajouts éval | Total annoté |
|---|---:|---:|---:|
| Devis PDF | 40 | 0 | 40 |
| Photos de commande | 30 | 0 | 30 |
| Messages | 16 | 4 | 20 |
| Bons de livraison | 10 | 10 | 20 |
| Photos dégradées (rotation, ombre, tampon) | 0 | 10 | 10 |
| **Total** | **96** | **24** | **120** |

Le split est écrit dans chaque vérité terrain : 72 dev / 24 validation / 24 test.

## Référentiels et historique

| Élément | Volume |
|---|---:|
| Clients | 64 |
| Articles | 120 |
| Factures historiques | 60 |
| Avoirs | 9 |
| Paiements simulés | 18 |
| Anomalies injectées | 44 signaux sur 120 documents |

## Ce que contient chaque dossier

| Chemin | Contenu | Versionné |
|---|---|---|
| `golden/*.truth.json` | Vérité terrain champ par champ ; montants imprimés et recalculés séparés (l'écart est une donnée, pas une correction). Relecture humaine de Larissa à faire. | oui |
| `ocr_cache/*.json` | Sorties **réelles** d'EasyOCR sur les photos (mots, boîtes, confiances), indexées par l'empreinte des pixels. Le mode `demo` les rejoue hors ligne. | oui |
| `generated/**` | Pièces rendues (PDF, PNG, TXT) et `*.render.json` | non (régénéré) |

Le fichier `*.render.json` décrit ce que le générateur a dessiné. Il sert à la
vérité terrain et à l'ablation « OCR parfait » de `domain.metrics` ; **l'extraction
ne le lit jamais** : elle lit le PDF (pdfplumber) ou l'image (EasyOCR ou son cache).

## Rendu

- PDF : vraie couche texte Helvetica, tableau en colonnes alignées comme un devis réel.
- Photos : page rendue avec la police vectorielle embarquée de Pillow (sans accents,
  elle n'en a pas), puis « photographiée » : fond, perspective, rotation légère,
  éclairage inégal, grain et flou, tous tirés de la graine.
- Photos dégradées : rotation de 3 à 4,5°, ombre forte ou tampon rouge posé
  **sur l'image** ; la vérité terrain reste celle de la pièce imprimée.

Après une régénération qui change des images : `python -m adapters.ocr --warm`
(nécessite `pip install -r requirements-ocr.txt`) puis committer `ocr_cache/`.
