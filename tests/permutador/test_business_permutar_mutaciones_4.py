"""Pruebas de las mutaciones que usan copias vigentes, comas, medidas, avances y direcciones.

Cada una: transformacion exacta, caso seguro en que no se aplica (arbol intacto) y ida y vuelta del C.
"""

from psxdecomp.permutador import mutaciones as mut

from permutador.ayudantes_mutaciones import aplicar, cuerpo, sin_cambio, todas_las_variantes

# --- encadenar_compuesta -------------------------------------------------------------------------------


def test_la_suma_sobre_una_copia_vigente_pasa_a_asignacion_compuesta() -> None:
    texto = cuerpo("s32 reg;", "s32 res;", "reg = a;", "res = reg;", "res = reg + 1;", "reg = res;")
    descripcion, resultado = aplicar(mut.encadenar_compuesta, texto)
    assert descripcion == "encadenar_compuesta(res = reg + 1)"
    assert resultado == cuerpo("s32 reg;", "s32 res;", "reg = a;", "res = reg;", "res += 1;", "reg = res;")


def test_el_operando_conmutativo_a_la_izquierda_tambien_se_encadena() -> None:
    texto = cuerpo("s32 res;", "res = a;", "res = b | a;")
    _, resultado = aplicar(mut.encadenar_compuesta, texto)
    assert resultado == cuerpo("s32 res;", "res = a;", "res |= b;")


def test_una_copia_a_traves_de_otra_variable_tambien_vale() -> None:
    texto = cuerpo("s32 t;", "s32 res;", "t = a;", "res = t;", "res = a - 4;")
    _, resultado = aplicar(mut.encadenar_compuesta, texto)
    assert resultado == cuerpo("s32 t;", "s32 res;", "t = a;", "res = t;", "res -= 4;")


def test_sin_copia_previa_la_suma_no_se_encadena() -> None:
    sin_cambio(mut.encadenar_compuesta, cuerpo("s32 res;", "res = a + 1;", "D_global = res;"))


def test_una_escritura_intermedia_de_la_fuente_anula_la_copia() -> None:
    sin_cambio(
        mut.encadenar_compuesta,
        cuerpo("s32 res;", "res = a;", "a = b;", "res = a + 1;", "D_global = res;"),
    )


# --- sustituir_por_alias -------------------------------------------------------------------------------


def test_el_operando_de_una_igualdad_se_cambia_por_su_copia() -> None:
    texto = cuerpo("Nodo* c;", "c = p;", "if (p == c->sig) {", "    D_global = 1;", "}")
    descripcion, resultado = aplicar(mut.sustituir_por_alias, texto)
    assert descripcion == "sustituir_por_alias(p por c)"
    assert resultado == cuerpo("Nodo* c;", "c = p;", "if (c == c->sig) {", "    D_global = 1;", "}")


def test_una_desigualdad_en_una_sentencia_de_expresion_tambien_se_sustituye() -> None:
    texto = cuerpo("Nodo* c;", "c = p;", "D_global = c != q->sig;")
    variantes = todas_las_variantes(mut.sustituir_por_alias, texto)
    assert cuerpo("Nodo* c;", "c = p;", "D_global = p != q->sig;") in variantes


def test_sin_una_copia_vigente_la_igualdad_no_cambia() -> None:
    sin_cambio(mut.sustituir_por_alias, cuerpo("Nodo* c;", "if (p == c->sig) {", "    D_global = 1;", "}"))


def test_la_igualdad_entre_las_dos_copias_no_se_vuelve_trivial() -> None:
    sin_cambio(mut.sustituir_por_alias, cuerpo("Nodo* c;", "c = p;", "D_global = p == c;"))


def test_la_condicion_de_un_bucle_no_se_sustituye_por_un_alias() -> None:
    sin_cambio(
        mut.sustituir_por_alias,
        cuerpo("Nodo* c;", "c = p;", "while (p == c->sig) {", "    c = q;", "}"),
    )


# --- conmutar_coma -------------------------------------------------------------------------------------


def test_los_incrementos_de_una_coma_se_intercambian() -> None:
    texto = cuerpo("s32 i;", "s32 v;", "i++, v++;")
    descripcion, resultado = aplicar(mut.conmutar_coma, texto)
    assert descripcion == "conmutar_coma(i++, v++)"
    assert resultado == cuerpo("s32 i;", "s32 v;", "v++, i++;")


