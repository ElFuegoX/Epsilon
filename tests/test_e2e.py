"""Jean-Marie avec Melon : parcours complet réel, du PDF source à l'avoir.

Le scénario rejoue DEV-2026-041 contre l'API FastAPI :
import du PDF → file `EN_ATTENTE_IA` → reprise worker → extraction →
IFU absent mais client connu → anomalies résolues → validation →
second clic 409 → PDF figé → émission → avoir → vérification de la chaîne.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed
from db import connect, initialize


class TestParcoursComplet(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        racine = Path(self.tmp.name)
        self.db_path = str(racine / "e2e.db")
        self.data_path = racine / "data"
        self.data_path.mkdir(parents=True, exist_ok=True)

        conn = lambda: connect(self.db_path)

        self.patches = [
            patch("api.routes._conn", side_effect=conn),
            patch("api.routes.data_dir", return_value=self.data_path),
            patch("db.data_dir", return_value=self.data_path),
            patch("worker.queue.data_dir", return_value=self.data_path),
            patch("domain.invoices.data_dir", return_value=self.data_path),
            patch("adapters.email_sim.data_dir", return_value=self.data_path),
            patch("adapters.whatsapp_sim.data_dir", return_value=self.data_path),
            patch("seed.RACINE", racine),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self._stop_patches)

        initialize(self.db_path)

        # On ne génère que la pièce témoin : même rendu que le corpus complet,
        # sans attendre les 120 pièces pour ce test de parcours.
        self.devis = racine / "DEV-2026-041.pdf"
        mesure = seed._mesure_pdf()
        lignes = seed._lignes_temoins()
        totaux = seed._totaux(lignes, "arithmetique")
        client = {"raison_sociale": "Ets Sossa Materiaux", "ifu": None}
        elements = (
            seed._entete("DEVIS", "DEV-2026-041", "2026-11-18", client, True, mesure)
            + seed._tableau(lignes, mesure, avec_livre=True)
            + seed._totaux_imprimes(totaux["printed"], ("ht", "vat", "ttc"), mesure)
        )
        seed._ecrire_piece(
            self.devis, elements, "pdf", random.Random(seed.settings.graine_demo),
            reference="DEV-2026-041", document_type="devis", split="dev",
        )
        self.assertTrue(self.devis.is_file())

    def _stop_patches(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_parcours_complet_et_reprise_worker(self) -> None:
        from fastapi.testclient import TestClient
        from api.app import create_app

        client = TestClient(create_app())
        dirigeant = {"X-Role": "dirigeant"}
        assistante = {"X-Role": "assistante"}
        lecture = {"X-Role": "lecture"}

        # 1. Santé et référentiel client : l'IFU vient du référentiel, pas de la pièce.
        self.assertEqual(client.get("/health").json()["status"], "ok")
        r_client = client.post(
            "/referentials/clients",
            json={
                "raison_sociale": "Ets Sossa Materiaux",
                "ifu": "123456789",
                "ville": "Cotonou",
                "conditions": "30J",
            },
            headers=dirigeant,
        )
        self.assertEqual(r_client.status_code, 200, r_client.text)

        # 2. Import du vrai PDF témoin : il part immédiatement en file.
        with self.devis.open("rb") as flux:
            r_doc = client.post(
                "/documents",
                files={"file": ("DEV-2026-041.pdf", flux, "application/pdf")},
                data={"canal": "demo", "type_piece": "devis"},
                headers=assistante,
            )
        self.assertEqual(r_doc.status_code, 200, r_doc.text)
        doc_id = r_doc.json()["id"]
        self.assertEqual(
            client.get("/documents", headers=lecture).json()["items"][0]["statut"],
            "EN_ATTENTE_IA",
        )

        # 2b. La pièce source immuable reste consultable par la visionneuse.
        r_source = client.get(f"/documents/{doc_id}/file", headers=lecture)
        self.assertEqual(r_source.status_code, 200, r_source.text)
        self.assertTrue(r_source.content.startswith(b"%PDF-"))
        self.assertEqual(
            client.get(f"/documents/{doc_id}", headers=lecture).json()["url"],
            f"/documents/{doc_id}/file",
        )

        # 3. Worker coupé puis relancé : une seule extraction, un seul brouillon.
        r_ext = client.post(f"/documents/{doc_id}/extract", headers=assistante)
        self.assertEqual(r_ext.status_code, 200, r_ext.text)
        draft_id = r_ext.json()["draft_id"]
        self.assertIsNotNone(draft_id)
        r_ext2 = client.post(f"/documents/{doc_id}/extract", headers=assistante)
        self.assertEqual(r_ext2.status_code, 200, r_ext2.text)
        self.assertEqual(r_ext2.json()["draft_id"], draft_id)
        conn = connect(self.db_path)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM invoice_drafts WHERE document=?", (doc_id,)
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

        # 4. provenance : IFU absent de la pièce, jamais inventé.
        document = client.get(f"/documents/{doc_id}", headers=lecture).json()
        champs = document["fields"]
        self.assertIsNone(champs["client_ifu"]["value"])
        self.assertEqual(champs["client_ifu"]["motif"], "ABSENT_DE_LA_PIECE")
        self.assertIn("bbox", champs["line_2_price"])

        # 5. Chiffres du devis témoin : imprimé / recalculé / écart.
        brouillon = client.get(f"/drafts/{draft_id}", headers=lecture).json()
        self.assertEqual(brouillon["client_detail"]["ifu"], "123456789")
        self.assertEqual(brouillon["printed_totals"]["ht"], 1_020_000)
        self.assertEqual(brouillon["recalculated_totals"]["ht"], 1_040_000)
        self.assertEqual(brouillon["recalculated_totals"]["ttc"], 1_227_200)
        self.assertEqual(brouillon["ecart"]["ht"], -20_000)

        # 6. Le message de clarification ne réclame pas l'IFU : il est connu du
        #    référentiel. Seules les conditions de paiement manquent encore.
        r_clar = client.post(
            f"/drafts/{draft_id}/clarification-message", headers=assistante
        )
        self.assertEqual(r_clar.status_code, 200, r_clar.text)
        self.assertIn("conditions de paiement", r_clar.json()["message"])
        self.assertNotIn("IFU", r_clar.json()["message"])

        # 7. Validation bloquée tant que les anomalies sont ouvertes.
        r_bloque = client.post(f"/drafts/{draft_id}/validate", headers=dirigeant)
        self.assertEqual(r_bloque.status_code, 422, r_bloque.text)
        anomalies = client.get(
            f"/drafts/{draft_id}/anomalies", headers=assistante
        ).json()["items"]
        self.assertTrue(any(a["status"] == "OUVERTE" for a in anomalies))
        for anomalie in anomalies:
            if anomalie["status"] == "OUVERTE":
                r_res = client.post(
                    f"/anomalies/{anomalie['id']}/resolve",
                    json={"justification": "Contrôle humain tracé"},
                    headers=assistante,
                )
                self.assertEqual(r_res.status_code, 200, r_res.text)

        # 8. Validation : numéro, snapshot, PDF figé.
        r_val = client.post(
            f"/drafts/{draft_id}/validate",
            headers={**dirigeant, "Idempotency-Key": "premier-clic"},
        )
        self.assertEqual(r_val.status_code, 200, r_val.text)
        facture = r_val.json()
        invoice_id = facture["invoice_id"]
        self.assertEqual(facture["numero"], "FAC-2026-00001")
        self.assertEqual(facture["totals"]["ttc"], 1_227_200)

        # 9. Second clic avec une autre clé : l'état figé renvoie 409, pas un 2e numéro.
        r_second = client.post(
            f"/drafts/{draft_id}/validate",
            headers={**dirigeant, "Idempotency-Key": "second-clic"},
        )
        self.assertEqual(r_second.status_code, 409, r_second.text)

        r_pdf = client.get(f"/invoices/{invoice_id}/pdf", headers=lecture)
        self.assertEqual(r_pdf.status_code, 200)
        self.assertTrue(r_pdf.content.startswith(b"%PDF-"))

        # 10. Émission simulée puis avoir total, sans toucher à la facture.
        r_issue = client.post(
            f"/invoices/{invoice_id}/issue",
            json={"channel": "email_sim"},
            headers=assistante,
        )
        self.assertEqual(r_issue.status_code, 200, r_issue.text)
        self.assertEqual(r_issue.json()["statut"], "ÉMIS")

        r_avoir = client.post(
            f"/invoices/{invoice_id}/credit-notes",
            json={"motif": "Erreur de livraison", "total": True},
            headers=dirigeant,
        )
        self.assertEqual(r_avoir.status_code, 200, r_avoir.text)
        self.assertTrue(r_avoir.json()["numero"].startswith("AV-2026-"))
        self.assertEqual(r_avoir.json()["solde"], 0)

        # 11. Chaîne d'audit vérifiable après toutes les écritures.
        r_audit = client.get("/audit/verify", headers=lecture)
        self.assertEqual(r_audit.status_code, 200, r_audit.text)
        self.assertTrue(r_audit.json()["valid"])
        self.assertGreater(r_audit.json()["events"], 0)


if __name__ == "__main__":
    unittest.main()
