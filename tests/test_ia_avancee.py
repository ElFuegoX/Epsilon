"""Tests des briques IA optionnelles : Jev, contraintes, lexical, backends."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters import constraints, llm, ocr
from domain import extraction, jev, semantic
from domain.jev import ABSENT, Choice, Noul, Score

BLOCS = [
    {
        "text": "DEVIS DEV-2026-900",
        "page": 1,
        "bbox": [10.0, 20.0, 40.0, 6.0],
        "confidence": 0.9,
    },
    {
        "text": "Client : Ets Sossa IFU : 123456789",
        "page": 1,
        "bbox": [10.0, 30.0, 60.0, 6.0],
        "confidence": 0.9,
    },
]


class TestJev(unittest.TestCase):
    def test_noul_ne_porte_jamais_de_valeur(self) -> None:
        absent = Noul()
        self.assertIsNone(absent.value)
        champ = absent.comme_champ(page=2, bbox=[1.0, 2.0, 3.0, 4.0])
        self.assertIsNone(champ["value"])
        self.assertEqual(champ["missing"], ABSENT)
        self.assertEqual(champ["motif"], ABSENT)
        self.assertEqual(champ["page"], 2)

    def test_choice_sans_candidat_donne_noul(self) -> None:
        self.assertIsInstance(Choice.depuis([]).resoudre(), Noul)

    def test_choice_respecte_le_seuil_et_calcule_la_marge(self) -> None:
        choix = Choice.depuis([("faible", 0.4), ("fort", 0.8)], seuil=0.9)
        self.assertIsInstance(choix.resoudre(), Noul)
        self.assertAlmostEqual(choix.marge, 0.4)

    def test_score_sans_logprobs_egale_la_formule_historique(self) -> None:
        self.assertEqual(
            Score(0.8, 0.9, 1.0).valeur,
            extraction.combinee_confiance(0.8, 0.9, 1.0),
        )

    def test_score_avec_logprobs_reels(self) -> None:
        score = Score(1.0, 1.0, 1.0, logprobs={"mean": -0.6931471805599453})
        self.assertAlmostEqual(score.valeur, 0.925, places=4)

    def test_logprobs_absents_ne_sont_pas_inventes(self) -> None:
        self.assertIsNone(jev.calibrer_logprobs(None))
        self.assertIsNone(jev.calibrer_logprobs({"tokens": ["sans", "valeur"]}))


class TestContraintes(unittest.TestCase):
    @staticmethod
    def _proposition() -> dict[str, object]:
        return {"document_type": "devis", "fields": {}, "lines": [], "totals": {}}

    def test_reparation_sans_invention(self) -> None:
        proposition = self._proposition()
        proposition["fields"] = {
            "client.name": {
                "raw": "Ets Sossa",
                "bloc": BLOCS[1],
                "missing": False,
            },
            "champ_inconnu": {"raw": "x", "bloc": None, "missing": False},
        }
        propre = constraints.appliquer(proposition)
        self.assertNotIn("champ_inconnu", propre["fields"])
        self.assertIn("client.ifu", propre["fields"])
        self.assertTrue(propre["fields"]["client.ifu"]["missing"])
        self.assertIsNone(propre["fields"]["client.ifu"]["raw"])
        self.assertEqual(propre["constraint_report"]["schema"], "wema-extraction-1.0")

    def test_type_invalide_est_refuse(self) -> None:
        proposition = self._proposition()
        proposition["document_type"] = "facture"
        with self.assertRaises(constraints.PropositionInvalide):
            constraints.appliquer(proposition)

    def test_backend_non_installe_refuse_sans_repli_silencieux(self) -> None:
        with mock.patch.dict(os.environ, {"WEMA_CONSTRAINT_BACKEND": "outlines"}, clear=False):
            with mock.patch(
                "adapters.constraints.importlib.util.find_spec", return_value=None
            ):
                with self.assertRaises(constraints.ContrainteIndisponible):
                    constraints.appliquer(self._proposition())

    def test_logprobs_sont_rapportes_sans_etre_inventes(self) -> None:
        propre = constraints.appliquer(
            self._proposition(), logprobs={"mean": -0.6931471805599453}
        )
        self.assertTrue(propre["constraint_report"]["logprobs_present"])
        self.assertAlmostEqual(
            propre["constraint_report"]["logprobs_calibres"], 0.5, places=4
        )


class TestSemantique(unittest.TestCase):
    def test_jargon_est_developpe(self) -> None:
        self.assertIn("papier", semantic.tokens("10 paquets A4"))
        self.assertIn("papier", semantic.tokens("ramette 80g"))

    def test_bm25_classe_le_jargon(self) -> None:
        scores = semantic.bm25(
            "ramette a4",
            {"bon": "ramette 80g", "mauvais": "canape velours"},
        )
        self.assertGreater(scores["bon"], scores["mauvais"])

    def test_rrf_est_deterministe(self) -> None:
        classements = [{"x": 3.0, "y": 1.0}, {"y": 2.0, "x": 1.0}]
        self.assertEqual(semantic.rrf(classements), semantic.rrf(classements))

    def test_similarite_sans_embedding_reste_dans_la_plage(self) -> None:
        with mock.patch.dict(os.environ, {"WEMA_EMBED_MODEL": ""}, clear=False):
            resultat = semantic.similarite("ramette a4", "ramette 80g")
        self.assertGreater(resultat["value"], 0.0)
        self.assertLessEqual(resultat["value"], 1.0)
        self.assertIsNone(resultat["embedding"])


class TestBackendsOptionnels(unittest.TestCase):
    @staticmethod
    def _fichier(dossier: str) -> Path:
        chemin = Path(dossier) / "piece.txt"
        chemin.write_text("DEVIS DEV-2026-900", encoding="utf-8")
        return chemin

    def test_backend_ocr_inconnu_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as dossier:
            with self.assertRaises(ocr.OCRIndisponible):
                ocr.lire(self._fichier(dossier), backend="inconnu")

    def test_sidecar_absent_ne_rompt_pas_sur_un_repli_silencieux(self) -> None:
        with tempfile.TemporaryDirectory() as dossier:
            with self.assertRaises(ocr.OCRIndisponible):
                ocr.lire(self._fichier(dossier), backend="sidecar")

    def test_vlm_sans_endpoint_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as dossier:
            with mock.patch.dict(os.environ, {"WEMA_VLM_ENDPOINT": ""}, clear=False):
                with self.assertRaises(ocr.OCRIndisponible):
                    ocr.lire(self._fichier(dossier), backend="vlm")


class TestPipelineContrainte(unittest.TestCase):
    @staticmethod
    def _proposition() -> dict[str, object]:
        with mock.patch.dict(os.environ, {"WEMA_CONSTRAINT_BACKEND": "auto"}, clear=False):
            return llm.proposer(BLOCS, backend="demo")

    def test_classification_utilise_choice_sans_changer_le_contrat(self) -> None:
        self.assertEqual(llm.classer(BLOCS), "devis")

    def test_proposition_et_payload_portent_le_rapport(self) -> None:
        proposition = self._proposition()
        self.assertEqual(proposition["constraint_report"]["backend"], "auto")
        self.assertFalse(proposition["constraint_report"]["logprobs_present"])
        payload = extraction.assembler(proposition, backend="demo")
        self.assertIn("constraint_report", payload)
        self.assertTrue(extraction.valider(payload)["valide"])

    def test_logprobs_globaux_abaissent_la_confiance_sans_inventer(self) -> None:
        sans = extraction.assembler(self._proposition(), backend="demo")
        avec_proposition = self._proposition()
        avec_proposition["logprobs"] = {"mean": -0.6931471805599453}
        avec = extraction.assembler(avec_proposition, backend="demo")
        self.assertLess(avec["reference"]["confidence"], sans["reference"]["confidence"])
        self.assertEqual(avec["reference"]["value"], sans["reference"]["value"])

    def test_cloud_propage_des_logprobs_reels(self) -> None:
        proposition_cloud = {
            "document_type": "devis",
            "fields": {},
            "lines": [],
            "totals": {},
            "logprobs": {"mean": -0.6931471805599453},
        }
        with mock.patch.object(llm, "_proposer_cloud", return_value=proposition_cloud):
            proposition = llm.proposer(BLOCS, backend="cloud")
        self.assertTrue(proposition["constraint_report"]["logprobs_present"])


if __name__ == "__main__":
    unittest.main()