def test_el_inicio_y_el_paso_de_un_for_tambien_conmutan() -> None:
    texto = cuerpo("s32 i;", "s32 v;", "for (i = 0, v = 1; i < a; i++, v++) {", "    D_global = i;", "}")
    variantes = todas_las_variantes(mut.conmutar_coma, texto)
    assert (
        cuerpo("s32 i;", "s32 v;", "for (v = 1, i = 0; i < a; i++, v++) {", "    D_global = i;", "}")
        in variantes
    )
    assert (
        cuerpo("s32 i;", "s32 v;", "for (i = 0, v = 1; i < a; v++, i++) {", "    D_global = i;", "}")
        in variantes
    )


def test_una_coma_con_lados_dependientes_no_se_conmuta() -> None:
    sin_cambio(mut.conmutar_coma, cuerpo("s32 i;", "s32 v;", "i = 1, v = i;"))


def test_un_for_sin_inicio_ni_paso_y_una_sentencia_sin_coma_no_tienen_nada_que_conmutar() -> None:
    sin_cambio(mut.conmutar_coma, cuerpo("for (; a < b;) {", "    a++;", "}"))


# --- reasignar_medida ----------------------------------------------------------------------------------


def test_la_medida_se_reasigna_antes_de_cada_producto_posterior() -> None:
    texto = cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "D_otra = med * b;")
    descripcion, resultado = aplicar(mut.reasignar_medida, texto)
    assert descripcion == "reasignar_medida(med = m->escala, 1 reasignaciones)"
    assert resultado == cuerpo(
        "s32 med;", "med = m->escala;", "D_global = med * a;", "med = m->escala;", "D_otra = med * b;"
    )


def test_la_medida_con_inicializador_tambien_se_reasigna() -> None:
    texto = cuerpo("s32 med = m->escala;", "D_global = med * a;", "D_otra = med * b;", "a = med * 2;")
    _, resultado = aplicar(mut.reasignar_medida, texto)
    assert resultado == cuerpo(
        "s32 med = m->escala;",
        "D_global = med * a;",
        "med = m->escala;",
        "D_otra = med * b;",
        "med = m->escala;",
        "a = med * 2;",
    )


def test_las_reasignaciones_iguales_se_funden_en_la_primera() -> None:
    texto = cuerpo(
        "s32 med;",
        "med = m->escala;",
        "D_global = med * a;",
        "med = m->escala;",
        "D_otra = med * b;",
    )
    descripcion, resultado = aplicar(mut.reasignar_medida, texto)
    assert descripcion == "reasignar_medida(med = m->escala, fundidas 1)"
    assert resultado == cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "D_otra = med * b;")


def test_una_medida_usada_en_una_sola_sentencia_no_se_reasigna() -> None:
    sin_cambio(
        mut.reasignar_medida, cuerpo("s32 med;", "med = m->escala;", "D_global = med * a;", "D_otra = b;")
    )


# --- unificar_locales con tipos enteros distintos ------------------------------------------------------


def test_una_local_estrecha_se_funde_en_una_local_de_32_bits() -> None:
    texto = cuerpo("s32 x;", "u16 y;", "x = a;", "D_global = x;", "y = 3;", "D_otra = y;")
    descripcion, resultado = aplicar(mut.unificar_locales, texto)
    assert descripcion == "unificar_locales(y en x)"
    assert resultado == cuerpo("s32 x;", "x = a;", "D_global = x;", "x = 3;", "D_otra = x;")


def test_una_local_ancha_no_se_funde_en_una_estrecha() -> None:
    sin_cambio(
        mut.unificar_locales,
        cuerpo("u16 x;", "s32 y;", "x = 3;", "D_global = x;", "y = 4;", "D_otra = y;"),
    )


def test_la_local_estrecha_con_un_valor_que_no_cabe_no_se_funde() -> None:
    sin_cambio(
        mut.unificar_locales,
        cuerpo("s32 x;", "u16 y;", "x = a;", "D_global = x;", "y = a;", "D_otra = y;"),
    )


def test_la_local_estrecha_que_se_incrementa_no_se_funde() -> None:
    sin_cambio(
        mut.unificar_locales,
        cuerpo("s32 x;", "u16 y;", "x = a;", "D_global = x;", "y = 1;", "y++;", "D_otra = y;"),
    )


def test_tipos_con_distinta_promocion_o_no_enteros_no_se_funden() -> None:
    sin_cambio(
        mut.unificar_locales,
        cuerpo("u32 x;", "u16 y;", "x = a;", "D_global = x;", "y = 3;", "D_otra = y;"),
    )
    sin_cambio(
        mut.unificar_locales,
        cuerpo("Nodo* x;", "s32 y;", "x = p;", "D_global = x->valor;", "y = 3;", "D_otra = y;"),
    )


# --- desplazar_avance ----------------------------------------------------------------------------------


