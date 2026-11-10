"""Reglas de negocio: acceso por desplazamiento, almacen directo en cada rama y lectura bajo la guarda."""

import random

import pytest
from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import c
from psxdecomp.permutador import mutaciones as mut

from .ayudantes_mutaciones import CABECERA, TIPOS, aplicar, azar, cuerpo, sin_cambio

FIRMA_CON_ELEMENTOS = "void f(Nodo* p, Nodo** pp, s16* h, u8* k, Nodo* q, s32 a, s32 b)"
CABECERA_PROPIA = """
typedef unsigned char u8;
typedef struct Mezcla {
    s32 inicio;
    u8 bandera : 3;
    s32 despues;
} Mezcla;
typedef struct Anidada {
    s32 antes;
    struct { s32 x; s32 y; } interior;
    s32 despues;
} Anidada;
typedef struct Rara {
    s32 a;
    Desconocido d;
    s32 siguiente;
} Rara;
typedef struct Alineada {
    u8 uno;
    s32 cuatro;
    s16 ocho[3];
    u8 doce;
    u16 catorce;
    s32 *pa, pb;
} Alineada;
extern Alineada tabla_global[4];
"""


def aplicar_con_cabecera(
    mutacion: mut.Mutacion, texto: str, cabecera: str, semilla: int = 0
) -> tuple[str | None, str]:
    """Aplica una mutacion con una cabecera propia y comprueba la ida y vuelta del resultado."""
    tabla = an.construir_tabla([cabecera])
    tipos = frozenset(tabla.nombres_de_tipo | TIPOS)
    funcion = c.analizar_funcion(texto, "f", tipos)
    contexto = mut.Contexto(funcion, an.Entorno(tabla, funcion), azar(semilla), mut._nombres_de(funcion))
    descripcion = mutacion(contexto)
    resultado = c.imprimir_funcion(funcion)
    assert c.imprimir_funcion(c.analizar_funcion(resultado, "f", tipos)) == resultado
    return descripcion, resultado


# --- disposicion de las estructuras ---------------------------------------------------------------------


def test_la_disposicion_usa_alineacion_natural_y_el_tamano_de_cada_campo() -> None:
    tabla = an.construir_tabla([CABECERA_PROPIA])
    assert tabla.disposicion["Alineada"] == {
        "uno": 0,
        "cuatro": 4,
        "ocho": 8,
        "doce": 14,
        "catorce": 16,
        "pa": 20,
        "pb": 24,
    }


def test_la_disposicion_de_la_cabecera_comun_cubre_enteros_y_punteros() -> None:
    tabla = an.construir_tabla([CABECERA])
    assert tabla.disposicion["Nodo"] == {
        "valor": 0,
        "corto": 4,
        "ancho": 6,
        "clave": 8,
        "byte": 12,
        "sig": 16,
    }
    assert tabla.disposicion["Mundo"] == {"escala": 0, "cabeza": 4}


def test_la_disposicion_se_detiene_en_un_campo_de_bits() -> None:
    tabla = an.construir_tabla([CABECERA_PROPIA])
    assert tabla.disposicion["Mezcla"] == {"inicio": 0}


def test_la_disposicion_se_detiene_en_una_estructura_anidada() -> None:
    tabla = an.construir_tabla([CABECERA_PROPIA])
    assert tabla.disposicion["Anidada"] == {"antes": 0}


def test_la_disposicion_se_detiene_en_un_tipo_de_tamano_desconocido() -> None:
    tabla = an.construir_tabla([CABECERA_PROPIA])
    assert tabla.disposicion["Rara"] == {"a": 0}


@pytest.mark.parametrize(
    "cuerpo_de_estructura",
    [
        "s32 a; s32 vec[N]; s32 b;",
        "s32 a; s32 vec[2 * 3]; s32 b;",
        "s32 a; void (*cb)(s32); s32 b;",
        "s32 a; s64 grande; s32 b;",
    ],
)
def test_la_disposicion_no_adivina_dimensiones_simbolicas_ni_punteros_a_funcion(
    cuerpo_de_estructura: str,
) -> None:
    tabla = an.construir_tabla([f"typedef struct Dato {{ {cuerpo_de_estructura} }} Dato;"])
    assert tabla.disposicion["Dato"].get("b") is None
    assert tabla.disposicion["Dato"]["a"] == 0


