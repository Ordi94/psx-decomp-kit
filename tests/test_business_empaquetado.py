"""Reglas del empaquetado: el kit declara lo que importa y se puede publicar sin datos de un proyecto."""

import ast
import re
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ_KIT = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ_KIT / "psxdecomp"
MODULO_A_DISTRIBUCION = {"yaml": "PyYAML", "splat": "splat64"}
# Paquetes y modulos de primer nivel que no dependen de ningun extra; `diff` y `permutador` usan
# la comparacion difusa del extra `comparacion` y quedan fuera de esta lista.
NUCLEO = frozenset(
    {
        "__init__",
        "cli",
        "confinamiento",
        "constantes",
        "construccion",
        "dominio",
        "entorno",
        "lectura",
        "progreso",
        "proyecto",
        "toolchain",
        "validacion",
    }
)
pytestmark = pytest.mark.skipif(
    not PAQUETE.is_dir(), reason="el kit se ejecuta instalado: no hay arbol de fuentes junto a las pruebas"
)


@pytest.fixture(scope="module")
def pyproject() -> dict[str, object]:
    ruta = RAIZ_KIT / "pyproject.toml"
    if not ruta.is_file():
        pytest.skip("el kit se ejecuta instalado: no hay pyproject.toml junto a las pruebas")
    return tomllib.loads(ruta.read_text(encoding="utf-8"))


def _modulos_importados(archivos: Iterable[Path] | None = None) -> set[str]:
    modulos: set[str] = set()
    for archivo in PAQUETE.rglob("*.py") if archivos is None else archivos:
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Import):
                modulos.update(alias.name.split(".")[0] for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                modulos.add(nodo.module.split(".")[0])
    return modulos


def _nombre_de_distribucion(requisito: str) -> str:
    """Normaliza un requisito PEP 508 a su nombre de distribucion (minusculas, guiones)."""
    nombre = re.split(r"[<>=!~\[ ;]", requisito, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", nombre).lower()


def _requisitos(pyproject: dict[str, object], *, con_extras: bool) -> set[str]:
    proyecto = pyproject["project"]
    assert isinstance(proyecto, dict)
    requisitos = list(proyecto["dependencies"])
    if con_extras:
        for lista in proyecto["optional-dependencies"].values():
            requisitos.extend(lista)
    return {_nombre_de_distribucion(requisito) for requisito in requisitos}


def _terceros_sin_distribucion_declarada(archivos: Iterable[Path], declaradas: set[str]) -> set[str]:
    propios = {"psxdecomp", "__future__"}
    terceros = {m for m in _modulos_importados(archivos) - propios if m not in sys.stdlib_module_names}
    return {m for m in terceros if _nombre_de_distribucion(MODULO_A_DISTRIBUCION.get(m, m)) not in declaradas}


def test_toda_importacion_de_terceros_esta_declarada_como_dependencia_o_extra(
    pyproject: dict[str, object],
) -> None:
    declaradas = _requisitos(pyproject, con_extras=True)
    assert not _terceros_sin_distribucion_declarada(PAQUETE.rglob("*.py"), declaradas)


def test_el_nucleo_del_kit_funciona_sin_extras(pyproject: dict[str, object]) -> None:
    """Los modulos del nucleo solo importan de la biblioteca estandar o de las dependencias obligatorias."""
    obligatorias = _requisitos(pyproject, con_extras=False)
    archivos = [
        archivo
        for archivo in PAQUETE.rglob("*.py")
        if archivo.relative_to(PAQUETE).parts[0].removesuffix(".py") in NUCLEO
    ]
    assert archivos
    assert not _terceros_sin_distribucion_declarada(archivos, obligatorias)


def test_la_deteccion_de_terceros_rechaza_una_libreria_de_un_extra_en_el_nucleo(
    pyproject: dict[str, object], tmp_path: Path
) -> None:
    modulo = tmp_path / "modulo.py"
    modulo.write_text("import rapidfuzz\nimport yaml\nimport os\n", encoding="utf-8")
    assert _terceros_sin_distribucion_declarada([modulo], _requisitos(pyproject, con_extras=False)) == {
        "rapidfuzz"
    }
    assert not _terceros_sin_distribucion_declarada([modulo], _requisitos(pyproject, con_extras=True))


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


def _pasos_de_calidad(flujo_ci: str) -> list[dict[str, Any]]:
    return list(yaml.safe_load(flujo_ci)["jobs"]["calidad"]["steps"])


@pytest.mark.parametrize(
    "herramienta",
    [
        "python -m ruff check .",
        "python -m ruff format --check .",
        "python -m mypy",
        "python -m pytest",
    ],
)
def test_cada_herramienta_de_calidad_es_el_comando_de_un_paso_de_la_integracion_continua(
    flujo_ci: str, herramienta: str
) -> None:
    comandos = [str(paso.get("run", "")) for paso in _pasos_de_calidad(flujo_ci)]
    assert any(comando == herramienta or comando.startswith(herramienta + " ") for comando in comandos)


def test_la_integracion_continua_cubre_linux_y_windows_con_python_313(flujo_ci: str) -> None:
    trabajo = yaml.safe_load(flujo_ci)["jobs"]["calidad"]
    assert set(trabajo["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    preparar = [p for p in trabajo["steps"] if str(p.get("uses", "")).startswith("actions/setup-python@")]
    assert [p["with"]["python-version"] for p in preparar] == ["3.13"]


def test_la_integracion_continua_cancela_las_ejecuciones_superadas(flujo_ci: str) -> None:
    assert yaml.safe_load(flujo_ci)["concurrency"]["cancel-in-progress"] is True


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
    assert publicacion[0]["if"] == "always()"


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