def test_el_avance_cruza_dos_sentencias_independientes() -> None:
    texto = cuerpo("s32 j;", "s32 e;", "s32 s;", "s = a + 8;", "j++;", "e++;", "D_global = j + e;")
    variantes = todas_las_variantes(mut.desplazar_avance, texto)
    assert (
        cuerpo("s32 j;", "s32 e;", "s32 s;", "e++;", "s = a + 8;", "j++;", "D_global = j + e;") in variantes
    )


def test_la_sentencia_no_cruza_una_vecina_que_la_usa() -> None:
    sin_cambio(
        mut.desplazar_avance,
        cuerpo("s32 j;", "j++;", "D_global = j;", "D_otra = b;"),
    )


def test_una_escritura_a_memoria_o_a_un_global_no_es_un_avance() -> None:
    sin_cambio(mut.desplazar_avance, cuerpo("p->valor = 1;", "D_global++;", "D_otra = 1;"))


# --- izar_direccion ------------------------------------------------------------------------------------


def test_la_direccion_fija_se_calcula_una_vez_al_principio_del_cuerpo() -> None:
    firma = "void f(u8* base)"
    texto = cuerpo("D_global = 1;", "D_otra = ((Nodo*)(base + 40))->valor;", firma=firma)
    descripcion, resultado = aplicar(mut.izar_direccion, texto)
    assert descripcion == "izar_direccion(Nodo* tmp1 = (Nodo*)(base + 40))"
    assert resultado == cuerpo(
        "Nodo* tmp1;", "tmp1 = (Nodo*)(base + 40);", "D_global = 1;", "D_otra = tmp1->valor;", firma=firma
    )


def test_la_direccion_de_un_simbolo_y_la_resta_tambien_se_izan() -> None:
    texto = cuerpo("D_global = ((Nodo*)(&tabla - 4))->valor;", "D_otra = ((u8*)tabla)[0];")
    variantes = todas_las_variantes(mut.izar_direccion, texto)
    assert any("Nodo* tmp1;" in v and "tmp1 = (Nodo*)(&tabla - 4);" in v for v in variantes)
    assert any("u8* tmp1;" in v for v in variantes)


def test_una_conversion_a_entero_no_se_iza() -> None:
    sin_cambio(mut.izar_direccion, cuerpo("D_global = (s32)tabla;"))


# --- asignar_antes_del_bucle ---------------------------------------------------------------------------


def test_la_tabla_se_asigna_justo_antes_del_primer_uso() -> None:
    texto = cuerpo(
        "Nodo* t = tabla;",
        "s32 i;",
        "D_global = 1;",
        "for (i = 0; i < a; i++) {",
        "    t[i].valor = i;",
        "}",
    )
    variantes = todas_las_variantes(mut.asignar_antes_del_bucle, texto)
    assert (
        cuerpo(
            "Nodo* t;",
            "s32 i;",
            "D_global = 1;",
            "t = tabla;",
            "for (i = 0; i < a; i++) {",
            "    t[i].valor = i;",
            "}",
        )
        in variantes
    )
    assert (
        cuerpo(
            "s32 i;",
            "D_global = 1;",
            "for (i = 0; i < a; i++) {",
            "    tabla[i].valor = i;",
            "}",
        )
        in variantes
    )


def test_el_acceso_directo_tambien_vale_con_la_direccion_asignada_en_el_cuerpo() -> None:
    texto = cuerpo(
        "Nodo* t;", "s32 i;", "t = tabla;", "for (i = 0; i < a; i++) {", "    t[i].valor = i;", "}"
    )
    variantes = todas_las_variantes(mut.asignar_antes_del_bucle, texto)
    assert cuerpo("s32 i;", "for (i = 0; i < a; i++) {", "    tabla[i].valor = i;", "}") in variantes


def test_un_puntero_inicializado_con_el_valor_de_un_global_escalar_no_se_mueve() -> None:
    sin_cambio(
        mut.asignar_antes_del_bucle,
        cuerpo("Nodo* t = (Nodo*)D_global;", "D_otra = 1;", "D_otra = t->valor;"),
    )


def test_un_puntero_usado_en_la_primera_sentencia_solo_admite_el_acceso_directo() -> None:
    texto = cuerpo("Nodo* t = tabla;", "D_global = t->valor;", "D_otra = 1;")
    assert todas_las_variantes(mut.asignar_antes_del_bucle, texto) == {
        cuerpo("D_global = tabla->valor;", "D_otra = 1;")
    }


def test_un_puntero_reasignado_no_cambia() -> None:
    sin_cambio(
        mut.asignar_antes_del_bucle,
        cuerpo("Nodo* t;", "t = tabla;", "t = q;", "D_global = t->valor;"),
    )