def test_una_union_no_tiene_disposicion_de_estructura() -> None:
    tabla = an.construir_tabla(["typedef union Mezcla { s32 a; s16 b; } Mezcla;"])
    assert tabla.disposicion["Mezcla"] == {}


def test_dos_definiciones_distintas_de_una_estructura_anulan_su_disposicion() -> None:
    tabla = an.construir_tabla(["struct Dato { s32 a; s32 b; };", "struct Dato { s32 a; s32 b; s32 c; };"])
    assert "Dato" not in tabla.disposicion


def test_dos_definiciones_iguales_de_una_estructura_conservan_su_disposicion() -> None:
    tabla = an.construir_tabla(["struct Dato { s32 a; s32 b; };", "struct Dato { s32 a; s32 b; };"])
    assert tabla.disposicion["Dato"] == {"a": 0, "b": 4}


@pytest.mark.parametrize(
    ("base", "estrellas", "esperado"),
    [("s8", 0, 1), ("u16", 0, 2), ("s32", 0, 4), ("Nodo", 1, 4), ("s64", 0, None), ("Nodo", 0, None)],
)
def test_el_tamano_de_un_tipo_solo_se_afirma_para_enteros_y_punteros(
    base: str, estrellas: int, esperado: int | None
) -> None:
    assert an.tamano_de_tipo(base, estrellas) == esperado


# --- acceso_por_desplazamiento -------------------------------------------------------------------------


def test_una_lectura_por_flecha_pasa_a_desplazamiento_de_bytes() -> None:
    descripcion, resultado = aplicar(mut.acceso_por_desplazamiento, cuerpo("a = p->clave;"))
    assert descripcion == "acceso_por_desplazamiento(p->clave en +8)"
    assert resultado == cuerpo("a = *(s32*)((unsigned char*)p + 8);")


def test_un_almacen_a_un_miembro_pasa_a_desplazamiento_de_bytes() -> None:
    _, resultado = aplicar(mut.acceso_por_desplazamiento, cuerpo("p->corto = 3;"))
    assert resultado == cuerpo("*(s16*)((unsigned char*)p + 4) = 3;")


def test_el_acceso_con_punto_sobre_un_puntero_desreferenciado_tambien_se_reescribe() -> None:
    _, resultado = aplicar(mut.acceso_por_desplazamiento, cuerpo("a = (*p).ancho;"))
    assert resultado == cuerpo("a = *(u16*)((unsigned char*)p + 6);")


def test_un_miembro_puntero_lleva_un_nivel_de_puntero_mas_en_el_molde() -> None:
    _, resultado = aplicar(mut.acceso_por_desplazamiento, cuerpo("q = p->sig;"))
    assert resultado == cuerpo("q = *(struct Nodo**)((unsigned char*)p + 16);")


def test_una_asignacion_compuesta_y_un_incremento_conservan_el_acceso_reescrito() -> None:
    _, compuesta = aplicar(mut.acceso_por_desplazamiento, cuerpo("p->valor += b;"))
    assert compuesta == cuerpo("*(s32*)((unsigned char*)p + 0) += b;")
    _, incremento = aplicar(mut.acceso_por_desplazamiento, cuerpo("p->clave++;"))
    assert incremento == cuerpo("(*(s32*)((unsigned char*)p + 8))++;")


def test_el_elemento_constante_de_un_puntero_usa_el_tamano_del_elemento() -> None:
    _, de_corto = aplicar(mut.acceso_por_desplazamiento, cuerpo("a = h[3];", firma=FIRMA_CON_ELEMENTOS))
    assert de_corto == cuerpo("a = *(s16*)((unsigned char*)h + 6);", firma=FIRMA_CON_ELEMENTOS)
    _, de_byte = aplicar(mut.acceso_por_desplazamiento, cuerpo("a = k[5];", firma=FIRMA_CON_ELEMENTOS))
    assert de_byte == cuerpo("a = *(u8*)((unsigned char*)k + 5);", firma=FIRMA_CON_ELEMENTOS)
    _, de_puntero = aplicar(mut.acceso_por_desplazamiento, cuerpo("q = pp[2];", firma=FIRMA_CON_ELEMENTOS))
    assert de_puntero == cuerpo("q = *(Nodo**)((unsigned char*)pp + 8);", firma=FIRMA_CON_ELEMENTOS)


