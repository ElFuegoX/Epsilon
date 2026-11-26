"""Maillon extraction → brouillon : rien d'inventé, tout ce qui est douteux se confirme."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import db
from adapters import ocr
from domain import brouillon, extraction
from domain.invoices import refresh_anomalies

RACINE = Path(__file__).resolve().parents[1]
GENERE = RACINE / "seeds" / "generated"
DEV_041 = GENERE / "demo" / "devis" / "DEV-2026-041.pdf"
CMD_114 = GENERE / "demo" / "photos" / "CMD-2026-114.png"


def _en_cache(chemin: Path) -> bool:
    return chemin.is_file() and (ocr.CACHE / f"{ocr.empreinte_contenu(chemin)}.json").is_file()


class BaseBrouillon(unittest.TestCase):
    def setUp(self) -> None:
        self.dossier = tempfile.TemporaryDirectory()
        chemin = str(Path(self.dossier.name) / "wema.db")
        db.initialize(chemin)
        self.conn = db.connect(chemin)
        clients = json.loads((GENERE / "clients.json").read_text(encoding="utf-8"))
        articles = json.loads((GENERE / "items.json").read_text(encoding="utf-8"))
        with db.transaction(self.conn):
            self.conn.executemany(
                "INSERT INTO clients(id, raison_sociale, ifu, ville) VALUES (?, ?, ?, ?)",
                [(c["id"], c["raison_sociale"], c["ifu"], c["ville"]) for c in clients])
            self.conn.executemany(
                "INSERT INTO items(id, reference, designation, unite, prix_catalogue, famille) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(a["id"], a["reference"], a["designation"], a["unite"], a["prix_catalogue"], a["famille"])
                 for a in articles])
        self.clients = extraction.clients_depuis_base(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.dossier.cleanup()

    def piece(self, document_id: str, chemin: Path) -> dict:
        payload = extraction.extraire_piece(chemin, ocr_backend="cache", clients=self.clients)
        with db.transaction(self.conn):
            self.conn.execute(
                "INSERT INTO documents(id, type, nom, mime, taille, hash, pages, canal, statut, cree_le) "
                "VALUES (?, ?, ?, 'application/pdf', 1, ?, 1, 'email', 'EXTRAIT', '2026-11-25T00:00:00Z')",
                (document_id, payload["document_type"], chemin.name, document_id))
            extraction.persister(self.conn, document_id, payload)
        return payload


class TestDevisTemoin(BaseBrouillon):
    def setUp(self) -> None:
        super().setUp()
        self.payload = self.piece("doc-041", DEV_041)
        self.resultat = brouillon.creer_brouillon(self.conn, "doc-041", self.payload)
        self.draft = self.resultat["draft_id"]

    def test_brouillon_au_statut_brouillon_avec_ses_lignes(self) -> None:
        self.assertEqual(self.resultat["statut"], "BROUILLON")
        self.assertEqual(self.resultat["lignes"], 3)
        lignes = self.conn.execute(
            "SELECT numero, quantite, pu_ht, tax_code FROM draft_lines WHERE draft=? ORDER BY numero",
            (self.draft,)).fetchall()
        self.assertEqual([tuple(l) for l in lignes],
                         [(1, "4", 185000, "TVA18"), (2, "2", 120000, "TVA18"), (3, "1", 60000, "TVA18")])

    def test_rien_n_est_invente(self) -> None:
        draft = self.conn.execute("SELECT * FROM invoice_drafts WHERE id=?", (self.draft,)).fetchone()
        self.assertIsNone(draft["date_echeance"])  # absente de la pièce : pas calculée
        self.assertEqual(draft["date_piece"], "2026-11-18")

    def test_livraisons_reportees(self) -> None:
        livre = dict(self.conn.execute(
            "SELECT numero, quantite_livree FROM deliveries WHERE draft=?", (self.draft,)).fetchall())
        self.assertEqual(livre, {1: "4", 2: "2", 3: "0"})

    def test_les_controles_de_larissa_voient_les_trois_anomalies(self) -> None:
        with db.transaction(self.conn):
            codes = {a.code for a in refresh_anomalies(self.conn, self.draft)}
        self.assertTrue({"MISSING_MANDATORY", "QUANTITY_MISMATCH", "ARITHMETIC_MISMATCH"} <= codes)

    def test_idempotent(self) -> None:
        second = brouillon.creer_brouillon(self.conn, "doc-041", self.payload)
        self.assertTrue(second["deja_existant"])
        self.assertEqual(second["draft_id"], self.draft)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoice_drafts").fetchone()[0], 1)

    def test_total_contradictoire_a_confirmer_puis_validation_permise(self) -> None:
        with self.assertRaises(brouillon.ConfirmationsEnAttente) as erreur:
            brouillon.exiger_confirmations(self.conn, self.draft)
        self.assertIn("totals.printed_ht", [e["chemin"] for e in erreur.exception.en_attente])
        brouillon.confirmer(self.conn, self.draft, "totals.printed_ht", "dirigeant",
                            motif="total imprimé faux, l'écart est traité par ARITHMETIC_MISMATCH")
        brouillon.exiger_confirmations(self.conn, self.draft)  # plus rien en attente
        evenement = self.conn.execute(
            "SELECT action FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
        self.assertEqual(evenement["action"], "VALEUR_CONFIRMEE")

    def test_confirmation_sans_acteur_refusee(self) -> None:
        with self.assertRaises(brouillon.BrouillonError):
            brouillon.confirmer(self.conn, self.draft, "totals.printed_ht", "")

    def test_brouillon_fige_refuse_toute_confirmation(self) -> None:
        with db.transaction(self.conn):
            self.conn.execute("UPDATE invoice_drafts SET statut='VALIDÉ' WHERE id=?", (self.draft,))
        with self.assertRaises(brouillon.BrouillonError):
            brouillon.confirmer(self.conn, self.draft, "totals.printed_ht", "dirigeant")


class TestLigneIncomplete(BaseBrouillon):
    def test_ligne_sans_quantite_ni_total_n_est_pas_creee_puis_completee(self) -> None:
        payload = copy.deepcopy(self.piece("doc-041", DEV_041))
        for nom in ("quantity", "line_total_ht"):
            payload["lines"][0][nom] = extraction.champ(None, None, absent=True)
        resultat = brouillon.creer_brouillon(self.conn, "doc-041", payload)
        self.assertEqual(resultat["lignes"], 2)
        attente = [e for e in brouillon.a_confirmer(self.conn, resultat["draft_id"])
                   if e["type"] == brouillon.LIGNE_INCOMPLETE]
        self.assertEqual(attente[0]["details"]["manquants"], ["quantity", "line_total_ht"])
        self.assertEqual(attente[0]["priorite"], "HAUTE")
        brouillon.completer_ligne(self.conn, resultat["draft_id"], 1,
                                  {"quantity": "4", "line_total_ht": 740000}, "assistante",
                                  motif="lu sur la pièce")
        self.assertEqual(brouillon.resume(self.conn, resultat["draft_id"])["lignes"], 3)


@unittest.skipUnless(_en_cache(CMD_114), "photo absente du cache OCR")
class TestPhoto(BaseBrouillon):
    def test_quantites_non_lues_deduites_et_a_confirmer(self) -> None:
        resultat = brouillon.creer_brouillon(self.conn, "doc-114", self.piece("doc-114", CMD_114))
        deduites = {e["chemin"]: e for e in brouillon.a_confirmer(self.conn, resultat["draft_id"])
                    if e["type"] == brouillon.VALEUR_DEDUITE}
        self.assertEqual(deduites["lines[0].quantity"]["details"]["valeur"], "4")
        self.assertEqual(deduites["lines[1].quantity"]["details"]["valeur"], "1")
        self.assertTrue(all(e["priorite"] == "HAUTE" for e in deduites.values()))
        # un total non imprimé n'a rien à confirmer
        chemins = [e["chemin"] for e in brouillon.a_confirmer(self.conn, resultat["draft_id"])]
        self.assertNotIn("totals.printed_ttc", chemins)

    def test_correction_humaine_met_a_jour_la_ligne(self) -> None:
        resultat = brouillon.creer_brouillon(self.conn, "doc-114", self.piece("doc-114", CMD_114))
        brouillon.confirmer(self.conn, resultat["draft_id"], "lines[0].quantity", "assistante",
                            motif="relu sur la photo", corrige="5")
        quantite = self.conn.execute(
            "SELECT quantite FROM draft_lines WHERE draft=? AND numero=1", (resultat["draft_id"],)
        ).fetchone()[0]
        self.assertEqual(quantite, "5")


if __name__ == "__main__":
    unittest.main()
