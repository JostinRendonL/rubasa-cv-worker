"""
RUBASA CV Worker v5 — Integrado con Background Checks Ecuador

Flujo:
  1. Apps Script (Google Forms) → POST /webhook
  2. Pre-filtro de disponibilidad (turnos rotativos = No → ROJO sin gastar IA)
  3. Descarga PDF de Drive + extrae texto/visión
  4. Lee Configuracion del cargo (cargo, experiencia, palabras clave)
  5. Analiza CV con IA (GPT-4o Mini / Gemini / Llama — cadena fallback)
  6. *** NUEVO *** Background Check: bachiller oficial + SATJE judicial
  7. Calcula Semáforo FINAL combinando CV × Background
  8. Escribe a hoja Candidatos con 3 columnas nuevas (T, U, V)
  9. Log en hoja Logs con costo

Variables de entorno necesarias:
  SHEET_ID            — ID del Google Sheet
  SA_JSON             — JSON del service account (o SA_JSON_PATH al archivo)
  OPENROUTER_API_KEY  — para GPT-4o Mini (IA principal)
  GEMINI_API_KEY      — fallback gratis Google
  GROQ_API_KEY        — fallback gratis Llama
  BG_API_URL          — http://dentaklin_bg-api:8000 (red interna Docker)
  BG_API_KEY          — clave de la Background API
  TELEGRAM_BOT_TOKEN  — (opcional) alertas de criminales graves
  TELEGRAM_CHAT_ID    — (opcional) chat destino
"""

import asyncio
import os
import io
import json
import time
import threading
import hmac
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from src.extractor import extraer_desde_drive
from src.analizador import analizar_cv
from src.config_reader import leer_configuracion, obtener_delitos_graves
from src.writer import escribir_candidato, escribir_log
from src.obs import init_sentry, capture_exception
from src.metrics import setup_metrics

load_dotenv()
# Inicializar Sentry (opt-in con SENTRY_DSN) — antes de crear FastAPI
init_sentry(servicio="cv-worker")

app = FastAPI(title="RUBASA CV Worker", version="5.5.0")

# Métricas Prometheus opt-in (si METRICS_ENABLED=1)
setup_metrics(app)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    # drive.file (validado 2026-05-24 contra Rubasa): solo archivos creados/abiertos
    # por el SA o explícitamente compartidos con su email. La carpeta "Adjuntar CV
    # (File responses)" está compartida con worker-railway@filtro-cvs-rubasa.iam.gserviceaccount.com
    # como Editor → todos los CVs subidos por el Form son accesibles.
    # Si el SA se filtra, el daño potencial es 95% menor que con "drive" completo.
    "https://www.googleapis.com/auth/drive.file",
]

# ── Configuración Background Check API ───────────────────────────────────────
# Por defecto apunta a la red interna de Docker (servicio bg-api en Easypanel)
BG_API_URL = os.getenv("BG_API_URL", "http://dentaklin_bg-api:8000")
BG_API_KEY = os.getenv("BG_API_KEY", "")
BG_TIMEOUT = float(os.getenv("BG_API_TIMEOUT", "60"))

# ── Seguridad del webhook ────────────────────────────────────────────────────
# Secreto que Apps Script debe enviar en cada POST a /webhook. Si no coincide,
# 401. Sin esto cualquiera con la URL puede saturar la cola y quemar saldo de IA.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# ── Idempotencia ─────────────────────────────────────────────────────────────
# Cache en memoria de file_ids recientemente procesados. Si Apps Script reintenta
# por timeout, el mismo CV no se procesa 2 veces (evita filas duplicadas + doble
# costo de IA). TTL 1 hora — suficiente para cubrir reintentos típicos.
IDEMPOTENCY_TTL_SEG = int(os.getenv("IDEMPOTENCY_TTL_SEG", "3600"))
_proc_cache:   dict[str, dict]   = {}     # file_id → {"ts": epoch, "result": dict}
_proc_in_flight: dict[str, threading.Event] = {}   # file_id → Event para serialización
_proc_lock = threading.Lock()

# Lista de delitos GRAVES — fallback si la Sheet no tiene la clave `delitos_graves`.
# La versión activa se lee dinámicamente con obtener_delitos_graves(spreadsheet).
DELITOS_GRAVES_FALLBACK = [
    "ASESINATO", "HOMICIDIO", "FEMICIDIO",
    "DELINCUENCIA ORGANIZADA", "ASOCIACION ILICITA",
    "VIOLACION", "ABUSO SEXUAL", "ABUSO DE MENORES",
    "ROBO", "ROBO AGRAVADO",
    "TRAFICO DE DROGAS", "TENENCIA DE DROGAS", "ESTUPEFACIENTES",
    "TENENCIA DE ARMAS", "PORTE ILEGAL",
    "SECUESTRO", "EXTORSION", "TRATA DE PERSONAS",
]