def test_el_byte_se_escribe_con_el_nombre_que_definen_las_cabeceras() -> None:
    _, con_u8 = aplicar_con_cabecera(
        mut.acceso_por_desplazamiento,
        cuerpo("a = p->cuatro;", firma="void f(Alineada* p, s32 a)"),
        CABECERA_PROPIA,
    )
    assert con_u8 == cuerpo("a = *(s32*)((u8*)p + 4);", firma="void f(Alineada* p, s32 a)")
    _, sin_u8 = aplicar(mut.acceso_por_desplazamiento, cuerpo("a = p->valor;"))
    assert "(unsigned char*)" in sin_u8 and "(u8*)" not in sin_u8


def test_el_desplazamiento_respeta_el_relleno_de_alineacion() -> None:
    _, resultado = aplicar_con_cabecera(
        mut.acceso_por_desplazamiento,
        cuerpo("a = p->catorce;", firma="void f(Alineada* p, s32 a)"),
        CABECERA_PROPIA,
    )
    assert "+ 16)" in resultado


def test_la_mutacion_enumera_cada_acceso_y_el_resultado_lee_de_nuevo() -> None:
    texto = cuerpo("a = p->valor;", "b = p->clave;")
    resultados = set()
    for indice in range(2):
        enumerador = mut._Enumerador(indice, (0.0, 0.0))
        contexto = preparar_con(enumerador, texto)
        assert mut.acceso_por_desplazamiento(contexto) is not None
        resultados.add(c.imprimir_funcion(contexto.funcion))
    assert len(resultados) == 2


def preparar_con(generador: random.Random, texto: str) -> mut.Contexto:
    tabla = an.construir_tabla([CABECERA])
    funcion = c.analizar_funcion(texto, "f", TIPOS)
    return mut.Contexto(funcion, an.Entorno(tabla, funcion), generador, mut._nombres_de(funcion))


@pytest.mark.parametrize(
    "linea",
    [
        "a = d->x;",
        "a = tabla[1].valor;",
        "a = D_global;",
        "q = &p->valor;",
        "a = ((Nodo*)0x80100000)->valor;",
        "a = ((Nodo*)&D_global)->valor;",
        "a = h[b];",
        "a = h[-1];",
        "a = q[1].valor;",
    ],
)
def test_no_se_reescribe_un_acceso_sin_posicion_conocida_o_sin_puntero(linea: str) -> None:
    firma = "void f(Nodo* p, Nodo* q, Desconocido* d, s16* h, s32 a, s32 b)"
    sin_cambio(mut.acceso_por_desplazamiento, cuerpo(linea, firma=firma))


def test_no_se_reescribe_un_campo_que_sigue_a_un_campo_de_bits_ni_a_una_estructura_anidada() -> None:
    for campo, estructura in (("despues", "Mezcla"), ("despues", "Anidada"), ("siguiente", "Rara")):
        texto = cuerpo(f"a = p->{campo};", firma=f"void f({estructura}* p, s32 a)")
        descripcion, _ = aplicar_con_cabecera(mut.acceso_por_desplazamiento, texto, CABECERA_PROPIA)
        assert descripcion is None


def test_no_se_reescribe_el_miembro_de_un_arreglo_ni_de_un_objeto_global() -> None:
    texto = cuerpo("a = tabla_global[1].cuatro;", firma="void f(s32 a)")
    descripcion, _ = aplicar_con_cabecera(mut.acceso_por_desplazamiento, texto, CABECERA_PROPIA)
    assert descripcion is None
    arreglo = cuerpo("a = p->ocho;", firma="void f(Alineada* p, s32 a)")
    descripcion, _ = aplicar_con_cabecera(mut.acceso_por_desplazamiento, arreglo, CABECERA_PROPIA)
    assert descripcion is None


