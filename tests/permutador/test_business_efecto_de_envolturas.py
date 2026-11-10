"""Efecto de las envolturas en el registro: ejes de la puntuacion secundaria antes y despues de aceptarlas."""

import json
from pathlib import Path

from psxdecomp.diff.ejes import EjesPuntuacion
from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import busqueda as pm
from psxdecomp.permutador import c
from psxdecomp.permutador import estado as est
from psxdecomp.permutador import evaluacion as ev

from .ayudantes import FUNCION
from .test_business_busqueda import CABECERA, Reloj
from .test_business_envolturas_y_ejes import FUNCION_CON_LLAMADA

ANTES = EjesPuntuacion(operandos=3, reordenadas=2)
DESPUES = EjesPuntuacion(operandos=1, reordenadas=2)


def leer_registro(carpeta: Path) -> list[dict[str, object]]:
    return [json.loads(x) for x in (carpeta / "registro.jsonl").read_text(encoding="utf-8").splitlines()]


def crear(tmp_path: Path, ejes_partida: EjesPuntuacion | None) -> pm.Busqueda:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(FUNCION_CON_LLAMADA, FUNCION, frozenset({"Objeto"}))
    return pm.Busqueda(
        base,
        tabla,
        lambda texto, umbral: ev.ResultadoEvaluacion(50),
        estado=est.Estado(FUNCION, "codigo/modulo_a.c", 5, 50, 50, 50),
        carpeta=tmp_path / "estado",
        opciones=pm.Opciones(iteraciones=1),
        salida=lambda texto: None,
        reloj=Reloj(0.001),
        ejes_partida=ejes_partida,
    )


def variante(busqueda: pm.Busqueda, *, envuelta: bool, ejes: EjesPuntuacion | None) -> pm._Variante:
    texto = FUNCION_CON_LLAMADA
    if envuelta:
        texto = texto.replace("    g(y);", "    do {\n        g(y);\n    } while (0);")
    arbol = c.analizar_funcion(texto, FUNCION, frozenset({"Objeto"}))
    return pm._Variante(texto, arbol, ["m"], ev.ResultadoEvaluacion(10, ejes=ejes))


def test_la_linea_que_acepta_una_envoltura_lleva_los_ejes_antes_y_despues(tmp_path: Path) -> None:
    est.anadir_registro(
        tmp_path, 7, 10, ["envolver_en_bloque(sentencias 1 a 1)"], envolturas=1, ejes=DESPUES,
        ejes_antes=ANTES, acepta_envoltura=True,
    )  # fmt: skip
    linea = leer_registro(tmp_path)[0]
    assert linea["efectoDeEnvolturas"] == {
        "antes": {"diferenciasDeOperando": 3, "lineasReordenadas": 2, "lineasInsertadasOBorradas": 0},
        "despues": {"diferenciasDeOperando": 1, "lineasReordenadas": 2, "lineasInsertadasOBorradas": 0},
    }
    assert linea["ejes"] == linea["efectoDeEnvolturas"]["despues"]


def test_sin_ejes_anteriores_el_efecto_solo_lleva_los_de_despues(tmp_path: Path) -> None:
    est.anadir_registro(tmp_path, 7, 10, ["m"], envolturas=1, ejes=DESPUES, acepta_envoltura=True)
    assert list(leer_registro(tmp_path)[0]["efectoDeEnvolturas"]) == ["despues"]  # type: ignore[call-overload]


def test_una_linea_que_no_acepta_envoltura_o_no_tiene_ejes_no_lleva_el_efecto(tmp_path: Path) -> None:
    est.anadir_registro(tmp_path, 1, 10, ["m"], ejes=DESPUES, ejes_antes=ANTES)
    est.anadir_registro(
        tmp_path, 2, 9, ["m"], envolturas=1, ejes=None, ejes_antes=ANTES, acepta_envoltura=True
    )
    lineas = leer_registro(tmp_path)
    assert all("efectoDeEnvolturas" not in linea for linea in lineas)


def test_la_busqueda_registra_el_efecto_de_una_envoltura_con_los_ejes_de_partida(tmp_path: Path) -> None:
    busqueda = crear(tmp_path, ANTES)
    busqueda._registrar_mejora(variante(busqueda, envuelta=True, ejes=DESPUES), 10, 1)
    linea = leer_registro(tmp_path / "estado")[0]
    assert linea["efectoDeEnvolturas"]["antes"]["diferenciasDeOperando"] == 3  # type: ignore[index]
    assert linea["efectoDeEnvolturas"]["despues"]["diferenciasDeOperando"] == 1  # type: ignore[index]
    assert busqueda.ejes_mejor == DESPUES


def test_los_ejes_de_antes_son_los_del_ultimo_mejor_aceptado(tmp_path: Path) -> None:
    intermedio = EjesPuntuacion(operandos=2, reordenadas=5)
    busqueda = crear(tmp_path, ANTES)
    busqueda._registrar_mejora(variante(busqueda, envuelta=False, ejes=intermedio), 30, 1)
    busqueda._registrar_mejora(variante(busqueda, envuelta=True, ejes=DESPUES), 10, 1)
    sin_envoltura, con_envoltura = leer_registro(tmp_path / "estado")
    assert "efectoDeEnvolturas" not in sin_envoltura
    assert con_envoltura["efectoDeEnvolturas"]["antes"] == intermedio.como_json()  # type: ignore[index]


def test_una_segunda_mejora_con_las_mismas_envolturas_no_repite_el_efecto(tmp_path: Path) -> None:
    busqueda = crear(tmp_path, ANTES)
    busqueda._registrar_mejora(variante(busqueda, envuelta=True, ejes=DESPUES), 20, 1)
    busqueda._registrar_mejora(variante(busqueda, envuelta=True, ejes=EjesPuntuacion()), 10, 1)
    primera, segunda = leer_registro(tmp_path / "estado")
    assert "efectoDeEnvolturas" in primera and "efectoDeEnvolturas" not in segunda


def test_al_reanudar_los_ejes_anteriores_se_desconocen_y_el_efecto_solo_lleva_los_de_despues(
    tmp_path: Path,
) -> None:
    busqueda = crear(tmp_path, None)
    busqueda._registrar_mejora(variante(busqueda, envuelta=True, ejes=DESPUES), 10, 1)
    efecto = leer_registro(tmp_path / "estado")[0]["efectoDeEnvolturas"]
    assert list(efecto) == ["despues"]  # type: ignore[call-overload]


def test_una_variante_sin_ejes_deja_desconocidos_los_ejes_del_mejor(tmp_path: Path) -> None:
    busqueda = crear(tmp_path, ANTES)
    busqueda._registrar_mejora(variante(busqueda, envuelta=False, ejes=None), 30, 1)
    assert busqueda.ejes_mejor is None