# Pool de hilos para procesar CVs en paralelo. Configurable via env.
# Default 5 (antes 3) — los workers pasan la mayor parte del tiempo esperando
# I/O (IA, Drive, bg-api), no CPU. Subir el pool ayuda en picos sin saturar CPU.
MAX_WORKERS = int(os.getenv("MAX_WORKERS_CV", "5"))
_pool_cvs = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="cv-worker")


# ── Modelo del payload del webhook ───────────────────────────────────────────
# Antes: body = await request.json() + body.get(...) sin validación.
# Ahora: FastAPI valida tipos automáticamente, rechaza 422 si llega basura.

class WebhookPayload(BaseModel):
    """Payload que envía Apps Script desde el Google Form."""
    file_id:                  str
    nombre:                   str = "No indicado"
    cedula:                   str = ""
    telefono:                 str = "No indicado"
    email:                    str = "No indicado"
    disponibilidad_inmediata: str = ""
    turnos_rotativos:         str = ""
    fines_semana:             str = ""
    movilidad:                str = ""
    drive_link:               str = ""

    # Permitir campos extra sin fallar (Forms puede mandar más cosas en el futuro)
    model_config = {"extra": "allow"}


# ── Helpers de auth + idempotencia ───────────────────────────────────────────

def _verificar_secret(secret_recibido: str | None) -> None:
    """Verifica el secret del webhook. Si no coincide → 401."""
    if not WEBHOOK_SECRET:
        # Modo permisivo: si la var no está configurada, no se valida.
        # Útil durante setup inicial — log warning para que se note.
        print("[security] ⚠️  WEBHOOK_SECRET no configurado — webhook está PÚBLICO")
        return
    if not secret_recibido or not hmac.compare_digest(secret_recibido, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="webhook secret inválido o ausente")


def _idempotency_check(file_id: str) -> dict | None:
    """
    Si este file_id ya se procesó recientemente o está en proceso, devuelve
    el resultado cacheado (sin reprocesar). None = procede a procesar.
    """
    ahora = time.time()
    with _proc_lock:
        # Limpiar cache expirado (cheap, in-place)
        for fid in list(_proc_cache.keys()):
            if ahora - _proc_cache[fid]["ts"] > IDEMPOTENCY_TTL_SEG:
                del _proc_cache[fid]

        # Cache hit fresco
        if file_id in _proc_cache:
            print(f"[idempotency] file_id {file_id[:12]}... ya procesado hace "
                  f"{int(ahora - _proc_cache[file_id]['ts'])}s — devolviendo cache")
            return _proc_cache[file_id]["result"]

        # Está en proceso por otro thread — esperaremos afuera del lock
        if file_id in _proc_in_flight:
            return {"_wait_for": _proc_in_flight[file_id]}

        # Reservamos el slot
        _proc_in_flight[file_id] = threading.Event()
        return None


def _idempotency_finish(file_id: str, result: dict) -> None:
    """Marca el file_id como completado y guarda el resultado."""
    with _proc_lock:
        _proc_cache[file_id] = {"ts": time.time(), "result": result}
        evt = _proc_in_flight.pop(file_id, None)
    if evt:
        evt.set()  # despierta a quien estuviera esperando


# ── Helpers de conexión (cache singleton) ────────────────────────────────────
# Antes: cada CV procesado re-autorizaba con Google + reabría el Sheet (200-500ms
# por log). Cada CV genera 5-7 logs → varios segundos de overhead inútil por CV.
# Ahora: 1 sola conexión por proceso, reusada vía cache thread-safe.

_creds_cache:  Credentials | None = None
_sheet_cache:  Any | None = None     # gspread.Spreadsheet
_creds_lock = threading.Lock()
_sheet_lock = threading.Lock()


def get_creds() -> Credentials:
    """Service Account Credentials cacheadas. Thread-safe."""
    global _creds_cache
    if _creds_cache is not None:
        return _creds_cache
    with _creds_lock:
        if _creds_cache is not None:   # double-checked locking
            return _creds_cache
        sa_json_str = os.getenv("SA_JSON")
        if sa_json_str:
            _creds_cache = Credentials.from_service_account_info(
                json.loads(sa_json_str), scopes=SCOPES
            )
        else:
            _creds_cache = Credentials.from_service_account_file(
                os.getenv("SA_JSON_PATH", "credentials/service_account.json"),
                scopes=SCOPES,
            )
        return _creds_cache


def get_spreadsheet():
    """Spreadsheet object cacheado. Thread-safe."""
    global _sheet_cache
    if _sheet_cache is not None:
        return _sheet_cache
    with _sheet_lock:
        if _sheet_cache is not None:
            return _sheet_cache
        creds = get_creds()
        client = gspread.authorize(creds)
        _sheet_cache = client.open_by_key(os.getenv("SHEET_ID"))
        print(f"[sheets] ✅ Spreadsheet cacheado (id={os.getenv('SHEET_ID', '')[:12]}...)")
        return _sheet_cache


