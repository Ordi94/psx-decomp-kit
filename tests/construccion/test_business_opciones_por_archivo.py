"""Reglas de negocio de las opciones del compilador por archivo (clave ``opciones`` junto a ``g``).

Un archivo que declara ``opciones`` las recibe despues de las globales y antes de ``-G``; los demas, y todo
proyecto sin la clave, compilan con el mismo comando de siempre.
"""

from pathlib import Path
from typing import Any

import pytest
from psxdecomp.construccion import compilacion as comp
from psxdecomp.construccion import dominio
from psxdecomp.construccion import infraestructura as infra
from psxdecomp.dominio import construir_compilacion, construir_convenciones, construir_rutas

from .test_business_construccion_mixta import SIN_DATOS, EjecutorC, construir, preparar
from .test_compilacion import herramientas
from .test_infraestructura import SALIDAS

CONVENCIONES = construir_convenciones({})
COMPILACION = construir_compilacion({})
RUTAS = construir_rutas({})
SCRIPT_DOS_ARCHIVOS = "main\n{\n    build/src/a.c.o(.text);\n    build/src/b.c.o(.text);\n}\n"


def opciones(**por_archivo: Any) -> dict[str, Any]:
    return {"archivos": {nombre: dict(valores) for nombre, valores in por_archivo.items()}}


# --- validacion ---------------------------------------------------------------------------------------


def test_las_opciones_de_un_archivo_se_leen_en_el_orden_declarado() -> None:
    datos = opciones(a={"g": 8, "opciones": ["-fno-schedule-insns", "-fno-peephole"]}, b={"g": 8})
    assert dominio.opciones_por_archivo(datos, CONVENCIONES) == {
        "a": ("-fno-schedule-insns", "-fno-peephole")
    }


def test_sin_la_clave_o_con_una_lista_vacia_el_archivo_no_aparece() -> None:
    assert dominio.opciones_por_archivo({}, CONVENCIONES) == {}
    assert dominio.opciones_por_archivo(opciones(a={"g": 8}, b={"opciones": []}), CONVENCIONES) == {}


def test_la_clave_opciones_no_cambia_el_g_declarado() -> None:
    datos = opciones(a={"g": 8, "opciones": ["-O1"]}, b={"opciones": ["-O1"]})
    assert dominio.valores_g_por_archivo(datos, CONVENCIONES) == {"a": 8, "b": 0}


@pytest.mark.parametrize(
    "malas",
    [
        "-fno-schedule-insns",
        {"x": 1},
        [1],
        [True],
        ["fno-schedule-insns"],
        ["-f no"],
        ["-"],
        ["-G8"],
        ["-o"],
        ["-fno;rm"],
        ["-a" * 20],
        ["-O1", "-O1"],
        [f"-f{i}" for i in range(17)],
    ],
)
def test_una_lista_de_opciones_invalida_se_rechaza_nombrando_el_campo(malas: Any) -> None:
    with pytest.raises(ValueError, match=r"'a\.opciones'"):
        dominio.opciones_por_archivo(opciones(a={"opciones": malas}), CONVENCIONES)


def test_el_limite_de_dieciseis_opciones_se_acepta() -> None:
    lista = [f"-f{chr(97 + i)}" for i in range(dominio.MAX_OPCIONES_ARCHIVO)]
    assert dominio.opciones_por_archivo(opciones(a={"opciones": lista}), CONVENCIONES) == {"a": tuple(lista)}


def test_el_esquema_del_archivo_sigue_validandose() -> None:
    with pytest.raises(ValueError, match="clave desconocida"):
        dominio.opciones_por_archivo(opciones(a={"extra": 1}), CONVENCIONES)
    with pytest.raises(ValueError, match="solo se admiten las tablas"):
        dominio.opciones_por_archivo({"otra": {}}, CONVENCIONES)


# --- comando del compilador -------------------------------------------------------------------------


