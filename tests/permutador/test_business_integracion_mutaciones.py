"""Integracion: las mutaciones de 0.3.0 y 0.3.1 estan registradas con su peso y el buscador las intenta."""

from pathlib import Path

import pytest
from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import busqueda as pm
from psxdecomp.permutador import c
from psxdecomp.permutador import estado as est
from psxdecomp.permutador import evaluacion as ev
from psxdecomp.permutador import mutaciones as mut

from .ayudantes_mutaciones import CABECERA, TIPOS, cuerpo
from .test_business_busqueda import Reloj

PESOS_REGISTRADOS = {
    "mover_sentencia_a_distancia": 2.0,
    "envolver_en_bloque": 1.0,
    "dividir_local_multiset": 1.5,
    "expandir_local": 1.5,
    "cadena_de_asignacion": 1.5,
    "dividir_asignacion": 1.5,
    "ajustar_desigualdad": 1.5,
    "forma_de_acceso_a_struct": 1.5,
    "cast_en_subexpresion": 1.5,
    "ancho_de_variable_de_retorno": 1.0,
    "limite_en_local_antes_del_incremento": 1.0,
    "copia_local_por_rama": 1.0,
    "acceso_por_desplazamiento": 1.5,
    "almacen_directo_en_cada_rama": 1.5,
    "leer_bajo_la_guarda": 1.5,
}
NUEVAS_DE_LA_VERSION = ("acceso_por_desplazamiento", "almacen_directo_en_cada_rama", "leer_bajo_la_guarda")

# Un fragmento minimo donde cada mutacion tiene al menos un sitio aplicable.
SITIOS: dict[str, str] = {
    "mover_sentencia_a_distancia": cuerpo("D_global = 1;", "D_otra = 2;", "p->valor = 3;"),
    "envolver_en_bloque": cuerpo("g(a);", "D_global = 1;"),
    "dividir_local_multiset": cuerpo("s32 u;", "u = f(a);", "u = g(b);", "h(u);"),
    "expandir_local": cuerpo("s32 x;", "x = a + b;", "D_global = 1;", "D_otra = x;"),
    "cadena_de_asignacion": cuerpo("s32 x;", "s32 y;", "x = a + b;", "y = a + b;", "D_global = x + y;"),
    "dividir_asignacion": cuerpo("s32 r;", "r = a + b;", "r += 3;", "D_global = r;"),
    "ajustar_desigualdad": cuerpo("if (a < 5) {", "    D_global = 1;", "}"),
    "forma_de_acceso_a_struct": cuerpo("a = tabla[1].valor;"),
    "cast_en_subexpresion": cuerpo("p->corto = a + b;"),
    "ancho_de_variable_de_retorno": cuerpo("s32 t;", "t = g(a);", "p->corto = t;"),
    "limite_en_local_antes_del_incremento": cuerpo(
        "do {", "    D_global = a;", "    a += 2;", "} while (a < D_otra);"
    ),
    "copia_local_por_rama": cuerpo(
        "p = q;", "D_otra = 1;", "if (a) {", "    p->valor = 2;", "}", "p->corto = 4;"
    ),
    "acceso_por_desplazamiento": cuerpo("a = p->clave;"),
    "almacen_directo_en_cada_rama": cuerpo(
        "s32 v;", "if (a) {", "    v = b + 1;", "} else {", "    v = b - 1;", "}", "p->valor = v;"
    ),
    "leer_bajo_la_guarda": cuerpo("s32 u;", "u = p->valor + b;", "if (a) {", "    q->clave = u;", "}"),
}
FUNCION_CON_LOS_TRES_SITIOS = cuerpo(
    "s32 v;",
    "s32 u;",
    "u = p->clave + b;",
    "if (a) {",
    "    q->clave = u;",
    "}",
    "if (b) {",
    "    v = a + 1;",
    "} else {",
    "    v = a - 1;",
    "}",
    "p->valor = v;",
)


def test_las_mutaciones_de_las_dos_versiones_estan_registradas_con_su_peso() -> None:
    registradas = {nombre: peso for nombre, _, peso in mut.MUTACIONES}
    assert {nombre: registradas[nombre] for nombre in PESOS_REGISTRADOS} == PESOS_REGISTRADOS
    assert len(registradas) == len(mut.MUTACIONES)


def test_cada_mutacion_registrada_es_la_funcion_del_mismo_nombre() -> None:
    funciones = {nombre: funcion for nombre, funcion, _ in mut.MUTACIONES}
    for nombre in NUEVAS_DE_LA_VERSION:
        assert funciones[nombre] is getattr(mut, nombre)


def test_el_fragmento_de_cada_mutacion_cubre_todas_las_registradas_de_las_dos_versiones() -> None:
    assert set(SITIOS) == set(PESOS_REGISTRADOS)


@pytest.mark.parametrize("nombre", sorted(SITIOS))
def test_el_barrido_de_vecinos_intenta_la_mutacion(nombre: str) -> None:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(SITIOS[nombre], "f", TIPOS)
    descripciones = [descripcion for _, descripcion in mut.vecinos(base, tabla)]
    assert any(descripcion.startswith(f"{nombre}(") for descripcion in descripciones)


def test_el_nombre_de_cada_descripcion_coincide_con_el_de_la_mutacion_registrada() -> None:
    tabla = an.construir_tabla([CABECERA])
    registrados = {nombre for nombre, _, _ in mut.MUTACIONES}
    for texto in SITIOS.values():
        base = c.analizar_funcion(texto, "f", TIPOS)
        for _, descripcion in mut.vecinos(base, tabla):
            assert descripcion.split("(", 1)[0] in registrados


def test_toda_variante_de_las_mutaciones_nuevas_se_imprime_y_se_lee_igual() -> None:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(FUNCION_CON_LOS_TRES_SITIOS, "f", TIPOS)
    vistas = set()
    for variante, descripcion in mut.vecinos(base, tabla):
        nombre = descripcion.split("(", 1)[0]
        if nombre not in NUEVAS_DE_LA_VERSION:
            continue
        vistas.add(nombre)
        texto = c.imprimir_funcion(variante)
        assert c.imprimir_funcion(c.analizar_funcion(texto, "f", TIPOS)) == texto
    assert vistas == set(NUEVAS_DE_LA_VERSION)


def test_la_busqueda_cuenta_como_intentadas_las_tres_mutaciones_nuevas(tmp_path: Path) -> None:
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(FUNCION_CON_LOS_TRES_SITIOS, "f", TIPOS)
    estado = est.Estado("f", "codigo/modulo_a.c", 5, 50, 50, 50)
    busqueda = pm.Busqueda(
        base,
        tabla,
        lambda texto, umbral: ev.ResultadoEvaluacion(50),
        estado=estado,
        carpeta=tmp_path / "estado",
        opciones=pm.Opciones(iteraciones=3000, procesos=2),
        salida=lambda texto: None,
        reloj=Reloj(0.001),
    )
    busqueda.iniciar_barrido()
    busqueda.ejecutar()
    intentadas = busqueda.estado.mutaciones_intentadas
    assert all(intentadas.get(nombre, 0) > 0 for nombre in NUEVAS_DE_LA_VERSION)
