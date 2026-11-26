# Extraction WÉMA : corpus, OCR, structuration, mesures

Responsable : **Freud** (piste Données & IA). Ce document décrit comment une pièce
devient un JSON d'extraction, et comment s'en servir depuis l'API, le front et les
contrôles. Les chiffres mesurés sont publiés dans [`FICHE_IA.md`](FICHE_IA.md).

> **Règle d'or.** L'extraction lit et propose. Elle ne calcule aucune TVA, n'attribue
> aucun numéro et ne valide rien. Un champ absent de la pièce vaut `null` avec le
> motif `ABSENT_DE_LA_PIECE` : jamais d'IFU, d'échéance ou de montant « probable ».

---

## 1. Vue d'ensemble

```
pièce (PDF / photo / message)
   │
   ▼
adapters/ocr.py ── lire()          mots + boîtes + confiance, regroupés en lignes
   │   PDF    → pdfplumber (couche texte, exact)
   │   photo  → EasyOCR  (ou son cache, voir §4)
   │   texte  → une ligne = une ligne
   ▼
adapters/llm.py ── proposer()      règles : libellés, tableau par colonnes, totaux imprimés
   │                                → valeurs brutes + bloc d'origine de chaque valeur
   ▼
domain/extraction.py ── assembler() / valider()
   │                                normalisation, confiance à 3 signaux, schéma, provenance,
   │                                contrôle « zéro valeur inventée »
   ▼
JSON d'extraction  ──► persister()  tables extractions / extracted_fields / document_totals
```

Point d'entrée unique : `domain.extraction.extraire_piece(chemin)`.

```python
from domain.extraction import extraire_piece, persister, aplatir

payload = extraire_piece("seeds/generated/demo/devis/DEV-2026-041.pdf")
payload["client"]["ifu"]        # {"value": None, "missing": "ABSENT_DE_LA_PIECE", ...}
payload["lines"][1]["unit_price_ht"]
# {"value": 120000, "raw": "120 000", "confidence": 0.95, "page": 1,
#  "bbox": [55.35, 21.13, 5.46, 1.07], "method": "pdf_texte+regles"}
```

Le résultat est **déterministe** : la même pièce donne toujours le même JSON.

---

## 2. Le corpus (`seed.py`, `seeds/`)

### Deux jeux

| Jeu | Volume | Où | Usage |
|---|---:|---|---|
| Démonstration | 96 pièces : 40 devis PDF, 30 photos de commande, 16 messages, 10 BL | `seeds/generated/demo/` | base de démo, interface, vidéo |
| Évaluation | 120 documents : les 96 + 4 messages, 10 BL, 10 photos dégradées | `seeds/generated/eval/` + démo | mesures de la fiche IA |

Split stratifié 72 dev / 24 validation / 24 test, écrit dans chaque vérité terrain.
Graine `20261125`, `AS_OF=2026-11-25`. Toutes les données sont fictives.

### Comment une pièce est fabriquée

Pour chaque pièce, le générateur produit **en même temps** :

| Fichier | Rôle | Versionné |
|---|---|---|
| `generated/.../DEV-2026-041.pdf` (ou `.png`, `.txt`) | la pièce elle-même | non (régénérée) |
| `generated/.../DEV-2026-041.render.json` | ce que le générateur a dessiné (texte + bbox de chaque élément) | non |
| `golden/DEV-2026-041.truth.json` | la vérité terrain annotée | **oui** |

- **Devis et BL** : PDF à vraie couche texte (Helvetica), en-tête, tableau en colonnes
  alignées comme un devis réel (`N° | Désignation | Qté | Unité | PU HT | Remise | TVA | Total HT | Livré`),
  totaux imprimés.
- **Photos de commande** : la page est dessinée puis « photographiée » : fond, perspective,
  rotation légère, éclairage inégal, grain, flou. Tout est tiré de la graine.
  La police embarquée de Pillow n'a pas d'accents : les photos sont écrites sans accents.
- **Photos dégradées** : rotation de 3 à 4,5°, ombre forte ou tampon « DUPLICATA » posé
  **sur l'image**. La vérité terrain reste celle de la pièce imprimée.
- **Messages** : texte brut, une commande par ligne, sans IFU.

