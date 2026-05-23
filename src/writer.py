import random
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# ── Zona horaria Ecuador ──────────────────────────────────────────────────────
_TZ_ECUADOR = ZoneInfo("America/Guayaquil")

# ── Locks para escritura concurrente ─────────────────────────────────────────
_lock_candidatos = threading.Lock()
_lock_logs       = threading.Lock()
_lock_config     = threading.Lock()


def _ahora() -> str:
    """Hora actual en Ecuador (UTC-5)."""
    return datetime.now(_TZ_ECUADOR).strftime("%d/%m/%Y %H:%M")


# ── Constantes visuales ───────────────────────────────────────────────────────

EMOJIS = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}

# ── Candidatos: 19 columnas (A–S) — Rediseño v5.1 ────────────────────────────
# Reorganizadas en bloques lógicos:
#   IDENTIDAD (A-E) | VEREDICTO (F-G) | VERIFICACIONES OFICIALES (H-I) |
#   CV (J-L) | DISPONIBILIDAD (M-N) | ANÁLISIS IA (O-R) | ARCHIVO (S)
HEADERS_CANDIDATOS = [
    "Fecha/Hora",                # A
    "Nombre",                    # B
    "Cédula",                    # C
    "Teléfono",                  # D
    "Email",                     # E
    "🚦 Semáforo",               # F  ← con fondo de color
    "Razón Veredicto",           # G
    "🎓 Bachiller (Min. Educ.)", # H  ← oficial
    "⚖️ Procesos Judiciales",    # I  ← SATJE
    "Educación (CV)",            # J
    "Años Exp.",                 # K
    "Experiencia",               # L
    "Disponibilidad",            # M
    "Movilidad",                 # N
    "Resumen",                   # O
    "⭐ Potencial",              # P
    "Preguntas Entrevista",      # Q
    "Alertas",                   # R
    "📎 CV",                     # S
]

ANCHOS_COLUMNAS = [
    130,  # A  Fecha/Hora
    200,  # B  Nombre
    110,  # C  Cédula
    110,  # D  Teléfono
    200,  # E  Email
    130,  # F  🚦 Semáforo (centrado, con bg dinámico)
    280,  # G  Razón Veredicto (wrap)
    260,  # H  Bachiller (Min. Educ.) (wrap)
    280,  # I  Procesos Judiciales (wrap)
    240,  # J  Educación CV (wrap)
     75,  # K  Años Exp.
    280,  # L  Experiencia (wrap)
    170,  # M  Disponibilidad (wrap)
     85,  # N  Movilidad
    320,  # O  Resumen (wrap)
    280,  # P  ⭐ Potencial (wrap)
    320,  # Q  Preguntas Entrevista (wrap)
    240,  # R  Alertas (wrap)
     80,  # S  📎 CV (hyperlink)
]

# Índices basados en 0
COLS_WRAP   = [6, 7, 8, 9, 11, 12, 14, 15, 16, 17]  # G, H, I, J, L, M, O, P, Q, R
COLS_CENTER = [5, 10, 13, 18]                       # F, K, N, S

NUM_COLS = len(HEADERS_CANDIDATOS)        # 19
COL_FIN  = chr(ord("A") + NUM_COLS - 1)   # "S"

# Índices clave (basados en 0)
IDX_SEMAFORO     = 5    # F
IDX_POTENCIAL    = 15   # P
IDX_CV_LINK      = 18   # S

# ── Logs: 6 columnas (A–F) ───────────────────────────────────────────────────
HEADERS_LOGS  = ["Fecha/Hora", "Nivel", "Evento", "Detalle", "IA Utilizada", "Costo USD"]
ANCHOS_LOGS   = [130, 95, 220, 380, 200, 90]
NUM_COLS_LOGS = len(HEADERS_LOGS)

# ── Configuracion: 4 columnas (A–D) ──────────────────────────────────────────
HEADERS_CONFIG = ["Campo", "Valor", "Descripción", "Ejemplo"]
ANCHOS_CONFIG  = [180, 380, 320, 220]

