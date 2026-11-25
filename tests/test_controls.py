"""Tests des neuf contrôles — piste Larissa.

Référence : docs/RECETTE.md R2 à R9, docs/DECISIONS.md
(traçabilité des résolutions, taux obligatoire, livraison absente).
"""

from __future__ import annotations

import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path

from domain.audit import verifier_chaine
from domain.controls import (
    Anomalie,
    ContexteControle,
    Resolution,
    bloquant,
    build_context,
    run_controls,
)
from domain.documents import (
    A_COMPLETER,
    ANNULE_PAR_AVOIR,
    BROUILLON,
    CONTROLE,
    EMIS,
    EN_ATTENTE_IA,
    ETATS,
    EXTRAIT,
    IMPORTE,
    REJETE,
    TERMINAUX,
    VALIDE,
    DecisionDoublon,
    DocumentError,
    DuplicateDocument,
    TransitionInterdite,
    appliquer_transition,
    decider_doublon,
    exiger_pas_de_doublon,
    transitions_possibles,
    verifier_transition,
)
from domain.matching import (
    NIVEAUX_RATTACHEMENT_AUTO,
    compare_quantites,
    match_client,
    match_item,
)
from domain.tax import CodeFiscal, calculer, lignes_depuis_dict

REFERENTIEL = {
    "TVA18": CodeFiscal("TVA18", 1800),
    "TVA0": CodeFiscal("TVA0", 0, exoneration=True),
}

DEV_LIGNES = (
    {"description": "Banquette 3 places", "quantite": "4", "pu_ht": 185_000, "tax_code": "TVA18"},
    {"description": "Table basse chêne", "quantite": "2", "pu_ht": 120_000, "tax_code": "TVA18"},
    {"description": "Livraison et installation", "quantite": "1", "pu_ht": 60_000, "tax_code": "TVA18"},
)


def contexte(**surcharges: object) -> ContexteControle:
    """Contexte conforme par défaut : chaque test ne change que ce qu'il cible."""
    valeurs: dict[str, object] = dict(
        draft={
            "client": "c1",
            "date_piece": "2026-11-18",
            "date_echeance": "2026-12-18",
            "conditions": "30 jours",
        },
        client={"id": "c1", "raison_sociale": "Ets Sossa Materiaux", "ifu": "123456789"},
        client_match={"client_id": "c1", "niveau": "C1", "confiance": 1.0},
        lignes=[{
            "numero": 1,
            "description": "Banquette 3 places",
            "quantite": "4",
            "pu_ht": 185_000,
            "tax_code": "TVA18",
            "item": "i1",
            "famille": "MOB",
        }],
        livree={1: "4"},
        referentiel_fiscal=REFERENTIEL,
        taux_connus=tuple(REFERENTIEL),
        prix_ref={"i1": 185_000, "MOB": 185_000},
    )
    valeurs.update(surcharges)
    return ContexteControle(**valeurs)  # type: ignore[arg-type]


def codes(anomalies: list[object]) -> set[str]:
    return {a.code for a in anomalies}  # type: ignore[attr-defined]


class TestDossierConforme(unittest.TestCase):
    def test_aucune_anomalie(self) -> None:
        anomalies = run_controls(contexte())
        self.assertEqual(anomalies, [])
        self.assertFalse(bloquant(anomalies))


class TestMissingMandatory(unittest.TestCase):
    def test_ifu_absent_sans_valeur_proposee(self) -> None:
        ctx = contexte(client={"id": "c1", "raison_sociale": "Ets Sossa Materiaux", "ifu": None})
        anomalies = run_controls(ctx)
        cibles = [a for a in anomalies if a.code == "MISSING_MANDATORY"]
        self.assertEqual(len(cibles), 1)
        self.assertEqual(cibles[0].severite, "BLOQUANT")
        self.assertIn("IFU client", cibles[0].champ)
        self.assertIn("Aucune valeur n'a été proposée", cibles[0].message)
        self.assertTrue(bloquant(anomalies))

    def test_echeance_absente(self) -> None:
        draft = dict(contexte().draft)
        draft["date_echeance"] = None
        anomalies = run_controls(contexte(draft=draft))
        cible = next(a for a in anomalies if a.code == "MISSING_MANDATORY")
        self.assertIn("échéance", cible.champ)


