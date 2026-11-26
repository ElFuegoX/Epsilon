"""Mesures observées de l'extraction, jamais les cibles du blueprint.

Deux familles restent séparées : ce module ne mesure que l'extraction. Le
recalcul TVA, les contrôles et la numérotation appartiennent à Larissa.

Commande : ``python -m domain.metrics`` (écrit ``seeds/generated/metrics.json``).
"""

from __future__ import annotations

import argparse
import sys
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from config import settings

from . import extraction, normalization as norm

RACINE = Path(__file__).resolve().parents[1]
DORE = RACINE / "seeds" / "golden"
SORTIE = RACINE / "seeds" / "generated" / "metrics.json"

CHAMPS_EN_TETE = (
    "reference", "client.name", "client.ifu", "dates.issue",
    "dates.delivery", "dates.due", "payment_terms.text", "payment_terms.days",
)
TOTAUX_IMPRIMES = ("ht", "vat", "ttc")
CRITIQUES = set(CHAMPS_EN_TETE) | {f"totals.{nom}" for nom in TOTAUX_IMPRIMES}


def charger_truths(dossier: Path | None = None) -> list[dict[str, Any]]:
    dossier = dossier or DORE
    return [
        json.loads(chemin.read_text(encoding="utf-8"))
        for chemin in sorted(dossier.glob("*.truth.json"))
    ]


def _valeur(obj: Any) -> Any:
    return extraction.valeur(obj) if isinstance(obj, Mapping) and "value" in obj else obj


def chemin_valeur(payload: Mapping[str, Any], chemin: str) -> Any:
    objet: Any = payload
    for partie in chemin.split("."):
        if not isinstance(objet, Mapping):
            return None
        objet = objet.get(partie)
    return _valeur(objet)


def egal(a: Any, b: Any) -> bool:
    """Comparaison normalisée : entiers FCFA, dates ISO, texte sans accents."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return int(a) == int(b)
    for convertisseur in (norm.normalize_amount, norm.normalize_date):
        na, nb = convertisseur(a), convertisseur(b)
        if na is not None or nb is not None:
            return na == nb
    ta, tb = norm.normalize_text(a), norm.normalize_text(b)
    return bool(ta) and ta == tb or str(a).strip() == str(b).strip()


def _tuple_ligne(ligne: Mapping[str, Any]) -> tuple[str, str | None, str | None, int | None]:
    return (
        norm.normalize_text(_valeur(ligne.get("description"))),
        norm.normalize_quantity(_valeur(ligne.get("quantity"))),
        norm.normalize_unit(_valeur(ligne.get("unit"))),
        norm.normalize_amount(_valeur(ligne.get("unit_price_ht"))),
    )


def _erreur(truth: Mapping[str, Any], chemin: str, attendu: Any, observe: Any,
            confiance: float | None, categorie: str) -> dict[str, Any]:
    return {
        "document": truth["reference"],
        "categorie": categorie,
        "champ": chemin,
        "attendu": attendu,
        "observe": observe,
        "confiance": confiance,
    }


def _cueils_anomalies(truth: Mapping[str, Any], payload: Mapping[str, Any]) -> set[str]:
    detects: set[str] = set()
    anomalies = set(truth.get("injected_anomalies", []))
    if "MISSING_MANDATORY" in anomalies or "ifu" in truth.get("missing", []):
        champ_ifu = (payload.get("client") or {}).get("ifu") or {}
        if champ_ifu.get("missing") or champ_ifu.get("value") is None:
            detects.add("MISSING_MANDATORY")
    if "arithmetique" in anomalies or "ARITHMETIC_MISMATCH" in anomalies:
        imprime = truth.get("printed_totals", {}).get("ht")
        extrait = chemin_valeur(payload, "totals.printed_ht")
        if imprime is not None and egal(imprime, extrait):
            detects.add("arithmetique")
    if "QUANTITY_MISMATCH" in anomalies:
        # Signal lisible dans la pièce : une ligne livrée en deçà du commandé.
        for ligne in payload.get("lines", []):
            commande = norm.normalize_quantity(_valeur(ligne.get("quantity")))
            livre = norm.normalize_quantity(_valeur(ligne.get("delivered")))
            if commande is None or livre is None:
                continue
            try:
                if int(livre) < int(commande):
                    detects.add("QUANTITY_MISMATCH")
                    break
            except ValueError:
                continue
    if "DUPLICATE_DOCUMENT" in anomalies:
        if egal(truth.get("reference"), chemin_valeur(payload, "reference")):
            detects.add("DUPLICATE_DOCUMENT")
    return detects


CHAMPS_REVUE_TETE = ("reference", "client.name", "client.ifu", "dates.issue",
                     "payment_terms.text", "payment_terms.days")
CHAMPS_REVUE_LIGNE = ("quantity", "unit_price_ht", "line_total_ht")


def charger_clients() -> list[dict[str, Any]] | None:
    """Référentiel clients du corpus, pour le signal de cohérence (docs/CONFIANCE.md)."""
    chemin = RACINE / "seeds" / "generated" / "clients.json"
    if not chemin.is_file():
        return None
    return json.loads(chemin.read_text(encoding="utf-8"))


def juger_revue(truth: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Chaque valeur à juger : juste / absente / fausse, et envoyée en revue ou acceptée.

    Une valeur est « en revue » si elle est absente ou sous son seuil de
    confiance. C'est la mesure qui dit si le seuil fait son travail : une
    valeur fausse acceptée est une erreur silencieuse.
    """
    cas: list[tuple[str, Any, Any]] = []
    for nom in CHAMPS_REVUE_TETE:
        cas.append((nom, (truth.get("fields") or {}).get(nom), _objet_champ(payload, nom)))
    for nom in TOTAUX_IMPRIMES:
        attendu = (truth.get("printed_totals") or {}).get(nom)
        if attendu is not None:
            cas.append((f"totals.printed_{nom}", attendu, _objet_champ(payload, f"totals.printed_{nom}")))
    lignes_lues = payload.get("lines", [])
    for index, ligne in enumerate(truth.get("lines", [])):
        lue = lignes_lues[index] if index < len(lignes_lues) else {}
        for nom in CHAMPS_REVUE_LIGNE:
            cas.append((f"lines.{nom}", ligne.get(nom), lue.get(nom)))
    resultats = []
    for chemin, attendu, champ in cas:
        champ = champ or {}
        observe = extraction.valeur(champ)
        if attendu is None and observe is None:
            continue  # absent de la pièce et déclaré absent : rien à juger
        en_revue = bool(champ.get("missing")) or \
            float(champ.get("confidence", 0.0) or 0.0) < extraction.seuil(chemin)
        if egal(attendu, observe):
            etat = "juste"
        elif observe is None:
            etat = "absente"
        else:
            etat = "fausse"
        resultats.append({"document": truth["reference"], "champ": chemin, "etat": etat,
                          "revue": en_revue, "attendu": attendu, "observe": observe,
                          "confiance": champ.get("confidence")})
    return resultats


