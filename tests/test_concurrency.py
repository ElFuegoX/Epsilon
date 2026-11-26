"""Tests Melon : concurrence à la validation, idempotence worker et protection d'accès."""

from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path

from config import horodatage, settings
from db import connect, initialize, new_id, transaction
from domain.documents import DuplicateDocument
from domain.invoices import EtatInvalide, validate_draft
from domain.numbering import verifier_continuite
from worker.queue import enqueue_document, ingerer_document, process_document


def _seed_valid_draft(db_path: str) -> str:
    """Crée un client complet (avec IFU) et un brouillon sans anomalie bloquante."""
    conn = connect(db_path)
    try:
        cid = new_id("cli")
        did = new_id("drf")
        lid = new_id("lin")
        now = horodatage()
        with transaction(conn):
            conn.execute(
                "INSERT INTO clients(id, raison_sociale, ifu, adresse, ville, telephone, conditions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, "Menuiserie Kora", "3202600001234", "Akpakpa", "Cotonou", "+22901020304", "30J"),
            )
            conn.execute(
                "INSERT INTO invoice_drafts("
                "id, document, client, date_piece, date_echeance, conditions, version, statut, cree_le, modifie_le"
                ") VALUES (?, NULL, ?, ?, ?, ?, 1, 'BROUILLON', ?, ?)",
                (did, cid, settings.as_of, "2026-12-25", "30J", now, now),
            )
            conn.execute(
                "INSERT INTO draft_lines("
                "id, draft, numero, description, quantite, unite, pu_ht, remise, remise_pct, tax_code, total_ht, item, famille"
                ") VALUES (?, ?, 1, ?, '2', 'pcs', 120000, 0, 0, 'TVA18', 240000, NULL, 'MOBILIER')",
                (lid, did, "Table basse chêne"),
            )
            conn.execute(
                "INSERT INTO deliveries(id, draft, numero, quantite_livree, decision, motif) "
                "VALUES (?, ?, 1, '2', 'CONFORME', 'BL vérifié')",
                (new_id("del"), did),
            )
        return did
    finally:
        conn.close()