class TestUnknownClient(unittest.TestCase):
    def test_niveau_c4_bloque(self) -> None:
        ctx = contexte(client_match={"niveau": "C4", "confiance": 0.50, "candidats": ["c1", "c2"]})
        anomalies = run_controls(ctx)
        self.assertTrue(any(a.code == "UNKNOWN_CLIENT" and a.severite == "BLOQUANT" for a in anomalies))

    def test_niveau_c5_bloque_meme_si_ligne_client_existe(self) -> None:
        ctx = contexte(client_match={"niveau": "C5", "confiance": 0.0})
        self.assertTrue(any(a.code == "UNKNOWN_CLIENT" for a in run_controls(ctx)))

    def test_niveau_c3_reste_a_confirmer(self) -> None:
        ctx = contexte(client_match={"niveau": "C3", "confiance": 0.80})
        self.assertTrue(any(a.code == "UNKNOWN_CLIENT" for a in run_controls(ctx)))


class TestUnknownItem(unittest.TestCase):
    def test_avertissement_seul_ne_bloque_pas(self) -> None:
        lignes = [dict(contexte().lignes[0])]
        lignes[0].update(item=None, famille=None, description="Banquette sur mesure")
        anomalies = run_controls(contexte(lignes=lignes))
        cibles = [a for a in anomalies if a.code == "UNKNOWN_ITEM"]
        self.assertEqual(len(cibles), 1)
        self.assertEqual(cibles[0].severite, "AVERTISSEMENT")
        self.assertFalse(bloquant(anomalies))
        self.assertIn("Banquette sur mesure", cibles[0].message)


class TestUnusualPrice(unittest.TestCase):
    def test_seuil_strictement_superieur(self) -> None:
        a_dix = contexte(lignes=[dict(contexte().lignes[0], pu_ht=132_000)], prix_ref={"i1": 120_000, "MOB": 120_000})
        self.assertNotIn("UNUSUAL_PRICE", codes(run_controls(a_dix)))
        a_onze = contexte(lignes=[dict(contexte().lignes[0], pu_ht=133_200)], prix_ref={"i1": 120_000, "MOB": 120_000})
        cibles = [a for a in run_controls(a_onze) if a.code == "UNUSUAL_PRICE"]
        self.assertEqual(len(cibles), 1)
        self.assertEqual(cibles[0].severite, "AVERTISSEMENT")
        self.assertIn("+11 %", cibles[0].message)

    def test_validation_dirigeant_au_delà_du_seuil(self) -> None:
        ctx = contexte(
            lignes=[dict(contexte().lignes[0], pu_ht=1_050_000)],
            prix_ref={"i1": 900_000, "MOB": 900_000},
        )
        cible = next(a for a in run_controls(ctx) if a.code == "UNUSUAL_PRICE")
        self.assertIn("Validation du dirigeant", cible.message)


class TestDoublons(unittest.TestCase):
    def test_doublon_document(self) -> None:
        anomalies = run_controls(contexte(doublon_document=True))
        self.assertTrue(any(a.code == "DUPLICATE_DOCUMENT" and a.severite == "BLOQUANT" for a in anomalies))

    def test_doublon_facture_empreinte(self) -> None:
        anomalies = run_controls(contexte(doublon_facture=True))
        self.assertTrue(any(a.code == "DUPLICATE_INVOICE" for a in anomalies))

    def test_doublon_facture_a_plus_moins_trois_jours(self) -> None:
        ctx = contexte(doublons_proches=("FAC-2026-00001",))
        cibles = [a for a in run_controls(ctx) if a.code == "DUPLICATE_INVOICE"]
        self.assertEqual(len(cibles), 1)
        self.assertIn("FAC-2026-00001", cibles[0].message)
        self.assertIn("±3 jours", cibles[0].message)


