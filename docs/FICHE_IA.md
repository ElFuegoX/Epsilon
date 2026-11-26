# Fiche IA — WÉMA 1.0

Remplie par **Freud** à partir des mesures exécutées le 26/11/2026. Relecture de Larissa à faire.
Tous les chiffres sont **observés** sur la chaîne réelle : ce ne sont pas les cibles du blueprint.
Détail technique : [`EXTRACTION.md`](EXTRACTION.md). Détail machine : `seeds/generated/metrics.json`.

> **Correction du 26/11.** Une version précédente de cette fiche annonçait 100 % et un F1 de 0,9966.
> Ces chiffres venaient d'une extraction qui relisait les blocs écrits par le générateur lui-même,
> pas les pièces : ils mesuraient le parseur sur un texte parfait. Ils sont retirés. L'extraction
> lit désormais les fichiers. Le chiffre « texte parfait » est conservé plus bas, comme ablation.

| Champ | Contenu |
|---|---|
| Nom et version du système | `wema-extract-demo-20261125` — extraction WÉMA 1.0 |
| Fournisseur et modèle | **Lecture** : `pdfplumber` 0.11 (couche texte des PDF) ; **EasyOCR 1.7.2** (CPU, torch 2.15, langue `fr`, réglages `min_size=4, low_text=0.3, mag_ratio=1.5`) pour les images. **Structuration** : règles déterministes de l'équipe (`adapters/llm.py`), sans modèle de langage. Tout tourne en local : aucune clé, aucun réseau. Le backend `cloud` (LLM) est prévu derrière le même contrat mais n'est pas branché ; sans `WEMA_LLM_URL`, il refuse de répondre. |
| Tâche | Classer la pièce, extraire l'en-tête et les lignes avec leur provenance (page + bbox de la cellule), lire les totaux **imprimés**, signaler les champs absents. Le calcul de la TVA, la numérotation, le rattachement décisionnel et la validation appartiennent à Larissa. |
| Entrées / sorties | PDF, PNG ou TXT → JSON contraint (annexe A) : `value`, `raw`, `confidence`, `page`, `bbox` (% de page), `method`, `missing`. Vue plate cliquable pour la visionneuse. |
| Données | 120 documents synthétiques annotés : 40 devis PDF, 20 bons de livraison PDF, 20 messages texte, 30 photos de commande et 10 photos dégradées (rotation, ombre, tampon). 96 d'entre eux forment la base de démonstration. Photos simulées : perspective, éclairage, grain, flou. Aucune donnée réelle. |
| Séparation des jeux | 72 dev / 24 validation / 24 test, stratifiés par famille. Graine `20261125`, `AS_OF=2026-11-25`. Empreinte du manifeste : `7713f888568e6bd7e4a57dbd364ea3e27d7405d4c4e1e328218c5c8932cc6d20`. |
| Annotation | Vérité terrain écrite par le générateur au moment du rendu (`seeds/golden/*.truth.json`) : en-tête, lignes, quantités livrées, montants imprimés et recalculés séparés. **Relecture humaine de Larissa encore à faire.** |
| Méthode d'évaluation | `python -m domain.metrics` : exactitude par champ d'en-tête, F1 des lignes (désignation + quantité + unité + PU), exactitude des totaux imprimés, STP (document lu sans aucune correction), rappel des anomalies injectées, décompte des valeurs inventées, matrice de confusion des types, détail par famille. |
| Seuils de revue | 0,80 par défaut ; 0,90 pour l'IFU, la TVA et les totaux ; 0,95 pour les numéros. Un champ sous son seuil ou absent part en revue humaine. L'IA ne valide jamais seule. Confiance = 0,30 × OCR + 0,40 × solidité de la règle + 0,30 × cohérence (lignes, totaux, référentiel clients) : voir [`CONFIANCE.md`](CONFIANCE.md). Poids et seuils **non calibrés** sur le jeu de validation. |
| Responsable | Freud — Données & IA. Dernière mesure : 26/11/2026. Relecture : Larissa, à programmer. |

## Résultats observés — chaîne réelle, 120 documents

