# Relecture des vérités terrain — dossier Larissa

Date : 2026-11-26 · Préparé par Jean-Marie à la demande de Larissa (délégation).
**Statut : contrôle machine terminé ; signature humaine encore requise.** La graine et un script ne remplacent pas une relecture humaine : la dernière section reste à signer.

## Méthode

Contrôle contradictoire indépendant, rejouable sur les 120 fichiers `seeds/golden/*.truth.json` :

1. `truth.sha256` comparé à l'empreinte SHA-256 du fichier source réel (`source_file`).
2. `truth.sha256` comparé à celui du `*.render.json` correspondant (quand le support a un rendu ; les messages texte n'ont pas de rendu graphique).
3. Référence, type, split, champs extraits (`reference`, `dates.issue`, `client.name`, `client.ifu`, conditions) comparés aux éléments du rendu.
4. Lignes comparées champ par champ au rendu, avec normalisation canonique des unités (`m2` imprimé ≡ `m²` vérité, via `domain.normalization.normalize_unit`).
5. Totaux imprimés comparés au rendu ; totaux recalculés réindépendamment en entiers FCFA (arrondi demi-vers-le-haut par ligne) ; écart recalculé selon `seed.py::_totaux`, c'est-à-dire **recalculé − imprimé**.
6. Vérification ciblée de la pièce témoin `DEV-2026-041`.

Commande de reproduction (contrôle local, hors dépôt) : comparaison graine ↔ rendu ↔ fichier, sans appel réseau.

## Résultats

| Contrôle | Résultat |
|---|---|
| Fichiers de vérité | **120** |
| Split | **72 dev / 24 validation / 24 test** |
| Familles | 40 devis, 30 photos, 16 messages, 10 bons de livraison + 24 documents d'évaluation (10 BL, 4 messages, 10 dégradés) |
| Empreinte des fichiers sources | 120/120 conformes au `sha256` déclaré |
| Render ↔ truth (référence, type, split, champs, lignes, totaux) | 120/120 conformes après normalisation des unités |
| Recalcul déterministe indépendant | 120/120 conformes |
| Écart imprimé / recalculé | **117/120 conformes**, 3 observations ci-dessous |

### Observations (3 fichiers, sans impact mesuré)

`DEG-2026-401`, `DEG-2026-405`, `DEG-2026-409` : la dégradation (rotation de la prise de vue) ne laisse imprimer que le total HT. Le `expected_ecart` écrit par la graine contient malgré tout les écarts TVA (`3 600`) et TTC (`23 600`) de l'anomalie injectée avant dégradation, alors que `printed_totals.vat` et `printed_totals.ttc` valent `null`.

- Décision de relecture : **conserver la vérité telle que générée**. Elle décrit l'anomalie d'addition injectée ; elle n'est pas utilisée par `domain/metrics.py`, seulement par `tests/test_extraction.py` sur la pièce témoin (non dégradée).
- À signaler au jury comme limitation documentée des 3 pièces dégradées, sans modifier `seed.py` (propriété de Freud) ni régénérer le corpus.

## Pièce témoin DEV-2026-041

| Champ | Valeur relevée |
|---|---|
| Lignes | **3** |
| Client | `Ets Sossa Materiaux`, IFU **`null`** + motif `ABSENT_DE_LA_PIECE` |
| Totaux imprimés | HT `1 020 000`, TVA `183 600`, TTC `1 203 600` |
| Totaux recalculés | HT `1 040 000`, TVA `187 200`, TTC `1 227 200` |
| Écart (`imprimé − recalculé` côté API, `recalculé − imprimé` côté graine) | **20 000 FCFA** sur le HT (grandleur annoncée) |
| Ligne 3 « Livraison et installation » | quantité `1`, livrée **`0`** |
| Anomalies injectées | `arithmetique`, `MISSING_MANDATORY` |
| Bbox `120 000` (ligne 2, PU HT) | `[55.35, 20.91, 5.46, 1.28]` en pourcent, page 1 |

## Preuves de tests (Larissa)

- `python -m unittest tests.test_tax tests.test_controls tests.test_numbering tests.test_invoices tests.test_concurrency -q` → **128 tests, OK**.
- Suite complète `python -m unittest discover -s tests -t . -q` → **184 tests, OK** (dont `tests/test_e2e.py`).
- Écart de 20 000 FCFA signalé comme anomalie bloquante : couvert par `tests/test_tax.py`, `tests/test_controls.py` et `tests/test_e2e.py`.
- Double validation → un seul numéro, second clic en `409` : couvert par `tests/test_invoices.py` et `tests/test_e2e.py`.
- Avoir cumulé au-delà du TTC refusé avant écriture : couvert par `tests/test_invoices.py`.
- Chaque règle arbitrée figure dans `docs/DECISIONS.md` (date, question, décision, motif, conséquence technique).

## Point à porter au jury (arbitrage C3)

`docs/DECISIONS.md` retient : **C3 reste une suggestion à confirmer par un humain** ; seuls C1 et C2 sont automatiques. Le blueprint cite « ≥ 0,80 (C1 à C3) ». L'écart de libellé est volontaire et doit être **signalé explicitement au jury** ; la décision est écrite, elle n'est pas un oubli.

## Validation humaine (à signer)

Je soussigné(e) .........................................................., agissant pour Larissa / délégataire, confirme avoir relu la vérité terrain et les chiffres du devis témoin.

- Date : ................................
- Décision sur les 3 pièces dégradées : conserver / corriger (barrer la mention inutile) : **conserver**
- Signature : .............................................................