# Filas por defecto de Configuracion — solo si la pestaña está vacía
CONFIG_DEFAULTS = [
    ("cargo",
     "Auxiliar de limpieza",
     "Posición que se está reclutando",
     "Auxiliar de limpieza"),
    ("experiencia_minima_años",
     "1 año de experiencia",
     "Años requeridos en el rol específico",
     "1, 2, 3"),
    ("tipo_experiencia_requerida",
     "Limpieza EN hospitales, clínicas, centros de salud o laboratorios clínicos — NO en oficinas, NO en casas de familia, NO en espacios públicos",
     "Contexto/sector donde el candidato debe haber trabajado",
     "hospitales, oficinas, hoteles, industrial"),
    ("palabras_clave_plus",
     "hospitalario, hospitales, desinfeccion, clinica, Unidades de salud",
     "Términos que suman puntos al evaluar el CV (separadas por coma)",
     "hospitalario, clinica, desinfeccion"),
    ("palabras_descarte_educacion",
     "solo primaria, no terminé el colegio, primaria completa",
     "Frases en el CV que descartan automáticamente al candidato (separadas por coma)",
     "solo primaria, no terminé el colegio"),
]

# ── Paleta de colores profesional ─────────────────────────────────────────────
COLOR_HEADER = {"red": 0.102, "green": 0.227, "blue": 0.361}   # #1A3A5C navy

# Semáforo: pasteles suaves para fondo de celda F
BG_SEMAFORO = {
    "VERDE":    {"red": 0.831, "green": 0.937, "blue": 0.875},  # #D4EFDF
    "AMARILLO": {"red": 0.988, "green": 0.953, "blue": 0.812},  # #FCF3CF
    "ROJO":     {"red": 0.945, "green": 0.580, "blue": 0.541},  # #F1948A
}

COLOR_TEXTO  = {"red": 0.110, "green": 0.157, "blue": 0.200}   # #1C2833
COLOR_BORDE  = {"red": 0.835, "green": 0.847, "blue": 0.863}   # #D5D8DC
COLOR_ACENTO = {"red": 0.161, "green": 0.502, "blue": 0.725}   # #2980B9

# Potencial dorado
COLOR_POTENCIAL_BG     = {"red": 1.0, "green": 0.957, "blue": 0.733}  # #FFF4BB
COLOR_POTENCIAL_TEXTO  = {"red": 0.396, "green": 0.259, "blue": 0.004} # #654201
COLOR_POTENCIAL_BORDE  = {"red": 0.933, "green": 0.714, "blue": 0.027} # #EEB607

# Configuracion
COLOR_CONFIG_CAMPO_BG  = {"red": 0.957, "green": 0.965, "blue": 0.969}  # #F4F6F7
COLOR_CONFIG_DESC      = {"red": 0.482, "green": 0.490, "blue": 0.490}  # #7B7D7D
COLOR_CONFIG_EJEMPLO   = {"red": 0.682, "green": 0.713, "blue": 0.745}  # #AEB6BF
COLOR_BANDA_ALTERNA    = {"red": 0.980, "green": 0.984, "blue": 0.988}  # #FAFBFC

_BLANCO = {"red": 1.0, "green": 1.0, "blue": 1.0}


# ── Helpers de disponibilidad ─────────────────────────────────────────────────

def _formatear_disponibilidad(metadata: dict) -> str:
    """Construye celda multi-línea con los 3 indicadores de disponibilidad."""
    def _icono(val: str) -> str:
        v = val.strip().lower()
        if v in ("si", "sí") or "inmediata" in v:
            return "✅"
        if v == "no" or "notificar" in v:
            return "❌"
        return "❓"

    disp   = metadata.get("disponibilidad_form", "")
    turnos = metadata.get("turnos_form", "")
    fines  = metadata.get("fines_semana_form", "")

    partes = []
    if disp:
        texto = "Sí" if "inmediata" in disp.lower() else ("No" if "notificar" in disp.lower() else disp)
        partes.append(f"{_icono(disp)} Inmediata: {texto}")
    if turnos:
        partes.append(f"{_icono(turnos)} Turnos: {turnos}")
    if fines:
        partes.append(f"{_icono(fines)} Fines/feriados: {fines}")

    return "\n".join(partes) if partes else "No indica"


