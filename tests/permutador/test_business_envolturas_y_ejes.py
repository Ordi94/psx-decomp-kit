"""Marca de envolturas, puntuacion secundaria y opciones por archivo en el estado y la busqueda."""

import json
from pathlib import Path
from typing import Any

import pytest
from psxdecomp.diff.ejes import EjesPuntuacion
from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import busqueda as pm
from psxdecomp.permutador import c
from psxdecomp.permutador import estado as est
from psxdecomp.permutador import evaluacion as ev

from construccion.test_compilacion import herramientas
from permutador.ayudantes import (
    COMPILACION,
    CONVENCIONES,
    EJECUTABLE,
    FUNCION,
    RUTAS,
    EjecutorPermutar,
    crear_repositorio,
)

from .test_business_busqueda import CABECERA, Reloj

FUNCION_CON_LLAMADA = (
    "s32 rutina_a(Objeto* o, s32 x)\n{\n    s32 y;\n    y = o->radio + x;\n    g(y);\n    return y;\n}"
)
OPCION = "-fno-schedule-insns"


def evaluador_que_premia_la_envoltura(texto: str, umbral: int) -> ev.ResultadoEvaluacion:
    if "do {" in texto:
        return ev.ResultadoEvaluacion(10, ejes=EjesPuntuacion(operandos=1))
    return ev.ResultadoEvaluacion(50, ejes=EjesPuntuacion(operandos=3, reordenadas=2))


def crear(tmp_path: Path, evaluador: pm.Evaluador, texto: str = FUNCION_CON_LLAMADA) -> pm.Busqueda:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(texto, FUNCION, frozenset({"Objeto"}))
    estado = est.Estado(FUNCION, "codigo/modulo_a.c", 5, 50, 50, 50)
    busqueda = pm.Busqueda(
        base,
        tabla,
        evaluador,
        estado=estado,
        carpeta=tmp_path / "estado",
        opciones=pm.Opciones(iteraciones=60, procesos=2),
        salida=lambda texto: None,
        reloj=Reloj(0.001),
    )
    busqueda.iniciar_barrido()
    return busqueda


# --- estado y mejor.c -------------------------------------------------------------------------------


def test_la_marca_de_envolturas_es_una_linea_fija_con_la_cantidad() -> None:
    marca = est.marca_de_envolturas(2)
    assert "\n" not in marca
    assert marca == (
        "/* El candidato contiene 2 envolturas do { } while (0) sin codigo "
        "que requieren justificacion con el volcado del compilador. */"
    )


def test_mejor_solo_lleva_la_marca_si_el_candidato_tiene_envolturas(tmp_path: Path) -> None:
    sin = est.guardar_mejor(tmp_path / "a", "s32 f(void)\n{\n}", 10, 50)
    con = est.guardar_mejor(tmp_path / "b", "s32 f(void)\n{\n}", 10, 50, envolturas=3)
    assert "envolturas" not in sin.read_text(encoding="utf-8")
    lineas = con.read_text(encoding="utf-8").splitlines()
    assert lineas[0].startswith("/* Candidato del permutador: puntuacion 10")
    assert lineas[1] == est.marca_de_envolturas(3)
    assert lineas[2] == "s32 f(void)"


def test_cargar_mejor_salta_todas_las_lineas_de_comentario_iniciales(tmp_path: Path) -> None:
    est.guardar_mejor(tmp_path / "a", "s32 f(void)\n{\n}", 10, 50)
    est.guardar_mejor(tmp_path / "b", "s32 f(void)\n{\n}", 10, 50, envolturas=1)
    assert est.cargar_mejor(tmp_path / "a") == est.cargar_mejor(tmp_path / "b") == "s32 f(void)\n{\n}"


def test_el_estado_guarda_y_recupera_las_envolturas_y_los_intentos(tmp_path: Path) -> None:
    estado = est.Estado("f", "a.c", 1, 50, 40, 30, envolturas=2, mutaciones_intentadas={"b": 3, "a": 1})
    est.guardar_estado(tmp_path, estado)
    datos = json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))
    assert datos["envolturas"] == 2
    assert list(datos["mutacionesIntentadas"]) == ["a", "b"]
    assert est.cargar_estado(tmp_path, "f") == estado


