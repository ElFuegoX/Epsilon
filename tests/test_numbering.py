"""Tests de numérotation — piste Larissa.

Référence : docs/RECETTE.md R10, docs/DECISIONS.md
(garde de transaction, continuité factures et avoirs, aucun numéro consommé
après échec).
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from config import settings
from domain.numbering import (
    SequenceInvalide,
    TransactionRequise,
    apercu,
    formatter,
    reserver,
    verifier_continuite,
)


def base() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(Path("schema.sql").read_text(encoding="utf-8"))
    for prefixe in (settings.prefixe_facture, settings.prefixe_avoir):
        conn.execute(
            "INSERT INTO number_sequences(serie, annee, prefixe, prochaine, version) "
            "VALUES (?, ?, ?, 1, 0)",
            (settings.serie_defaut, settings.annee, prefixe),
        )
    return conn


def inserer_facture(conn: sqlite3.Connection, numero: str, annee: int = 2026) -> None:
    conn.execute(
        "INSERT INTO invoices(id, numero, serie, annee, snapshot, hash_snapshot, hash_pdf, "
        "date, statut, total_ht, total_tva, total_ttc) VALUES (?, ?, 'FAC', ?, '{}', 'h', 'h', "
        "'2026-11-25', 'VALIDÉ', 0, 0, 0)",
        (f"inv_{numero}", numero, annee),
    )


def inserer_avoir(conn: sqlite3.Connection, numero: str, annee: int = 2026) -> None:
    conn.execute(
        "INSERT INTO credit_notes(id, numero, serie, annee, facture, motif, total_ht, "
        "total_tva, total_ttc, statut, cree_le) VALUES (?, ?, ?, ?, 'inv', 'motif', 0, 0, 0, "
        "'EMIS', '2026-11-25T00:00:00Z')",
        (f"av_{numero}", numero, settings.serie_defaut, annee),
    )


class TestFormat(unittest.TestCase):
    def test_formats_fiscaux(self) -> None:
        self.assertEqual(formatter("FAC", 2026, 1), "FAC-2026-00001")
        self.assertEqual(formatter("AV", 2026, 12), "AV-2026-00012")
        self.assertEqual(formatter("FAC", 2026, 123456), "FAC-2026-123456")

    def test_format_invalide(self) -> None:
        for prefixe, annee, valeur in (("", 2026, 1), ("FAC", 999, 1), ("FAC", 2026, 0)):
            with self.assertRaises(ValueError):
                formatter(prefixe, annee, valeur)


class TestTransaction(unittest.TestCase):
    def test_reserver_hors_transaction_refuse(self) -> None:
        conn = base()
        with self.assertRaises(TransactionRequise):
            reserver(conn)

    def test_apercu_hors_transaction_autorise(self) -> None:
        conn = base()
        self.assertEqual(apercu(conn), "FAC-2026-00001")

    def test_apercu_ne_consomme_pas(self) -> None:
        conn = base()
        avant = conn.execute("SELECT prochaine FROM number_sequences").fetchall()
        self.assertEqual(apercu(conn), "FAC-2026-00001")
        self.assertEqual(apercu(conn), "FAC-2026-00001")
        apres = conn.execute("SELECT prochaine FROM number_sequences").fetchall()
        self.assertEqual([dict(r) for r in avant], [dict(r) for r in apres])

    def test_rollback_ne_consomme_pas(self) -> None:
        conn = base()
        self.assertEqual(apercu(conn), "FAC-2026-00001")
        conn.execute("BEGIN IMMEDIATE")
        numero = reserver(conn)
        self.assertEqual(numero, "FAC-2026-00001")
        self.assertEqual(apercu(conn), "FAC-2026-00002")
        conn.execute("ROLLBACK")
        self.assertEqual(apercu(conn), "FAC-2026-00001")

    def test_compteur_incohérent_refuse(self) -> None:
        conn = base()
        conn.execute("UPDATE number_sequences SET prochaine=0 WHERE prefixe='FAC'")
        conn.execute("BEGIN IMMEDIATE")
        with self.assertRaises(SequenceInvalide):
            reserver(conn)
        conn.execute("ROLLBACK")


class TestContinuite(unittest.TestCase):
    def test_series_independantes(self) -> None:
        conn = base()
        conn.execute("BEGIN IMMEDIATE")
        self.assertEqual(reserver(conn), "FAC-2026-00001")
        self.assertEqual(reserver(conn), "FAC-2026-00002")
        self.assertEqual(reserver(conn, prefixe=settings.prefixe_avoir), "AV-2026-00001")
        conn.execute("COMMIT")
        self.assertEqual(apercu(conn), "FAC-2026-00003")
        self.assertEqual(apercu(conn, prefixe=settings.prefixe_avoir), "AV-2026-00002")

    def test_version_incrementee(self) -> None:
        conn = base()
        conn.execute("BEGIN IMMEDIATE")
        reserver(conn)
        reserver(conn)
        conn.execute("COMMIT")
        version = conn.execute(
            "SELECT version FROM number_sequences WHERE prefixe='FAC'"
        ).fetchone()["version"]
        self.assertEqual(version, 2)

    def test_annee_differente_a_sa_propre_sequence(self) -> None:
        conn = base()
        conn.execute("BEGIN IMMEDIATE")
        self.assertEqual(reserver(conn, annee=2027), "FAC-2027-00001")
        conn.execute("COMMIT")
        self.assertEqual(apercu(conn), "FAC-2026-00001")
        self.assertEqual(apercu(conn, annee=2027), "FAC-2027-00002")

    def test_continuite_factures_et_avoirs(self) -> None:
        conn = base()
        inserer_facture(conn, "FAC-2026-00001")
        inserer_avoir(conn, "AV-2026-00001")
        conn.execute("BEGIN IMMEDIATE")
        reserver(conn)
        reserver(conn, prefixe=settings.prefixe_avoir)
        conn.execute("COMMIT")
        valide, erreurs = verifier_continuite(conn)
        self.assertTrue(valide, erreurs)
        self.assertEqual(erreurs, [])

    def test_trou_detecte(self) -> None:
        conn = base()
        inserer_facture(conn, "FAC-2026-00002")
        conn.execute("UPDATE number_sequences SET prochaine=3 WHERE prefixe='FAC'")
        valide, erreurs = verifier_continuite(conn)
        self.assertFalse(valide)
        self.assertTrue(any("ordre invalide" in e for e in erreurs))

    def test_derive_sequence_detectee(self) -> None:
        conn = base()
        inserer_facture(conn, "FAC-2026-00001")
        valide, erreurs = verifier_continuite(conn)
        self.assertFalse(valide)
        self.assertTrue(any("séquence à 1, attendu 2" in e for e in erreurs))

    def test_avoir_sans_facture_est_detecte(self) -> None:
        conn = base()
        inserer_avoir(conn, "AV-2026-00002")
        conn.execute("UPDATE number_sequences SET prochaine=3 WHERE prefixe='AV'")
        valide, erreurs = verifier_continuite(conn)
        self.assertFalse(valide)
        self.assertTrue(any("AV:" in e for e in erreurs))

    def test_unicite_sql_empêche_le_doublon(self) -> None:
        conn = base()
        inserer_facture(conn, "FAC-2026-00001")
        with self.assertRaises(sqlite3.IntegrityError):
            inserer_facture(conn, "FAC-2026-00001", 2026)


if __name__ == "__main__":
    unittest.main()
