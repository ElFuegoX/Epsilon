# Recette — piste Larissa (règles métier et moteurs déterministes)

Responsable : **Larissa**. Les résultats ci-dessous sont écrits **avant** l’implémentation.
Ils servent de spécification exécutable : aucun résultat « observé » n’est inventé après coup.

- Date de rédaction : 2026-11-25.
- Branche de travail : `main` (choix de Larissa, confirmé au démarrage).
- Références : `Plan.md` §3, blueprint v1.1 §5.7 à §5.10 et annexe E,
  `seeds/golden/DEV-2026-041.truth.json`, `docs/DECISIONS.md`.
- Périmètre : calcul, contrôles, numérotation, factures/avoirs, rapprochement, règles liées aux pièces.
- Hors périmètre exécuté ici : API, SQLite réelle, frontend, extraction IA, génération PDF (Melon/Freud/Jean-Marie).

## Conventions de lecture

- Devise unique : `XOF` / FCFA. Montants monétaires : **entiers FCFA**, jamais de flottant.
- Date de référence : `AS_OF=2026-11-25`. Tolérance arithmétique : `0 FCFA`.
- Écart affiché : **`imprimé − recalculé`** (convention déjà présente dans `domain/tax.py::comparer`).
  Un écart positif signifie que la pièce imprimée annonce un montant trop élevé.
- Sévérités : `BLOQUANT` ou `AVERTISSEMENT`. Une anomalie bloquante empêche la validation
  tant qu’elle n’est pas résolue par une décision humaine **tracée** (acteur, motif, avant/après).
- « Résolu » ne veut pas dire « effacé » : l’anomalie reste dans l’historique avec sa trace.
- Colonne « Observé » : toujours `À mesurer` jusqu’à l’exécution réelle des tests.

---

## R1 — DEV-2026-041 : recalcul et écart d’arithmétique

### Données d’entrée

| Champ | Valeur |
|---|---|
| Référence | `DEV-2026-041` |
| Type de pièce | `devis` |
| Date de la pièce | `2026-11-18` |
| Client | `Ets Sossa Matériaux`, IFU `null` + motif `ABSENT_DE_LA_PIECE` |
| Conditions | présentes dans la pièce |
| Code fiscal | `TVA18` (18 %, soit `1800` points de base) |

| Ligne | Désignation | Quantité | PU HT | Brut HT | Remise | Net HT | TVA 18 % | TTC ligne |
|---|---|---|---|---|---|---|---|---|
| 1 | Banquette 3 places | 4 | 185 000 | 740 000 | 0 | 740 000 | 133 200 | 873 200 |
| 2 | Table basse chêne | 2 | 120 000 | 240 000 | 0 | 240 000 | 43 200 | 283 200 |
| 3 | Livraison et installation | 1 | 60 000 | 60 000 | 0 | 60 000 | 10 800 | 70 800 |

Montants imprimés sur le devis : HT `1 020 000`, TVA `183 600`, TTC `1 203 600`.

Livraison déclarée : ligne 1 → `4`, ligne 2 → `2`, ligne 3 → `0`.

### Résultats attendus

| Grandeur | Recalculé | Imprimé | Écart (imprimé − recalculé) |
|---|---|---|---|
| Total HT | **1 040 000** | 1 020 000 | **−20 000** |
| Total TVA | **187 200** | 183 600 | **−3 600** |
| Total TTC | **1 227 200** | 1 203 600 | **−23 600** |

> Le document source et `Plan.md` parlent d’un « écart de 20 000 FCFA ». La grandeur est
> `|20 000|` ; le signe `-20 000` vient de la convention `imprimé − recalculé`.
> Le moteur ne modifie ni le total imprimé ni les lignes source.
>
> L'arrondi TVA est appliqué **par ligne, puis sommé** (jamais sur le total). Si une remise globale
> de 20 000 FCFA est appliquée, le HT retombe à 1 020 000 mais la TVA vaut 183 599 et le TTC
> 1 203 599 : un résidu de 1 FCFA subsiste face à l'imprimé. Ce résidu est attendu et n'est jamais
> corrigé silencieusement (voir `docs/DECISIONS.md`).

