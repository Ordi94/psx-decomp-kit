"""Reglas de negocio de las mutaciones de movimiento, envoltura, locales y expresiones.

Cada prueba fija CUANDO es legal la reformulacion (el programa resultante hace lo mismo) y cuando no
lo es: dependencia de lectura o escritura, llamada opaca, salto, direccion tomada, tipo que cambia un
valor o constante que desborda el tipo.
"""

import re

import pytest
from psxdecomp.permutador import c
from psxdecomp.permutador import mutaciones as mut

from permutador.ayudantes_mutaciones import aplicar, cuerpo, sin_cambio, todas_las_variantes

# Valores del tope fijados aqui, no leidos de la constante: si alguien los desactiva o los sube, la
# prueba que los afirma contra ``mut`` falla en vez de seguir al valor modificado.
ALCANCE_DE_REFERENCIA = 8
MAX_ENVUELTAS_DE_REFERENCIA = 6

# --- mover_sentencia_a_distancia -------------------------------------------------------------------------


def test_una_sentencia_se_mueve_hacia_adelante_cruzando_independientes() -> None:
    texto = cuerpo("s32 x;", "x = a + 1;", "D_global = b;", "D_otra = b;", "p->valor = a;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert cuerpo("s32 x;", "D_global = b;", "D_otra = b;", "x = a + 1;", "p->valor = a;") in variantes


def test_una_sentencia_se_mueve_hacia_atras_cruzando_independientes() -> None:
    texto = cuerpo("D_global = b;", "D_otra = b;", "q->valor = a;", "p->clave = 1;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert cuerpo("p->clave = 1;", "D_global = b;", "D_otra = b;", "q->valor = a;") in variantes


def test_no_cruza_una_sentencia_que_escribe_lo_que_lee_la_movida() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("s32 x;", "x = a;", "a = 3;", "b = x;"))


def test_no_cruza_una_sentencia_que_lee_lo_que_escribe_la_movida() -> None:
    texto = cuerpo("D_global = a;", "b = D_global;", "q->valor = b;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("D_global = a;") < v.index("b = D_global;") for v in variantes)


def test_no_cruza_dos_escrituras_a_la_misma_memoria() -> None:
    texto = cuerpo("p->valor = 1;", "p->valor = 2;", "p->valor = 3;")
    sin_cambio(mut.mover_sentencia_a_distancia, texto)


def test_una_llamada_no_se_mueve_ni_se_cruza_con_memoria() -> None:
    texto = cuerpo("p->valor = 1;", "g(a);", "h(b);", "q->valor = 2;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("p->valor = 1;") < v.index("g(a);") for v in variantes)


def test_una_local_cruza_una_llamada_que_no_la_menciona() -> None:
    texto = cuerpo("s32 x;", "s32 y;", "x = a + 1;", "g(b);", "h(b);", "y = x;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert cuerpo("s32 x;", "s32 y;", "g(b);", "h(b);", "x = a + 1;", "y = x;") in variantes


def test_una_local_no_cruza_una_llamada_que_la_lee_o_la_escribe() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("s32 x;", "x = a + 1;", "g(x);", "h(b);"))
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("s32 x;", "x = a + 1;", "b = g(x);", "h(b);"))
    texto = cuerpo("s32 x;", "b = x;", "g(b);", "h(a);", "x = 0;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert variantes
    assert all(v.index("b = x;") < v.index("x = 0;") for v in variantes)


def test_una_local_que_lee_el_resultado_de_la_llamada_no_la_cruza() -> None:
    sin_cambio(
        mut.mover_sentencia_a_distancia, cuerpo("s32 x;", "s32 y;", "y = g(a);", "h(y);", "x = y + 1;")
    )


def test_una_variable_con_direccion_tomada_no_se_mueve() -> None:
    texto = cuerpo("s32 x;", "g(&x);", "x = 1;", "D_global = a;", "D_otra = b;", "h(x);")
    sin_cambio(mut.mover_sentencia_a_distancia, texto)


def test_no_se_cruza_una_etiqueta_un_salto_ni_un_return() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("D_global = 1;", "goto fin;", "D_otra = 2;", "fin:"))
    sin_cambio(
        mut.mover_sentencia_a_distancia,
        cuerpo("D_global = 1;", "if (a) {", "    return;", "}", "D_otra = 2;"),
    )
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("D_global = 1;", "fin:", "D_otra = 2;"))


def test_no_se_cruza_un_bucle_que_nunca_termina() -> None:
    texto = cuerpo("D_global = 1;", "while (1) {", "    q->valor = a;", "}", "D_otra = 2;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("D_global = 1;") < v.index("while (1)") for v in variantes)
    texto = cuerpo("D_global = 1;", "for (;;) {", "    q->valor = a;", "}", "D_otra = 2;")
    assert all(
        v.index("D_global = 1;") < v.index("for (;;)")
        for v in todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    )
    texto = cuerpo("D_global = 1;", "do {", "    q->valor = a;", "} while (1);", "D_otra = 2;")
    assert all(
        v.index("D_global = 1;") < v.index("do {")
        for v in todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    )


def test_se_cruza_un_bucle_que_termina_si_es_independiente() -> None:
    texto = cuerpo("D_global = 1;", "while (b) {", "    q->valor = a;", "    b--;", "}", "p->clave = 2;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert (
        cuerpo("while (b) {", "    q->valor = a;", "    b--;", "}", "p->clave = 2;", "D_global = 1;")
        in variantes
    )


def test_una_declaracion_con_inicial_se_mueve_entera_dentro_de_la_serie() -> None:
    texto = cuerpo("s32 x;", "s32 y;", "s32 z = a + 1;", "D_global = z;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert cuerpo("s32 z = a + 1;", "s32 x;", "s32 y;", "D_global = z;") in variantes


def test_una_declaracion_con_inicial_deja_la_declaracion_y_mueve_la_asignacion() -> None:
    texto = cuerpo("s32 x = a + 1;", "D_global = b;", "D_otra = b;", "p->valor = x;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert cuerpo("s32 x;", "D_global = b;", "D_otra = b;", "x = a + 1;", "p->valor = x;") in variantes


def test_la_asignacion_dividida_no_pasa_por_encima_de_un_uso_de_la_variable() -> None:
    texto = cuerpo("s32 x = a + 1;", "D_global = x;", "D_otra = b;", "p->valor = b;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("D_global = x;") > v.index("x = a + 1;") for v in variantes if "s32 x;" in v)


def test_una_declaracion_no_se_mueve_si_su_orden_deja_de_ser_valido() -> None:
    texto = cuerpo("s32 x;", "s32 y = a;", "s32 z = y + 1;", "D_global = z;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("s32 y = a;") < v.index("s32 z = y + 1;") for v in variantes if "s32 y = a;" in v)


def test_una_declaracion_con_arreglo_o_calificador_no_se_divide() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("const s32 x = 1;", "D_global = a;", "D_otra = b;"))
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("s32 x[2] = 1;", "D_global = a;", "D_otra = b;"))


def test_una_expresion_cruza_una_declaracion_que_no_menciona() -> None:
    texto = cuerpo("s32 x;", "D_global = a;", "D_otra = b;", "p->valor = 1;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert all(v.index("s32 x;") < v.index("D_global = a;") for v in variantes)


def test_la_descripcion_indica_origen_y_destino() -> None:
    descripcion, _ = aplicar(
        mut.mover_sentencia_a_distancia, cuerpo("D_global = a;", "D_otra = b;", "p->valor = 1;")
    )
    assert descripcion is not None and descripcion.startswith("mover_sentencia_a_distancia(")


def test_sin_dos_sentencias_independientes_no_hay_movimiento() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("D_global = a;"))
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("if (a) {", "    D_global = 1;", "}", "return;"))


def _sentencias_del_cuerpo(texto: str) -> list[str]:
    """Las lineas del cuerpo de ``f`` sin sangrado, una por sentencia (las pruebas no anidan)."""
    return [linea.strip() for linea in texto.splitlines()[2:-1]]


def _desplazamiento_maximo(original: str, variante: str) -> int:
    """Mayor cambio de posicion de una sentencia entre el original y la variante (sentencias unicas)."""
    antes = _sentencias_del_cuerpo(original)
    despues = _sentencias_del_cuerpo(variante)
    assert sorted(antes) == sorted(despues)
    return max(abs(despues.index(sentencia) - posicion) for posicion, sentencia in enumerate(antes))


def _texto_de_alcance() -> str:
    """Una sentencia seguida de doce independientes: sobra recorrido para superar cualquier tope."""
    relleno = [f"q->clave = {i};" if i % 2 else f"D_otra = {i};" for i in range(12)]
    return cuerpo("p->valor = 0;", "D_global = a;", *relleno, "q->valor = 1;")


def test_el_alcance_de_un_movimiento_esta_acotado() -> None:
    texto = _texto_de_alcance()
    distancias = {
        _desplazamiento_maximo(texto, variante)
        for variante in todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    }
    assert distancias
    assert max(distancias) == mut.ALCANCE_MAXIMO_DE_MOVIMIENTO


def test_sin_tope_de_alcance_el_movimiento_superaria_la_distancia_maxima(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mut, "ALCANCE_MAXIMO_DE_MOVIMIENTO", 100)
    texto = _texto_de_alcance()
    distancias = {
        _desplazamiento_maximo(texto, variante)
        for variante in todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    }
    assert max(distancias) > ALCANCE_DE_REFERENCIA


def test_con_dos_sentencias_independientes_la_distancia_uno_pertenece_a_orden_de_sentencias() -> None:
    sin_cambio(mut.mover_sentencia_a_distancia, cuerpo("D_global = a;", "D_otra = b;"))


def test_con_tres_sentencias_independientes_se_mueve_a_distancia_dos() -> None:
    texto = cuerpo("D_global = a;", "D_otra = b;", "p->valor = 1;")
    variantes = todas_las_variantes(mut.mover_sentencia_a_distancia, texto)
    assert variantes
    assert all(_desplazamiento_maximo(texto, variante) == 2 for variante in variantes)
    assert cuerpo("D_otra = b;", "p->valor = 1;", "D_global = a;") in variantes


# --- envolver_en_bloque ---------------------------------------------------------------------------------


def test_se_envuelve_un_rango_que_contiene_una_llamada() -> None:
    texto = cuerpo("D_global = a;", "g(a);", "D_otra = b;")
    variantes = todas_las_variantes(mut.envolver_en_bloque, texto)
    assert cuerpo("D_global = a;", "do {", "    g(a);", "} while (0);", "D_otra = b;") in variantes
    assert cuerpo("D_global = a;", "do {", "    g(a);", "    D_otra = b;", "} while (0);") in variantes


def test_se_envuelve_todo_el_bloque_aunque_no_tenga_llamadas() -> None:
    texto = cuerpo("D_global = a;", "D_otra = b;")
    variantes = todas_las_variantes(mut.envolver_en_bloque, texto)
    assert cuerpo("do {", "    D_global = a;", "    D_otra = b;", "} while (0);") in variantes


def test_no_se_envuelve_un_rango_sin_llamada_que_no_abarca_el_bloque() -> None:
    texto = cuerpo("D_global = a;", "D_otra = b;", "p->valor = 1;")
    assert all(
        v.count("do {") == 1 and "do {\n        D_global = a;\n        D_otra = b;\n        p->valor" in v
        for v in todas_las_variantes(mut.envolver_en_bloque, texto)
    )


def test_no_se_envuelve_una_sentencia_vacia_ni_codigo_nuevo() -> None:
    sin_cambio(mut.envolver_en_bloque, cuerpo(";"))
    sin_cambio(mut.envolver_en_bloque, cuerpo("s32 x;"))
    texto = cuerpo("g(a);", "D_global = a;")
    for variante in todas_las_variantes(mut.envolver_en_bloque, texto):
        assert variante.replace("do {", "").replace("} while (0);", "").count("g(a);") == 1


def test_no_se_envuelve_un_rango_con_break_continue_saltos_o_etiquetas() -> None:
    sin_cambio(mut.envolver_en_bloque, cuerpo("while (a) {", "    break;", "}"))
    for variante in todas_las_variantes(
        mut.envolver_en_bloque, cuerpo("while (a) {", "    g(a);", "    continue;", "}")
    ):
        assert variante.index("} while (0);") < variante.index("continue;")
    sin_cambio(mut.envolver_en_bloque, cuerpo("goto fin;", "fin:"))
    for variante in todas_las_variantes(
        mut.envolver_en_bloque, cuerpo("switch (a) {", "case 1:", "    g(a);", "    break;", "}")
    ):
        assert variante.index("} while (0);") < variante.index("break;")
        assert variante.index("case 1:") < variante.index("do {")


def test_un_return_dentro_de_un_rango_envuelto_se_conserva() -> None:
    texto = cuerpo("if (a) {", "    g(a);", "    return;", "}", "D_global = b;")
    variantes = todas_las_variantes(mut.envolver_en_bloque, texto)
    assert any("do {" in v and "return;" in v for v in variantes)


def test_una_envoltura_no_se_envuelve_otra_vez_pero_se_pueden_envolver_sus_vecinas() -> None:
    texto = cuerpo("do {", "    g(a);", "} while (0);")
    sin_cambio(mut.envolver_en_bloque, texto)
    texto = cuerpo("do {", "    g(a);", "    D_global = a;", "} while (0);", "D_otra = b;")
    for variante in todas_las_variantes(mut.envolver_en_bloque, texto):
        assert "} while (0);\n    } while (0);\n    D_otra" not in variante


def _sentencias_envueltas(variante: str) -> int:
    """Cantidad de sentencias entre ``do {`` y ``} while (0);`` de la variante."""
    bloques = re.findall(r"do \{\n(.*?)\n\s*\} while \(0\);", variante, re.DOTALL)
    assert len(bloques) == 1
    return sum(1 for linea in bloques[0].splitlines() if linea.strip().endswith(";"))


def test_el_rango_envuelto_tiene_un_tope_de_sentencias() -> None:
    texto = cuerpo(*[f"g({i});" for i in range(10)])
    cantidades = {
        _sentencias_envueltas(variante) for variante in todas_las_variantes(mut.envolver_en_bloque, texto)
    }
    assert cantidades
    assert max(cantidades) == mut.MAX_SENTENCIAS_ENVUELTAS


def test_sin_tope_de_envoltura_el_rango_superaria_el_maximo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mut, "MAX_SENTENCIAS_ENVUELTAS", 100)
    texto = cuerpo(*[f"g({i});" for i in range(10)])
    cantidades = {
        _sentencias_envueltas(variante) for variante in todas_las_variantes(mut.envolver_en_bloque, texto)
    }
    assert max(cantidades) > MAX_ENVUELTAS_DE_REFERENCIA


def test_contar_envolturas_cuenta_las_anidadas() -> None:
    funcion = c.analizar_funcion(
        cuerpo(
            "do {",
            "    do {",
            "        g(a);",
            "    } while (0);",
            "} while (0);",
            "do {",
            "    g(b);",
            "} while (a);",
        ),
        "f",
        frozenset({"Nodo", "Mundo"}),
    )
    assert mut.contar_envolturas(funcion) == 2


def test_una_condicion_cero_con_otro_literal_no_es_una_envoltura() -> None:
    funcion = c.analizar_funcion(
        cuerpo("do {", "    g(a);", "} while (1);"), "f", frozenset({"Nodo", "Mundo"})
    )
    assert mut.contar_envolturas(funcion) == 0


# --- dividir_local_multiset ----------------------------------------------------------------------------


def test_una_local_asignada_varias_veces_se_reparte_en_locales_frescas() -> None:
    texto = cuerpo("s32 u;", "u = a;", "u = f(u, a);", "u = g(u, b);", "h(u);")
    _, resultado = aplicar(mut.dividir_local_multiset, texto)
    assert resultado == cuerpo(
        "s32 tmp1;",
        "s32 tmp2;",
        "s32 tmp3;",
        "tmp1 = a;",
        "tmp2 = f(tmp1, a);",
        "tmp3 = g(tmp2, b);",
        "h(tmp3);",
    )


def test_la_primera_asignacion_conserva_el_valor_inicial_de_la_declaracion() -> None:
    texto = cuerpo("s32 u = a;", "u = u + 1;", "D_global = u;", "u = b;", "D_otra = u;")
    _, resultado = aplicar(mut.dividir_local_multiset, texto)
    assert resultado == cuerpo(
        "s32 u = a;",
        "s32 tmp1;",
        "s32 tmp2;",
        "tmp1 = u + 1;",
        "D_global = tmp1;",
        "tmp2 = b;",
        "D_otra = tmp2;",
    )


def test_los_usos_anidados_entre_asignaciones_se_renombran() -> None:
    texto = cuerpo(
        "s32 u;", "u = a;", "if (b) {", "    D_global = u;", "}", "u = b;", "while (u) {", "    u--;", "}"
    )
    sin_cambio(mut.dividir_local_multiset, texto)
    texto = cuerpo("s32 u;", "u = a;", "if (b) {", "    D_global = u;", "}", "u = b;", "D_otra = u;")
    _, resultado = aplicar(mut.dividir_local_multiset, texto)
    assert "D_global = tmp1;" in resultado and "D_otra = tmp2;" in resultado


def test_no_se_divide_una_local_escrita_dentro_de_una_rama_o_con_otro_operador() -> None:
    sin_cambio(
        mut.dividir_local_multiset, cuerpo("s32 u;", "u = a;", "if (b) {", "    u = 1;", "}", "u = 2;")
    )
    sin_cambio(mut.dividir_local_multiset, cuerpo("s32 u;", "u = a;", "u += 1;", "u = b;"))
    sin_cambio(mut.dividir_local_multiset, cuerpo("s32 u;", "u = a;", "u++;", "u = b;"))


def test_no_se_divide_una_local_con_una_sola_asignacion() -> None:
    sin_cambio(mut.dividir_local_multiset, cuerpo("s32 u;", "u = a;", "D_global = u;"))


def test_no_se_divide_con_etiquetas_ni_con_la_direccion_tomada_ni_en_un_bloque_interior() -> None:
    sin_cambio(mut.dividir_local_multiset, cuerpo("s32 u;", "u = a;", "fin:", "u = b;"))
    sin_cambio(mut.dividir_local_multiset, cuerpo("s32 u;", "g(&u);", "u = a;", "u = b;"))
    sin_cambio(
        mut.dividir_local_multiset,
        cuerpo("if (a) {", "    s32 u;", "    u = a;", "    u = b;", "    h(u);", "}"),
    )


def test_no_se_divide_una_estructura_ni_un_parametro() -> None:
    sin_cambio(mut.dividir_local_multiset, cuerpo("Registro r;", "r = *q;", "r = *q;"))
    sin_cambio(mut.dividir_local_multiset, cuerpo("a = 1;", "a = 2;", "h(a);"))


def test_la_declaracion_original_sin_usos_se_elimina() -> None:
    texto = cuerpo("s32 u;", "u = f(a);", "u = g(b);", "h(u);")
    _, resultado = aplicar(mut.dividir_local_multiset, texto)
    assert "s32 u;" not in resultado


# --- expandir_local ------------------------------------------------------------------------------------


def test_una_local_de_un_solo_uso_se_sustituye_por_su_expresion_a_distancia() -> None:
    texto = cuerpo("s32 x;", "x = a + b;", "D_global = 1;", "D_otra = x;")
    _, resultado = aplicar(mut.expandir_local, texto)
    assert resultado == cuerpo("D_global = 1;", "D_otra = a + b;")


def test_una_local_con_inicializador_se_expande() -> None:
    texto = cuerpo("s32 x = a + b;", "D_global = 1;", "D_otra = x;")
    _, resultado = aplicar(mut.expandir_local, texto)
    assert resultado == cuerpo("D_global = 1;", "D_otra = a + b;")


def test_no_se_expande_si_una_sentencia_intermedia_escribe_un_operando() -> None:
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a + b;", "a = 3;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = p->valor;", "p->valor = 3;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = p->valor;", "g(a);", "D_otra = x;"))


def test_no_se_expande_con_mas_de_un_uso_ni_con_varias_escrituras() -> None:
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a + b;", "D_global = x;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a;", "x = b;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x = a;", "x = b;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a + b;"))


def test_no_se_expande_si_el_valor_tiene_efectos_o_el_tipo_lo_cambia() -> None:
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = g(a);", "D_global = 1;", "D_otra = x;"))
    sin_cambio(mut.expandir_local, cuerpo("s16 x;", "x = a + b;", "D_global = 1;", "D_otra = x;"))


def test_no_se_expande_si_el_uso_esta_en_la_condicion_de_un_bucle_o_en_otra_rama() -> None:
    sin_cambio(
        mut.expandir_local, cuerpo("s32 x;", "x = a;", "D_global = 1;", "while (b < x) {", "    b++;", "}")
    )
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a;", "if (b) {", "    D_otra = x;", "}"))


def test_no_se_expande_si_hay_una_etiqueta_entre_la_asignacion_y_el_uso() -> None:
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a;", "fin:", "D_otra = x;"))


def test_no_se_expande_un_uso_perezoso_ni_uno_con_otras_asignaciones_en_la_sentencia() -> None:
    sin_cambio(
        mut.expandir_local,
        cuerpo("s32 x;", "x = a;", "D_global = 1;", "if (b && x) {", "    D_otra = 1;", "}"),
    )
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a;", "D_global = 1;", "D_otra = (b = 2) + x;"))
    sin_cambio(mut.expandir_local, cuerpo("s32 x;", "x = a;", "D_global = 1;", "D_otra = x + b++;"))


def test_un_uso_en_la_condicion_de_un_if_o_en_un_return_se_expande() -> None:
    _, resultado = aplicar(
        mut.expandir_local,
        cuerpo("s32 x;", "x = a + 1;", "D_global = 1;", "if (x) {", "    D_otra = 1;", "}"),
    )
    assert "if (a + 1) {" in resultado


# --- cadena_de_asignacion ------------------------------------------------------------------------------


def test_dos_asignaciones_iguales_se_encadenan() -> None:
    texto = cuerpo("s32 x;", "s32 y;", "x = a + b;", "y = a + b;", "D_global = x + y;")
    _, resultado = aplicar(mut.cadena_de_asignacion, texto)
    assert resultado == cuerpo("s32 x;", "s32 y;", "x = y = a + b;", "D_global = x + y;")


def test_una_cadena_se_separa_en_dos_asignaciones() -> None:
    texto = cuerpo("s32 x;", "s32 y;", "x = y = a + b;", "D_global = x + y;")
    _, resultado = aplicar(mut.cadena_de_asignacion, texto)
    assert resultado == cuerpo("s32 x;", "s32 y;", "x = a + b;", "y = a + b;", "D_global = x + y;")


def test_no_se_encadenan_valores_distintos_ni_con_efectos() -> None:
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "x = a + b;", "y = a + 1;"))
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "x = g(a);", "y = g(a);"))


