"""Tests del módulo de vacantes (slugify + naming de pestañas)."""
import pytest

from src.vacantes import (
    slugify, validar_slug, slug_a_pascal,
    nombre_hoja_candidatos, nombre_hoja_config, etiqueta_legible,
)


class TestSlugify:
    def test_basico(self):
        assert slugify("Auxiliar de Limpieza") == "auxiliar_de_limpieza"

    def test_tildes(self):
        assert slugify("Jardinería") == "jardineria"

    def test_simbolos_y_espacios(self):
        assert slugify("Chofer / Conductor") == "chofer_conductor"
        assert slugify("  supervisor   ") == "supervisor"

    def test_vacio(self):
        assert slugify("") == ""
        assert slugify(None) == ""

    def test_corta_a_40(self):
        s = slugify("a" * 100)
        assert len(s) == 40


class TestValidarSlug:
    def test_acepta_validos(self):
        assert validar_slug("aux_limpieza") == "aux_limpieza"
        assert validar_slug("Supervisores")  == "supervisores"  # lowercase

    def test_rechaza_caracteres_peligrosos(self):
        # Anti-inyección de nombre de pestaña
        assert validar_slug("aux_limpieza; DROP TABLE") == ""
        assert validar_slug("../etc/passwd") == ""
        assert validar_slug("aux limpieza") == ""   # espacio no permitido
        assert validar_slug("aux-limpieza") == ""   # guion no permitido

    def test_vacio_o_invalido(self):
        assert validar_slug("") == ""
        assert validar_slug(None) == ""
        assert validar_slug("   ") == ""


class TestSlugAPascal:
    def test_basico(self):
        assert slug_a_pascal("aux_limpieza") == "AuxLimpieza"
        assert slug_a_pascal("supervisores") == "Supervisores"
        assert slug_a_pascal("choferes") == "Choferes"

    def test_multipalabra(self):
        assert slug_a_pascal("operador_de_maquinaria") == "OperadorDeMaquinaria"

    def test_vacio(self):
        assert slug_a_pascal("") == ""


class TestNombresPestañas:
    def test_candidatos_con_slug(self):
        assert nombre_hoja_candidatos("aux_limpieza") == "Candidatos_AuxLimpieza"
        assert nombre_hoja_candidatos("supervisores") == "Candidatos_Supervisores"

    def test_candidatos_sin_slug_fallback(self):
        # Backward compat con sistema mono-vacante
        assert nombre_hoja_candidatos("") == "Candidatos"
        assert nombre_hoja_candidatos(None) == "Candidatos"

    def test_candidatos_slug_invalido_fallback(self):
        assert nombre_hoja_candidatos("hack; DROP") == "Candidatos"

    def test_config_con_slug(self):
        assert nombre_hoja_config("aux_limpieza") == "Config_AuxLimpieza"
        assert nombre_hoja_config("choferes") == "Config_Choferes"

    def test_config_sin_slug_fallback(self):
        assert nombre_hoja_config("") == "Configuracion"


class TestEtiquetaLegible:
    def test_con_slug(self):
        assert etiqueta_legible("aux_limpieza") == "Aux Limpieza"
        assert etiqueta_legible("supervisores") == "Supervisores"

    def test_sin_slug(self):
        assert etiqueta_legible("") == "(global)"
