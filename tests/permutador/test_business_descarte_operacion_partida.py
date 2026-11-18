"""Reglas de negocio: se descarta toda variante que parte una operacion en dos sentencias consecutivas."""

from pathlib import Path

from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import busqueda as pm
from psxdecomp.permutador import c
from psxdecomp.permutador import estado as est
from psxdecomp.permutador import evaluacion as ev
from psxdecomp.permutador import mutaciones as mut

from .ayudantes_mutaciones import CABECERA, TIPOS, aplicar, cuerpo
from .test_business_busqueda import Reloj


def partidas(*lineas: str) -> int:
    """Operaciones partidas de una funcion ``f`` con locales ``v`` (entero) y ``n`` (puntero)."""
    texto = cuerpo("s32 v;", "Nodo* n;", *lineas)
    return mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS))


def test_el_par_asignacion_y_operacion_sobre_la_misma_local_cuenta_como_partido() -> None:
    assert partidas("v = a << 8;", "v = v >> 8;") == 1


def test_el_par_con_una_constante_y_la_variable_cuenta_como_partido() -> None:
    assert partidas("v = a + 4;", "v = v & 3;") == 1


def test_una_asignacion_compuesta_tras_la_asignacion_es_la_misma_particion() -> None:
    assert partidas("v = a + 4;", "v += 3;") == 1


def test_una_compuesta_con_una_expresion_de_constantes_es_la_misma_particion() -> None:
    assert partidas("v = a;", "v <<= 2 + 1;") == 1


def test_el_par_con_un_unario_aritmetico_o_un_molde_cuenta_como_partido() -> None:
    assert partidas("v = a;", "v = -v;") == 1
    assert partidas("v = a;", "v = (u16)v;") == 1


def test_el_par_sobre_un_parametro_cuenta_como_partido() -> None:
    texto = cuerpo("a = b + 1;", "a = a << 2;")
    assert mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS)) == 1


def test_el_par_dentro_de_un_bloque_anidado_cuenta_como_partido() -> None:
    assert partidas("if (a) {", "    v = b;", "    v = v >> 1;", "}") == 1


def test_cada_par_se_cuenta_una_vez() -> None:
    assert partidas("v = a;", "v = v >> 1;", "v = b;", "v = v & 7;") == 2


def test_leer_un_campo_de_la_variable_entre_medias_no_es_una_operacion_partida() -> None:
    assert partidas("n = p;", "n = n->sig;") == 0


def test_la_segunda_sentencia_con_otra_variable_no_es_una_operacion_partida() -> None:
    assert partidas("v = a;", "v = v + b;") == 0
    assert partidas("v = a;", "v += b;") == 0


def test_la_segunda_sentencia_con_una_llamada_o_una_desreferencia_no_es_una_operacion_partida() -> None:
    assert partidas("v = a;", "v = g(v);") == 0
    assert partidas("n = p;", "n = *n;") == 0
    assert partidas("v = a;", "v = v + p->valor;") == 0
    assert partidas("v = a;", "v = v++;") == 0


def test_la_segunda_sentencia_que_no_lee_la_variable_no_es_una_operacion_partida() -> None:
    assert partidas("v = a;", "v = 5;") == 0


def test_variables_distintas_o_sentencias_no_consecutivas_no_son_una_operacion_partida() -> None:
    assert partidas("v = a;", "a = v >> 1;") == 0
    assert partidas("v = a;", "D_global = 1;", "v = v >> 1;") == 0


def test_una_variable_global_no_es_una_operacion_partida() -> None:
    assert partidas("D_global = a;", "D_global = D_global >> 1;") == 0


def test_solo_cuentan_las_sentencias_de_expresion_con_destino_simple() -> None:
    assert partidas("v = a;", "if (b) {", "    D_otra = 1;", "}") == 0
    assert partidas("g(a);", "v = v >> 1;") == 0
    assert partidas("v += a;", "v = v >> 1;") == 0
    assert partidas("p->valor = a;", "p->valor = p->valor >> 1;") == 0


def test_una_declaracion_con_inicial_no_es_una_sentencia_de_expresion() -> None:
    texto = cuerpo("s32 w = a;", "w = w >> 1;")
    assert mut.contar_operaciones_partidas(c.analizar_funcion(texto, "f", TIPOS)) == 0