def test_sin_opciones_adicionales_el_comando_es_identico_al_de_siempre() -> None:
    base = comp.comando_compilar(Path("CC1PSX.EXE"), "a.i", "a.s", 8, max_valor_g=64, compilacion=COMPILACION)
    vacio = comp.comando_compilar(
        Path("CC1PSX.EXE"), "a.i", "a.s", 8, max_valor_g=64, compilacion=COMPILACION, opciones_extra=()
    )
    assert base == vacio == ["CC1PSX.EXE", "-quiet", "-O2", "-G8", "a.i", "-o", "a.s"]


def test_las_opciones_adicionales_van_despues_de_las_globales_y_antes_de_g() -> None:
    comando = comp.comando_compilar(
        Path("CC1PSX.EXE"),
        "a.i",
        "a.s",
        8,
        max_valor_g=64,
        compilacion=COMPILACION,
        opciones_extra=("-fno-schedule-insns",),
    )
    assert comando == ["CC1PSX.EXE", "-quiet", "-O2", "-fno-schedule-insns", "-G8", "a.i", "-o", "a.s"]


# --- lectura y construccion -------------------------------------------------------------------------


def escribir_opciones(raiz: Path, texto: str) -> None:
    (raiz / "config").mkdir(exist_ok=True)
    (raiz / RUTAS.opciones_compilacion).write_text(texto, encoding="utf-8")


def test_el_proyecto_sin_archivo_de_opciones_no_declara_opciones_adicionales(tmp_path: Path) -> None:
    assert infra.leer_opciones_por_archivo(tmp_path, rutas=RUTAS, convenciones=CONVENCIONES) == {}


def test_el_proyecto_lee_las_opciones_de_su_archivo(tmp_path: Path) -> None:
    escribir_opciones(tmp_path, '[archivos.a]\ng = 8\nopciones = ["-fno-schedule-insns"]\n')
    leidas = infra.leer_opciones_por_archivo(tmp_path, rutas=RUTAS, convenciones=CONVENCIONES)
    assert leidas == {"a": ("-fno-schedule-insns",)}


def comandos_de_cc1(ejecutor: EjecutorC) -> dict[str, list[str]]:
    return {Path(c[-1]).name.split(".")[0]: c for c in ejecutor.comandos if Path(c[0]).name == "CC1PSX.EXE"}


def preparar_dos_archivos(raiz: Path) -> None:
    preparar(raiz, SCRIPT_DOS_ARCHIVOS)
    (raiz / "src" / "b.c").write_text("int y;\n", encoding="utf-8")
    (raiz / SALIDAS.script_enlazador).write_text(SCRIPT_DOS_ARCHIVOS, encoding="utf-8")


def test_build_anade_las_opciones_solo_al_comando_del_archivo_indicado(tmp_path: Path) -> None:
    preparar_dos_archivos(tmp_path)
    escribir_opciones(tmp_path, '[archivos.a]\ng = 8\nopciones = ["-fno-schedule-insns"]\n')
    ejecutor = EjecutorC(secciones=SIN_DATOS)
    construir(tmp_path, herramientas, ejecutor)
    comandos = comandos_de_cc1(ejecutor)
    assert "-fno-schedule-insns" in comandos["a"]
    assert comandos["a"].index("-fno-schedule-insns") > comandos["a"].index("-O2")
    assert comandos["a"].index("-fno-schedule-insns") < comandos["a"].index("-G8")
    assert "-fno-schedule-insns" not in comandos["b"]


def test_build_sin_la_clave_compila_con_el_mismo_comando_que_antes(tmp_path: Path) -> None:
    preparar_dos_archivos(tmp_path)
    ejecutor = EjecutorC(secciones=SIN_DATOS)
    construir(tmp_path, herramientas, ejecutor)
    sin_clave = comandos_de_cc1(ejecutor)
    escribir_opciones(tmp_path, "[archivos.a]\ng = 0\n")
    otro = EjecutorC(secciones=SIN_DATOS)
    construir(tmp_path, herramientas, otro)
    assert comandos_de_cc1(otro) == sin_clave
    assert sin_clave["a"][1:-3] == ["-quiet", "-O2", "-G0"]
