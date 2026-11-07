"""Reglas de negocio de las mutaciones de variables, bucles, copias, comas, medidas y direcciones.

Cada prueba fija CUANDO es legal aplicar la reformulacion (el programa resultante hace lo mismo) y
cuando no lo es: escritura intermedia, vida que se solapa, tipo que cambia un valor, uso fuera del
patron, variable con la direccion tomada o llamada opaca.
"""

from psxdecomp.permutador import mutaciones as mut

from permutador.ayudantes_mutaciones import aplicar, cuerpo, sin_cambio, todas_las_variantes

FIRMA_ENTEROS = "void f(s32* v, s32 a, s32 b)"

# --- bucle_por_indice: el puntero solo vale base + indice en ciertos puntos ----------------------------


def test_un_puntero_sobre_un_arreglo_local_o_un_entero_se_indexa_contra_el_arreglo() -> None:
    texto = cuerpo(
        "Nodo vec[4];",
        "s32 i;",
        "Nodo* r;",
        "r = vec + i;",
        "while (i < a) {",
        "    r->valor = 0;",
        "    r++;",
        "    i++;",
        "}",
    )
    _, resultado = aplicar(mut.bucle_por_indice, texto)
    assert "vec[i].valor = 0;" in resultado


def test_la_desreferencia_directa_del_puntero_se_convierte_en_elemento() -> None:
    texto = cuerpo(
        "s32 i;", "s32* r;", "r = v + i;", "while (i < a) {", "    *r = b;", "    r++;", "    i++;", "}",
        firma=FIRMA_ENTEROS,
    )  # fmt: skip
    _, resultado = aplicar(mut.bucle_por_indice, texto)
    assert resultado == cuerpo(
        "s32 i;", "while (i < a) {", "    v[i] = b;", "    i++;", "}", firma=FIRMA_ENTEROS
    )


def test_un_puntero_de_otro_tipo_que_la_base_no_se_sustituye() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;", "s32* r;", "r = p + i;", "while (i < a) {", "    *r = 0;", "    r++;", "    i++;", "}"
        ),
    )


def test_el_puntero_usado_en_el_inicio_del_for_impide_la_sustitucion() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo("s32 i;", "Nodo* r;", "r = p + i;", "for (i = r->valor; i < a; i++) {", "    r++;", "}"),
    )


def test_un_contador_que_no_es_entero_no_sirve_de_indice() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo("Nodo* r;", "r = p + q;", "while (a) {", "    r->valor = 0;", "    r++;", "    q++;", "}"),
    )


def test_si_el_bucle_reescribe_la_base_el_indice_no_equivale_al_puntero() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    r->valor = 0;",
            "    p = q;",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


def test_si_el_bucle_reasigna_el_contador_el_puntero_no_lo_sigue() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    r->valor = 0;",
            "    i = 0;",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


def test_un_bucle_con_continue_no_se_reescribe_porque_puede_saltarse_un_avance() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    if (b) {",
            "        continue;",
            "    }",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


def test_un_puntero_que_se_pasa_entero_a_una_expresion_no_se_sustituye() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    D_global = (s32)r;",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


def test_un_indice_que_depende_del_puntero_no_se_reescribe() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    D_global = r[r->valor].valor;",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


def test_sin_inicializacion_inmediata_o_con_inicializador_en_la_declaracion_no_hay_cambio() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo("s32 i;", "Nodo* r = q;", "r = p + i;", "while (i < a) {", "    r++;", "    i++;", "}"),
    )
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "D_global = 1;",
            "while (i < a) {",
            "    r++;",
            "    i++;",
            "}",
        ),
    )
    sin_cambio(mut.bucle_por_indice, cuerpo("while (a) {", "    a--;", "}"))


def test_un_contador_con_la_direccion_tomada_no_se_sigue() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "D_global = (s32)&i;",
            "while (i < a) {",
            "    r++;",
            "    i++;",
            "}",
        ),
    )


# --- duplicar_local_de_global --------------------------------------------------------------------------


