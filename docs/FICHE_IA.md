# Fiche IA — WÉMA 1.0

Remplie par **Freud** à partir des mesures réellement exécutées le 25/11/2026.
Relecture de Larissa à faire. Les chiffres ci-dessous sont **observés**, pas les cibles du blueprint.
Le rapport final, la mise en page et le pitch restent différés (voir `Plan.md` §14).

| Champ | Contenu |
|---|---|
| Nom et version du système | `wema-extract-demo-20261125` — extraction WÉMA 1.0 |
| Fournisseur et modèle | Modèle local déterministe de l'équipe, figé le 25/11/2026. Accès : `AI_BACKEND=demo`, aucune clé, aucun réseau. Variantes `cpu` et `cloud` derrière le même contrat ; `cloud` refuse de répondre sans `WEMA_LLM_URL`. |
| Tâche | Classer le type de pièce, extraire l'en-tête et les lignes avec provenance, et signaler les champs absents. Le calcul TVA, la numérotation, le rapprochement décisionnel et la validation appartiennent à Larissa. |
| Entrées / sorties | PDF, PNG ou TXT → JSON contraint (`page`, `bbox`, `method`, `confidence`, `value_normalized`) + vue plate cliquable. `bbox` = pourcent de page `{x, y, w, h}` ; `bbox_px` reste optionnel côté OCR et n'entre pas dans le contrat API. |
| Données | 120 documents synthétiques annotés, dont 96 pièces de démonstration (40 devis, 30 photos, 16 messages, 10 BL) et 24 documents d'évaluation (4 messages, 10 BL, 10 cas dégradés). 64 clients, 120 articles, 60 factures, 9 avoirs, 18 paiements. Aucune donnée réelle. |
| Séparation des jeux | 72 dev / 24 validation / 24 test (60/20/20). Graine `20261125`, `AS_OF=2026-11-25`. Empreinte du manifeste : `2414ff0cf0acafaf6b5ff13b4efa6f09636cba8a45c3346fe79efd5f0062debd`. |
| Annotation | Vérité terrain générée par `seed.py` et stockée dans `seeds/golden/*.truth.json` : en-tête, lignes, quantités livrées, montants imprimés et montants recalculés séparés. Relecture humaine de Larissa encore à faire : la graine ne remplace pas une validation humaine. |
| Méthode d'évaluation | `python -m seed --as-of 2026-11-25` puis `python -m domain.metrics`. Exactitude des champs, précision/rappel/F1 des lignes, exactitude des **totaux imprimés extraits**, STP (document exact sans correction), rappel des signaux d'anomalie injectés, décompte des valeurs inventées. |
| Résultats observés | Champs d'en-tête : **100,0 %** (8/8 champs). Lignes : **F1 0,9966** (TP 289, FP 1, FN 1). Totaux imprimés extraits : **100,0 %**. STP : **99,2 %** (119/120). Signaux d'anomalie : **44/44, 100 %** — il s'agit de la détection de signaux par l'extraction, pas d'une décision comptable. Valeurs inventées : **0**. Matrice de confusion des types : 40/40 devis, 30/30 photos, 20/20 messages, 20/20 BL. Détail machine : `seeds/generated/metrics.json`. |
| Erreurs observées | 30 points d'attention triés : 2 écarts réels puis 28 alertes de confiance. **Ligne décalée** : `DEG-2026-402` (ombre simulée) donne 1 ligne manquante + 1 ligne surnuméraire ; la lecture reste signalée à la revue. **Confiance sous le seuil** : `CMD-2026-101` à `CMD-2026-128`, référence à 0,9489 contre un seuil de 0,95 ; la valeur est juste mais passe en revue. **Champ absent correctement traité** : IFU de `DEV-2026-041` = `null` + `ABSENT_DE_LA_PIECE` avec bbox du libellé, jamais une valeur devinée. Aucun de ces points n'a été corrigé automatiquement. |
| Seuils de revue | 0,80 par défaut ; 0,90 pour IFU/TVA/totaux ; 0,95 pour les numéros. Un champ sous son seuil ou absent est envoyé à la revue humaine. Aucune validation automatique côté IA. |
| Limites | Le mode `demo` relit des blocs OCR écrits par la graine : il ne prouve pas la robustesse face à de vrais scans. Écriture manuscrite, tampons réels, documents multi-pages et langues locales non validés. Le backend `cloud` n'est pas configuré. Les hooks optionnels ci-dessous ne sont **pas mesurés** : aucune amélioration de F1 n'est revendiquée avant branchement et évaluation d'un vrai modèle. Les tests ne couvrent pas encore l'API de bout en bout (phase 5 de Jean-Marie). |
| Briques optionnelles intégrées | `domain/jev.py` : `Choice` (arbitrage), `Noul` (absence explicite), `Score` (OCR 30 % / modèle 40 % / croisement 30 %, avec calibration 15 % si de vrais `logprobs` arrivent). `domain/semantic.py` : BM25 pur Python, lexique métier (`paquets A4` → `papier a4`), RRF, embeddings seulement si `sentence-transformers` est installé **et** `WEMA_EMBED_MODEL` défini. `adapters/constraints.py` : validation/réparation du schéma sans inventer de valeur, rapport `constraint_report`. `adapters/ocr.py` : backend `vlm` via `WEMA_VLM_ENDPOINT` (PaddleOCR-VL / MinerU / Docling derrière le même contrat). Rien n'est téléchargé ; un backend demandé mais absent lève une exception. |
| Branchement par les propriétaires | **Larissa** peut appeler `domain.semantic.similarite()` pour affiner C3/C4 seulement ; C1 (IFU), C2 (nom + ville) et C5 (aucun candidat) restent des règles exactes. **Melon** peut appeler `ocr.lire(..., backend="vlm")` ou `llm.extraire(..., ocr_backend="vlm")` et documenter JWT dans `docs/API.md` : HS256, `JWT_SECRET`, claim `role`, expiration, repli `X-Role` uniquement si `AUTH_MODE=demo`. Freud n'a modifié ni `domain/matching.py`, ni `config.py`, ni `api/*`, ni `docs/API.md`. |
| Périmètre entrée | PDF, photos, texte scanné et messages WhatsApp/texte uniquement. L'audio et Whisper sont **écartés** : aucun adaptateur audio n'a été créé et `config.allowed_mimes` n'est pas modifié par Freud. |
| Coût | `demo` : 0 € pour 1 000 documents (aucun appel réseau, aucun fournisseur). `cpu` : coût local non mesuré. `cloud` : non configuré, donc non mesuré — aucun chiffre n'est avancé. Mise en cache déterministe via les fichiers `.layout.json` générés. |
| Responsable | Freud — Données & IA. Dernière mesure : 25/11/2026. Relecture : Larissa, à programmer. |

## Reproduction

```bash
python -m seed --as-of 2026-11-25
python -m domain.metrics
python -m unittest discover -s tests -t . -v   # 44 tests, dont 21 sur les hooks optionnels
```

`python -m seed --reset` réinitialise aussi la base de Melon ; ne l'utiliser que
si Melon a confirmé que la réinitialisation est voulue. Les trois commandes
ci-dessus suffisent pour rejouer l'extraction et les mesures sans toucher à la base.
