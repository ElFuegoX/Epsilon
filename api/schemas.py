"""Modèles Pydantic pour les entrées/sorties de l'API WÉMA."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DocumentTextIn(BaseModel):
    nom: str = Field(..., min_length=1, description="Nom logique de la pièce ou du message")
    texte: str = Field(..., min_length=1, description="Contenu texte brut (ex. message WhatsApp)")
    type: Optional[str] = Field(default=None, description="devis | commande | bon_livraison | message")
    canal: Optional[str] = Field(default="whatsapp_sim")


class DraftPatchIn(BaseModel):
    client: Optional[str] = None
    date_piece: Optional[str] = None
    date_echeance: Optional[str] = None
    conditions: Optional[str] = None
    statut: Optional[str] = None


class LineCreateIn(BaseModel):
    description: str = Field(..., min_length=1)
    quantite: str | int | float = Field(default=1)
    unite: str = Field(default="pcs")
    pu_ht: int = Field(default=0, ge=0)
    remise: int = Field(default=0, ge=0)
    remise_pct: int = Field(default=0, ge=0, le=100)
    tax_code: str = Field(default="TVA18")
    item: Optional[str] = None
    famille: Optional[str] = None


class LinePatchIn(BaseModel):
    description: Optional[str] = None
    quantite: Optional[str | int | float] = None
    unite: Optional[str] = None
    pu_ht: Optional[int] = Field(default=None, ge=0)
    remise: Optional[int] = Field(default=None, ge=0)
    remise_pct: Optional[int] = Field(default=None, ge=0, le=100)
    tax_code: Optional[str] = None
    item: Optional[str] = None
    famille: Optional[str] = None


class AnomalyResolveIn(BaseModel):
    resolution: Optional[str] = Field(default="Résolu manuellement")
    justification: Optional[str] = None


class IssueInvoiceIn(BaseModel):
    channel: Optional[str] = Field(default=None, description="email_sim | whatsapp_sim | telechargement")
    canal: Optional[str] = Field(default=None, description="Alias francophone de channel")
    destinataire: Optional[str] = None
    telephone: Optional[str] = None


class CreditNoteLineIn(BaseModel):
    numero: int
    description: str = ""
    quantite: str | int | float = 1
    unite: str = "pcs"
    pu_ht: int = 0
    remise: int = 0
    remise_pct: int = 0
    taux_bp: int = 1800


class CreditNoteCreateIn(BaseModel):
    motif: str = Field(..., min_length=1)
    total: bool = Field(default=False)
    lignes: Optional[list[CreditNoteLineIn]] = None


class ClientCreateIn(BaseModel):
    raison_sociale: str = Field(..., min_length=1)
    ifu: Optional[str] = None
    adresse: Optional[str] = None
    ville: Optional[str] = None
    telephone: Optional[str] = None
    conditions: Optional[str] = None


class ItemCreateIn(BaseModel):
    reference: str = Field(..., min_length=1)
    designation: str = Field(..., min_length=1)
    unite: str = Field(default="pcs")
    prix_catalogue: int = Field(..., ge=0)
    famille: str = Field(default="GENERAL")


class HealthOut(BaseModel):
    status: str
    version: str
    ai_backend: str
    as_of: str
    simulation: bool = True


class GenericDictOut(BaseModel):
    data: dict[str, Any]
