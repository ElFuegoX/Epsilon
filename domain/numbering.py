"""Numérotation transactionnelle et continue.

À appeler impérativement dans une transaction BEGIN IMMEDIATE : un seul
validateur à la fois, aucun numéro consommé si la transaction échoue.
`apercu()` est la seule fonction autorisée hors transaction : elle ne écrit
jamais et ne consomme aucun numéro.
"""

from __future__ import annotations

import sqlite3

from config import settings


class TransactionRequise(RuntimeError):
    """`reserver()` a été appelé hors transaction explicite."""


class SequenceInvalide(ValueError):
    """Le compteur de séquence est incohérent."""


def formatter(prefixe: str, annee: int, valeur: int) -> str:
    """Format fiscal `FAC-AAAA-00000` / `AV-AAAA-00000`."""
    if not prefixe or not str(prefixe).isalpha():
        raise ValueError("préfixe de série invalide")
    if not (1000 <= int(annee) <= 9999):
        raise ValueError("année invalide")
    if int(valeur) < 1:
        raise ValueError("un numéro fiscal commence à 1")
    return f"{prefixe}-{int(annee)}-{int(valeur):05d}"


def _exiger_transaction(conn: sqlite3.Connection) -> None:
    if not conn.in_transaction:
        raise TransactionRequise(
            "reserver() doit être appelé dans BEGIN IMMEDIATE (voir db.transaction)"
        )


def reserver(
    conn: sqlite3.Connection,
    prefixe: str | None = None,
    serie: str | None = None,
    annee: int | None = None,
) -> str:
    """Incrémente la séquence et renvoie le numéro unique.

    L'incrément est fait en une seule instruction après `INSERT OR IGNORE` :
    aucun état intermédiaire visible, aucune lecture avant écriture.
    Un rollback annule l'incrément, donc aucun numéro n'est consommé.
    """
    _exiger_transaction(conn)
    prefixe = prefixe or settings.prefixe_facture
    serie = serie or settings.serie_defaut
    annee = annee if annee is not None else settings.annee
    conn.execute(
        "INSERT OR IGNORE INTO number_sequences(serie, annee, prefixe, prochaine, version) "
        "VALUES (?, ?, ?, 1, 0)",
        (serie, annee, prefixe),
    )
    conn.execute(
        "UPDATE number_sequences SET prochaine=prochaine+1, version=version+1 "
        "WHERE serie=? AND annee=? AND prefixe=?",
        (serie, annee, prefixe),
    )
    row = conn.execute(
        "SELECT prochaine FROM number_sequences WHERE serie=? AND annee=? AND prefixe=?",
        (serie, annee, prefixe),
    ).fetchone()
    if row is None or int(row["prochaine"]) < 2:
        raise SequenceInvalide("compteur de séquence incohérent")
    return formatter(prefixe, annee, int(row["prochaine"]) - 1)


def apercu(
    conn: sqlite3.Connection,
    prefixe: str | None = None,
    serie: str | None = None,
    annee: int | None = None,
) -> str:
    """Lecture seule : numéro prévisualisé, non consommé."""
    prefixe = prefixe or settings.prefixe_facture
    serie = serie or settings.serie_defaut
    annee = annee if annee is not None else settings.annee
    row = conn.execute(
        "SELECT prochaine FROM number_sequences WHERE serie=? AND annee=? AND prefixe=?",
        (serie, annee, prefixe),
    ).fetchone()
    return formatter(prefixe, annee, int(row["prochaine"]) if row else 1)


def verifier_continuite(
    conn: sqlite3.Connection,
    serie: str | None = None,
    annee: int | None = None,
) -> tuple[bool, list[str]]:
    """Aucun trou, aucun doublon sur les factures **et** les avoirs.

    Vérifie aussi que le compteur correspond au dernier numéro utilisé plus un.
    """
    serie = serie or settings.serie_defaut
    annee = annee if annee is not None else settings.annee
    erreurs: list[str] = []
    for table, prefixe in (
        ("invoices", settings.prefixe_facture),
        ("credit_notes", settings.prefixe_avoir),
    ):
        numeros = [
            r["numero"]
            for r in conn.execute(
                f"SELECT numero FROM {table} WHERE serie=? AND annee=? ORDER BY numero",
                (serie, annee),
            )
        ]
        if len(numeros) != len(set(numeros)):
            erreurs.append(f"{prefixe}: numéros dupliqués")
        for i, numero in enumerate(numeros, start=1):
            if numero != formatter(prefixe, annee, i):
                erreurs.append(f"{prefixe}: trou ou ordre invalide à la position {i}: {numero}")
                break
        rang = conn.execute(
            "SELECT prochaine FROM number_sequences WHERE serie=? AND annee=? AND prefixe=?",
            (serie, annee, prefixe),
        ).fetchone()
        if rang is not None and int(rang["prochaine"]) != len(numeros) + 1:
            erreurs.append(
                f"{prefixe}: séquence à {rang['prochaine']}, attendu {len(numeros) + 1}"
            )
    return (not erreurs), erreurs
