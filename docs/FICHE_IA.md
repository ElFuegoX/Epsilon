# Fiche IA — WÉMA 1.0

À remplir par **Freud** après les mesures, relu par **Larissa**. Mise en forme finale à faire quand l'outil sera prêt. Ne publier que des résultats mesurés, jamais les cibles du blueprint.

| Champ | Contenu |
|---|---|
| Nom et version du système | WÉMA 1.0 — extraction de pièces commerciales |
| Fournisseur et modèle | À compléter : nom exact, version figée, date de figeage, mode d'accès |
| Tâche | Classer, extraire en-tête et lignes, proposer un rapprochement |
| Entrées / sorties | PDF, image, texte → JSON contraint (page, bbox, confiance, valeurs normalisées) |
| Données | 120 documents synthétiques, aucune donnée réelle |
| Séparation des jeux | 60 % dev / 20 % validation / 20 % test, graine et empreinte du corpus |
| Annotation | Vérité terrain champ par champ, double relecture |
| Méthode d'évaluation | Exactitude par champ, F1 des lignes, exactitude des totaux, STP, rappel des anomalies |
| Résultats | À compléter : chiffres observés, y compris classes faibles |
| Erreurs observées | Au moins 3 catégories, avec un exemple anonymisé chacune |
| Seuils de revue | 0,80 par défaut ; 0,90 IFU/TVA/totaux ; 0,95 numéro |
| Limites | Écriture manuscrite, tampons, multi-pages, langues locales, dépendance fournisseur |
| Coût | Coût pour 1 000 documents, plafond mensuel, politique de cache |
| Responsable | Nom, rôle, date de la dernière revue |
