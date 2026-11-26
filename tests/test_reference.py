"""Comparateur saisie manuelle / WÉMA : il note juste et ne simule rien."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from domain import metrics, reference


class TestReference(unittest.TestCase):
    def setUp(self) -> None:
        self.dossier_tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.dossier_tmp.name)
        reference.preparer(self.dossier)
        self.verites = {t["reference"]: t for t in metrics.charger_truths()}

    def tearDown(self) -> None:
        self.dossier_tmp.cleanup()

    def _remplir(self, documents: list[str], fautes: bool = False) -> None:
        with (self.dossier / "saisie_entetes.csv").open(encoding="utf-8") as flux:
            lignes = list(csv.DictReader(flux))
        sorties = []
        for ligne in lignes:
            truth = self.verites[ligne["document"]]
            if ligne["document"] in documents:
                ligne.update({"debut": "10:00:00", "fin": "10:03:00",
                              "reference": truth["reference"], "client": truth["fields"]["client.name"],
                              "ifu": truth["fields"]["client.ifu"] or "",
                              "date": truth["fields"]["dates.issue"],
                              "total_ht_imprime": truth["printed_totals"]["ht"] or ""})
                if fautes:
                    ligne["ifu"] = "1234567890"  # IFU tapé alors qu'il n'est pas sur la pièce
                    ligne["client"] = ""          # oubli
                    for l in truth["lines"]:
                        sorties.append({"document": truth["reference"], "ligne": l["line_no"],
                                        "description": l["description"], "quantite": l["quantity"],
                                        "unite": l["unit"], "pu_ht": int(l["unit_price_ht"]) + 1000,
                                        "total_ligne": l["line_total_ht"]})
                else:
                    for l in truth["lines"]:
                        sorties.append({"document": truth["reference"], "ligne": l["line_no"],
                                        "description": l["description"], "quantite": l["quantity"],
                                        "unite": l["unit"], "pu_ht": l["unit_price_ht"],
                                        "total_ligne": l["line_total_ht"]})
        with (self.dossier / "saisie_entetes.csv").open("w", newline="", encoding="utf-8") as flux:
            ecrivain = csv.DictWriter(flux, fieldnames=reference.ENTETES)
            ecrivain.writeheader()
            ecrivain.writerows(lignes)
        with (self.dossier / "saisie_lignes.csv").open("w", newline="", encoding="utf-8") as flux:
            ecrivain = csv.DictWriter(flux, fieldnames=reference.LIGNES)
            ecrivain.writeheader()
            ecrivain.writerows(sorties)

    def test_vingt_pieces_stratifiees_hors_jeu_de_developpement(self) -> None:
        pieces = reference.choisir()
        self.assertEqual(len(pieces), 20)
        self.assertTrue(all(t["split"] in ("validation", "test") for t in pieces))
        self.assertEqual({t["family"] for t in pieces}, set(reference.QUOTAS))

    def test_fiche_vide_aucune_simulation(self) -> None:
        with self.assertRaises(SystemExit):
            reference.comparer(self.dossier)

    def test_saisie_parfaite_zero_erreur(self) -> None:
        documents = [t["reference"] for t in reference.choisir()[:3]]
        self._remplir(documents)
        resultat = reference.comparer(self.dossier)
        self.assertEqual(resultat["pieces"], 3)
        self.assertEqual(resultat["manuel"]["erreurs"], 0)
        self.assertEqual(resultat["manuel"]["temps_moyen_s"], 180.0)

    def test_fautes_classees_par_nature(self) -> None:
        sans_ifu = next(t for t in reference.choisir() if t["fields"]["client.ifu"] is None)
        self._remplir([sans_ifu["reference"]], fautes=True)
        natures = reference.comparer(self.dossier)["manuel"]["erreurs_par_nature"]
        self.assertEqual(natures["valeur_inventee"], 1)                 # l'IFU tapé
        self.assertEqual(natures["oubli"], 1)                           # le client
        self.assertEqual(natures["faute_de_saisie"], len(sans_ifu["lines"]))  # les PU


if __name__ == "__main__":
    unittest.main()
