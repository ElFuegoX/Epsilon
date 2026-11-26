"""Tests de validation, immutabilité, idempotence et avoirs — piste Larissa.

Référence : docs/RECETTE.md R10 à R12, docs/DECISIONS.md
(idempotence lue dans la transaction, snapshot immuable, avoirs bornés par
ligne et par le cumul TTC, aucune quantité ni confiance inventée).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from typing import Any, Mapping

from config import settings
from domain.controls import Resolution, build_context
from domain.extraction import canonical
from domain.invoices import (
    AnomaliesBloquantes,
    AvoirRefuse,
    EtatInvalide,
    ValidationError,
    add_payment,
    bornes_avoir,
    construire_snapshot,
    create_credit_note,
    issue_invoice,
    refresh_anomalies,
    validate_draft,
    verifier_pdf,
)

LIGNES = (
    (1, "Banquette 3 places", "4", 185_000),
    (2, "Table basse chêne", "2", 120_000),
    (3, "Livraison et installation", "1", 60_000),
)
HT, TVA, TTC = 1_040_000, 187_200, 1_227_200


def _pdf(snapshot: Mapping[str, Any], numero: str, destination: Path) -> None:
    """Générateur de test déterministe, injecté à la place de adapters.pdf."""
    chemin = Path(destination)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(canonical(snapshot), encoding="utf-8")


def _hash(destination: Path) -> str:
    return hashlib.sha256(Path(destination).read_bytes()).hexdigest()


PDF = (_pdf, _hash)


def base() -> sqlite3.Connection:
    """Base conforme : chaque contrôle peut passer sans décision supplémentaire."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(Path("schema.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO tax_codes(code, libelle, taux_bp, exoneration) VALUES ('TVA18','TVA 18',1800,0)"
    )
    conn.execute(
        "INSERT INTO clients(id, raison_sociale, ifu) VALUES ('c1','Ets Sossa Materiaux','123456789')"
    )
    conn.execute(
        "INSERT INTO documents(id, type, nom, mime, taille, hash, statut, cree_le) "
        "VALUES ('doc1','devis','devis.pdf','application/pdf',100,'abc','IMPORTE',"
        "'2026-11-25T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO extractions(id, document, modele, version, date, brut_json) "
        "VALUES ('ex1','doc1','demo','1','2026-11-25T00:00:00Z','{}')"
    )
    conn.execute(
        "INSERT INTO extracted_fields(id, extraction, chemin, valeur, confiance) "
        "VALUES ('f1','ex1','client.ifu','123456789',0.99)"
    )
    conn.execute(
        "INSERT INTO invoice_drafts(id, document, client, date_piece, date_echeance, "
        "conditions, statut, cree_le, modifie_le) VALUES "
        "('d1','doc1','c1','2026-11-18','2026-12-18','30 jours','BROUILLON',"
        "'2026-11-25T00:00:00Z','2026-11-25T00:00:00Z')"
    )
    for numero, description, quantite, pu in LIGNES:
        conn.execute(
            "INSERT INTO draft_lines(id, draft, numero, description, quantite, unite, pu_ht, "
            "tax_code, total_ht, item, famille) VALUES (?, 'd1', ?, ?, ?, 'pcs', ?, 'TVA18', ?, "
            "'i1','MOB')",
            (f"l{numero}", numero, description, quantite, pu, int(quantite) * pu),
        )
        conn.execute(
            "INSERT INTO deliveries(id, draft, numero, quantite_livree) VALUES (?, 'd1', ?, ?)",
            (f"liv{numero}", numero, quantite),
        )
    for prefixe in (settings.prefixe_facture, settings.prefixe_avoir):
        conn.execute(
            "INSERT INTO number_sequences(serie, annee, prefixe, prochaine, version) "
            "VALUES (?, ?, ?, 1, 0)",
            (settings.serie_defaut, settings.annee, prefixe),
        )
    return conn


