"""Tests de la lógica de compliance y semáforos del cv-worker (sin Google APIs)."""
import pytest


# Importamos solo las funciones puras (sin tocar Google APIs ni FastAPI)
from src.main import (
    _cedula_valida_ec,
    _verificar_consistencia,
    _tiene_delito_grave,
    _resumir_bachiller_oficial,
    _resumir_satje,
    _resumir_setec,
    _calcular_semaforo_final,
    _normalizar,
)


class TestCedulaValidaEc:
    def test_validas(self):
        assert _cedula_valida_ec("0954008272") is True
        assert _cedula_valida_ec("0925772246") is True

    def test_invalidas(self):
        assert _cedula_valida_ec("") is False
        assert _cedula_valida_ec("12345") is False
        assert _cedula_valida_ec("0954008273") is False  # último dígito mal
        assert _cedula_valida_ec("abc1234567") is False


class TestVerificarConsistencia:
    def test_coincide_cv_confirmado_y_titulo_oficial(self):
        r = _verificar_consistencia("CONFIRMADO", {"tiene_titulo": True})
        assert r == "COINCIDE"

    def test_mintio_cv_dice_si_pero_oficial_no(self):
        r = _verificar_consistencia("CONFIRMADO", {"tiene_titulo": False})
        assert r == "MINTIO"

    def test_bonus_cv_inferido_pero_oficial_si(self):
        r = _verificar_consistencia("INFERIDO", {"tiene_titulo": True})
        assert r == "COINCIDE"  # bonus: oficial confirma aunque CV no lo dijo claro

    def test_no_aplica_error_oficial(self):
        r = _verificar_consistencia("CONFIRMADO", {"estado": "ERROR"})
        assert r == "NO_APLICA"


class TestTieneDelitoGrave:
    def test_sin_procesos(self):
        es, lista = _tiene_delito_grave({"causas_demandado": []})
        assert es is False
        assert lista == []

    def test_homicidio_es_grave(self):
        satje = {"causas_demandado": [{"delito": "144 HOMICIDIO SIMPLE"}]}
        es, lista = _tiene_delito_grave(satje)
        assert es is True
        assert "HOMICIDIO" in lista

    def test_robo_es_grave(self):
        satje = {"causas_demandado": [{"delito": "ROBO AGRAVADO"}]}
        es, lista = _tiene_delito_grave(satje)
        assert es is True

    def test_delito_menor_no_dispara(self):
        satje = {"causas_demandado": [{"delito": "FALTA DE PAGO ALIMENTOS"}]}
        es, _ = _tiene_delito_grave(satje)
        assert es is False


class TestResumirBachillerOficial:
    def test_error(self):
        r = _resumir_bachiller_oficial({"estado": "ERROR", "detalle": "timeout"})
        assert "❌" in r
        assert "timeout" in r.lower()

    def test_no_encontrado(self):
        r = _resumir_bachiller_oficial({"estado": "NO_ENCONTRADO"})
        assert "NO encontrado" in r

    def test_encontrado(self):
        r = _resumir_bachiller_oficial({
            "tiene_titulo": True,
            "titulo": "Bachiller",
            "institucion": "UE Test",
            "fecha_grado": "2015-06-15",
        })
        assert "✅" in r
        assert "Bachiller" in r
        assert "UE Test" in r
        assert "2015" in r


class TestResumirSatje:
    def test_sin_procesos(self):
        r = _resumir_satje({"total_demandado": 0, "total_actor": 0})
        assert "Sin procesos" in r

    def test_solo_actor(self):
        r = _resumir_satje({"total_demandado": 0, "total_actor": 1})
        assert "actor" in r
        assert "1" in r

    def test_demandado_con_delito(self):
        r = _resumir_satje({
            "total_demandado": 1, "total_actor": 0,
            "causas_demandado": [{"delito": "144 HOMICIDIO"}]
        })
        assert "🔴" in r
        assert "HOMICIDIO" in r


class TestResumirSetec:
    def test_sin_dato(self):
        r = _resumir_setec({})
        assert r == "—"

    def test_error(self):
        r = _resumir_setec({"error": "timeout en MDT"})
        assert "❌" in r

    def test_sin_certificados(self):
        r = _resumir_setec({"tiene_certificados": False})
        assert "Sin registros" in r

    def test_con_certificados(self):
        r = _resumir_setec({
            "tiene_certificados": True,
            "detalle_cursos":     "PRIMEROS AUXILIOS (40h) | LIMPIEZA HOSPITALARIA (60h)",
            "total_cursos":       2,
        })
        assert "✅" in r
        assert "2 cert" in r
        assert "PRIMEROS AUXILIOS" in r


class TestCalcularSemaforoFinal:
    def test_critico_si_delito_grave(self):
        # CV apto pero SATJE con homicidio → CRITICO
        bg = {"semaforo": "VERDE", "satje": {
            "causas_demandado": [{"delito": "144 HOMICIDIO"}]
        }}
        r = _calcular_semaforo_final("APTO", bg)
        assert r == "CRITICO"

    def test_rechazar_si_cv_rojo(self):
        bg = {"semaforo": "VERDE", "satje": {"total_demandado": 0}}
        r = _calcular_semaforo_final("ROJO", bg)
        assert r == "RECHAZAR"

    def test_rechazar_si_demandado(self):
        bg = {"semaforo": "AMARILLO", "satje": {
            "total_demandado": 1,
            "causas_demandado": [{"delito": "ESTAFA"}],
        }}
        r = _calcular_semaforo_final("VERDE", bg)
        assert r == "RECHAZAR"

    def test_apto_si_todo_limpio(self):
        bg = {"semaforo": "VERDE", "satje": {"total_demandado": 0, "total_actor": 0}}
        r = _calcular_semaforo_final("VERDE", bg)
        assert r == "APTO"

    def test_sin_datos_si_bg_falla(self):
        bg = {"semaforo": "GRIS", "satje": {"total_demandado": 0}}
        r = _calcular_semaforo_final("AMARILLO", bg)
        assert r == "OBSERVACION"   # mantiene el nivel del CV


class TestNormalizar:
    def test_strip(self):
        assert _normalizar("  hola  ") == "hola"
    def test_lowercase(self):
        assert _normalizar("HOLA") == "hola"
    def test_none(self):
        assert _normalizar(None) == ""