# ── Helpers de formato Candidatos ────────────────────────────────────────────

def _limpiar_formato_condicional(spreadsheet, hoja) -> None:
    """Elimina TODAS las reglas de formato condicional y bandas — empezamos limpio."""
    try:
        raw = spreadsheet.client.http_client.request(
            "GET",
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet.id}",
            params={"fields": "sheets(properties.sheetId,conditionalFormats,bandedRanges)"},
        ).json()

        requests = []
        for s in raw.get("sheets", []):
            if s.get("properties", {}).get("sheetId") != hoja.id:
                continue

            reglas = s.get("conditionalFormats", [])
            for i in range(len(reglas) - 1, -1, -1):
                requests.append({
                    "deleteConditionalFormatRule": {"sheetId": hoja.id, "index": i}
                })

            for br in s.get("bandedRanges", []):
                requests.append({"deleteBanding": {"bandedRangeId": br["bandedRangeId"]}})

        if requests:
            spreadsheet.batch_update({"requests": requests})
            print(f"[writer] Limpiadas {len(requests)} reglas en la hoja {hoja.title}")
    except Exception as e:
        print(f"[writer] _limpiar_formato_condicional: {e}")


def _quitar_filtro_basico(spreadsheet, hoja) -> None:
    """Elimina el filtro básico actual (si existe) para poder recrearlo."""
    try:
        spreadsheet.batch_update({"requests": [
            {"clearBasicFilter": {"sheetId": hoja.id}}
        ]})
    except Exception:
        pass  # no había filtro


def _dashboard_request(sid: int) -> list:
    """Construye fila 1 con stats — fórmulas que cuentan candidatos por semáforo."""
    # Texto unificado en una celda merged A1:S1 con fórmula JOIN
    # Usar ';' como separador de argumentos (locale es_EC) y "&" para concatenar
    formula = (
        '="📊 TOTAL: "&COUNTA(B3:B)'
        '&"     🟢 VERDES: "&COUNTIF(F3:F;"🟢 VERDE")'
        '&"     🟡 AMARILLOS: "&COUNTIF(F3:F;"🟡 AMARILLO")'
        '&"     🔴 ROJOS: "&COUNTIF(F3:F;"🔴 ROJO")'
    )

    return [
        # Merge A1:S1
        {"mergeCells": {
            "range": {"sheetId": sid,
                      "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
            "mergeType": "MERGE_ALL",
        }},
        # Altura fila 1
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 50},
            "fields": "pixelSize",
        }},
        # Contenido: fórmula + estilo navy
        {"updateCells": {
            "rows": [{"values": [{
                "userEnteredValue": {"formulaValue": formula},
                "userEnteredFormat": {
                    "backgroundColor":     COLOR_HEADER,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment":   "MIDDLE",
                    "textFormat": {
                        "bold": True,
                        "fontSize": 13,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                },
            }]}],
            "fields": "userEnteredValue,userEnteredFormat",
            "range": {"sheetId": sid,
                      "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
        }},
    ]


def _conditional_format_requests(sid: int) -> list:
    """Reglas de formato condicional para la columna F (Semáforo)."""
    reglas = []
    for valor, color in BG_SEMAFORO.items():
        reglas.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sid,
                        "startRowIndex": 2, "endRowIndex": 5000,
                        "startColumnIndex": IDX_SEMAFORO,
                        "endColumnIndex": IDX_SEMAFORO + 1,
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_CONTAINS",
                            "values": [{"userEnteredValue": valor}],
                        },
                        "format": {
                            "backgroundColor": color,
                            "textFormat": {"bold": True},
                        },
                    },
                },
                "index": 0,
            }
        })
    return reglas


