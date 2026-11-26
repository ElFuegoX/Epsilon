"""Parcours complet de bout en bout : les 4 gestes du jury, la reprise, les rôles."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db
from adapters import ocr
from domain import audit, brouillon, invoices, parcours

RACINE = Path(__file__).resolve().parents[1]
GENERE = RACINE / "seeds" / "generated"
DEV_041 = GENERE / "demo" / "devis" / "DEV-2026-041.pdf"
CMD_114 = GENERE / "demo" / "photos" / "CMD-2026-114.png"


class BaseParcours(unittest.TestCase):
    def setUp(self) -> None:
        self.dossier = tempfile.TemporaryDirectory()
        chemin = str(Path(self.dossier.name) / "wema.db")
        db.initialize(chemin)
        self.conn = db.connect(chemin)
        with db.transaction(self.conn):
            for c in json.loads((GENERE / "clients.json").read_text(encoding="utf-8")):
                self.conn.execute(
                    "INSERT INTO clients(id, raison_sociale, ifu, adresse, ville, telephone, conditions) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (c["id"], c["raison_sociale"], c["ifu"], c["adresse"], c["ville"], c["telephone"],
                     c["conditions"]))
            for a in json.loads((GENERE / "items.json").read_text(encoding="utf-8")):
                self.conn.execute(
                    "INSERT INTO items(id, reference, designation, unite, prix_catalogue, famille) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (a["id"], a["reference"], a["designation"], a["unite"], a["prix_catalogue"], a["famille"]))

    def tearDown(self) -> None:
        self.conn.close()
        self.dossier.cleanup()

    def statut_piece(self, document_id: str) -> str:
        return self.conn.execute("SELECT statut FROM documents WHERE id=?", (document_id,)).fetchone()[0]


class TestParcoursDevisTemoin(BaseParcours):
    """DEV-2026-041 : IFU absent, total imprimé faux, installation non livrée."""

    def preparer(self) -> tuple[str, str]:
        document = parcours.importer(self.conn, DEV_041)["document_id"]
        draft = parcours.extraire(self.conn, document)["draft_id"]
        return document, draft

    def rendre_validable(self, draft: str) -> None:
        brouillon.confirmer(self.conn, draft, "totals.printed_ht", "dirigeant",
                            motif="total imprimé faux : écart traité par ARITHMETIC_MISMATCH")
        parcours.renseigner_ifu(self.conn, "cli-001", "3201912345678", role="dirigeant",
                                motif="réponse au message de clarification")
        parcours.modifier_brouillon(self.conn, draft, role="assistante", date_echeance="2026-12-25",
                                    motif="échéance confirmée par le client")
        parcours.exclure_ligne(self.conn, draft, 3, role="assistante",
                               motif="installation non livrée : facturée après pose")
        parcours.resoudre(self.conn, draft, "ARITHMETIC_MISMATCH", role="dirigeant",
                          motif="addition fausse sur le devis", avant="1 020 000 imprimé",
                          apres="980 000 recalculé")

    def test_geste_1_import_double_une_seule_piece(self) -> None:
        premier = parcours.importer(self.conn, DEV_041)
        second = parcours.importer(self.conn, DEV_041)
        self.assertFalse(premier["doublon"])
        self.assertTrue(second["doublon"])
        self.assertEqual(second["document_id"], premier["document_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_anomalies_et_message_de_clarification(self) -> None:
        _, draft = self.preparer()
        codes = {a["code"] for a in parcours.controler(self.conn, draft)}
        self.assertTrue({"MISSING_MANDATORY", "QUANTITY_MISMATCH", "ARITHMETIC_MISMATCH"} <= codes)
        message = parcours.message_clarification(self.conn, draft)
        self.assertIn("DEV-2026-041", message)
        self.assertIn("IFU", message)
        self.assertNotRegex(message, r"\d{10}")  # aucune valeur proposée

    def test_brouillon_exportable_en_pdf(self) -> None:
        _, draft = self.preparer()
        apercu = parcours.apercu_pdf(self.conn, draft)
        self.assertTrue(Path(apercu["chemin"]).is_file())

    def test_validation_refusee_tant_que_rien_n_est_confirme_ni_resolu(self) -> None:
        _, draft = self.preparer()
        with self.assertRaises(brouillon.ConfirmationsEnAttente):
            parcours.valider(self.conn, draft)
        brouillon.confirmer(self.conn, draft, "totals.printed_ht", "dirigeant", motif="vu")
        with self.assertRaises(invoices.AnomaliesBloquantes):
            parcours.valider(self.conn, draft)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)

    def test_parcours_complet_gestes_2_3_4(self) -> None:
        document, draft = self.preparer()
        self.rendre_validable(draft)

        # Geste 2 : double validation -> une seule facture, un seul numéro.
        premier = parcours.valider(self.conn, draft)
        second = parcours.valider(self.conn, draft)
        self.assertEqual(premier, second)
        self.assertEqual(premier["numero"], "FAC-2026-00001")
        self.assertEqual((premier["total_ht"], premier["total_tva"], premier["total_ttc"]),
                         (980_000, 176_400, 1_156_400))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)
        self.assertTrue(invoices.verifier_pdf(self.conn, premier["invoice_id"]))
        self.assertEqual(self.statut_piece(document), "VALIDÉ")

        # Geste 3 : une facture validée ne se modifie pas.
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE invoices SET total_ttc=1 WHERE id=?", (premier["invoice_id"],))
        with self.assertRaises(invoices.EtatInvalide):
            parcours.modifier_brouillon(self.conn, draft, role="dirigeant", date_echeance="2027-01-01",
                                        motif="tentative après validation")

        # Émission simulée.
        emission = parcours.emettre(self.conn, premier["invoice_id"], "whatsapp_sim", role="assistante")
        self.assertEqual(emission["facture"]["statut"], "ÉMIS")
        self.assertTrue(Path(emission["message"]["fichier"]).is_file())
        self.assertTrue(emission["message"]["simulation"])
        self.assertEqual(self.statut_piece(document), "ÉMIS")

        # Geste 4 : avoir total -> facture conservée, solde nul, numérotation continue.
        avoir = parcours.avoir(self.conn, premier["invoice_id"], motif="annulation demandée", total=True)
        self.assertEqual(avoir["numero"], "AV-2026-00001")
        self.assertEqual(avoir["solde"], 0)
        statut = self.conn.execute("SELECT statut FROM invoices WHERE id=?", (premier["invoice_id"],)).fetchone()[0]
        self.assertEqual(statut, "ANNULÉ_PAR_AVOIR")
        self.assertEqual(self.statut_piece(document), "ANNULÉ_PAR_AVOIR")

        # Journal d'audit intact.
        valide, erreurs = audit.verifier_chaine(self.conn)
        self.assertTrue(valide, erreurs)

    def test_roles(self) -> None:
        _, draft = self.preparer()
        with self.assertRaises(parcours.AccesRefuse):
            parcours.importer(self.conn, CMD_114, role="lecture")
        with self.assertRaises(parcours.AccesRefuse):
            parcours.valider(self.conn, draft, role="assistante")
        with self.assertRaises(parcours.AccesRefuse):
            parcours.renseigner_ifu(self.conn, "cli-001", "1", role="assistante", motif="x")
        with self.assertRaises(parcours.AccesRefuse):
            parcours.resoudre(self.conn, draft, "UNUSUAL_PRICE", role="assistante", motif="x", avant="a", apres="b")


@unittest.skipUnless((ocr.CACHE / f"{ocr.empreinte_contenu(CMD_114)}.json").is_file() if CMD_114.is_file() else False,
                     "photo absente du cache OCR")
class TestReprise(BaseParcours):
    def test_coupure_ocr_puis_reprise_sans_doublon(self) -> None:
        document = parcours.importer(self.conn, CMD_114)["document_id"]
        with mock.patch("adapters.ocr.lire_pages", side_effect=ocr.OCRIndisponible("service coupé")):
            resultat = parcours.extraire(self.conn, document)
        self.assertEqual(resultat["statut"], "EN_ATTENTE_IA")
        self.assertEqual(self.statut_piece(document), "EN_ATTENTE_IA")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0], 0)

        repris = parcours.reprendre(self.conn)
        self.assertEqual([r["statut"] for r in repris], ["EXTRAIT"])
        self.assertEqual(parcours.reprendre(self.conn), [])  # rien à refaire
        parcours.extraire(self.conn, document)                # relance manuelle : sans effet
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoice_drafts").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