def test_la_variante_con_un_par_nuevo_se_descarta_con_su_motivo() -> None:
    base = c.analizar_funcion(cuerpo("s32 v;", "v = a << 8;", "D_global = v >> 8;"), "f", TIPOS)
    nueva = c.analizar_funcion(cuerpo("s32 v;", "v = a << 8;", "v = v >> 8;", "D_global = v;"), "f", TIPOS)
    cuenta_base = mut.contar_operaciones_partidas(base)
    assert mut.motivo_de_descarte_nuevo(nueva, cuenta_base) == mut.MOTIVO_OPERACION_PARTIDA
    assert mut.MOTIVO_OPERACION_PARTIDA == "operacion_partida_en_dos_sentencias"


def test_el_par_que_ya_estaba_en_el_fuente_de_partida_no_descarta() -> None:
    texto = cuerpo("s32 v;", "v = a << 8;", "v = v >> 8;", "D_global = v;")
    base = c.analizar_funcion(texto, "f", TIPOS)
    cuenta_base = mut.contar_operaciones_partidas(base)
    assert cuenta_base == 1
    assert mut.motivo_de_descarte_nuevo(base, cuenta_base) is None


def test_un_segundo_par_sobre_un_fuente_que_ya_tenia_uno_si_descarta() -> None:
    uno = c.analizar_funcion(cuerpo("s32 v;", "v = a << 8;", "v = v >> 8;", "D_global = v;"), "f", TIPOS)
    dos = c.analizar_funcion(
        cuerpo("s32 v;", "v = a << 8;", "v = v >> 8;", "v = b;", "v = v & 3;", "D_global = v;"), "f", TIPOS
    )
    assert mut.motivo_de_descarte_nuevo(dos, mut.contar_operaciones_partidas(uno)) == (
        mut.MOTIVO_OPERACION_PARTIDA
    )


def test_el_acceso_a_memoria_entre_medias_no_se_descarta() -> None:
    base = c.analizar_funcion(cuerpo("Nodo* n;", "n = p;", "D_global = n->valor;"), "f", TIPOS)
    nueva = c.analizar_funcion(
        cuerpo("Nodo* n;", "n = p;", "n = n->sig;", "D_global = n->valor;"), "f", TIPOS
    )
    assert mut.motivo_de_descarte_nuevo(nueva, mut.contar_operaciones_partidas(base)) is None


def test_dividir_asignacion_puede_producir_el_par_y_la_regla_lo_descarta() -> None:
    texto = cuerpo("s32 v;", "v = a + 4 + 8;", "D_global = v;")
    base = c.analizar_funcion(texto, "f", TIPOS)
    cuenta_base = mut.contar_operaciones_partidas(base)
    tabla = an.construir_tabla([CABECERA])
    motivos = {
        mut.motivo_de_descarte_nuevo(variante, cuenta_base)
        for variante, descripcion in mut.vecinos(base, tabla)
        if descripcion.startswith("dividir_asignacion(")
    }
    assert mut.MOTIVO_OPERACION_PARTIDA in motivos


def test_la_variante_descartada_sigue_siendo_un_c_valido_que_se_imprime_estable() -> None:
    _, resultado = aplicar(mut.dividir_asignacion, cuerpo("s32 v;", "v = a + 4 + 8;", "D_global = v;"))
    assert "v = a + 4;" in resultado


def test_la_busqueda_no_mide_ninguna_variante_con_una_operacion_nueva_partida(tmp_path: Path) -> None:
    texto = cuerpo("s32 v;", "v = a + 4 + 8;", "D_global = v;")
    tabla = an.construir_tabla([CABECERA])
    base = c.analizar_funcion(texto, "f", TIPOS)
    medidos: list[str] = []

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
    resultado = busqueda.ejecutar()
    assert resultado.descartadas[mut.MOTIVO_OPERACION_PARTIDA] > 0
    assert medidos
    for texto_variante in medidos:
        analizada = c.analizar_funcion(texto_variante, "f", TIPOS)
        assert mut.contar_operaciones_partidas(analizada) == 0
