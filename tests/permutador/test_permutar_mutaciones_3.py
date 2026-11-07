"""Pruebas de las mutaciones de variables, bucles, copias y direcciones.

Para cada mutacion: la transformacion produce el C exacto esperado, no se aplica (y deja el arbol
intacto) cuando no es segura, y el C resultante vuelve a leerse y a escribirse igual (``aplicar``).
"""

from psxdecomp.permutador import mutaciones as mut

from permutador.ayudantes_mutaciones import aplicar, cuerpo, sin_cambio, todas_las_variantes

# --- bucle_por_indice ----------------------------------------------------------------------------------


def test_el_puntero_de_un_while_pasa_a_acceso_indexado_en_todas_las_sentencias() -> None:
    texto = cuerpo(
        "s32 i;",
        "Nodo* r;",
        "r = p + i;",
        "while (i < a) {",
        "    r->valor = 1;",
        "    r->clave = r->corto;",
        "    r++;",
        "    i++;",
        "}",
    )
    descripcion, resultado = aplicar(mut.bucle_por_indice, texto)
    assert descripcion == "bucle_por_indice(r por p[i])"
    assert resultado == cuerpo(
        "s32 i;", "while (i < a) {", "    p[i].valor = 1;", "    p[i].clave = p[i].corto;", "    i++;", "}"
    )


def test_el_for_con_coma_y_la_direccion_de_un_elemento_se_reescriben() -> None:
    texto = cuerpo(
        "s32 i;",
        "Nodo* r;",
        "r = &p[i];",
        "for (; i < a; r++, i++) {",
        "    r->byte = r[2].byte;",
        "    D_global = r[0].valor;",
        "}",
    )
    _, resultado = aplicar(mut.bucle_por_indice, texto)
    assert resultado == cuerpo(
        "s32 i;", "for (; i < a; i++) {", "    p[i].byte = p[i + 2].byte;", "    D_global = p[i].valor;", "}"
    )


def test_el_avance_del_puntero_puede_ser_todo_el_paso_del_for() -> None:
    texto = cuerpo(
        "s32 i;",
        "Nodo* r;",
        "r = p + i;",
        "for (; i < a; r++) {",
        "    D_global = r->valor;",
        "    i++;",
        "}",
    )
    _, resultado = aplicar(mut.bucle_por_indice, texto)
    assert "D_global = p[i].valor;" in resultado
    assert "r++" not in resultado
    assert "Nodo* r;" not in resultado


def test_la_condicion_de_un_do_while_y_el_avance_compuesto_se_reescriben() -> None:
    texto = cuerpo(
        "s32 i;",
        "Nodo* r;",
        "r = p + i;",
        "do {",
        "    D_global = r->valor;",
        "    r += 1;",
        "    i += 1;",
        "} while (r->clave);",
    )
    _, resultado = aplicar(mut.bucle_por_indice, texto)
    assert resultado == cuerpo(
        "s32 i;", "do {", "    D_global = p[i].valor;", "    i += 1;", "} while (p[i].clave);"
    )


def test_el_puntero_usado_despues_del_bucle_no_se_sustituye() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    r->valor = 1;",
            "    r++;",
            "    i++;",
            "}",
            "D_global = r->valor;",
        ),
    )


def test_un_uso_entre_los_dos_avances_ve_valores_desacoplados_y_no_se_sustituye() -> None:
    sin_cambio(
        mut.bucle_por_indice,
        cuerpo(
            "s32 i;",
            "Nodo* r;",
            "r = p + i;",
            "while (i < a) {",
            "    r++;",
            "    D_global = r->valor;",
            "    i++;",
            "}",
        ),
    )


# --- duplicar_local_de_global --------------------------------------------------------------------------


def test_la_segunda_lectura_del_global_usa_una_local_nueva() -> None:
    texto = cuerpo(
        "s32 j;",
        "j = D_global;",
        "D_otra = j + 1;",
        "if (a) {",
        "    D_otra = 0;",
        "}",
        "j = D_global;",
        "D_otra = j * 2;",
    )
    descripcion, resultado = aplicar(mut.duplicar_local_de_global, texto)
    assert descripcion == "duplicar_local_de_global(j en tmp1 = D_global)"
    assert resultado == cuerpo(
        "s32 j;",
        "s32 tmp1;",
        "j = D_global;",
        "D_otra = j + 1;",
        "if (a) {",
        "    D_otra = 0;",
        "}",
        "tmp1 = D_global;",
        "D_otra = tmp1 * 2;",
    )


