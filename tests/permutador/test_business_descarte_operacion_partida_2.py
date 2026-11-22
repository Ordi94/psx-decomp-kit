"""Reglas de negocio: la operacion partida tambien se reconoce con compuestas y con sentencias intermedias."""

from pathlib import Path

from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import busqueda as pm
from psxdecomp.permutador import c
from psxdecomp.permutador import estado as est
from psxdecomp.permutador import evaluacion as ev
from psxdecomp.permutador import mutaciones as mut

from .ayudantes_mutaciones import CABECERA, TIPOS, cuerpo
from .test_business_busqueda import Reloj


def partidas(*lineas: str) -> int:
    """Operaciones partidas de una funcion ``f`` con locales ``v`` (entero) y ``n`` (puntero)."""
    texto = cuerpo("s32 v;", "Nodo* n;", *lineas)
    return mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS))


# --- forma A: dos asignaciones compuestas seguidas ------------------------------------------------------


def test_dos_asignaciones_compuestas_seguidas_sobre_la_misma_variable_son_una_operacion_partida() -> None:
    assert partidas("v <<= 8;", "v >>= 8;") == 1


def test_una_compuesta_seguida_de_la_reasignacion_con_constantes_es_una_operacion_partida() -> None:
    assert partidas("v += a;", "v = v >> 1;") == 1


def test_una_cadena_de_compuestas_cuenta_cada_eslabon() -> None:
    assert partidas("v = a;", "v >>= 1;", "v &= 3;") == 2


def test_la_segunda_compuesta_con_otra_variable_no_es_una_operacion_partida() -> None:
    assert partidas("v <<= 8;", "v >>= b;") == 0


# --- forma B: el par separado por sentencias que no tocan la variable ------------------------------------


def test_el_par_separado_por_sentencias_que_no_nombran_la_variable_es_una_operacion_partida() -> None:
    assert partidas("v = a << 8;", "p->valor = 3;", "b = q->clave;", "p->clave = b;", "v >>= 8;") == 1


def test_el_par_separado_por_una_declaracion_sin_relacion_es_una_operacion_partida() -> None:
    texto = cuerpo("s32 v;", "v = a << 8;", "s32 w = b;", "D_global = w;", "v >>= 8;")
    assert mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS)) == 1


def test_una_llamada_entre_el_par_puede_justificar_la_separacion_y_no_se_cuenta() -> None:
    assert partidas("v = a << 8;", "p->valor = 3;", "g(b);", "v >>= 8;") == 0
    assert partidas("v = a << 8;", "b = g(a);", "v >>= 8;") == 0


def test_una_declaracion_que_lee_la_variable_no_es_la_segunda_sentencia_del_par() -> None:
    texto = cuerpo("s32 v;", "v = a << 8;", "s32 w = v;", "D_global = w;", "v >>= 8;")
    assert mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS)) == 0


def test_una_declaracion_con_llamada_entre_el_par_tampoco_se_cuenta() -> None:
    texto = cuerpo("s32 v;", "v = a << 8;", "s32 w = g(b);", "D_global = w;", "v >>= 8;")
    assert mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS)) == 0


def test_una_sentencia_intermedia_que_lee_la_variable_impide_el_par() -> None:
    assert partidas("v = a << 8;", "D_global = v;", "v >>= 8;") == 0


def test_una_sentencia_intermedia_que_escribe_la_variable_es_la_nueva_segunda_sentencia() -> None:
    assert partidas("v = a << 8;", "v = b;", "D_global = 1;") == 0
    assert partidas("v = a << 8;", "v = b;", "v >>= 8;") == 1
    assert partidas("v = a << 8;", "D_global = 1;", "v = v & 3;", "v = b;", "D_otra = 2;") == 1


def test_una_intermedia_que_toma_la_direccion_de_la_variable_impide_el_par() -> None:
    assert partidas("v = a << 8;", "n = (Nodo*)&v;", "v >>= 8;") == 0


# --- limites del bloque ---------------------------------------------------------------------------------


def test_un_par_que_cruza_un_if_no_se_cuenta() -> None:
    assert partidas("v = a << 8;", "if (b) {", "    D_global = 1;", "}", "v >>= 8;") == 0