| Mesure | Chaîne réelle | Texte parfait (ablation) | Cible blueprint |
|---|---:|---:|---:|
| Exactitude des champs d'en-tête | **96,4 %** | 100 % | ≥ 95 % |
| F1 des lignes | **0,959** (TP 278, FP 12, FN 12) | 1,000 | ≥ 0,90 |
| Exactitude des totaux imprimés | **100 %** | 100 % | ≥ 98 % |
| Traitement sans correction (STP) | **69,2 %** | 100 % | ≥ 60 % |
| Rappel des anomalies injectées | **100 %** (44/44) | 100 % | ≥ 95 % |
| **Valeurs inventées** | **0** | 0 | 0 |
| Type de pièce | 120/120 | 120/120 | — |

La colonne **texte parfait** fait lire au même parseur le texte exact dessiné par le générateur
(`--ocr rendu`). Elle mesure le parseur seul ; l'écart avec la chaîne réelle est le coût de la lecture.

### Par famille : les classes faibles sont les photos

| Famille | Documents | Champs d'en-tête | F1 lignes | STP |
|---|---:|---:|---:|---:|
| Devis PDF | 40 | 100 % | 1,000 | 100 % |
| Bons de livraison PDF | 20 | 100 % | 1,000 | 100 % |
| Messages texte | 20 | 100 % | 1,000 | 100 % |
| **Photos de commande** | 30 | **88,8 %** | **0,920** | **6,7 %** |
| **Photos dégradées** | 10 | **90,0 %** | **0,760** | **10,0 %** |

Les PDF et les messages sont parfaits parce qu'ils ne demandent aucune reconnaissance de
caractères : leur texte est lu tel quel. **Le vrai test, ce sont les 40 images**, sur lesquelles
presque chaque document demande une correction humaine.

### Par jeu

| Jeu | Documents | En-tête | F1 lignes | STP |
|---|---:|---:|---:|---:|
| dev | 72 | 96,4 % | 0,977 | 70,8 % |
| validation | 24 | 96,4 % | 0,897 | 66,7 % |
| test | 24 | 96,4 % | 0,965 | 66,7 % |

**Biais à déclarer.** Le parseur a été corrigé en lisant des erreurs sur l'ensemble du corpus, jeu
de test compris (en-tête `Qté` lu `Ote`, ponctuation doublée `IFU: :`, zéros lus `O`). Le jeu de test
n'est donc pas « jamais regardé » au sens du blueprint. Avec 6 photos par jeu, les écarts entre
jeux relèvent surtout du bruit d'échantillonnage.

### Le seuil de revue fait-il son travail ?

Chaque valeur (1 563 au total) est jugée juste, absente ou fausse, puis croisée avec la
décision « envoyée en revue » ou « acceptée ». Le détail est dans [`CONFIANCE.md`](CONFIANCE.md).

| Valeur | En revue | Acceptée |
|---|---:|---:|
| juste | 270 (17,8 %, fausses alertes) | 1 245 |
| absente | 13 | 0 |
| fausse | 35 | **0** |

**48 erreurs sur 48 envoyées en revue : 0 erreur silencieuse.** Avant les corrections du 26/11
(signal « modèle » constant, pas de comparaison au référentiel), 35 noms mal lus étaient acceptés
avec une confiance de 0,85 à 0,95. Le prix de cette garantie : sur les photos, la plupart des
montants corrigés (« O » lu à la place de « 0 ») sont soumis à confirmation.

### Rattachement client malgré les erreurs de lecture