def test_una_local_cuya_primera_mencion_no_es_la_lectura_del_global_no_se_duplica() -> None:
    sin_cambio(
        mut.duplicar_local_de_global,
        cuerpo("s32 j;", "j = a;", "D_otra = j;", "j = D_global;", "D_global = j;"),
    )


def test_la_local_leida_del_global_en_tres_tramos_se_duplica_en_algun_corte() -> None:
    texto = cuerpo(
        "s32 j;",
        "j = D_global;",
        "D_otra = j;",
        "j = D_global;",
        "D_otra = j;",
        "j = D_global;",
        "D_otra = j;",
    )
    variantes = todas_las_variantes(mut.duplicar_local_de_global, texto)
    assert len(variantes) == 2
    assert all("tmp1 = D_global;" in v for v in variantes)


def test_una_local_asignada_desde_otra_variable_local_no_cuenta_como_lectura_de_global() -> None:
    sin_cambio(
        mut.duplicar_local_de_global,
        cuerpo("s32 j;", "j = a;", "D_otra = j;", "j = a;", "D_global = j;"),
    )


# --- ancho_de_local_de_campo ---------------------------------------------------------------------------


def test_una_local_con_inicializador_que_solo_se_copia_a_16_bits_tambien_cambia() -> None:
    texto = cuerpo("s32 x = q->corto;", "p->corto = x;")
    variantes = todas_las_variantes(mut.ancho_de_local_de_campo, texto)
    assert cuerpo("s16 x = q->corto;", "p->corto = x;") in variantes


def test_una_local_que_se_modifica_con_asignacion_compuesta_conserva_su_ancho() -> None:
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("s32 x;", "x = q->corto;", "x += 1;", "p->corto = x;"))


def test_una_local_sin_lecturas_o_sin_escrituras_conserva_su_ancho() -> None:
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("s32 x;", "x = q->corto;"))
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("s32 x;", "p->corto = x;"))


def test_una_local_de_8_bits_o_de_puntero_no_entra_en_el_cambio() -> None:
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("u8 x;", "x = q->byte;", "p->byte = x;"))
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("Nodo* x;", "x = q;", "p->sig = x;"))


# --- encadenar_compuesta -------------------------------------------------------------------------------


def test_la_copia_no_vale_si_las_variables_tienen_distinto_tipo() -> None:
    sin_cambio(
        mut.encadenar_compuesta,
        cuerpo("u16 res;", "res = a;", "res = a + 1;", "D_global = res;"),
    )


def test_una_etiqueta_entre_la_copia_y_la_suma_anula_la_equivalencia() -> None:
    sin_cambio(
        mut.encadenar_compuesta,
        cuerpo("s32 res;", "res = a;", "inicio:", "res = a + 1;", "if (b) {", "    goto inicio;", "}"),
    )


def test_un_operador_que_no_tiene_forma_compuesta_o_un_destino_global_no_se_encadena() -> None:
    sin_cambio(mut.encadenar_compuesta, cuerpo("s32 res;", "res = a;", "res = a * 2;", "D_global = res;"))
    sin_cambio(mut.encadenar_compuesta, cuerpo("s32 res;", "res = a;", "D_global = a + 1;", "D_otra = res;"))


def test_el_operando_que_menciona_la_variable_de_destino_no_se_encadena() -> None:
    sin_cambio(mut.encadenar_compuesta, cuerpo("s32 res;", "res = a;", "res = a + res;", "D_global = res;"))


def test_una_variable_con_inicializador_en_la_declaracion_tambien_cuenta_como_copia() -> None:
    texto = cuerpo("s32 t = b;", "s32 res = a;", "res = a + 1;", "D_global = res + t;")
    _, resultado = aplicar(mut.encadenar_compuesta, texto)
    assert resultado == cuerpo("s32 t = b;", "s32 res = a;", "res += 1;", "D_global = res + t;")


def test_una_declaracion_con_inicializador_previa_no_crea_equivalencias_por_si_sola() -> None:
    sin_cambio(
        mut.encadenar_compuesta, cuerpo("s32 t = b;", "s32 res;", "res = a + 1;", "D_global = res + t;")
    )


# --- sustituir_por_alias -------------------------------------------------------------------------------