def test_no_se_encadena_si_el_valor_menciona_un_destino() -> None:
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "x = x + 1;", "y = x + 1;"))
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "x = y = x + 1;"))


def test_no_se_encadenan_destinos_de_distinto_tipo() -> None:
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s16 y;", "x = a;", "y = a;"))
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s16 y;", "x = y = a;"))


def test_no_se_encadena_el_mismo_destino_ni_si_la_segunda_lleva_comentario() -> None:
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "x = a;", "x = a;"))
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "x = a;", "/* nota */", "y = a;"))


def test_un_valor_que_lee_memoria_solo_se_encadena_entre_locales_sin_direccion() -> None:
    texto = cuerpo("s32 x;", "s32 y;", "x = p->valor;", "y = p->valor;", "D_global = x + y;")
    _, resultado = aplicar(mut.cadena_de_asignacion, texto)
    assert "x = y = p->valor;" in resultado
    sin_cambio(mut.cadena_de_asignacion, cuerpo("D_global = p->valor;", "D_otra = p->valor;"))
    sin_cambio(mut.cadena_de_asignacion, cuerpo("s32 x;", "x = p->valor;", "D_otra = p->valor;"))


def test_dos_globales_se_encadenan_si_el_valor_no_lee_memoria() -> None:
    _, resultado = aplicar(mut.cadena_de_asignacion, cuerpo("D_global = a + 1;", "D_otra = a + 1;"))
    assert "D_global = D_otra = a + 1;" in resultado