def valider(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str | None = None,
    resolutions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_draft(
        conn,
        "d1",
        "larissa",
        idempotency_key=idempotency_key,
        resolutions=resolutions,
        generateur_pdf=PDF,
    )


def prochaine(conn: sqlite3.Connection, prefixe: str) -> int:
    return int(conn.execute(
        "SELECT prochaine FROM number_sequences WHERE serie=? AND annee=? AND prefixe=?",
        (settings.serie_defaut, settings.annee, prefixe),
    ).fetchone()["prochaine"])


class TestValidation(unittest.TestCase):
    def test_validation_nominale(self) -> None:
        conn = base()
        resultat = valider(conn, idempotency_key="cle-1")
        self.assertEqual(resultat["numero"], "FAC-2026-00001")
        self.assertEqual(resultat["statut"], "VALIDÉ")
        self.assertEqual(
            (resultat["total_ht"], resultat["total_tva"], resultat["total_ttc"]),
            (HT, TVA, TTC),
        )
        invoice = conn.execute(
            "SELECT * FROM invoices WHERE id=?", (resultat["invoice_id"],)
        ).fetchone()
        self.assertEqual(invoice["client"], "c1")
        self.assertEqual(invoice["total_ttc"], TTC)
        self.assertEqual(
            invoice["hash_snapshot"],
            hashlib.sha256(invoice["snapshot"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            conn.execute("SELECT statut FROM invoice_drafts WHERE id='d1'").fetchone()["statut"],
            "VALIDÉ",
        )
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 2)
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_events ORDER BY sequence"
        )]
        self.assertEqual(actions, ["VALIDATION_BROUILLON", "NUMERO_ATTRIBUE", "PDF_GENERE"])

    def test_idempotence_meme_cle(self) -> None:
        conn = base()
        premier = valider(conn, idempotency_key="meme-cle")
        second = valider(conn, idempotency_key="meme-cle")
        self.assertEqual(premier, second)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 3)

    def test_cle_par_defaut_idempotente(self) -> None:
        conn = base()
        self.assertEqual(
            validate_draft(conn, "d1", generateur_pdf=PDF),
            validate_draft(conn, "d1", generateur_pdf=PDF),
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)

    def test_cle_differente_apres_validation_refusee(self) -> None:
        conn = base()
        valider(conn, idempotency_key="a")
        with self.assertRaises(EtatInvalide):
            valider(conn, idempotency_key="b")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 2)

    def test_anomalie_bloquante_sans_numero_consomme(self) -> None:
        conn = base()
        conn.execute("DELETE FROM deliveries WHERE numero=1")
        with self.assertRaises(AnomaliesBloquantes) as attire:
            valider(conn, idempotency_key="bloque")
        self.assertTrue(any(a.code == "QUANTITY_MISMATCH" for a in attire.exception.anomalies))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0], 0)

    def test_anomalie_resolue_acceptee_et_tracée(self) -> None:
        conn = base()
        conn.execute("UPDATE deliveries SET quantite_livree='3' WHERE numero=1")
        trace = Resolution("larissa", "livraison partielle justifiée", "4", "3")
        resultat = valider(
            conn,
            idempotency_key="resolue",
            resolutions={"QUANTITY_MISMATCH:ligne 1": trace},
        )
        self.assertEqual(resultat["numero"], "FAC-2026-00001")
        anomalie = conn.execute(
            "SELECT * FROM anomalies WHERE code='QUANTITY_MISMATCH' AND champ='ligne 1'"
        ).fetchone()
        self.assertEqual(anomalie["severite"], "BLOQUANT")
        self.assertEqual(anomalie["statut"], "RESOLUE")
        self.assertEqual(json.loads(anomalie["resolution"])["motif"], "livraison partielle justifiée")
        self.assertEqual(anomalie["avant"], "4")
        self.assertEqual(anomalie["apres"], "3")

    def test_resolution_relue_sans_reprendre_la_trace(self) -> None:
        conn = base()
        conn.execute("UPDATE deliveries SET quantite_livree='3' WHERE numero=1")
        trace = Resolution("larissa", "justificatif joint", "4", "3")
        refresh_anomalies(conn, "d1", resolutions={"QUANTITY_MISMATCH:ligne 1": trace})
        anomalies = refresh_anomalies(conn, "d1")
        cible = next(a for a in anomalies if a.code == "QUANTITY_MISMATCH")
        self.assertEqual(cible.statut, "RESOLUE")
        self.assertEqual(cible.acteur, "larissa")
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM anomalies WHERE statut='RESOLUE'"
        ).fetchone()[0], 1)

    def test_code_fiscal_inconnu_bloque_sans_defaut(self) -> None:
        conn = base()
        conn.execute("UPDATE draft_lines SET tax_code='TVA_MAJ' WHERE numero=1")
        with self.assertRaises(AnomaliesBloquantes) as attire:
            valider(conn, idempotency_key="taxe")
        self.assertTrue(any(a.code == "INVALID_TAX" for a in attire.exception.anomalies))
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 1)

    def test_pdf_de_melon_indisponible_sans_injection(self) -> None:
        # adapters/pdf.py existe désormais : on simule un générateur absent pour garder
        # la garantie « PDF indisponible → aucune facture, aucun numéro consommé ».
        import sys
        import types
        from unittest import mock

        conn = base()
        vide = types.ModuleType("pdf_absent")
        with mock.patch.dict(sys.modules, {"adapters.pdf": vide}), \
                mock.patch("adapters.pdf", vide, create=True), \
                self.assertRaises(EtatInvalide) as attire:
            validate_draft(conn, "d1", "larissa", idempotency_key="sans-pdf")
        self.assertIn("TODO Melon", str(attire.exception))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 0)
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 1)

    def test_snapshot_conforme(self) -> None:
        conn = base()
        ctx = build_context(conn, "d1")
        draft = conn.execute("SELECT * FROM invoice_drafts WHERE id='d1'").fetchone()
        assert ctx.calcule is not None
        snap = construire_snapshot(dict(draft), ctx.lignes, ctx.calcule, ctx.client, "FAC-2026-00001")
        self.assertEqual(snap["numero"], "FAC-2026-00001")
        self.assertEqual(snap["devise"], settings.devise)
        self.assertEqual(snap["as_of"], settings.as_of)
        self.assertEqual(snap["calcul"]["total_ttc"], TTC)
        self.assertEqual(snap["client"]["ifu"], "123456789")
        self.assertTrue(snap["mention"].startswith("SIMULATION"))


