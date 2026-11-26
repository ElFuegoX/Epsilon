"""Tests de l'extraction WÉMA : contrat, provenance, non-invention, mesures."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
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
        self.assertEqual(champ["method"], "ocr+regles")
        bloc["method"] = "easyocr"
        self.assertEqual(extraction.champ("X", bloc)["method"], "easyocr+regles")

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

    def test_fichier_et_rendu_vont_ensemble(self) -> None:
        verite = json.loads(TEMOIN.read_text(encoding="utf-8"))
        piece = RACINE / verite["source_file"]
        rendu = piece.with_name(piece.stem + ".render.json")
        self.assertTrue(piece.is_file())
        self.assertTrue(rendu.is_file())
        donnees = json.loads(rendu.read_text(encoding="utf-8"))
        self.assertEqual(donnees["sha256"], verite["sha256"])
        self.assertEqual(donnees["bbox_unite"], "pourcent")
        self.assertEqual(donnees["role"], "verite_de_rendu")

    def test_ocr_lit_blocs_avec_bbox(self) -> None:
        blocs = ocr.lire(RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf")
        self.assertTrue(blocs)
        for bloc in blocs:
            self.assertEqual(len(bloc["bbox"]), 4)
            self.assertTrue(all(0 <= v <= 100 for v in bloc["bbox"]))
            self.assertEqual(bloc["method"], "pdf_texte")
            for mot in bloc["words"]:
                self.assertEqual(len(mot["bbox"]), 4)


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


def _cache_complet() -> bool:
    """Vrai si chaque image du corpus a sa lecture EasyOCR en cache."""
    images = [p for p in (RACINE / "seeds" / "generated").rglob("*.png")]
    return bool(images) and all(
        (ocr.CACHE / f"{ocr.empreinte_contenu(p)}.json").is_file() for p in images
    )


class TestOCRReel(unittest.TestCase):
    PDF = RACINE / "seeds" / "generated" / "demo" / "devis" / "DEV-2026-041.pdf"

    def test_extraction_ne_lit_jamais_le_rendu_du_generateur(self) -> None:
        """Un rendu falsifié à côté de la pièce ne change rien : on lit le fichier."""
        with tempfile.TemporaryDirectory() as dossier:
            copie = Path(dossier) / self.PDF.name
            shutil.copy(self.PDF, copie)
            rendu = json.loads(self.PDF.with_name("DEV-2026-041.render.json").read_text(encoding="utf-8"))
            for element in rendu["elements"]:
                element["texte"] = element["texte"].replace("Sossa", "FALSIFIE")
            copie.with_name("DEV-2026-041.render.json").write_text(json.dumps(rendu), encoding="utf-8")
            payload = extraction.extraire_piece(copie)
        self.assertEqual(payload["client"]["name"]["value"], "Ets Sossa Materiaux")

    def test_pdf_hors_corpus_lu_par_sa_couche_texte(self) -> None:
        import seed

        mesure = seed._mesure_pdf()
        client = {"raison_sociale": "Atelier Hors Corpus", "ifu": "1234567890123"}
        lignes = [{"line_no": 1, "description": "Chaise pliante", "quantity": "6", "unit": "pcs",
                   "unit_price_ht": 15000, "discount": 0, "tax_rate": 18, "line_total_ht": 90000}]
        elements = (seed._entete("DEVIS", "DEV-2026-777", "2026-11-20", client, False, mesure)
                    + seed._tableau(lignes, mesure, avec_livre=False)
                    + seed._totaux_imprimes({"ht": 90000, "vat": 16200, "ttc": 106200},
                                            ("ht", "vat", "ttc"), mesure))
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "hors_corpus.pdf"
            seed._ecrire_pdf(chemin, elements)
            payload = extraction.extraire_piece(chemin)
        self.assertEqual(payload["reference"]["value"], "DEV-2026-777")
        self.assertEqual(payload["client"]["ifu"]["value"], "1234567890123")
        self.assertEqual(len(payload["lines"]), 1)
        self.assertEqual(payload["lines"][0]["unit_price_ht"]["value"], 15000)
        self.assertEqual(payload["lines"][0]["quantity"]["value"], "6")
        self.assertEqual(payload["lines"][0]["delivered"]["missing"], ABSENT)
        self.assertEqual(extraction.valeur(payload["totals"]["printed_ttc"]), 106200)
        self.assertTrue(payload["lines"][0]["unit_price_ht"]["method"].startswith("pdf_texte"))

    def _image(self, dossier: str) -> Path:
        from PIL import Image

        chemin = Path(dossier) / "photo.png"
        Image.new("RGB", (40, 30), "white").save(chemin)
        return chemin

    def test_image_hors_cache_sans_lecteur_echoue_explicitement(self) -> None:
        with tempfile.TemporaryDirectory() as dossier:
            with mock.patch.object(ocr, "CACHE", Path(dossier) / "cache"):
                with self.assertRaises(ocr.OCRIndisponible):
                    ocr.lire(self._image(dossier), backend="cache")
                with mock.patch.object(ocr, "_lecteur", side_effect=ocr.OCRIndisponible("absent")):
                    with self.assertRaises(ocr.OCRIndisponible):
                        ocr.lire(self._image(dossier))

    def test_cache_rejoue_la_lecture_a_l_identique(self) -> None:
        page = {"numero": 1, "largeur": 40.0, "hauteur": 30.0, "methode": "easyocr",
                "mots": [{"text": "DEVIS", "box": [2, 2, 20, 6], "confidence": 0.91, "angle": 0.0}]}
        with tempfile.TemporaryDirectory() as dossier:
            with mock.patch.object(ocr, "CACHE", Path(dossier) / "cache"), \
                    mock.patch.object(ocr, "_pages_image", return_value=[page]) as lecteur:
                image = self._image(dossier)
                premier = ocr.lire(image)
                second = ocr.lire(image, backend="cache")
        self.assertEqual(lecteur.call_count, 1)
        self.assertEqual(premier, second)
        self.assertEqual(premier[0]["method"], "easyocr")

    def test_zeros_lus_comme_des_o_seulement_dans_un_nombre(self) -> None:
        self.assertEqual(llm._chiffres("OOO", apres_nombre=True), "000")
        self.assertEqual(llm._chiffres("O0OO", apres_nombre=False), "0000")
        self.assertEqual(llm._chiffres("OOO", apres_nombre=False), "OOO")  # pas de contexte : on ne devine pas
        self.assertEqual(llm._chiffres("No", apres_nombre=True), "No")
        self.assertEqual(llm._chiffres("Article", apres_nombre=True), "Article")
        mots = llm._normaliser_mots([{"text": "192", "xr": [0, 1]}, {"text": "OOO", "xr": [1.2, 2]}])
        self.assertEqual(mots[1]["text"], "000")
        self.assertEqual(mots[1]["lu"], "OOO")  # la lecture d'origine reste traçable

    def test_redressement_regroupe_les_lignes_d_une_photo_inclinee(self) -> None:
        pente = math.tan(math.radians(4))  # la photo penche de 4°
        mots = []
        for rang, rangee in enumerate((("1", "Chaise", "15", "000"), ("2", "Table", "40", "000"))):
            for colonne, texte in enumerate(rangee):
                x, y = 100 + colonne * 300, 200 + rang * 40
                y += x * pente
                mots.append({"text": texte, "box": [x, y, x + 60, y + 14],
                             "confidence": 0.9, "angle": 4.0})
        mots.append({"text": "Livraison et installation", "box": [100, 100, 900, 114],
                     "confidence": 0.9, "angle": 4.0})
        page = {"numero": 1, "largeur": 1200.0, "hauteur": 1600.0, "methode": "easyocr", "mots": mots}
        textes = [ligne["text"] for ligne in ocr.lignes_depuis_pages([page])]
        self.assertIn("1 Chaise 15 000", textes)
        self.assertIn("2 Table 40 000", textes)


class TestPersistance(unittest.TestCase):
    def test_champs_persistes_lisibles_par_les_controles(self) -> None:
        import db
        from domain import controls

        payload = extraction.extraire_piece(TestOCRReel.PDF)
        with tempfile.TemporaryDirectory() as dossier:
            chemin_base = str(Path(dossier) / "wema.db")
            db.initialize(chemin_base)
            conn = db.connect(chemin_base)
            try:
                with db.transaction(conn):
                    conn.execute(
                        "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
                        "VALUES ('doc-041', 'devis', 'DEV-2026-041.pdf', 'application/pdf', 1, 'h', 1, "
                        "'email', 'EXTRAIT', '2026-11-25T00:00:00Z')"
                    )
                    premiere = extraction.persister(conn, "doc-041", payload)
                    seconde = extraction.persister(conn, "doc-041", payload)
                self.assertLess(premiere, seconde)
                self.assertEqual(controls._champ_extrait(conn, "doc-041", "client.name"),
                                 "Ets Sossa Materiaux")
                self.assertIsNone(controls._champ_extrait(conn, "doc-041", "client.ifu"))
                motif = conn.execute(
                    "SELECT missing FROM extracted_fields WHERE extraction=? AND chemin='client.ifu'",
                    (seconde,),
                ).fetchone()[0]
                self.assertEqual(motif, ABSENT)
                totaux = conn.execute("SELECT * FROM document_totals WHERE document='doc-041'").fetchone()
                self.assertEqual(totaux["printed_ht"], 1_020_000)
                self.assertEqual(totaux["printed_ttc"], 1_203_600)
                prix = conn.execute(
                    "SELECT valeur_normalisee, page, bbox FROM extracted_fields "
                    "WHERE extraction=? AND chemin='lines[1].unit_price_ht'", (seconde,),
                ).fetchone()
                self.assertEqual(prix["valeur_normalisee"], "120000")
                self.assertEqual(len(json.loads(prix["bbox"])), 4)
            finally:
                conn.close()


class TestConfiance(unittest.TestCase):
    """Signaux « modèle » et « cohérence » : voir docs/CONFIANCE.md."""

    CLIENTS = [
        {"id": "cli-1", "raison_sociale": "Maison Hounsa Boot en Bois", "ifu": "9934368630"},
        {"id": "cli-2", "raison_sociale": "Ets Sossa Materiaux", "ifu": None},
    ]

    def test_nom_identique_au_referentiel(self) -> None:
        nom, ifu, _ = llm._coherence_client("Maison Hounsa Boot en Bois", "9934368630", self.CLIENTS)
        self.assertEqual((nom, ifu), (llm.COHERENCE_CONNUE, llm.COHERENCE_CONNUE))

    def test_nom_presque_identique_est_suspect(self) -> None:
        """« Malson » pour « Maison » : une lecture fautive, pas un nouveau client."""
        nom, _, diagnostic = llm._coherence_client("Malson Hounsa Boot en Bols", None, self.CLIENTS)
        self.assertEqual(nom, llm.COHERENCE_PRESQUE)
        self.assertEqual(diagnostic["nom"], "presque_identique")

    def test_nom_inconnu_est_un_client_nouveau_possible(self) -> None:
        nom, _, _ = llm._coherence_client("Quincaillerie du Port", None, self.CLIENTS)
        self.assertEqual(nom, llm.COHERENCE_NOUVELLE)

    def test_ifu_d_un_client_nom_d_un_autre(self) -> None:
        nom, ifu, _ = llm._coherence_client("Ets Sossa Materiaux", "9934368630", self.CLIENTS)
        self.assertEqual((nom, ifu), (llm.COHERENCE_CONTRADICTION, llm.COHERENCE_CONTRADICTION))

    def test_sans_referentiel_le_signal_reste_neutre(self) -> None:
        nom, _, diagnostic = llm._coherence_client("Malson Hounsa", None, None)
        self.assertEqual(nom, llm.COHERENCE_SANS_REFERENTIEL)
        self.assertFalse(diagnostic["referentiel"])

    def test_un_nom_suspect_part_en_revue_meme_avec_un_ocr_sur(self) -> None:
        """OCR parfait, libellé net : la cohérence suffit à passer sous le seuil."""
        confiance = extraction.combinee_confiance(1.0, llm.MODELE_NET, llm.COHERENCE_PRESQUE)
        self.assertLess(confiance, extraction.seuil("client.name"))

    def test_modele_libelle_net_ou_tolerant(self) -> None:
        net = {"text": "Client : Ets Sossa", "words": [{"text": "Client"}, {"text": ":"}, {"text": "Ets"}]}
        tolerant = {"text": "Cllent : Ets Sossa", "words": [{"text": "Cllent"}, {"text": ":"}, {"text": "Ets"}]}
        self.assertEqual(llm._modele_libelle("client.name", net), llm.MODELE_NET)
        self.assertEqual(llm._modele_libelle("client.name", tolerant), llm.MODELE_TOLERANT)

    def test_modele_cellule(self) -> None:
        self.assertEqual(llm._modele_cellule(0.5, [{"text": "185"}], True), llm.MODELE_NET)
        self.assertAlmostEqual(llm._modele_cellule(llm.TOLERANCE_COLONNE, [{"text": "185"}], True),
                               llm.MODELE_POSITION_MIN)
        self.assertEqual(llm._modele_cellule(0.5, [{"text": "000", "lu": "OOO"}], True), llm.MODELE_CORRIGE)
        self.assertEqual(llm._modele_cellule(0.5, [{"text": "4"}], False), 0.85)

    def test_le_signal_modele_n_est_plus_constant(self) -> None:
        payload = extraction.extraire_piece(TestOCRReel.PDF)
        modeles = {round(payload["lines"][0][k]["confidence"], 4) for k in ("description", "unit_price_ht")}
        self.assertEqual(len(modeles), 2)  # texte libre et montant ne reçoivent plus le même signal


class TestMesures(unittest.TestCase):
    def test_parseur_sur_ocr_parfait(self) -> None:
        """Ablation : texte exact du générateur. Mesure le parseur seul, pas la lecture."""
        mesures = metrics.evaluer(ecrire=False, ocr_backend="rendu")
        self.assertEqual(mesures["documents"], 120)
        self.assertEqual(mesures["valeurs_inventees"], 0)
        self.assertGreaterEqual(mesures["exactitude_champs"], 0.95)
        self.assertGreaterEqual(mesures["lignes"]["f1"], 0.95)

    @unittest.skipUnless(_cache_complet(), "cache OCR incomplet : python -m adapters.ocr --warm")
    def test_chaine_reelle_reproductible_et_sans_invention(self) -> None:
        premier = metrics.evaluer(ecrire=False, ocr_backend="cache")
        second = metrics.evaluer(ecrire=False, ocr_backend="cache")
        self.assertEqual(premier, second)
        self.assertEqual(premier["documents"], 120)
        self.assertEqual(premier["valeurs_inventees"], 0)
        # Le seuil doit attraper toute valeur fausse ou absente (docs/CONFIANCE.md).
        self.assertEqual(premier["revue"]["erreurs_silencieuses"], 0)


if __name__ == "__main__":
    unittest.main()
