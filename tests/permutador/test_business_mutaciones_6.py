"""Reglas de negocio: signo de la comparacion, suma reagrupada, recorte de bits, bucles y locales de rama."""

from psxdecomp.permutador import mutaciones as mut

from .ayudantes_mutaciones import aplicar, cuerpo, sin_cambio, todas_las_variantes

FIRMA_SIN_SIGNO = "void f(Nodo* p, Nodo* q, Mundo* m, s32 a, s32 b, u32 x, s16 h, s32* r)"


def con_firma(*lineas: str) -> str:
    """Una funcion ``f`` con parametros sin signo, estrechos y un puntero a entero."""
    return cuerpo(*lineas, firma=FIRMA_SIN_SIGNO)


# --- signo de la comparacion ----------------------------------------------------------------------------


def test_un_contador_sin_signo_comparado_con_una_constante_pequena_recibe_el_molde_con_signo() -> None:
    texto = con_firma("u32 i;", "i = a;", "while (i < 3) {", "    D_global = i;", "    i++;", "}")
    descripcion, resultado = aplicar(mut.signo_de_la_comparacion, texto)
    assert descripcion is not None
    assert descripcion.startswith("signo_de_la_comparacion(")
    assert "while ((s32)i < 3)" in resultado


def test_una_variable_con_signo_recibe_el_molde_sin_signo() -> None:
    _, resultado = aplicar(mut.signo_de_la_comparacion, con_firma("if (a >= 7) {", "    D_global = 1;", "}"))
    assert "if ((u32)a >= 7)" in resultado


def test_el_molde_existente_de_32_bits_se_quita() -> None:
    texto = con_firma("u32 i;", "i = a;", "while ((s32)i < 3) {", "    D_global = i;", "    i++;", "}")
    _, resultado = aplicar(mut.signo_de_la_comparacion, texto)
    assert "while (i < 3)" in resultado


def test_la_constante_a_la_izquierda_tambien_fija_el_signo_del_operando_de_la_derecha() -> None:
    _, resultado = aplicar(mut.signo_de_la_comparacion, con_firma("if (3 > x) {", "    D_global = 1;", "}"))
    assert "if (3 > (s32)x)" in resultado


def test_el_molde_se_aplica_en_la_condicion_de_cada_tipo_de_bucle() -> None:
    for lineas in (
        ("do {", "    a++;", "} while (a < 9);"),
        ("for (a = 0; a < 9; a++) {", "    D_global = a;", "}"),
    ):
        descripcion, _ = aplicar(mut.signo_de_la_comparacion, con_firma(*lineas))
        assert descripcion is not None


def test_una_comparacion_dentro_de_una_condicion_compuesta_tambien_se_considera() -> None:
    texto = con_firma("if (b != 0 && x < 4) {", "    D_global = 1;", "}")
    _, resultado = aplicar(mut.signo_de_la_comparacion, texto)
    assert "(s32)x < 4" in resultado


def test_el_molde_no_se_aplica_si_la_constante_llega_al_umbral_o_es_negativa() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (x < 32768) {", "    D_global = 1;", "}"))
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (x < -1) {", "    D_global = 1;", "}"))


def test_el_molde_no_se_aplica_si_el_otro_lado_no_es_constante() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (x < b) {", "    D_global = 1;", "}"))


def test_el_molde_no_se_aplica_a_igualdades_ni_fuera_de_una_condicion() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (x == 3) {", "    D_global = 1;", "}"))
    sin_cambio(mut.signo_de_la_comparacion, con_firma("a = x < 3;"))


def test_el_molde_no_se_aplica_a_operandos_que_no_son_de_32_bits() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (h < 3) {", "    D_global = 1;", "}"))
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (p->corto < 3) {", "    D_global = 1;", "}"))


def test_un_molde_de_otro_ancho_o_sobre_un_operando_estrecho_no_se_quita() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if ((u16)x < 3) {", "    D_global = 1;", "}"))
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if ((s32)h < 3) {", "    D_global = 1;", "}"))


def test_dos_constantes_no_reciben_molde() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("if (2 < 3) {", "    D_global = 1;", "}"))


def test_un_bucle_sin_condicion_no_tiene_comparacion_que_cambiar() -> None:
    sin_cambio(mut.signo_de_la_comparacion, con_firma("for (;;) {", "    break;", "}"))