def test_un_estado_anterior_sin_los_campos_nuevos_se_carga_con_ceros(tmp_path: Path) -> None:
    estado = est.Estado("f", "a.c", 1, 50, 40, 30)
    est.guardar_estado(tmp_path, estado)
    datos = json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))
    del datos["envolturas"], datos["mutacionesIntentadas"]
    (tmp_path / "estado.json").write_text(json.dumps(datos), encoding="utf-8")
    cargado = est.cargar_estado(tmp_path, "f")
    assert cargado.envolturas == 0 and cargado.mutaciones_intentadas == {}


@pytest.mark.parametrize(
    ("clave", "valor"),
    [
        ("mutacionesIntentadas", []),
        ("mutacionesIntentadas", {"a": -1}),
        ("mutacionesIntentadas", {"a": True}),
        ("mutacionesIntentadas", {"a": "3"}),
        ("envolturas", -1),
        ("envolturas", "1"),
    ],
)
def test_un_estado_con_los_campos_nuevos_invalidos_se_rechaza(tmp_path: Path, clave: str, valor: Any) -> None:
    est.guardar_estado(tmp_path, est.Estado("f", "a.c", 1, 50, 40, 30))
    datos = json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))
    datos[clave] = valor
    (tmp_path / "estado.json").write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ValueError, match=r"estado\.json"):
        est.cargar_estado(tmp_path, "f")