> Le `.render.json` n'est **jamais** lu par l'extraction. Il sert à la vérité terrain et
> à l'ablation « OCR parfait » des mesures (§7). Un test le vérifie : un rendu falsifié
> posé à côté d'un PDF ne change pas le résultat.

### Pièce témoin `DEV-2026-041`

3 lignes (banquettes 4 × 185 000, tables 2 × 120 000, installation 1 × 60 000),
IFU absent, total imprimé faux (HT 1 020 000 au lieu de 1 040 000, écart 20 000 FCFA),
installation non livrée (colonne « Livré » = 0).

### Anomalies injectées

Total d'addition faux (`arithmetique`), IFU absent (`MISSING_MANDATORY`), ligne non
livrée sur BL (`QUANTITY_MISMATCH`). Elles sont listées dans `injected_anomalies` de
chaque vérité terrain.

---

## 3. OCR : `adapters/ocr.py`

### Contrat

`ocr.lire(chemin, backend=None)` renvoie une liste de **lignes** :

```json
{
  "text": "2 Table basse chêne 2 pcs 120 000 0 18 % 240 000 2",
  "page": 1,
  "bbox": [6.72, 21.13, 86.0, 1.07],
  "confidence": 0.99,
  "method": "pdf_texte",
  "words": [
    {"text": "120", "bbox": [55.35, 21.13, 2.52, 1.07], "confidence": 0.99, "xr": [55.35, 57.87], "h": 1.07}
  ]
}
```

- `bbox` : **pourcentage de la page** `[x, y, largeur, hauteur]`, origine en haut à gauche.
  C'est le format de la visionneuse de Jean-Marie.
- `words` : chaque mot garde sa propre bbox, ce qui permet de surligner une **cellule**
  et pas toute la ligne.
- `xr` : position horizontale **redressée**, utilisée pour retrouver les colonnes.

**Regroupement en lignes.** Sur une photo en perspective, la droite d'une rangée peut être
une demi-rangée plus haut que sa gauche. Un regroupement par hauteur globale coupait alors
l'en-tête du tableau en deux, et les lignes de la photo étaient perdues. Les mots sont donc
**chaînés de gauche à droite** : chaque mot rejoint la ligne dont le dernier mot est à sa
hauteur, en suivant la pente. La pente est mesurée sur les mots eux-mêmes : on retient la
pente qui forme le moins de lignes, puis on l'affine par régression. L'angle des boîtes
renvoyées par EasyOCR ne sert à rien ici, car ce sont presque toujours des rectangles droits.
- `method` : `pdf_texte`, `easyocr`, `pdf_scan+easyocr`, `texte`, `rendu_parfait` ou `vlm`.

### Lecteurs

| Pièce | Lecteur | Confiance |
|---|---|---|
| PDF avec couche texte | `pdfplumber` | 0,99 (texte lu, pas reconnu sur des pixels) |
| PDF scanné (sans texte) | rendu 150 dpi puis EasyOCR | celle d'EasyOCR |
| Image PNG/JPG/WEBP | EasyOCR (`fr`, CPU) | celle d'EasyOCR, par mot |
| Texte (`.txt`) | lecture directe | 1,0 |

Réglages EasyOCR (`PARAMS_EASYOCR`) : `min_size=4, low_text=0.3, mag_ratio=1.5`.
Sans eux, les chiffres isolés (n° de ligne, quantité, remise « 0 ») n'étaient pas détectés
(mesuré sur `CMD-2026-101`).

### Backends OCR

`backend` (ou la variable `WEMA_OCR_BACKEND`) :

| Valeur | Comportement |
|---|---|
| `auto` (défaut) | cache → sinon EasyOCR → sinon `OCRIndisponible` |
| `cache` | cache seulement pour les images ; n'exécute jamais EasyOCR |
| `reel` | ignore le cache, relit et réécrit le cache |
| `rendu` | ablation de mesure « OCR parfait » (relit le `.render.json`) ; **jamais en production** |
| `vlm` | service externe optionnel (`WEMA_VLM_ENDPOINT`) ; échoue s'il n'est pas configuré |

Un lecteur absent **lève une exception** au lieu de retomber silencieusement sur autre
chose : la pièce reste alors en `EN_ATTENTE_IA`.

---

## 4. Le cache OCR (`seeds/ocr_cache/`)