class TestImmutabilite(unittest.TestCase):
    def _facture(self) -> tuple[sqlite3.Connection, str]:
        conn = base()
        resultat = valider(conn, idempotency_key="immuable")
        return conn, resultat["invoice_id"]

    def test_champs_fiscaux_non_modifiables(self) -> None:
        conn, identifiant = self._facture()
        for champ, valeur in (
            ("total_ht", 1), ("total_tva", 1), ("total_ttc", 1), ("client", "c2"),
            ("date", "2026-01-01"), ("snapshot", "{}"), ("hash_snapshot", "x"),
            ("hash_pdf", "x"), ("numero", "FAC-2026-00009"),
        ):
            with self.subTest(champ=champ):
                with self.assertRaises(sqlite3.IntegrityError) as attire:
                    conn.execute(
                        f"UPDATE invoices SET {champ}=? WHERE id=?", (valeur, identifiant)
                    )
                self.assertIn("INVOICE_IMMUTABLE", str(attire.exception))

    def test_suppression_refusee(self) -> None:
        conn, identifiant = self._facture()
        with self.assertRaises(sqlite3.IntegrityError) as attire:
            conn.execute("DELETE FROM invoices WHERE id=?", (identifiant,))
        self.assertIn("INVOICE_IMMUTABLE", str(attire.exception))

    def test_emission_ne_change_que_statut_canal_et_reference(self) -> None:
        conn, identifiant = self._facture()
        avant = conn.execute("SELECT * FROM invoices WHERE id=?", (identifiant,)).fetchone()
        apres = issue_invoice(conn, identifiant, "email_sim", "larissa")
        self.assertEqual(apres["statut"], "ÉMIS")
        self.assertEqual(apres["canal"], "email_sim")
        self.assertEqual(apres["mecef_ref"], f"SIM-FAC-2026-00001-{settings.as_of.replace('-', '')}")
        self.assertEqual(apres["total_ttc"], avant["total_ttc"])
        self.assertEqual(apres["snapshot"], avant["snapshot"])
        self.assertEqual(apres["hash_pdf"], avant["hash_pdf"])
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE invoices SET total_ttc=1 WHERE id=?", (identifiant,))

    def test_verification_pdf_depuis_snapshot(self) -> None:
        conn, identifiant = self._facture()
        self.assertTrue(verifier_pdf(conn, identifiant, generateur_pdf=PDF))