def test_no_se_reescribe_un_puntero_de_dos_niveles_ni_un_elemento_de_estructura() -> None:
    descripcion, _ = aplicar(
        mut.acceso_por_desplazamiento, cuerpo("a = pp->valor;", firma=FIRMA_CON_ELEMENTOS)
    )
    assert descripcion is None
    descripcion, _ = aplicar(mut.acceso_por_desplazamiento, cuerpo("q = &p[1];", firma=FIRMA_CON_ELEMENTOS))
    assert descripcion is None


def test_una_funcion_sin_accesos_no_se_reescribe() -> None:
    sin_cambio(mut.acceso_por_desplazamiento, cuerpo("a = b + 1;"))


# --- almacen_directo_en_cada_rama ----------------------------------------------------------------------


UNION_DE_RAMAS = (
    "s32 v;",
    "if (a) {",
    "    v = b + 1;",
    "} else {",
    "    v = b - 1;",
    "}",
    "p->valor = v;",
)
RAMAS_DIRECTAS = (
    "if (a) {",
    "    p->valor = b + 1;",
    "} else {",
    "    p->valor = b - 1;",
    "}",
)


def test_el_almacen_se_escribe_en_cada_rama_y_la_variable_desaparece() -> None:
    descripcion, resultado = aplicar(mut.almacen_directo_en_cada_rama, cuerpo(*UNION_DE_RAMAS))
    assert descripcion == "almacen_directo_en_cada_rama(v en p->valor)"
    assert resultado == cuerpo(*RAMAS_DIRECTAS)


def test_la_inversa_introduce_la_variable_que_une_las_ramas() -> None:
    descripcion, resultado = aplicar(mut.almacen_directo_en_cada_rama, cuerpo(*RAMAS_DIRECTAS))
    assert descripcion == "almacen_directo_en_cada_rama(tmp1 desde p->valor)"
    assert resultado == cuerpo(
        "s32 tmp1;",
        "if (a) {",
        "    tmp1 = b + 1;",
        "} else {",
        "    tmp1 = b - 1;",
        "}",
        "p->valor = tmp1;",
    )


def test_la_forma_directa_y_la_inversa_se_deshacen_entre_si() -> None:
    _, con_variable = aplicar(mut.almacen_directo_en_cada_rama, cuerpo(*RAMAS_DIRECTAS))
    _, de_vuelta = aplicar(mut.almacen_directo_en_cada_rama, con_variable)
    assert de_vuelta == cuerpo(*RAMAS_DIRECTAS)


def test_el_almacen_directo_conserva_lo_que_las_ramas_hacen_antes_de_asignar() -> None:
    texto = cuerpo(
        "s32 v;",
        "if (a) {",
        "    b = b + 1;",
        "    v = b;",
        "} else {",
        "    v = 0;",
        "}",
        "p->clave = v;",
    )
    _, resultado = aplicar(mut.almacen_directo_en_cada_rama, texto)
    assert resultado == cuerpo(
        "if (a) {", "    b = b + 1;", "    p->clave = b;", "} else {", "    p->clave = 0;", "}"
    )


def variante_con(*cambios: tuple[str, str]) -> str:
    """El cuerpo de la union de ramas con unas lineas sustituidas."""
    lineas = list(UNION_DE_RAMAS)
    for viejo, nuevo in cambios:
        lineas[lineas.index(viejo)] = nuevo
    return cuerpo(*lineas)


@pytest.mark.parametrize(
    "texto",
    [
        variante_con(("s32 v;", "s16 v;")),
        variante_con(("s32 v;", "s32 v = 0;")),
        variante_con(("    v = b + 1;", "    v = p->valor + 1;")),
        variante_con(("    v = b - 1;", "    v = g(b);")),
        variante_con(("p->valor = v;", "p->valor = v + 1;")),
        variante_con(("p->valor = v;", "p->valor += v;")),
        variante_con(("p->valor = v;", "a = v;")),
        variante_con(("p->valor = v;", "p[b++].valor = v;")),
        variante_con(("    v = b + 1;", "    v = b + 1; b = 0;")),
    ],
)
def test_no_se_elimina_la_variable_si_la_forma_no_es_segura(texto: str) -> None:
    sin_cambio(mut.almacen_directo_en_cada_rama, texto)