**Pourquoi.** Lire une photo avec EasyOCR coûte 45 à 90 s sur CPU et demande torch
(~200 Mo) ainsi qu'un téléchargement unique des poids. La démo doit pourtant tourner
hors ligne, vite et toujours pareil, y compris dans le Docker où EasyOCR n'est pas installé.

**Ce que c'est.** Un fichier JSON par image, qui contient la **sortie brute réelle**
d'EasyOCR (mots, boîtes en pixels, confiance, angle), le moteur, sa version et ses
réglages. Les erreurs de lecture y sont conservées telles quelles (`OOO` pour `000`,
`Cllent` pour `Client`) : ce n'est pas une version corrigée.

**Clé.** L'empreinte SHA-256 des **pixels décodés** (`px-…`), pas des octets du PNG :
deux versions de zlib peuvent encoder les mêmes pixels différemment, et le cache doit
survivre à un changement de machine.

**Cycle de vie.**

```bash
pip install -r requirements-ocr.txt        # une fois, si on veut relire des images
python -m adapters.ocr --warm               # lit toutes les images du corpus absentes du cache
python -m adapters.ocr --warm --force       # relit tout (après changement de réglages)
python -m adapters.ocr chemin/photo.png     # une image précise
```

Le cache est **versionné dans git**. Après une modification du rendu des images dans
`seed.py`, il faut relancer `--warm` et committer `seeds/ocr_cache/`. Le regroupement en
lignes n'est pas dans le cache : il est recalculé à chaque lecture, donc une
amélioration du parseur ne demande pas de relire les images.

**Ce que l'on dit au jury.** « Lectures EasyOCR réelles, mises en cache pour une
démonstration hors ligne et reproductible. »

---

## 5. Structuration : `adapters/llm.py`

Les backends `demo` et `cpu` utilisent le même **structureur à règles**, déterministe et
hors ligne. `cloud` est un point d'entrée prévu : sans `WEMA_LLM_URL`, il lève
`BackendIndisponible`.

### En-tête

Les libellés sont lus avec tolérance aux confusions OCR courantes : `Client`, `Cllent`,
`C1ient` ; `IFU`, `1FU` ; ponctuation lue `:`, `;` ou `.`.

| Champ | Repéré par |
|---|---|
| `reference` | motif `DEV/CMD/BL/MSG/DEG/FAC/AV-AAAA-NNN` |
| `client.name` | `Client : …` |
| `client.ifu` | `IFU : <chiffres>` ; libellé sans chiffres = **absent** |
| `dates.issue` | `Date : …` |
| `payment_terms` | `Conditions : …` |
| `dates.due`, `dates.delivery`, `client.address`, `client.phone` | non lus aujourd'hui : toujours absents |

Une ligne OCR est découpée en **segments** là où les mots s'écartent fortement. Ainsi, un
tampon posé à côté du nom du client ne se colle pas au nom.

### Tableau des lignes

