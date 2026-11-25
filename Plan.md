# Plan de travail WÉMA — équipe de 4 personnes, 4 pistes de code

> Blueprint de référence : `docs/WEMA_Blueprint_Facturation_BWAI2026_v1.1.pdf` (v1.1, 25/11/2026).
> On travaille **uniquement à la racine de `Epsilon/`** : `api/`, `domain/`, `adapters/`, `worker/`, `web/`, `tests/`, `seeds/`, `docs/`. Il n'y a plus de dossier `wema/`.
> **Les quatre codent.** La présentation, le pitch, la vidéo et le rapport ne sont pas des tâches actives : ils seront faits **quand l'outil sera prêt** (voir §14).

---

## 1. Attribution nominative

Le blueprint prévoit 5 rôles. Avec 4 personnes qui codent toutes, on garde les 4 blocs techniques distincts et on étale l'ancien bloc « produit » dans le code des règles.

| Personne | Piste de code | Tâche concrète (une phrase) | Fichiers possédés | Livrable vérifiable |
|---|---|---|---|---|
| **Larissa** | Règles métier & moteurs déterministes | Écrire les moteurs qui calculent, contrôlent et numérotent, **sans jamais appeler l'IA** | `domain/tax.py`, `domain/controls.py`, `domain/numbering.py`, `domain/invoices.py`, `domain/matching.py`, `domain/documents.py`, `tests/test_tax.py`, `tests/test_controls.py`, `tests/test_numbering.py`, `tests/test_invoices.py`, `docs/DECISIONS.md`, `docs/RECETTE.md` | Moteur TVA exact, 9 contrôles, numérotation, idempotence, avoir ; tests au vert |
| **Melon** | API & infrastructure | Rendre l'outil exécutable : base SQLite, endpoints, worker, fichiers générés, audit et rôles | `config.py`, `db.py`, `schema.py`, `schema.sql`, `api/*`, `worker/*`, `cli.py`, `adapters/pdf.py`, `adapters/email_sim.py`, `adapters/whatsapp_sim.py`, `adapters/mecef_stub.py`, `tests/test_audit.py`, `tests/test_concurrency.py`, `docs/API.md` | `docker compose up` fonctionne, API documentée, chaîne d'audit vérifiable |
| **Jean-Marie** | Frontend & visionneuse | Coder les 10 écrans React et rendre chaque valeur cliquable vers sa source | `web/**`, `tests/test_e2e.py` (avec Melon) | Parcours complet rejouable dans le navigateur, provenance visible |
| **Freud** | Données & IA | Produire les 120 pièces synthétiques et l'extraction avec provenance, confiance et zéro valeur inventée | `seed.py`, `seeds/**`, `domain/extraction.py`, `domain/normalization.py`, `adapters/ocr.py`, `adapters/llm.py`, `tests/test_extraction.py`, `docs/FICHE_IA.md` | Jeu reproductible, extraction déterministe en mode `demo`, métriques mesurées |

**Propriété des fichiers** : une seule personne écrit un fichier. Les autres le lisent et proposent des retours, mais ne l'éditent pas directement ; elles passent par la personne propriétaire ou par un point de synchronisation.

---

## 2. Frontières de responsabilité

- **Larissa** code les règles, mais n'écrit ni endpoint ni écran et ne fait pas d'extraction. Elle est la seule à arbitrer une règle fiscale ; tout arbitrage est écrit dans `docs/DECISIONS.md`.
- **Melon** code le transport et la persistance, mais ne décide d'aucun montant et n'interprète aucune pièce. L'API ne laisse jamais l'IA calculer, numéroter ou valider.
- **Jean-Marie** affiche ce que l'API renvoie, il ne recalcule rien. En cas de désaccord front/back, c'est l'API qui a raison.
- **Freud** lit, propose une valeur, une page, une bbox et une confiance. Il n'écrit jamais de montant dans une facture : le calcul, le numéro et la validation sont hors de sa portée.

> **Pourquoi séparer Larissa et Freud ?** Le blueprint exige trois moteurs distincts : extraction probabiliste (Freud), calcul déterministe (Larissa), décision humaine (Larissa + Jean-Marie). Mettre lecture et calcul dans la même main détruirait la preuve.

---

## 3. Larissa — Règles métier & moteurs déterministes