class TestQuantites(unittest.TestCase):
    def test_livraison_inconnue_bloque(self) -> None:
        ctx = contexte(livree={})
        cibles = [a for a in run_controls(ctx) if a.code == "QUANTITY_MISMATCH"]
        self.assertEqual(len(cibles), 1)
        self.assertEqual(cibles[0].severite, "BLOQUANT")
        self.assertIn("Aucune quantité n'est supposée", cibles[0].message)

    def test_livraison_inferieure_bloque(self) -> None:
        ctx = contexte(livree={1: "0"})
        cible = next(a for a in run_controls(ctx) if a.code == "QUANTITY_MISMATCH")
        self.assertIn("4 facturée(s), 0 livrée(s)", cible.message)

    def test_livraison_superieure_est_avertissement(self) -> None:
        ctx = contexte(livree={1: "6"})
        cible = next(a for a in run_controls(ctx) if a.code == "QUANTITY_MISMATCH")
        self.assertEqual(cible.severite, "AVERTISSEMENT")
        self.assertIn("sous-facturation", cible.message)

    def test_livraison_conforme(self) -> None:
        self.assertNotIn("QUANTITY_MISMATCH", codes(run_controls(contexte())))


class TestArithmetique(unittest.TestCase):
    def test_ecarts_imprimes_sont_bloquants(self) -> None:
        calcule = calculer(
            lignes_depuis_dict(DEV_LIGNES, referentiel=REFERENTIEL),
            imprime={"ht": 1_020_000, "vat": 183_600, "ttc": 1_203_600},
            referentiel=REFERENTIEL,
        )
        anomalies = run_controls(contexte(calcule=calcule))
        cibles = [a for a in anomalies if a.code == "ARITHMETIC_MISMATCH"]
        self.assertEqual({a.champ for a in cibles}, {"totaux.ht", "totaux.vat", "totaux.ttc"})
        self.assertTrue(all(a.severite == "BLOQUANT" for a in cibles))


class TestInvalidTax(unittest.TestCase):
    def test_code_hors_referentiel(self) -> None:
        ctx = contexte(lignes=[dict(contexte().lignes[0], tax_code="TVA_MAJ")])
        cible = next(a for a in run_controls(ctx) if a.code == "INVALID_TAX")
        self.assertIn("absent du référentiel", cible.message)
        self.assertIn("aucun défaut 18 %", cible.resolution)

    def test_code_absent(self) -> None:
        ctx = contexte(lignes=[dict(contexte().lignes[0], tax_code="")])
        self.assertTrue(any(a.code == "INVALID_TAX" for a in run_controls(ctx)))

    def test_exoneration_non_justifiee(self) -> None:
        ctx = contexte(lignes=[dict(contexte().lignes[0], tax_code="TVA0", justification="")])
        cible = next(a for a in run_controls(ctx) if a.code == "INVALID_TAX")
        self.assertIn("exonéré sans justification", cible.message)

    def test_exoneration_justifiee(self) -> None:
        ctx = contexte(lignes=[dict(contexte().lignes[0], tax_code="TVA0", justification="exportation")])
        self.assertNotIn("INVALID_TAX", codes(run_controls(ctx)))

    def test_base_negative(self) -> None:
        ligne = {"numero": 1, "description": "x", "quantite": "1", "pu_ht": 10_000,
                 "remise": 12_000, "tax_code": "TVA18"}
        calcule = calculer(lignes_depuis_dict([ligne], referentiel=REFERENTIEL), referentiel=REFERENTIEL)
        ctx = contexte(lignes=[ligne], calcule=calcule, prix_ref={})
        cible = next(a for a in run_controls(ctx) if a.code == "INVALID_TAX")
        self.assertIn("Base TVA négative (-2000 FCFA)", cible.message)


