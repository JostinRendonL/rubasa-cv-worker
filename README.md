# 📋 RUBASA CV Worker v5

> Sistema de filtrado automático de hojas de vida (CV) con análisis por IA + verificación oficial de antecedentes.
> Cliente piloto: **RUBASA**.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](#despliegue)

---

## 🎯 Qué hace

1. Recibe webhook desde Google Forms cuando alguien postula
2. Pre-filtra candidatos que no aceptan turnos rotativos (sin gastar IA)
3. Descarga el CV de Google Drive y extrae texto (con fallback a visión por IA)
4. Lee la **Configuración del puesto** desde Google Sheets (cargo, requisitos, palabras clave)
5. Analiza el CV con **cadena de IAs** (GPT-4o Mini → Gemini → Llama 3.1, con fallback automático)
6. **NUEVO v5:** Verifica oficialmente vía [Background Checks Ecuador API](https://github.com/JostinRendonL/background-checks-ec):
   - Bachiller en el Ministerio de Educación
   - Procesos judiciales en SATJE (Función Judicial)
7. Combina ambos en un **semáforo FINAL** (🟢/🟡/🔴)
8. Escribe el reporte en la hoja **Candidatos** con formato profesional
9. Alerta por **Telegram** si detecta candidato con delitos graves

---

## 🚦 Semáforo FINAL

| Resultado | Significado |
|-----------|-------------|
| 🟢 VERDE | CV cumple requisitos + Bachiller verificado + Sin procesos judiciales |
| 🟡 AMARILLO | CV parcial, O sin título oficial, O mintió en CV, O procesos solo como actor |
| 🔴 ROJO | CV no cumple, O **tiene procesos judiciales como demandado** (alerta Telegram si grave) |

---

## 🏗️ Arquitectura

```
Postulante → Google Form → Google Sheet (raw)
                ↓
         Apps Script (trigger.gs) — onFormSubmit
                ↓
         POST https://cv.dentaklin.shop/webhook
                ↓
   ┌─────────────────────────────────────────────┐
   │   CV Worker (este repo)                      │
   │                                              │
   │  1. Pre-filtro disponibilidad                │
   │  2. Descarga CV (Drive API)                  │
   │  3. Extrae texto (PDF + visión fallback)     │
   │  4. Analiza con IA (chain con fallback)      │
   │  5. ──▶ Llama a bg-api ────────────────┐    │
   │  6. Combina semáforo CV × BG          │    │
   │  7. Escribe en hoja "Candidatos"      │    │
   └────────────────────────────────────────┼────┘
                                            ▼
                            ┌────────────────────────────┐
                            │  Background Checks API     │
                            │  (servicio separado)       │
                            │  - Ministerio de Educación │
                            │  - SATJE Función Judicial  │
                            └────────────────────────────┘
```

---

## 🔌 Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET`  | `/health` | Healthcheck |
| `GET`  | `/` | Info del sistema |
| `POST` | `/webhook` | Recibe la respuesta del Google Form (auto-llamado por Apps Script) |

---

## 📊 Hoja "Candidatos" — 22 columnas

| Col | Campo | Origen |
|-----|-------|--------|
| A-F | Fecha, Nombre, Teléfono, Email, **Semáforo**, Puntaje | Sistema + IA |
| G-H | Bachiller (CV), Detalle Educación | IA |
| I-J | Años Exp, Experiencia detalle | IA |
| K-L | Disponibilidad, Movilidad | Formulario |
| M-N | Resumen, ⭐ Potencial | IA |
| O-Q | Preguntas Entrevista, Alertas, Razón | IA |
| R-S | CV link, Cédula | Formulario |
| **T** | **Bachiller MinEdu** | **Background API** |
| **U** | **Coincide CV** (✅/⚠️ MINTIÓ) | **Verificación cruzada** |
| **V** | **Procesos Judiciales** | **SATJE** |

---

## 🔐 Variables de entorno

Ver [`.env.example`](.env.example) para plantilla.

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `SHEET_ID` | ✅ | ID del Google Sheet |
| `SA_JSON` | ✅ | JSON del Service Account (toda la cadena) |
| `OPENROUTER_API_KEY` | ✅ | GPT-4o Mini (IA principal) |
| `GEMINI_API_KEY` | ⚪ | Fallback gratis |
| `GROQ_API_KEY` | ⚪ | Fallback gratis Llama |
| `BG_API_URL` | ✅ | URL del background-checks-ec (red interna Docker preferido) |
| `BG_API_KEY` | ✅ | API Key del background service |
| `TELEGRAM_BOT_TOKEN` | ⚪ | Alertas de delitos graves |
| `TELEGRAM_CHAT_ID` | ⚪ | Chat destino |

---

## 🚀 Despliegue

### Easypanel (recomendado — mismo VPS que bg-api)

1. Easypanel → New App → GitHub source
2. Repo: `JostinRendonL/rubasa-cv-worker`
3. Build: Dockerfile
4. Domain: `cv.dentaklin.shop` puerto `8000`
5. Environment: copiar variables del `.env.example`
6. Deploy

### Docker local

```bash
docker build -t rubasa-cv-worker .
docker run -d -p 8000:8000 --env-file .env --name cv-worker rubasa-cv-worker
```

---

## 💰 Costo por candidato

| Componente | Costo |
|-----------|-------|
| Análisis CV con GPT-4o Mini | ~$0.001 |
| Background Check (proxy + captcha) | ~$0.003 |
| **Total por candidato verificado** | **~$0.004** |

Para 100 candidatos/mes: **$0.40 USD totales**.

---

## 📄 Licencia

MIT