Anomalies attendues :

| Code | Sévérité | Champ | Précision |
|---|---|---|---|
| `ARITHMETIC_MISMATCH` | `BLOQUANT` | `totaux.ht` | écart `-20 000` FCFA |
| `ARITHMETIC_MISMATCH` | `BLOQUANT` | `totaux.vat` | écart `-3 600` FCFA |
| `ARITHMETIC_MISMATCH` | `BLOQUANT` | `totaux.ttc` | écart `-23 600` FCFA |
| `QUANTITY_MISMATCH` | `BLOQUANT` | `ligne 3` | 1 facturée, 0 livrée |
| `MISSING_MANDATORY` | `BLOQUANT` | `IFU client` | aucune valeur proposée |

Le `hash_calcul` est stable : deux exécutions avec les mêmes lignes, les mêmes taux et le
même `AS_OF` produisent le même hash. Ce hash est repris dans le snapshot de validation.

### Critères de réussite

- `tests/test_tax.py` affirme les six montants recalculés et les trois écarts.
- `tests/test_controls.py` affirme la présence de `ARITHMETIC_MISMATCH` avec sévérité bloquante.
- Tant que l’écart n’est pas résolu explicitement, `validate_draft()` lève `AnomaliesBloquantes`
  et **aucune facture ni aucun numéro fiscal** n’est créé.
- Aucun total imprimé n’est remplacé silencieusement.

---

## R2 — IFU absent : demander, ne pas inventer

### Données d’entrée

Client `Ets Sossa Matériaux`, champ `ifu = {"value": null, "missing": "ABSENT_DE_LA_PIECE"}`.
Toutes les autres mentions obligatoires sont présentes.

### Résultats attendus

- Code `MISSING_MANDATORY`, sévérité `BLOQUANT`, champ `IFU client`.
- Aucune valeur d’IFU n’est déduite du nom, d’un homonyme ou du référentiel sans décision humaine.
- Message de clarification généré à partir de la référence `DEV-2026-041` et du seul champ manquant,
  sans valeur proposée. Si l’échéance manque aussi, elle est ajoutée à la liste des manquants.

### Critères de réussite

- Validation refusée tant que l’IFU n’est pas renseigné.
- Le test « zéro valeur inventée » de Freud reste cohérent avec le contrôle de Larissa.
- La résolution, quand elle arrive, porte source `référentiel`, acteur, motif et horodatage.

---

## R3 — Ligne commandée mais non livrée

### Données d’entrée

| Ligne | Commandée / facturée | Livrée |
|---|---|---|
| 1 · Banquette 3 places | 4 | 4 |
| 2 · Table basse chêne | 2 | 2 |
| 3 · Livraison et installation | 1 | **0** |

### Résultats attendus

- Sans décision : `QUANTITY_MISMATCH`, sévérité `BLOQUANT`, champ `ligne 3`,
  message indiquant `1 facturée` et `0 livrée`. Aucune facture.
- Avec décision humaine tracée `EXCLURE` sur la ligne 3 :
  - ligne 3 absente de la facture ;
  - total HT facturé `980 000`, TVA `176 400`, TTC `1 156 400` ;
  - événement d’audit avec acteur, motif, avant (`1`) et après (`0` ou ligne exclue).
- Une ligne non livrée ne peut pas être facturée sur la seule base d’une absence de données de livraison.

### Critères de réussite

- `tests/test_controls.py` couvre le cas sans décision et le cas avec décision tracée.
- Le rapprochement compare explicitement **commandé / livré / facturé** (`domain/matching.py`).
- Aucune quantité livrée n’est supposée quand la table de livraison est vide.

---

## R4 — Client inconnu

### Données d’entrée

Nom fourni mais aucun rattachement automatique possible : aucun IFU identique (C1),
aucun nom normalisé identique avec ville cohérente (C2). Les niveaux C3, C4 et C5
restent à confirmer par une décision humaine tracée.

### Résultats attendus