def test_cada_linea_del_registro_declara_las_envolturas_y_los_ejes(tmp_path: Path) -> None:
    est.anadir_registro(
        tmp_path, 3, 20, ["envolver_en_bloque(sentencias 0 a 1)"], envolturas=1, ejes=EjesPuntuacion(1, 2, 3)
    )
    est.anadir_registro(tmp_path, 4, 10, ["orden_sentencias(posiciones 1 y 2)"])
    lineas = [json.loads(x) for x in (tmp_path / "registro.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lineas[0]["envolturas"] == 1
    assert lineas[0]["ejes"] == {
        "diferenciasDeOperando": 1,
        "lineasReordenadas": 2,
        "lineasInsertadasOBorradas": 3,
    }
    assert lineas[1]["envolturas"] == 0 and "ejes" not in lineas[1]


# --- busqueda ---------------------------------------------------------------------------------------


def test_una_variante_con_envoltura_aceptada_marca_el_estado_el_registro_y_mejor(tmp_path: Path) -> None:
    busqueda = crear(tmp_path, evaluador_que_premia_la_envoltura)
    resumen = busqueda.ejecutar()
    assert resumen.puntuacion_mejor == 10 and resumen.envolturas == 1
    assert busqueda.estado.envolturas == 1
    carpeta = tmp_path / "estado"
    estado = json.loads((carpeta / "estado.json").read_text(encoding="utf-8"))
    assert estado["envolturas"] == 1 and "envolver_en_bloque" in estado["mutacionesIntentadas"]
    registro = [json.loads(x) for x in (carpeta / "registro.jsonl").read_text(encoding="utf-8").splitlines()]
    assert registro and registro[-1]["envolturas"] == 1
    assert registro[-1]["ejes"]["diferenciasDeOperando"] == 1
    mejor = (carpeta / "mejor.c").read_text(encoding="utf-8").splitlines()
    assert mejor[1] == est.marca_de_envolturas(1)
    assert "do {" in "\n".join(mejor)


def test_el_resumen_avisa_de_las_envolturas_del_candidato(tmp_path: Path) -> None:
    resumen = pm.Resumen(FUNCION, 1, 2, 10, 50, 10, tmp_path / "mejor.c", 6.0, envolturas=2)
    texto = pm.formatear_resumen(resumen, tmp_path)
    assert "aviso: el candidato contiene 2 envolturas" in texto
    sin = pm.formatear_resumen(pm.Resumen(FUNCION, 1, 2, 10, 50, 10, tmp_path / "mejor.c", 6.0), tmp_path)
    assert "envolturas" not in sin


def test_las_envolturas_ya_presentes_en_el_c_de_partida_no_se_cuentan_como_nuevas(tmp_path: Path) -> None:
    texto = "s32 rutina_a(Objeto* o, s32 x)\n{\n    do {\n        g(x);\n    } while (0);\n    return x;\n}"
    busqueda = crear(tmp_path, lambda t, u: ev.ResultadoEvaluacion(10), texto)
    assert busqueda.envolturas_base == 1
    assert busqueda._envolturas_nuevas(busqueda.base) == 0


def test_la_busqueda_cuenta_las_variantes_generadas_por_mutacion(tmp_path: Path) -> None:
    busqueda = crear(tmp_path, lambda t, u: ev.ResultadoEvaluacion(50))
    busqueda.ejecutar()
    intentadas = busqueda.estado.mutaciones_intentadas
    assert intentadas and all(isinstance(n, int) and n > 0 for n in intentadas.values())
    assert "envolver_en_bloque" in intentadas


def test_la_reanudacion_lee_un_mejor_con_la_marca_de_envolturas(tmp_path: Path) -> None:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(FUNCION_CON_LLAMADA, FUNCION, frozenset({"Objeto"}))
    envuelta = FUNCION_CON_LLAMADA.replace("    g(y);", "    do {\n        g(y);\n    } while (0);")
    carpeta = tmp_path / "estado"
    est.guardar_estado(carpeta, est.Estado(FUNCION, "codigo/modulo_a.c", 5, 50, 10, 10, envolturas=1))
    est.guardar_actual(carpeta, envuelta)
    est.guardar_mejor(carpeta, envuelta, 10, 50, envolturas=1)
    busqueda = pm._reanudar(
        carpeta,
        FUNCION,
        base,
        tabla=tabla,
        evaluador=lambda t, u: ev.ResultadoEvaluacion(50),
        opciones=pm.Opciones(iteraciones=1),
        salida=lambda texto: None,
        reloj=Reloj(0.001),
    )
    assert c.imprimir_funcion(busqueda.arbol_mejor) == envuelta
    assert busqueda.estado.envolturas == 1


# --- opciones por archivo en la medicion de variantes ------------------------------------------------


def preparar(raiz: Path, ejecutor: EjecutorPermutar) -> ev.ObjetivoMedicion:
    return ev.preparar_medicion(
        raiz,
        FUNCION,
        herramientas(),
        Path("diff.py"),
        ejecutor,
        carpeta="salida/diff/objetivo",
        rutas=RUTAS,
        convenciones=CONVENCIONES,
        compilacion=COMPILACION,
        nombre_ejecutable=EJECUTABLE,
    )


def comando_de_cc1(ejecutor: EjecutorPermutar) -> list[str]:
    (comando,) = [c for c in ejecutor.comandos if Path(c[0]).name == "CC1PSX.EXE"]
    return comando


def test_la_medicion_compila_la_variante_con_las_opciones_del_archivo(tmp_path: Path) -> None:
    crear_repositorio(tmp_path / "r", valor_g=8)
    (tmp_path / "r" / "datos" / "opciones.toml").write_text(
        f'[archivos.modulo_a]\ng = 8\nopciones = ["{OPCION}"]\n', encoding="utf-8"
    )
    ejecutor = EjecutorPermutar()
    objetivo = preparar(tmp_path / "r", ejecutor)
    assert objetivo.opciones_extra == (OPCION,)
    ejecutor.comandos.clear()
    ev.evaluar(objetivo, objetivo.texto_archivo[objetivo.inicio : objetivo.fin], comprobar_bytes_bajo=0)
    comando = comando_de_cc1(ejecutor)
    assert comando[1:5] == ["-quiet", "-O2", OPCION, "-G8"]


def test_la_medicion_sin_la_clave_no_cambia_el_comando(tmp_path: Path) -> None:
    crear_repositorio(tmp_path / "r", valor_g=8)
    ejecutor = EjecutorPermutar()
    objetivo = preparar(tmp_path / "r", ejecutor)
    assert objetivo.opciones_extra == ()
    ejecutor.comandos.clear()
    ev.evaluar(objetivo, objetivo.texto_archivo[objetivo.inicio : objetivo.fin], comprobar_bytes_bajo=0)
    assert comando_de_cc1(ejecutor)[1:4] == ["-quiet", "-O2", "-G8"]
