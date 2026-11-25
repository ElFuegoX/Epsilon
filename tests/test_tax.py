"""Tests du moteur de calcul déterministe — piste Larissa.

Référence : seeds/golden/DEV-2026-041.truth.json, docs/RECETTE.md (R1),
docs/DECISIONS.md (taux obligatoire, remise globale au prorata, écarts signés).
"""

from __future__ import annotations

import random
import unittest
from decimal import Decimal

from config import settings
from domain.tax import (
    CodeFiscal,
    Ligne,
    TauxFiscalInconnu,
    arrondi_fcfa,
    calculer,
    calculer_ligne,
    demi_vers_le_haut,
    lignes_depuis_dict,
    repartir_remise_globale,
)


DEV_LIGNES = (
    Ligne(description="Banquette 3 places", quantite="4", unite="pcs", pu_ht=185_000, taux_bp=1800),
    Ligne(description="Table basse chêne", quantite="2", unite="pcs", pu_ht=120_000, taux_bp=1800),
    Ligne(
        description="Livraison et installation",
        quantite="1",
        unite="forfait",
        pu_ht=60_000,
        taux_bp=1800,
    ),
)

DEV_IMPRIME = {"ht": 1_020_000, "vat": 183_600, "ttc": 1_203_600}

REFERENTIEL = {
    "TVA18": CodeFiscal("TVA18", 1800),
    "TVA0": CodeFiscal("TVA0", 0, exoneration=True),
}


class TestArrondi(unittest.TestCase):
    def test_demi_vers_le_haut(self) -> None:
        self.assertEqual(arrondi_fcfa("2.4"), 2)
        self.assertEqual(arrondi_fcfa("2.5"), 3)
        self.assertEqual(arrondi_fcfa("1 040 000"), 1_040_000)
        self.assertEqual(arrondi_fcfa(Decimal("0.5")), 1)

    def test_version_entiere(self) -> None:
        self.assertEqual(demi_vers_le_haut(5, 2), 3)
        self.assertEqual(demi_vers_le_haut(1, 4), 0)
        with self.assertRaises(ValueError):
            demi_vers_le_haut(1, 0)

    def test_flottant_interdit(self) -> None:
        with self.assertRaises(TypeError):
            arrondi_fcfa(2.5)
        ligne = Ligne(description="x", quantite="1", pu_ht=1.5, taux_bp=1800)
        with self.assertRaises(TypeError):
            calculer_ligne(ligne)


class TestDev2026041(unittest.TestCase):
    def test_recalcul_exact(self) -> None:
        r = calculer(DEV_LIGNES)
        self.assertEqual([l.brut_ht for l in r.lignes], [740_000, 240_000, 60_000])
        self.assertEqual([l.net_ht for l in r.lignes], [740_000, 240_000, 60_000])
        self.assertEqual([l.tva for l in r.lignes], [133_200, 43_200, 10_800])
        self.assertEqual(r.total_ht, 1_040_000)
        self.assertEqual(r.total_tva, 187_200)
        self.assertEqual(r.total_ttc, 1_227_200)

    def test_ecarts_imprime_moins_recalcul(self) -> None:
        r = calculer(DEV_LIGNES, imprime=DEV_IMPRIME)
        self.assertEqual(r.ecarts, {"ht": -20_000, "vat": -3_600, "ttc": -23_600})

    def test_tolerance_filtre_ecarts(self) -> None:
        sans_tolerance = calculer(DEV_LIGNES, imprime=DEV_IMPRIME)
        self.assertEqual(set(sans_tolerance.ecarts), {"ht", "vat", "ttc"})
        # Un écart exactement égal à la tolérance n'est pas signalé.
        avec_tolerance = calculer(DEV_LIGNES, imprime=DEV_IMPRIME, tolerance=20_000)
        self.assertEqual(avec_tolerance.ecarts, {"ttc": -23_600})

    def test_hash_stable_et_sensible(self) -> None:
        a = calculer(DEV_LIGNES, imprime=DEV_IMPRIME)
        b = calculer(DEV_LIGNES, imprime=DEV_IMPRIME)
        self.assertEqual(a.hash_calcul, b.hash_calcul)
        modifiees = DEV_LIGNES[:-1] + (
            Ligne(description="Livraison et installation", quantite="1", pu_ht=60_001, taux_bp=1800),
        )
        self.assertNotEqual(a.hash_calcul, calculer(modifiees, imprime=DEV_IMPRIME).hash_calcul)

    def test_aucun_float_dans_le_resultat(self) -> None:
        r = calculer(DEV_LIGNES, imprime=DEV_IMPRIME)
        for valeur in (
            r.total_ht,
            r.total_tva,
            r.total_ttc,
            r.remise_globale,
            *r.ecarts.values(),
        ):
            self.assertIs(type(valeur), int)
        for ligne in r.lignes:
            for valeur in ligne.to_dict().values():
                self.assertIs(type(valeur), int)


