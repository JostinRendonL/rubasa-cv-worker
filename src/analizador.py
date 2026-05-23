import os
import io
import json
import time
import base64
from datetime import datetime
import pdfplumber
import httpx
from google import genai

# ── Cadena de proveedores ──────────────────────────────────────────────────────
# Se intentan en orden. Si uno falla, se pasa al siguiente inmediatamente.
CADENA = [
    {
        "nombre":    "GPT-4o Mini",
        "proveedor": "OpenRouter",
        "tipo":      "openrouter",
        "modelo":    "openai/gpt-4o-mini",
        "vision":    True,
        "env_key":   "OPENROUTER_API_KEY",
        "costo_in":  0.15,   # USD por millón de tokens de entrada
        "costo_out": 0.60,   # USD por millón de tokens de salida
    },
    {
        "nombre":    "Gemini 3.1 Flash Lite",
        "proveedor": "Google",
        "tipo":      "gemini",
        "modelo":    "gemini-3.1-flash-lite-preview",
        "vision":    True,
        "env_key":   "GEMINI_API_KEY",
        "costo_in":  0.0,    # gratis hasta 500 req/día
        "costo_out": 0.0,
    },
    {
        "nombre":    "Llama 3.1 70B",
        "proveedor": "Groq",
        "tipo":      "groq",
        "modelo":    "llama-3.1-70b-versatile",
        "vision":    False,
        "env_key":   "GROQ_API_KEY",
        "costo_in":  0.0,    # gratis hasta ~14,400 req/día
        "costo_out": 0.0,
    },
]

MAX_INTENTOS  = 2   # intentos por proveedor antes de saltar al siguiente
ESPERA_SEG    = 5   # segundos entre reintentos del mismo proveedor


# ── Clasificadores de error ───────────────────────────────────────────────────

def _es_error_billing(exc) -> bool:
    """Error de saldo o facturación → saltar de proveedor sin reintentar."""
    msg    = str(exc).lower()
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return (
        status in (402, 403) or
        "billing" in msg or "payment" in msg or
        "exceeded your current quota" in msg or
        "your plan" in msg or "check your plan" in msg or
        "insufficient" in msg or "credits" in msg
    )


def _es_error_temporal(exc) -> bool:
    """Sobrecarga o cuota por minuto → reintentar en el mismo proveedor."""
    msg    = str(exc)
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return (
        status in (429, 503) or
        "429" in msg or "RESOURCE_EXHAUSTED" in msg or
        "503" in msg or "UNAVAILABLE" in msg or
        "high demand" in msg or "rate limit" in msg.lower()
    )


def _proveedor_disponible(cfg: dict) -> bool:
    """Verifica que la API key del proveedor esté configurada."""
    return bool(os.getenv(cfg["env_key"]))


# ── Llamadas a cada proveedor ─────────────────────────────────────────────────

