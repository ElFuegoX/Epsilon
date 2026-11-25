# Recette — les 10 tests du jury

Responsable : **Larissa** (critères), **Melon** (exécution). Remplacer « Observé » par les chiffres réels le jour J.

| Test | Attendu | Observé | Preuve |
|---|---|---|---|
| Import rejoué | 0 nouvelle pièce | À mesurer | Hash + journal |
| Total faux de 20 000 | Anomalie bloquante | À mesurer | Capture + événement |
| IFU absent | Validation bloquée, rien inventé | À mesurer | `MISSING_MANDATORY` |
| Quantité livrée < commandée | Ligne bloquée, décision humaine | À mesurer | `QUANTITY_MISMATCH` |
| Deux validations | 1 facture, 1 numéro | À mesurer | Base + réponses API |
| Facture émise modifiée | Refus 409 | À mesurer | Réponse API |
| Avoir total | Facture conservée, solde nul | À mesurer | Registre + PDF |
| Commande en photo puis PDF | Doublon métier détecté | À mesurer | Empreinte + événement |
| Avoir cumulé > TTC | Refus avant écriture | À mesurer | Test de propriété |
| Audit altéré | Chaîne invalide détectée | À mesurer | Écran de vérification |