# --- suma reagrupada ------------------------------------------------------------------------------------


def test_una_suma_de_tres_enteros_se_reagrupa_de_las_dos_formas_posibles() -> None:
    resultados = todas_las_variantes(mut.reagrupar_suma, cuerpo("D_global = a + b + D_otra;"))
    assert resultados == {
        cuerpo("D_global = a + (b + D_otra);"),
        cuerpo("D_global = a + D_otra + b;"),
    }


def test_una_suma_con_el_parentesis_a_la_derecha_vuelve_a_las_otras_dos_agrupaciones() -> None:
    resultados = todas_las_variantes(mut.reagrupar_suma, cuerpo("D_global = a + (b + D_otra);"))
    assert resultados == {cuerpo("D_global = a + b + D_otra;"), cuerpo("D_global = a + D_otra + b;")}


def test_el_unico_puntero_queda_siempre_fuera_del_parentesis_interior() -> None:
    resultados = todas_las_variantes(mut.reagrupar_suma, cuerpo("q = p + a + b;"))
    assert resultados == {cuerpo("q = p + (a + b);")}


def test_un_puntero_en_medio_solo_permite_la_agrupacion_que_lo_deja_fuera() -> None:
    resultados = todas_las_variantes(mut.reagrupar_suma, cuerpo("q = a + p + b;"))
    assert resultados == {cuerpo("q = a + b + p;")}


def test_una_suma_con_dos_punteros_no_se_reagrupa() -> None:
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = p + q + a;"))


def test_una_suma_con_un_sumando_de_tipo_desconocido_o_un_arreglo_no_se_reagrupa() -> None:
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a + Z + b;"))
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = tabla + a + b;"))


def test_una_suma_con_efectos_no_se_reagrupa() -> None:
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a + g(b) + b;"))
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a + b++ + b;"))


def test_solo_se_reagrupan_las_sumas_de_tres_terminos() -> None:
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a + b;"))
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a - b + b;"))
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = a * b * b;"))


def test_los_sumandos_estrechos_se_reagrupan_como_enteros() -> None:
    descripcion, _ = aplicar(mut.reagrupar_suma, cuerpo("D_global = p->corto + p->byte + b;"))
    assert descripcion is not None


def test_una_suma_usada_como_destino_de_una_direccion_no_se_reagrupa() -> None:
    sin_cambio(mut.reagrupar_suma, cuerpo("D_global = *(&a);"))


# --- recorte de bits altos ------------------------------------------------------------------------------


def test_dos_desplazamientos_de_un_valor_sin_signo_pasan_a_una_mascara() -> None:
    _, resultado = aplicar(mut.recorte_de_bits_altos, con_firma("a = (x << 8) >> 8;"))
    assert "a = x & 0xFFFFFF;" in resultado


def test_la_mascara_depende_de_la_cantidad_desplazada() -> None:
    _, resultado = aplicar(mut.recorte_de_bits_altos, con_firma("a = (x << 1) >> 1;"))
    assert "a = x & 0x7FFFFFFF;" in resultado
    _, resultado = aplicar(mut.recorte_de_bits_altos, con_firma("a = (x << 31) >> 31;"))
    assert "a = x & 0x1;" in resultado


def test_una_mascara_de_bits_bajos_pasa_a_dos_desplazamientos() -> None:
    _, resultado = aplicar(mut.recorte_de_bits_altos, con_firma("a = x & 0xFFFF;"))
    assert "a = (x << 16) >> 16;" in resultado


def test_la_mascara_a_la_izquierda_tambien_pasa_a_dos_desplazamientos() -> None:
    _, resultado = aplicar(mut.recorte_de_bits_altos, con_firma("a = 0xFF & x;"))
    assert "a = (x << 24) >> 24;" in resultado


def test_la_ida_y_la_vuelta_del_recorte_devuelven_el_mismo_valor() -> None:
    _, mascara = aplicar(mut.recorte_de_bits_altos, con_firma("a = (x << 12) >> 12;"))
    _, desplazamientos = aplicar(mut.recorte_de_bits_altos, mascara)
    assert desplazamientos == con_firma("a = (x << 12) >> 12;")


def test_un_operando_con_signo_no_se_recorta_porque_el_desplazamiento_extiende_el_signo() -> None:
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (b << 8) >> 8;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = b & 0xFF;"))