def test_no_se_encadena_una_variable_con_la_direccion_tomada() -> None:
    sin_cambio(
        mut.cadena_de_asignacion, cuerpo("s32 x;", "s32 y;", "g(&x);", "x = p->valor;", "y = p->valor;")
    )


# --- dividir_asignacion --------------------------------------------------------------------------------


def test_una_suma_de_tres_se_parte_en_dos_pasos() -> None:
    texto = cuerpo("s32 r;", "r = a + b + 3;", "D_global = r;")
    variantes = todas_las_variantes(mut.dividir_asignacion, texto)
    assert cuerpo("s32 r;", "r = a + b;", "r = r + 3;", "D_global = r;") in variantes
    assert cuerpo("s32 r;", "r = a + b;", "r += 3;", "D_global = r;") in variantes


def test_una_asignacion_simple_se_parte_dejando_el_primer_operando() -> None:
    texto = cuerpo("s32 r;", "r = a - b;", "D_global = r;")
    variantes = todas_las_variantes(mut.dividir_asignacion, texto)
    assert cuerpo("s32 r;", "r = a;", "r -= b;", "D_global = r;") in variantes


def test_dos_sentencias_se_unen_en_una() -> None:
    texto = cuerpo("s32 r;", "r = a + b;", "r += 3;", "D_global = r;")
    _, resultado = aplicar(mut.dividir_asignacion, texto)
    assert resultado == cuerpo("s32 r;", "r = a + b + 3;", "D_global = r;") or "r = r" in resultado
    texto = cuerpo("s32 r;", "r = a + b;", "r = r | 3;", "D_global = r;")
    variantes = todas_las_variantes(mut.dividir_asignacion, texto)
    assert cuerpo("s32 r;", "r = a + b | 3;", "D_global = r;") in variantes