def test_un_par_que_cruza_una_etiqueta_un_salto_o_un_case_no_se_cuenta() -> None:
    assert partidas("v = a << 8;", "L1:", "v >>= 8;") == 0
    assert partidas("v = a << 8;", "goto L1;", "v >>= 8;", "L1:", "D_global = 1;") == 0
    assert partidas("switch (b) {", "case 1:", "    v = a << 8;", "case 2:", "    v >>= 8;", "}") == 0


def test_un_par_que_cruza_un_return_o_un_bloque_anidado_no_se_cuenta() -> None:
    assert partidas("v = a << 8;", "return;", "v >>= 8;") == 0
    assert partidas("v = a << 8;", "{", "    D_global = 1;", "}", "v >>= 8;") == 0


def test_el_par_cuya_segunda_sentencia_esta_en_otro_bloque_no_se_cuenta() -> None:
    assert partidas("v = a << 8;", "if (b) {", "    v >>= 8;", "}") == 0


def test_el_contador_de_un_bucle_no_es_una_operacion_partida() -> None:
    assert partidas("v = 0;", "while (v < a) {", "    D_global = v;", "    v++;", "}") == 0
    assert partidas("v = 0;", "for (; v < a; v++) {", "    D_global = v;", "}") == 0
    assert partidas("v = 0;", "do {", "    D_global = v;", "    v += 2;", "} while (v < a);") == 0


def test_el_incremento_dentro_del_cuerpo_del_bucle_sin_asignacion_previa_en_el_cuerpo_no_cuenta() -> None:
    assert partidas("v = 0;", "while (v < a) {", "    D_otra = a;", "    v++;", "}") == 0


# --- pasos unitarios ------------------------------------------------------------------------------------


def test_un_incremento_tras_la_asignacion_es_la_operacion_mas_uno_partida() -> None:
    assert partidas("v = a << 2;", "v++;") == 1
    assert partidas("v = a << 2;", "++v;") == 1
    assert partidas("v = a << 2;", "v--;") == 1
    assert partidas("v = a << 2;", "D_global = 1;", "--v;") == 1


def test_un_decremento_seguido_de_un_incremento_no_cuenta_aunque_siga_a_una_asignacion() -> None:
    assert partidas("v--;", "v++;") == 0
    assert partidas("v = a;", "v--;", "v++;") == 0
    assert partidas("v = a;", "v--;", "v = b;") == 1


def test_un_incremento_seguido_de_un_decremento_si_se_cuenta_tras_la_asignacion() -> None:
    assert partidas("v = a;", "v++;", "v--;") == 1


def test_un_paso_unitario_sobre_otra_variable_no_es_la_segunda_sentencia() -> None:
    assert partidas("v = a;", "a++;", "D_global = v;") == 0


# --- sin cambios en lo que no es un par -----------------------------------------------------------------


def test_una_segunda_sentencia_con_memoria_o_llamada_no_cuenta_aunque_haya_intermedias() -> None:
    assert partidas("n = p;", "D_global = 1;", "n = n->sig;") == 0
    assert partidas("v = a;", "D_global = 1;", "v = g(v);") == 0
    assert partidas("v = a;", "D_global = 1;", "v += b;") == 0


# --- comparacion con el fuente de partida ---------------------------------------------------------------


def test_el_par_en_dos_compuestas_que_ya_estaba_en_el_fuente_de_partida_no_descarta() -> None:
    base = c.analizar_funcion(cuerpo("s32 v;", "v <<= 8;", "v >>= 8;", "D_global = v;"), "f", TIPOS)
    cuenta_base = mut.contar_operaciones_partidas(base)
    assert cuenta_base == 1
    assert mut.motivo_de_descarte_nuevo(base, cuenta_base) is None


def test_el_par_separado_que_ya_estaba_en_el_fuente_de_partida_no_descarta() -> None:
    texto = cuerpo("s32 v;", "v = a << 8;", "p->valor = 3;", "v >>= 8;", "D_global = v;")
    base = c.analizar_funcion(texto, "f", TIPOS)
    assert mut.motivo_de_descarte_nuevo(base, mut.contar_operaciones_partidas(base)) is None