def _filtro_basico_request(sid: int) -> dict:
    """Aplica filtro básico desde fila 2 (headers) hasta 5000."""
    return {
        "setBasicFilter": {
            "filter": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 1,        # fila 2 (headers)
                    "endRowIndex":   5000,
                    "startColumnIndex": 0,
                    "endColumnIndex": NUM_COLS,
                },
            }
        }
    }


def _formatear_sheet(spreadsheet, hoja) -> None:
    """Aplica todo el formato premium a Candidatos: dashboard, headers, filtros, congelado."""
    _limpiar_formato_condicional(spreadsheet, hoja)
    _quitar_filtro_basico(spreadsheet, hoja)

    try:
        sid = hoja.id
        requests = []

        # Anchos de columnas
        for i, ancho in enumerate(ANCHOS_COLUMNAS):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS",
                              "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": ancho},
                    "fields": "pixelSize",
                }
            })

        # Dashboard fila 1
        requests.extend(_dashboard_request(sid))

        # Altura de fila 2 (headers)
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 42},
                "fields": "pixelSize",
            }
        })

        # Estilo del encabezado (fila 2)
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": 1, "endRowIndex": 2,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
                "cell": {"userEnteredFormat": {
                    "backgroundColor":     COLOR_HEADER,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment":   "MIDDLE",
                    "wrapStrategy":        "WRAP",
                    "textFormat": {
                        "bold": True,
                        "fontSize": 10,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                }},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
            }
        })

        # Borde inferior azul acento bajo headers
        requests.append({
            "updateBorders": {
                "range": {"sheetId": sid,
                          "startRowIndex": 1, "endRowIndex": 2,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
                "bottom": {"style": "SOLID_MEDIUM", "color": COLOR_ACENTO},
            }
        })

        # Limpiar color de fondo en filas de datos (fila 3+)
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": 2, "endRowIndex": 5000,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS + 10},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _BLANCO,
                }},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

        # Conditional formatting para columna F
        requests.extend(_conditional_format_requests(sid))

        # Filtro básico desde fila 2
        requests.append(_filtro_basico_request(sid))

        spreadsheet.batch_update({"requests": requests})

        # Congelar 2 filas (dashboard + headers) + 2 columnas (A + B)
        hoja.freeze(rows=2, cols=2)

    except Exception as e:
        print(f"[writer] advertencia _formatear_sheet: {e}")


def _colorear_fila(spreadsheet, hoja, fila_num: int, semaforo: str) -> None:
    """Resetea fondo a blanco, semáforo en negrita con bg dinámico, separador inferior."""
    try:
        sid = hoja.id

        requests = [
            # Fondo blanco en toda la fila (limpia colores anteriores)
            {
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": 0, "endColumnIndex": NUM_COLS + 6},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": _BLANCO,
                    }},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            },
            # Semáforo (col F = índice 5) en negrita
            {
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": IDX_SEMAFORO,
                              "endColumnIndex": IDX_SEMAFORO + 1},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 11},
                    }},
                    "fields": "userEnteredFormat.textFormat",
                }
            },
            # Separador entre filas
            {
                "updateBorders": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
                    "bottom": {"style": "SOLID", "color": COLOR_BORDE},
                }
            },
        ]

        spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"[writer] advertencia _colorear_fila {fila_num}: {e}")


