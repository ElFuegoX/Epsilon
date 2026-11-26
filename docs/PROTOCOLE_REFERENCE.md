# Protocole — mesure contre la méthode de référence

Responsable : **Freud**. Le TDR demande de « **mesurer les gains de temps et les erreurs évitées par
rapport à une méthode de référence**, en distinguant les résultats de l'IA de l'exactitude des règles
et des calculs ». La méthode de référence est celle d'aujourd'hui : une personne **recopie** la pièce
à la main. On la chronomètre sur 20 pièces, on compte ses erreurs, et on met WÉMA en face, sur les
mêmes pièces.

> **Aucune donnée humaine n'est simulée.** `python -m domain.reference comparer` s'arrête si les
> fiches sont vides. Les chiffres du rapport viennent d'une vraie saisie, ou n'existent pas.

---

## 1. Les 20 pièces

`python -m domain.reference preparer` les choisit de façon déterministe, **hors du jeu de
développement** (jeux validation et test), stratifiées par famille :

| Famille | Pièces |
|---|---:|
| Devis PDF | 6 |
| Photos de commande | 6 |
| Messages | 3 |
| Bons de livraison | 3 |
| Photos dégradées | 2 |

La liste est dans `seeds/reference/pieces.json`. Les fiches à remplir sont
`seeds/reference/saisie_entetes.csv` (une ligne par pièce) et `seeds/reference/saisie_lignes.csv`
(une ligne par ligne de commande). Les fiches remplies sont **versionnées** : c'est la preuve
citée dans le rapport.

## 2. Qui saisit

- Idéalement quelqu'un **hors de l'équipe de développement**, qui n'a jamais vu les pièces : un
  mentor, un camarade, un profil gestion.
- À défaut, un membre de l'équipe, et le rapport le dit.
- Une seule personne pour les 20 pièces, d'une traite, sans pause au milieu d'une pièce.

## 3. La saisie, pièce par pièce

1. Ouvrir le fichier indiqué dans la colonne `fichier` (PDF, PNG ou TXT).
2. Noter l'heure de **début** au format `HH:MM:SS` (horloge de l'ordinateur), colonne `debut`.
3. Recopier ce qu'on **lit sur la pièce**, rien d'autre :
   - `saisie_entetes.csv` : `reference`, `client`, `ifu`, `date` (AAAA-MM-JJ), `total_ht_imprime` ;
   - `saisie_lignes.csv` : une ligne par article, avec `document`, `ligne` (le numéro), `description`,
     `quantite`, `unite`, `pu_ht`, `total_ligne`.
4. **Un champ absent de la pièce reste vide.** Ne pas compléter de mémoire, ne pas calculer
   (pas de TVA, pas de total recalculé), ne pas corriger une erreur de la pièce.
5. Noter l'heure de **fin**, colonne `fin`. Une remarque libre est possible (`remarque`).

Montants en chiffres, espaces acceptés (`1 020 000`). On garde les fautes de frappe : c'est ce
qu'on mesure.

## 4. Côté WÉMA

`comparer` mesure automatiquement, sur les mêmes 20 pièces :
- le **temps machine** de l'extraction ;
- le **temps réel de l'OCR** des photos, tel qu'enregistré dans le cache EasyOCR ;
- le nombre de **valeurs à confirmer** (celles que le seuil envoie en revue) ;
- les **erreurs** de l'outil et ses **erreurs silencieuses** (0 attendu).

**Ce que le script ne mesure pas** : le temps qu'un humain passe à **confirmer** ces valeurs dans
l'interface. Dès que le parcours tourne (API et front branchés), chronométrer la même personne sur
les mêmes pièces : ouvrir la pièce, confirmer ou corriger chaque valeur signalée, valider. Ajouter
ce temps au rapport. Tant que ce n'est pas fait, le rapport compare la saisie manuelle au temps
machine **plus** un nombre de valeurs à confirmer, pas à un temps humain total.

## 5. Le calcul

```bash
python -m domain.reference comparer
```

Pour chaque valeur, la saisie est comparée à la vérité terrain avec la même règle d'égalité que les
métriques de l'IA (montants en entiers, dates en ISO, texte sans accents ni casse). Chaque erreur
manuelle est classée :

| Nature | Exemple |
|---|---|
| `faute_de_saisie` | 185 000 tapé 158 000 |
| `oubli` | client laissé vide alors qu'il est sur la pièce |
| `valeur_inventee` | IFU tapé alors qu'il n'est pas sur la pièce, ligne en trop |

Toute erreur de saisie manuelle est **silencieuse par nature** : rien ne la signale. C'est la
comparaison clé avec WÉMA, où chaque erreur de lecture mesurée part en revue (voir
[`CONFIANCE.md`](CONFIANCE.md)).

Le résultat complet est écrit dans `seeds/reference/resultat.json`.

## 6. Ce qu'on publie

Dans le rapport, section « Tests et mesures », **séparément** des résultats de l'IA (exigence du TDR) :

| | Saisie manuelle | WÉMA |
|---|---|---|
| Temps par pièce | mesuré (s) | machine (s) + temps de confirmation (à mesurer) |
| Erreurs | nombre, par nature | nombre |
| Erreurs silencieuses | toutes | 0 attendu |
| Valeurs inventées | nombre | 0 (mesuré) |

**Limites à écrire** : une seule personne, 20 pièces synthétiques, une personne qui découvre les
pièces (ni l'outil ni la saisie ne bénéficient d'habitude), et pour WÉMA, le temps de confirmation
encore à chronométrer.
