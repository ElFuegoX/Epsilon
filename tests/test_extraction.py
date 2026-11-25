"""Tests de l'extraction WÉMA : contrat, provenance, non-invention, mesures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from adapters import llm, ocr
from config import settings
from domain import extraction, metrics, normalization as norm
from domain.extraction import ABSENT

RACINE = Path(__file__).resolve().parents[1]
TEMOIN = RACINE / "seeds" / "golden" / "DEV-2026-041.truth.json"


class TestNormalisation(unittest.TestCase):
    def test_montant_fcfa_avec_espaces(self) -> None:
        self.assertEqual(norm.normalize_amount("1 020 000 FCFA"), 1_020_000)

    def test_date_iso_et_locale(self) -> None:
        self.assertEqual(norm.normalize_date("2026-11-18"), "2026-11-18")
        self.assertEqual(norm.normalize_date("18/11/2026"), "2026-11-18")

    def test_tva_en_points_de_base(self) -> None:
        self.assertEqual(norm.normalize_tax("18 %"), 1800)

    def test_quantite_et_unite(self) -> None:
        self.assertEqual(norm.normalize_quantity("4"), "4")
        self.assertEqual(norm.normalize_unit("m²"), "m²")

    def test_valeur_inconnue_reste_nulle(self) -> None:
        self.assertIsNone(norm.normalize_amount("environ 100"))
        self.assertIsNone(norm.normalize_date("bientôt"))


class TestChampContraint(unittest.TestCase):
    def test_champ_present_a_une_provenance(self) -> None:
        bloc = {
            "text": "DEVIS DEV-2026-041", "page": 2,
            "bbox": [10.0, 20.0, 30.0, 5.0], "confidence": 0.9,
        }
        champ = extraction.champ("DEV-2026-041", bloc, normaliseur=str)
        self.assertNotIn("missing", champ)
        self.assertEqual(champ["value"], "DEV-2026-041")
        self.assertEqual(champ["page"], 2)
        self.assertEqual(champ["bbox"], [10.0, 20.0, 30.0, 5.0])
        self.assertGreaterEqual(champ["confidence"], 0.80)
        self.assertEqual(champ["method"], "ocr+llm+croise")

    def test_champ_absent_ne_recoit_aucune_valeur(self) -> None:
        champ = extraction.champ(None, {"page": 1, "bbox": [1, 2, 3, 4]}, absent=True)
        self.assertIsNone(champ["value"])
        self.assertEqual(champ["missing"], ABSENT)
        self.assertEqual(champ["motif"], ABSENT)
        self.assertEqual(champ["confidence"], 0.0)

    def test_confiance_trois_signaux(self) -> None:
        self.assertEqual(extraction.combinee_confiance(1.0, 1.0, 1.0), 1.0)
        self.assertEqual(extraction.combinee_confiance(0.0, 0.0, 0.0), 0.0)
        self.assertEqual(extraction.combinee_confiance(0.8, 0.9, 1.0), 0.9)

    def test_seuils_differencies(self) -> None:
        self.assertEqual(extraction.seuil("reference"), settings.confiance_numero)
        self.assertEqual(extraction.seuil("client.ifu"), settings.confiance_fiscal)
        self.assertEqual(extraction.seuil("description"), settings.confiance_champ)

    def test_normaleurrefuse_une_valeur_ambiguo(self) -> None:
        champ = extraction.champ("?", {"page": 1, "bbox": [1, 2, 3, 4]},
                                 normaliseur=norm.normalize_amount)
        self.assertEqual(champ["missing"], ABSENT)
        self.assertIsNone(champ["value"])


class TestCorpus(unittest.TestCase):
    def test_temoin_est_conforme(self) -> None:
        verite = json.loads(TEMOIN.read_text(encoding="utf-8"))
        self.assertEqual(verite["reference"], "DEV-2026-041")
        self.assertIsNone(verite["client"]["ifu"])
        self.assertEqual(verite["expected_ecart"]["ht"], 20_000)
        self.assertEqual(verite["expected_ecart"]["vat"], 3_600)
        self.assertEqual(verite["date"], "2026-11-18")

    def test_manifest_120_documents_et_split(self) -> None:
        manifest = json.loads(
            (RACINE / "seeds" / "generated" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["evaluation"]["documents"], 120)
        self.assertEqual(manifest["evaluation"]["split"],
                         {"dev": 72, "validation": 24, "test": 24})
        self.assertEqual(manifest["demonstration"]["pieces"], 96)
        self.assertEqual(manifest["referentiels"]["clients"], 64)
        self.assertEqual(manifest["referentiels"]["articles"], 120)
        self.assertEqual(settings.graine_demo, manifest["graine"])

    def test_fichier_et_sidecar_vont_ensemble(self) -> None:
        verite = json.loads(TEMOIN.read_text(encoding="utf-8"))
        piece = RACINE / verite["source_file"]
        sidecar = piece.with_name(piece.stem + ".layout.json")
        self.assertTrue(piece.is_file())
        self.assertTrue(sidecar.is_file())
        donnees = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(donnees["sha256"], verite["sha256"])
        self.assertEqual(donnees["bbox_unite"], "pourcent")

    def test_ocr_lit_blocs_avec_bbox(self) -> None:
        blocs = ocr.lire(RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf")
        self.assertTrue(blocs)
        for bloc in blocs:
            self.assertEqual(len(bloc["bbox"]), 4)
            self.assertTrue(all(0 <= v <= 100 for v in bloc["bbox"]))
            self.assertIn(bloc["method"], ("ocr", "mise_en_page", "pypdf", "texte"))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = extraction.extraire_piece(
            RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf"
        )

    def test_reference_et_client(self) -> None:
        self.assertEqual(self.payload["reference"]["value"], "DEV-2026-041")
        self.assertEqual(self.payload["client"]["name"]["value"], "Ets Sossa Materiaux")
        self.assertEqual(self.payload["client"]["ifu"]["value"], None)
        self.assertEqual(self.payload["client"]["ifu"]["missing"], ABSENT)

    def test_lignes_et_taux(self) -> None:
        self.assertEqual(len(self.payload["lines"]), 3)
        self.assertEqual(self.payload["lines"][0]["unit_price_ht"]["value"], 185_000)
        self.assertEqual(self.payload["lines"][0]["tax_rate"]["value"], 18)
        self.assertEqual(self.payload["lines"][2]["delivered"]["value"], "0")

    def test_montants_imprimes_pas_recalcules(self) -> None:
        self.assertEqual(extraction.valeur(self.payload["totals"]["printed_ht"]), 1_020_000)
        self.assertEqual(extraction.valeur(self.payload["totals"]["printed_ttc"]), 1_203_600)

    def test_schema_valide_sans_valeur_inventee(self) -> None:
        resultat = extraction.valider(self.payload)
        self.assertTrue(resultat["valide"], resultat["problemes"])

    def test_revue_oblige_pour_ifu_absent(self) -> None:
        self.assertIn("client.ifu", extraction.exiger_revue(self.payload))

    def test_vue_plate_pour_la_visionneuse(self) -> None:
        plat = extraction.aplatir(self.payload)
        self.assertEqual(plat["reference"]["value"], "DEV-2026-041")
        self.assertEqual(plat["reference"]["bbox"]["x"], plat["reference"]["bbox"]["x"])
        self.assertEqual(plat["client_ifu"]["motif"], ABSENT)
        self.assertEqual(plat["line_1_price"]["value"], 185_000)
        for cle, champ in plat.items():
            if champ["value"] is not None:
                self.assertIn("x", champ["bbox"])
                self.assertIn("y", champ["bbox"])

    def test_classification_document(self) -> None:
        blocs = ocr.lire(RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf")
        self.assertEqual(llm.classer(blocs), "devis")
        self.assertEqual(llm.proposer(blocs, backend="demo")["backend"], "demo")

    def test_backend_cloud_sans_url_ne_devine_rien(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(llm.BackendIndisponible):
                llm.extraire(
                    RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf",
                    backend="cloud",
                )


class TestMesures(unittest.TestCase):
    def test_mesures_reproductibles(self) -> None:
        premier = metrics.evaluer(ecrire=False)
        second = metrics.evaluer(ecrire=False)
        self.assertEqual(premier, second)
        self.assertEqual(premier["documents"], 120)
        self.assertEqual(premier["valeurs_inventees"], 0)
        self.assertGreaterEqual(premier["exactitude_champs"], 0.95)
        self.assertGreaterEqual(premier["lignes"]["f1"], 0.90)
        self.assertGreaterEqual(premier["exactitude_totaux_imprimes"], 0.98)
        self.assertEqual(premier["matrice_confusion"],
                         [{"reel": "bon_livraison", "preddit": "bon_livraison", "nombre": 20},
                          {"reel": "commande", "preddit": "commande", "nombre": 30},
                          {"reel": "devis", "preddit": "devis", "nombre": 50},
                          {"reel": "message", "preddit": "message", "nombre": 20}])


if __name__ == "__main__":
    unittest.main()