def _formatear_fila_nueva(
    spreadsheet, hoja, fila_num: int, drive_link: str, nota_talento: str = ""
) -> None:
    """Wrap, alineación, altura, potencial dorado y hyperlink CV."""
    try:
        sid = hoja.id
        requests = []

        # Wrap en columnas de texto largo (TOP)
        for col_idx in COLS_WRAP:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "wrapStrategy":      "WRAP",
                        "verticalAlignment": "TOP",
                    }},
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            })

        # Centrado en columnas cortas (MIDDLE)
        for col_idx in COLS_CENTER:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment":   "MIDDLE",
                    }},
                    "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
                }
            })

        # Altura de fila
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": fila_num - 1, "endIndex": fila_num},
                "properties": {"pixelSize": 95},
                "fields": "pixelSize",
            }
        })

        # ⭐ Potencial dorado si tiene contenido (col P = índice 15)
        if nota_talento:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": IDX_POTENCIAL,
                              "endColumnIndex": IDX_POTENCIAL + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": COLOR_POTENCIAL_BG,
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": COLOR_POTENCIAL_TEXTO,
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })
            requests.append({
                "updateBorders": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": IDX_POTENCIAL,
                              "endColumnIndex": IDX_POTENCIAL + 1},
                    "left": {"style": "SOLID_MEDIUM", "color": COLOR_POTENCIAL_BORDE},
                }
            })

        spreadsheet.batch_update({"requests": requests})

        # Hyperlink "Ver CV" — col S = índice 18
        if drive_link:
            spreadsheet.batch_update({"requests": [{
                "updateCells": {
                    "rows": [{"values": [{
                        "userEnteredValue": {"stringValue": "Ver CV"},
                        "userEnteredFormat": {
                            "textFormat": {
                                "link":            {"uri": drive_link},
                                "foregroundColor": COLOR_ACENTO,
                                "underline":       True,
                                "bold":            True,
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment":   "MIDDLE",
                        },
                    }]}],
                    "fields": "userEnteredValue,userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
                    "range": {
                        "sheetId":          sid,
                        "startRowIndex":    fila_num - 1,
                        "endRowIndex":      fila_num,
                        "startColumnIndex": IDX_CV_LINK,
                        "endColumnIndex":   IDX_CV_LINK + 1,
                    },
                }
            }]})

    except Exception as e:
        print(f"[writer] advertencia _formatear_fila_nueva {fila_num}: {e}")


def _asegurar_encabezado(spreadsheet, hoja, todos: list) -> None:
    """
    Estructura esperada:
      Fila 1 = dashboard (merged)
      Fila 2 = HEADERS_CANDIDATOS
      Fila 3+ = datos
    """
    # Detectar estructura actual
    fila1 = todos[0] if len(todos) >= 1 else []
    fila2 = todos[1] if len(todos) >= 2 else []

    headers_ok = (
        len(fila2) >= NUM_COLS
        and fila2[0] == "Fecha/Hora"
        and fila2[1] == "Nombre"
        and fila2[2] == "Cédula"
    )

    if headers_ok:
        # Estructura ya correcta — no hacemos nada (idempotente)
        return

    # Estructura incorrecta: limpiar y reconstruir
    # Borrar todo lo que haya y empezar desde cero con dashboard + headers
    try:
        hoja.clear()
    except Exception:
        pass

    # Insertar fila vacía para dashboard (será reemplazada por la fórmula en _formatear_sheet)
    # y luego los headers en fila 2
    try:
        hoja.update("A1", [[""]], value_input_option="USER_ENTERED")
        hoja.update(f"A2:{COL_FIN}2", [HEADERS_CANDIDATOS], value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"[writer] error insertando headers: {e}")

    _formatear_sheet(spreadsheet, hoja)


# ── Helpers de formato Logs ───────────────────────────────────────────────────

def _formatear_sheet_logs(spreadsheet, hoja) -> None:
    """Formato del encabezado de Logs."""
    try:
        sid = hoja.id
        requests = []

        for i, ancho in enumerate(ANCHOS_LOGS):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS",
                              "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": ancho},
                    "fields": "pixelSize",
                }
            })

        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 38},
                "fields": "pixelSize",
            }
        })

        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS_LOGS},
                "cell": {"userEnteredFormat": {
                    "backgroundColor":     COLOR_HEADER,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment":   "MIDDLE",
                    "textFormat": {
                        "bold": True,
                        "fontSize": 10,
                        "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    },
                }},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
            }
        })

        requests.append({
            "updateBorders": {
                "range": {"sheetId": sid,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS_LOGS},
                "bottom": {"style": "SOLID_MEDIUM", "color": COLOR_ACENTO},
            }
        })

        spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"[writer] advertencia _formatear_sheet_logs: {e}")