Sur les 40 images, `match_client` (règles de Larissa) retrouve le bon client dans **37 cas**
(36 en C1 par l'IFU, 1 en C2). Les 3 autres restent en C4, donc en revue humaine. **Aucun
rattachement à un mauvais client.**

## Erreurs observées (toutes les erreurs, pas seulement 30)

| Catégorie | Volume | Exemple | Ce que fait le système |
|---|---:|---|---|
| **Confusion i → l dans les noms** | 35 documents (toutes des images) | `CMD-2026-101` : « Maison Hounsa Boot en Bois » lu « Malson Hounsa Boot en Bols » | Le nom est rapporté tel que lu : l'extraction ne le corrige pas. Comme il ressemble à un client connu sans lui être identique, sa cohérence tombe à 0,30 et il part en **revue** (35/35). Le rattachement par IFU retrouve le client (37/40). |
| **Chiffre isolé non détecté** | 11 quantités (« 4 » ou « 1 ») | `CMD-2026-114` : quantités des lignes 1 et 2 absentes | La quantité ressort **absente** (`ABSENT_DE_LA_PIECE`) et la ligne part en revue. Aucune quantité n'est devinée, aucune n'est fausse. |
| **Cellule masquée par un tampon** | 2 unités | `DEG-2026-409` : unités `pcs` et `jour` non lues | Unité absente, revue. |
| **Zéros lus comme des « O »** | fréquent (`192 OOO`, `1 276 0OO`) | `CMD-2026-101` | Corrigé **uniquement à l'intérieur d'un nombre** ; la lecture d'origine reste traçable (`lu`). |
| **Total imprimé contradictoire** | 11 devis (anomalie injectée) | `DEV-2026-041` : HT imprimé 1 020 000 contre 1 040 000 de lignes | Valeur lue telle quelle, confiance abaissée à 0,861 (< 0,90), revue obligatoire. Le recalcul et l'écart appartiennent à Larissa. |

Sur les images, **toutes les erreurs de lignes restantes sont des valeurs absentes, aucune n'est
une valeur fausse.** Au total, 70 alertes de confiance envoient un champ juste en revue par prudence.

## Limites

- **Corpus synthétique.** Les photos sont simulées : perspective, lumière, grain. L'écriture
  manuscrite, les vrais tampons, les documents multi-pages et les langues locales ne sont pas testés.
- **Police unique sur les images** (police embarquée de Pillow, sans accents). La confusion i → l
  et la non-détection des « 4 » et « 1 » isolés y sont probablement liées : rien ne garantit que ces
  taux se transposent à d'autres polices.
- **Mise en page connue des règles** (`Client :`, `IFU :`, tableau à en-tête). Une mise en page très
  différente ne sera pas structurée : ses champs ressortiront absents, pas inventés, et il faudra une
  saisie humaine.
- **Champs non lus aujourd'hui** : échéance, adresse, téléphone, mode de paiement.
- Le backend `cloud` (LLM multimodal) n'est **pas branché ni mesuré**.
- Une photo **hors corpus** exige EasyOCR installé ; sans lui, elle reste en `EN_ATTENTE_IA`.

## Coût

| Poste | Mesure |
|---|---|
| Lecture d'un PDF | ~50 ms (pdfplumber) |
| Lecture d'une photo par EasyOCR | médiane **45 s**, moyenne 59 s (CPU Intel, sans GPU, 40 images) |
| Extraction d'une photo déjà en cache | ~70 ms |
| 1 000 photos sur ce CPU | ~12,5 h de calcul local, 0 € de fournisseur ; à paralléliser ou à passer sur GPU en production |
| 1 000 PDF | < 1 min |
| Politique de cache | sortie EasyOCR brute indexée par l'empreinte des pixels (`seeds/ocr_cache/`, ~500 Ko pour 40 images), versionnée ; le mode démo n'exécute jamais d'OCR |
| `cloud` | non configuré : aucun chiffre avancé |

## Reproduction

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m seed --as-of 2026-11-25                 # corpus et vérités terrain
python -m domain.metrics --ocr cache              # chaîne réelle (rejoue le cache EasyOCR)
python -m domain.metrics --ocr rendu              # ablation « texte parfait »
python -m domain.metrics --ocr cache --split test # un seul jeu
python -m unittest discover -s tests -t . -v      # 177 tests
# pour relire les images au lieu de rejouer le cache :
pip install -r requirements-ocr.txt && python -m adapters.ocr --warm --force
```

## Ce que l'on dit au jury

> « Sur 120 documents annotés, l'extraction atteint 96 % sur les champs d'en-tête et un F1 de 0,96
> sur les lignes, avec **zéro valeur inventée**. Les PDF passent sans correction ; les photos sont
> notre point faible : sur les images, presque chaque document demande une revue. Mais quand
> l'OCR ne lit pas une quantité, elle ressort vide, jamais fausse. Et sur 1 563 valeurs jugées, les
> 48 erreurs de lecture ont toutes été envoyées en revue : aucune ne passe en silence. »

Ce que l'on ne dit pas : que l'IA lit tous les documents, qu'elle calcule la TVA, ou que les
chiffres des PDF valent pour des photos.
