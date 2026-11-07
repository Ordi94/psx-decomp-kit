"""Reglas de negocio del orden de dos almacenes a campos de igual nombre en estructuras distintas.

Dos estructuras distintas no se solapan (hipotesis de aliasing del modulo), de modo que
``p->valor = 1; r->valor = 2;`` se puede intercambiar aunque el campo se llame igual. No es legal si
las dos estructuras son la misma, si algun valor lee memoria o comparte una variable escrita, si el
puntero no apunta a una estructura conocida o si la otra sentencia no es un almacen a un campo.
"""

from psxdecomp.permutador import mutaciones as mut

from permutador.ayudantes_mutaciones import aplicar, cuerpo, sin_cambio

FIRMA = "void f(Nodo* p, Nodo* q, Registro* r, Desconocido* d, s32 a)"


def test_dos_almacenes_al_mismo_campo_de_estructuras_distintas_se_intercambian() -> None:
    descripcion, resultado = aplicar(
        mut.orden_de_sentencias, cuerpo("p->valor = 1;", "r->valor = 2;", firma=FIRMA)
    )
    assert descripcion == "orden_sentencias(posiciones 0 y 1)"
    assert resultado == cuerpo("r->valor = 2;", "p->valor = 1;", firma=FIRMA)


def test_la_asignacion_compuesta_a_estructuras_distintas_tambien_se_intercambia() -> None:
    _, resultado = aplicar(mut.orden_de_sentencias, cuerpo("p->valor |= a;", "r->valor &= 3;", firma=FIRMA))
    assert resultado == cuerpo("r->valor &= 3;", "p->valor |= a;", firma=FIRMA)


def test_dos_almacenes_al_mismo_campo_de_la_misma_estructura_conservan_su_orden() -> None:
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = 1;", "q->valor = 2;", firma=FIRMA))


def test_un_almacen_cuyo_valor_lee_memoria_conserva_su_orden() -> None:
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = r->valor;", "r->valor = 2;", firma=FIRMA))


def test_dos_almacenes_que_comparten_una_variable_escrita_conservan_su_orden() -> None:
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = a;", "r->valor = (a = 3);", firma=FIRMA))


def test_un_puntero_a_una_estructura_desconocida_o_un_entero_conserva_su_orden() -> None:
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = 1;", "d->valor = 2;", firma=FIRMA))
    sin_cambio(mut.orden_de_sentencias, cuerpo("a->valor = 1;", "r->valor = 2;", firma=FIRMA))


def test_la_otra_sentencia_debe_ser_un_almacen_a_un_campo_por_flecha() -> None:
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = 1;", "foo(a);", firma=FIRMA))
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = 1;", "*(s32*)a = 2;", firma=FIRMA))
    sin_cambio(mut.orden_de_sentencias, cuerpo("p->valor = 1;", "r->valor = foo(a);", firma=FIRMA))
