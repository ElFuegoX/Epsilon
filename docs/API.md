# Contrat API WÉMA

Responsable : **Melon** (écrit) / **Jean-Marie** (consomme). Toute modification doit être annoncée au point de synchronisation suivant.

Base locale : `http://localhost:8000` (ou port `7860` sur Hugging Face Spaces) · Documentation interactive : `/docs`.
Rôle transmis par `X-Role: dirigeant | assistante | lecture` (simulation, défaut `lecture`, 403 si non autorisé).
Idempotence : en-tête optionnel `Idempotency-Key` sur `POST /documents`, `POST /drafts/{id}/validate` et `POST /invoices/{id}/credit-notes`.

| Endpoint | Rôle requis | Rôle fonctionnel | Statut |
|---|---|---|---|
| `GET /health` | Public | État de l'API, version, `ai_backend`, `as_of` | Implémenté |
| `GET /documents`, `POST /documents`, `GET /documents/{id}` | Lecture / Assistante+ | Lister, importer (fichier multipart ou JSON `{nom, texte}`), consulter | Implémenté |
| `GET /documents/{id}/file` | Lecture | Copie immuable de la pièce source pour la visionneuse (`404` si message texte sans fichier) | Implémenté |
| `POST /documents/{id}/extract` | Assistante+ | Mettre en file et exécuter l'extraction (idempotent) | Implémenté |
| `GET /drafts`, `GET /drafts/{id}`, `PATCH /drafts/{id}` | Lecture / Assistante+ | Lister, consulter et modifier un brouillon (409 si déjà validé) | Implémenté |
| `POST /drafts/{id}/lines`, `PATCH /lines/{id}` | Assistante+ | Ajouter ou corriger une ligne (recalcul via `domain/tax.py`) | Implémenté |
| `GET /drafts/{id}/anomalies`, `POST /anomalies/{id}/resolve` | Lecture / Assistante+ | Contrôler (9 règles) et résoudre une anomalie avec trace | Implémenté |
| `POST /drafts/{id}/clarification-message` | Assistante+ | Générer le message WhatsApp des champs manquants | Implémenté |
| `POST /drafts/{id}/validate` | **Dirigeant** | Valider, numéroter, figer le snapshot et générer le PDF (422 si anomalie bloquante, 409 si état invalide) | Implémenté |
| `GET /invoices`, `GET /invoices/{id}`, `GET /invoices/{id}/pdf` | Lecture | Registre, détail et téléchargement du PDF figé | Implémenté |
| `PATCH /invoices/{id}`, `DELETE /invoices/{id}` | Assistante+ | Toujours refusé en `409 Conflict` (`INVOICE_IMMUTABLE`) | Implémenté |
| `POST /invoices/{id}/issue` | Assistante+ | Émettre sur un canal simulé (`email_sim`, `whatsapp_sim`, `telechargement`) | Implémenté |
| `POST /invoices/{id}/credit-notes` | **Dirigeant** | Émettre un avoir lié borné au TTC | Implémenté |
| `GET /referentials/clients`, `POST /referentials/clients` | Lecture / **Dirigeant** | Consulter et créer un client | Implémenté |
| `GET /referentials/items`, `POST /referentials/items` | Lecture / Assistante+ | Consulter et créer un article | Implémenté |
| `GET /audit`, `GET /audit/verify`, `GET /audit/export.csv` | Lecture | Journal chaîné SHA-256, vérification d'intégrité et export CSV | Implémenté |
| `POST /admin/reset` | **Dirigeant** | Réinitialiser la base et les fichiers générés (`AS_OF=2026-11-25`) | Implémenté |

`GET /documents` et `GET /documents/{id}` exposent `url` (chemin relatif vers `/file`) uniquement lorsqu'une copie du fichier existe ; `null` sinon. Les téléchargements (`/pdf`, `/export.csv`, `/file`) exigent l'en-tête `X-Role` : le front les récupère via `fetch` puis ouvre un Blob local.

`POST /anomalies/{id}/resolve` accepte `{"justification": "motif"}` (ou `{"resolution": "motif"}`). L'acteur est lu dans `X-Role` ; le motif est le texte fourni ; `avant` et `apres` sont journalisés dans la ligne d'anomalie. Aucun acteur n'est accepté dans le corps de la requête.

### Limites de contrat connues (2026-11-26)

- `remise_globale` n'est ni persistée ni exposée : `draft_lines` ne porte que `remise` et `remise_pct` par ligne. Le calcul déterministe reste disponible côté domaine.
- Aucune colonne `reference_commande` : `DUPLICATE_INVOICE` repose sur client + TTC + date à ±3 jours.
- Aucune table `credit_note_lines` : `avoirs_precedents` n'est pas transmis par l'API ; seule la borne TTC globale est appliquée à l'émission d'un avoir.

Ces limites sont arbitrées dans [`DECISIONS.md`](DECISIONS.md) (§ Confirmations techniques — Melon).

## Codes d'erreur standard

- `403 Forbidden` : rôle absent/inconnu ou insuffisant pour l'action.
- `404 Not Found` : ressource introuvable.
- `409 Conflict` : doublon exact de document, brouillon déjà validé, ou tentative de modification/suppression d'une facture émise (`INVOICE_IMMUTABLE`).
- `422 Unprocessable Entity` : anomalies bloquantes ouvertes à la validation, avoir dépassant le TTC, fichier ou canal invalide.

## Schéma d'extraction

Voir annexe A du blueprint et `domain/extraction.py`. Règle : `null` + motif `ABSENT_DE_LA_PIECE`, jamais une valeur probable.