def test_una_constante_que_no_es_una_mascara_de_bits_bajos_no_se_toca() -> None:
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = x & 0xFE;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = x & 0;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = x & 0xFFFFFFFF;"))


def test_los_desplazamientos_desiguales_o_fuera_de_rango_no_se_tocan() -> None:
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x << 8) >> 16;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x << 0) >> 0;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x << 32) >> 32;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x >> 8) >> 8;"))
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x << b) >> b;"))


def test_un_operando_con_efectos_no_se_recorta() -> None:
    sin_cambio(mut.recorte_de_bits_altos, con_firma("a = (x++ << 8) >> 8;"))


def test_el_molde_de_signo_dentro_del_recorte_se_alterna_como_cambio_de_forma() -> None:
    texto = con_firma("a = (s16)(((s32)x << 16) >> 16);")
    _, resultado = aplicar(mut.recorte_de_bits_altos, texto)
    assert "((u32)x << 16) >> 16" in resultado
    _, vuelta = aplicar(mut.recorte_de_bits_altos, resultado)
    assert vuelta in {texto, con_firma("a = (s16)((u32)x & 0xFFFF);")}


def test_un_recorte_con_molde_sin_signo_ofrece_la_mascara_y_el_molde_con_signo() -> None:
    texto = con_firma("a = ((u32)x << 8) >> 8;")
    variantes = todas_las_variantes(mut.recorte_de_bits_altos, texto)
    assert con_firma("a = (u32)x & 0xFFFFFF;") in variantes
    assert con_firma("a = ((s32)x << 8) >> 8;") in variantes


def test_el_recorte_nunca_parte_la_operacion_en_dos_sentencias() -> None:
    for linea in ("a = (x << 8) >> 8;", "a = x & 0xFFFF;", "a = (s16)(((s32)x << 16) >> 16);"):
        for resultado in todas_las_variantes(mut.recorte_de_bits_altos, con_firma(linea)):
            assert resultado.count(";") == con_firma(linea).count(";")


# --- bucle do-while y while -----------------------------------------------------------------------------

DO_CON_GUARDA = (
    "if (a < 5) {",
    "    do {",
    "        D_global = a;",
    "        a += 1;",
    "    } while (a < 5);",
    "}",
)
MIENTRAS = ("while (a < 5) {", "    D_global = a;", "    a += 1;", "}")


def test_un_do_con_su_propia_guarda_pasa_a_while() -> None:
    descripcion, resultado = aplicar(mut.bucle_do_while_y_while, cuerpo(*DO_CON_GUARDA))
    assert descripcion == "bucle_do_while_y_while(a < 5, a_mientras)"
    assert resultado == cuerpo(*MIENTRAS)


def test_un_while_pasa_a_do_con_su_propia_guarda() -> None:
    descripcion, resultado = aplicar(mut.bucle_do_while_y_while, cuerpo(*MIENTRAS))
    assert descripcion == "bucle_do_while_y_while(a < 5, a_guarda)"
    assert resultado == cuerpo(*DO_CON_GUARDA)


def test_la_ida_y_la_vuelta_del_bucle_devuelven_el_mismo_c() -> None:
    _, ida = aplicar(mut.bucle_do_while_y_while, cuerpo(*DO_CON_GUARDA))
    _, vuelta = aplicar(mut.bucle_do_while_y_while, ida)
    assert vuelta == cuerpo(*DO_CON_GUARDA)


def test_un_do_sin_guarda_no_se_convierte_porque_entra_una_vez_aunque_la_condicion_sea_falsa() -> None:
    sin_cambio(mut.bucle_do_while_y_while, cuerpo("do {", "    a += 1;", "} while (a < 5);"))


def test_una_guarda_con_otra_condicion_no_basta() -> None:
    texto = cuerpo("if (a < 6) {", "    do {", "        a += 1;", "    } while (a < 5);", "}")
    sin_cambio(mut.bucle_do_while_y_while, texto)


def test_una_guarda_con_rama_else_o_con_mas_sentencias_no_basta() -> None:
    con_else = cuerpo(
        "if (a < 5) {", "    do {", "        a += 1;", "    } while (a < 5);", "} else {", "    b = 1;", "}"
    )
    sin_cambio(mut.bucle_do_while_y_while, con_else)
    con_mas = cuerpo("if (a < 5) {", "    b = 1;", "    do {", "        a += 1;", "    } while (a < 5);", "}")
    sin_cambio(mut.bucle_do_while_y_while, con_mas)