def test_no_se_elimina_la_variable_con_mas_usos_que_el_almacen() -> None:
    texto = cuerpo(*UNION_DE_RAMAS, "b = v;")
    descripcion, _ = aplicar(mut.almacen_directo_en_cada_rama, texto)
    assert descripcion is None


def test_no_se_elimina_la_variable_si_el_almacen_no_sigue_al_if() -> None:
    lineas = [*UNION_DE_RAMAS]
    lineas.insert(6, "a = a + 1;")
    descripcion, _ = aplicar(mut.almacen_directo_en_cada_rama, cuerpo(*lineas))
    assert descripcion is None


def test_no_se_elimina_la_variable_sin_rama_else_ni_con_etiquetas() -> None:
    sin_else = cuerpo("s32 v;", "if (a) {", "    v = b;", "}", "p->valor = v;")
    sin_cambio(mut.almacen_directo_en_cada_rama, sin_else)
    con_etiqueta = variante_con(("    v = b + 1;", "    v = b + 1;\n    otra:"))
    descripcion, _ = aplicar(mut.almacen_directo_en_cada_rama, con_etiqueta)
    assert descripcion is None


def test_no_se_introduce_la_variable_si_los_destinos_difieren_o_no_hay_else() -> None:
    distintos = cuerpo("if (a) {", "    p->valor = b;", "} else {", "    p->clave = b;", "}")
    sin_cambio(mut.almacen_directo_en_cada_rama, distintos)
    sin_else = cuerpo("if (a) {", "    p->valor = b;", "}")
    sin_cambio(mut.almacen_directo_en_cada_rama, sin_else)


FIRMA_DESCONOCIDA = "void f(Nodo* p, Desconocido* d, s32 a, s32 b)"


@pytest.mark.parametrize("destino", ["D_global", "d->x", "p[b++].valor"])
def test_no_se_introduce_la_variable_para_un_destino_sin_memoria_conocida_o_con_efectos(destino: str) -> None:
    texto = cuerpo(
        "if (a) {", f"    {destino} = b;", "} else {", f"    {destino} = 0;", "}", firma=FIRMA_DESCONOCIDA
    )
    sin_cambio(mut.almacen_directo_en_cada_rama, texto)


def test_no_se_introduce_la_variable_con_un_valor_con_efectos() -> None:
    texto = cuerpo("if (a) {", "    p->valor = g(b);", "} else {", "    p->valor = 0;", "}")
    sin_cambio(mut.almacen_directo_en_cada_rama, texto)


def test_una_variable_del_mismo_tipo_que_el_miembro_se_elimina_aunque_no_tenga_signo() -> None:
    texto = cuerpo(
        "u16 v;",
        "if (a) {",
        "    v = b;",
        "} else {",
        "    v = 1;",
        "}",
        "p->ancho = v;",
    )
    descripcion, _ = aplicar(mut.almacen_directo_en_cada_rama, texto)
    assert descripcion == "almacen_directo_en_cada_rama(v en p->ancho)"


# --- leer_bajo_la_guarda -------------------------------------------------------------------------------


def test_la_asignacion_pasa_al_cuerpo_del_if_que_usa_la_local() -> None:
    texto = cuerpo("s32 u;", "u = p->valor + b;", "if (a) {", "    q->clave = u;", "}")
    descripcion, resultado = aplicar(mut.leer_bajo_la_guarda, texto)
    assert descripcion == "leer_bajo_la_guarda(u en el cuerpo)"
    assert resultado == cuerpo("s32 u;", "if (a) {", "    u = p->valor + b;", "    q->clave = u;", "}")


def test_con_el_uso_en_la_condicion_la_asignacion_queda_bajo_la_guarda_y_se_conserva_el_cortocircuito() -> (
    None
):
    texto = cuerpo("s32 u;", "u = p->valor;", "if (q && u > b) {", "    a = 1;", "}")
    descripcion, resultado = aplicar(mut.leer_bajo_la_guarda, texto)
    assert descripcion == "leer_bajo_la_guarda(u tras la guarda)"
    assert resultado == cuerpo(
        "s32 u;", "if (q) {", "    u = p->valor;", "}", "if (q && u > b) {", "    a = 1;", "}"
    )


