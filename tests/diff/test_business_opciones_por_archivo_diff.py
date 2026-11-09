"""Las opciones del compilador por archivo llegan tambien a ``diff`` y al banco de variantes."""

from pathlib import Path
from typing import Any

from construccion.test_compilacion import herramientas

from .ayudantes_variantes import EjecutorVariantes, crear_repo, crear_variantes, escribir_opciones, probar
from .test_comparacion import EjecutorDiff, comparar_funcion, repo_diff  # noqa: F401

OPCION = "-fno-schedule-insns"


def comandos_del_compilador(ejecutor: Any) -> list[list[str]]:
    return [c for c in ejecutor.comandos if Path(c[0]).name == "CC1PSX.EXE"]


def test_diff_anade_las_opciones_del_archivo_al_comando_del_compilador(repo_diff: Path) -> None:  # noqa: F811
    (repo_diff / "config").mkdir()
    (repo_diff / "config" / "opciones_compilacion.toml").write_text(
        f'[archivos.modulo_a]\ng = 8\nopciones = ["{OPCION}"]\n', encoding="utf-8"
    )
    ejecutor = EjecutorDiff(0)
    comparar_funcion(repo_diff, "rutina_a", herramientas(), Path("diff.py"), ejecutor)
    (comando,) = comandos_del_compilador(ejecutor)
    assert comando[1:5] == ["-quiet", "-O2", OPCION, "-G8"]


def test_diff_sin_la_clave_usa_el_mismo_comando_que_siempre(repo_diff: Path) -> None:  # noqa: F811
    (repo_diff / "config").mkdir()
    (repo_diff / "config" / "opciones_compilacion.toml").write_text(
        "[archivos.modulo_a]\ng = 8\n", encoding="utf-8"
    )
    ejecutor = EjecutorDiff(0)
    comparar_funcion(repo_diff, "rutina_a", herramientas(), Path("diff.py"), ejecutor)
    (comando,) = comandos_del_compilador(ejecutor)
    assert comando[1:4] == ["-quiet", "-O2", "-G8"]
    assert OPCION not in comando


def test_el_banco_de_variantes_compila_con_las_opciones_del_archivo(tmp_path: Path) -> None:
    raiz = tmp_path / "proyecto"
    crear_repo(raiz)
    escribir_opciones(raiz, f'[archivos.modulo_a]\ng = 8\nopciones = ["{OPCION}"]\n')
    carpeta = crear_variantes(tmp_path / "v", ["peor.c", "mejor.c"])
    ejecutor = EjecutorVariantes()
    probar(raiz, carpeta, ejecutor)
    comandos = comandos_del_compilador(ejecutor)
    assert comandos and all(OPCION in c and c.index(OPCION) < c.index("-G8") for c in comandos)


def test_las_opciones_de_otro_archivo_no_llegan_a_las_variantes(tmp_path: Path) -> None:
    raiz = tmp_path / "proyecto"
    crear_repo(raiz)
    escribir_opciones(raiz, f'[archivos.otro_archivo]\nopciones = ["{OPCION}"]\n')
    carpeta = crear_variantes(tmp_path / "v", ["mejor.c"])
    ejecutor = EjecutorVariantes()
    probar(raiz, carpeta, ejecutor)
    assert all(OPCION not in c for c in comandos_del_compilador(ejecutor))