class TestResolutionTracée(unittest.TestCase):
    def test_severite_preservee_et_trace_complete(self) -> None:
        trace = Resolution("larissa", "total corrigé et validé", "183600", "187200")
        ctx = contexte(
            calcule=calculer(
                lignes_depuis_dict(DEV_LIGNES, referentiel=REFERENTIEL),
                imprime={"ht": 1_020_000, "vat": 183_600, "ttc": 1_203_600},
                referentiel=REFERENTIEL,
            ),
            resolus={"ARITHMETIC_MISMATCH": trace},
        )
        anomalies = run_controls(ctx)
        resolues = [a for a in anomalies if a.code == "ARITHMETIC_MISMATCH"]
        self.assertEqual(len(resolues), 3)
        self.assertTrue(all(a.severite == "BLOQUANT" for a in resolues))
        self.assertTrue(all(a.statut == "RESOLUE" for a in resolues))
        self.assertTrue(all(a.acteur == "larissa" and a.motif == "total corrigé et validé" for a in resolues))
        self.assertFalse(bloquant(anomalies))

    def test_resolution_incomplete_refusee(self) -> None:
        with self.assertRaises(ValueError):
            Resolution.depuis({"acteur": "larissa", "motif": "ok", "avant": "1"})
        # L'ancien format (codes seuls) ne prouve aucune résolution : il est ignoré.
        ancien = ContexteControle(draft={}, resolus=["ARITHMETIC_MISMATCH"])
        self.assertEqual(ancien.resolus, {})

    def test_resolution_par_ligne(self) -> None:
        lignes = [
            {"numero": 1, "description": "Banquette", "quantite": "4", "pu_ht": 185_000,
             "tax_code": "TVA18", "item": "i1", "famille": "MOB"},
            {"numero": 3, "description": "Installation", "quantite": "1", "pu_ht": 60_000,
             "tax_code": "TVA18", "item": "i3", "famille": "SERV"},
        ]
        ctx = contexte(
            lignes=lignes,
            livree={1: "4", 3: "0"},
            prix_ref={"i1": 185_000, "MOB": 185_000, "i3": 60_000, "SERV": 60_000},
            resolus={"QUANTITY_MISMATCH:ligne 3": Resolution(
                "larissa", "installation exclue", "1", "0"
            )},
        )
        anomalies = [a for a in run_controls(ctx) if a.code == "QUANTITY_MISMATCH"]
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].champ, "ligne 3")
        self.assertEqual(anomalies[0].statut, "RESOLUE")
        self.assertEqual(anomalies[0].severite, "BLOQUANT")


class TestBuildContextSqlite(unittest.TestCase):
    def _base(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
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
            "VALUES ('f1','ex1','client.name','Ets Sossa Materiaux',0.97)"
        )
        conn.execute(
            "INSERT INTO invoice_drafts(id, document, client, date_piece, date_echeance, "
            "conditions, statut, cree_le, modifie_le) VALUES "
            "('d1','doc1','c1','2026-11-18','2026-12-18','30 jours','BROUILLON',"
            "'2026-11-25T00:00:00Z','2026-11-25T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO draft_lines(id, draft, numero, description, quantite, unite, pu_ht, "
            "tax_code, total_ht) VALUES ('l1','d1',1,'Banquette 3 places','4','pcs',185000,'TVA18',740000)"
        )
        conn.commit()
        return conn

    def test_livraison_absente_non_inventee(self) -> None:
        ctx = build_context(self._base(), "d1")
        self.assertEqual(dict(ctx.livree), {})
        self.assertTrue(any(a.code == "QUANTITY_MISMATCH" for a in run_controls(ctx)))

    def test_client_match_depuis_champ_extrait(self) -> None:
        ctx = build_context(self._base(), "d1")
        self.assertEqual(ctx.client_match["niveau"], "C2")
        self.assertEqual(ctx.client_match["confiance"], 0.95)

    def test_taux_resolu_depuis_referentiel(self) -> None:
        ctx = build_context(self._base(), "d1")
        self.assertEqual(ctx.referentiel_fiscal["TVA18"].taux_bp, 1800)
        self.assertIsNotNone(ctx.calcule)
        self.assertEqual(ctx.calcule.total_ttc, 873_200)  # type: ignore[union-attr]

    def test_code_fiscal_inconnu_sans_defaut(self) -> None:
        conn = self._base()
        conn.execute("UPDATE draft_lines SET tax_code='TVA_MAJ' WHERE id='l1'")
        ctx = build_context(conn, "d1")
        self.assertIsNone(ctx.calcule)
        self.assertTrue(any(a.code == "INVALID_TAX" for a in run_controls(ctx)))

    def test_doublon_a_trois_jours(self) -> None:
        conn = self._base()
        conn.execute(
            "INSERT INTO invoices(id, numero, serie, annee, snapshot, hash_snapshot, hash_pdf, "
            "date, statut, client, total_ht, total_tva, total_ttc) VALUES "
            "('inv1','FAC-2026-00001','FAC',2026,'{}','h1','h2','2026-11-19','VALIDÉ','c1',"
            "740000,133200,873200)"
        )
        ctx = build_context(conn, "d1")
        self.assertEqual(ctx.doublons_proches, ("FAC-2026-00001",))
        self.assertTrue(any(a.code == "DUPLICATE_INVOICE" for a in run_controls(ctx)))


