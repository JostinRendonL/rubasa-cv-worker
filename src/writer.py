import random
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# ── Zona horaria Ecuador ──────────────────────────────────────────────────────
_TZ_ECUADOR = ZoneInfo("America/Guayaquil")

# ── Locks para escritura concurrente ─────────────────────────────────────────
# Protegen el bloque append_row + get_all_values() en cada hoja por separado,
# evitando que dos hilos lean el mismo número de fila al mismo tiempo.
_lock_candidatos = threading.Lock()
_lock_logs       = threading.Lock()

def _ahora() -> str:
    """Hora actual en Ecuador (UTC-5), no en el servidor de Railway."""
    return datetime.now(_TZ_ECUADOR).strftime("%d/%m/%Y %H:%M")


# ── Constantes visuales ───────────────────────────────────────────────────────

EMOJIS = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}

# ── Candidatos: 22 columnas (A–V) ────────────────────────────────────────────
# Columnas T, U, V agregadas en v5 — Background Check (Ministerio + SATJE)
HEADERS_CANDIDATOS = [
    "Fecha/Hora", "Nombre", "Teléfono", "Email",
    "Semáforo", "Puntaje", "Bachiller", "Detalle Educación",
    "Años Exp.", "Experiencia", "Disponibilidad", "Movilidad",
    "Resumen", "⭐ Potencial", "Preguntas Entrevista", "Alertas",
    "Razón Veredicto", "CV", "Cédula",
    "Bachiller MinEdu", "Coincide CV", "Procesos Judiciales",
]

ANCHOS_COLUMNAS = [
    130,  # A  Fecha/Hora
    180,  # B  Nombre
    110,  # C  Teléfono
    175,  # D  Email
    105,  # E  Semáforo (FINAL — CV × Background)
     60,  # F  Puntaje
    110,  # G  Bachiller (IA)
    230,  # H  Detalle Educación  (wrap)
     70,  # I  Años Exp.
    250,  # J  Experiencia        (wrap)
    155,  # K  Disponibilidad     (wrap, 3 líneas)
     80,  # L  Movilidad
    320,  # M  Resumen            (wrap)
    320,  # N  ⭐ Potencial        (wrap)
    310,  # O  Preguntas          (wrap)
    240,  # P  Alertas            (wrap)
    240,  # Q  Razón Veredicto    (wrap)
     65,  # R  CV
    120,  # S  Cédula
    260,  # T  Bachiller MinEdu   (wrap — oficial del Ministerio de Educación)
    110,  # U  Coincide CV        (centered — detector de mentiras)
    320,  # V  Procesos Judiciales (wrap — SATJE Función Judicial)
]

COLS_WRAP   = [7, 9, 10, 12, 13, 14, 15, 16, 19, 21]  # H, J, K, M, N, O, P, Q, T, V
COLS_CENTER = [4, 5, 6, 8, 11, 17, 20]                 # E, F, G, I, L, R, U

NUM_COLS = len(HEADERS_CANDIDATOS)       # 19
COL_FIN  = chr(ord("A") + NUM_COLS - 1) # "S"

# ── Logs: 6 columnas (A–F) ───────────────────────────────────────────────────
HEADERS_LOGS  = ["Fecha/Hora", "Nivel", "Evento", "Detalle", "IA Utilizada", "Costo USD"]
ANCHOS_LOGS   = [130, 95, 220, 380, 200, 90]
NUM_COLS_LOGS = len(HEADERS_LOGS)

# ── Paleta de colores profesional ─────────────────────────────────────────────
# Header: azul marino oscuro
COLOR_HEADER = {"red": 0.102, "green": 0.227, "blue": 0.361}   # #1A3A5C

# Semáforo: VERDE y AMARILLO pasteles, ROJO claramente rojo
COLORES_FILA = {
    "VERDE":    {"red": 0.831, "green": 0.937, "blue": 0.875},  # #D4EFDF  pastel verde
    "AMARILLO": {"red": 0.988, "green": 0.953, "blue": 0.812},  # #FCF3CF  pastel amarillo
    "ROJO":     {"red": 0.945, "green": 0.580, "blue": 0.541},  # #F1948A  rojo visible
}

# Texto en filas: azul-negro refinado
COLOR_TEXTO  = {"red": 0.110, "green": 0.157, "blue": 0.200}   # #1C2833

# Borde inferior sutil entre filas
COLOR_BORDE  = {"red": 0.835, "green": 0.847, "blue": 0.863}   # #D5D8DC

# Acento del borde inferior del header
COLOR_ACENTO = {"red": 0.161, "green": 0.502, "blue": 0.725}   # #2980B9

