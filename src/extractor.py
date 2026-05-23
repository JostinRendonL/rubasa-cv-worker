import io
import pdfplumber
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Si el PDF tiene menos de este número de caracteres después de extraer,
# probablemente es un escaneo y necesita que Gemini lo lea visualmente.
MIN_CHARS_TEXTO = 150


def extraer_local(ruta_pdf: str) -> dict:
    """
    Lee un PDF desde el disco local (modo sandbox/desarrollo).
    Usa esto para probar sin pasar por Drive.
    """
    try:
        with pdfplumber.open(ruta_pdf) as pdf:
            paginas = len(pdf.pages)
            texto = "\n".join(
                (pagina.extract_text() or "") for pagina in pdf.pages
            ).strip()
    except Exception as e:
        return {"ok": False, "error": str(e), "texto": "", "necesita_vision": False}

    return {
        "ok": True,
        "texto": texto,
        "paginas": paginas,
        "necesita_vision": len(texto) < MIN_CHARS_TEXTO,
        "fuente": "local",
    }


def extraer_desde_drive(file_id: str, creds) -> dict:
    """
    Descarga un PDF desde Google Drive y extrae su texto.
    Se usa en producción cuando llega un webhook con el file_id.
    """
    try:
        service = build("drive", "v3", credentials=creds)

        # Descargar el archivo a memoria (sin tocardisco)
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)

        # Extraer texto del PDF en memoria
        with pdfplumber.open(buffer) as pdf:
            paginas = len(pdf.pages)
            texto = "\n".join(
                (pagina.extract_text() or "") for pagina in pdf.pages
            ).strip()

    except Exception as e:
        return {"ok": False, "error": str(e), "texto": "", "necesita_vision": False}

    return {
        "ok": True,
        "texto": texto,
        "paginas": paginas,
        "necesita_vision": len(texto) < MIN_CHARS_TEXTO,
        "fuente": "drive",
        "file_id": file_id,
    }