def test_no_se_parte_si_la_variable_aparece_en_el_valor_o_hay_llamadas() -> None:
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = r + a + b;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = g(a) + b;"))


def test_no_se_parte_un_destino_estrecho_ni_con_direccion_tomada() -> None:
    sin_cambio(mut.dividir_asignacion, cuerpo("s16 r;", "r = a + b + 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "g(&r);", "r = a + b + 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("D_global = a + b;"))


def test_no_se_parte_un_desplazamiento_con_tipos_de_distinto_signo() -> None:
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "u32 v;", "r = v >> 2;"))
    variantes = todas_las_variantes(mut.dividir_asignacion, cuerpo("u32 r;", "u32 v;", "r = v >> 2;"))
    assert cuerpo("u32 r;", "u32 v;", "r = v;", "r >>= 2;") in variantes


def test_no_se_parte_con_un_primer_operando_de_tipo_desconocido() -> None:
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = desconocido + b;"))


def test_no_se_unen_dos_sentencias_con_comentario_o_con_otra_variable() -> None:
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "s32 t;", "r = a;", "t += 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = a;", "/* nota */", "r += 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = a;", "r = 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = a;", "r += r;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = a;", "r *= 3;"))
    sin_cambio(mut.dividir_asignacion, cuerpo("s32 r;", "r = a;", "g(r);"))