### Tâche à réaliser, dans l'ordre
1. **Moteur de calcul** (`domain/tax.py`) : TVA 18 % par ligne, entiers FCFA, arrondi demi-vers-le-haut, jamais de flottant. Sur `DEV-2026-041` : HT 1 040 000 / TVA 187 200 / TTC 1 227 200, contre un imprimé de 1 020 000 / 183 600 / 1 203 600 → écart HT 20 000.
2. **9 contrôles** (`domain/controls.py`) : `MISSING_MANDATORY`, `UNKNOWN_CLIENT`, `UNKNOWN_ITEM`, `UNUSUAL_PRICE`, `DUPLICATE_DOCUMENT`, `DUPLICATE_INVOICE`, `QUANTITY_MISMATCH`, `ARITHMETIC_MISMATCH`, `INVALID_TAX`. Chaque anomalie porte une sévérité bloquante/non bloquante et un statut de résolution tracé.
3. **Numérotation** (`domain/numbering.py`) : `FAC-AAAA-00000` et `AV-AAAA-00000` continus, dans une transaction, sans numéro consommé si la validation échoue.
4. **Facture et avoir** (`domain/invoices.py`) : snapshot immuable, refus 409 sur facture émise, avoir borné par le TTC déjà facturé (cumul des avoirs ≤ TTC).
5. **Rapprochement et pièces** (`domain/matching.py`, `domain/documents.py`) : commandé / livré / facturé ; une ligne non livrée est bloquée sauf décision humaine tracée.
6. **Tests** (`tests/test_tax.py`, `test_controls.py`, `test_numbering.py`, `test_invoices.py`) : 1 000 cas de propriété sur le calcul, un test par code d'anomalie, continuité des numéros, immuabilité.
7. **Spécifications de recette** (`docs/RECETTE.md`, `docs/DECISIONS.md`) : écrire les résultats attendus **avant** le code, pas après.

### Definition of done — Larissa
- [ ] `make test` passe sur les 4 fichiers de test possédés, sans réseau.
- [ ] L'écart de 20 000 FCFA est signalé comme anomalie bloquante.
- [ ] Deux validations simultanées ne produisent qu'un seul numéro (test avec Melon).
- [ ] Un avoir cumulé supérieur au TTC est refusé avant toute écriture.
- [ ] Chaque règle arbitrée figure dans `DECISIONS.md` avec date, question, décision, motif, conséquence technique.

---

## 4. Melon — API & infrastructure

### Tâche à réaliser, dans l'ordre
1. **Base et config** (`config.py`, `db.py`, `schema.py`, `schema.sql`) : SQLite WAL, schéma complet (pièces, brouillons, lignes, anomalies, clients, articles, factures, avoirs, paiements, journal), réinitialisation en une commande avec `AS_OF=2026-11-25`.
2. **API** (`api/*`) : tous les endpoints de `docs/API.md`, schémas Pydantic, rôles via `X-Role`, `/health`, `/docs`, CORS, idempotence par clé de requête.
3. **Worker** (`worker/*`) : file persistante `EN_ATTENTE_IA → EXTRAIT`, options `--once` et `--loop`, reprise sans doublon après coupure.
4. **Adaptateurs de sortie** (`adapters/pdf.py`, `email_sim.py`, `whatsapp_sim.py`, `mecef_stub.py`) : PDF figé + hash, bandeau `SIMULATION`, canaux simulés journalisés, QR factice. Aucun appel réel à la DGI.
5. **Audit et CLI** (`domain/audit.py` est écrit par Larissa, consommé ici ; `tests/test_audit.py`, `tests/test_concurrency.py`, `cli.py`) : journal chaîné SHA-256, `make verify`, `make clean`, test de concurrence.
6. **Contrat** (`docs/API.md`) : tenir le contrat à jour et prévenir Jean-Marie avant toute modification.

### Definition of done — Melon
- [ ] `docker compose up --build` démarre API + worker + web sans clé API externe.
- [ ] Une pièce importée deux fois ne crée qu'une pièce (hash unique + clé d'idempotence).
- [ ] `GET /audit/verify` et `make verify` détectent une altération du journal.
- [ ] Toutes les routes refusent un rôle non autorisé, et toute modification d'une facture émise renvoie 409.
- [ ] Le worker coupé puis relancé reprend sans recréer de pièce.

---

## 5. Jean-Marie — Frontend & visionneuse