def test_dos_lecturas_de_globales_distintos_no_se_duplican() -> None:
    sin_cambio(
        mut.duplicar_local_de_global,
        cuerpo("s32 j;", "j = D_global;", "D_otra = j;", "j = D_otra;", "D_global = j;"),
    )


def test_una_funcion_con_etiquetas_no_se_toca_para_duplicar() -> None:
    sin_cambio(
        mut.duplicar_local_de_global,
        cuerpo(
            "s32 j;",
            "j = D_global;",
            "inicio:",
            "D_otra = j;",
            "j = D_global;",
            "D_otra = j;",
            "goto inicio;",
        ),
    )


# --- ancho_de_local_de_campo ---------------------------------------------------------------------------


def test_una_local_que_solo_se_copia_a_campos_de_16_bits_cambia_de_ancho() -> None:
    texto = cuerpo("s32 x;", "x = q->corto;", "p->ancho = x;", "p->corto = x;")
    variantes = todas_las_variantes(mut.ancho_de_local_de_campo, texto)
    assert variantes == {
        cuerpo("s16 x;", "x = q->corto;", "p->ancho = x;", "p->corto = x;"),
        cuerpo("u16 x;", "x = q->corto;", "p->ancho = x;", "p->corto = x;"),
    }


def test_una_local_de_16_bits_puede_ensancharse_a_32() -> None:
    texto = cuerpo("s16 x;", "x = q->corto;", "p->byte = x;")
    descripcion, resultado = aplicar(mut.ancho_de_local_de_campo, texto, 1)
    assert descripcion is not None and descripcion.startswith("ancho_de_local_de_campo(x: s16 a ")
    assert resultado != texto


def test_una_local_leida_en_una_comparacion_conserva_su_ancho() -> None:
    sin_cambio(
        mut.ancho_de_local_de_campo,
        cuerpo("s32 x;", "x = q->corto;", "if (x == 1) {", "    D_global = 0;", "}", "p->corto = x;"),
    )


def test_una_local_copiada_a_un_destino_de_32_bits_conserva_su_ancho() -> None:
    sin_cambio(mut.ancho_de_local_de_campo, cuerpo("s32 x;", "x = q->corto;", "p->valor = x;"))


# --- truncar_en_asignacion -----------------------------------------------------------------------------


def test_la_local_estrecha_pasa_a_32_bits_con_un_molde_en_la_asignacion() -> None:
    texto = cuerpo("u16 d;", "d = a / 100;", "D_global = d;")
    descripcion, resultado = aplicar(mut.truncar_en_asignacion, texto)
    assert descripcion == "truncar_en_asignacion(d: u16 a s32)"
    assert resultado == cuerpo("s32 d;", "d = (u16)(a / 100);", "D_global = d;")


def test_el_inicializador_tambien_recibe_el_molde_y_no_se_repite_uno_existente() -> None:
    texto = cuerpo("u8 d = a / 100;", "u8 e;", "e = (u8)b;", "D_global = d + e;")
    variantes = todas_las_variantes(mut.truncar_en_asignacion, texto)
    assert cuerpo("s32 d = (u8)(a / 100);", "u8 e;", "e = (u8)b;", "D_global = d + e;") in variantes
    assert cuerpo("u8 d = a / 100;", "s32 e;", "e = (u8)b;", "D_global = d + e;") in variantes


def test_la_local_de_32_bits_con_moldes_iguales_vuelve_al_tipo_estrecho() -> None:
    texto = cuerpo("s32 d;", "d = (u16)(a / 100);", "D_global = d;")
    descripcion, resultado = aplicar(mut.truncar_en_asignacion, texto)
    assert descripcion == "truncar_en_asignacion(d: s32 a u16)"
    assert resultado == cuerpo("u16 d;", "d = a / 100;", "D_global = d;")


def test_moldes_distintos_o_una_asignacion_sin_molde_impiden_estrechar() -> None:
    sin_cambio(mut.truncar_en_asignacion, cuerpo("s32 d;", "d = (u16)a;", "d = (u8)b;", "D_global = d;"))
    sin_cambio(mut.truncar_en_asignacion, cuerpo("s32 d;", "d = (u16)a;", "d = b;", "D_global = d;"))


def test_una_local_que_se_incrementa_no_cambia_de_tipo() -> None:
    sin_cambio(mut.truncar_en_asignacion, cuerpo("u16 d;", "d = a;", "d++;", "D_global = d;"))


def test_una_local_estrecha_sin_escrituras_no_se_toca() -> None:
    sin_cambio(mut.truncar_en_asignacion, cuerpo("u16 d;", "D_global = d;"))