def _llamar_openrouter(cfg: dict, prompt: str, pdf_bytes: bytes = None) -> tuple:
    api_key = os.getenv("OPENROUTER_API_KEY")

    # Construir contenido (texto o visión)
    if pdf_bytes and cfg.get("vision"):
        content = [{"type": "text", "text": prompt}]
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages:
                img = pagina.to_image(resolution=150).original
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
    else:
        content = prompt

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://rubasa.com.ec",
            "X-Title":       "RUBASA CV Analyzer",
        },
        json={
            "model":       cfg["modelo"],
            "messages":    [{"role": "user", "content": content}],
            "temperature": 0.1,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def _llamar_groq(cfg: dict, prompt: str) -> tuple:
    api_key = os.getenv("GROQ_API_KEY")

    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        json={
            "model":       cfg["modelo"],
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=45.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def _llamar_gemini(cfg: dict, prompt: str, pdf_bytes: bytes = None) -> tuple:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    if pdf_bytes and cfg.get("vision"):
        partes = [prompt]
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages:
                partes.append(pagina.to_image(resolution=150).original)
        contents = partes
    else:
        contents = prompt
    resp = client.models.generate_content(model=cfg["modelo"], contents=contents)
    # Gemini no devuelve usage detallado en la misma forma, lo estimamos en 0
    return resp.text, {}


def _llamar(cfg: dict, prompt: str, pdf_bytes: bytes = None) -> tuple:
    """Dispatcher: llama al proveedor correcto y devuelve (texto, usage)."""
    if cfg["tipo"] == "openrouter":
        return _llamar_openrouter(cfg, prompt, pdf_bytes)
    elif cfg["tipo"] == "gemini":
        return _llamar_gemini(cfg, prompt, pdf_bytes)
    elif cfg["tipo"] == "groq":
        return _llamar_groq(cfg, prompt)
    raise ValueError(f"Tipo desconocido: {cfg['tipo']}")


def _calcular_costo(cfg: dict, usage: dict) -> float:
    tokens_in  = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)
    return round(
        tokens_in  * cfg["costo_in"]  / 1_000_000 +
        tokens_out * cfg["costo_out"] / 1_000_000,
        6,
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

def _fecha_hoy() -> str:
    hoy   = datetime.now()
    dias  = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{dias[hoy.weekday()]}, {hoy.day} de {meses[hoy.month - 1]} de {hoy.year}"


def _criterios_por_cargo(cargo: str) -> str:
    """Devuelve criterios adicionales según el tipo de cargo."""
    c = cargo.lower()
    if any(k in c for k in ["limpieza", "aseo", "janitor", "conserje"]):
        return (
            "- Prioriza: disponibilidad inmediata, experiencia práctica en limpieza, honestidad.\n"
            "- No penalices ausencia de educación superior si hay experiencia relevante.\n"
            "- Valora especialmente: experiencia en empresas, hospitales o edificios sobre casas familiares."
        )
    elif any(k in c for k in ["ti", "soporte", "sistemas", "técnico", "tecnolog", "it "]):
        return (
            "- Prioriza: certificaciones técnicas reales (CompTIA, Cisco, Microsoft, etc.).\n"
            "- Penaliza: conocimiento solo teórico sin experiencia práctica comprobable.\n"
            "- Valora: años de experiencia en soporte real, no solo cursos."
        )
    elif any(k in c for k in ["guardia", "seguridad", "vigilancia"]):
        return (
            "- Prioriza: experiencia en vigilancia empresarial o corporativa.\n"
            "- Valora: cursos de seguridad, licencias vigentes, experiencia en empresa sobre casas.\n"
            "- Disponibilidad para turnos nocturnos es un plus importante."
        )
    else:
        return "- Evalúa con criterio equilibrado según la experiencia y educación indicadas."


def _construir_prompt(texto: str, config: dict) -> str:
    cargo             = config.get("cargo", "Auxiliar de Limpieza")
    exp_min           = config.get("experiencia_minima_años", "1")
    palabras_plus     = config.get("palabras_clave_plus", "industrial, hospitalario, empresa")
    palabras_descarte = config.get(
        "palabras_descarte_educacion",
        "solo primaria, no terminé el colegio, primaria completa"
    )
    tipo_experiencia  = config.get(
        "tipo_experiencia_requerida",
        f"experiencia directa en el rol de {cargo} en empresas o instituciones formales"
    )

    return f"""Eres un experto en recursos humanos de RUBASA, empresa en Guayaquil, Ecuador.
Hoy es {_fecha_hoy()}. Usa esta fecha para calcular antigüedad correctamente; cualquier fecha hasta hoy NO es futura.
Analiza el siguiente CV para el cargo de {cargo}.
Experiencia mínima requerida: {exp_min} año(s).

══ REGLAS DE EDUCACIÓN (aplica en orden) ══════════════════════════
1. BACHILLER CONFIRMADO → el CV menciona directamente:
   bachiller, secundaria completa, educación media, colegio culminado.

2. BACHILLER INFERIDO → el CV menciona cualquiera de los siguientes (en Ecuador
   todos requieren bachillerato aprobado para poder inscribirse):

   Términos genéricos de nivel superior:
   tecnólogo/a, técnico superior, tercer nivel, cuarto nivel, pregrado, posgrado,
   universidad, carrera universitaria, politécnico/a, escuela superior,
   ingeniería, licenciatura, maestría, magíster, doctorado, especialización,
   egresado/a de [carrera], graduado/a de [carrera], título de [carrera],
   estudiante de [carrera], cursando [carrera], semestres aprobados,
   en proceso de graduación, técnico en [área].

   Carreras técnico-industriales:
   electromecánica, mecatrónica, mecánica automotriz, mecánica industrial,
   electricidad, electricista industrial, electrónica, electrónica industrial,
   soldadura, refrigeración y aire acondicionado, automotriz, motores,
   mantenimiento industrial, instrumentación, hidráulica, neumática.

   Carreras de salud:
   enfermería, auxiliar de enfermería (con título de instituto), medicina,
   odontología, farmacia, nutrición, fisioterapia, terapia física,
   psicología, laboratorio clínico, radiología, optometría, paramédico.

   Carreras administrativas y de negocios:
   contabilidad, CPA, auditoría, administración de empresas, gestión empresarial,
   marketing, mercadotecnia, finanzas, economía, comercio exterior,
   negocios internacionales, recursos humanos, logística, cadena de suministro,
   secretariado ejecutivo, relaciones públicas, banca y finanzas.

   Carreras de tecnología e informática:
   computación, sistemas, redes, programación, desarrollo de software,
   tecnología de la información, TI, soporte técnico (con título de instituto),
   seguridad informática, análisis de sistemas, bases de datos, diseño web.

   Carreras de construcción y afines:
   arquitectura, construcción civil, topografía, diseño de interiores,
   gestión de obras, seguridad industrial, SSO, salud y seguridad ocupacional.

   Carreras de servicios y humanidades:
   turismo, hotelería y turismo, gastronomía, chef (con título de instituto),
   comunicación social, periodismo, diseño gráfico, diseño,
   trabajo social, derecho, educación, pedagogía, docencia,
   agronomía, veterinaria, ambiental, medio ambiente, química.

   Tipo de bachillerato que ya ES confirmado (no inferido):
   "bachiller técnico en [especialidad]" → cuenta como CONFIRMADO.

   REGLA CLAVE: si el CV indica CUALQUIER estudio post-colegio (aunque sea
   un técnico de 1 año, en curso o sin terminar), el bachillerato está
   IMPLÍCITO → marca INFERIDO. Ante la duda, INFERIDO es siempre mejor
   que NO_CUMPLE.

3. AMBIGUO → el CV menciona algún tipo de estudio pero no queda claro si
   terminó el colegio (ej: "cursé el bachillerato", "estudié 1 año de colegio").

4. NO_CUMPLE → SOLO si el CV dice EXPLÍCITAMENTE:
   "solo primaria", "educación primaria", "primaria completa",
   "no terminé el colegio", "dejé el colegio", "bachillerato incompleto".
   Si hay CUALQUIER duda, usa AMBIGUO en vez de NO_CUMPLE.

5. Sin datos → si el CV NO menciona educación en ninguna parte → AMBIGUO
   (no se descarta, se marca para aclarar en entrevista).

══ REGLAS DE EXPERIENCIA ════════════════════════════════════════════
"Experiencia" = tiempo ejerciendo la FUNCIÓN ESPECÍFICA de {cargo}, no
simplemente haber trabajado en una empresa.

REGLA CLAVE: si el candidato trabajó en una empresa pero en un ROL
COMPLETAMENTE DISTINTO a {cargo}, esos años NO se suman a anios_experiencia.
Ejemplo: para {cargo}, haber sido RRHH, soporte TI, vendedor o cajero
en una empresa NO cuenta como experiencia válida.

TIPO DE EXPERIENCIA VÁLIDA PARA ESTE CARGO:
{tipo_experiencia}

EJEMPLOS OBLIGATORIOS para aplicar el tipo de experiencia:
  - Limpieza EN hospitales, clinicas, centros de salud, laboratorios: SI cuenta como tipo correcto
  - Limpieza en oficinas corporativas: NO es tipo correcto aunque sea empresa grande
  - Limpieza en casas de familia: NO es tipo correcto
  - "Empresa de limpieza" o "empresa de servicios de limpieza" NO equivale a experiencia hospitalaria
    Lo que importa es el LUGAR fisico donde se limpio, no el nombre ni tipo de empresa contratante
  - Si el CV no menciona hospitales, clinicas ni centros de salud en ningun trabajo: tipo NO cumplido

Reglas de puntuacion:
- Cuenta con peso completo: experiencia en {cargo} dentro de hospitales o clinicas ({palabras_plus})
- Cuenta con peso reducido + genera alerta: experiencia en {cargo} en oficinas o empresas generales
- NO cuenta: experiencia en {cargo} solo en casas de familia
- NO cuenta: roles distintos a {cargo}

══ TABLA DE DECISION SEMAFORO — SIGUE ESTE CUADRO EXACTO ══════════

Situacion                                          | Semaforo | Puntaje base
---------------------------------------------------|----------|-------------
Exp. tipo CORRECTO (sector salud) >= {exp_min} anos | VERDE    | 70-100
Exp. tipo CORRECTO (sector salud) < {exp_min} anos  | AMARILLO | 50-69
Exp. tipo INCORRECTO (oficinas/casas) cualq. anos   | AMARILLO | 40-60
Cero experiencia en limpieza de ningun tipo         | AMARILLO | 30-45
Educacion NO_CUMPLE (solo primaria confirmada)      | ROJO     | 0-30

ATENCION: "tipo incorrecto" = AMARILLO, NUNCA ROJO.
Tener anos de limpieza en el lugar equivocado no es lo mismo que no tener experiencia.
El candidato con 5 anos en oficinas y hogares va a AMARILLO con alerta — no a ROJO.
ROJO solo si la educacion es NO_CUMPLE. El pre-filtro de turnos ya manejo el ROJO de disponibilidad.

EJEMPLO CONCRETO para que no haya confusion:
  Candidato con 3 anos limpiando oficinas + 2 anos casas de familia, bachiller confirmado
  → semaforo: AMARILLO, puntaje: 50, anios_experiencia: 0
  → alerta: "Tiene 5 anos de experiencia en limpieza de oficinas y hogares, pero el cargo
    requiere experiencia especifica en hospitales o clinicas del sector salud."

CAMPO anios_experiencia: suma SOLO los anos en el tipo de lugar correcto.
Experiencia en lugares incorrectos NO se suma pero SÍ va en experiencia_detalle y alertas.

══ CRITERIOS ESPECÍFICOS PARA ESTE CARGO ══════════════════════════
{_criterios_por_cargo(cargo)}

══ DATOS INFORMATIVOS (no excluyentes) ════════════════════════════
- Disponibilidad inmediata: anotar, no afecta el veredicto
- Movilidad propia: suma puntos (+5), no descarta si no la tiene

══ PREGUNTAS DE ENTREVISTA — REGLAS ESTRICTAS ═════════════════════
Genera EXACTAMENTE 3 preguntas.

El entrevistador ya sabe preguntar "¿qué hacías en ese trabajo?" o "¿cuáles eran
tus funciones?". Tu trabajo es generar las preguntas que SOLO se pueden formular
leyendo ESTE CV — las que van directo a donde hay algo que aclarar o verificar.

PROHIBIDO — si una pregunta cae aquí, deséchala y reformúlala:
  ✗ Cualquier pregunta que el entrevistador haría sin haber leído el CV
  ✗ Fortalezas, debilidades, trabajo en equipo, manejo del estrés — en abstracto
  ✗ "¿Qué funciones tenías en [empresa]?" — eso ya está en el CV
  ✗ Preguntas respondibles con conocimiento general del campo sin haber estado ahí

TIPOS DE PREGUNTA — usa uno diferente por cada una de las 3:

TIPO A — COMPROMISO DE DETALLE CONCRETO:
  Obliga al candidato a dar un dato específico que solo alguien que estuvo ahí
  sabe sin pensarlo. Si mintió, tiene que inventar en vivo y se nota.
  Ejemplos de lo que se puede preguntar (adapta al CV real):
  → "¿Cuántas personas había en tu equipo en [Empresa] y cómo se repartían las áreas?"
  → "¿Cómo llegabas al trabajo en [Empresa]? ¿A qué hora era tu entrada?"
  → "¿Quién era tu supervisor directo en [Empresa]?"

TIPO B — HISTORIA REAL (situación específica):
  Pide que cuente algo concreto que le haya pasado — no qué haría, sino qué pasó.
  Quien realmente trabajó ahí tiene historias. Quien no, divaga y se vuelve genérico.
  Ejemplos (adapta al CV real):
  → "Cuéntame de una situación difícil o fuera de lo normal que te haya tocado en
     [Empresa] — algo puntual que recuerdes bien. ¿Qué pasó y cómo lo resolviste?"
  → "¿Hubo algún conflicto con un compañero o jefe en [período]? ¿Cómo lo manejaste?"
  → "¿Cuál fue el trabajo más exigente que te tocó hacer en [Empresa]? ¿Qué implicó?"

TIPO C — CONTRASTE O COHERENCIA DEL CV:
  Señala algo del historial que no cuadra o necesita explicación: un gap, un salto
  de rol, estudios que contrastan con el cargo, salida abrupta de una empresa.
  Ejemplos (adapta al CV real):
  → "Entre [Empresa A] y [Empresa B] hay un período sin actividad — ¿qué hacías entonces?"
  → "Saliste de [Empresa] después de [tiempo corto] — ¿qué ocurrió ahí?"
  → "Estás cursando [carrera] — ¿cómo organizarías tus horarios de clases con turnos rotativos?"
  → "Venías trabajando en [área distinta] — ¿qué te llevó a querer cambiar a {cargo}?"

DISTRIBUCIÓN:
  • Historial con señales de alarma (gaps, rotación alta, salidas cortas): 2×TIPO C + 1×TIPO A o B
  • Historial limpio con experiencia directa: 1×TIPO A + 1×TIPO B + 1×TIPO C
  • Nunca dos preguntas del mismo tipo

══ TEXTO DEL CV ══════════════════════════════════════════════════════
{texto}

══ RESPUESTA ══════════════════════════════════════════════════════════
Responde ÚNICAMENTE con JSON válido, sin texto adicional, sin bloques markdown:

{{
  "semaforo": "VERDE | AMARILLO | ROJO",
  "puntaje": <número 0-100>,
  "nombre": "<nombre completo o No indicado>",
  "telefono": "<teléfono o No indicado>",
  "email": "<email o No indicado>",
  "bachiller": "<CONFIRMADO | INFERIDO | AMBIGUO | NO_CUMPLE>",
  "detalle_educacion": "<Detalla TODO lo académico en este orden: (1) título de colegio/bachillerato, (2) títulos universitarios o técnicos COMPLETADOS — si una carrera universitaria aparece en el CV sin la indicación '(en curso)', trátala como título completado y escríbela como 'Título: [nombre] — [universidad] ([facultad])'; (3) carreras EN CURSO — indícalas como 'Cursando [carrera] en [universidad] ([facultad])'. Si el CV lista varias carreras universitarias, incluye TODAS — completadas y en curso. No omitas ninguna entrada académica.>",
  "anios_experiencia": <número decimal, ej: 1.5>,
  "experiencia_detalle": "<descripción breve de dónde trabajó>",
  "disponibilidad": "<Inmediata | 15 días | 1 mes | No indica>",
  "movilidad": <true | false | null>,
  "resumen": "<3 a 5 líneas. Incluye: (1) perfil general del candidato, (2) experiencia más relevante para el cargo, (3) si tiene certificaciones, cursos destacados o formación adicional que aporten valor, menciónalos brevemente. No te limites a la experiencia laboral — un candidato con cursos de SSO, calidad o técnicos merece que eso aparezca aquí.>",
  "nota_talento": "<REGLA: la nota_talento es para candidatos con credenciales SUPERIORES al cargo — no para quienes simplemente encajan bien. Es OBLIGATORIA solo si cumple ALGUNO de estos criterios: (a) tiene carrera universitaria en curso o terminada (no cuenta el bachillerato solo), (b) tiene título técnico superior o tecnólogo en área distinta al cargo, (c) tiene experiencia previa en roles claramente superiores al cargo: supervisor, coordinador, SIG, SSO, proyectos, administración, etc., (d) tiene 5 o más certificaciones técnicas de instituciones reconocidas que lo posicionan muy por encima del perfil típico del cargo. DESCARTA nota_talento si: el candidato solo tiene bachiller aunque tenga cursos básicos, o si toda su experiencia y formación encaja directamente con el cargo actual sin exceder su perfil. Si cumple algún criterio, estructura en 3 partes: (1) credencial más fuerte con nombre exacto; (2) área de RUBASA donde encajaría mejor; (3) razón concreta por qué es oportunidad para la empresa. Hasta 4 líneas. Si no cumple → null.>",
  "preguntas_entrevista": ["<pregunta crítica 1 — específica al CV>", "<pregunta crítica 2>", "<pregunta crítica 3>"],
  "alertas": ["<alerta si aplica, o lista vacía []>"],
  "razon_semaforo": "<una oración explicando por qué ese veredicto>"
}}"""


def _limpiar_json(texto_raw: str) -> dict:
    texto = texto_raw.strip()
    if "```" in texto:
        for parte in texto.split("```"):
            parte = parte.strip()
            if parte.startswith("json"):
                parte = parte[4:].strip()
            if parte.startswith("{"):
                texto = parte
                break
    return json.loads(texto)


def _log(spreadsheet, mensaje: str, detalle: str = "") -> None:
    if spreadsheet:
        try:
            from src.writer import escribir_log
            escribir_log(spreadsheet, "WARN", mensaje, detalle)
        except Exception as e:
            print(f"[analizador] no pudo escribir log: {e}")


# ── Función principal ─────────────────────────────────────────────────────────

def analizar_cv(
    texto: str,
    config: dict,
    pdf_bytes: bytes = None,
    necesita_vision: bool = False,
    spreadsheet=None,
    nombre: str = "?",
) -> dict:
    """
    Analiza un CV con cadena de proveedores: OpenRouter → Groq.
    Máximo 2 intentos por proveedor con 5s de espera entre ellos.
    Salta al siguiente proveedor en menos de 20 segundos en total.
    Incluye en el resultado el modelo usado y el costo en USD.
    """
    prompt    = _construir_prompt(texto, config)
    pdf_vision = pdf_bytes if necesita_vision else None

    for cfg in CADENA:
        # Saltar si no hay API key configurada para este proveedor
        if not _proveedor_disponible(cfg):
            print(f"[analizador] {cfg['nombre']} sin API key, saltando")
            continue

        pnombre = f"{cfg['nombre']} / {cfg['proveedor']}"

        for intento in range(1, MAX_INTENTOS + 1):
            try:
                print(f"[analizador] {pnombre} — intento {intento}/{MAX_INTENTOS} ({nombre})")
                texto_resp, usage = _llamar(cfg, prompt, pdf_vision)
                resultado = _limpiar_json(texto_resp)

                # Enriquecer con metadata de costos
                resultado["_ia_utilizada"] = pnombre
                resultado["_costo_usd"]    = _calcular_costo(cfg, usage)

                print(f"[analizador] ✅ {pnombre} — costo: ${resultado['_costo_usd']:.6f}")
                return resultado

            except json.JSONDecodeError as e:
                print(f"[analizador] {pnombre} devolvió JSON inválido: {e}")
                _log(spreadsheet,
                     f"JSON inválido de {pnombre} para {nombre}",
                     "Saltando al siguiente proveedor")
                break  # no reintentar, ir al siguiente proveedor

            except Exception as e:
                if _es_error_billing(e):
                    print(f"[analizador] {pnombre} — error de billing/saldo, saltando")
                    _log(spreadsheet,
                         f"Sin saldo en {cfg['proveedor']} para {nombre}",
                         "Saltando al siguiente proveedor sin reintentar")
                    break

                elif _es_error_temporal(e):
                    if intento < MAX_INTENTOS:
                        print(f"[analizador] {pnombre} saturado, reintentando en {ESPERA_SEG}s...")
                        _log(spreadsheet,
                             f"Error temporal con {nombre} en {cfg['proveedor']}",
                             f"Reintentando en {ESPERA_SEG}s (intento {intento}/{MAX_INTENTOS})")
                        time.sleep(ESPERA_SEG)
                    else:
                        print(f"[analizador] {pnombre} agotado, probando siguiente proveedor")
                        _log(spreadsheet,
                             f"{cfg['proveedor']} no disponible para {nombre}",
                             "Cambiando al proveedor de respaldo...")
                else:
                    raise  # error inesperado — propagar

    # Todos los proveedores fallaron
    _log(spreadsheet,
         f"Todos los proveedores fallaron para {nombre}",
         "CV no procesado — reenviar el formulario cuando el servicio se recupere")

    return {
        "semaforo":        "AMARILLO",
        "puntaje":         0,
        "nombre":          nombre,
        "nota_talento":    None,
        "alertas":         ["Error: todos los proveedores de IA no disponibles. Reintentar más tarde."],
        "razon_semaforo":  "No se pudo analizar el CV por indisponibilidad temporal de los servicios de IA.",
        "_ia_utilizada":   "Sin proveedor disponible",
        "_costo_usd":      0.0,
    }