- `UNKNOWN_CLIENT`, sévérité `BLOQUANT`.
- Aucun client créé automatiquement pour « débloquer » la facture.
- Rattachement ou création réservé à une décision autorisée et journalisée.

### Critères de réussite

- `tests/test_controls.py` couvre C1 à C5, dont le téléphone et l’e-mail pour C3 et la liste
  de candidats pour C4, sans aucun rattachement dans ces deux cas.
- Le résultat de `domain/matching.py::match_client()` est consommé tel quel, sans écraser
  la confiance par une valeur fabriquée dans `build_context()`. La règle « seuls C1/C2
  sont automatiques » est portée par `NIVEAUX_RATTACHEMENT_AUTO` et consommée par `controls.py`.

---

## R5 — Article inconnu

### Données d’entrée

Ligne `Banquette 3 places sur mesure`, sans `item` ni `famille`.

### Résultats attendus

- `UNKNOWN_ITEM`, sévérité `AVERTISSEMENT`.
- La ligne peut rester libre si elle est rattachée à une famille, porte une unité et un prix justifié.
- Sinon, l’avertissement reste ouvert jusqu’au rattachement ou à la justification.

### Critères de réussite

- `tests/test_controls.py` vérifie qu’un avertissement **seul** ne bloque pas la validation.
- La description brute extraite est conservée.

---

## R6 — Prix inhabituel

### Données d’entrée

Ligne 2 : PU HT `156 000` FCFA ; tarif de référence `120 000` FCFA (écart `+30 %`).

### Résultats attendus

- `UNUSUAL_PRICE`, sévérité `AVERTISSEMENT`, message indiquant l’écart en pourcentage.
- Seuil : écart strictement supérieur à `10 %` (`ECART_PRIX_PCT`).
- Au-delà du seuil dirigeant (`SEUIL_DIRIGEANT = 1 000 000 FCFA`), justification et validation
  du dirigeant exigées avant passage à l’état suivant.

### Critères de réussite

- Test d’un écart à `+10 %` (pas d’anomalie) et à `+11 %` (anomalie).
- Le prix catalogue et la moyenne des 90 derniers jours restent des données du référentiel ;
  le moteur n’en invente aucune.

---

## R7 — Doublon de document

### Données d’entrée

Fichier dont le SHA-256 est identique à celui d’une pièce déjà importée.

### Résultats attendus

- `DUPLICATE_DOCUMENT`, sévérité `BLOQUANT`.
- L’identifiant de la pièce existante est retrouvé et renvoyé.
- Aucun nouvel import métier, aucun nouveau brouillon, aucune nouvelle facture.

### Critères de réussite

- Test avec un contexte contenant `doublon_document=True`.
- `domain/documents.py::decider_doublon()` refuse tout doublon transmis avant la moindre écriture ;
  seul `REJETÉ` est alors une transition recevable.
- Test complémentaire avec Melon : hash unique en base et réponse idempotente sur `POST /documents`.

---

## R8 — Doublon de facture

### Données d’entrée

Facture déjà validée avec la même empreinte métier (client, date, lignes normalisées).

### Résultats attendus

- `DUPLICATE_INVOICE`, sévérité `BLOQUANT`.
- Aucune seconde facture créée.
- Une confirmation de facture distincte exige motif et trace.

### Critères de réussite

- Test de l’empreinte métier dans `tests/test_controls.py`.
- Le critère « même client + même montant + date à `±3 jours` » est **implémenté** depuis
  les champs déjà présents dans `schema.sql` (`client`, `total_ttc`, `date`) et couvert
  par un test SQLite en mémoire.
- Le critère « même référence de commande déjà facturée » reste **en attente** : aucune
  colonne `reference_commande` n'existe dans `schema.sql` (Melon). Il ne sera pas considéré
  comme livré tant que le contrat ne fournira pas ce champ.

---

## R9 — TVA invalide

### Données d’entrée — trois cas

| Cas | Entrée |
|---|---|
| Code hors référentiel | `tax_code = "TVA_MAJ"` absent de `tax_codes` |
| Exonération non justifiée | code exonéré sans `justification` |
| Base négative | quantité `1`, PU `10 000`, remise `12 000` → net `-2 000` |

