# Jeu de pièces — WÉMA

Toutes les données sont **fictives**. Aucun nom, IFU ou montant réel.

Génération : `python -m seed --reset --as-of 2026-11-25` (responsable Freud).
La graine `20261125` et la date de référence produisent toujours les mêmes octets.

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
| Cas dégradés | 0 | 10 | 10 |
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

`golden/*.truth.json` contient la vérité terrain, relue par Larissa. Les montants
imprimés et les montants recalculés y sont séparés : l'écart est une donnée,
pas une correction. `generated/*.layout.json` contient les blocs OCR avec
`bbox` en pourcentage de page (`{x, y, w, h}`) pour la visionneuse.

`generated/` est produit par la graine et n'est pas versionné.