# Nota talento: oro pastel con borde ámbar
COLOR_POTENCIAL_BG     = {"red": 1.0, "green": 0.957, "blue": 0.733}  # #FFF4BB
COLOR_POTENCIAL_TEXTO  = {"red": 0.396, "green": 0.259, "blue": 0.004} # #654201
COLOR_POTENCIAL_BORDE  = {"red": 0.933, "green": 0.714, "blue": 0.027} # #EEB607


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
    """Elimina todas las reglas de formato condicional y colores alternos de la hoja."""
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

            # Eliminar reglas de formato condicional en orden inverso (para que los índices no se desplacen)
            reglas = s.get("conditionalFormats", [])
            for i in range(len(reglas) - 1, -1, -1):
                requests.append({
                    "deleteConditionalFormatRule": {"sheetId": hoja.id, "index": i}
                })

            # Eliminar colores alternos (BandedRanges)
            for br in s.get("bandedRanges", []):
                requests.append({"deleteBanding": {"bandedRangeId": br["bandedRangeId"]}})

        if requests:
            spreadsheet.batch_update({"requests": requests})
            print(f"[writer] Limpiadas {len(requests)} reglas de formato en la hoja Candidatos")
    except Exception as e:
        print(f"[writer] _limpiar_formato_condicional: {e}")


def _formatear_sheet(spreadsheet, hoja) -> None:
    """Anchos de columna, altura y estilo del encabezado de Candidatos."""
    _limpiar_formato_condicional(spreadsheet, hoja)
    try:
        sid = hoja.id
        requests = []

        for i, ancho in enumerate(ANCHOS_COLUMNAS):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS",
                              "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": ancho},
                    "fields": "pixelSize",
                }
            })

        # Altura del encabezado
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 40},
                "fields": "pixelSize",
            }
        })

        # Estilo del encabezado
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
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

        # Borde inferior azul acento
        requests.append({
            "updateBorders": {
                "range": {"sheetId": sid,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
                "bottom": {"style": "SOLID_MEDIUM", "color": COLOR_ACENTO},
            }
        })

        # Limpiar color de fondo en todas las filas de datos (fila 2 en adelante)
        # Esto borra el color verde que quedó en columnas de versiones anteriores
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": 1, "endRowIndex": 5000,
                          "startColumnIndex": 0, "endColumnIndex": NUM_COLS + 10},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                }},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

        spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"[writer] advertencia _formatear_sheet: {e}")


_BLANCO = {"red": 1.0, "green": 1.0, "blue": 1.0}

def _colorear_fila(spreadsheet, hoja, fila_num: int, semaforo: str) -> None:
    """Resetea fondo a blanco, semáforo en negrita, separador inferior."""
    try:
        sid = hoja.id

        spreadsheet.batch_update({"requests": [
            # Fondo blanco explícito en toda la fila (limpia colores anteriores)
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
            # Semáforo (col E = índice 4) en negrita
            {
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": 4, "endColumnIndex": 5},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True},
                    }},
                    "fields": "userEnteredFormat.textFormat.bold",
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
        ]})
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
                        "wrapStrategy":    "WRAP",
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

        # ⭐ Potencial dorado si tiene contenido (col N = índice 13)
        if nota_talento:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid,
                              "startRowIndex": fila_num - 1, "endRowIndex": fila_num,
                              "startColumnIndex": 13, "endColumnIndex": 14},
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
                              "startColumnIndex": 13, "endColumnIndex": 14},
                    "left": {"style": "SOLID_MEDIUM", "color": COLOR_POTENCIAL_BORDE},
                }
            })

        spreadsheet.batch_update({"requests": requests})

        # Hyperlink "Ver CV" — col R = índice 17
        if drive_link:
            spreadsheet.batch_update({"requests": [{
                "updateCells": {
                    "rows": [{"values": [{
                        "userEnteredValue": {"stringValue": "Ver CV"},
                        "userEnteredFormat": {
                            "textFormat": {
                                "link":            {"uri": drive_link},
                                "foregroundColor": {"red": 0.161, "green": 0.502, "blue": 0.725},
                                "underline":       True,
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment":   "MIDDLE",
                        },
                    }]}],
                    "fields": "userEnteredValue,userEnteredFormat.textFormat,userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment",
                    "range": {
                        "sheetId":          hoja.id,
                        "startRowIndex":    fila_num - 1,
                        "endRowIndex":      fila_num,
                        "startColumnIndex": 17,
                        "endColumnIndex":   18,
                    },
                }
            }]})

    except Exception as e:
        print(f"[writer] advertencia _formatear_fila_nueva {fila_num}: {e}")


def _asegurar_encabezado(spreadsheet, hoja, todos: list) -> None:
    """Inserta o actualiza el encabezado y limpia colores residuales."""
    primera_celda     = todos[0][0] if todos and todos[0] else ""
    num_cols_actuales = len(todos[0]) if todos and todos[0] else 0

    if primera_celda == "Fecha/Hora" and num_cols_actuales == NUM_COLS:
        # Encabezado correcto — igual relimpiar colores en cada escritura
        _formatear_sheet(spreadsheet, hoja)
        return

    if primera_celda == "Fecha/Hora":
        hoja.delete_rows(1)

    hoja.insert_row(HEADERS_CANDIDATOS, index=1)
    hoja.freeze(rows=1)
    _formatear_sheet(spreadsheet, hoja)


# ── Helpers de formato Logs ───────────────────────────────────────────────────

def _formatear_sheet_logs(spreadsheet, hoja) -> None:
    """Anchos de columna y estilo del encabezado de Logs."""
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

        # Altura del encabezado
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 38},
                "fields": "pixelSize",
            }
        })

        # Estilo del encabezado (mismo navy que Candidatos)
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
    """Inserta el encabezado de Logs si no existe o si no tiene las 6 columnas."""
    primera_celda = todos[0][0] if todos and todos[0] else ""
    num_cols_actuales = len(todos[0]) if todos and todos[0] else 0
    if primera_celda == "Fecha/Hora" and num_cols_actuales >= NUM_COLS_LOGS:
        return
    # Reemplazar encabezado viejo o crear uno nuevo
    if primera_celda == "Fecha/Hora":
        hoja.delete_rows(1)
    hoja.insert_row(HEADERS_LOGS, index=1)
    hoja.freeze(rows=1)
    _formatear_sheet_logs(spreadsheet, hoja)