### Tâche à réaliser, dans l'ordre
1. **Socle** (`web/package.json`, `vite.config.js`, `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/main.jsx`, `src/App.jsx`, `src/index.css`) : React + Vite + Tailwind, routeur/onglets, bandeau `SIMULATION`.
2. **Client HTTP** (`web/src/api.js`) : base `VITE_API_URL`, en-tête `X-Role`, gestion des erreurs 409/422 renvoyées par Melon.
3. **Visionneuse** (`web/src/components/SourceViewer.jsx`) : PDF.js, page + bbox fournis par Freud, surlignage au clic sur un champ, ancienne/nouvelle valeur affichées après correction.
4. **10 écrans** (`web/src/components/*.jsx`) dans cet ordre : Boîte d'entrée → Analyse → Lignes → Contrôles → Rapprochement → Aperçu → Validation → Registre → Référentiels → Journal.
5. **Règles d'affichage** : champ absent = `— absent de la pièce —`, jamais de valeur par défaut ; bouton « Copier le message de clarification » ; total extrait / recalculé / écart côte à côte ; double clic sur « Valider » neutralisé côté front.
6. **Parcours complet** (`tests/test_e2e.py`, avec Melon) : scénario de reprise worker coupé puis relancé.

### Definition of done — Jean-Marie
- [ ] `npm install && npm run dev` affiche la boîte d'entrée sans clé API.
- [ ] Cliquer sur `120 000` ouvre la ligne du devis qui le contient (page + bbox).
- [ ] L'IFU absent s'affiche vide avec le message de clarification.
- [ ] La ligne « installation non livrée » apparaît en rouge avec décision « exclure / réduire / justificatif ».
- [ ] Le double clic sur « Valider » est neutralisé côté front **et** confirmé par l'API.
- [ ] Les 10 écrans sont utilisables sur portable et sur téléphone.

---

## 6. Freud — Données & intelligence artificielle

### Tâche à réaliser, dans l'ordre
1. **Corpus** (`seed.py`, `seeds/**`) : 120 pièces synthétiques — 40 devis PDF, 30 photos de commande, 16 messages, 10 bons de livraison, 10 cas dégradés (rotation, ombre, tampon) ; aucune donnée réelle ; graine `20261125`.
2. **Vérité terrain** (`seeds/golden/*.truth.json`) : champ par champ et ligne par ligne, split 60 % dev / 20 % validation / 20 % test. `DEV-2026-041` sert de pièce témoin (3 lignes, IFU absent, écart 20 000).
3. **Extraction** (`domain/extraction.py`, `domain/normalization.py`) : schéma contraint, en-tête + lignes, normalisation IFU/date/nom, provenance page + bbox + méthode, confiance à 3 signaux (OCR 30 %, modèle 40 %, cohérence 30 %), seuils 0,80 / 0,90 / 0,95.
4. **Adaptateurs d'entrée** (`adapters/ocr.py`, `adapters/llm.py`) : mode `AI_BACKEND=demo` déterministe, hors ligne, sans clé ; variantes `cpu` et `cloud` derrière le même contrat.
5. **Règle d'or** : champ absent = `null` + `ABSENT_DE_LA_PIECE`. Aucun IFU, aucune échéance, aucun montant « probable ».
6. **Mesures** (`tests/test_extraction.py`, `docs/FICHE_IA.md`) : exactitude par champ, F1 des lignes, exactitude des totaux, STP, rappel des anomalies injectées ; analyser 30 erreurs et publier les chiffres **observés**, y compris les classes faibles.

### Definition of done — Freud
- [ ] `python -m seed --reset --as-of 2026-11-25` produit 120 pièces annotées et le split 60/20/20 en moins de 30 s.
- [ ] Toute valeur extraite non nulle porte page + bbox + méthode ; tout champ absent porte son motif.
- [ ] Le test « zéro valeur inventée » passe sur l'IFU et l'échéance.
- [ ] Le mode `demo` rejoue le même document avec le même résultat, sans réseau.
- [ ] La matrice de confusion et la fiche IA contiennent des mesures réelles, pas les cibles du blueprint.

---

## 7. Plan d'attaque de Jean-Marie — démarrage immédiat

### Principe directeur
**Ne pas attendre Melon.** Jean-Marie code contre le contrat `docs/API.md`, pas contre l'API en cours d'écriture. Un seul interrupteur (`VITE_USE_MOCK`) choisit entre client HTTP réel et client fictif. Quand Melon aura terminé, on éteint le mock **sans toucher aux écrans**.

### État de départ vérifié
- `web/src/App.jsx` retourne `null` ; `web/src/api.js` ne contient que `API_URL` ; les 10 composants retournent `null`.
- Aucune route de `docs/API.md` n'est encore implémentée côté Melon (toutes marquées `TODO Melon`).
- `package.json` contient déjà React 18, Vite 5, Tailwind 3, PDF.js 4.