def test_una_guarda_cuyo_cuerpo_no_es_un_do_no_se_convierte() -> None:
    sin_cambio(mut.bucle_do_while_y_while, cuerpo("if (a < 5) {", "    b = 1;", "}"))


def test_una_condicion_con_efectos_no_se_convierte_en_ninguno_de_los_dos_sentidos() -> None:
    sin_cambio(mut.bucle_do_while_y_while, cuerpo("while (g(a)) {", "    b = 1;", "}"))
    texto = cuerpo("if (a++ < 5) {", "    do {", "        b = 1;", "    } while (a++ < 5);", "}")
    sin_cambio(mut.bucle_do_while_y_while, texto)


def test_los_comentarios_del_do_o_del_final_de_la_guarda_impiden_perderlos() -> None:
    con_comentario = cuerpo(
        "if (a < 5) {", "    /* avance */", "    do {", "        a += 1;", "    } while (a < 5);", "}"
    )
    sin_cambio(mut.bucle_do_while_y_while, con_comentario)
    con_final = cuerpo(
        "if (a < 5) {", "    do {", "        a += 1;", "    } while (a < 5);", "    /* fin */", "}"
    )
    sin_cambio(mut.bucle_do_while_y_while, con_final)


def test_los_comentarios_de_la_guarda_pasan_al_while_y_los_del_while_a_la_guarda() -> None:
    _, resultado = aplicar(
        mut.bucle_do_while_y_while,
        cuerpo("/* busca */", "if (a < 5) {", "    do {", "        a += 1;", "    } while (a < 5);", "}"),
    )
    assert "/* busca */\n    while (a < 5)" in resultado
    _, vuelta = aplicar(
        mut.bucle_do_while_y_while,
        cuerpo("/* busca */", "while (a < 5) {", "    a += 1;", "}"),
    )
    assert "/* busca */\n    if (a < 5)" in vuelta


# --- variable intermedia entre ramas --------------------------------------------------------------------

DOS_RAMAS = (
    "s32 t;",
    "t = a * b;",
    "if (D_global) {",
    "    p->valor = t >> 11;",
    "} else {",
    "    q->valor = t >> 11;",
    "}",
)


def test_la_local_que_solo_usan_las_dos_ramas_se_sustituye_por_su_expresion_en_cada_una() -> None:
    descripcion, resultado = aplicar(mut.quitar_variable_intermedia_en_ramas, cuerpo(*DOS_RAMAS))
    assert descripcion == "quitar_variable_intermedia_en_ramas(t = a * b)"
    assert resultado == cuerpo(
        "if (D_global) {", "    p->valor = a * b >> 11;", "} else {", "    q->valor = a * b >> 11;", "}"
    )


def test_una_rama_que_usa_la_local_dos_veces_no_se_sustituye() -> None:
    texto = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    p->valor = t >> 11;",
        "    p->clave = t;",
        "} else {",
        "    q->valor = t >> 11;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_una_local_usada_solo_en_una_rama_o_tambien_despues_no_se_sustituye() -> None:
    una_rama = cuerpo(
        "s32 t;", "t = a * b;", "if (D_global) {", "    p->valor = t;", "} else {", "    q->valor = 1;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, una_rama)
    con_uso_posterior = cuerpo(*DOS_RAMAS, "D_otra = t;")
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, con_uso_posterior)