CLIENTS_REFERENCE = (
    {
        "id": "c1", "raison_sociale": "Ets Sossa Materiaux", "ifu": "123456789",
        "telephone": "+2290123456789", "ville": "Cotonou", "email": "sossa@example.bj",
    },
    {"id": "c2", "raison_sociale": "Sossa Materiaux SARL", "ifu": "987654321",
     "ville": "Porto-Novo"},
)
ITEMS_REFERENCE = (
    {"id": "i1", "designation": "Banquette 3 places", "famille": "MOB"},
    {"id": "i2", "designation": "Table basse chene", "famille": "MOB"},
)


class TestRapprochementClients(unittest.TestCase):
    def test_seuls_c1_et_c2_sont_automatiques(self) -> None:
        self.assertEqual(NIVEAUX_RATTACHEMENT_AUTO, ("C1", "C2"))

    def test_c1_ifu_identique_non_vide(self) -> None:
        resultat = match_client(CLIENTS_REFERENCE, "Autre nom", " 123456789 ")
        self.assertEqual(resultat["niveau"], "C1")
        self.assertEqual(resultat["client_id"], "c1")
        self.assertEqual(resultat["confiance"], 1.0)

    def test_ifu_vide_ne_donne_pas_c1(self) -> None:
        resultat = match_client(
            ({"id": "x", "raison_sociale": "X", "ifu": ""},), "X", "   "
        )
        self.assertEqual(resultat["niveau"], "C2")
        self.assertEqual(resultat["client_id"], "x")

    def test_c2_nom_exact_et_ville_coherente(self) -> None:
        self.assertEqual(
            match_client(CLIENTS_REFERENCE, "ets sossa matériaux", ville="Cotonou")["niveau"],
            "C2",
        )
        incoherent = match_client(CLIENTS_REFERENCE, "Ets Sossa Materiaux", ville="Parakou")
        self.assertNotEqual(incoherent["niveau"], "C2")
        self.assertIsNone(incoherent["client_id"])

    def test_c3_telephone_identique_et_nom_proche(self) -> None:
        resultat = match_client(
            CLIENTS_REFERENCE, "Ets Sossa Materiau", telephone="+229 01 23 45 67 89"
        )
        self.assertEqual(resultat["niveau"], "C3")
        self.assertEqual(resultat["client_id"], "c1")
        self.assertEqual(resultat["confiance"], 0.80)
        self.assertEqual(resultat["action"], "SUGGESTION_A_CONFIRMER")

    def test_c3_email_identique_et_nom_proche(self) -> None:
        resultat = match_client(
            CLIENTS_REFERENCE, "Ets Sossa Materiau", email="Sossa@Example.BJ"
        )
        self.assertEqual(resultat["niveau"], "C3")
        self.assertEqual(resultat["client_id"], "c1")

    def test_contact_identique_mais_nom_eloigne(self) -> None:
        resultat = match_client(
            CLIENTS_REFERENCE, "Hotel Codjo", telephone="+2290123456789"
        )
        self.assertEqual(resultat["niveau"], "C5")
        self.assertIsNone(resultat["client_id"])

    def test_c4_candidats_sans_rattachement(self) -> None:
        resultat = match_client(CLIENTS_REFERENCE, "Sossa Materiaux")
        self.assertEqual(resultat["niveau"], "C4")
        self.assertIsNone(resultat["client_id"])
        self.assertEqual(set(resultat["candidats"]), {"c1", "c2"})

    def test_c5_aucun_candidat(self) -> None:
        resultat = match_client(CLIENTS_REFERENCE, "Auberge inconnue")
        self.assertEqual(resultat["niveau"], "C5")
        self.assertEqual(resultat["confiance"], 0.0)
        self.assertEqual(resultat["action"], "CREATION_DIRIGEANT")


