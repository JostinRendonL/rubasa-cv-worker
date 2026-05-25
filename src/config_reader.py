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

# Cache por nombre de pestaña (multi-vacante v5.6+):
# {"Configuracion": (config_dict, timestamp), "Config_AuxLimpieza": (...), ...}
_cache: dict[str, tuple[dict, float]] = {}
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


def _leer_pestaña_raw(spreadsheet, nombre_pestaña: str) -> dict | None:
    """Lee una pestaña key-value (col A = clave, col B = valor). None si no existe o vacía."""
    try:
        hoja = spreadsheet.worksheet(nombre_pestaña)
    except Exception:
        return None
    try:
        filas = hoja.get_all_values()
    except Exception as e:
        print(f"[config_reader] error leyendo '{nombre_pestaña}': {e}")
        return None

    config: dict[str, Any] = {}
    for fila in filas:
        if len(fila) >= 2 and fila[0].strip():
            clave = fila[0].strip().lower().replace(" ", "_")
            valor = fila[1].strip()
            config[clave] = valor
    return config or None


def leer_configuracion(spreadsheet, nombre_pestaña: str = "Configuracion") -> dict:
    """
    Lee los criterios del cargo desde una pestaña key-value.

    Cache por nombre de pestaña (multi-vacante): cada Config_<Vacante> tiene su
    propia entrada en _cache, así no se cruzan vacantes.

    Fallback en cascada:
      1. Pestaña pedida (ej. Config_AuxLimpieza)
      2. Pestaña global "Configuracion" (si la pedida no existe)
      3. CONFIG_DEFAULT (si nada existe en el Sheet)
    """
    ahora = time.time()
    # Cache hit
    entry = _cache.get(nombre_pestaña)
    if entry and (ahora - entry[1]) < CONFIG_CACHE_TTL:
        return entry[0]

    with _cache_lock:
        # Double-checked
        entry = _cache.get(nombre_pestaña)
        if entry and (ahora - entry[1]) < CONFIG_CACHE_TTL:
            return entry[0]

        # 1) intentar la pestaña pedida
        config = _leer_pestaña_raw(spreadsheet, nombre_pestaña)

        # 2) si no existe y NO es la global, intentar la global como fallback
        if config is None and nombre_pestaña != "Configuracion":
            config = _leer_pestaña_raw(spreadsheet, "Configuracion")
            if config:
                print(f"[config_reader] '{nombre_pestaña}' no existe — usando 'Configuracion' como fallback")

        # 3) fallback final a defaults hardcoded
        if config is None:
            print(f"[config_reader] sin Sheet config — usando CONFIG_DEFAULT")
            config = dict(CONFIG_DEFAULT)

        _cache[nombre_pestaña] = (config, ahora)
        return config


def obtener_delitos_graves(spreadsheet=None, nombre_pestaña: str = "Configuracion") -> list[str]:
    """
    Devuelve la lista de delitos considerados graves para alertas Telegram
    y semáforo CRÍTICO. Configurable desde Sheet con la clave `delitos_graves`
    (valores separados por coma o pipe).

    Si no hay Sheet o la clave no existe → usa DELITOS_GRAVES_DEFAULT.
    Acepta nombre_pestaña opcional para soportar multi-vacante.
    """
    if spreadsheet is None:
        return list(DELITOS_GRAVES_DEFAULT)

    config = leer_configuracion(spreadsheet, nombre_pestaña)
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


def invalidar_cache(nombre_pestaña: str | None = None) -> None:
    """Fuerza re-lectura en la próxima llamada.

    Si nombre_pestaña se especifica, solo invalida esa entrada.
    Si es None, invalida todo (útil en tests).
    """
    with _cache_lock:
        if nombre_pestaña is None:
            _cache.clear()
        else:
            _cache.pop(nombre_pestaña, None)