def _resume_revue(jugements: list[dict[str, Any]]) -> dict[str, Any]:
    compte = Counter((j["etat"], "revue" if j["revue"] else "acceptee") for j in jugements)
    erreurs = [j for j in jugements if j["etat"] != "juste"]
    attrapees = sum(1 for j in erreurs if j["revue"])
    justes = [j for j in jugements if j["etat"] == "juste"]
    silencieuses = [j for j in erreurs if not j["revue"]]
    par_champ: dict[str, Counter[str]] = {}
    for j in jugements:
        par_champ.setdefault(j["champ"], Counter())[
            f"{j['etat']}_{'revue' if j['revue'] else 'acceptee'}"] += 1
    return {
        "valeurs_jugees": len(jugements),
        "matrice": {f"{etat}_{decision}": n for (etat, decision), n in sorted(compte.items())},
        "erreurs": len(erreurs),
        "erreurs_attrapees": attrapees,
        "rappel_revue": round(attrapees / len(erreurs), 4) if erreurs else 1.0,
        "erreurs_silencieuses": len(silencieuses),
        "fausses_alertes": sum(1 for j in justes if j["revue"]),
        "taux_fausses_alertes": round(sum(1 for j in justes if j["revue"]) / len(justes), 4) if justes else 0.0,
        "exemples_silencieux": silencieuses[:10],
        "par_champ": {nom: dict(c) for nom, c in sorted(par_champ.items())},
    }