class TestRapprochementArticles(unittest.TestCase):
    def test_designation_exacte(self) -> None:
        resultat = match_item(ITEMS_REFERENCE, "Banquette 3 places")
        self.assertEqual(resultat["item_id"], "i1")
        self.assertEqual(resultat["confiance"], 1.0)
        self.assertEqual(resultat["action"], "RATTACHEMENT_AUTO")

    def test_designation_proche_reste_a_confirmer(self) -> None:
        resultat = match_item(ITEMS_REFERENCE, "Banquette 3 place")
        self.assertIsNone(resultat["item_id"])
        self.assertEqual(resultat["famille"], "MOB")
        self.assertEqual(resultat["confiance"], 0.50)
        self.assertEqual(resultat["action"], "SUGGESTION_A_CONFIRMER")

    def test_famille_seule_est_ligne_libre(self) -> None:
        resultat = match_item(ITEMS_REFERENCE, "Prestation sur mesure", "SERV")
        self.assertEqual(resultat["action"], "LIGNE_LIBRE_JUSTIFIEE")
        self.assertEqual(resultat["famille"], "SERV")
        self.assertEqual(resultat["confiance"], 0.30)

    def test_sans_rattachement(self) -> None:
        resultat = match_item(ITEMS_REFERENCE, "Prestation sur mesure")
        self.assertEqual(resultat["action"], "A_RATTACHER")
        self.assertEqual(resultat["confiance"], 0.0)

    def test_designation_vide_nest_pas_un_rattachement(self) -> None:
        resultat = match_item(({"id": "i0", "designation": "", "famille": "MOB"},), "")
        self.assertEqual(resultat["action"], "A_RATTACHER")


class TestRapprochementQuantites(unittest.TestCase):
    def test_trois_quantites_et_trois_ecarts(self) -> None:
        lignes = [{
            "numero": 3, "description": "Installation", "quantite": "1",
            "quantite_commandee": "2", "quantite_facturee": "1",
        }]
        comparaison = compare_quantites(lignes, {3: "0"})[0]
        self.assertEqual(comparaison.commandee, Decimal("2"))
        self.assertEqual(comparaison.livree, Decimal("0"))
        self.assertEqual(comparaison.facturee, Decimal("1"))
        self.assertEqual(comparaison.statut, "LIVREE_INFERIEURE")
        self.assertEqual(comparaison.ecart_livre_commande, Decimal("-2"))
        self.assertEqual(comparaison.ecart_livre_facture, Decimal("-1"))
        self.assertEqual(comparaison.ecart_facture_commande, Decimal("-1"))
        self.assertEqual(comparaison.to_dict()["ecart_livre_facture"], "-1")

    def test_livraison_inconnue_sans_ecart_de_livraison(self) -> None:
        comparaison = compare_quantites(
            [{"numero": 1, "description": "x", "quantite": "4", "quantite_commandee": "5"}],
            {},
        )[0]
        self.assertEqual(comparaison.statut, "LIVRAISON_INCONNUE")
        self.assertIsNone(comparaison.livree)
        self.assertIsNone(comparaison.ecart_livre_commande)
        self.assertIsNone(comparaison.ecart_livre_facture)
        self.assertEqual(comparaison.ecart_facture_commande, Decimal("-1"))

    def test_cles_de_livraison_en_texte(self) -> None:
        comparaison = compare_quantites(
            [{"numero": 1, "description": "x", "quantite": "4"}], {"1": "4"}
        )[0]
        self.assertEqual(comparaison.statut, "OK")

    def test_flottant_et_booleen_refuses(self) -> None:
        with self.assertRaises(TypeError):
            compare_quantites([{"numero": 1, "quantite": 1.5}], {})
        with self.assertRaises(TypeError):
            compare_quantites([{"numero": 1, "quantite": "1"}], {1: True})

    def test_quantite_invalide_refusee(self) -> None:
        for valeur in ("abc", "NaN", "Infinity"):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                compare_quantites([{"numero": 1, "quantite": valeur}], {})

    def test_r13_tableau_consomme_par_les_controles(self) -> None:
        lignes = [
            dict(contexte().lignes[0], numero=1, description="Banquettes", quantite="4"),
            dict(contexte().lignes[0], numero=2, description="Tables", quantite="2"),
            dict(contexte().lignes[0], numero=3, description="Installation", quantite="1"),
        ]
        livree = {1: "4", 2: "2", 3: "0"}
        ctx = contexte(lignes=lignes, livree=livree)
        anomalies = [a for a in run_controls(ctx) if a.code == "QUANTITY_MISMATCH"]
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].champ, "ligne 3")
        troisieme = compare_quantites(lignes, livree)[2]
        self.assertEqual(
            (troisieme.commandee, troisieme.livree, troisieme.facturee),
            (Decimal("1"), Decimal("0"), Decimal("1")),
        )