### Phases

| Phase | Objectif | Fichiers | Résultat attendu |
|---|---|---|---|
| **0 — 15 min** | Projet lancable | `npm install`, `npm run dev`, `npm run build`, `web/.env.example` (`VITE_API_URL`, `VITE_USE_MOCK`, `VITE_ROLE`) | Vite démarre et le build passe |
| **1 — Socle** | Navigation et client unique | `src/App.jsx`, `src/components/Layout.jsx`, `src/api.js`, `src/mock.js` | 10 onglets, bandeau `SIMULATION`, `request(path, {method, body})` avec `X-Role` et gestion 409/422, mock déterministe calqué sur `docs/API.md` et `seeds/golden/DEV-2026-041.truth.json` |
| **2 — Priorité jury** | Voir la pièce et sa source | `SourceViewer.jsx`, `Inbox.jsx`, `Analysis.jsx` | **Cliquer sur `120 000` ouvre la ligne du devis qui le contient** (page + bbox) |
| **3 — Lignes et contrôles** | Éditer et décider | `Lines.jsx`, `Controls.jsx`, `Reconciliation.jsx` | Table éditable, anomalies avec résolution, ligne non livrée en rouge avec « exclure / réduire / justificatif » |
| **4 — Engagement** | Figer et registrar | `Preview.jsx`, `Validation.jsx`, `Register.jsx`, `Referentials.jsx`, `Audit.jsx` | Extrait / recalculé / écart côte à côte, double confirmation désactivée après 1er clic, registre et journal |
| **5 — Bascule API** | Passer du mock au réel | `src/api.js`, `tests/test_e2e.py` avec Melon | `VITE_USE_MOCK=false`, parcours rejoué, portable + téléphone |

### État d'avancement (fin de session)