def evaluer(dossier: Path | None = None, backend: str = "demo",
            ecrire: bool = True, ocr_backend: str = "auto", split: str | None = None,
            clients: list[dict[str, Any]] | None = None, avec_referentiel: bool = True) -> dict[str, Any]:
    """Exécute l'extraction sur tout le corpus annoté et calcule les mesures."""
    truths = charger_truths(dossier)
    if split:
        truths = [t for t in truths if t.get("split") == split]
    if not truths:
        raise RuntimeError("aucune vérité terrain trouvée : lancer `python -m seed`")

    champs_bons = 0
    champs_total = 0
    par_champ: dict[str, dict[str, int]] = {
        nom: {"bons": 0, "total": 0} for nom in CHAMPS_EN_TETE
    }
    totaux_bons = 0
    totaux_total = 0
    tp = fp = fn = 0
    stp = 0
    anomalies_injectees = 0
    anomalies_detectees = 0
    valeurs_inventees = 0
    confusion: Counter[tuple[str, str]] = Counter()
    erreurs: list[dict[str, Any]] = []
    confiances_basses: list[dict[str, Any]] = []
    familles: dict[str, dict[str, int]] = {}
    jugements: list[dict[str, Any]] = []
    if clients is None and avec_referentiel:
        clients = charger_clients()

    for truth in truths:
        chemin = RACINE / truth["source_file"]
        payload = extraction.extraire_piece(chemin, backend=backend, ocr_backend=ocr_backend,
                                            clients=clients)
        jugements.extend(juger_revue(truth, payload))
        famille = familles.setdefault(truth.get("family", truth["document_type"]), {
            "documents": 0, "champs_bons": 0, "champs_total": 0, "tp": 0, "fp": 0, "fn": 0, "stp": 0,
        })
        famille["documents"] += 1
        stp_avant = stp
        confusion[(truth["document_type"], payload["document_type"])] += 1

        for nom in CHAMPS_EN_TETE:
            attendu = (truth.get("fields") or {}).get(nom)
            observe = chemin_valeur(payload, nom)
            bon = egal(attendu, observe)
            champs_bons += int(bon)
            champs_total += 1
            famille["champs_bons"] += int(bon)
            famille["champs_total"] += 1
            par_champ[nom]["bons"] += int(bon)
            par_champ[nom]["total"] += 1
            if not bon:
                if attendu is None and observe is not None:
                    categorie = "valeur_inventee"
                    valeurs_inventees += 1
                elif attendu is not None and observe is None:
                    categorie = "champ_manquant"
                else:
                    categorie = "lecture_ambiguo"
                champ_obj = _objet_champ(payload, nom)
                erreurs.append(_erreur(
                    truth, nom, attendu, observe,
                    champ_obj.get("confidence") if champ_obj else None, categorie,
                ))

        for nom in TOTAUX_IMPRIMES:
            attendu = (truth.get("printed_totals") or {}).get(nom)
            if attendu is None:
                continue  # valeur absente de la pièce : rien à mesurer
            observe = chemin_valeur(payload, f"totals.{nom}")
            totaux_total += 1
            if egal(attendu, observe):
                totaux_bons += 1
            else:
                erreurs.append(_erreur(truth, f"printed_{nom}", attendu, observe,
                                       chemin_confiance(payload, f"totals.{nom}"), "total_lecture"))

        attendus = Counter(_tuple_ligne(l) for l in truth.get("lines", []))
        observes = Counter(_tuple_ligne(l) for l in payload.get("lines", []))
        tp_doc = sum((attendus & observes).values())
        fn_doc = sum((attendus - observes).values())
        fp_doc = sum((observes - attendus).values())
        tp += tp_doc
        fn += fn_doc
        fp += fp_doc
        famille["tp"] += tp_doc
        famille["fn"] += fn_doc
        famille["fp"] += fp_doc
        if fn_doc:
            erreurs.append(_erreur(truth, "lines", len(attendus), len(observes), None, "ligne_manquante"))
        if fp_doc:
            erreurs.append(_erreur(truth, "lines", len(attendus), len(observes), None, "ligne_surnumeraire"))

        for chemin, champ_obj in extraction._parcours_champs(payload):
            if chemin not in CRITIQUES or champ_obj.get("missing"):
                continue
            seuil = extraction.seuil(chemin)
            confiance = float(champ_obj.get("confidence", 0.0) or 0.0)
            if confiance < seuil:
                confiances_basses.append(_erreur(
                    truth, chemin, seuil, confiance, confiance, "confiance_basse",
                ))

        attendues = set(truth.get("injected_anomalies", []))
        anomalies_injectees += len(attendues)
        anomalies_detectees += len(attendues & _cueils_anomalies(truth, payload))

        champs_doc_ok = all(
            egal((truth.get("fields") or {}).get(n), chemin_valeur(payload, n))
            for n in CHAMPS_EN_TETE
        )
        lignes_doc_ok = attendus == observes
        totaux_doc_ok = all(
            egal((truth.get("printed_totals") or {}).get(n), chemin_valeur(payload, f"totals.{n}"))
            for n in TOTAUX_IMPRIMES if (truth.get("printed_totals") or {}).get(n) is not None
        )
        type_ok = truth["document_type"] == payload["document_type"]
        critique_revue = any(
            e["document"] == truth["reference"] and e["categorie"] != "confiance_basse"
            for e in erreurs
        )
        if type_ok and champs_doc_ok and lignes_doc_ok and totaux_doc_ok and not critique_revue:
            stp += 1
        famille["stp"] += stp - stp_avant

    precision = tp / (tp + fp) if tp + fp else 0.0
    rappel = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0
    precision_lue = round(precision, 4)
    rappel_lu = round(rappel, 4)
    f1_lu = round(f1, 4)

    # Les erreurs de lecture passent avant les simples alertes de confiance.
    erreurs_triees = sorted(erreurs, key=lambda e: e["categorie"] == "confiance_basse")
    erreurs_triees = erreurs_triees[:30]
    if len(erreurs_triees) < 30:
        erreurs_triees += confiances_basses[:30 - len(erreurs_triees)]

    matrice = [
        {"reel": reel, "preddit": pred, "nombre": nombre}
        for (reel, pred), nombre in sorted(confusion.items())
    ]
    resultat = {
        "modele": extraction.MODELE_DEMO,
        "backend": backend,
        "ocr": ocr_backend,
        "jeu": split or "tous",
        "chaine": "texte parfait (ablation)" if ocr_backend == "rendu" else "chaine reelle (pdfplumber + EasyOCR)",
        "as_of": settings.as_of,
        "graine": settings.graine_demo,
        "documents": len(truths),
        "split": {nom: sum(1 for t in truths if t.get("split") == nom)
                  for nom in ("dev", "validation", "test")},
        "exactitude_champs": round(champs_bons / champs_total, 4) if champs_total else 0.0,
        "exactitude_par_champ": {
            nom: round(v["bons"] / v["total"], 4) if v["total"] else 0.0
            for nom, v in par_champ.items()
        },
        "lignes": {"tp": tp, "fp": fp, "fn": fn,
                   "precision": precision_lue, "rappel": rappel_lu, "f1": f1_lu},
        "exactitude_totaux_imprimes": round(totaux_bons / totaux_total, 4) if totaux_total else 0.0,
        "stp": round(stp / len(truths), 4) if truths else 0.0,
        "rappel_anomalies": round(anomalies_detectees / anomalies_injectees, 4)
        if anomalies_injectees else 0.0,
        "anomalies": {"injectees": anomalies_injectees, "detectees": anomalies_detectees},
        "valeurs_inventees": valeurs_inventees,
        "matrice_confusion": matrice,
        "erreurs_analysees": erreurs_triees,
        "erreurs_brutes": len(erreurs) + len(confiances_basses),
        "erreurs_par_categorie": dict(sorted(Counter(e["categorie"] for e in erreurs).items())),
        "erreurs_par_champ": dict(sorted(Counter(e["champ"] for e in erreurs).items())),
        "alertes_confiance": len(confiances_basses),
        "par_famille": {nom: _resume_famille(f) for nom, f in sorted(familles.items())},
        "referentiel_clients": bool(clients),
        "revue": _resume_revue(jugements),
    }
    if ecrire and dossier is None:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(
            json.dumps(resultat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return resultat


def _resume_famille(f: Mapping[str, int]) -> dict[str, Any]:
    precision = f["tp"] / (f["tp"] + f["fp"]) if f["tp"] + f["fp"] else 0.0
    rappel = f["tp"] / (f["tp"] + f["fn"]) if f["tp"] + f["fn"] else 0.0
    return {
        "documents": f["documents"],
        "exactitude_champs": round(f["champs_bons"] / f["champs_total"], 4) if f["champs_total"] else 0.0,
        "f1_lignes": round(2 * precision * rappel / (precision + rappel), 4) if precision + rappel else 0.0,
        "stp": round(f["stp"] / f["documents"], 4) if f["documents"] else 0.0,
    }


def _objet_champ(payload: Mapping[str, Any], chemin: str) -> Mapping[str, Any] | None:
    objet: Any = payload
    for partie in chemin.split("."):
        if not isinstance(objet, Mapping):
            return None
        objet = objet.get(partie)
    return objet if isinstance(objet, Mapping) else None


def chemin_confiance(payload: Mapping[str, Any], chemin: str) -> float | None:
    objet = _objet_champ(payload, chemin)
    return float(objet.get("confidence", 0.0)) if objet else None


def render_markdown(m: Mapping[str, Any]) -> str:
    lignes = [
        "# Mesures observées — extraction WÉMA",
        "",
        f"- Modèle : `{m['modele']}` · backend `{m['backend']}` · graine {m['graine']} · AS_OF {m['as_of']}",
        f"- Lecture : **{m.get('chaine', 'chaine reelle')}** (OCR `{m.get('ocr', 'auto')}`)",
        f"- Jeu mesuré : **{m.get('jeu', 'tous')}**",
        f"- Corpus : {m['documents']} documents (dev {m['split']['dev']} / "
        f"validation {m['split']['validation']} / test {m['split']['test']})",
        f"- Valeurs inventées : **{m['valeurs_inventees']}**",
        "",
        "| Mesure | Résultat observé |",
        "|---|---:|",
        f"| Exactitude des champs d'en-tête | {m['exactitude_champs']:.1%} |",
        f"| F1 des lignes | {m['lignes']['f1']:.4f} |",
        f"| Exactitude des totaux imprimés extraits | {m['exactitude_totaux_imprimes']:.1%} |",
        f"| Traitement sans correction (STP) | {m['stp']:.1%} |",
        f"| Rappel des signaux d'anomalie | {m['rappel_anomalies']:.1%} "
        f"({m['anomalies']['detectees']}/{m['anomalies']['injectees']}) |",
        "",
        "## Matrice de confusion — type de document",
        "",
        "| Réel | Prédit | Nombre |",
        "|---|---|---:|",
    ]
    for entree in m["matrice_confusion"]:
        lignes.append(f"| {entree['reel']} | {entree['preddit']} | {entree['nombre']} |")
    lignes += ["", "## Par famille de pièce (classes faibles visibles)", "",
               "| Famille | Documents | Champs d'en-tête | F1 lignes | STP |", "|---|---:|---:|---:|---:|"]
    for nom, f in m.get("par_famille", {}).items():
        lignes.append(f"| {nom} | {f['documents']} | {f['exactitude_champs']:.1%} | {f['f1_lignes']:.4f} | {f['stp']:.1%} |")
    lignes += ["", f"Écarts relevés : {m.get('erreurs_par_categorie', {})} · alertes de confiance : {m.get('alertes_confiance', 0)}"]
    r = m.get("revue")
    if r:
        lignes += ["", "## Le seuil fait-il son travail ? (valeurs jugées une à une)", "",
                   f"- Valeurs jugées : {r['valeurs_jugees']} · référentiel clients : "
                   f"{'oui' if m.get('referentiel_clients') else 'non'}",
                   f"- Erreurs attrapées par la revue : **{r['erreurs_attrapees']}/{r['erreurs']}** "
                   f"({r['rappel_revue']:.1%}) · **erreurs silencieuses : {r['erreurs_silencieuses']}**",
                   f"- Fausses alertes (valeur juste envoyée en revue) : {r['fausses_alertes']} "
                   f"({r['taux_fausses_alertes']:.1%} des valeurs justes)", "",
                   "| | En revue | Acceptée |", "|---|---:|---:|"]
        for etat in ("juste", "absente", "fausse"):
            lignes.append(f"| {etat} | {r['matrice'].get(etat + '_revue', 0)} | "
                          f"{r['matrice'].get(etat + '_acceptee', 0)} |")
    lignes += ["", "## 30 points d'attention analysés (écarts puis alertes)", "",
               "| Document | Catégorie | Champ | Attendu | Observé | Confiance |",
               "|---|---|---|---|---|---:|"]
    for erreur in m["erreurs_analysees"]:
        confiance = erreur.get("confiance")
        texte_confiance = "" if confiance is None else f"{float(confiance):.3f}"
        lignes.append(
            f"| {erreur['document']} | {erreur['categorie']} | {erreur['champ']} | "
            f"{erreur['attendu']} | {erreur['observe']} | {texte_confiance} |"
        )
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesure l'extraction sur le corpus annoté")
    parser.add_argument("--backend", default="demo", choices=("demo", "cpu"))
    parser.add_argument("--no-write", action="store_true", help="n'écrit pas metrics.json")
    parser.add_argument("--split", choices=("dev", "validation", "test"), default=None,
                        help="mesure un seul jeu (par défaut : les 120 documents)")
    parser.add_argument("--ocr", default="auto", choices=("auto", "cache", "rendu"),
                        help="auto/cache : chaîne réelle ; rendu : ablation « OCR parfait »")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mesures = evaluer(backend=args.backend,
                      ecrire=not args.no_write and args.ocr != "rendu" and not args.split,
                      ocr_backend=args.ocr, split=args.split)
    print(render_markdown(mesures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