def _asegurar_encabezado_logs(spreadsheet, hoja, todos: list) -> None:
    primera_celda = todos[0][0] if todos and todos[0] else ""
    num_cols_actuales = len(todos[0]) if todos and todos[0] else 0
    if primera_celda == "Fecha/Hora" and num_cols_actuales >= NUM_COLS_LOGS:
        return
    if primera_celda == "Fecha/Hora":
        hoja.delete_rows(1)
    hoja.insert_row(HEADERS_LOGS, index=1)
    hoja.freeze(rows=1)
    _formatear_sheet_logs(spreadsheet, hoja)


# ── Helpers de formato Configuracion ─────────────────────────────────────────

def _formatear_pestana_configuracion(spreadsheet) -> None:
    """
    Aplica formato premium a la pestaña Configuracion:
    - 4 columnas: Campo | Valor | Descripción | Ejemplo
    - Header navy igual que Candidatos
    - Filas alternadas, descripciones grises italic
    - Si la pestaña está vacía o tiene el formato viejo, la reconstruye con CONFIG_DEFAULTS
    """
    with _lock_config:
        try:
            hoja = spreadsheet.worksheet("Configuracion")
        except Exception:
            print("[writer] Pestaña Configuracion no existe — saltando formato")
            return

        try:
            todos = hoja.get_all_values()

            # Detectar si ya tiene el formato nuevo (header "Campo" en A1)
            tiene_header_nuevo = (
                len(todos) >= 1
                and len(todos[0]) >= 1
                and todos[0][0].strip().lower() == "campo"
            )

            # Si ya tiene el formato nuevo, no aplicamos nada (idempotente, ahorra API calls)
            if tiene_header_nuevo:
                return

            # Está en formato viejo (clave|valor sin header)
            # → preservar los pares clave/valor existentes y agregar descripción/ejemplo desde defaults
            pares_actuales = {}
            for fila in todos:
                if len(fila) >= 2 and fila[0].strip() and fila[0].strip().lower() != "columna a":
                    clave = fila[0].strip().lower().replace(" ", "_")
                    valor = fila[1].strip()
                    pares_actuales[clave] = valor

            # Reconstruir con defaults pero preservando valores actuales
            nuevas_filas = [HEADERS_CONFIG]
            for clave, valor_def, desc, ejemplo in CONFIG_DEFAULTS:
                valor_real = pares_actuales.get(clave, valor_def)
                nuevas_filas.append([clave, valor_real, desc, ejemplo])

            hoja.clear()
            hoja.update(
                f"A1:D{len(nuevas_filas)}",
                nuevas_filas,
                value_input_option="USER_ENTERED",
            )

            # Aplicar formato visual (solo en la primera ejecución)
            sid = hoja.id
            requests = []

            # Anchos
            for i, ancho in enumerate(ANCHOS_CONFIG):
                requests.append({
                    "updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "COLUMNS",
                                  "startIndex": i, "endIndex": i + 1},
                        "properties": {"pixelSize": ancho},
                        "fields": "pixelSize",
                    }
                })

            # Altura header
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "ROWS",
                              "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": 42},
                    "fields": "pixelSize",
                }
            })

            # Estilo header
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": len(HEADERS_CONFIG)},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor":     COLOR_HEADER,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment":   "MIDDLE",
                        "textFormat": {
                            "bold": True,
                            "fontSize": 11,
                            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
                }
            })

            requests.append({
                "updateBorders": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": len(HEADERS_CONFIG)},
                    "bottom": {"style": "SOLID_MEDIUM", "color": COLOR_ACENTO},
                }
            })

            num_filas = len(CONFIG_DEFAULTS)

            # Altura de filas de datos
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "ROWS",
                              "startIndex": 1, "endIndex": 1 + num_filas},
                    "properties": {"pixelSize": 60},
                    "fields": "pixelSize",
                }
            })

            # Columna A (Campo): bold + bg gris
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 1, "endRowIndex": 1 + num_filas,
                              "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor":     COLOR_CONFIG_CAMPO_BG,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment":   "MIDDLE",
                        "wrapStrategy":        "WRAP",
                        "textFormat": {
                            "bold": True,
                            "fontSize": 10,
                            "foregroundColor": COLOR_TEXTO,
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
                }
            })

            # Columna B (Valor): editable, fondo blanco, wrap
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 1, "endRowIndex": 1 + num_filas,
                              "startColumnIndex": 1, "endColumnIndex": 2},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor":     _BLANCO,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment":   "MIDDLE",
                        "wrapStrategy":        "WRAP",
                        "textFormat": {
                            "fontSize": 10,
                            "foregroundColor": COLOR_TEXTO,
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
                }
            })

            # Columna C (Descripción): italic gris suave
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 1, "endRowIndex": 1 + num_filas,
                              "startColumnIndex": 2, "endColumnIndex": 3},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor":     _BLANCO,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment":   "MIDDLE",
                        "wrapStrategy":        "WRAP",
                        "textFormat": {
                            "italic":          True,
                            "fontSize": 9,
                            "foregroundColor": COLOR_CONFIG_DESC,
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
                }
            })

            # Columna D (Ejemplo): italic gris muy claro
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": 1, "endRowIndex": 1 + num_filas,
                              "startColumnIndex": 3, "endColumnIndex": 4},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor":     _BLANCO,
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment":   "MIDDLE",
                        "wrapStrategy":        "WRAP",
                        "textFormat": {
                            "italic":          True,
                            "fontSize": 9,
                            "foregroundColor": COLOR_CONFIG_EJEMPLO,
                        },
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
                }
            })

            # Bordes inferiores entre filas
            for i in range(num_filas):
                requests.append({
                    "updateBorders": {
                        "range": {"sheetId": sid,
                                  "startRowIndex": 1 + i, "endRowIndex": 2 + i,
                                  "startColumnIndex": 0, "endColumnIndex": len(HEADERS_CONFIG)},
                        "bottom": {"style": "SOLID", "color": COLOR_BORDE},
                    }
                })

            spreadsheet.batch_update({"requests": requests})

            # Congelar header
            hoja.freeze(rows=1)

            print("[writer] Configuracion formateada con look premium")

        except Exception as e:
            print(f"[writer] error formateando Configuracion: {e}")