def test_sin_rama_else_no_hay_una_lectura_por_rama() -> None:
    texto = cuerpo("s32 t;", "t = a * b;", "if (D_global) {", "    p->valor = t;", "}", "D_otra = 1;")
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_un_valor_con_efectos_o_una_local_con_inicializador_no_se_sustituye() -> None:
    con_llamada = cuerpo(
        "s32 t;", "t = g(a);", "if (D_global) {", "    p->valor = t;", "} else {", "    q->valor = t;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, con_llamada)
    con_inicial = cuerpo(
        "s32 t = a * b;", "if (D_global) {", "    p->valor = t;", "} else {", "    q->valor = t;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, con_inicial)


def test_una_local_que_no_conserva_el_valor_de_la_expresion_no_se_sustituye() -> None:
    texto = cuerpo(
        "s16 t;", "t = a * b;", "if (D_global) {", "    p->valor = t;", "} else {", "    q->valor = t;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_un_parametro_o_una_global_no_se_trata_como_variable_intermedia() -> None:
    parametro = cuerpo(
        "a = b * 2;", "if (D_global) {", "    p->valor = a;", "} else {", "    q->valor = a;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, parametro)
    global_ = cuerpo(
        "D_otra = b * 2;",
        "if (D_global) {",
        "    p->valor = D_otra;",
        "} else {",
        "    q->valor = D_otra;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, global_)


def test_la_condicion_que_escribe_un_operando_impide_calcular_el_valor_mas_tarde() -> None:
    texto = cuerpo(
        "s32 t;", "t = a * b;", "if (a++) {", "    p->valor = t;", "} else {", "    q->valor = t;", "}"
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_una_sentencia_de_la_rama_que_escribe_un_operando_antes_del_uso_impide_la_sustitucion() -> None:
    texto = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    a = 3;",
        "    p->valor = t;",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_la_escritura_posterior_al_uso_no_impide_la_sustitucion() -> None:
    texto = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    p->valor = t;",
        "    a = 3;",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    descripcion, _ = aplicar(mut.quitar_variable_intermedia_en_ramas, texto)
    assert descripcion is not None


def test_un_uso_condicional_anidado_o_en_la_condicion_de_un_bucle_no_se_sustituye() -> None:
    perezoso = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    p->valor = b && t;",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, perezoso)
    anidado = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    if (b) {",
        "        p->valor = t;",
        "    }",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, anidado)
    en_bucle = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    while (t > 0) {",
        "        b = 1;",
        "    }",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, en_bucle)


def test_un_uso_en_una_sentencia_con_dos_asignaciones_no_se_sustituye() -> None:
    texto = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    p->valor = (q->valor = 2) + t;",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


def test_la_local_escrita_dos_veces_no_se_sustituye() -> None:
    texto = cuerpo(
        "s32 t;",
        "t = a * b;",
        "if (D_global) {",
        "    t = 1;",
        "    p->valor = t;",
        "} else {",
        "    q->valor = t;",
        "}",
    )
    sin_cambio(mut.quitar_variable_intermedia_en_ramas, texto)


# --- lectura guardada antes de un almacen ---------------------------------------------------------------

DOS_ALMACENES = ("q->clave = 4;", "p->valor = 3;", "D_global = D_otra;")


def test_la_lectura_de_una_global_se_guarda_en_una_local_nueva_antes_de_un_almacen() -> None:
    resultados = todas_las_variantes(mut.guardar_lectura_antes_del_almacen, cuerpo(*DOS_ALMACENES))
    assert resultados == {
        cuerpo("s32 tmp1;", "q->clave = 4;", "tmp1 = D_otra;", "p->valor = 3;", "D_global = tmp1;"),
        cuerpo("s32 tmp1;", "tmp1 = D_otra;", "q->clave = 4;", "p->valor = 3;", "D_global = tmp1;"),
    }


def test_la_lectura_de_un_campo_se_guarda_si_el_almacen_es_de_otro_campo() -> None:
    texto = cuerpo("q->clave = 4;", "D_global = p->valor;")
    descripcion, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert descripcion is not None
    assert resultado == cuerpo("s32 tmp1;", "tmp1 = p->valor;", "q->clave = 4;", "D_global = tmp1;")


def test_la_lectura_se_guarda_en_una_local_existente_libre_del_mismo_tipo() -> None:
    texto = cuerpo("s32 w;", "q->clave = 4;", "D_global = D_otra;", "w = a;", "D_otra = w;")
    descripcion, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert descripcion == "guardar_lectura_antes_del_almacen(s32 w = D_otra, 1 antes)"
    assert resultado == cuerpo(
        "s32 w;", "w = D_otra;", "q->clave = 4;", "D_global = w;", "w = a;", "D_otra = w;"
    )


def test_una_local_que_se_usa_antes_del_tramo_no_esta_libre() -> None:
    texto = cuerpo("s32 w;", "w = a;", "D_otra = w;", "q->clave = 4;", "D_global = D_otra;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert "s32 tmp1;" in resultado
    assert "w = D_otra;" not in resultado


def test_una_local_que_se_lee_despues_sin_asignarla_antes_no_esta_libre() -> None:
    texto = cuerpo("s32 w;", "q->clave = 4;", "D_global = D_otra;", "D_otra = w;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert "s32 tmp1;" in resultado


def test_una_local_mencionada_dentro_del_tramo_no_esta_libre() -> None:
    texto = cuerpo("s32 w;", "q->clave = 4;", "w = 1;", "D_global = D_otra + w;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert "s32 tmp1;" in resultado


def test_una_local_de_otro_tipo_o_con_inicializador_no_esta_libre() -> None:
    otro_tipo = cuerpo("s16 w;", "q->clave = 4;", "D_global = D_otra;", "w = a;", "D_otra = w;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, otro_tipo)
    assert "s32 tmp1;" in resultado
    con_inicial = cuerpo("s32 w = 5;", "q->clave = 4;", "D_global = D_otra;", "D_otra = w;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, con_inicial)
    assert "s32 tmp1;" in resultado


def test_una_local_sin_ningun_uso_esta_libre() -> None:
    texto = cuerpo("s32 w;", "q->clave = 4;", "D_global = D_otra;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, texto)
    assert resultado == cuerpo("s32 w;", "w = D_otra;", "q->clave = 4;", "D_global = w;")


def test_un_almacen_que_puede_escribir_lo_leido_impide_guardar_la_lectura() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("p->valor = 3;", "D_global = p->valor;"))
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("D_otra = 3;", "D_global = D_otra;"))


def test_una_lectura_por_puntero_opaco_no_sube_sobre_un_almacen_a_memoria() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, con_firma("p->valor = 3;", "D_global = *r;"))


def test_una_llamada_o_un_return_entre_el_almacen_y_el_uso_impide_guardar_la_lectura() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("q->clave = 4;", "g(a);", "D_global = D_otra;"))
    sin_cambio(
        mut.guardar_lectura_antes_del_almacen,
        cuerpo("q->clave = 4;", "if (b) {", "    return;", "}", "D_global = D_otra;"),
    )


def test_sin_almacen_previo_no_hay_donde_guardar_la_lectura() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("a = 3;", "D_global = D_otra;"))
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("D_global = D_otra;"))


def test_una_lectura_condicional_o_con_efectos_no_se_guarda() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("q->clave = 4;", "D_global = a && D_otra;"))
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("q->clave = 4;", "D_global = D_otra + g(a);"))


def test_una_variable_local_no_es_una_lectura_que_guardar() -> None:
    sin_cambio(mut.guardar_lectura_antes_del_almacen, cuerpo("q->clave = 4;", "D_global = a;"))


def test_la_lectura_que_se_guarda_no_crea_una_operacion_partida() -> None:
    funcion_base = cuerpo("q->clave = 4;", "D_global = D_otra;")
    _, resultado = aplicar(mut.guardar_lectura_antes_del_almacen, funcion_base)
    assert resultado.count("tmp1") == 3


# --- entregables que las mutaciones existentes ya cubren --------------------------------------------------


def test_la_asignacion_compuesta_existente_cubre_la_forma_x_igual_x_mas_e_y_su_inversa() -> None:
    resultados = todas_las_variantes(mut.asignacion_compuesta, cuerpo("p->valor = p->valor + a;"))
    assert resultados == {cuerpo("p->valor += a;")}
    resultados = todas_las_variantes(mut.asignacion_compuesta, cuerpo("p->valor += a;"))
    assert resultados == {cuerpo("p->valor = p->valor + a;")}
    resultados = todas_las_variantes(mut.asignacion_compuesta, cuerpo("a = b | a;"))
    assert resultados == {cuerpo("a |= b;")}
    sin_cambio(mut.asignacion_compuesta, cuerpo("a = a + g(b);"))


def test_operandos_conmutados_existente_cubre_la_comparacion_con_el_operador_reflejado() -> None:
    resultados = todas_las_variantes(
        mut.operandos_conmutados, cuerpo("if (a <= b) {", "    D_global = 1;", "}")
    )
    assert resultados == {cuerpo("if (b >= a) {", "    D_global = 1;", "}")}
    resultados = todas_las_variantes(
        mut.operandos_conmutados, cuerpo("if (a == b) {", "    D_global = 1;", "}")
    )
    assert resultados == {cuerpo("if (b == a) {", "    D_global = 1;", "}")}
    sin_cambio(mut.operandos_conmutados, cuerpo("if (a < g(b)) {", "    D_global = 1;", "}"))
