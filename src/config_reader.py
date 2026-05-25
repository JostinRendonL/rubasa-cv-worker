"""
Lectura de la configuración del cargo desde la pestaña "Configuracion".

Mejoras v5.4:
- Cache TTL 5 minutos (antes se re-leía en cada CV → latencia + cuota API)
- Lectura de `delitos_graves` configurable (antes hardcoded en main.py)
- Defensa contra errores: si Sheets falla, usa defaults sensatos
"""
from __future__ import annotations

import os
import time
import threading
from typing import Any

# Cache singleton de la config
_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()

# TTL del cache (5 min — balance entre frescura y latencia)
CONFIG_CACHE_TTL = int(os.getenv("CONFIG_CACHE_TTL_SEG", "300"))


# Lista de delitos por defecto si la Sheet no lo configura.
# Configurable desde la hoja Configuracion en la fila "delitos_graves" (CSV o pipe).
DELITOS_GRAVES_DEFAULT = [
    "ASESINATO", "HOMICIDIO", "FEMICIDIO", "PARRICIDIO", "SICARIATO",
    "DELINCUENCIA ORGANIZADA", "ASOCIACION ILICITA",
    "VIOLACION", "ABUSO SEXUAL", "ABUSO DE MENORES", "ESTUPRO",
    "ROBO", "ROBO AGRAVADO", "ASALTO",
    "NARCOTRAFICO", "TRAFICO DE DROGAS", "TENENCIA DE DROGAS", "ESTUPEFACIENTES",
    "TENENCIA DE ARMAS", "PORTE ILEGAL",
    "SECUESTRO", "EXTORSION", "PLAGIO", "TRATA DE PERSONAS",
    "TERRORISMO",
    "LAVADO DE ACTIVOS",
    "PECULADO", "ENRIQUECIMIENTO ILICITO",
]

CONFIG_DEFAULT = {
    "cargo": "Auxiliar de Limpieza",
    "experiencia_minima_años": "1",
    "educacion_minima": "Bachiller (por inferencia)",
    "movilidad": "bonus",
    "disponibilidad": "informativo",
    "palabras_clave_plus": "industrial, hospitalario, empresa, corporativo",
    "palabras_descarte_educacion": "solo primaria, no terminé el colegio, primaria completa, dejé el colegio",
}


def leer_configuracion(spreadsheet, nombre_pestaña="Configuracion") -> dict:
    """
    Lee los criterios del cargo desde la pestaña Configuracion.
    Cacheado por CONFIG_CACHE_TTL (default 5 min) para no estresar la API
    cuando hay un batch de CVs.
    """
    global _cache, _cache_ts

    ahora = time.time()
    # Cache hit
    if _cache is not None and (ahora - _cache_ts) < CONFIG_CACHE_TTL:
        return _cache

    with _cache_lock:
        # Double-checked locking
        if _cache is not None and (ahora - _cache_ts) < CONFIG_CACHE_TTL:
            return _cache

        try:
            hoja = spreadsheet.worksheet(nombre_pestaña)
            filas = hoja.get_all_values()

            config: dict[str, Any] = {}
            for fila in filas:
                if len(fila) >= 2 and fila[0].strip():
                    clave = fila[0].strip().lower().replace(" ", "_")
                    valor = fila[1].strip()
                    config[clave] = valor

            if config:
                _cache    = config
                _cache_ts = ahora
                return _cache
        except Exception as e:
            print(f"[config_reader] error leyendo Sheet: {e} — usando defaults")

        # Fallback
        _cache    = dict(CONFIG_DEFAULT)
        _cache_ts = ahora
        return _cache


def obtener_delitos_graves(spreadsheet=None) -> list[str]:
    """
    Devuelve la lista de delitos considerados graves para alertas Telegram
    y semáforo CRÍTICO. Configurable desde Sheet con la clave `delitos_graves`
    (valores separados por coma o pipe).

    Si no hay Sheet o la clave no existe → usa DELITOS_GRAVES_DEFAULT.
    """
    if spreadsheet is None:
        return list(DELITOS_GRAVES_DEFAULT)

    config = leer_configuracion(spreadsheet)
    raw = config.get("delitos_graves", "")
    if not raw:
        return list(DELITOS_GRAVES_DEFAULT)

    # Parsear "ASESINATO, HOMICIDIO | ROBO" → ["ASESINATO", "HOMICIDIO", "ROBO"]
    separadores = [",", "|", ";"]
    lista = [raw]
    for sep in separadores:
        nueva = []
        for item in lista:
            nueva.extend(item.split(sep))
        lista = nueva
    return [d.strip().upper() for d in lista if d.strip()]


def invalidar_cache() -> None:
    """Fuerza re-lectura en la próxima llamada. Útil para tests o si admin edita."""
    global _cache, _cache_ts
    with _cache_lock:
        _cache    = None
        _cache_ts = 0.0
