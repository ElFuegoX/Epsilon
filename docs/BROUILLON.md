# Maillon extraction → brouillon

Responsable : **Freud** (à valider avec Larissa et Melon). Code : [`domain/brouillon.py`](../domain/brouillon.py).
Tests : [`tests/test_brouillon.py`](../tests/test_brouillon.py).

Le TDR demande de « transformer une source commerciale en un projet de facture vérifiable » et de
« créer un document au statut **BROUILLON** ». L'extraction produit un JSON ; les contrôles et la
validation de Larissa lisent les tables `invoice_drafts`, `draft_lines` et `deliveries`. Ce module
fait le pont, **sans rien inventer**, et branche la revue humaine sur la validation.

```
pièce → extraire_piece() → persister()  →  creer_brouillon()  →  refresh_anomalies()  (Larissa)
                                                    │
                                                    └→ confirmations (review_items)
                                                       exiger_confirmations() avant validate_draft()
```

## Ce que fait `creer_brouillon(conn, document_id, payload)`

| Élément | Règle |
|---|---|
| Brouillon | statut `BROUILLON`, lié à la pièce, **un seul par pièce** (idempotent : un second appel renvoie le même) |
| Client | `matching.match_client` sur le nom et l'IFU lus ; rattaché seulement en **C1/C2**, sinon laissé vide (`UNKNOWN_CLIENT` et `MISSING_MANDATORY` le signaleront) |
| Date de pièce | la date lue |
| Échéance | **jamais calculée** : absente de la pièce, elle reste vide et `MISSING_MANDATORY` la réclame |
| Conditions | code du référentiel dont le libellé correspond au texte lu (« 30 jours » → `30J`) |
| Lignes | une ligne de brouillon par ligne lue ; article rattaché par `matching.match_item` |
| Taux de TVA | code du référentiel pour le taux lu ; un taux inconnu devient `TAUX_INCONNU_x` et `INVALID_TAX` le bloque ; **jamais 18 % par défaut** |
| Livraisons | quantité « Livré » lue → table `deliveries` ; absente → rien (`QUANTITY_MISMATCH` traite la livraison inconnue) |

Une trace `BROUILLON_CREE` est écrite au journal d'audit.

## Valeurs non lues : déduire, ou attendre l'humain

Quand l'OCR rate une valeur d'une ligne (par exemple un « 4 » isolé), la règle est :

1. **Déduire** la valeur, si et seulement si les autres valeurs **imprimées** de la même ligne la
   déterminent exactement :
   - quantité = total ÷ PU (résultat fini, au millième) ;
   - remise = qté × PU − total (entière et ≥ 0) ;
   - total = qté × PU − remise.
2. Une valeur déduite crée une confirmation **`VALEUR_DEDUITE`, priorité haute**. Elle n'est
   jamais acceptée seule.
3. Si la déduction est impossible, **la ligne n'est pas créée**. Une confirmation
   **`LIGNE_INCOMPLETE`** garde ce qui a été lu ; un humain la complète avec `completer_ligne()`.

Sur la base de démo : 96 brouillons, 0 ligne incomplète, 6 quantités déduites. Sur CMD-2026-114,
les deux quantités ratées par l'OCR sont déduites (4 et 1) et **conformes** à la vérité terrain.

## Confirmations : la revue humaine branchée sur la validation

Toute valeur **sous son seuil de confiance** (`extraction.exiger_revue`, voir
[`CONFIANCE.md`](CONFIANCE.md)) devient une confirmation **`CHAMP_A_CONFIRMER`**, stockée dans
`review_items` avec la valeur, la lecture brute, la confiance, le seuil, la page et la bbox. La
visionneuse peut donc la montrer sur la pièce.

Ne deviennent **pas** des confirmations, pour éviter les doublons :
- les absences d'en-tête déjà réclamées par `MISSING_MANDATORY` (IFU, échéance, conditions…) ;
- un total non imprimé sur la pièce : rien à confirmer.

| Fonction | Rôle |
|---|---|
| `a_confirmer(conn, draft_id)` | liste des confirmations en attente (pour l'écran) |
| `confirmer(conn, draft_id, chemin, acteur, motif=, corrige=)` | l'humain confirme, ou corrige ; une correction de ligne met à jour `draft_lines` ; trace d'audit `VALEUR_CONFIRMEE` / `VALEUR_CORRIGEE` |
| `completer_ligne(conn, draft_id, numero, valeurs, acteur)` | crée une ligne incomplète avec les valeurs fournies ; trace `LIGNE_COMPLETEE` |
| `exiger_confirmations(conn, draft_id)` | lève `ConfirmationsEnAttente` s'il reste quelque chose : **à appeler avant `validate_draft`** |

Une confirmation exige un **acteur**. Un brouillon validé ou émis refuse toute modification : on
passe alors par un avoir.

## Intégration

**Melon** (worker et API) :

```python
payload = extraire_piece(chemin, clients=clients_depuis_base(conn))
with transaction(conn):
    persister(conn, document_id, payload)
    creer_brouillon(conn, document_id, payload)          # même transaction
# endpoint POST /drafts/{id}/validate :
brouillon.exiger_confirmations(conn, draft_id)           # 409 si ConfirmationsEnAttente
invoices.validate_draft(conn, draft_id, acteur=role, idempotency_key=...)
```

Nouveaux endpoints à prévoir : `GET /drafts/{id}/confirmations`,
`POST /drafts/{id}/confirmations` (`chemin`, `motif`, `corrige?`), `POST /drafts/{id}/lines/{n}/complete`.

**Larissa** : rien à changer. `refresh_anomalies` voit sur DEV-2026-041 exactement les anomalies
attendues : `MISSING_MANDATORY` (IFU, échéance), `QUANTITY_MISMATCH` (ligne 3), `ARITHMETIC_MISMATCH`
(HT, TVA, TTC). Une option serait d'appeler `exiger_confirmations` **dans** `validate_draft`, pour que
la garantie ne dépende pas de l'API.

**Jean-Marie** : écran Contrôles ou Lignes, afficher `a_confirmer` avec la source surlignée ; un
bouton « Confirmer » et un champ « Corriger ».

## Points ouverts

- **Commande sans bon de livraison.** La règle de Larissa bloque une livraison inconnue
  (`QUANTITY_MISMATCH`). Une photo de commande seule n'est donc jamais validable sans BL ou sans
  décision tracée. Le TDR dit de comparer commandé et livré « lorsque ces deux informations sont
  fournies » : à arbitrer par Larissa.
- **Rapprochement entre pièces** (commande ↔ BL de la même affaire) : pas encore fait. Aujourd'hui,
  seule une pièce qui porte elle-même la colonne « Livré » (devis, BL) alimente `deliveries`.
