"""
Multi-tenant — prep para vender el sistema a varias empresas.

ESTADO ACTUAL (v5.5):
- Single-tenant: una sola organización (Rubasa Facility Services).
- Toda la config viene de env vars: SHEET_ID, SA_JSON, BG_API_URL, etc.

ESTADO FUTURO (v6.x cuando entre el cliente #2):
- Multi-tenant: cada organización tiene su config independiente.
- Cada webhook se enruta a la organización correcta usando un identificador
  (sub-domain, header, query param, o el Sheet emisor).

ESTRATEGIA DE MIGRACIÓN (compatible hacia atrás):

1. Esta v5.5 introduce el concepto de "tenant" SIN romper el flujo actual.
   resolver_tenant() siempre devuelve "rubasa" (el cliente piloto).

2. Cuando entre el cliente #2, agregar un row a TENANTS y cambiar
   resolver_tenant() para que use el identificador del payload.

3. Después, cuando haya 5-10 tenants, migrar el dict en memoria a SQLite
   y agregar un admin UI para CRUD.

Para el diseño completo ver: ~/Desktop/md claude/JR_AUTOMATA_ROADMAP.md
sección "Multi-tenant".
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class TenantConfig:
    """Configuración de una organización cliente."""
    id:               str               # identificador único (slug)
    nombre:           str               # razón social
    sheet_id:         str               # Google Sheet de candidatos
    drive_folder_id:  str = ""          # carpeta donde se suben los CVs (opcional)
    bg_api_url:       str = ""          # opcional override
    bg_api_key:       str = ""          # opcional override
    webhook_secret:   str = ""          # opcional override
    branding: dict[str, str] = field(default_factory=lambda: {
        "color_primary":   "#0F2C5C",
        "color_accent":    "#1E5BFA",
        "logo_url":        "",
    })

    @classmethod
    def from_env(cls, tenant_id: str = "rubasa") -> "TenantConfig":
        """
        Construye TenantConfig desde env vars (modo single-tenant).
        Cuando entre multi-tenant, esto se reemplazará por lookup en
        un dict/SQLite con todos los tenants.
        """
        return cls(
            id              = tenant_id,
            nombre          = os.getenv("TENANT_NOMBRE", "Rubasa Facility Services"),
            sheet_id        = os.getenv("SHEET_ID", ""),
            drive_folder_id = os.getenv("DRIVE_FOLDER_ID", ""),
            bg_api_url      = os.getenv("BG_API_URL", ""),
            bg_api_key      = os.getenv("BG_API_KEY", ""),
            webhook_secret  = os.getenv("WEBHOOK_SECRET", ""),
        )


# Registro en memoria de tenants. En multi-tenant esto se reemplaza por SQLite.
_TENANTS: dict[str, TenantConfig] = {}


def _init_tenants() -> None:
    """Carga el tenant default desde env. Llamado en arranque."""
    global _TENANTS
    default = TenantConfig.from_env()
    _TENANTS[default.id] = default
    print(f"[tenant] cargado tenant default: {default.id} ({default.nombre})")


_init_tenants()


def resolver_tenant(payload: dict | None = None,
                    header_tenant: str | None = None) -> TenantConfig:
    """
    Resuelve qué tenant atender para un request.

    Single-tenant (hoy): siempre devuelve el tenant default.
    Multi-tenant (futuro):
      - Si payload trae `tenant_id`: usar ese
      - Si header `X-Tenant-ID`: usar ese
      - Sino: 400 Bad Request (en lugar de asumir default)
    """
    # Modo single-tenant — solo hay uno
    if len(_TENANTS) == 1:
        return next(iter(_TENANTS.values()))

    # Modo multi-tenant (cuando entre cliente #2)
    tid = (payload or {}).get("tenant_id") or header_tenant
    if not tid:
        raise ValueError("multi-tenant activo: falta tenant_id en payload o X-Tenant-ID")

    if tid not in _TENANTS:
        raise ValueError(f"tenant '{tid}' no encontrado")
    return _TENANTS[tid]


def listar_tenants() -> list[dict]:
    """Devuelve la lista de tenants registrados (para admin UI futuro)."""
    return [
        {"id": t.id, "nombre": t.nombre, "sheet_id": t.sheet_id[:8] + "..."}
        for t in _TENANTS.values()
    ]


def agregar_tenant(config: TenantConfig) -> None:
    """API para registrar un nuevo tenant. En multi-tenant esto va a SQLite."""
    _TENANTS[config.id] = config
    print(f"[tenant] agregado: {config.id} ({config.nombre})")
