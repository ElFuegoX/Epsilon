# Contrat API WÉMA

Responsable : **Melon** (écrit) / **Jean-Marie** (consomme). Toute modification doit être annoncée au point de synchronisation suivant.

Base : `http://localhost:8000` · Documentation interactive : `/docs`.
Rôle transmis par `X-Role: dirigeant | assistante | lecture` (simulation, jamais en production).

| Endpoint | Rôle | Statut |
|---|---|---|
| `POST /documents`, `GET /documents/{id}` | Importer une pièce, consulter son état | TODO Melon |
| `POST /documents/{id}/extract` | Lancer ou relancer une extraction | TODO Melon |
| `GET /drafts`, `PATCH /drafts/{id}` | Lister et modifier un brouillon | TODO Melon |
| `POST /drafts/{id}/lines`, `PATCH /lines/{id}` | Ajouter ou corriger une ligne | TODO Melon |
| `GET /drafts/{id}/anomalies`, `POST /anomalies/{id}/resolve` | Contrôler et résoudre | TODO Melon |
| `POST /drafts/{id}/clarification-message` | Message des champs manquants | TODO Melon |
| `POST /drafts/{id}/validate` | Valider, numéroter, figer | TODO Melon |
| `POST /invoices/{id}/issue` | Émettre sur un canal simulé | TODO Melon |
| `POST /invoices/{id}/credit-notes` | Émettre un avoir lié | TODO Melon |
| `GET /invoices`, `GET /invoices/{id}` | Registre et détail | TODO Melon |
| `GET /audit`, `GET /audit/verify` | Journal et vérification de la chaîne | TODO Melon |
| `POST /admin/reset` | Réinitialiser la démonstration | TODO Melon |

## Schéma d'extraction

Voir annexe A du blueprint et `domain/extraction.py`. Règle : `null` + motif `ABSENT_DE_LA_PIECE`, jamais une valeur probable.
