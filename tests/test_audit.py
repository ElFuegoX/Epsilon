"""Tests Melon : chaîne d'audit SHA-256, détection d'altération, export CSV, PDF déterministe."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from adapters.pdf import build_invoice_pdf, hash_file
from cli import cmd_verify
from db import connect, initialize, transaction
from domain.audit import append_event, exporter_csv, verifier_chaine


class TestAuditChain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test_audit.db")
        initialize(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_chain_intact_and_tamper_detected(self) -> None:
        conn = connect(self.db_path)
        try:
            with transaction(conn):
                append_event(conn, "assistante", "IMPORT_DOCUMENT", None, {"id": "doc_1"})
                append_event(conn, "worker", "EXTRACTION_TERMINEE", {"id": "doc_1"}, {"draft": "drf_1"})
                append_event(conn, "dirigeant", "VALIDATION_BROUILLON", {"statut": "BROUILLON"}, {"statut": "VALIDÉ"})

            ok, errors = verifier_chaine(conn)
            self.assertTrue(ok)
            self.assertEqual(errors, [])
            self.assertEqual(cmd_verify(self.db_path), 0)

            # Altération malveillante d'un événement passé
            conn.execute("UPDATE audit_events SET acteur='intrus' WHERE sequence=2")
            ok_after, errors_after = verifier_chaine(conn)
            self.assertFalse(ok_after)
            self.assertEqual(len(errors_after), 1)
            self.assertIn("sequence 2", errors_after[0])
            self.assertEqual(cmd_verify(self.db_path), 1)
        finally:
            conn.close()

    def test_export_csv_contains_all_events(self) -> None:
        conn = connect(self.db_path)
        try:
            with transaction(conn):
                append_event(conn, "assistante", "IMPORT_DOCUMENT", None, {"id": "doc_a"})
                append_event(conn, "dirigeant", "VALIDATION_BROUILLON", None, {"numero": "FAC-2026-00001"})
            csv_text = exporter_csv(conn)
            lines = [l for l in csv_text.strip().splitlines() if l]
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[0].startswith("sequence,acteur,action,avant,apres,horodatage,hash"))
            self.assertIn("IMPORT_DOCUMENT", lines[1])
            self.assertIn("VALIDATION_BROUILLON", lines[2])
        finally:
            conn.close()

    def test_pdf_generation_is_deterministic(self) -> None:
        snapshot = {
            "numero": "FAC-2026-00001",
            "date": "2026-11-25",
            "echeance": "2026-12-25",
            "conditions": "30J",
            "devise": "XOF",
            "client": {"raison_sociale": "Ets Sossa", "ifu": "1234567890123", "adresse": "Cotonou"},
            "lignes": [{"description": "Table basse", "quantite": "2", "unite": "pcs", "pu_ht": 120000, "tax_code": "TVA18"}],
            "calcul": {"total_ht": 240000, "total_tva": 43200, "total_ttc": 283200},
            "mention": "SIMULATION — document de démonstration",
        }
        p1 = Path(self.tmpdir.name) / "f1.pdf"
        p2 = Path(self.tmpdir.name) / "f2.pdf"
        build_invoice_pdf(snapshot, "FAC-2026-00001", p1)
        build_invoice_pdf(snapshot, "FAC-2026-00001", p2)
        self.assertTrue(p1.is_file())
        self.assertGreater(p1.stat().st_size, 100)
        self.assertEqual(hash_file(p1), hash_file(p2))


if __name__ == "__main__":
    unittest.main()