class TestAvoirs(unittest.TestCase):
    def _facture(self) -> tuple[sqlite3.Connection, str]:
        conn = base()
        resultat = valider(conn, idempotency_key="avoir")
        return conn, resultat["invoice_id"]

    def test_avoir_partiel(self) -> None:
        conn, identifiant = self._facture()
        resultat = create_credit_note(
            conn, identifiant,
            [{"numero": 2, "description": "Table basse chêne", "quantite": "1", "pu_ht": 120_000}],
            "réclamation", "larissa",
        )
        self.assertEqual(resultat["numero"], "AV-2026-00001")
        self.assertEqual(resultat["total_ttc"], 141_600)
        self.assertEqual(resultat["solde"], 1_085_600)
        avoir = conn.execute("SELECT * FROM credit_notes WHERE id=?", (resultat["credit_note_id"],)).fetchone()
        self.assertEqual(avoir["facture"], identifiant)
        self.assertEqual(avoir["motif"], "réclamation")
        self.assertEqual(
            conn.execute("SELECT statut FROM invoices WHERE id=?", (identifiant,)).fetchone()["statut"],
            "VALIDÉ",
        )
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 2)
        self.assertEqual(prochaine(conn, settings.prefixe_facture), 2)

    def test_avoir_total_annule_sans_supprimer(self) -> None:
        conn, identifiant = self._facture()
        lignes = [
            {"numero": numero, "description": description, "quantite": quantite, "pu_ht": pu}
            for numero, description, quantite, pu in LIGNES
        ]
        resultat = create_credit_note(conn, identifiant, lignes, "annulation", "larissa", total=True)
        self.assertEqual(resultat["total_ttc"], TTC)
        self.assertEqual(resultat["solde"], 0)
        self.assertEqual(
            conn.execute("SELECT statut FROM invoices WHERE id=?", (identifiant,)).fetchone()["statut"],
            "ANNULÉ_PAR_AVOIR",
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)

    def test_avoir_idempotent(self) -> None:
        conn, identifiant = self._facture()
        lignes = [{"numero": 2, "description": "Table basse chêne", "quantite": "1", "pu_ht": 120_000}]
        self.assertEqual(
            create_credit_note(conn, identifiant, lignes, "motif", "larissa"),
            create_credit_note(conn, identifiant, lignes, "motif", "larissa"),
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM credit_notes").fetchone()[0], 1)
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 2)

    def test_avoir_herite_du_code_fiscal(self) -> None:
        conn, identifiant = self._facture()
        resultat = create_credit_note(
            conn, identifiant,
            [{"numero": 2, "description": "Table basse chêne", "quantite": "1", "pu_ht": 120_000}],
            "motif", "larissa",
        )
        self.assertEqual(resultat["total_ttc"], 141_600)

    def test_avoir_quantite_superieure_refuse_avant_ecriture(self) -> None:
        conn, identifiant = self._facture()
        with self.assertRaises(AvoirRefuse) as attire:
            create_credit_note(
                conn, identifiant,
                [{"numero": 2, "description": "Table basse chêne", "quantite": "3", "pu_ht": 120_000}],
                "motif", "larissa",
            )
        self.assertIn("supérieure à la ligne 2", str(attire.exception))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM credit_notes").fetchone()[0], 0)
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 1)

    def test_avoir_ligne_absente_refuse(self) -> None:
        conn, identifiant = self._facture()
        with self.assertRaises(AvoirRefuse) as attire:
            create_credit_note(
                conn, identifiant,
                [{"numero": 9, "description": "Inconnue", "quantite": "1", "pu_ht": 1_000}],
                "motif", "larissa",
            )
        self.assertIn("absente de la facture", str(attire.exception))
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 1)

    def test_cumul_par_ligne_refuse(self) -> None:
        conn, identifiant = self._facture()
        with self.assertRaises(AvoirRefuse) as attire:
            create_credit_note(
                conn, identifiant,
                [{"numero": 2, "description": "Table basse chêne", "quantite": "2", "pu_ht": 120_000}],
                "motif", "larissa", avoirs_precedents={2: "1"},
            )
        self.assertIn("cumul des avoirs 3 supérieur à la ligne 2 (2)", str(attire.exception))
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 1)

    def test_cumul_ttc_refuse(self) -> None:
        conn, identifiant = self._facture()
        create_credit_note(
            conn, identifiant,
            [{"numero": 1, "description": "Banquette 3 places", "quantite": "4", "pu_ht": 185_000}],
            "motif 1", "larissa", idempotency_key="k1",
        )
        create_credit_note(
            conn, identifiant,
            [{"numero": 2, "description": "Table basse chêne", "quantite": "2", "pu_ht": 120_000}],
            "motif 2", "larissa", idempotency_key="k2",
        )
        with self.assertRaises(AvoirRefuse) as attire:
            create_credit_note(
                conn, identifiant,
                [{"numero": 2, "description": "Table basse chêne", "quantite": "1", "pu_ht": 120_000}],
                "motif 3", "larissa", idempotency_key="k3",
            )
        self.assertIn(f"cumul des avoirs 1298000 FCFA supérieur au TTC {TTC} FCFA", str(attire.exception))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM credit_notes").fetchone()[0], 2)
        self.assertEqual(prochaine(conn, settings.prefixe_avoir), 3)

    def test_quantite_flottante_refusee(self) -> None:
        with self.assertRaises(ValidationError):
            bornes_avoir({1: {"quantite": "4"}}, [{"numero": 1, "quantite": 1.5}])
        with self.assertRaises(ValidationError):
            bornes_avoir({1: {"quantite": "4"}}, [{"numero": 1, "quantite": True}])