def test_la_local_queda_sin_inicializar_en_los_caminos_donde_no_se_lee() -> None:
    texto = cuerpo("s32 u;", "u = b + 1;", "if (a) {", "    p->valor = u;", "}", "p->clave = 0;")
    _, resultado = aplicar(mut.leer_bajo_la_guarda, texto)
    asignaciones = [linea for linea in resultado.splitlines() if "u = b + 1" in linea]
    assert asignaciones == ["        u = b + 1;"]


def test_la_asignacion_se_mueve_tras_las_declaraciones_del_cuerpo() -> None:
    texto = cuerpo("s32 u;", "u = b + 1;", "if (a) {", "    s32 t;", "    t = u;", "    p->valor = t;", "}")
    _, resultado = aplicar(mut.leer_bajo_la_guarda, texto)
    assert resultado == cuerpo(
        "s32 u;", "if (a) {", "    s32 t;", "    u = b + 1;", "    t = u;", "    p->valor = t;", "}"
    )


def test_una_condicion_con_llamada_admite_un_valor_que_solo_lee_locales() -> None:
    texto = cuerpo("s32 u;", "u = b + 1;", "if (g(a)) {", "    p->valor = u;", "}")
    descripcion, _ = aplicar(mut.leer_bajo_la_guarda, texto)
    assert descripcion == "leer_bajo_la_guarda(u en el cuerpo)"


@pytest.mark.parametrize(
    "texto",
    [
        cuerpo("s32 u;", "u = p->valor;", "if (g(a)) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = b;", "if (b++ > 0) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = b;", "if (g(b++)) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = g(b);", "if (a) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = b;", "if (a) {", "    q->clave = u;", "} else {", "    q->clave = u + 1;", "}"),
        cuerpo("s32 u;", "u = b;", "if (a) {", "    q->clave = 1;", "}"),
        cuerpo("s32 u;", "u = b;", "if (a) {", "    q->clave = u;", "}", "p->clave = u;"),
        cuerpo("s32 u;", "u = b;", "a = 1;", "if (a) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = b;", "if (u > 3) {", "    q->clave = 1;", "}"),
        cuerpo("s32 u;", "u = b;", "if (u && q) {", "    q->clave = 1;", "}"),
        cuerpo("s32 u;", "u = b;", "if (g(a) && u) {", "    q->clave = 1;", "}"),
        cuerpo("s32 u;", "u = b;", "if (a) {", "etiqueta:", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = b;", "if (a) {", "    s32 t = a;", "    q->clave = u;", "}"),
        cuerpo("s32 u = 1;", "u = b;", "if (a) {", "    q->clave = u;", "}"),
        cuerpo("s32 u;", "u = u + b;", "if (a) {", "    q->clave = u;", "}"),
        cuerpo("a = b;", "if (b) {", "    q->clave = a;", "}"),
    ],
)
def test_no_se_mueve_la_asignacion_si_la_forma_no_es_segura(texto: str) -> None:
    sin_cambio(mut.leer_bajo_la_guarda, texto)


def test_la_condicion_dentro_de_un_bucle_tambien_admite_la_forma() -> None:
    texto = cuerpo(
        "s32 u;",
        "while (b) {",
        "    u = p->valor;",
        "    if (a) {",
        "        q->clave = u;",
        "    }",
        "    b--;",
        "}",
    )
    descripcion, _ = aplicar(mut.leer_bajo_la_guarda, texto)
    assert descripcion == "leer_bajo_la_guarda(u en el cuerpo)"


def test_una_rama_vacia_no_impide_las_demas_formas_ni_se_toma_por_asignacion() -> None:
    vacia = cuerpo("s32 v;", "if (a) {", "} else {", "    v = b;", "}", "p->valor = v;")
    sin_cambio(mut.almacen_directo_en_cada_rama, vacia)
    sin_else_vacio = cuerpo("if (a) {", "} else {", "    p->valor = b;", "}")
    sin_cambio(mut.almacen_directo_en_cada_rama, sin_else_vacio)
