"""Reglas del empaquetado: el kit declara lo que importa y se puede publicar sin datos de un proyecto."""

import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ_KIT = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ_KIT / "psxdecomp"
MODULO_A_DISTRIBUCION = {"yaml": "pyyaml", "requests": "requests"}
pytestmark = pytest.mark.skipif(
    not PAQUETE.is_dir(), reason="el kit se ejecuta instalado: no hay arbol de fuentes junto a las pruebas"
)


@pytest.fixture(scope="module")
def pyproject() -> dict[str, object]:
    ruta = RAIZ_KIT / "pyproject.toml"
    if not ruta.is_file():
        pytest.skip("el kit se ejecuta instalado: no hay pyproject.toml junto a las pruebas")
    return tomllib.loads(ruta.read_text(encoding="utf-8"))


def _modulos_importados() -> set[str]:
    modulos: set[str] = set()
    for archivo in PAQUETE.rglob("*.py"):
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Import):
                modulos.update(alias.name.split(".")[0] for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                modulos.add(nodo.module.split(".")[0])
    return modulos


def _dependencias_declaradas(pyproject: dict[str, object]) -> set[str]:
    proyecto = pyproject["project"]
    assert isinstance(proyecto, dict)
    nombres = (
        re.split(r"[<>=!~\[ ]", dependencia, maxsplit=1)[0] for dependencia in proyecto["dependencies"]
    )
    return {nombre.lower() for nombre in nombres}


def test_toda_importacion_de_terceros_esta_declarada_como_dependencia(pyproject: dict[str, object]) -> None:
    propios = {"psxdecomp", "__future__"}
    terceros = {m for m in _modulos_importados() - propios if m not in sys.stdlib_module_names}
    declaradas = _dependencias_declaradas(pyproject)
    faltantes = {m for m in terceros if MODULO_A_DISTRIBUCION.get(m, m).lower() not in declaradas}
    assert not faltantes


def test_el_kit_nunca_importa_del_proyecto_consumidor() -> None:
    importados = _modulos_importados()
    assert "tools" not in importados


def test_el_paquete_declara_su_tipado_para_los_consumidores() -> None:
    assert (PAQUETE / "py.typed").is_file()


def test_los_metadatos_de_publicacion_estan_completos(pyproject: dict[str, object]) -> None:
    proyecto = pyproject["project"]
    assert isinstance(proyecto, dict)
    assert proyecto["name"] == "psx-decomp-kit"
    assert proyecto["license"] == "MIT"
    assert proyecto["readme"] == "README.md"
    assert proyecto["classifiers"]
    assert {"Repository", "Issues", "Changelog"} <= set(proyecto["urls"])


def test_la_version_del_proyecto_figura_en_el_registro_de_cambios(pyproject: dict[str, object]) -> None:
    proyecto = pyproject["project"]
    assert isinstance(proyecto, dict)
    registro = (RAIZ_KIT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{proyecto['version']}]" in registro


def test_la_licencia_nombra_titular_y_ano() -> None:
    texto = (RAIZ_KIT / "LICENSE").read_text(encoding="utf-8")
    assert re.search(r"Copyright \(c\) 20\d\d \S", texto)


ENTRADAS_ADMITIDAS = frozenset(
    {
        "psxdecomp",
        "tests",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        ".gitignore",
        "CONTRIBUTING.md",
        "SECURITY.md",
        ".github",
        ".git",
        ".gitattributes",
        # Productos locales de las herramientas de desarrollo; el .gitignore del kit los excluye.
        ".coverage",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
        "psx_decomp_kit.egg-info",
    }
)


def test_la_carpeta_del_kit_solo_contiene_lo_que_se_distribuye() -> None:
    nombres = {ruta.name for ruta in RAIZ_KIT.iterdir()}
    assert nombres <= ENTRADAS_ADMITIDAS, sorted(nombres - ENTRADAS_ADMITIDAS)


def test_el_extra_dev_trae_las_herramientas_de_calidad(pyproject: dict[str, object]) -> None:
    proyecto = pyproject["project"]
    assert isinstance(proyecto, dict)
    extra = proyecto["optional-dependencies"]["dev"]
    herramientas = {re.split(r"[<>=!~\[ ]", d, maxsplit=1)[0] for d in extra}
    assert {"pytest", "pytest-cov", "mypy", "ruff", "types-PyYAML", "types-requests"} <= herramientas


COMANDO_INSTALACION = 'python -m pip install -e ".[particion,comparacion,dev]"'
FLUJO_CI = RAIZ_KIT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def flujo_ci() -> str:
    return FLUJO_CI.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "requerido",
    [
        "ubuntu-latest",
        "windows-latest",
        '"3.13"',
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "pytest",
        "cancel-in-progress: true",
    ],
)
def test_la_integracion_continua_cubre_linux_y_windows_con_la_misma_cadena_de_calidad(
    flujo_ci: str, requerido: str
) -> None:
    assert requerido in flujo_ci


def test_la_integracion_continua_no_usa_secretos(flujo_ci: str) -> None:
    assert "secrets." not in flujo_ci


def test_el_token_de_la_integracion_continua_es_de_solo_lectura(flujo_ci: str) -> None:
    flujo = yaml.safe_load(flujo_ci)
    assert flujo["permissions"] == {"contents": "read"}


def test_la_integracion_continua_publica_el_informe_de_cobertura(flujo_ci: str) -> None:
    flujo = yaml.safe_load(flujo_ci)
    pasos = flujo["jobs"]["calidad"]["steps"]
    publicacion = [p for p in pasos if str(p.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(publicacion) == 1
    assert publicacion[0]["with"]["path"] == "coverage.xml"


@pytest.mark.parametrize("documento", [".github/workflows/ci.yml", "README.md", "CONTRIBUTING.md"])
def test_el_comando_de_instalacion_es_el_mismo_en_la_ci_y_en_la_documentacion(documento: str) -> None:
    assert COMANDO_INSTALACION in (RAIZ_KIT / documento).read_text(encoding="utf-8")


def test_mypy_se_ejecuta_en_modo_estricto(pyproject: dict[str, Any]) -> None:
    assert pyproject["tool"]["mypy"]["strict"] is True


def test_la_cobertura_exige_el_cien_por_ciento_de_lineas_y_ramas(pyproject: dict[str, Any]) -> None:
    herramientas = pyproject["tool"]
    assert herramientas["coverage"]["report"]["fail_under"] == 100
    assert herramientas["coverage"]["run"]["branch"] is True
    addopts = herramientas["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=100" in addopts
    assert "--cov-branch" in addopts


def test_los_finales_de_linea_se_normalizan_a_lf() -> None:
    atributos = (RAIZ_KIT / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in atributos.split()
