"""Mesure contre la méthode de référence : saisie manuelle chronométrée vs WÉMA.

Le TDR demande de « mesurer les gains de temps et les erreurs évitées par
rapport à une méthode de référence ». La méthode de référence est celle
d'aujourd'hui : une personne recopie la pièce à la main. Protocole complet :
docs/PROTOCOLE_REFERENCE.md.

    python -m domain.reference preparer            # 20 pièces + fiches de saisie vierges
    python -m domain.reference comparer            # après la saisie : rapport saisie vs outil

Aucune donnée humaine n'est simulée : sans fiche remplie, ``comparer`` s'arrête.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from . import extraction, metrics

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "seeds" / "reference"  # versionné : les fiches remplies sont la preuve du rapport
# 20 pièces, stratifiées par famille, prises dans les jeux validation + test.
QUOTAS = {"devis": 6, "photo": 6, "message": 3, "bon_livraison": 3, "degrade": 2}
ENTETES = ["document", "fichier", "debut", "fin", "reference", "client", "ifu", "date",
           "total_ht_imprime", "remarque"]
LIGNES = ["document", "ligne", "description", "quantite", "unite", "pu_ht", "total_ligne"]
CHAMPS_ENTETE = {"reference": "reference", "client": "client.name", "ifu": "client.ifu", "date": "dates.issue"}


def choisir() -> list[dict[str, Any]]:
    """Sélection déterministe : jeux validation + test, par famille, ordre des références."""
    restants = dict(QUOTAS)
    choisis = []
    for truth in metrics.charger_truths():
        famille = truth.get("family")
        if truth.get("split") in ("validation", "test") and restants.get(famille, 0) > 0:
            choisis.append(truth)
            restants[famille] -= 1
    return choisis


def preparer(dossier: Path = DOSSIER) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    pieces = choisir()
    with (dossier / "saisie_entetes.csv").open("w", newline="", encoding="utf-8") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=ENTETES)
        ecrivain.writeheader()
        for truth in pieces:
            ecrivain.writerow({"document": truth["reference"], "fichier": truth["source_file"]})
    with (dossier / "saisie_lignes.csv").open("w", newline="", encoding="utf-8") as flux:
        csv.DictWriter(flux, fieldnames=LIGNES).writeheader()
    (dossier / "pieces.json").write_text(
        json.dumps([t["reference"] for t in pieces], indent=2) + "\n", encoding="utf-8")
    return dossier


def _duree(debut: str, fin: str) -> float | None:
    for format_ in ("%H:%M:%S", "%H:%M"):
        try:
            return (datetime.strptime(fin.strip(), format_) - datetime.strptime(debut.strip(), format_)).total_seconds()
        except (ValueError, AttributeError):
            continue
    return None


def _juger(truth: Mapping[str, Any], entete: Mapping[str, str],
           lignes: list[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Erreurs de la saisie manuelle, champ par champ, avec la même règle d'égalité que les métriques."""
    erreurs = []

    def comparer(champ: str, attendu: Any, saisi: Any) -> None:
        saisi = None if saisi in (None, "") else saisi
        if metrics.egal(attendu, saisi):
            return
        if attendu is None:
            nature = "valeur_inventee"  # ex. un IFU tapé de mémoire alors qu'il n'est pas sur la pièce
        elif saisi is None:
            nature = "oubli"
        else:
            nature = "faute_de_saisie"
        erreurs.append({"document": truth["reference"], "champ": champ, "attendu": attendu,
                        "saisi": saisi, "nature": nature})

    for colonne, chemin in CHAMPS_ENTETE.items():
        comparer(chemin, (truth.get("fields") or {}).get(chemin), entete.get(colonne))
    imprime = (truth.get("printed_totals") or {}).get("ht")
    if imprime is not None or entete.get("total_ht_imprime"):
        comparer("totals.printed_ht", imprime, entete.get("total_ht_imprime"))
    saisies = {str(l.get("ligne", "")).strip(): l for l in lignes}
    for ligne in truth.get("lines", []):
        saisie = saisies.get(str(ligne["line_no"]), {})
        for colonne, cle in (("description", "description"), ("quantite", "quantity"),
                             ("unite", "unit"), ("pu_ht", "unit_price_ht"), ("total_ligne", "line_total_ht")):
            comparer(f"lines[{ligne['line_no']}].{cle}", ligne[cle], saisie.get(colonne))
    for numero in set(saisies) - {str(l["line_no"]) for l in truth.get("lines", [])}:
        erreurs.append({"document": truth["reference"], "champ": f"lines[{numero}]", "attendu": None,
                        "saisi": "ligne en trop", "nature": "valeur_inventee"})
    return erreurs