def test_reasignar_la_copia_anula_el_alias() -> None:
    sin_cambio(
        mut.sustituir_por_alias,
        cuerpo("Nodo* c;", "c = p;", "c = q;", "if (p == c->sig) {", "    D_global = 1;", "}"),
    )


def test_una_igualdad_que_escribe_una_de_las_dos_variables_no_se_sustituye() -> None:
    sin_cambio(
        mut.sustituir_por_alias,
        cuerpo("Nodo* c;", "c = p;", "D_global = (p = q) == c->sig;"),
    )


def test_una_etiqueta_previa_olvida_las_copias_conocidas() -> None:
    sin_cambio(
        mut.sustituir_por_alias,
        cuerpo("Nodo* c;", "c = p;", "inicio:", "if (p == c->sig) {", "    goto inicio;", "}"),
    )


# --- conmutar_coma -------------------------------------------------------------------------------------


def test_una_coma_con_una_llamada_no_se_conmuta() -> None:
    sin_cambio(mut.conmutar_coma, cuerpo("s32 i;", "s32 v;", "i++, v = foo(a);"))


def test_una_coma_sobre_variables_con_la_direccion_tomada_no_se_conmuta() -> None:
    sin_cambio(mut.conmutar_coma, cuerpo("s32 i;", "s32 v;", "D_global = (s32)&i;", "i++, v++;"))


def test_una_cadena_de_comas_conmuta_cada_nivel_si_sus_lados_son_independientes() -> None:
    texto = cuerpo("s32 i;", "s32 v;", "s32 w;", "i++, v++, w++;")
    assert len(todas_las_variantes(mut.conmutar_coma, texto)) == 2


# --- reasignar_medida ----------------------------------------------------------------------------------


def test_si_una_sentencia_cambia_lo_que_lee_la_medida_no_se_reasigna_ni_se_funde() -> None:
    sin_cambio(
        mut.reasignar_medida,
        cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "m->escala = 5;", "D_otra = med * b;"),
    )
    sin_cambio(
        mut.reasignar_medida,
        cuerpo(
            "s32 med;",
            "med = m->escala;",
            "m->escala = 5;",
            "D_global = med * a;",
            "med = m->escala;",
            "D_otra = med * b;",
        ),
    )


def test_una_medida_que_viene_de_una_llamada_no_se_repite() -> None:
    sin_cambio(
        mut.reasignar_medida,
        cuerpo("s32 med;", "med = foo(a);", "D_global = med * a;", "D_otra = med * b;"),
    )


def test_una_medida_usada_fuera_de_un_producto_no_se_reasigna() -> None:
    sin_cambio(
        mut.reasignar_medida,
        cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "D_otra = med + b;"),
    )


def test_una_medida_con_otra_escritura_no_se_reasigna() -> None:
    sin_cambio(
        mut.reasignar_medida,
        cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "med++;", "D_otra = med * b;"),
    )


def test_la_fusion_deja_la_primera_asignacion_con_varias_repeticiones() -> None:
    texto = cuerpo(
        "s32 med;",
        "med = m->escala;",
        "D_global = med * a;",
        "med = m->escala;",
        "D_otra = med * b;",
        "med = m->escala;",
        "a = med * 3;",
    )
    variantes = todas_las_variantes(mut.reasignar_medida, texto)
    assert (
        cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "D_otra = med * b;", "a = med * 3;")
        in variantes
    )


def test_una_declaracion_con_inicializador_no_forma_parte_de_una_fusion() -> None:
    texto = cuerpo("s32 med = m->escala;", "D_global = med * a;", "med = m->escala;", "D_otra = med * b;")
    assert all("med = m->escala;" in v for v in todas_las_variantes(mut.reasignar_medida, texto))


# --- unificar_locales ----------------------------------------------------------------------------------


def test_la_union_de_tipos_distintos_exige_que_los_valores_quepan_en_ambos() -> None:
    texto = cuerpo("s32 x;", "u8 y;", "x = a;", "D_global = x;", "y = 200;", "D_otra = y;")
    _, resultado = aplicar(mut.unificar_locales, texto)
    assert resultado == cuerpo("s32 x;", "x = a;", "D_global = x;", "x = 200;", "D_otra = x;")
    sin_cambio(
        mut.unificar_locales,
        cuerpo("s32 x;", "s8 y;", "x = a;", "D_global = x;", "y = 200;", "D_otra = y;"),
    )


