"""Numérotation transactionnelle et continue.

À appeler impérativement dans une transaction BEGIN IMMEDIATE : un seul
validateur à la fois, aucun numéro consommé si la transaction échoue.
"""

from __future__ import annotations

import sqlite3

from config import settings


def formatter(prefixe: str, annee: int, valeur: int) -> str:
    return f"{prefixe}-{annee}-{valeur:05d}"


def reserver(
    conn: sqlite3.Connection,
    prefixe: str | None = None,
    serie: str | None = None,
    annee: int | None = None,
) -> str:
    """Incrémente la séquence et renvoie le numéro unique."""
    prefixe = prefixe or settings.prefixe_facture
    serie = serie or settings.serie_defaut
    annee = annee if annee is not None else settings.annee
    row = conn.execute(
        "SELECT prochaine FROM number_sequences WHERE serie=? AND annee=? AND prefixe=?",
        (serie, annee, prefixe),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO number_sequences(serie, annee, prefixe, prochaine, version) VALUES (?, ?, ?, 1, 0)",
            (serie, annee, prefixe),
        )
        valeur = 1
    else:
        valeur = int(row["prochaine"])
    conn.execute(
        "UPDATE number_sequences SET prochaine=?, version=version+1 "
        "WHERE serie=? AND annee=? AND prefixe=?",
        (valeur + 1, serie, annee, prefixe),
    )
    return formatter(prefixe, annee, valeur)


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


def verifier_continuite(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    """Aucun trou, aucun doublon, aucun numéro réutilisé."""
    erreurs: list[str] = []
    rows = conn.execute(
        "SELECT numero FROM invoices WHERE serie=? AND annee=? ORDER BY numero",
        (settings.serie_defaut, settings.annee),
    ).fetchall()
    numeros = [r["numero"] for r in rows]
    if len(numeros) != len(set(numeros)):
        erreurs.append("numéros dupliqués")
    for i, numero in enumerate(numeros, start=1):
        if numero != formatter(settings.prefixe_facture, settings.annee, i):
            erreurs.append(f"trou ou ordre invalide à la position {i}: {numero}")
            break
    return (not erreurs), erreurs