1. Repérer la ligne d'en-tête (`Désignation` + `PU` ou `Total`) et la position de chaque
   colonne (`PUHT` lu d'un bloc est accepté).
2. Pour chaque rangée, regrouper les nombres : `185` + `000` = un montant,
   `18` + `%` = un taux.
3. Ranger chaque nombre dans la colonne numérique dont le **bord droit** est le plus
   proche, à 3,5 % de largeur près : les montants sont alignés à droite.
4. Le reste se répartit entre la désignation et l'unité selon la position de la colonne `Unité`.
5. Une rangée sans désignation ni au moins deux nombres (tampon, griffonnage) est ignorée.

**Confusions lettre/chiffre.** Elles ne sont corrigées que dans un nombre : `O0OO` donne
`0000`, et `OOO` donne `000` s'il suit un nombre. `No` et `Article` ne sont jamais
convertis. La lecture d'origine reste dans le champ `lu` du mot.

Les messages texte, qui n'ont pas de tableau, sont lus ligne à ligne
(`1  Article …  2 pcs x 120 000 FCFA … Total 240 000 FCFA`).

### Totaux

Seuls les **montants imprimés** sont lus (`Total HT :`, `TVA 18 % :`, `Total TTC :`).
L'extraction ne recalcule rien : le recalcul et l'écart appartiennent à `domain/tax.py`.

---

## 6. Le JSON d'extraction : `domain/extraction.py`

Schéma de l'annexe A du blueprint. Chaque valeur est un objet :

| Clé | Sens |
|---|---|
| `value` / `value_normalized` | valeur normalisée : entier FCFA, date ISO, quantité en texte décimal, taux en % entier |
| `raw` | texte tel que lu |
| `confidence` | 0..1, trois signaux (ci-dessous) |
| `page`, `bbox` | provenance, obligatoire pour toute valeur non nulle |
| `method` | lecteur + `regles`, par exemple `easyocr+regles` |
| `missing` / `motif` | `ABSENT_DE_LA_PIECE` si la valeur est absente |

Racine : `document_type`, `reference`, `client{name, ifu, address, phone}`,
`dates{issue, delivery, due}`, `payment_terms{text, days, method}`, `lines[]`,
`totals{printed_ht, printed_vat, printed_ttc, ht, vat, ttc}`, `missing[]`,
`confidence_global`. Ici, `totals.ht` est un **alias du montant imprimé**, pas un recalcul.

### Confiance : trois signaux

`confiance = 0,30 × OCR + 0,40 × modèle + 0,30 × cohérence`

- **OCR** : confiance moyenne des mots de la cellule (0,99 pour une couche texte PDF).
- **Modèle** : solidité de la règle. 0,95 si la valeur est lue nette, 0,75 si le libellé n'a
  été reconnu que par tolérance (`Cllent`), 0,65 si des lettres ont été converties en chiffres,
  dégressif selon l'alignement d'une cellule sous sa colonne.
- **Cohérence** : la ligne se tient-elle (`qté × PU − remise = total`) ? Le total imprimé
  égale-t-il la somme des lignes ? Le nom et l'IFU correspondent-ils au **référentiel
  clients** (un nom presque identique à un client connu, comme « Malson » pour « Maison », est suspect) ?

Seuils de revue : 0,80 par défaut, 0,90 pour les champs fiscaux (IFU, TVA, totaux),
0,95 pour les numéros. Sous le seuil, le champ part en revue humaine
(`extraction.exiger_revue(payload)`). C'est pourquoi le total faux de `DEV-2026-041`
ressort à 0,857 : la valeur lue est juste, mais elle contredit les lignes, donc on la fait regarder.

**Tout le détail (barèmes, exemples, mesure de l'efficacité du seuil) est dans
[`CONFIANCE.md`](CONFIANCE.md).** Mesuré : 48 erreurs sur 48 attrapées, 0 erreur silencieuse.

### Garde-fous (`valider`)

`extraire_piece` lève `ExtractionInvalide` si l'un de ces contrôles échoue :
- schéma incomplet ;
- valeur non nulle sans `page` + `bbox` + `method` ;
- champ absent avec une valeur, ou valeur nulle sans motif.

---

## 7. Mesures : `domain/metrics.py`

```bash
python -m domain.metrics                 # chaîne réelle (cache EasyOCR + pdfplumber)
python -m domain.metrics --ocr rendu     # ablation : parseur sur texte parfait
```

Les mesures portent sur les 120 documents annotés :
- exactitude par champ d'en-tête ;
- précision, rappel et F1 des lignes (désignation + quantité + unité + PU) ;
- exactitude des totaux imprimés ;
- STP : document lu sans aucune correction ;
- rappel des anomalies injectées ;
- **valeurs inventées**, qui doivent rester à 0 ;
- matrice de confusion des types ;
- 30 erreurs analysées.

Les deux colonnes se lisent ensemble : **texte parfait** mesure le parseur seul, **chaîne
réelle** mesure ce que le système fait vraiment. L'écart entre les deux, c'est le coût de
la lecture. Seuls les chiffres de la chaîne réelle sont annoncés comme résultats.

---

## 8. Intégration pour l'équipe

### Melon (API, worker, base)

> **Maillon extraction → brouillon** et confirmations avant validation : voir
> [`BROUILLON.md`](BROUILLON.md) (`creer_brouillon`, `exiger_confirmations`).

```python
from adapters.ocr import OCRIndisponible
from domain.extraction import ExtractionInvalide, extraire_piece, persister
import db

try:
    payload = extraire_piece(chemin_piece)              # backend selon AI_BACKEND
except (OCRIndisponible, ExtractionInvalide):
    ...                                                 # statut EN_ATTENTE_IA, rien d'inventé
else:
    with db.transaction(conn):
        persister(conn, document_id, payload)           # extractions + extracted_fields + document_totals
        ...                                             # transition IMPORTÉ → EXTRAIT
```

- `persister` **ajoute** une passe sans rien écraser. Les identifiants `ext_0001_…`,
  `ext_0002_…` sont ordonnés par document : `ORDER BY extraction DESC` renvoie bien la
  dernière passe.
- `extracted_fields.chemin` suit le JSON : `client.name`, `client.ifu`, `dates.issue`,
  `lines[0].quantity`, `totals.printed_ht`…
- **Dockerfile** : il faut ajouter `COPY seeds ./seeds` pour que le cache OCR et les
  vérités terrain soient dans l'image. EasyOCR n'est pas requis dans l'image de démo.
- `python -m seed --reset` réinitialise **ta** base, puis la charge (§9). Ne la lance que si
  la réinitialisation est voulue.

### Jean-Marie (front)

- `extraction.aplatir(payload)` donne la vue plate attendue par la visionneuse :
  `reference`, `date`, `client_name`, `client_ifu`, `printed_ht`, `line_2_price`…
  Chaque entrée a la forme `{value, raw, page, bbox:{x,y,w,h}, method, confidence, motif?}`.
- Les bbox sont en **% de la page**, comme dans le mock : rien à convertir.
- Cliquer sur `120 000` → `line_2_price.bbox` encadre la **cellule** dans le PDF.
- Les vraies pièces sont dans `seeds/generated/demo/` : elles peuvent remplacer la page
  simulée de `SourceViewer.jsx`.

### Larissa (règles)

- `controls._champ_extrait()` lit ce que `persister` écrit, chemins compris (couvert par
  `TestPersistance`).
- `document_totals` reçoit les **montants imprimés** ; le recalcul reste chez toi.
- À faire : relire les vérités terrain de `seeds/golden/` ; la graine ne remplace pas une
  validation humaine.

---

## 9. Commandes

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -r requirements-ocr.txt          # optionnel : lire des photos hors cache

python -m seed --as-of 2026-11-25            # corpus + vérités terrain (~25 s)
python -m seed --reset --as-of 2026-11-25    # + base : 64 clients, 120 articles, 60 factures,
                                             #   9 avoirs, 18 paiements, 96 pièces extraites
python -m adapters.ocr --warm                # remplit le cache EasyOCR (~1 min par image)
python -m domain.metrics                     # mesures de la chaîne réelle
python -m unittest tests.test_extraction tests.test_ia_avancee -v
```

Après `--reset`, la prochaine facture validée reçoit `FAC-2026-00061` et le prochain avoir
`AV-2026-00010` (`numbering.verifier_continuite` → OK). Une photo absente du cache, sans
EasyOCR installé, reste en `EN_ATTENTE_IA`.

---

## 10. Limites connues

Mesures complètes dans [`FICHE_IA.md`](FICHE_IA.md). En résumé, sur la chaîne réelle : en-tête
96,4 %, F1 des lignes 0,959, STP 69,2 %, **0 valeur inventée**. Les PDF et les messages sont
parfaits. Les **photos sont la classe faible** (STP 6,7 % sur les photos de commande) :
- confusion **i → l** dans les noms (35 documents) ;
- **« 4 » et « 1 » isolés non détectés** (11 quantités) : la quantité ressort absente, jamais fausse ;
- cellules masquées par un tampon.

- Le corpus est **synthétique**. Les photos sont simulées (perspective, lumière, grain) :
  elles ne remplacent ni de vrais scans, ni l'écriture manuscrite, ni des tampons réels.
- Les règles connaissent la mise en page du corpus : libellés `Client :`, `IFU :`, tableau
  à en-tête. Une mise en page très différente ne sera pas structurée et ses champs
  ressortiront absents. Ils ne seront pas inventés, mais il faudra une saisie humaine.
- Échéance, adresse, téléphone et mode de paiement ne sont pas lus aujourd'hui.
- EasyOCR confond `i` et `l` dans les noms (`Malson`, `Bols`) : le rattachement au
  référentiel client (Larissa, `match_client`) absorbe une partie de ces erreurs.
- Le backend `cloud` (LLM) n'est pas branché.
- Une photo nouvelle (hors corpus) exige EasyOCR installé ; sans lui, elle reste en attente.
