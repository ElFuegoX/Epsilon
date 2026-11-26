# Confiance, cohérence et revue humaine

Responsable : **Freud**. Ce document explique comment WÉMA décide qu'une valeur extraite doit
être **regardée par un humain** : la formule, d'où vient chaque signal, les barèmes, des exemples
réels, et la mesure qui prouve que ça marche. Code : [`adapters/llm.py`](../adapters/llm.py)
(signaux), [`domain/jev.py`](../domain/jev.py) (`Score`), [`domain/extraction.py`](../domain/extraction.py)
(`seuil`, `exiger_revue`), [`domain/metrics.py`](../domain/metrics.py) (`juger_revue`).

> **Principe.** Le seuil n'est pas une décision d'acceptation : c'est une invitation à regarder.
> L'IA ne valide jamais. Le seuil décide seulement **sur quoi l'humain porte son attention**.

---

## 1. La formule

Chaque valeur extraite (un nom, un IFU, un prix, un total…) reçoit une confiance entre 0 et 1 :

```
confiance = 0,30 × OCR  +  0,40 × modèle  +  0,30 × cohérence
```

Chaque signal est borné entre 0 et 1. Les poids viennent du blueprint (§6). Un quatrième signal,
les `logprobs` d'un modèle de langage à 15 %, est prévu dans `Score`, mais il reste inactif tant
qu'aucun modèle de langage n'est branché.

La confiance est comparée à un **seuil qui dépend du champ** (`extraction.seuil`, réglable dans `config.py`) :

| Champ | Seuil | Pourquoi |
|---|---:|---|
| ordinaire (désignation, date, conditions, nom) | 0,80 | une erreur coûte peu |
| fiscal (IFU, TVA, totaux, prix, montants) | 0,90 | une erreur fausse la facture |
| numéro (référence de la pièce) | 0,95 | une erreur crée un doublon ou un mauvais lien |

**Envoyée en revue** = valeur **absente**, ou confiance **sous le seuil**. Le calcul est fait par
`extraction.exiger_revue(payload)`, qui renvoie la liste des champs à faire confirmer.

---

## 2. Signal OCR (30 %) : la netteté de la lecture

C'est la confiance que le lecteur donne lui-même aux mots qu'il a reconnus. Pour une valeur, on
prend la **moyenne des seuls mots qui la composent**. Pour « 192 000 », c'est la moyenne de
« 192 » et « 000 », pas celle de toute la ligne.

| Source | Signal OCR |
|---|---|
| Photo (EasyOCR) | variable, de 0,3 à 1,0 selon la netteté |
| PDF (pdfplumber) | 0,99 : le texte est lu dans le fichier, pas reconnu sur des pixels |
| Message texte | 1,0 |

**Limite.** Le lecteur ne sait pas quand il se trompe : EasyOCR lit « Malson » avec 0,86 de
confiance. L'OCR seul ne suffit donc pas.

---

## 3. Signal « modèle » (40 %) : la solidité de la règle

Le blueprint destine ce signal à un modèle de langage, qui donnerait une probabilité par champ.
Notre structureur est fait de **règles** : il n'a pas de probabilité à fournir. En revanche, il
sait **comment** il a trouvé la valeur : proprement, ou en rattrapant une lecture imparfaite.