def test_un_puntero_se_parte_con_aritmetica_de_direccion() -> None:
    texto = cuerpo("Nodo* r;", "r = p + a + b;", "D_global = r->valor;")
    variantes = todas_las_variantes(mut.dividir_asignacion, texto)
    assert cuerpo("Nodo* r;", "r = p + a;", "r += b;", "D_global = r->valor;") in variantes


# --- ajustar_desigualdad -------------------------------------------------------------------------------


def test_menor_que_pasa_a_menor_o_igual_con_la_constante_menos_uno() -> None:
    texto = cuerpo("if (a < 10) {", "    D_global = 1;", "}")
    assert cuerpo("if (a <= 9) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )


def test_mayor_que_pasa_a_mayor_o_igual_con_la_constante_mas_uno() -> None:
    texto = cuerpo("while (b > 4) {", "    b--;", "}")
    assert cuerpo("while (b >= 5) {", "    b--;", "}") in todas_las_variantes(mut.ajustar_desigualdad, texto)


def test_las_formas_con_igual_vuelven_a_la_desigualdad_estricta() -> None:
    texto = cuerpo("for (a = 0; a <= 7; a++) {", "    D_global = a;", "}")
    assert cuerpo("for (a = 0; a < 8; a++) {", "    D_global = a;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )
    texto = cuerpo("if (a >= 3) {", "    D_global = 1;", "}")
    assert cuerpo("if (a > 2) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )


def test_una_constante_negativa_se_escribe_con_signo() -> None:
    texto = cuerpo("if (a > -3) {", "    D_global = 1;", "}")
    assert cuerpo("if (a >= -2) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )
    texto = cuerpo("if (a >= 0) {", "    D_global = 1;", "}")
    assert cuerpo("if (a > -1) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )


def test_un_valor_sin_signo_no_pasa_a_una_constante_negativa() -> None:
    sin_cambio(mut.ajustar_desigualdad, cuerpo("u32 v;", "if (v < 0) {", "    D_global = 1;", "}"))
    texto = cuerpo("u16 v;", "if (v < 0) {", "    D_global = 1;", "}")
    assert cuerpo("u16 v;", "if (v <= -1) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )


def test_no_se_ajusta_si_la_constante_sale_del_tipo() -> None:
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (a < -2147483647 - 1) {", "    D_global = 1;", "}"))
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (a > 2147483647) {", "    D_global = 1;", "}"))


def test_no_se_ajusta_con_sufijo_sin_signo_ni_con_operandos_no_enteros() -> None:
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (a < 10u) {", "    D_global = 1;", "}"))
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (p < 10) {", "    D_global = 1;", "}"))
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (a < b) {", "    D_global = 1;", "}"))
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (desconocido < 3) {", "    D_global = 1;", "}"))
    sin_cambio(mut.ajustar_desigualdad, cuerpo("if (a == 3) {", "    D_global = 1;", "}"))


def test_un_valor_estrecho_se_compara_en_el_tipo_promovido() -> None:
    texto = cuerpo("if (p->corto < 100) {", "    D_global = 1;", "}")
    assert cuerpo("if (p->corto <= 99) {", "    D_global = 1;", "}") in todas_las_variantes(
        mut.ajustar_desigualdad, texto
    )


# --- forma_de_acceso_a_struct --------------------------------------------------------------------------


def test_un_acceso_con_indice_toma_las_otras_tres_formas() -> None:
    variantes = todas_las_variantes(mut.forma_de_acceso_a_struct, cuerpo("D_global = tabla[a].valor;"))
    assert variantes == {
        cuerpo("D_global = (tabla + a)->valor;"),
        cuerpo("D_global = (&tabla[a])->valor;"),
        cuerpo("D_global = (*(tabla + a)).valor;"),
    }


def test_cada_forma_se_reconoce_y_pasa_a_las_demas() -> None:
    for entrada in ("(p + a)->valor", "(&p[a])->valor", "(*(p + a)).valor", "p[a].valor"):
        variantes = todas_las_variantes(mut.forma_de_acceso_a_struct, cuerpo(f"D_global = {entrada};"))
        esperadas = {
            f"D_global = {f};" for f in ("(p + a)->valor", "(&p[a])->valor", "(*(p + a)).valor", "p[a].valor")
        }
        obtenidas = {
            linea.strip()
            for v in variantes
            for linea in v.splitlines()
            if linea.strip().startswith("D_global")
        }
        assert obtenidas == esperadas - {f"D_global = {entrada};"}


def test_tambien_se_reescribe_un_destino_de_asignacion() -> None:
    variantes = todas_las_variantes(mut.forma_de_acceso_a_struct, cuerpo("tabla[a].valor = b;"))
    assert cuerpo("(tabla + a)->valor = b;") in variantes


def test_no_se_reescribe_si_la_base_no_es_un_puntero_o_el_indice_no_es_entero() -> None:
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (a + b)->valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (p + q)->valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (*(a + b)).valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (desconocido + a)->valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (p - a)->valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = p->valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (*p).valor;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = (&p->valor)->x;"))
    sin_cambio(mut.forma_de_acceso_a_struct, cuerpo("D_global = a;"))


# --- cast_en_subexpresion ------------------------------------------------------------------------------


def test_un_valor_guardado_en_un_destino_de_16_bits_admite_moldes_de_ese_ancho_o_mayor() -> None:
    variantes = todas_las_variantes(mut.cast_en_subexpresion, cuerpo("p->corto = a + b;"))
    assert variantes == {
        cuerpo("p->corto = (s16)(a + b);"),
        cuerpo("p->corto = (u16)(a + b);"),
        cuerpo("p->corto = (s32)(a + b);"),
    }


def test_un_destino_de_8_bits_admite_tambien_el_molde_de_8_bits() -> None:
    variantes = todas_las_variantes(mut.cast_en_subexpresion, cuerpo("p->byte = a + b;"))
    assert cuerpo("p->byte = (u8)(a + b);") in variantes


def test_un_molde_s32_sobre_una_expresion_de_32_bits_es_la_identidad() -> None:
    variantes = todas_las_variantes(mut.cast_en_subexpresion, cuerpo("D_global = a * b;"))
    assert variantes == {cuerpo("D_global = (s32)(a * b);")}


def test_se_quita_un_molde_que_no_cambia_el_valor() -> None:
    variantes = todas_las_variantes(mut.cast_en_subexpresion, cuerpo("p->corto = (s16)(a + b);"))
    assert cuerpo("p->corto = a + b;") in variantes
    variantes = todas_las_variantes(mut.cast_en_subexpresion, cuerpo("D_global = (s32)(a * b);"))
    assert cuerpo("D_global = a * b;") in variantes


def test_un_molde_mas_estrecho_que_el_destino_no_se_quita() -> None:
    sin_cambio(mut.cast_en_subexpresion, cuerpo("p->ancho = (u8)(a + b);"))
    sin_cambio(mut.cast_en_subexpresion, cuerpo("D_global = (s16)(a + b);"))
    sin_cambio(mut.cast_en_subexpresion, cuerpo("D_global = (u16)(a + b);"))


def test_no_se_anade_un_molde_que_cambiaria_el_valor() -> None:
    sin_cambio(mut.cast_en_subexpresion, cuerpo("u32 v;", "D_otra = v + 1;"))
    sin_cambio(mut.cast_en_subexpresion, cuerpo("p->valor = a;"))
    sin_cambio(mut.cast_en_subexpresion, cuerpo("D_global = a;"))


def test_no_se_anade_un_molde_encima_de_otro_ni_sobre_una_expresion_de_tipo_desconocido() -> None:
    sin_cambio(mut.cast_en_subexpresion, cuerpo("p->valor = (u16)desconocido;"))
    sin_cambio(mut.cast_en_subexpresion, cuerpo("D_global = (s32)(desconocido + 1);"))
    for variante in todas_las_variantes(mut.cast_en_subexpresion, cuerpo("D_global = (s16)(a + b);")):
        assert "(s32)(s16)" not in variante and "(s16)(s32)" not in variante


def test_un_destino_de_asignacion_compuesta_no_recibe_un_molde() -> None:
    sin_cambio(mut.cast_en_subexpresion, cuerpo("p->corto += a;"))


# --- ancho_de_variable_de_retorno ----------------------------------------------------------------------


def test_una_local_de_32_bits_del_retorno_pasa_a_16_si_solo_se_lee_truncada() -> None:
    texto = cuerpo("s32 r;", "r = g(a);", "p->corto = (s16)r;", "q->corto = r;")
    variantes = todas_las_variantes(mut.ancho_de_variable_de_retorno, texto)
    assert variantes == {
        cuerpo("s16 r;", "r = g(a);", "p->corto = (s16)r;", "q->corto = r;"),
        cuerpo("u16 r;", "r = g(a);", "p->corto = (s16)r;", "q->corto = r;"),
    }


def test_una_local_inicializada_con_la_llamada_tambien_pasa_a_16_bits() -> None:
    texto = cuerpo("u32 r = g(a);", "p->ancho = (u16)r;")
    assert cuerpo("s16 r = g(a);", "p->ancho = (u16)r;") in todas_las_variantes(
        mut.ancho_de_variable_de_retorno, texto
    )


def test_no_se_estrecha_si_alguna_lectura_usa_el_valor_completo() -> None:
    sin_cambio(mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);", "D_global = r;"))
    sin_cambio(mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);", "p->corto = (s32)r;"))
    sin_cambio(
        mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);", "if (r == 3) {", "    h(a);", "}")
    )


def test_no_se_estrecha_si_recibe_algo_que_no_es_una_llamada() -> None:
    sin_cambio(
        mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);", "r = b;", "p->corto = (s16)r;")
    )
    sin_cambio(
        mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);", "r += 1;", "p->corto = (s16)r;")
    )
    sin_cambio(mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "p->corto = (s16)r;"))


def test_no_se_estrecha_una_local_que_ya_es_estrecha_ni_sin_lecturas() -> None:
    sin_cambio(mut.ancho_de_variable_de_retorno, cuerpo("s16 r;", "r = g(a);", "p->corto = (s16)r;"))
    sin_cambio(mut.ancho_de_variable_de_retorno, cuerpo("s32 r;", "r = g(a);"))


# --- limite_en_local_antes_del_incremento --------------------------------------------------------------


def test_el_limite_de_un_do_se_lee_antes_del_avance() -> None:
    texto = cuerpo("do {", "    D_global = a;", "    a += 2;", "} while (a < D_otra);")
    _, resultado = aplicar(mut.limite_en_local_antes_del_incremento, texto)
    assert resultado == cuerpo(
        "s32 tmp1;", "do {", "    D_global = a;", "    tmp1 = D_otra;", "    a += 2;", "} while (a < tmp1);"
    )


def test_el_limite_puede_ser_un_campo_y_estar_a_cualquier_lado_de_la_comparacion() -> None:
    texto = cuerpo("do {", "    D_global = a;", "    a++;", "} while (m->escala > a);")
    _, resultado = aplicar(mut.limite_en_local_antes_del_incremento, texto)
    assert "tmp1 = m->escala;" in resultado and "while (tmp1 > a);" in resultado


def test_no_se_lee_antes_si_el_avance_escribe_el_limite() -> None:
    sin_cambio(
        mut.limite_en_local_antes_del_incremento,
        cuerpo("do {", "    m->escala += 1;", "} while (a < m->escala);"),
    )
    sin_cambio(
        mut.limite_en_local_antes_del_incremento, cuerpo("do {", "    a += 2;", "} while (a < a + D_otra);")
    )


def test_no_se_lee_antes_si_hay_continue_o_el_avance_no_es_lo_ultimo() -> None:
    sin_cambio(
        mut.limite_en_local_antes_del_incremento,
        cuerpo("do {", "    if (b) {", "        continue;", "    }", "    a += 2;", "} while (a < D_otra);"),
    )
    sin_cambio(
        mut.limite_en_local_antes_del_incremento,
        cuerpo("do {", "    a += 2;", "    g(b);", "} while (a < D_otra);"),
    )


def test_no_se_lee_antes_si_el_limite_es_una_local_o_una_constante() -> None:
    sin_cambio(mut.limite_en_local_antes_del_incremento, cuerpo("do {", "    a += 2;", "} while (a < b);"))
    sin_cambio(mut.limite_en_local_antes_del_incremento, cuerpo("do {", "    a += 2;", "} while (a < 10);"))
    sin_cambio(mut.limite_en_local_antes_del_incremento, cuerpo("do {", "    a += 2;", "} while (a);"))
    sin_cambio(mut.limite_en_local_antes_del_incremento, cuerpo("do {", "} while (a < D_otra);"))
    sin_cambio(mut.limite_en_local_antes_del_incremento, cuerpo("while (a < D_otra) {", "    a += 2;", "}"))


def test_no_se_lee_antes_si_el_otro_lado_no_usa_la_variable_avanzada() -> None:
    sin_cambio(
        mut.limite_en_local_antes_del_incremento, cuerpo("do {", "    a += 2;", "} while (b < D_otra);")
    )


def test_no_se_lee_antes_un_limite_de_tipo_desconocido() -> None:
    sin_cambio(
        mut.limite_en_local_antes_del_incremento,
        cuerpo("do {", "    a += 2;", "} while (a < desconocido->x);"),
    )


# --- copia_local_por_rama ------------------------------------------------------------------------------


def test_un_puntero_leido_en_una_rama_se_copia_al_principio() -> None:
    texto = cuerpo(
        "q->valor = 1;",
        "if (a) {",
        "    p->valor = 2;",
        "} else {",
        "    D_global = 5;",
        "}",
        "p->corto = 4;",
    )
    variantes = todas_las_variantes(mut.copia_local_por_rama, texto)
    assert (
        cuerpo(
            "Nodo* tmp1;",
            "tmp1 = p;",
            "q->valor = 1;",
            "if (a) {",
            "    tmp1->valor = 2;",
            "} else {",
            "    D_global = 5;",
            "}",
            "p->corto = 4;",
        )
        in variantes
    )


def test_la_copia_se_crea_justo_despues_de_la_ultima_asignacion_del_puntero() -> None:
    texto = cuerpo("p = q;", "D_otra = 1;", "if (a) {", "    p->valor = 2;", "}", "p->corto = 4;")
    _, resultado = aplicar(mut.copia_local_por_rama, texto)
    assert resultado == cuerpo(
        "Nodo* tmp1;",
        "p = q;",
        "tmp1 = p;",
        "D_otra = 1;",
        "if (a) {",
        "    tmp1->valor = 2;",
        "}",
        "p->corto = 4;",
    )


def test_la_copia_de_la_rama_else_tambien_se_reconoce() -> None:
    texto = cuerpo("if (a) {", "    D_global = 1;", "} else {", "    p->valor = 2;", "}", "p->corto = 4;")
    _, resultado = aplicar(mut.copia_local_por_rama, texto)
    assert "tmp1->valor = 2;" in resultado


def test_no_se_copia_un_puntero_escrito_en_la_rama_o_en_la_condicion() -> None:
    sin_cambio(
        mut.copia_local_por_rama,
        cuerpo("if (a) {", "    p->valor = 2;", "    p = q;", "}", "p->corto = 4;"),
    )
    sin_cambio(
        mut.copia_local_por_rama, cuerpo("if ((p = q) != 0) {", "    p->valor = 2;", "}", "p->corto = 4;")
    )


def test_no_se_copia_un_puntero_usado_solo_en_la_rama_ni_un_entero() -> None:
    sin_cambio(mut.copia_local_por_rama, cuerpo("if (a) {", "    p->valor = 2;", "}"))
    sin_cambio(mut.copia_local_por_rama, cuerpo("if (a) {", "    D_global = b;", "}", "D_otra = b;"))


def test_no_se_copia_con_una_etiqueta_entre_la_definicion_y_la_rama() -> None:
    sin_cambio(
        mut.copia_local_por_rama,
        cuerpo("fin:", "if (a) {", "    p->valor = 2;", "}", "p->corto = 4;"),
    )


def test_no_se_copia_un_puntero_con_la_direccion_tomada() -> None:
    sin_cambio(
        mut.copia_local_por_rama,
        cuerpo("g(&p);", "if (a) {", "    p->valor = 2;", "}", "p->corto = 4;"),
    )


def test_la_copia_cubre_un_if_dentro_de_un_bucle() -> None:
    texto = cuerpo(
        "while (a) {", "    if (b) {", "        p->valor = 2;", "    }", "    p->corto = 4;", "    a--;", "}"
    )
    _, resultado = aplicar(mut.copia_local_por_rama, texto)
    assert "tmp1 = p;" in resultado and "tmp1->valor = 2;" in resultado


def test_el_registro_incluye_las_mutaciones_nuevas_con_peso_positivo() -> None:
    registradas = {nombre: peso for nombre, _, peso in mut.MUTACIONES}
    nuevas = (
        "mover_sentencia_a_distancia",
        "envolver_en_bloque",
        "dividir_local_multiset",
        "expandir_local",
        "cadena_de_asignacion",
        "dividir_asignacion",
        "ajustar_desigualdad",
        "forma_de_acceso_a_struct",
        "cast_en_subexpresion",
        "ancho_de_variable_de_retorno",
        "limite_en_local_antes_del_incremento",
        "copia_local_por_rama",
    )
    assert all(registradas[nombre] > 0 for nombre in nuevas)
    assert len(registradas) == len(mut.MUTACIONES) == 40
