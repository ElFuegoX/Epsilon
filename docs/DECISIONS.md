# Journal des décisions métier

Responsable : **Larissa**. Toute règle arbitrée est écrite ici. Une décision non écrite n'existe pas.

| Date | Question | Décision | Motif | Conséquence technique |
|---|---|---|---|---|
| 2026-11-25 | Une ligne non livrée peut-elle être facturée ? | Non, sauf décision humaine tracée | TDR : anomalie non résolue bloquante | `QUANTITY_MISMATCH`, exclusion journalisée |
| 2026-11-25 | Un IFU absent peut-il être déduit du nom ? | Non, jamais | TDR : donnée manquante non inventée | `null` + `ABSENT_DE_LA_PIECE`, `MISSING_MANDATORY` |
| 2026-11-25 | Le modèle calcule-t-il la TVA ? | Non, jamais | Calcul déterministe, entiers FCFA | Moteur `domain/tax.py`, aucun appel LLM |