# ── Helper: append con reintento ante 429 / cuota agotada ────────────────────

def _append_con_reintento(hoja, fila: list, max_intentos: int = 4) -> None:
    """Append con backoff exponencial si Sheets devuelve 429."""
    for intento in range(max_intentos):
        try:
            hoja.append_row(fila, value_input_option="USER_ENTERED")
            return
        except Exception as e:
            msg = str(e)
            es_cuota = (
                "429"                in msg
                or "Quota"          in msg
                or "RESOURCE_EXHAUSTED" in msg
                or "rateLimitExceeded"  in msg
            )
            if es_cuota and intento < max_intentos - 1:
                espera = (2 ** intento) + random.uniform(0.0, 1.0)
                print(f"[writer] ⚠️  Sheets 429 — reintento {intento + 1}/{max_intentos - 1} "
                      f"en {espera:.1f}s")
                time.sleep(espera)
            else:
                raise


# ── Funciones públicas ────────────────────────────────────────────────────────

def escribir_candidato(spreadsheet, resultado: dict, metadata: dict = None) -> None:
    if metadata is None:
        metadata = {}

    hoja     = spreadsheet.worksheet("Candidatos")
    semaforo = resultado.get("semaforo", "AMARILLO")
    emoji    = EMOJIS.get(semaforo, "⚪")

    nombre   = metadata.get("nombre_form")   or resultado.get("nombre",   "No indicado")
    telefono = metadata.get("telefono_form") or resultado.get("telefono", "No indicado")
    email    = metadata.get("email_form")    or resultado.get("email",    "No indicado")
    cedula   = metadata.get("cedula_form", "")

    movilidad_raw = resultado.get("movilidad")
    if movilidad_raw is True:
        movilidad_str = "Sí"
    elif movilidad_raw is False:
        movilidad_str = "No"
    else:
        movilidad_str = metadata.get("movilidad_form", "No indica")

    alertas        = " | ".join(resultado.get("alertas", []))
    preguntas      = " | ".join(resultado.get("preguntas_entrevista", []))
    drive_link     = metadata.get("drive_link", "")
    nota_talento   = resultado.get("nota_talento") or ""
    disponibilidad = _formatear_disponibilidad(metadata)

    # Nueva estructura de 19 columnas
    fila = [
        _ahora(),                                          # A  Fecha/Hora
        nombre,                                            # B  Nombre
        cedula,                                            # C  Cédula
        telefono,                                          # D  Teléfono
        email,                                             # E  Email
        f"{emoji} {semaforo}",                             # F  🚦 Semáforo (FINAL)
        resultado.get("razon_semaforo", ""),               # G  Razón Veredicto
        resultado.get("bachiller_oficial_resumen", "—"),   # H  🎓 Bachiller MinEdu
        resultado.get("satje_resumen", "—"),               # I  ⚖️ Procesos Judiciales
        resultado.get("detalle_educacion", ""),            # J  Educación (CV)
        resultado.get("anios_experiencia", 0),             # K  Años Exp.
        resultado.get("experiencia_detalle", ""),          # L  Experiencia
        disponibilidad,                                    # M  Disponibilidad
        movilidad_str,                                     # N  Movilidad
        resultado.get("resumen", ""),                      # O  Resumen
        nota_talento,                                      # P  ⭐ Potencial
        preguntas,                                         # Q  Preguntas Entrevista
        alertas,                                           # R  Alertas
        drive_link,                                        # S  📎 CV (se reemplaza por hyperlink)
    ]

    # ── Sección crítica: encabezado + append + número de fila ────────────────
    with _lock_candidatos:
        todos = hoja.get_all_values()
        _asegurar_encabezado(spreadsheet, hoja, todos)
        _append_con_reintento(hoja, fila)
        fila_num = len(hoja.get_all_values())

    # Formato fuera del lock
    _colorear_fila(spreadsheet, hoja, fila_num, semaforo)
    _formatear_fila_nueva(spreadsheet, hoja, fila_num, drive_link, nota_talento)

    # Asegurar formato de pestaña Configuracion (idempotente, no cuesta nada hacerlo cada vez)
    _formatear_pestana_configuracion(spreadsheet)


def escribir_log(
    spreadsheet,
    nivel: str,
    mensaje: str,
    detalle: str = "",
    ia: str = "",
    costo=None,
) -> None:
    hoja   = spreadsheet.worksheet("Logs")
    iconos = {"INFO": "ℹ️", "OK": "✅", "ERROR": "❌", "WARN": "⚠️"}

    if costo is None:
        costo_str = ""
    elif costo == 0.0:
        costo_str = "$0.00"
    else:
        costo_str = f"${costo:.6f}"

    fila_log = [
        _ahora(),
        f"{iconos.get(nivel, '')} {nivel}",
        mensaje,
        detalle,
        ia or "",
        costo_str,
    ]

    with _lock_logs:
        todos = hoja.get_all_values()
        _asegurar_encabezado_logs(spreadsheet, hoja, todos)
        _append_con_reintento(hoja, fila_log)
