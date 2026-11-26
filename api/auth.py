"""Gestion des rôles via l'en-tête X-Role (dirigeant | assistante | lecture).

Simulation de contrôle d'accès par rôle pour le prototype WÉMA.
Tout rôle inconnu ou non autorisé est refusé avec 403 Forbidden.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException

VALID_ROLES = ("dirigeant", "assistante", "lecture")


def get_role(x_role: str | None = Header(default="lecture", alias="X-Role")) -> str:
    """Extrait et valide le rôle depuis l'en-tête HTTP X-Role."""
    role = (x_role or "lecture").strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Rôle inconnu : '{role}'. Rôles valides : {', '.join(VALID_ROLES)}.",
        )
    return role


def require_roles(*allowed: str) -> Callable[..., str]:
    """Dépendance FastAPI vérifiant que le rôle courant est autorisé."""
    allowed_set = set(allowed)

    def _checker(x_role: str | None = Header(default="lecture", alias="X-Role")) -> str:
        role = get_role(x_role)
        if role not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=f"Action interdite pour le rôle '{role}'. Rôle requis : {', '.join(sorted(allowed_set))}.",
            )
        return role

    return _checker
