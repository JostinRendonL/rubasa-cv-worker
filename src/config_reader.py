import gspread
from google.oauth2.service_account import Credentials


def leer_configuracion(spreadsheet, nombre_pestaña="Configuracion") -> dict:
    """
    Lee los criterios del cargo desde la pestaña Configuracion de la Sheet.
    Si la pestaña no existe o está vacía, devuelve los criterios por defecto
    para Auxiliar de Limpieza.
    """
    try:
        hoja = spreadsheet.worksheet(nombre_pestaña)
        filas = hoja.get_all_values()

        config = {}
        for fila in filas:
            if len(fila) >= 2 and fila[0].strip():
                clave = fila[0].strip().lower().replace(" ", "_")
                valor = fila[1].strip()
                config[clave] = valor

        if config:
            return config

    except Exception:
        pass

    # Valores por defecto si la pestaña no existe o está vacía
    return {
        "cargo": "Auxiliar de Limpieza",
        "experiencia_minima_años": "1",
        "educacion_minima": "Bachiller (por inferencia)",
        "movilidad": "bonus",
        "disponibilidad": "informativo",
        "palabras_clave_plus": "industrial, hospitalario, empresa, corporativo",
        "palabras_descarte_educacion": "solo primaria, no terminé el colegio, primaria completa, dejé el colegio",
    }