# ── Helper: append con reintento ante 429 / cuota agotada ────────────────────

def _append_con_reintento(hoja, fila: list, max_intentos: int = 4) -> None:
    """
    Hace append_row con backoff exponencial si Sheets devuelve 429 / RESOURCE_EXHAUSTED.
    No usa sleep preventivo — solo reintenta ante error real.
    """
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

    movilidad_raw = resultado.get("movilidad")
    if movilidad_raw is True:
        movilidad_str = "Sí"
    elif movilidad_raw is False:
        movilidad_str = "No"
    else:
        movilidad_str = metadata.get("movilidad_form", "No indica")

    alertas       = " | ".join(resultado.get("alertas", []))
    preguntas     = " | ".join(resultado.get("preguntas_entrevista", []))
    drive_link    = metadata.get("drive_link", "")
    nota_talento  = resultado.get("nota_talento") or ""
    disponibilidad = _formatear_disponibilidad(metadata)

    # Columnas Background (v5) — con iconos visuales para Coincide CV
    coincide_raw = resultado.get("coincide_cv", "—")
    coincide_visual = {
        "COINCIDE":   "✅ Sí",
        "MINTIO":     "⚠️ MINTIÓ",
        "NO_APLICA":  "⚪ —",
        "—":          "—",
    }.get(coincide_raw, coincide_raw)

    fila = [
        _ahora(),                # A  Fecha/Hora
        nombre,                  # B  Nombre
        telefono,                # C  Teléfono
        email,                   # D  Email
        f"{emoji} {semaforo}",   # E  Semáforo (FINAL)
        resultado.get("puntaje", 0),                   # F  Puntaje
        resultado.get("bachiller", "AMBIGUO"),          # G  Bachiller (IA)
        resultado.get("detalle_educacion", ""),         # H  Detalle Educación
        resultado.get("anios_experiencia", 0),          # I  Años Exp.
        resultado.get("experiencia_detalle", ""),       # J  Experiencia
        disponibilidad,                                 # K  Disponibilidad
        movilidad_str,                                  # L  Movilidad
        resultado.get("resumen", ""),                   # M  Resumen
        nota_talento,                                   # N  ⭐ Potencial
        preguntas,                                      # O  Preguntas
        alertas,                                        # P  Alertas
        resultado.get("razon_semaforo", ""),            # Q  Razón
        drive_link,                                     # R  CV (hyperlink)
        metadata.get("cedula_form", ""),                # S  Cédula
        resultado.get("bachiller_oficial_resumen", "—"),# T  Bachiller MinEdu
        coincide_visual,                                # U  Coincide CV
        resultado.get("satje_resumen", "—"),            # V  Procesos Judiciales
    ]

    # ── Sección crítica: encabezado + append + número de fila ────────────────
    # El Lock garantiza que dos hilos no lean el mismo fila_num simultáneamente.
    with _lock_candidatos:
        todos = hoja.get_all_values()
        _asegurar_encabezado(spreadsheet, hoja, todos)
        _append_con_reintento(hoja, fila)
        fila_num = len(hoja.get_all_values())

    # El formato puede ir fuera del lock — solo depende de fila_num ya fijado
    _colorear_fila(spreadsheet, hoja, fila_num, semaforo)
    _formatear_fila_nueva(spreadsheet, hoja, fila_num, drive_link, nota_talento)


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