def test_la_variante_con_el_par_de_dos_compuestas_se_descarta_con_su_motivo() -> None:
    base = c.analizar_funcion(cuerpo("s32 v;", "v = a << 8;", "D_global = v >> 8;"), "f", TIPOS)
    nueva = c.analizar_funcion(cuerpo("s32 v;", "v = a << 8;", "v >>= 8;", "D_global = v;"), "f", TIPOS)
    assert mut.motivo_de_descarte_nuevo(nueva, mut.contar_operaciones_partidas(base)) == (
        mut.MOTIVO_OPERACION_PARTIDA
    )


def test_la_variante_con_el_par_separado_se_descarta_con_su_motivo() -> None:
    base = c.analizar_funcion(
        cuerpo("s32 v;", "v = a << 8;", "p->valor = 3;", "D_global = v >> 8;"), "f", TIPOS
    )
    nueva = c.analizar_funcion(
        cuerpo("s32 v;", "v = a << 8;", "p->valor = 3;", "v >>= 8;", "D_global = v;"), "f", TIPOS
    )
    assert mut.motivo_de_descarte_nuevo(nueva, mut.contar_operaciones_partidas(base)) == (
        mut.MOTIVO_OPERACION_PARTIDA
    )


# --- integracion con la busqueda ------------------------------------------------------------------------


def _busqueda_sobre(texto: str, tmp_path: Path, medidos: list[str]) -> pm.Resumen:
    """Ejecuta una busqueda corta sobre ``texto`` y devuelve el resultado, anotando lo que se mide."""
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(texto, "f", TIPOS)

    def evaluar(texto_variante: str, umbral: int) -> ev.ResultadoEvaluacion:
        medidos.append(texto_variante)
        return ev.ResultadoEvaluacion(50)

    estado = est.Estado("f", "codigo/modulo_a.c", 5, 50, 50, 50)
    busqueda = pm.Busqueda(
        base,
        tabla,
        evaluar,
        estado=estado,
        carpeta=tmp_path / "estado",
        opciones=pm.Opciones(iteraciones=400, procesos=2),
        salida=lambda linea: None,
        reloj=Reloj(0.001),
    )
    busqueda.iniciar_barrido()
    return busqueda.ejecutar()


def test_la_busqueda_descarta_con_su_motivo_la_variante_con_dos_compuestas_o_con_el_par_separado(
    tmp_path: Path,
) -> None:
    medidos: list[str] = []
    texto = cuerpo("s32 v;", "v = a + 4 + 8;", "p->valor = 3;", "D_global = v;")
    resultado = _busqueda_sobre(texto, tmp_path, medidos)
    assert resultado.descartadas[mut.MOTIVO_OPERACION_PARTIDA] > 0
    assert medidos
    for texto_variante in medidos:
        analizada = c.analizar_funcion(texto_variante, "f", TIPOS)
        assert mut.contar_operaciones_partidas(analizada) == 0


def _separa_el_par(variante: c.Funcion) -> bool:
    """La variante deja el almacen ``p->valor = 3;`` entre ``v = a + 4;`` y la segunda sentencia de ``v``."""
    lineas = [linea.strip() for linea in c.imprimir_funcion(variante).splitlines()]
    if "v = a + 4;" not in lineas:
        return False
    posicion = lineas.index("v = a + 4;")
    return lineas[posicion + 1] == "p->valor = 3;" and lineas[posicion + 2].startswith("v ")


def test_una_mutacion_existente_separa_el_par_con_una_sentencia_intermedia_y_la_regla_lo_descarta() -> None:
    base = c.analizar_funcion(
        cuerpo("s32 v;", "v = a + 4 + 8;", "p->valor = 3;", "D_global = v;"), "f", TIPOS
    )
    tabla = an.construir_tabla([CABECERA])
    cuenta_base = mut.contar_operaciones_partidas(base)
    pares_separados = [
        segunda
        for primera, descripcion in mut.vecinos(base, tabla)
        if descripcion.startswith("dividir_asignacion(")
        for segunda, otra in mut.vecinos(primera, tabla)
        if otra.startswith("orden_sentencias(") and _separa_el_par(segunda)
    ]
    assert pares_separados
    motivos = {mut.motivo_de_descarte_nuevo(variante, cuenta_base) for variante in pares_separados}
    assert motivos == {mut.MOTIVO_OPERACION_PARTIDA}