class TestTauxObligatoire(unittest.TestCase):
    def test_code_resolu_depuis_referentiel(self) -> None:
        ligne = Ligne(description="x", quantite="1", pu_ht=10_000, code_fiscal="TVA18")
        self.assertEqual(ligne.taux_resolu(REFERENTIEL), 1800)
        self.assertEqual(calculer_ligne(ligne, referentiel=REFERENTIEL).tva, 1_800)

    def test_ligne_sans_taux_leve_exception(self) -> None:
        ligne = Ligne(description="x", quantite="1", pu_ht=10_000)
        with self.assertRaises(TauxFiscalInconnu):
            calculer_ligne(ligne)

    def test_code_absent_du_referentiel(self) -> None:
        ligne = Ligne(description="x", quantite="1", pu_ht=10_000, code_fiscal="TVA_MAJ")
        with self.assertRaises(TauxFiscalInconnu):
            calculer_ligne(ligne, referentiel=REFERENTIEL)

    def test_lignes_depuis_dict_sans_defaut_dix_huit(self) -> None:
        lignes = lignes_depuis_dict([{"description": "x", "quantite": "1", "pu_ht": 10_000}])
        self.assertIsNone(lignes[0].taux_bp)
        with self.assertRaises(TauxFiscalInconnu):
            calculer(lignes)

    def test_lignes_depuis_dict_avec_referentiel(self) -> None:
        lignes = lignes_depuis_dict(
            [{"description": "x", "quantite": "2", "pu_ht": 10_000, "tax_code": "TVA18"}],
            referentiel=REFERENTIEL,
        )
        self.assertEqual(calculer(lignes, referentiel=REFERENTIEL).total_ttc, 23_600)

    def test_code_inconnu_leve_au_chargement(self) -> None:
        with self.assertRaises(TauxFiscalInconnu):
            lignes_depuis_dict(
                [{"description": "x", "quantite": "1", "pu_ht": 10_000, "code_fiscal": "TVA_MAJ"}],
                referentiel=REFERENTIEL,
            )


class TestRemises(unittest.TestCase):
    def test_remise_ligne_pourcentage_avant_tva(self) -> None:
        ligne = Ligne(description="x", quantite="2", pu_ht=120_000, remise_pct=10, taux_bp=1800)
        r = calculer_ligne(ligne)
        self.assertEqual(r.brut_ht, 240_000)
        self.assertEqual(r.remise, 24_000)
        self.assertEqual(r.net_ht, 216_000)
        self.assertEqual(r.tva, 38_880)
        self.assertEqual(r.total_ttc, 254_880)

    def test_repartition_plus_grand_reste(self) -> None:
        self.assertEqual(repartir_remise_globale(100, [1, 1, 1]), [34, 33, 33])
        self.assertEqual(repartir_remise_globale(10, [0, 0]), [0, 0])
        self.assertEqual(repartir_remise_globale(0, [5, 5]), [0, 0])

    def test_repartition_prorata_sans_perte(self) -> None:
        parts = repartir_remise_globale(20_000, [740_000, 240_000, 60_000])
        self.assertEqual(parts, [14_231, 4_615, 1_154])
        self.assertEqual(sum(parts), 20_000)

    def test_remise_globale_visible_dans_le_resultat(self) -> None:
        r = calculer(DEV_LIGNES, imprime=DEV_IMPRIME, remise_globale=20_000)
        self.assertEqual(r.remise_globale, 20_000)
        self.assertEqual([l.remise_globale for l in r.lignes], [14_231, 4_615, 1_154])
        self.assertEqual(r.total_ht, 1_020_000)
        # L'arrondi TVA est fait par ligne : la somme des TVA arrondies vaut
        # 183 599, pas l'arrondi du total HT (183 600). Ce résidu de 1 FCFA
        # est attendu et ne doit jamais être corrigé silencieusement.
        self.assertEqual(r.total_tva, 183_599)
        self.assertEqual(r.total_ttc, 1_203_599)
        self.assertEqual(r.ecarts, {"vat": 1, "ttc": 1})
        with self.assertRaises(ValueError):
            repartir_remise_globale(-1, [10])


class TestProprietesDeterministes(unittest.TestCase):
    def test_mille_cas_avec_graine_fixe(self) -> None:
        """1 000 cas reproductibles, sans réseau, sans Hypothesis."""
        rng = random.Random(settings.graine_demo)
        for cas in range(1000):
            with self.subTest(cas=cas):
                lignes = []
                for i in range(rng.randint(1, 6)):
                    quantite = rng.randint(1, 12)
                    pu = rng.choice((0, 999, 120_000, 185_000, 1_000_000))
                    lignes.append(
                        Ligne(
                            description=f"L{i + 1}",
                            quantite=str(quantite),
                            pu_ht=pu,
                            remise=rng.randint(0, quantite * pu),
                            taux_bp=rng.choice((0, 900, 1800, 2000)),
                        )
                    )
                bruts = [int(l.quantite) * l.pu_ht for l in lignes]
                globale = rng.randint(0, sum(bruts))

                a = calculer(lignes, remise_globale=globale)
                b = calculer(lignes, remise_globale=globale)

                self.assertEqual(a.hash_calcul, b.hash_calcul)
                self.assertEqual(a.to_dict(), b.to_dict())
                for valeur in (a.total_ht, a.total_tva, a.total_ttc, a.remise_globale):
                    self.assertIs(type(valeur), int)
                self.assertEqual(a.total_ht, sum(l.net_ht for l in a.lignes))
                self.assertEqual(a.total_tva, sum(l.tva for l in a.lignes))
                self.assertEqual(a.total_ttc, a.total_ht + a.total_tva)
                self.assertEqual(sum(l.remise_globale for l in a.lignes), globale)
                for ligne in a.lignes:
                    self.assertIs(type(ligne.net_ht), int)
                    self.assertIs(type(ligne.tva), int)
                    self.assertEqual(ligne.total_ttc, ligne.net_ht + ligne.tva)
                    self.assertEqual(
                        ligne.tva,
                        arrondi_fcfa(
                            Decimal(ligne.net_ht) * Decimal(ligne.taux_bp) / Decimal(10000)
                        ),
                    )

                imprime = {
                    "ht": a.total_ht + rng.randint(-1000, 1000),
                    "vat": a.total_tva,
                    "ttc": a.total_ttc,
                }
                c = calculer(lignes, imprime=imprime, remise_globale=globale)
                self.assertEqual(c.ecarts.get("ht", 0), imprime["ht"] - a.total_ht)


if __name__ == "__main__":
    unittest.main()
