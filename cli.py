"""Ligne de commande WÉMA : vérifier, rejouer la démonstration, piloter le parcours.

    python -m cli verify                      chaîne d'audit, PDF des factures, continuité des numéros
    python -m cli demo                        parcours complet de DEV-2026-041 sur une base neuve, pas à pas
    python -m cli importer <fichier> [--role assistante]
    python -m cli extraire <document_id>
    python -m cli reprendre                   reprise après interruption (pièces IMPORTÉ / EN_ATTENTE_IA)
    python -m cli etat <draft_id>             anomalies, confirmations, statut de la pièce
    python -m cli clean                       supprime les fichiers générés (PDF, boîte d'envoi)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import db
from config import settings


def _afficher(titre: str, valeur: Any = None) -> None:
    print(f"\n> {titre}")
    if valeur is not None:
        print("  " + json.dumps(valeur, ensure_ascii=False, default=str, indent=1).replace("\n", "\n  "))


def verify(conn: Any) -> int:
    from domain import audit, invoices, numbering

    ok_audit, erreurs = audit.verifier_chaine(conn)
    total = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    print(f"Chaîne d'audit : {'OK' if ok_audit else 'ALTÉRÉE'} ({total} événements)")
    for erreur in erreurs:
        print(f"  {erreur}")
    ok_pdf = True
    for facture in conn.execute("SELECT id, numero, hash_pdf FROM invoices ORDER BY numero"):
        if facture["hash_pdf"] == "HISTORIQUE_SANS_PDF":
            continue
        conforme = invoices.verifier_pdf(conn, facture["id"])
        ok_pdf &= conforme
        print(f"PDF {facture['numero']} : {'OK' if conforme else 'DIFFÉRENT DU SNAPSHOT'}")
    ok_num, erreurs_num = numbering.verifier_continuite(conn)
    print(f"Numérotation continue : {'OK' if ok_num else 'ROMPUE'}")
    for erreur in erreurs_num:
        print(f"  {erreur}")
    return 0 if (ok_audit and ok_pdf and ok_num) else 1


def _base_demo() -> Any:
    from seed import GENERE

    chemin = str(Path(tempfile.mkdtemp()) / "demo.db")
    db.initialize(chemin)
    conn = db.connect(chemin)
    with db.transaction(conn):
        for c in json.loads((GENERE / "clients.json").read_text(encoding="utf-8")):
            conn.execute(
                "INSERT INTO clients(id, raison_sociale, ifu, adresse, ville, telephone, conditions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c["id"], c["raison_sociale"], c["ifu"], c["adresse"], c["ville"], c["telephone"],
                 c["conditions"]))
        for a in json.loads((GENERE / "items.json").read_text(encoding="utf-8")):
            conn.execute(
                "INSERT INTO items(id, reference, designation, unite, prix_catalogue, famille) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (a["id"], a["reference"], a["designation"], a["unite"], a["prix_catalogue"], a["famille"]))
    return conn


def demo() -> int:
    """Rejoue le scénario du jury sur une base temporaire : la base de démo n'est pas touchée."""
    from domain import brouillon, invoices, parcours
    from seed import GENERE

    piece = GENERE / "demo" / "devis" / "DEV-2026-041.pdf"
    if not piece.is_file():
        print("Corpus absent : lancer d'abord `python -m seed --as-of 2026-11-25`.")
        return 1
    conn = _base_demo()

    _afficher("1. Import du devis DEV-2026-041, puis réimport du même fichier")
    document = parcours.importer(conn, piece)["document_id"]
    print(f"  pièce {document} ; second import : doublon = {parcours.importer(conn, piece)['doublon']}")

    _afficher("2. Extraction et brouillon")
    extrait = parcours.extraire(conn, document)
    draft = extrait["draft_id"]
    print(f"  {extrait['brouillon']}")

    _afficher("3. Contrôles", [(a["code"], a["severite"], a["champ"]) for a in parcours.controler(conn, draft)])
    _afficher("   Message de clarification à envoyer", parcours.message_clarification(conn, draft))
    print(f"  Aperçu PDF du brouillon : {parcours.apercu_pdf(conn, draft)['chemin']}")

    _afficher("4. Validation tentée trop tôt")
    try:
        parcours.valider(conn, draft)
    except brouillon.ConfirmationsEnAttente as erreur:
        print(f"  refusée : {erreur}")

    _afficher("5. Décisions humaines tracées")
    brouillon.confirmer(conn, draft, "totals.printed_ht", "dirigeant",
                        motif="total imprimé faux : écart traité par ARITHMETIC_MISMATCH")
    parcours.renseigner_ifu(conn, "cli-001", "3201912345678", role="dirigeant", motif="réponse du client")
    parcours.modifier_brouillon(conn, draft, role="assistante", date_echeance="2026-12-25",
                                motif="échéance confirmée par le client")
    parcours.exclure_ligne(conn, draft, 3, role="assistante", motif="installation non livrée")
    parcours.resoudre(conn, draft, "ARITHMETIC_MISMATCH", role="dirigeant", motif="addition fausse sur le devis",
                      avant="1 020 000 imprimé", apres="980 000 recalculé")
    print("  total confirmé, IFU obtenu, échéance saisie, installation exclue, écart expliqué")

    _afficher("6. Double validation (double clic)")
    premier, second = parcours.valider(conn, draft), parcours.valider(conn, draft)
    print(f"  {premier['numero']} / {second['numero']} - identiques : {premier == second} - "
          f"HT {premier['total_ht']} TVA {premier['total_tva']} TTC {premier['total_ttc']}")
    print(f"  PDF : {Path(settings.data_dir) / 'pdf' / (premier['numero'] + '.pdf')}")

    _afficher("7. Tentative de modification de la facture validée")
    try:
        conn.execute("UPDATE invoices SET total_ttc=1 WHERE id=?", (premier["invoice_id"],))
    except Exception as erreur:  # noqa: BLE001 - on montre le refus, quel qu'il soit
        print(f"  refusée : {erreur}")

    _afficher("8. Émission simulée sur WhatsApp")
    emission = parcours.emettre(conn, premier["invoice_id"], "whatsapp_sim", role="assistante")
    print(f"  {emission['message']['texte']}\n  -> {emission['message']['fichier']}")

    _afficher("9. Avoir total")
    print(f"  {parcours.avoir(conn, premier['invoice_id'], motif='annulation demandée', total=True)}")
    print(f"  registre : {[(f['numero'], f['statut']) for f in invoices.registre(conn)]}")

    _afficher("10. Vérification")
    return verify(conn)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="WÉMA - ligne de commande")
    sous = parser.add_subparsers(dest="commande", required=True)
    for nom in ("verify", "demo", "clean", "reprendre"):
        sous.add_parser(nom)
    p = sous.add_parser("importer")
    p.add_argument("fichier")
    p.add_argument("--role", default="assistante")
    sous.add_parser("extraire").add_argument("document_id")
    sous.add_parser("etat").add_argument("draft_id")
    args = parser.parse_args(argv)

    if args.commande == "demo":
        return demo()
    if args.commande == "clean":
        for dossier in ("pdf", "outbox"):
            shutil.rmtree(Path(settings.data_dir) / dossier, ignore_errors=True)
        print("PDF et boîte d'envoi simulée supprimés (base conservée ; `python -m seed --reset` pour repartir).")
        return 0

    from domain import parcours

    db.initialize()
    conn = db.connect()
    if args.commande == "verify":
        return verify(conn)
    if args.commande == "importer":
        resultat = parcours.importer(conn, args.fichier, role=args.role)
        if not resultat["doublon"]:
            resultat |= parcours.extraire(conn, resultat["document_id"], role=args.role)
        _afficher("Import", resultat)
    elif args.commande == "extraire":
        _afficher("Extraction", parcours.extraire(conn, args.document_id))
    elif args.commande == "reprendre":
        _afficher("Reprise", parcours.reprendre(conn))
    elif args.commande == "etat":
        _afficher("État", parcours.etat(conn, args.draft_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