class TestPaiements(unittest.TestCase):
    def test_paiement_dans_le_net(self) -> None:
        conn = base()
        resultat = valider(conn, idempotency_key="paiement")
        paiement = add_payment(conn, resultat["invoice_id"], 500_000, "virement_sim", "REF-1", "assistante")
        self.assertEqual(paiement["solde"], 727_200)

    def test_paiement_excedentaire_refuse(self) -> None:
        conn = base()
        resultat = valider(conn, idempotency_key="paiement")
        with self.assertRaises(ValidationError):
            add_payment(conn, resultat["invoice_id"], TTC + 1, "virement_sim", "REF-2", "assistante")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 0)

    def test_net_reduit_par_avoir(self) -> None:
        conn = base()
        resultat = valider(conn, idempotency_key="paiement")
        create_credit_note(
            conn, resultat["invoice_id"],
            [{"numero": 2, "description": "Table basse chêne", "quantite": "1", "pu_ht": 120_000}],
            "réclamation", "larissa", idempotency_key="av",
        )
        with self.assertRaises(ValidationError):
            add_payment(conn, resultat["invoice_id"], 1_085_601, "virement_sim", "REF-3", "assistante")
        paiement = add_payment(conn, resultat["invoice_id"], 1_085_600, "virement_sim", "REF-4", "assistante")
        self.assertEqual(paiement["solde"], 0)


if __name__ == "__main__":
    unittest.main()