class TestConcurrencyAndIdempotency(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.db_path = str(Path(self.tmpdir.name) / "test_conc.db")
        initialize(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_two_concurrent_validations_same_key_produce_one_invoice(self) -> None:
        draft_id = _seed_valid_draft(self.db_path)
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[Exception] = []

        def _worker() -> None:
            conn = connect(self.db_path)
            try:
                barrier.wait(timeout=5)
                res = validate_draft(conn, draft_id, acteur="dirigeant", idempotency_key="same-click-key")
                results.append(res)
            except Exception as exc:
                errors.append(exc)
            finally:
                conn.close()

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Soit les deux renvoient la même facture (idempotence), soit le 2e reçoit EtatInvalide
        self.assertGreaterEqual(len(results), 1)
        for err in errors:
            self.assertIsInstance(err, EtatInvalide)
        if len(results) == 2:
            self.assertEqual(results[0]["numero"], results[1]["numero"])
            self.assertEqual(results[0]["invoice_id"], results[1]["invoice_id"])

        conn = connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM invoices").fetchone()["c"]
            self.assertEqual(count, 1)
            ok, errs = verifier_continuite(conn)
            self.assertTrue(ok, errs)
        finally:
            conn.close()

    def test_worker_restart_is_idempotent_and_deduplicates_imports(self) -> None:
        sample = Path(self.tmpdir.name) / "message_whatsapp.txt"
        sample.write_text("Bonjour, merci de nous livrer 4 banquettes.", encoding="utf-8")

        conn = connect(self.db_path)
        try:
            with transaction(conn):
                doc = ingerer_document(conn, sample, canal="whatsapp_sim")
            # Un second import du même fichier est bloqué par hash unique
            with self.assertRaises(DuplicateDocument):
                with transaction(conn):
                    ingerer_document(conn, sample, canal="whatsapp_sim")

            enqueue_document(conn, doc["id"])
            first = process_document(conn, doc["id"])
            # Simulation d'une coupure puis relance du worker sur le même document
            second = process_document(conn, doc["id"])

            self.assertEqual(first["statut"], "EXTRAIT")
            self.assertTrue(second["reused"])
            self.assertEqual(first["draft_id"], second["draft_id"])
            draft_count = conn.execute("SELECT COUNT(*) AS c FROM invoice_drafts WHERE document=?", (doc["id"],)).fetchone()["c"]
            self.assertEqual(draft_count, 1)
        finally:
            conn.close()


class TestApiEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "api_test.db")
        self.data_path = Path(self.tmpdir.name) / "data"
        self.data_path.mkdir(parents=True, exist_ok=True)
        initialize(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_api_roles_dedup_validation_immutability_and_audit(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from api.app import create_app

        db_path = self.db_path
        data_path = self.data_path

        def _test_conn():
            return connect(db_path)

        with (
            patch("api.routes._conn", side_effect=_test_conn),
            patch("api.routes.data_dir", return_value=data_path),
            patch("db.data_dir", return_value=data_path),
            patch("worker.queue.data_dir", return_value=data_path),
            patch("domain.invoices.data_dir", return_value=data_path),
            patch("adapters.email_sim.data_dir", return_value=data_path),
            patch("adapters.whatsapp_sim.data_dir", return_value=data_path),
        ):
            client = TestClient(create_app())

            # 1. Health
            r = client.get("/health")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "ok")

            # 2. Contrôle d'accès par rôle
            r_forbid = client.post(
                "/documents",
                json={"nom": "cmd_1.txt", "texte": "Commande 4 banquettes"},
                headers={"X-Role": "lecture"},
            )
            self.assertEqual(r_forbid.status_code, 403)

            r_cli_forbid = client.post(
                "/referentials/clients",
                json={"raison_sociale": "Client Interdit", "ifu": "3202600009999"},
                headers={"X-Role": "assistante"},
            )
            self.assertEqual(r_cli_forbid.status_code, 403)

            # 3. Création client (dirigeant) + import document + doublon refusé en 409
            r_cli = client.post(
                "/referentials/clients",
                json={"raison_sociale": "Ets Sossa", "ifu": "3202600001111", "conditions": "30J"},
                headers={"X-Role": "dirigeant"},
            )
            self.assertEqual(r_cli.status_code, 200)
            client_id = r_cli.json()["id"]

            r_doc = client.post(
                "/documents",
                json={"nom": "cmd_sossa.txt", "texte": "Bonjour, 2 tables basses"},
                headers={"X-Role": "assistante"},
            )
            self.assertEqual(r_doc.status_code, 200)
            doc_id = r_doc.json()["id"]

            r_dup = client.post(
                "/documents",
                json={"nom": "cmd_sossa_copie.txt", "texte": "Bonjour, 2 tables basses"},
                headers={"X-Role": "assistante"},
            )
            self.assertEqual(r_dup.status_code, 409)

            # 4. Extraction -> brouillon -> édition -> message clarification
            r_ext = client.post(f"/documents/{doc_id}/extract", headers={"X-Role": "assistante"})
            self.assertEqual(r_ext.status_code, 200)
            draft_id = r_ext.json()["draft_id"]
            self.assertIsNotNone(draft_id)

            r_clar = client.post(f"/drafts/{draft_id}/clarification-message", headers={"X-Role": "assistante"})
            self.assertEqual(r_clar.status_code, 200)
            self.assertIn("message", r_clar.json())

            # Validation refusée tant qu'il y a des anomalies bloquantes (422)
            r_val_blocked = client.post(f"/drafts/{draft_id}/validate", headers={"X-Role": "dirigeant"})
            self.assertEqual(r_val_blocked.status_code, 422)

            # Compléter le brouillon et ajouter une ligne
            r_patch = client.patch(
                f"/drafts/{draft_id}",
                json={"client": client_id, "date_piece": "2026-11-25", "date_echeance": "2026-12-25", "conditions": "30J"},
                headers={"X-Role": "assistante"},
            )
            self.assertEqual(r_patch.status_code, 200)

            r_line = client.post(
                f"/drafts/{draft_id}/lines",
                json={"description": "Table basse", "quantite": 2, "unite": "pcs", "pu_ht": 120000, "tax_code": "TVA18", "famille": "MOBILIER"},
                headers={"X-Role": "assistante"},
            )
            self.assertEqual(r_line.status_code, 200)

            # Résoudre l'anomalie de livraison inconnue (traçabilité humaine)
            r_anos = client.get(f"/drafts/{draft_id}/anomalies", headers={"X-Role": "assistante"})
            self.assertEqual(r_anos.status_code, 200)
            for ano in r_anos.json()["items"]:
                if ano["status"] != "RESOLUE":
                    r_res = client.post(
                        f"/anomalies/{ano['id']}/resolve",
                        json={"justification": "Livraison confirmée par BL papier"},
                        headers={"X-Role": "assistante"},
                    )
                    self.assertEqual(r_res.status_code, 200)

            # Assistante ne peut pas valider (403)
            r_val_forbid = client.post(f"/drafts/{draft_id}/validate", headers={"X-Role": "assistante"})
            self.assertEqual(r_val_forbid.status_code, 403)

            # Dirigeant valide -> facture créée + PDF + numéro
            r_val = client.post(f"/drafts/{draft_id}/validate", headers={"X-Role": "dirigeant"})
            self.assertEqual(r_val.status_code, 200, r_val.text)
            inv_id = r_val.json()["invoice_id"]
            self.assertEqual(r_val.json()["numero"], "FAC-2026-00001")

            # Immutabilité : modification ou suppression d'une facture -> 409
            self.assertEqual(client.patch(f"/invoices/{inv_id}", headers={"X-Role": "dirigeant"}).status_code, 409)
            self.assertEqual(client.delete(f"/invoices/{inv_id}", headers={"X-Role": "dirigeant"}).status_code, 409)

            # Émission simulée + avoir total lié
            r_issue = client.post(f"/invoices/{inv_id}/issue", json={"channel": "whatsapp"}, headers={"X-Role": "assistante"})
            self.assertEqual(r_issue.status_code, 200)
            self.assertEqual(r_issue.json()["statut"], "ÉMIS")

            r_av = client.post(
                f"/invoices/{inv_id}/credit-notes",
                json={"motif": "Erreur de livraison", "total": True},
                headers={"X-Role": "dirigeant"},
            )
            self.assertEqual(r_av.status_code, 200)
            self.assertEqual(r_av.json()["solde"], 0)

            # Chaîne d'audit intègre
            r_ver = client.get("/audit/verify", headers={"X-Role": "lecture"})
            self.assertEqual(r_ver.status_code, 200)
            self.assertTrue(r_ver.json()["valid"])


if __name__ == "__main__":
    unittest.main()