class TestAutomateDocuments(unittest.TestCase):
    def test_vocabulaire_et_etats_terminaux(self) -> None:
        self.assertEqual(len(ETATS), 10)
        self.assertEqual(TERMINAUX, frozenset({REJETE, ANNULE_PAR_AVOIR}))
        self.assertEqual(transitions_possibles(REJETE), ())
        self.assertEqual(transitions_possibles(ANNULE_PAR_AVOIR), ())
        self.assertEqual(
            set(transitions_possibles(IMPORTE)), {EN_ATTENTE_IA, EXTRAIT, REJETE}
        )

    def test_chaine_complete_du_blueprint(self) -> None:
        etapes = (
            (IMPORTE, EN_ATTENTE_IA, {}),
            (EN_ATTENTE_IA, EXTRAIT, {}),
            (EXTRAIT, A_COMPLETER, {}),
            (A_COMPLETER, EXTRAIT, {}),
            (EXTRAIT, CONTROLE, {}),
            (CONTROLE, BROUILLON, {}),
            (BROUILLON, VALIDE, {"decision_humaine": True, "acteur": "codjo"}),
            (VALIDE, EMIS, {"canal": "email"}),
            (EMIS, EMIS, {"type_avoir": "partiel"}),
            (EMIS, ANNULE_PAR_AVOIR, {"type_avoir": "total"}),
        )
        for source, cible, preuves in etapes:
            with self.subTest(source=source, cible=cible):
                decision = verifier_transition(source, cible, **preuves)
                self.assertTrue(decision.autorisee)
                self.assertEqual(decision.actuel, source)
                self.assertEqual(decision.cible, cible)
                self.assertTrue(decision.motif)

    def test_sauts_interdits(self) -> None:
        cas = (
            (IMPORTE, VALIDE, {}),
            (EXTRAIT, BROUILLON, {}),
            (A_COMPLETER, CONTROLE, {}),
            (REJETE, EXTRAIT, {}),
            (ANNULE_PAR_AVOIR, EMIS, {}),
            (BROUILLON, VALIDE, {}),
            (VALIDE, EMIS, {"canal": ""}),
            (EMIS, EMIS, {}),
            (EMIS, ANNULE_PAR_AVOIR, {}),
            (VALIDE, ANNULE_PAR_AVOIR, {"type_avoir": "total"}),
        )
        for source, cible, preuves in cas:
            with self.subTest(source=source, cible=cible), self.subTest(preuves=preuves):
                self.assertFalse(verifier_transition(source, cible, **preuves).autorisee)

    def test_etat_inconnu_refuse_sans_transition(self) -> None:
        for source, cible in (("", EXTRAIT), (IMPORTE, ""), ("IMPORTE", EXTRAIT)):
            with self.subTest(source=source, cible=cible), self.assertRaises(DocumentError):
                verifier_transition(source, cible)

    def test_anomalie_bloquante_et_resolution(self) -> None:
        ouverte = Anomalie("MISSING_MANDATORY", "BLOQUANT", "client.ifu", "IFU absent", "COMPLETER")
        decision = verifier_transition(EXTRAIT, CONTROLE, anomalies=[ouverte])
        self.assertFalse(decision.autorisee)
        self.assertIn("bloquante", decision.motif)
        resolue = Anomalie(
            "MISSING_MANDATORY", "BLOQUANT", "client.ifu", "IFU absent", "COMPLETER",
            "RESOLUE", "codjo", "IFU communiqué", "", "123456789",
        )
        self.assertTrue(verifier_transition(EXTRAIT, CONTROLE, anomalies=[resolue]).autorisee)
        self.assertTrue(verifier_transition(EXTRAIT, A_COMPLETER, anomalies=[ouverte]).autorisee)

    def test_avertissement_seul_ne_bloque_pas(self) -> None:
        avertissement = Anomalie("UNUSUAL_PRICE", "AVERTISSEMENT", "ligne 2", "+11 %", "JUSTIFIER")
        self.assertTrue(verifier_transition(EXTRAIT, CONTROLE, anomalies=[avertissement]).autorisee)

    def test_doublon_force_rejet(self) -> None:
        self.assertFalse(verifier_transition(IMPORTE, EXTRAIT, doublon=True).autorisee)
        decision = verifier_transition(IMPORTE, REJETE, doublon=True)
        self.assertTrue(decision.autorisee)
        self.assertIn("doublon", decision.motif)


