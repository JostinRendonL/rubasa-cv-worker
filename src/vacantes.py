"""
Multi-vacante: helpers para slugificar y nombrar pestañas del Sheet.

Convención:
  - El Apps Script de cada Form envía `vacante: "aux_limpieza"` (slug snake_case).
  - El cv-worker calcula los nombres de pestaña a partir del slug:
       slug "aux_limpieza"  →  hoja Candidatos: "Candidatos_AuxLimpieza"
                            →  hoja Config:     "Config_AuxLimpieza"
  - Si NO se envía vacante (slug vacío) → fallback al sistema mono-vacante:
       hojas "Candidatos" y "Configuracion" (compatibilidad pre-v5.6).
"""
from __future__ import annotations

import re
import unicodedata


# Slug por defecto cuando el Form no envía vacante (compat pre-multi-vacante)
SLUG_DEFAULT = ""

# Regex para validar slug entrante (anti-inyección de nombre de pestaña)
_SLUG_REGEX = re.compile(r"^[a-z0-9_]{1,40}$")


def slugify(texto: str) -> str:
    """Convierte texto humano a slug snake_case ASCII.

    Ejemplos:
      "Auxiliar de Limpieza"  → "auxiliar_de_limpieza"
      "Chofer / Conductor"    → "chofer_conductor"
      "Jardinería"            → "jardineria"
    """
    if not texto:
        return ""
    # Normalizar tildes (NFKD descompone, encode ASCII descarta los combinings)
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = texto.lower().strip()
    # Reemplazar todo lo que no sea alfanumérico por underscore
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    # Colapsar underscores múltiples y quitar de los bordes
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto[:40]


def validar_slug(slug: str) -> str:
    """Valida que el slug recibido del Form sea seguro para usar como nombre de pestaña.

    Retorna el slug validado (en lowercase), o "" si es inválido (→ fallback default).
    No lanza excepciones — best-effort para no romper el webhook.
    """
    if not slug or not isinstance(slug, str):
        return SLUG_DEFAULT
    s = slug.strip().lower()
    if not _SLUG_REGEX.match(s):
        return SLUG_DEFAULT
    return s


def slug_a_pascal(slug: str) -> str:
    """Convierte slug snake_case a PascalCase para nombres de pestañas.

    Ejemplos:
      "aux_limpieza"  → "AuxLimpieza"
      "supervisores"  → "Supervisores"
      ""              → ""
    """
    if not slug:
        return ""
    return "".join(parte.capitalize() for parte in slug.split("_") if parte)


def nombre_hoja_candidatos(slug: str) -> str:
    """Nombre de la pestaña donde escribir los resultados de candidatos."""
    s = validar_slug(slug)
    if not s:
        return "Candidatos"                       # legacy / fallback
    return f"Candidatos_{slug_a_pascal(s)}"


def nombre_hoja_config(slug: str) -> str:
    """Nombre de la pestaña de configuración para esta vacante."""
    s = validar_slug(slug)
    if not s:
        return "Configuracion"                    # legacy / fallback
    return f"Config_{slug_a_pascal(s)}"


def etiqueta_legible(slug: str) -> str:
    """Etiqueta lectura humana del slug (para logs, emails, etc.).

    "aux_limpieza" → "Aux Limpieza" · "" → "(global)"
    """
    s = validar_slug(slug)
    if not s:
        return "(global)"
    return " ".join(p.capitalize() for p in s.split("_") if p)