- [x] **Phase 0** — `npm install` OK (131 paquets), `npm run build` OK (48 modules). `web/.env.example` créé.
- [x] **Phase 1** — `App.jsx` (10 onglets), `Layout.jsx` (bandeau `SIMULATION`, sélecteur de rôle), `api.js` (client unique + `X-Role` + erreurs 409/422), `mock.js` (données déterministes), `utils.js`.
- [x] **Phase 2** — `SourceViewer.jsx` (page simulée + overlay bbox, rendu PDF.js prêt dès qu'une URL sera fournie par Freud), `Inbox.jsx`, `Analysis.jsx` (clic sur `120 000` → surlignage de la ligne source, IFU absent + message de clarification).
- [x] **Phase 3** — `Lines.jsx` (table éditable), `Controls.jsx` (9 anomalies simulées, résolution tracée), `Reconciliation.jsx` (ligne non livrée en rouge, décisions).
- [x] **Phase 4** — `Preview.jsx`, `Validation.jsx` (double clic neutralisé), `Register.jsx` (facture + avoir total), `Referentials.jsx`, `Audit.jsx` (vérification de chaîne simulée).
- [ ] **Phase 5** — en attente : API de Melon, PDF réel de Freud, `tests/test_e2e.py`, test portable/téléphone.
- Point d'attention : `npm audit` signale 2 dépendances vulnérables (1 modérée, 1 élevée) à revoir avant la remise.

### Règles à ne jamais enfreindre
- **Aucun calcul TVA dans le front** : on affiche ce que l'API renvoie. En cas de désaccord, l'API a raison.
- **Aucune valeur par défaut** pour un champ absent : `— absent de la pièce —`.
- **Aucun appel IA depuis le navigateur** : l'extraction passe par l'API.
- Contrat de provenance attendu de Freud : `{ page, bbox, method, confidence }`, avec motif `ABSENT_DE_LA_PIECE`.

### Coordinations au prochain point de sync
| Avec | Ce que Jean-Marie attend |
|---|---|
| **Melon** | Statuts 409/422 et format exact des erreurs dans `docs/API.md` |
| **Freud** | Format de provenance `{ page, bbox, method, confidence }` et motif d'absence |
| **Larissa** | Libellés des 9 codes d'anomalie et les chiffres du devis témoin |

---

## 8. Déroulé sur 48 heures

| Créneau | Larissa — règles | Melon — API/infra | Jean-Marie — front | Freud — données/IA |
|---|---|---|---|---|
| **H0–H3** | Recette, vocabulaire des anomalies, `DECISIONS.md` | Schéma SQL, config `AS_OF`, reset | Squelette Vite + Tailwind, layout, routeur | Plan du corpus, contrat d'extraction |
| **H3–H10** | Règles TVA et champs obligatoires | Ingestion, hash, dédup, file `EN_ATTENTE_IA` | Boîte d'entrée + Analyse | 120 pièces, vérité terrain, extraction en-tête |
| **H10–H16** | 9 contrôles, lignes et seuils de prix | Modélisation des lignes, endpoints brouillons | Écran Lignes + clic sur la source | Extraction des lignes, bbox, confiance |
| **H16–H22** | Arbitrage C1–C5, rapprochement commandé/livré | Référentiels, anomalies, clarification | Écrans Contrôles + Rapprochement | Seuils calibrés, rappel des anomalies |
| **H22–H24** | Recalcule à la main `DEV-2026-041` | Comparaison imprimé / recalculé dans l'API | Affichage HT/TVA/TTC et écart | Évaluation intermédiaire des champs |
| **H24** | **Gel du périmètre** | **Gel du périmètre** | **Gel du périmètre** | **Gel du périmètre** |
| **H24–H32** | Numérotation, snapshot, avoir | Brouillon, PDF, idempotence, worker | Aperçu + Validation (double confirmation) | Mode `demo`, extraction de secours |
| **H32–H38** | Tests avoir/immutabilité | Audit, rôles, registre, concurrence | Registre + Journal + Référentiels | Matrice de confusion, analyse d'erreurs |
| **H38–H42** | Corrections des cas pièges | Coupure worker, `make verify` | Corrections après répétition 1 | Mesures finales, coût pour 1 000 documents |
| **H42–H45** | Recette exécutée, cas pièges validés | `make test`, empreinte du commit | Polish, accessibilité, bandeau simulation | Relecture des chiffres publiés |
| **H45–H47** | Vérifie 409 et avoir total | Repli `AI_BACKEND=demo` vérifié | Répétition sans intervention technique | Aucune donnée réelle dans le corpus |
| **H47–H48** | Gel des règles | Gel de l'API | Dernière capture d'écran | Archive du corpus et de son empreinte |

### 6 points de synchronisation (15 min, les 4 présents)
1. **H3** — contrat API (Melon/Jean-Marie) et schéma d'extraction (Freud/Larissa) signés par les quatre.
2. **H10** — première pièce visible dans le navigateur ; format de provenance décidé.
3. **H16** — devis de 3 lignes reconstitué ; Larissa valide les montants à la main.
4. **H24** — gel du périmètre ; toute nouvelle idée part dans `DECISIONS.md` en « plus tard ».
5. **H38** — répétition du scénario complet ; on ne corrige plus que ce qui casse la démo.
6. **H47** — checklist de démonstration (§13) cochée à quatre.

---

## 9. Répartition des épopées du blueprint

| Épopée | Responsable | Appui |
|---|---|---|
| E1 · Ingestion | Melon | Freud fournit les pièces |
| E2 · Extraction | Freud | Larissa consomme le schéma |
| E3 · Référentiels | Larissa | Melon persiste, Freud mesure le rappel |
| E4 · Contrôles (9) | Larissa | Jean-Marie affiche, Freud mesure le rappel |
| E5 · Calcul et brouillon | Larissa | Melon expose l'API |
| E6 · Validation | Larissa | Melon transactionne et génère le PDF, Jean-Marie confirme |
| E7 · Émission et avoir | Larissa | Melon code les canaux simulés |
| E8 · Audit et rôles | Melon | Larissa définit les événements à tracer |
| E9 · Registre et 10 écrans | Jean-Marie | Melon fournit l'API |
| E10 · Exploitation | Melon | Freud fournit le corpus et les mesures |

---

## 10. Conventions de collaboration

- **Contrat d'extraction** : `domain/extraction.py` (Freud). Champ absent = `null` + `missing`, jamais une valeur « probable ». Larissa consomme, Jean-Marie affiche.
- **Contrat API** : `docs/API.md` (Melon). Jean-Marie code contre ce contrat ; Melon annonce tout changement au point de sync suivant.
- **Vocabulaire des anomalies** : les 9 codes de `domain/controls.py` (§3). Aucun nouveau code sans accord à quatre.
- **Identifiants** : UUID internes ; numéro fiscal continu uniquement à la validation. Les deux ne se confondent jamais.
- **Graine et date** : `GRAINE_DEMO=20261125`, `AS_OF=2026-11-25`. Melon et Freud ne les changent pas sans en parler aux quatre.
- **Branches** : `larissa-regles`, `melon-api`, `jean-marie-front`, `freud-ia`. `main` reste exécutable ; PR revue par au moins une autre personne.
- **Messages de commit** : `Larissa|`, `Melon|`, `Jean-Marie|`, `Freud|` + verbe à l'impératif (ex. `Larissa| ajoute le contrôle ARITHMETIC_MISMATCH`). Le commit initial d'ossature utilise `Équipe|`.
- **Règle de fusion** : qui casse `make test` corrige avant de rentrer chez soi.
- **Décisions** : toute question de règle est tranchée par Larissa et écrite dans `docs/DECISIONS.md` (date, question, décision, motif, conséquence technique). Une décision non écrite n'existe pas.

---

## 11. Risques et parades

| Risque | Parade | Responsable |
|---|---|---|
| Le modèle invente un IFU | `null` obligatoire + `MISSING_MANDATORY` + test dédié | Freud, vérifié par Larissa |
| Deux validations → deux numéros | `BEGIN IMMEDIATE` + contrainte unique + clé d'idempotence | Larissa + Melon |
| La démo dépend du réseau | `AI_BACKEND=demo`, hors ligne, sans clé | Freud + Melon |
| Le jury ne voit pas la source | bbox + surlignage au clic, testés en H38 | Jean-Marie avec Freud |
| Résultats IA et comptabilité mélangés | Deux tableaux distincts, plus tard dans le rapport | Larissa + Freud |
| Périmètre qui explose après H24 | Gel + backlog « plus tard » dans `DECISIONS.md` | Tous |
| Corpus non reproductible | Graine fixe et empreinte notée | Freud |
| Absence d'un membre | Propriétaire unique par fichier ; chacun sait lire le fichier voisin | Tous |

---

## 12. État du dépôt et prochaine étape

- Commit initial : `c95934b Initialisation et partage des tâches` (contient le plan à 4 personnes, les fichiers et les marqueurs TODO nominatifs).
- Le fichier `Plan.md` avait été remplacé par une ancienne version à 3 personnes dans le dossier de travail ; il est remis à jour ici avec le plan nominatif **et** le plan d'attaque frontend (§7).
- Commit suivant : `972d865 Mis à jour de la répartition` (plan nominatif + plan d'attaque frontend).
- La partie Jean-Marie est engagée : phases 0 à 4 du §7 codées en mode mock, `npm run build` vérifié. Il reste la phase 5 (bascule sur l'API de Melon et tests de parcours).
- Ces modifications de code et ce suivi d'avancement ne sont pas encore commités.

---

## 13. Checklist de démonstration — code seulement

- [ ] **[Melon/Freud]** Base réinitialisée avec `--as-of 2026-11-25`, trois rôles testés.
- [ ] **[Jean-Marie]** Trois onglets ouverts : boîte d'entrée, analyse, registre.
- [ ] **[Freud/Melon]** Mode de secours `AI_BACKEND=demo` activé, sans réseau.
- [ ] **[Larissa/Freud]** Pièce avec IFU manquant prête, message de clarification vérifié.
- [ ] **[Melon/Jean-Marie]** File `EN_ATTENTE_IA` prête : coupure simulée, reprise vérifiée.
- [ ] **[Larissa/Melon]** Pièce avec écart d'addition prête (20 000 FCFA).
- [ ] **[Larissa/Jean-Marie]** Bon de livraison avec ligne non livrée prêt.
- [ ] **[Larissa/Melon/Jean-Marie]** Double clic de validation préparé, avoir prêt.
- [ ] **[Tous]** Une répétition complète sans intervention technique.

---

## 14. Présentation — **différée, pas assignée maintenant**

La consigne est : **tout le monde code d'abord**. Les éléments suivants ne sont donc pas des tâches actives et n'ont pas de propriétaire pour l'instant :

- pitch oral et script seconde par seconde (`docs/PLAYBOOK_DEMO.md`) ;
- rapport 3–5 pages (`docs/RAPPORT_trame.md`) ;
- vidéo 3 minutes, captures d'écran, checklist du jury ;
- mise en forme finale de la fiche IA (`docs/FICHE_IA.md`) à partir des mesures de Freud.

Ils seront répartis **quand l'outil sera prêt et que la démo tournera**, en utilisant les chiffres réellement observés pendant le code. Aucune de ces tâches ne bloque le travail des quatre pistes ci-dessus.
