# Parcours complet : de la pièce à l'avoir

Code : [`domain/parcours.py`](../domain/parcours.py) (enchaînement), [`adapters/pdf.py`](../adapters/pdf.py),
[`adapters/mecef_stub.py`](../adapters/mecef_stub.py), [`adapters/canaux.py`](../adapters/canaux.py),
[`cli.py`](../cli.py). Tests : [`tests/test_parcours.py`](../tests/test_parcours.py).

`domain/parcours.py` est **la seule porte d'entrée** à utiliser depuis l'API, le worker, la CLI ou
les tests. Il enchaîne les règles existantes (extraction, brouillon, contrôles, numérotation,
avoirs), vérifie le rôle, fait avancer le statut de la pièce et écrit au journal d'audit. Il
n'ajoute aucune règle de calcul.

```bash
python -m cli demo      # rejoue tout le scénario du jury sur une base neuve, pas à pas
python -m cli verify    # chaîne d'audit, PDF des factures, continuité des numéros (make verify)
```

## Les étapes

| # | Fonction | Rôle requis | Ce qui se passe | Statut de la pièce |
|---|---|---|---|---|
| 1 | `importer(conn, fichier)` | assistante, dirigeant | SHA-256 ; **même empreinte = même pièce, aucun nouvel import** ; copie immuable dans `data/documents/` | `IMPORTÉ` |
| 2 | `extraire(conn, document_id)` | assistante, dirigeant | extraction (avec référentiel clients) + `persister` + `creer_brouillon` dans **une transaction** ; OCR indisponible → aucune écriture partielle | `EXTRAIT` ou `EN_ATTENTE_IA` |
| – | `reprendre(conn)` | assistante, dirigeant | **reprise après interruption** : relance chaque pièce `IMPORTÉ` / `EN_ATTENTE_IA`, sans recréer d'extraction ni de brouillon | `EN_ATTENTE_IA` → `EXTRAIT` |
| 3 | `controler(conn, draft_id)` | tous | les 9 contrôles de Larissa (`refresh_anomalies`) | — |
| – | `message_clarification(conn, draft_id)` | tous | texte à envoyer au client : **seulement les champs manquants**, aucune valeur proposée | — |
| – | `apercu_pdf(conn, draft_id)` | tous | brouillon exportable, bandeau « BROUILLON — NON FISCAL », sans numéro | — |
| 4 | `brouillon.confirmer` / `completer_ligne` | assistante, dirigeant | valeurs sous le seuil, déduites ou manquantes (voir [`BROUILLON.md`](BROUILLON.md)) | — |
| 4 | `modifier_brouillon(…)` | assistante (client : dirigeant) | échéance, conditions, rattachement client ; version +1, trace avant/après | — |
| 4 | `renseigner_ifu(conn, client_id, ifu)` | **dirigeant** | IFU obtenu en réponse au message de clarification | — |
| 4 | `exclure_ligne(conn, draft_id, n)` | assistante, dirigeant | décision « exclure la ligne non livrée » ; la ligne quitte le brouillon, la trace reste | — |
| 4 | `resoudre(conn, draft_id, "CODE[:champ]")` | assistante ; **prix inhabituel : dirigeant** | résolution tracée (acteur, motif, avant, après) | — |
| 5 | `valider(conn, draft_id)` | **dirigeant** | `exiger_confirmations` puis `validate_draft` : contrôles, **numéro réservé dans la transaction**, snapshot, PDF figé ; **idempotent** | `CONTRÔLÉ` → `BROUILLON` → `VALIDÉ` |
| 6 | `emettre(conn, invoice_id, canal)` | assistante, dirigeant | `email_sim`, `whatsapp_sim` ou `telechargement` ; message écrit dans `data/outbox/`, **rien n'est envoyé** | `ÉMIS` |
| 7 | `avoir(conn, invoice_id, motif, total=True)` | **dirigeant** | avoir lié et numéroté (`AV-…`), plafonné au TTC ; facture conservée | `ANNULÉ_PAR_AVOIR` (total) |

Un rôle insuffisant lève `AccesRefuse` (HTTP 403 côté API). Une facture validée qu'on tente de
modifier lève `EtatInvalide` (409) ; en base, un trigger refuse aussi la modification
(`INVOICE_IMMUTABLE`).

## Le scénario du jury (`python -m cli demo`, sur DEV-2026-041)

1. Import, puis réimport du même fichier → **une seule pièce** (geste 1).
2. Extraction : 3 lignes, IFU absent, total imprimé 1 020 000.
3. Contrôles : `MISSING_MANDATORY` (IFU, échéance), `QUANTITY_MISMATCH` (installation non livrée),
   `ARITHMETIC_MISMATCH` (écart de 20 000 sur le HT). Message de clarification prêt à copier.
4. Validation tentée trop tôt → **refusée** (une valeur à confirmer, puis des anomalies bloquantes).
5. Décisions humaines tracées :
   - total imprimé confirmé ;
   - IFU obtenu du client ;
   - échéance saisie ;
   - installation exclue ;
   - écart expliqué.
6. Double validation → **une seule facture `FAC-…`** (geste 2) : HT 980 000, TVA 176 400,
   TTC 1 156 400 ; PDF reproductible à l'identique.
7. Tentative de modification → **refusée** (geste 3).
8. Émission WhatsApp simulée : le message est écrit dans `data/outbox/whatsapp_sim/`.
9. Avoir total → facture **conservée** au registre, solde 0, `AV-…` (geste 4).
10. `verify` : chaîne d'audit OK, PDF conforme au snapshot, numérotation continue.

## Adaptateurs

| Fichier | Rôle |
|---|---|
| `adapters/pdf.py` | `build_invoice_pdf` (facture figée, mentions de l'annexe B, bandeau SIMULATION), `build_draft_pdf` (aperçu de brouillon), `hash_file`. ReportLab en mode `invariant` : **régénérer depuis le snapshot redonne le même hash** (`invoices.verifier_pdf`). |
| `adapters/mecef_stub.py` | code MECeF et contenu du QR **factices**, dérivés du snapshot ; ils annoncent eux-mêmes qu'ils n'ont aucune valeur fiscale |
| `adapters/canaux.py` (+ `email_sim.py`, `whatsapp_sim.py`) | message rédigé et écrit dans `data/outbox/<canal>/<numéro>.json` ; **aucun envoi réel** |

L'émetteur imprimé sur la facture est **fictif** (`EMETTEUR` dans `adapters/pdf.py`).

## Ce qui reste à brancher

- **API HTTP** (`api/`) : chaque endpoint de `docs/API.md` appelle une fonction de
  `domain/parcours.py` et traduit les exceptions : `AccesRefuse` → 403, `ConfirmationsEnAttente`,
  `AnomaliesBloquantes`, `EtatInvalide` → 409/422. Le rôle vient de l'en-tête `X-Role`.
- **Worker** (`worker/`) : boucle sur `parcours.reprendre(conn)`.
- **Front** : remplacer le mock par ces endpoints ; afficher `brouillon.a_confirmer`.
- La pièce n'avance pas encore par `À_COMPLÉTER` quand un champ obligatoire manque : elle reste
  `EXTRAIT` jusqu'à la validation. Le blocage est assuré par les anomalies.