### Résultats attendus

- `INVALID_TAX`, sévérité `BLOQUANT`, dans chacun des trois cas.
- Message distinct pour chaque cause : code absent, exonération non documentée, base négative.
- Aucune facture créée.

### Critères de réussite

- Un test par cause dans `tests/test_controls.py`.
- Le taux est résolu depuis le référentiel par code fiscal ; aucun défaut silencieux à 18 %.
- Le contrôle s’appuie sur `tax_codes.exoneration`, pas sur un code littéral figé.

---

## R10 — Numérotation, échec et idempotence

### Données d’entrée

Base réinitialisée (`AS_OF=2026-11-25`) : séquence `FAC` à `1`, séquence `AV` à `1`.
Deux appels `validate_draft()` avec la **même clé d’idempotence** et le même brouillon complet.

### Résultats attendus

| Situation | Numéro | Effet |
|---|---|---|
| Validation réussie | `FAC-2026-00001` | 1 facture, séquence suivante `00002` |
| Second appel identique | `FAC-2026-00001` | même réponse, **aucun** second numéro consommé |
| Validation échouée (anomalie bloquante non résolue) | aucun | séquence toujours à `00001` ; aperçu inchangé |
| Avoir lié | `AV-2026-00001` | série indépendante, continuité propre |

### Critères de réussite

- `tests/test_numbering.py` : continuité des deux séries, unicité, garde de transaction, aucun numéro consommé après rollback ou échec, aperçu sans consommation, détection d'une dérive de compteur.
- `tests/test_invoices.py` : deux validations avec la même clé → une facture, une réponse identique ; clé lue dans la transaction, aucun numéro consommé en cas d’échec.
- UUID technique et numéro fiscal restent deux identifiants distincts.
- La vérification concurrente avec la vraie SQLite (deux processus) est à faire **avec Melon** ; un test isolé en mémoire ne suffit pas à la prouver.

---

## R11 — Immutabilité de la facture émise

### Données d’entrée

Facture au statut `VALIDÉ` ou `ÉMIS`, avec `hash_snapshot` et `hash_pdf` connus.
Tentative de modification d’un montant, du client, de la date ou du snapshot, puis tentative de suppression.

### Résultats attendus

- Refus par le trigger SQL `INVOICE_IMMUTABLE` et erreur `409` traduite par l’API (Melon).
- `numero`, `snapshot`, `hash_snapshot`, `hash_pdf`, `total_ht`, `total_tva`, `total_ttc`, `client`, `date` inchangés.
- Seuls le statut, le canal et la référence simulée peuvent évoluer lors de l’émission.

### Critères de réussite

- `tests/test_invoices.py` couvre le refus `UPDATE` des champs fiscaux et le refus `DELETE` (trigger `INVOICE_IMMUTABLE`), ainsi que l’émission qui ne change que statut, canal et référence simulée.
- `verifier_pdf()` régénère depuis le snapshot et retrouve le même hash ; le générateur est injecté en attendant `adapters.pdf` de Melon.
- Test API 409 avec Melon dans `tests/test_concurrency.py` (à faire avec Melon).

---

## R12 — Avoirs, solde et bornes

### Données d’entrée

Facture `FAC-2026-00001`, TTC initial `1 227 200`.

| Avoir | Lignes | TTC attendu | Solde après avoir | Statut facture |
|---|---|---|---|---|
| Partiel | ligne 2, quantité `1`, PU `120 000` | `141 600` | `1 085 600` | `ÉMIS` |
| Total | lignes 1 + 2 + 3 aux quantités facturées | `1 227 200` | `0` | `ANNULÉ_PAR_AVOIR` |

Cas refusés :

- cumul des avoirs `> 1 227 200` ;
- quantité d’avoir `> ` quantité facturée sur la ligne correspondante ;
- ligne d’avoir absente de la facture.

### Résultats attendus

- Refus **avant toute écriture** : aucun numéro `AV` consommé, aucune ligne `credit_notes` insérée.
- Avoir total : facture conservée au registre, liée, non supprimée.
- Nouvelle facture éventuelle : nouveau numéro `FAC`, référence explicite à l’avoir concerné.