**Avant (jusqu'au 26/11)** : une constante, `0,96` pour tous les champs. Le signal le plus lourd
de la formule ne distinguait rien.

**Maintenant** : un signal propre à chaque champ.

### En-tête et totaux : le libellé a-t-il été lu net ? (`_modele_libelle`)

| Situation | Signal | Exemple |
|---|---:|---|
| libellé et valeur lus tels quels | **0,95** (`MODELE_NET`) | `Client : Ets Sossa`, `Total HT : 1 020 000` |
| libellé reconnu seulement grâce à la tolérance OCR | **0,75** (`MODELE_TOLERANT`) | `Cllent : …`, `1FU : …`, `IFU: :99…`, `Tota1 HT` |
| espaces parasites retirés de la valeur | 0,75 | `DEV - 2026-041`, `2026- 11-25` |
| lettres converties en chiffres dans la valeur | **0,65** (`MODELE_CORRIGE`) | IFU `99O4…`, total `1 276 0OO` |

Les libellés « nets » sont listés dans `LIBELLES_NETS`.

### Cellules du tableau (`_modele_cellule`)

| Situation | Signal |
|---|---:|
| nombre aligné sur le bord droit de sa colonne (écart ≤ 1 % de la largeur de page) | **0,95** |
| écart plus grand : décroît linéairement jusqu'à la tolérance (3,5 %) | 0,95 → **0,70** |
| en-tête de la colonne reconnu par tolérance (`Ote` pour `Qté`, `PUHT`) | plafonné à **0,85** |
| un « O » ou un « l » converti en chiffre dans la cellule (`192 OOO`) | plafonné à **0,65** |
| désignation (texte libre, invérifiable par une règle) | 0,90 |
| unité connue (`pcs`, `m²`, `forfait`…) / inconnue | 0,95 / 0,60 |

Les messages texte sont lus par une expression stricte : 0,95 pour les montants et les quantités.

---

## 4. Signal cohérence (30 %) : la valeur se tient-elle ?

C'est le signal qui **sait** quand quelque chose cloche, parce qu'il confronte la valeur au reste
de la pièce et au référentiel. Il ne corrige rien et ne produit aucune valeur : c'est un
contrôle de lecture, pas un calcul de facture.

### a) Les lignes se tiennent-elles ? (`_coherence_ligne`)

Il s'applique aux cellules numériques de la ligne : quantité, PU, remise, TVA, total.

| Situation | Cohérence |
|---|---:|
| `qté × PU − remise = total de ligne` | **0,98** |
| l'égalité est fausse : une des valeurs est mal lue | **0,55** |
| quantité, PU ou total manquant : vérification impossible | 0,70 |

### b) Le total imprimé correspond-il aux lignes ? (`proposer`, totaux)

| Situation | Cohérence du total HT imprimé |
|---|---:|
| total imprimé = somme des totaux de lignes lus | **0,98** |
| différent (DEV-2026-041 : 1 020 000 contre 1 040 000) | **0,60** |
| une ligne illisible, comparaison impossible | 0,90 |

Le total TVA et le total TTC imprimés gardent 0,90 : le recalcul de la TVA appartient au moteur
de Larissa, pas à l'extraction.

### c) Le nom et l'IFU correspondent-ils au référentiel clients ? (`_coherence_client`)

**Nouveau au 26/11.** Le nom et l'IFU lus sont comparés au référentiel clients :

| Situation | Cohérence | Interprétation |
|---|---:|---|
| nom **identique** à un client connu (sans tenir compte des accents ni de la casse) | **0,98** | lecture plausible |
| nom **presque identique** (ressemblance ≥ 0,80) sans être identique | **0,30** | presque toujours une **lecture fautive** : « Malson » pour « Maison » |
| nom qui ne ressemble à aucun client | 0,70 | client nouveau possible ; `UNKNOWN_CLIENT` (Larissa) prendra le relais |
| IFU présent dans le référentiel | 0,98 | |
| IFU inconnu | 0,70 | client nouveau ou IFU mal lu |
| IFU d'un client, **nom d'un autre** | **0,30** pour les deux | contradiction, revue obligatoire |
| pas de référentiel fourni | 0,90 (nom) / 0,95 (IFU) | neutre : rien à comparer |

La ressemblance est `matching.similarite` (Larissa), utilisée en lecture seule. Ce signal
**ne rattache pas** le client : le rattachement reste à `matching.match_client`, avec ses
niveaux C1 à C5.

D'où vient le référentiel ? `extraire_piece(chemin, clients=…)`. Depuis la base :
`extraction.clients_depuis_base(conn)`. Le seed et les mesures le passent automatiquement.

### d) Champs dont la cohérence reste fixée

| Champ | Cohérence |
|---|---:|
| référence, date d'émission | 0,95 |
| conditions de paiement, désignation, unité | 0,90 |

Ces champs n'ont rien à quoi se comparer aujourd'hui. Il faudrait par exemple vérifier qu'une
date n'est pas postérieure à `AS_OF`, ou qu'une référence n'est pas déjà connue. C'est une piste
d'amélioration.

---

## 5. Exemples réels (chaîne réelle, référentiel fourni)

| Valeur | OCR | Modèle | Cohérence | **Confiance** | Seuil | Décision |
|---|---:|---:|---:|---:|---:|---|
| PU « 120 000 », DEV-041 (PDF) | 0,99 | 0,95 | 0,98 | **0,971** | 0,90 | acceptée ✅ |
| Nom « Ets Sossa Materiaux », DEV-041 (PDF) | 0,99 | 0,95 | 0,98 | **0,971** | 0,80 | acceptée ✅ |
| Total HT « 1 020 000 », DEV-041 | 0,99 | 0,95 | **0,60** | **0,857** | 0,90 | **revue** ✅ le total contredit les lignes |
| Nom « Malson Hounsa Boot en Bols », CMD-101 | 0,86 | **0,75** (`Cllent`) | **0,30** (presque « Maison Hounsa… ») | **0,647** | 0,80 | **revue** ✅ (acceptée à 0,911 avant) |
| PU « 192 OOO » → 192 000, CMD-101 | 0,75 | **0,65** (O → 0) | 0,98 | **0,780** | 0,90 | **revue** (valeur juste, mais corrigée : à confirmer) |
| IFU « 9934368630 », CMD-101 | ~0,70 | 0,95 | 0,98 | **0,886** | 0,90 | revue (OCR flou sur cette zone) |

Calcul du nom de CMD-101 : 0,30 × 0,858 + 0,40 × 0,75 + 0,30 × 0,30 = 0,257 + 0,300 + 0,090 = **0,647**.

---

## 6. Ce que la formule garantit

Quelques propriétés se lisent directement dans les nombres :

- **Un montant incohérent part toujours en revue.** Avec une cohérence de 0,55, même un OCR et
  une règle parfaits plafonnent à 0,30 + 0,40 + 0,165 = **0,865**, sous le seuil fiscal de 0,90.
- **Un nom presque identique à un client connu part toujours en revue.** Avec une cohérence de
  0,30, le plafond est 0,30 + 0,40 + 0,09 = **0,79**, sous le seuil de 0,80 (testé dans
  `TestConfiance.test_un_nom_suspect_part_en_revue_meme_avec_un_ocr_sur`).
- **Une valeur absente part toujours en revue**, quelle que soit sa confiance.
- **Une lecture corrigée (O → 0) sur un champ fiscal** plafonne à 0,30 + 0,26 + 0,294 = 0,854 :
  elle est toujours confirmée par un humain.

---

## 7. La mesure : le seuil fait-il son travail ?

Une confiance ne vaut que si elle **dit vrai**. On le vérifie sur les 120 documents annotés, avec
`metrics.juger_revue`. Chaque valeur est classée **juste, absente ou fausse**, puis croisée avec
la décision **envoyée en revue ou acceptée** :

```bash
python -m domain.metrics --ocr cache     # section « Le seuil fait-il son travail ? »
```

| Valeur | En revue | Acceptée |
|---|---:|---:|
| juste | 270 (fausses alertes) | 1 245 ✅ |
| absente | **13** ✅ | 0 |
| fausse | **35** ✅ | **0** |

**48 erreurs sur 48 attrapées, 0 erreur silencieuse**, sur 1 563 valeurs jugées.

### Avant et après les corrections du 26/11

| Version | Erreurs silencieuses | Fausses alertes |
|---|---:|---:|
| Modèle constant, pas de référentiel (avant) | **35** (tous des noms mal lus) | 220 (14,5 % des valeurs justes) |
| Signal « modèle » seul (`avec_referentiel=False`) | 22 | 273 (18,0 %) |
| **Modèle + cohérence avec le référentiel** | **0** | 270 (17,8 %) |

Le signal « modèle » attrape 13 des 35 noms (ceux dont le libellé était lu « Cllent »). Le
référentiel attrape les 22 autres. Le test `test_chaine_reelle_reproductible_et_sans_invention`
vérifie que les erreurs silencieuses restent à **0**.

### D'où viennent les fausses alertes

| Famille | Champ | Fausses alertes | Cause |
|---|---|---:|---|
| photo / dégradé | PU et total de ligne | 193 | surtout des zéros lus « O » et corrigés, ou un OCR peu sûr de la zone |
| photo / dégradé | total HT imprimé | 39 | mêmes causes |
| photo | nom du client | 1 | OCR peu sûr |
| photo / dégradé | référence | 22 | OCR moins sûr que le seuil de 0,95 |
| devis PDF | total HT imprimé | 7 | **anomalie injectée** : le total contredit les lignes |
| photo / dégradé | IFU | 8 | zone floue |

Les 7 alertes sur les devis ne sont pas de vraies fausses alertes : la valeur est **lue
correctement**, mais elle est **fausse sur la pièce**. On veut que l'humain la voie. Sur les
PDF, presque rien d'autre ne part en revue.

**Le compromis est assumé** : sur une photo, l'humain confirme les montants. C'est le prix de zéro
erreur silencieuse, et c'est cohérent avec le TDR (« confirmer les valeurs avant validation »).

---

## 8. Limites honnêtes

- **Le signal « modèle » est un barème**, pas une probabilité apprise. Ses valeurs (0,95, 0,75,
  0,65…) sont choisies, pas calibrées.
- **Les poids (30/40/30) et les seuils (0,80/0,90/0,95) ne sont pas calibrés** sur le jeu de
  validation, comme le prévoyait le blueprint. Ils ont été réglés en regardant les erreurs de
  tout le corpus, jeu de test compris.
- **La cohérence avec le référentiel suppose un référentiel à jour.** Un client nouveau dont le
  nom ressemble à 80 % à un client existant sera envoyé en revue : c'est une fausse alerte, mais
  le bon réflexe.
- **`exiger_revue` n'est pas encore branché** sur la validation : la liste des champs à revoir est
  calculée, mais rien n'oblige encore l'humain à les confirmer. Cela se fera dans le maillon
  extraction → brouillon.
- **Corpus synthétique, police unique sur les photos** : ces taux ne se transposent pas tels
  quels à de vraies photos.

---

## 9. Et si on branchait un vrai modèle (Gemini, Claude…) ?

Le contrat est prêt : `AI_BACKEND=cloud` et `WEMA_LLM_URL` dans `adapters/llm.py`, et le signal
`logprobs` dans `Score`, qui pèserait alors 15 %. Un modèle multimodal apporterait :
- une **vraie probabilité** par champ, si l'API renvoie des `logprobs` (à vérifier selon le modèle) ;
- une meilleure lecture des **libellés et des mises en page variées** ;
- une correction plausible des noms (« Malson » → « Maison »).

Ce troisième point est aussi un **risque** : c'est exactement le type de « valeur plausible
inventée » que le TDR interdit. Un modèle de langage ne remplacerait donc **pas** la cohérence
avec le référentiel : elle resterait le garde-fou.

À peser avant de le faire :
- **Le TDR** : « un modèle payant ne procure aucun avantage automatique ». Le jury note la qualité
  **mesurée**, pas le nom du modèle.
- **La démo** doit tourner hors ligne : le modèle resterait optionnel, avec `demo` par défaut.
- **Les données** : envoyer des pièces clients à un service externe se déclare, dans le rapport
  et dans les licences.
- **La reproductibilité** : version figée du modèle, température 0, réponses mises en cache comme
  pour l'OCR.
- **La mesure** : le brancher ne vaut que si l'on remesure tout (`--ocr cache`, `juger_revue`) et
  que l'on publie les deux colonnes, règles et modèle.

---

## 10. Pour l'équipe

| Qui | Ce qui le concerne |
|---|---|
| **Melon** | Passer le référentiel à l'extraction : `extraire_piece(chemin, clients=clients_depuis_base(conn))`. Sans lui, la cohérence du nom reste neutre et des noms mal lus repassent sous le radar. |
| **Jean-Marie** | Afficher la confiance de chaque champ et surligner ceux que renvoie `exiger_revue`. Un champ en revue doit être **confirmé** avant validation. |
| **Larissa** | `_coherence_client` utilise `matching.similarite` en lecture seule. Le rattachement (C1 à C5) reste le sien et vient **après** : la cohérence dit « regarde », le rattachement dit « c'est ce client ». |