# --- desplazar_avance ----------------------------------------------------------------------------------


def test_el_avance_no_cruza_una_llamada() -> None:
    sin_cambio(
        mut.desplazar_avance,
        cuerpo("s32 j;", "j++;", "foo(a);", "D_global = b;"),
    )


def test_el_avance_no_cruza_sentencias_que_leen_o_escriben_la_misma_variable() -> None:
    sin_cambio(mut.desplazar_avance, cuerpo("s32 j;", "j = a;", "D_global = j;", "j = b;"))


def test_el_alcance_del_desplazamiento_esta_acotado() -> None:
    cuerpos = ["j++;"] + [f"D_global = {n};" for n in range(12)]
    texto = cuerpo("s32 j;", *cuerpos)
    destinos = {len(v.splitlines()) for v in todas_las_variantes(mut.desplazar_avance, texto)}
    assert destinos == {len(texto.splitlines())}
    posiciones = {
        [linea.strip() for linea in v.splitlines()].index("j++;") - 3
        for v in todas_las_variantes(mut.desplazar_avance, texto)
    }
    assert posiciones <= set(range(2, 9))


def test_el_avance_de_una_variable_con_la_direccion_tomada_no_se_mueve() -> None:
    sin_cambio(
        mut.desplazar_avance,
        cuerpo("s32 j;", "D_global = (s32)&j;", "j++;", "D_otra = 1;", "D_global = 2;"),
    )


# --- izar_direccion ------------------------------------------------------------------------------------


def test_una_direccion_que_depende_de_un_parametro_escrito_no_se_iza() -> None:
    firma = "void f(u8* base)"
    sin_cambio(
        mut.izar_direccion,
        cuerpo("base = base + 4;", "D_global = ((Nodo*)(base + 40))->valor;", firma=firma),
    )


def test_una_direccion_que_lee_un_global_escalar_o_memoria_no_se_iza() -> None:
    sin_cambio(mut.izar_direccion, cuerpo("D_global = ((Nodo*)(D_otra + 4))->valor;"))
    sin_cambio(mut.izar_direccion, cuerpo("D_global = ((Nodo*)(p->byte))->valor;"))


def test_una_direccion_sobre_una_local_no_se_iza() -> None:
    sin_cambio(
        mut.izar_direccion,
        cuerpo("u8* base;", "base = (u8*)foo();", "D_global = ((Nodo*)(base + 4))->valor;"),
    )


# --- asignar_antes_del_bucle ---------------------------------------------------------------------------


def test_una_local_que_no_es_un_puntero_o_que_se_declara_fuera_del_cuerpo_no_cambia() -> None:
    sin_cambio(mut.asignar_antes_del_bucle, cuerpo("s32 t = 4;", "D_global = 1;", "D_otra = t;"))
    sin_cambio(
        mut.asignar_antes_del_bucle,
        cuerpo("if (a) {", "    Nodo* t = tabla;", "    D_global = 1;", "    D_otra = t->valor;", "}"),
    )


def test_el_acceso_directo_no_se_aplica_si_la_direccion_no_se_lee() -> None:
    sin_cambio(mut.asignar_antes_del_bucle, cuerpo("Nodo* t = tabla;", "D_global = 1;"))
    sin_cambio(mut.asignar_antes_del_bucle, cuerpo("Nodo* t;", "t = tabla;", "D_global = 1;"))


def test_la_direccion_asignada_con_un_comentario_o_un_parametro_no_se_sustituye() -> None:
    sin_cambio(
        mut.asignar_antes_del_bucle,
        cuerpo("Nodo* t = (Nodo*)a;", "D_global = 1;", "D_otra = t->valor;"),
    )
    sin_cambio(
        mut.asignar_antes_del_bucle,
        cuerpo("Nodo* t;", "D_global = 1;", "D_otra = t->valor;"),
    )