### Critères de réussite

- `tests/test_invoices.py` couvre partiel, total, cumul > TTC, dépassement par ligne, ligne inexistante, idempotence et refus avant écriture (aucun numéro `AV` consommé).
- Le cumul des avoirs par ligne est comparé avec des décimales exactes, jamais avec `float`.
- La limite **cumulée par ligne** est arbitrée et implémentée (Larissa, 2026-11-25) ; elle consomme `avoirs_precedents`, fourni par l’API tant que `schema.sql` n’expose pas `credit_note_lines`.

---

## R13 — Rapprochement commandé / livré / facturé

### Données d’entrée

| Ligne | Commandée | Livrée | Facturée | Décision |
|---|---|---|---|---|
| 1 · Banquettes | 4 | 4 | 4 | aucune |
| 2 · Tables | 2 | 2 | 2 | aucune |
| 3 · Installation | 1 | 0 | 1 | `A_DECIDER` |

### Résultats attendus

- Les trois quantités sont affichées et comparées séparément.
- Écart ligne 3 : commandé `1`, livré `0`, facturé `1` → `QUANTITY_MISMATCH` bloquant.
- Résolutions possibles, toutes tracées : exclure, réduire la quantité facturée, joindre un justificatif.
- Aucune quantité n’est inventée quand la livraison est absente ou partielle.

### Critères de réussite

- `domain/matching.py::compare_quantites()` expose les trois quantités **et** les trois écarts
  (`ecart_livre_commande`, `ecart_livre_facture`, `ecart_facture_commande`).
- `domain/controls.py` consomme le statut sans dupliquer la logique de comparaison.
- Les cas C1–C5 et les articles sont testés dans `tests/test_controls.py` (fichier du périmètre).
- `float`, `bool`, `NaN` et l’infini sont refusés : les quantités restent des décimales exactes.

---

## R14 — Événements à tracer

Les événements métier attendus dans la chaîne d’audit :

| Action | Déclencheur |
|---|---|
| `IMPORT_DOCUMENT` | pièce acceptée (Melon) |
| `CHANGEMENT_STATUT_DOCUMENT` | transition d’état, avant/après |
| `VALIDATION_BROUILLON` | acte humain de validation, avant/après version |
| `NUMERO_ATTRIBUE` | numéro fiscal attribué à la validation |
| `PDF_GENERE` | hash du PDF figé |
| `RESOLUTION_ANOMALIE` | acteur, motif, avant/après — nom exact à confirmer avec Melon |
| `EMISSION_SIMULEE` | canal, statut |
| `AVOIR_EMIS` | facture liée, motif, montant |
| `PAIEMENT_SIMULE` | montant, facture |

### Critères de réussite

- Aucune résolution d’anomalie bloquante ne peut être enregistrée sans ces quatre informations :
  acteur, motif, avant, après.
- `make verify` détecte toute altération d’un événement passé (test de Melon).

---

## R15 — Cycle de vie de la pièce

### Données d’entrée

Statut courant de la pièce et preuves transmises par l’appelant : anomalies,
décision humaine, type d’avoir, canal d’émission simulée, drapeau de doublon.
Le vocabulaire et les arcs sont ceux du blueprint §5.6, sans alias ASCII.

### Résultats attendus

| Depuis | Vers | Condition |
|---|---|---|
| `IMPORTÉ` | `EN_ATTENTE_IA`, `EXTRAIT` ou `REJETÉ` | file d’extraction, extraction disponible ou pièce invalide/doublon |
| `EN_ATTENTE_IA` | `EXTRAIT` | retour du service ou saisie manuelle de secours |
| `EXTRAIT` | `À_COMPLÉTER` ou `CONTRÔLÉ` | champ manquant/ambigu, ou contrôles verts |
| `À_COMPLÉTER` | `EXTRAIT` | pièce corrigée, extraction rejouée |
| `CONTRÔLÉ` | `BROUILLON` | brouillon éditable, sans numéro |
| `BROUILLON` | `VALIDÉ` | décision humaine explicite uniquement |
| `VALIDÉ` | `ÉMIS` | émission simulée avec canal, montants inchangés |
| `ÉMIS` | `ÉMIS` ou `ANNULÉ_PAR_AVOIR` | avoir partiel ou avoir total |
| `REJETÉ`, `ANNULÉ_PAR_AVOIR` | — | états terminaux |

