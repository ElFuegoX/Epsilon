"""Charge le schéma SQL depuis schema.sql (une seule source de vérité)."""

from pathlib import Path

SCHEMA_SQL = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