class TestDecisionDoublon(unittest.TestCase):
    def test_hash_absent_refuse(self) -> None:
        with self.assertRaises(DocumentError):
            decider_doublon("   ", None)

    def test_sans_piece_existante_importe(self) -> None:
        decision = decider_doublon("abc", None)
        self.assertEqual(decision, DecisionDoublon(False, None, "IMPORTER", decision.motif))
        exiger_pas_de_doublon(decision)

    def test_piece_existante_bloque_avant_ecriture(self) -> None:
        decision = decider_doublon(" abc ", {"id": "doc9"})
        self.assertTrue(decision.doublon)
        self.assertEqual(decision.document_existant, "doc9")
        self.assertEqual(decision.action, "OUVRIR_EXISTANT")
        self.assertIn("abc", decision.motif)
        with self.assertRaises(DuplicateDocument) as leve:
            exiger_pas_de_doublon(decision)
        self.assertEqual(leve.exception.existing_id, "doc9")

    def test_identifiant_existant_manquant_refuse(self) -> None:
        with self.assertRaises(DocumentError):
            decider_doublon("abc", {"nom": "devis.pdf"})


class TestApplicationTransitionsDocuments(unittest.TestCase):
    def _base(self, statut: str = IMPORTE) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(Path("schema.sql").read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO documents(id, type, nom, mime, taille, hash, statut, cree_le) "
            "VALUES ('doc1','devis','devis.pdf','application/pdf',100,'abc',?,"
            "'2026-11-25T00:00:00Z')",
            (statut,),
        )
        conn.commit()
        return conn

    def test_refus_sans_ecriture_ni_evenement(self) -> None:
        conn = self._base(EXTRAIT)
        ouverte = Anomalie("MISSING_MANDATORY", "BLOQUANT", "client.ifu", "IFU absent", "COMPLETER")
        with self.assertRaises(TransitionInterdite):
            appliquer_transition(conn, "doc1", CONTROLE, anomalies=[ouverte])
        self.assertEqual(
            conn.execute("SELECT statut FROM documents WHERE id='doc1'").fetchone()["statut"],
            EXTRAIT,
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)

    def test_transition_autorisee_journalisee(self) -> None:
        conn = self._base(EXTRAIT)
        resolue = Anomalie(
            "MISSING_MANDATORY", "BLOQUANT", "client.ifu", "IFU absent", "COMPLETER",
            "RESOLUE", "codjo", "IFU communiqué", "", "123456789",
        )
        decision = appliquer_transition(
            conn, "doc1", CONTROLE, acteur="codjo", anomalies=[resolue],
            motif="IFU vérifié sur la pièce",
        )
        self.assertTrue(decision.autorisee)
        self.assertEqual(
            conn.execute("SELECT statut FROM documents WHERE id='doc1'").fetchone()["statut"],
            CONTROLE,
        )
        evenement = conn.execute("SELECT * FROM audit_events").fetchone()
        self.assertEqual(evenement["action"], "CHANGEMENT_STATUT_DOCUMENT")
        self.assertEqual(evenement["acteur"], "codjo")
        self.assertIn(EXTRAIT, evenement["avant"])
        self.assertIn(CONTROLE, evenement["apres"])
        valide, erreurs = verifier_chaine(conn)
        self.assertTrue(valide, erreurs)

    def test_validation_humaine_explicite_tracée(self) -> None:
        conn = self._base(BROUILLON)
        with self.assertRaises(TransitionInterdite):
            appliquer_transition(conn, "doc1", VALIDE, acteur="systeme")
        with self.assertRaises(TransitionInterdite):
            appliquer_transition(conn, "doc1", VALIDE, acteur="codjo")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)
        appliquer_transition(
            conn, "doc1", VALIDE, acteur="codjo", decision_humaine=True
        )
        apres = conn.execute("SELECT apres FROM audit_events").fetchone()["apres"]
        self.assertIn("decision_humaine", apres)
        self.assertEqual(
            conn.execute("SELECT statut FROM documents WHERE id='doc1'").fetchone()["statut"],
            VALIDE,
        )

    def test_piece_inexistante_refusee(self) -> None:
        with self.assertRaises(DocumentError):
            appliquer_transition(self._base(), "inconnu", EXTRAIT)


if __name__ == "__main__":
    unittest.main()