def reset_sheet_cache() -> None:
    """Invalida el cache (útil si el token expira o se cambia SHEET_ID)."""
    global _creds_cache, _sheet_cache
    with _creds_lock:
        _creds_cache = None
    with _sheet_lock:
        _sheet_cache = None
    print("[sheets] cache invalidado")


def descargar_pdf_drive(file_id: str, creds: Credentials) -> bytes:
    service = build("drive", "v3", credentials=creds)
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


# ── Background Check API client ──────────────────────────────────────────────

def consultar_background_sync(cedula: str) -> dict:
    """
    Llama síncronamente a la API de background checks.
    Retorna dict con bachiller, satje, semaforo, tiempo_seg.
    Si falla, retorna estructura con status=ERROR.
    """
    if not cedula or not cedula.isdigit() or len(cedula) != 10:
        return {
            "semaforo":  "GRIS",
            "bachiller": {"estado": "ERROR", "detalle": "Cédula inválida"},
            "satje":     {"status": "ERROR", "detalle": "Cédula inválida"},
            "error":     "cedula_invalida",
        }

    try:
        with httpx.Client(timeout=BG_TIMEOUT) as client:
            r = client.post(
                f"{BG_API_URL}/consultar/completo",
                headers={"X-API-Key": BG_API_KEY, "Content-Type": "application/json"},
                json={"cedula": cedula},
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {
            "semaforo":  "GRIS",
            "bachiller": {"estado": "ERROR", "detalle": str(e)[:200]},
            "satje":     {"status": "ERROR", "detalle": str(e)[:200]},
            "error":     str(e)[:200],
        }


# ── SETEC API client ─────────────────────────────────────────────────────────

def consultar_setec_sync(cedula: str) -> dict:
    """
    Llama síncronamente al endpoint /consultar/setec del bg-api.
    Retorna dict con tiene_certificados, detalle_cursos, total_cursos, nombre.
    Si falla, retorna estructura con error y tiene_certificados=False.
    """
    if not cedula or not cedula.isdigit() or len(cedula) != 10:
        return {
            "error":              "Cédula inválida",
            "tiene_certificados": False,
            "detalle_cursos":     "Sin registros",
            "total_cursos":       0,
        }
    try:
        with httpx.Client(timeout=BG_TIMEOUT) as client:
            r = client.post(
                f"{BG_API_URL}/consultar/setec",
                headers={"X-API-Key": BG_API_KEY, "Content-Type": "application/json"},
                json={"cedula": cedula},
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {
            "error":              str(e)[:200],
            "tiene_certificados": False,
            "detalle_cursos":     "Sin registros",
            "total_cursos":       0,
        }


def _resumir_setec(st: dict) -> str:
    """Texto compacto para la columna T (Certificaciones MDT)."""
    if not st:
        return "—"
    if st.get("error"):
        return f"❌ Error: {st['error'][:60]}"
    if st.get("tiene_certificados"):
        cursos = (st.get("detalle_cursos") or "").strip()
        total  = st.get("total_cursos", 0)
        if total and cursos:
            return f"✅ {total} cert.: {cursos}"
        return cursos or "Sin registros"
    return "Sin registros"


def _verificar_consistencia(bachiller_ia: str, bachiller_oficial: dict) -> str:
    """
    Compara lo que la IA leyó del CV con lo que el Ministerio confirma.
    Retorna: 'COINCIDE' | 'MINTIO' | 'NO_APLICA'
    """
    estado_oficial = bachiller_oficial.get("estado")
    if estado_oficial == "ERROR":
        return "NO_APLICA"

    tiene_titulo_oficial = bachiller_oficial.get("tiene_titulo") is True
    ia_dice_confirmado = (bachiller_ia or "").upper() == "CONFIRMADO"

    if ia_dice_confirmado and not tiene_titulo_oficial:
        return "MINTIO"   # el CV dice bachiller pero el ministerio no lo tiene
    if not ia_dice_confirmado and tiene_titulo_oficial:
        return "COINCIDE"  # bonus: tiene título aunque el CV no lo dijo claro
    return "COINCIDE"


def _calcular_semaforo_final(cv_semaforo: str, bg: dict, spreadsheet=None) -> str:
    """
    Combina nivel de riesgo del CV con resultado del Background.

    Niveles (de mayor a menor riesgo):
      CRITICO    — Delitos graves detectados (homicidio, narcos, etc)
      RECHAZAR   — CV ya era ROJO, O procesos judiciales como demandado (sin delitos graves)
      OBSERVACION— CV era AMARILLO, O mintió sobre bachiller, O procesos como actor
      APTO       — CV apto Y sin observaciones en background
      SIN_DATOS  — error en BG, mantener veredicto del CV mapeado a los nuevos niveles

    Compatibilidad: si el CV viene con etiqueta vieja (VERDE/AMARILLO/ROJO) la mapeamos.
    """
    # Mapeo de etiquetas viejas → nuevas (por compatibilidad con analizador.py)
    mapa = {
        "VERDE":    "APTO",
        "AMARILLO": "OBSERVACION",
        "ROJO":     "RECHAZAR",
        "APTO":         "APTO",
        "OBSERVACION":  "OBSERVACION",
        "RECHAZAR":     "RECHAZAR",
        "CRITICO":      "CRITICO",
    }
    cv_nivel = mapa.get((cv_semaforo or "").upper(), "OBSERVACION")

    satje = bg.get("satje", {})

    # 1. CRITICO — delitos graves siempre ganan
    hay_grave, _ = _tiene_delito_grave(satje, spreadsheet)
    if hay_grave:
        return "CRITICO"

    # 2. RECHAZAR — CV ya era rechazado, o tiene procesos como demandado
    if cv_nivel == "RECHAZAR":
        return "RECHAZAR"
    if satje.get("total_demandado", 0) > 0:
        return "RECHAZAR"

    # 3. SIN_DATOS — bg con error → mantener nivel del CV
    bg_semaforo = bg.get("semaforo", "GRIS")
    if bg_semaforo == "GRIS":
        return cv_nivel  # ya está mapeado

    # 4. OBSERVACION — cualquiera de los dos tiene observación
    if cv_nivel == "OBSERVACION" or bg_semaforo == "AMARILLO":
        return "OBSERVACION"

    # 5. APTO
    return "APTO"


def _resumir_bachiller_oficial(b: dict) -> str:
    """Texto compacto para la columna T."""
    if not b or b.get("estado") == "ERROR":
        return f"❌ Error: {b.get('detalle', 'sin datos')[:60]}"
    if b.get("estado") == "NO_ENCONTRADO" or not b.get("tiene_titulo"):
        return "❌ NO encontrado en Min. Educación"
    titulo  = b.get("titulo") or ""
    inst    = b.get("institucion") or ""
    fecha   = (b.get("fecha_grado") or "")[:4]
    return f"✅ {titulo} — {inst} ({fecha})".strip()


def _resumir_satje(s: dict) -> str:
    """Texto compacto para la columna V."""
    if not s or s.get("status") == "ERROR":
        return f"❌ Error: {s.get('detalle', 'sin datos')[:60]}"
    td = s.get("total_demandado", 0)
    ta = s.get("total_actor", 0)
    if td == 0 and ta == 0:
        return "✅ Sin procesos"
    # Listar delitos como demandado (los más graves)
    delitos = []
    for causa in (s.get("causas_demandado") or [])[:5]:
        d = (causa.get("delito") or "").strip()
        if d:
            # Acortar "144 HOMICIDIO" → "HOMICIDIO"
            d_corto = " ".join(d.split()[1:]) if d.split()[0].isdigit() else d
            delitos.append(d_corto[:40])
    extra = f" (+{td - len(delitos)})" if td > len(delitos) else ""
    if td > 0:
        return f"🔴 {td} demandado: {' | '.join(delitos)}{extra}"
    return f"🟡 {ta} como actor (víctima/demandante)"


def _tiene_delito_grave(s: dict, spreadsheet=None) -> tuple[bool, list[str]]:
    """
    Detecta si hay delitos GRAVES → dispara alerta Telegram.
    La lista se lee dinámicamente de la Sheet (configurable por cliente),
    con fallback a DELITOS_GRAVES_FALLBACK si no hay Sheet disponible.
    """
    try:
        lista = obtener_delitos_graves(spreadsheet) if spreadsheet else DELITOS_GRAVES_FALLBACK
    except Exception:
        lista = DELITOS_GRAVES_FALLBACK

    graves = []
    for causa in (s.get("causas_demandado") or []):
        delito = (causa.get("delito") or "").upper()
        for g in lista:
            if g in delito and g not in graves:
                graves.append(g)
    return len(graves) > 0, graves


def _enviar_alerta_telegram(nombre: str, cedula: str, delitos: list[str]) -> None:
    """
    Notifica por Telegram cuando aparece un candidato con delitos graves.
    Solo se ejecuta si TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID están configurados.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat  = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return

    texto = (
        "🚨 *Candidato con antecedentes graves*\n\n"
        f"*Nombre:* {nombre}\n"
        f"*Cédula:* `{cedula}`\n"
        f"*Delitos detectados:* {', '.join(delitos)}\n\n"
        "Revisar en la hoja Candidatos."
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": texto, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[telegram] no se pudo enviar alerta: {e}")


# ── Validación de cédula ecuatoriana ─────────────────────────────────────────

def _cedula_valida_ec(cedula: str) -> bool:
    """
    Valida cédula con el algoritmo del dígito verificador del Registro Civil.
    Evita gastar API en cédulas mal escritas o falsas.
    """
    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return False
    provincia = int(cedula[:2])
    if not (1 <= provincia <= 24) and provincia != 30:
        return False
    if int(cedula[2]) >= 6:
        return False
    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for i, c in enumerate(cedula[:9]):
        p = int(c) * coef[i]
        if p >= 10:
            p -= 9
        suma += p
    return ((10 - (suma % 10)) % 10) == int(cedula[9])


# ── Pre-filtro de disponibilidad ─────────────────────────────────────────────

def _normalizar(valor: str) -> str:
    return (valor or "").strip().lower()


def _pre_filtrar(body: dict) -> dict | None:
    turnos = _normalizar(body.get("turnos_rotativos", ""))
    nombre = body.get("nombre", "No indicado")
    if turnos == "no":
        razon = "No acepta turnos rotativos"
        return {
            "semaforo": "RECHAZAR", "puntaje": 0, "nombre": nombre,
            "telefono": body.get("telefono", "No indicado"),
            "email":    body.get("email", "No indicado"),
            "bachiller": "No evaluado",
            "detalle_educacion": "No evaluado — descarte previo al análisis",
            "anios_experiencia": 0,
            "experiencia_detalle": "No evaluado — descarte previo al análisis",
            "disponibilidad": body.get("disponibilidad_inmediata", "No indica"),
            "movilidad": None, "nota_talento": None,
            "resumen": "Candidato descartado automáticamente por no cumplir requisitos mínimos.",
            "preguntas_entrevista": [],
            "alertas": [f"🚫 DESCARTADO AUTOMÁTICAMENTE: {razon}"],
            "razon_semaforo": f"Descarte sin análisis de IA: {razon}. Costo: $0.",
            "_ia_utilizada": "Sin IA — descarte previo",
            "_costo_usd": 0.0,
        }
    return None


def _advertencias_disponibilidad(body: dict) -> list[str]:
    alertas = []
    disp_inm = _normalizar(body.get("disponibilidad_inmediata", ""))
    fines    = _normalizar(body.get("fines_semana", ""))
    if "notificar" in disp_inm or disp_inm == "no":
        alertas.append("⚠️ ATENCIÓN: NO tiene disponibilidad inmediata (debe notificar a su trabajo actual)")
    if fines == "no":
        alertas.append("⚠️ ATENCIÓN: NO cuenta con disponibilidad para fines de semana/feriados")
    return alertas


# ── Procesamiento principal ──────────────────────────────────────────────────

def _procesar_cv_sync(body: dict) -> dict:
    spreadsheet = get_spreadsheet()
    creds       = get_creds()
    nombre      = body.get("nombre", "desconocido")
    cedula      = body.get("cedula", "").strip()
    file_id     = body.get("file_id")

    thread_id = threading.current_thread().name
    print(f"[{thread_id}] Iniciando CV: {nombre} ({cedula})")

    try:
        # ── 1. Pre-filtro disponibilidad ──────────────────────────────────────
        descarte = _pre_filtrar(body)
        if descarte:
            razon = descarte["alertas"][0]
            escribir_log(spreadsheet, "INFO", f"Descarte previo: {nombre}", razon)
            metadata = _build_metadata(body, nombre)
            # No corremos Background ni SETEC para descartados (ahorra dinero)
            descarte["bachiller_oficial_resumen"] = "—"
            descarte["coincide_cv"]               = "—"
            descarte["satje_resumen"]             = "—"
            descarte["setec_resumen"]             = "—"
            escribir_candidato(spreadsheet, descarte, metadata)
            escribir_log(spreadsheet, "OK", f"RECHAZAR (descarte) — {nombre}",
                         descarte["razon_semaforo"],
                         ia="Sin IA — descarte previo", costo=0.0)
            return {"status": "ok", "semaforo": "RECHAZAR", "nombre": nombre, "razon": razon}

        # ── 2. Advertencias de disponibilidad ─────────────────────────────────
        advertencias_disp = _advertencias_disponibilidad(body)

        # ── 3. Descargar y extraer PDF ────────────────────────────────────────
        pdf_bytes  = descargar_pdf_drive(file_id, creds)
        extraccion = extraer_desde_drive(file_id, creds)
        texto      = extraccion["texto"]
        necesita_vision = extraccion["necesita_vision"]
        escribir_log(spreadsheet, "INFO", f"CV recibido: {nombre}",
                     f"Páginas: {extraccion['paginas']} | "
                     f"Modo: {'visión' if necesita_vision else 'texto'} | Hilo: {thread_id}")

        # ── 4. Leer configuración del cargo ───────────────────────────────────
        config = leer_configuracion(spreadsheet)

        # ── 5. Analizar con IA ────────────────────────────────────────────────
        resultado = analizar_cv(
            texto=texto, config=config,
            pdf_bytes=pdf_bytes if necesita_vision else None,
            necesita_vision=necesita_vision,
            spreadsheet=spreadsheet, nombre=nombre,
        )

        # ── 6. Background Check + SETEC EN PARALELO ───────────────────────────
        # Ambas son llamadas HTTP independientes al bg-api. SETEC tarda ~20-60s
        # (Playwright). Si las hacemos en serie, sumamos tiempos. ThreadPoolExecutor
        # local de 2 workers para correrlas concurrentemente.
        bg    = {"semaforo": "GRIS"}
        setec = {}
        if cedula:
            if not _cedula_valida_ec(cedula):
                print(f"[{thread_id}] Cédula '{cedula}' inválida (no pasa dígito verificador) — saltando bg-api+SETEC")
                escribir_log(spreadsheet, "WARN",
                             f"Cédula inválida: {nombre}",
                             f"'{cedula}' no pasa validación del Registro Civil — bg-api+SETEC no consultados",
                             ia="validación local", costo=0.0)
            else:
                print(f"[{thread_id}] Consultando background + SETEC en paralelo para {cedula}...")
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"bg-{cedula[:4]}") as ex:
                    f_bg    = ex.submit(consultar_background_sync, cedula)
                    f_setec = ex.submit(consultar_setec_sync, cedula)
                    bg    = f_bg.result()
                    setec = f_setec.result()
                setec_status = "OK" if setec.get("tiene_certificados") else ("ERROR" if setec.get("error") else "sin")
                escribir_log(spreadsheet, "INFO",
                             f"Background+SETEC: {nombre}",
                             f"BG semáforo={bg.get('semaforo')} | "
                             f"SETEC={setec_status} ({setec.get('total_cursos', 0)} cert.) | "
                             f"tiempo BG={bg.get('tiempo_seg', '?')}s",
                             ia="bg-api", costo=0.005)  # 2 llamadas en paralelo

        # ── 7. Calcular Semáforo FINAL y agregar campos al resultado ──────────
        cv_semaforo  = resultado.get("semaforo", "AMARILLO")
        bachiller_ia = resultado.get("bachiller", "")
        bachiller_of = bg.get("bachiller", {})
        satje        = bg.get("satje", {})

        semaforo_final = _calcular_semaforo_final(cv_semaforo, bg, spreadsheet)
        coincide       = _verificar_consistencia(bachiller_ia, bachiller_of)

        # Sobreescribir el semáforo principal con el FINAL (mom filtra por columna E)
        resultado["semaforo"]                   = semaforo_final
        resultado["semaforo_cv_solo"]           = cv_semaforo
        resultado["bachiller_oficial_resumen"]  = _resumir_bachiller_oficial(bachiller_of)
        resultado["coincide_cv"]                = coincide
        resultado["satje_resumen"]              = _resumir_satje(satje)
        resultado["setec_resumen"]              = _resumir_setec(setec)

        # Inyectar advertencia "mintió en CV" si aplica
        if coincide == "MINTIO":
            resultado.setdefault("alertas", []).insert(
                0, "🚨 INCONSISTENCIA: CV dice bachiller pero Ministerio NO lo confirma"
            )

        # Enriquecer "razón veredicto" con datos BG
        razon_actual = resultado.get("razon_semaforo", "")
        razon_bg     = f"BG: {resultado['bachiller_oficial_resumen']} · {resultado['satje_resumen']}"
        resultado["razon_semaforo"] = f"{razon_actual} | {razon_bg}".strip(" |")

        # ── 8. Alerta Telegram si delito grave ────────────────────────────────
        es_grave, delitos_graves = _tiene_delito_grave(satje, spreadsheet)
        if es_grave:
            resultado.setdefault("alertas", []).insert(
                0, f"🚨 DELITOS GRAVES: {', '.join(delitos_graves)}"
            )
            _enviar_alerta_telegram(nombre, cedula, delitos_graves)

        # ── 9. Inyectar advertencias de disponibilidad (al inicio) ────────────
        if advertencias_disp:
            for aviso in reversed(advertencias_disp):
                resultado.setdefault("alertas", []).insert(0, aviso)

        # ── 10. Escribir en Sheet ─────────────────────────────────────────────
        metadata = _build_metadata(body, nombre)
        escribir_candidato(spreadsheet, resultado, metadata)
        escribir_log(spreadsheet, "OK",
                     f"{semaforo_final} — {nombre}",
                     resultado.get("razon_semaforo", ""),
                     ia=resultado.get("_ia_utilizada", ""),
                     costo=resultado.get("_costo_usd"))

        print(f"[{thread_id}] ✅ {nombre} → FINAL: {semaforo_final} (CV: {cv_semaforo}, BG: {bg.get('semaforo')})")
        return {"status": "ok", "semaforo": semaforo_final, "nombre": resultado.get("nombre"),
                "cv": cv_semaforo, "bg": bg.get("semaforo")}

    except Exception as e:
        escribir_log(spreadsheet, "ERROR", f"Fallo procesando CV de {nombre}", str(e))
        capture_exception("procesar_cv_sync", e,
                          extra={"file_id": file_id, "cedula": cedula,
                                 "nombre": nombre, "thread": thread_id})
        raise


def _build_metadata(body: dict, nombre: str) -> dict:
    return {
        "nombre_form":         nombre,
        "email_form":          body.get("email", ""),
        "telefono_form":       body.get("telefono", ""),
        "cedula_form":         body.get("cedula", ""),
        "disponibilidad_form": body.get("disponibilidad_inmediata", ""),
        "turnos_form":         body.get("turnos_rotativos", ""),
        "fines_semana_form":   body.get("fines_semana", ""),
        "movilidad_form":      body.get("movilidad", ""),
        "drive_link":          body.get("drive_link", ""),
    }


# ── Eventos ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    app.state.semaforo_cvs = asyncio.Semaphore(MAX_WORKERS)
    print("🚀 RUBASA CV Worker v5 — con Background Checks integrado")
    print(f"   BG_API_URL: {BG_API_URL}")
    try:
        spreadsheet = get_spreadsheet()
        escribir_log(spreadsheet, "OK", "SISTEMA ONLINE",
                     "CV Worker v5 — integración Background Checks activa")
        print("✅ Conexión a Google Sheets confirmada.")
    except Exception as e:
        print(f"❌ Error al conectar con Google Sheets: {e}")


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status":  "ok",
        "sistema": "RUBASA CV Worker v5",
        "workers": 3,
        "endpoints": ["/webhook", "/health"],
        "bg_api":  BG_API_URL,
        "descripcion": "CV Worker + Background Checks (Bachiller + SATJE)",
    }


@app.get("/health")
def health(deep: bool = False):
    """
    Healthcheck.
      /health         — liveness simple (rápido, lo usa Docker HEALTHCHECK)
      /health?deep=1  — valida dependencias externas: bg-api + Google Sheets
                        (más lento, no usar como liveness)
    """
    base = {
        "status":              "ok",
        "version":             "5.4.1",
        "webhook_auth":        "enabled" if WEBHOOK_SECRET else "DISABLED (configurar WEBHOOK_SECRET)",
        "sentry":              "enabled" if os.getenv("SENTRY_DSN") else "disabled",
        "idempotency_cache":   len(_proc_cache),
        "in_flight":           len(_proc_in_flight),
    }
    if not deep:
        return base

    # Deep check — útil para dashboards y alertas
    deps: dict[str, Any] = {}

    # 1) bg-api
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{BG_API_URL}/health")
            deps["bg_api"] = {
                "status":      "ok" if r.status_code == 200 else "degraded",
                "http_code":   r.status_code,
                "url":         BG_API_URL,
            }
    except Exception as e:
        deps["bg_api"] = {"status": "down", "error": str(e)[:120], "url": BG_API_URL}

    # 2) Google Sheets (intentar abrir el spreadsheet cacheado)
    try:
        ss = get_spreadsheet()
        deps["google_sheets"] = {"status": "ok", "title": ss.title[:60]}
    except Exception as e:
        deps["google_sheets"] = {"status": "down", "error": str(e)[:120]}

    # Estado global
    overall = "ok"
    for v in deps.values():
        if v.get("status") == "down":
            overall = "down"
            break
        if v.get("status") == "degraded" and overall == "ok":
            overall = "degraded"

    return {**base, "status": overall, "deps": deps}


@app.post("/webhook")
async def webhook(
    payload:        WebhookPayload,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Procesa un CV desde el Google Form.

    Seguridad:
      - Header `X-Webhook-Secret` debe coincidir con WEBHOOK_SECRET (env).
      - Payload validado por Pydantic — si falla, 422 antes de gastar IA.
      - Idempotencia por `file_id` con TTL 1h: reintentos no duplican filas.
    """
    # 1. Auth
    _verificar_secret(x_webhook_secret)

    # 2. Idempotencia
    cached = _idempotency_check(payload.file_id)
    if cached is not None:
        # Caso A: ya está en proceso por otro thread — esperar al Event
        if "_wait_for" in cached:
            evt: threading.Event = cached["_wait_for"]
            # Esperar afuera del lock — máx BG_TIMEOUT+30s antes de timeout HTTP
            if evt.wait(timeout=BG_TIMEOUT + 30):
                # Reconsultar cache ya con el resultado
                with _proc_lock:
                    if payload.file_id in _proc_cache:
                        r = _proc_cache[payload.file_id]["result"]
                        return {**r, "_from_inflight_wait": True}
            raise HTTPException(status_code=504, detail="Procesamiento en curso, intenta de nuevo")
        # Caso B: resultado ya listo
        return {**cached, "_from_cache": True}

    # 3. Procesar normal — el Event ya quedó reservado en _proc_in_flight
    try:
        async with app.state.semaforo_cvs:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                _pool_cvs, _procesar_cv_sync, payload.model_dump()
            )
        _idempotency_finish(payload.file_id, result)
        return result
    except HTTPException:
        # Liberar el Event antes de relanzar
        _idempotency_finish(payload.file_id, {"status": "error", "detail": "HTTPException"})
        raise
    except Exception as e:
        capture_exception("webhook.procesar", e,
                          extra={"file_id": payload.file_id,
                                 "cedula": payload.cedula,
                                 "nombre": payload.nombre})
        _idempotency_finish(payload.file_id, {"status": "error", "detail": str(e)[:200]})
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Endpoints administrativos ────────────────────────────────────────────────

class ReprocesarPayload(BaseModel):
    """Payload para forzar re-procesar un CV ya en idempotencia cache."""
    nombre:                   str = "No indicado"
    cedula:                   str = ""
    telefono:                 str = "No indicado"
    email:                    str = "No indicado"
    disponibilidad_inmediata: str = ""
    turnos_rotativos:         str = ""
    fines_semana:             str = ""
    movilidad:                str = ""
    drive_link:               str = ""
    model_config = {"extra": "allow"}


@app.post("/reprocesar/{file_id}")
async def reprocesar(
    file_id:        str,
    payload:        ReprocesarPayload | None = None,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Re-procesa un CV específico ignorando la idempotencia cache.
    Útil cuando:
      - Algo falló en producción y queremos re-correrlo
      - Quieres re-evaluar con prompts/criterios actualizados
      - El cache idempotency dice que ya está pero quieres forzar

    El body es opcional. Si se omite, se usan defaults vacíos.
    En la práctica conviene mandar al menos cedula+nombre.
    """
    _verificar_secret(x_webhook_secret)

    # Invalidar cache de idempotencia para este file_id
    with _proc_lock:
        _proc_cache.pop(file_id, None)
        _proc_in_flight.pop(file_id, None)

    body = (payload.model_dump() if payload else {})
    body["file_id"] = file_id

    try:
        async with app.state.semaforo_cvs:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(_pool_cvs, _procesar_cv_sync, body)
        _idempotency_finish(file_id, result)
        return {**result, "_reprocesado": True}
    except Exception as e:
        capture_exception("reprocesar", e, extra={"file_id": file_id})
        raise HTTPException(status_code=500, detail=str(e)[:200])


class BatchPayload(BaseModel):
    """Procesar N CVs en una sola llamada (sin pasar por Forms)."""
    cvs: list[WebhookPayload]


@app.post("/batch")
async def batch(
    payload:          BatchPayload,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Procesa una lista de CVs en paralelo (respeta el semáforo de concurrencia).
    Útil para:
      - Onboarding inicial: subir N CVs históricos de un cliente
      - Re-evaluar todos los candidatos después de cambiar el criterio
      - Migración desde otro sistema

    Cada CV pasa por la misma idempotencia: si el file_id ya está en cache,
    se devuelve el resultado anterior sin re-procesar.
    """
    _verificar_secret(x_webhook_secret)

    if not payload.cvs:
        raise HTTPException(status_code=400, detail="lista 'cvs' vacía")
    if len(payload.cvs) > 100:
        raise HTTPException(status_code=400, detail="máximo 100 CVs por batch")

    async def _procesar_uno(cv: WebhookPayload):
        # Cache hit
        cached = _idempotency_check(cv.file_id)
        if cached is not None and "_wait_for" not in cached:
            return {**cached, "_from_cache": True}

        try:
            async with app.state.semaforo_cvs:
                loop = asyncio.get_running_loop()
                r = await loop.run_in_executor(
                    _pool_cvs, _procesar_cv_sync, cv.model_dump()
                )
            _idempotency_finish(cv.file_id, r)
            return r
        except Exception as e:
            capture_exception("batch.procesar_uno", e,
                              extra={"file_id": cv.file_id, "cedula": cv.cedula})
            _idempotency_finish(cv.file_id, {"status": "error", "detail": str(e)[:200]})
            return {"file_id": cv.file_id, "status": "error", "detail": str(e)[:200]}

    resultados = await asyncio.gather(*[_procesar_uno(cv) for cv in payload.cvs])
    ok    = sum(1 for r in resultados if r.get("status") == "ok")
    error = sum(1 for r in resultados if r.get("status") == "error")
    return {
        "total":      len(payload.cvs),
        "ok":         ok,
        "error":      error,
        "resultados": resultados,
    }


# ── Compliance: derecho al olvido + healthcheck de scheduler ─────────────────

@app.delete("/admin/idempotency/{file_id}")
async def admin_borrar_idempotency(
    file_id: str,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Borra una entrada del cache de idempotencia (debug/admin)."""
    _verificar_secret(x_webhook_secret)
    with _proc_lock:
        existed = _proc_cache.pop(file_id, None)
        _proc_in_flight.pop(file_id, None)
    return {"file_id": file_id, "existia": existed is not None}


@app.get("/admin/idempotency")
async def admin_listar_idempotency(
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Lista el contenido del cache de idempotencia (debug)."""
    _verificar_secret(x_webhook_secret)
    ahora = time.time()
    with _proc_lock:
        return {
            "cache_size": len(_proc_cache),
            "in_flight":  len(_proc_in_flight),
            "entries": [
                {
                    "file_id": fid[:20],
                    "edad_seg": int(ahora - data["ts"]),
                    "status":   data["result"].get("status", "?"),
                    "nombre":   data["result"].get("nombre", "?"),
                }
                for fid, data in _proc_cache.items()
            ][:50],   # máx 50 para no inundar la respuesta
        }