def _outil(truth: Mapping[str, Any], clients: list[dict[str, Any]] | None) -> dict[str, Any]:
    """WÉMA sur la même pièce : temps machine, valeurs à confirmer, erreurs silencieuses."""
    chemin = RACINE / truth["source_file"]
    debut = time.perf_counter()
    payload = extraction.extraire_piece(chemin, ocr_backend="cache", clients=clients)
    machine = time.perf_counter() - debut
    ocr_reel = None
    if chemin.suffix.lower() == ".png":
        from adapters import ocr
        cache = ocr.CACHE / f"{ocr.empreinte_contenu(chemin)}.json"
        if cache.is_file():
            ocr_reel = json.loads(cache.read_text(encoding="utf-8")).get("duree_s")
    jugements = metrics.juger_revue(truth, payload)
    return {
        "temps_machine_s": round(machine, 3),
        "temps_ocr_reel_s": ocr_reel,  # lecture EasyOCR réelle, rejouée ici depuis le cache
        "a_confirmer": sum(1 for j in jugements if j["revue"]),
        "erreurs": sum(1 for j in jugements if j["etat"] != "juste"),
        "erreurs_silencieuses": sum(1 for j in jugements if j["etat"] != "juste" and not j["revue"]),
        "valeurs_jugees": len(jugements),
    }


def comparer(dossier: Path = DOSSIER) -> dict[str, Any]:
    entetes_csv, lignes_csv = dossier / "saisie_entetes.csv", dossier / "saisie_lignes.csv"
    if not entetes_csv.is_file():
        raise SystemExit("aucune fiche : lancer d'abord `python -m domain.reference preparer`")
    with entetes_csv.open(encoding="utf-8") as flux:
        entetes = {r["document"]: r for r in csv.DictReader(flux)}
    with lignes_csv.open(encoding="utf-8") as flux:
        toutes_lignes = list(csv.DictReader(flux))
    remplies = {doc: e for doc, e in entetes.items() if e.get("debut") and e.get("fin")}
    if not remplies:
        raise SystemExit("fiche vide : aucune pièce n'a d'heure de début et de fin. Rien n'est simulé.")

    verites = {t["reference"]: t for t in metrics.charger_truths()}
    clients = metrics.charger_clients()
    manuel, outil, erreurs = [], [], []
    for doc, entete in sorted(remplies.items()):
        truth = verites[doc]
        lignes = [l for l in toutes_lignes if l.get("document") == doc]
        erreurs_doc = _juger(truth, entete, lignes)
        erreurs.extend(erreurs_doc)
        manuel.append({"document": doc, "famille": truth["family"],
                       "duree_s": _duree(entete["debut"], entete["fin"]), "erreurs": len(erreurs_doc)})
        outil.append({"document": doc, "famille": truth["family"], **_outil(truth, clients)})

    durees = [m["duree_s"] for m in manuel if m["duree_s"] is not None]
    resultat = {
        "pieces": len(remplies),
        "manuel": {
            "temps_moyen_s": round(sum(durees) / len(durees), 1) if durees else None,
            "erreurs": len(erreurs),
            "erreurs_par_nature": {n: sum(1 for e in erreurs if e["nature"] == n)
                                   for n in ("faute_de_saisie", "oubli", "valeur_inventee")},
            "documents_sans_erreur": sum(1 for m in manuel if m["erreurs"] == 0),
            # Une erreur de saisie manuelle n'est signalée par rien : elle est silencieuse par nature.
            "erreurs_silencieuses": len(erreurs),
        },
        "outil": {
            "temps_machine_moyen_s": round(sum(o["temps_machine_s"] for o in outil) / len(outil), 3),
            "temps_ocr_reel_moyen_photos_s": _moyenne([o["temps_ocr_reel_s"] for o in outil]),
            "valeurs_a_confirmer": sum(o["a_confirmer"] for o in outil),
            "erreurs": sum(o["erreurs"] for o in outil),
            "erreurs_silencieuses": sum(o["erreurs_silencieuses"] for o in outil),
        },
        "detail_manuel": manuel,
        "detail_outil": outil,
        "erreurs_manuelles": erreurs,
        "limite": "Le temps humain de confirmation dans WÉMA n'est pas mesuré ici : "
                  "le chronométrer pendant la démo (protocole, étape 4).",
    }
    (dossier / "resultat.json").write_text(
        json.dumps(resultat, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return resultat


def _moyenne(valeurs: list[Any]) -> float | None:
    valeurs = [v for v in valeurs if v is not None]
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else None


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Saisie manuelle chronométrée contre WÉMA")
    parser.add_argument("action", choices=("preparer", "comparer"))
    parser.add_argument("--dossier", default=str(DOSSIER))
    args = parser.parse_args(argv)
    dossier = Path(args.dossier)
    if args.action == "preparer":
        preparer(dossier)
        print(f"20 pièces choisies. Fiches à remplir : {dossier / 'saisie_entetes.csv'} "
              f"et {dossier / 'saisie_lignes.csv'}. Protocole : docs/PROTOCOLE_REFERENCE.md")
        return 0
    r = comparer(dossier)
    m, o = r["manuel"], r["outil"]
    print(f"Pièces saisies : {r['pieces']}")
    print(f"Saisie manuelle : {m['temps_moyen_s']} s par pièce · {m['erreurs']} erreurs "
          f"({m['erreurs_par_nature']}) · toutes silencieuses")
    print(f"WÉMA : {o['temps_machine_moyen_s']} s machine par pièce (OCR réel photo : "
          f"{o['temps_ocr_reel_moyen_photos_s']} s) · {o['valeurs_a_confirmer']} valeurs à confirmer · "
          f"{o['erreurs']} erreurs dont {o['erreurs_silencieuses']} silencieuses")
    print(f"Détail : {dossier / 'resultat.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