### Critères de réussite

- Toute anomalie bloquante non résolue interdit `CONTRÔLÉ`, `BROUILLON`, `VALIDÉ` et `ÉMIS`.
- `BROUILLON → VALIDÉ` exige `decision_humaine=True` et un acteur autre que `systeme`.
- Un refus ne modifie ni le statut ni le journal ; une acceptation trace
  `CHANGEMENT_STATUT_DOCUMENT` avec avant/après et chaîne d’audit vérifiable.
- `domain/documents.py` ne calcule aucun hash, ne copie aucun fichier et n’insère aucune pièce.

---

## Matrice des dix tests du jury

| Test | Attendu | Observé | Preuve |
|---|---|---|---|
| Import rejoué | 0 nouvelle pièce | À mesurer | Hash + journal |
| Total faux de 20 000 | `ARITHMETIC_MISMATCH` bloquant, écart `20 000` HT | À mesurer | Capture + événement |
| IFU absent | Validation bloquée, rien inventé | À mesurer | `MISSING_MANDATORY` |
| Quantité livrée < commandée | Ligne bloquée, décision humaine | À mesurer | `QUANTITY_MISMATCH` |
| Deux validations | 1 facture, 1 numéro | À mesurer | Base + réponses API |
| Facture émise modifiée | Refus `409` | À mesurer | Réponse API |
| Avoir total | Facture conservée, solde nul | À mesurer | Registre + PDF |
| Commande en photo puis PDF | Doublon métier détecté | À mesurer | Empreinte + événement |
| Avoir cumulé > TTC | Refus avant écriture | À mesurer | Test de propriété |
| Audit altéré | Chaîne invalide détectée | À mesurer | Écran de vérification |

---

## Arbitrages conclus

Ces points ont été tranchés et inscrits dans `docs/DECISIONS.md` :

1. **Livraison absente** : bloquer ; aucune quantité supposée.
2. **Taux fiscal absent** : exiger un code du référentiel, sans défaut 18 %.
3. **Remise globale** : champ explicite, réparti au prorata des brut par ligne avant TVA.
4. **Avoir par ligne** : cumul des avoirs ≤ ligne facturée, en plus du plafond global ≤ TTC.
5. **Périmètre de `domain/documents.py`** : règles métier seules ; ingestion, hash et stockage à Melon.
6. **`domain/audit.py`** : fichier consommé sans modification.
7. **Framework de test** : `unittest` + 1 000 cas déterministes avec graine `20261125`, compatible `make test`.
8. **Cycle de vie** : vocabulaire accentué du blueprint §5.6, états terminaux `REJETÉ` et
   `ANNULÉ_PAR_AVOIR`, validation humaine explicite avant `VALIDÉ`.

## Points encore en attente

- **Périmètre de `MISSING_MANDATORY`** : ajouter ou non les mentions de l’émetteur (raison sociale, adresse, IFU vendeur).
- **C3 et le libellé du blueprint** : le tableau des contrôles cite `≥ 0,80 (C1 à C3)` alors que le tableau C1–C5 décrit C3 comme « suggestion à confirmer ». La décision conservée bloque C3 tant qu’il n’est pas confirmé ; à réarbitrer explicitement si le jury impose la lecture littérale.
- **Contrats Melon dans `docs/API.md`** : format de `/anomalies/{id}/resolve`, `client_match`, `doublon_document`, `reference_commande`, champ de remise globale, `avoirs_precedents` / table `credit_note_lines`, appel de `appliquer_transition()` avec ses preuves, et implémentation de `adapters.pdf`.
- **Champs extraits `client.ville`, `client.phone`, `client.email`** : `build_context()` les lit quand Freud les fournit ; sinon C2 reste possible sur nom exact et C3 n’est pas inventée.
