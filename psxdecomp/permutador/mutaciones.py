"""Mutaciones del C de una funcion que conservan su significado.

Cada mutacion recibe el arbol de una funcion y lo cambia en un sitio elegido al azar por una
reformulacion equivalente: reordenar declaraciones o sentencias independientes, introducir o
eliminar un temporal, cambiar el ancho de un temporal, conmutar operandos, pasar de indice a puntero,
cambiar de ``for`` a ``while`` y negar una condicion intercambiando sus ramas. Son las
reformulaciones que alteran el reparto de registros y el orden de las instrucciones del compilador
sin cambiar lo que la funcion hace.

Ninguna mutacion escribe ensamblador, ``volatile``, ``register`` ni barreras: son recursos que el
proyecto no admite como estado final, y ``variante_permitida`` descarta cualquier variante que
aumente su cantidad respecto al C de partida. Las macros de funcion (en mayusculas o ``gte_*``) y las
llamadas son sentencias opacas: nada se mueve a traves de ellas y sus argumentos no se parten.
"""

from __future__ import annotations

import copy
import itertools
import random
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import c

PREFIJO_TEMPORAL = "tmp"
PATRONES_PROHIBIDOS = (
    re.compile(r"__asm__"),
    re.compile(r"\basm\s*\("),
    re.compile(r"\bvolatile\b"),
    re.compile(r"\bregister\b"),
    re.compile(r"\bGLOBAL_ASM\b"),
)
OPERADORES_CONMUTATIVOS = frozenset({"+", "*", "&", "|", "^", "==", "!="})
RELACIONALES_INVERSOS = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
NEGACION_DE_COMPARACION = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
PROBABILIDAD_TODAS_LAS_APARICIONES = 0.5
PROBABILIDAD_NEGACION_LITERAL = 0.3


@dataclass
class Contexto:
    """Estado de una ronda de mutaciones sobre una copia de la funcion.

    Attributes:
        funcion: Copia de la funcion que se muta.
        entorno: Tipos de los identificadores de la copia.
        azar: Generador de numeros aleatorios.
        nombres: Identificadores en uso (para no repetir el nombre de un temporal).
    """

    funcion: c.Funcion
    entorno: an.Entorno
    azar: random.Random
    nombres: set[str]

    @property
    def alias(self) -> Mapping[str, str]:
        """Campos que comparten almacenamiento en una ``union``, para los efectos de las sentencias."""
        return self.entorno.tabla.alias_de_campos


@dataclass(frozen=True)
class Sitio:
    """Una subexpresion junto con su contexto.

    Attributes:
        nodo: La subexpresion.
        padre: Nodo o sentencia que la contiene.
        perezoso: Verdadero si solo se evalua a veces (operando derecho de ``&&``, ramas de ``?:``).
        lvalue: Verdadero si es un destino o un operando de ``&`` (no se puede copiar a un temporal).
    """

    nodo: c.Expr
    padre: object
    perezoso: bool
    lvalue: bool


# ---------------------------------------------------------------------------------------------------
# Recorridos
# ---------------------------------------------------------------------------------------------------


def _hijos_con_contexto(  # noqa: PLR0911 - despachador por tipo de nodo
    expr: c.Expr, perezoso: bool, lvalue: bool
) -> list[tuple[c.Expr, bool, bool]]:
    """Hijos de una expresion con las banderas ``perezoso`` y ``lvalue`` que les corresponden."""
    if isinstance(expr, c.Binario) and expr.op in ("&&", "||"):
        return [(expr.izq, perezoso, False), (expr.der, True, False)]
    if isinstance(expr, c.Ternario):
        return [(expr.cond, perezoso, False), (expr.si, True, False), (expr.no, True, False)]
    if isinstance(expr, c.Asigna):
        return [(expr.destino, perezoso, True), (expr.valor, perezoso, False)]
    if isinstance(expr, c.Unario) and expr.op in ("&", "++", "--"):
        return [(expr.operando, perezoso, True)]
    if isinstance(expr, c.Postfijo):
        return [(expr.operando, perezoso, True)]
    if isinstance(expr, c.Llamada):
        return [(expr.funcion, perezoso, True), *((a, perezoso, False) for a in expr.args)]
    if isinstance(expr, c.Miembro):
        return [(expr.base, perezoso, lvalue and not expr.flecha)]
    if isinstance(expr, c.Indice):
        return [(expr.base, perezoso, lvalue), (expr.indice, perezoso, False)]
    return [(hijo, perezoso, False) for hijo in c.hijos(expr)]


def sitios_de(
    raiz: c.Expr, padre: object, *, perezoso: bool = False, lvalue: bool = False
) -> Iterator[Sitio]:
    """
    Recorre una expresion dando cada subexpresion con su contexto de evaluacion.

    Contexto:
        Las mutaciones de temporales y de operandos eligen su sitio entre estos.

    Args:
        raiz (c.Expr): Raiz del recorrido.
        padre (object): Sentencia o nodo que contiene a ``raiz``.
        perezoso (bool, opcional): Si la raiz ya esta en una posicion de evaluacion condicional.
        lvalue (bool, opcional): Si la raiz es un destino.

    Yields:
        Sitio: Cada nodo en preorden.

    Ejemplo:
        sitios = list(sitios_de(sentencia.expr, sentencia))
    """
    yield Sitio(raiz, padre, perezoso, lvalue)
    for hijo, hijo_perezoso, hijo_lvalue in _hijos_con_contexto(raiz, perezoso, lvalue):
        yield from sitios_de(hijo, raiz, perezoso=hijo_perezoso, lvalue=hijo_lvalue)


def _sentencias(funcion: c.Funcion) -> Iterator[tuple[c.Bloque, int, c.Sentencia]]:
    """Cada sentencia de la funcion con su bloque y su posicion."""
    for bloque in c.todos_los_bloques(funcion.cuerpo):
        for indice, sentencia in enumerate(list(bloque.items)):
            yield bloque, indice, sentencia


def _todas_las_expresiones(funcion: c.Funcion) -> Iterator[tuple[c.Sentencia, c.Expr]]:
    """Cada expresion raiz de la funcion con su sentencia."""
    for _, _, sentencia in _sentencias(funcion):
        for raiz in c.expresiones_de(sentencia):
            yield sentencia, raiz


def _nombres_de(funcion: c.Funcion) -> set[str]:
    """Todos los identificadores que aparecen en la funcion, incluidos los declarados."""
    nombres = {p.nombre for p in funcion.parametros}
    for _, _, sentencia in _sentencias(funcion):
        if isinstance(sentencia, c.Decl):
            nombres.add(sentencia.nombre)
        for raiz in c.expresiones_de(sentencia):
            nombres |= an.identificadores_de(raiz)
    return nombres


def nombres_ambiguos(funcion: c.Funcion) -> set[str]:
    """
    Nombres que no identifican a una unica variable dentro de la funcion.

    Contexto:
        El seguimiento de tipos y de usos de las mutaciones de temporales, de ancho y de parametros
        trabaja por nombre, sin ambito lexico: dos locales ``tmp`` en bloques hermanos, o una local
        que sombrea a un parametro, se confundirian en una sola variable y una mutacion podria borrar
        la declaracion equivocada o razonar con el tipo equivocado. Esas mutaciones solo actuan sobre
        nombres que NO estan en este conjunto, ni toman subexpresiones que los mencionen.

    Args:
        funcion (c.Funcion): Funcion que se analiza.

    Returns:
        set[str]: Nombres declarados mas de una vez en cualquier bloque (incluidos los anidados) y
        nombres de local que coinciden con un parametro.

    Ejemplo:
        ambiguos = nombres_ambiguos(funcion)
    """
    parametros = {p.nombre for p in funcion.parametros}
    vistos: set[str] = set()
    ambiguos: set[str] = set()
    for _, _, sentencia in _sentencias(funcion):
        if not isinstance(sentencia, c.Decl):
            continue
        if sentencia.nombre in vistos or sentencia.nombre in parametros:
            ambiguos.add(sentencia.nombre)
        vistos.add(sentencia.nombre)
    return ambiguos


def _fin_de_declaraciones(cuerpo: c.Bloque) -> int:
    """Posicion donde termina la serie inicial de declaraciones de un bloque."""
    posicion = 0
    while posicion < len(cuerpo.items) and isinstance(cuerpo.items[posicion], c.Decl):
        posicion += 1
    return posicion


def _elegir[T](azar: random.Random, opciones: list[T]) -> T | None:
    """Elige un elemento al azar; ``None`` si la lista esta vacia."""
    return azar.choice(opciones) if opciones else None


def _contiene_continuar(bloque: c.Bloque) -> bool:
    """Indica si un cuerpo de bucle tiene un ``continue`` que le pertenezca (no el de un bucle interior)."""
    for sentencia in bloque.items:
        if isinstance(sentencia, c.Continuar):
            return True
        if isinstance(sentencia, c.Mientras | c.HacerMientras | c.Para):
            continue
        if any(_contiene_continuar(hijo) for hijo in c.bloques_hijos(sentencia)):
            return True
    return False


# ---------------------------------------------------------------------------------------------------
# Orden de declaraciones y sentencias
# ---------------------------------------------------------------------------------------------------


def _orden_de_declaraciones_valido(declaraciones: list[c.Decl]) -> bool:
    """Un inicializador solo puede nombrar variables de la serie declaradas antes que el."""
    de_la_serie = {d.nombre for d in declaraciones}
    declaradas: set[str] = set()
    for declaracion in declaraciones:
        if declaracion.inicial is not None:
            usadas = an.identificadores_de(declaracion.inicial) & de_la_serie
            if not usadas <= declaradas:
                return False
        declaradas.add(declaracion.nombre)
    return True


def orden_de_declaraciones(ctx: Contexto) -> str | None:
    """
    Mueve una declaracion local a otra posicion de su serie.

    Contexto:
        El orden de las declaraciones fija la reserva de pila y el numero de pseudoregistro de cada
        variable, que desempata el reparto de registros.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion de la mutacion, o ``None`` si ningun bloque tiene dos declaraciones
        que se puedan reordenar.

    Ejemplo:
        descripcion = orden_de_declaraciones(contexto)
    """
    candidatos: list[tuple[c.Bloque, int, int]] = []
    for bloque in c.todos_los_bloques(ctx.funcion.cuerpo):
        fin = _fin_de_declaraciones(bloque)
        if fin < 2:
            continue
        declaraciones = [d for d in bloque.items[:fin] if isinstance(d, c.Decl)]
        for origen in range(fin):
            for destino in range(fin):
                if origen == destino:
                    continue
                movida = list(declaraciones)
                movida.insert(destino, movida.pop(origen))
                if _orden_de_declaraciones_valido(movida):
                    candidatos.append((bloque, origen, destino))
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    bloque, origen, destino = elegido
    nombre = getattr(bloque.items[origen], "nombre", "")
    bloque.items.insert(destino, bloque.items.pop(origen))
    return f"orden_declaraciones({nombre} a la posicion {destino})"


def _locales_con_direccion(funcion: c.Funcion) -> set[str]:
    """Ubicaciones ``v:nombre`` de las variables a las que la funcion les toma la direccion."""
    return {
        f"v:{nodo.operando.nombre}"
        for _, raiz in _todas_las_expresiones(funcion)
        for nodo in c.recorrer(raiz)
        if isinstance(nodo, c.Unario) and nodo.op == "&" and isinstance(nodo.operando, c.Id)
    }


def orden_de_sentencias(ctx: Contexto) -> str | None:
    """
    Intercambia dos sentencias de expresion consecutivas que no dependen una de la otra.

    Contexto:
        El orden de sentencias independientes cambia la planificacion y la vida de los registros.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay un par intercambiable.

    Ejemplo:
        descripcion = orden_de_sentencias(contexto)
    """
    con_direccion = _locales_con_direccion(ctx.funcion)
    candidatos: list[tuple[c.Bloque, int]] = []
    for bloque in c.todos_los_bloques(ctx.funcion.cuerpo):
        for indice in range(len(bloque.items) - 1):
            a = an.efectos_de(bloque.items[indice], ctx.alias)
            b = an.efectos_de(bloque.items[indice + 1], ctx.alias)
            # Una variable con direccion tomada puede escribirse por un puntero: no se mueve.
            tocadas = a.lee | a.escribe | b.lee | b.escribe
            if an.son_independientes(a, b) and not con_direccion & tocadas:
                candidatos.append((bloque, indice))
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    bloque, indice = elegido
    bloque.items[indice], bloque.items[indice + 1] = bloque.items[indice + 1], bloque.items[indice]
    return f"orden_sentencias(posiciones {indice} y {indice + 1})"


# ---------------------------------------------------------------------------------------------------
# Temporales
# ---------------------------------------------------------------------------------------------------


def _nombre_temporal(ctx: Contexto) -> str:
    """Primer nombre ``tmpN`` que no esta en uso."""
    numero = 1
    while f"{PREFIJO_TEMPORAL}{numero}" in ctx.nombres:
        numero += 1
    nombre = f"{PREFIJO_TEMPORAL}{numero}"
    ctx.nombres.add(nombre)
    return nombre


def _declarar_temporal(ctx: Contexto, nombre: str, tipo: an.Tipo) -> None:
    """Anade la declaracion del temporal al final de las declaraciones de la funcion."""
    cuerpo = ctx.funcion.cuerpo
    cuerpo.items.insert(_fin_de_declaraciones(cuerpo), c.Decl(tipo.base, tipo.estrellas, nombre))
    ctx.entorno.locales[nombre] = tipo


def _aparicion_unica_de_asignacion(raiz: c.Expr) -> bool:
    """Una sentencia admite izar una subexpresion si no tiene mas efectos que su asignacion o llamada raiz."""
    asignaciones = [n for n in c.recorrer(raiz) if isinstance(n, c.Asigna)]
    llamadas = [n for n in c.recorrer(raiz) if isinstance(n, c.Llamada)]
    incrementos = [
        n
        for n in c.recorrer(raiz)
        if isinstance(n, c.Postfijo) or (isinstance(n, c.Unario) and n.op in ("++", "--"))
    ]
    if incrementos or len(asignaciones) > 1 or (asignaciones and asignaciones[0] is not raiz):
        return False
    if not llamadas:
        return True
    return len(llamadas) == 1 and llamadas[0] is raiz and all(an.es_pura(a) for a in raiz.args)


def _sitios_izables(ctx: Contexto) -> list[tuple[c.Bloque, int, Sitio, an.Tipo]]:
    """Subexpresiones puras de tipo escalar conocido que se pueden copiar a un temporal."""
    resultado: list[tuple[c.Bloque, int, Sitio, an.Tipo]] = []
    ambiguos = nombres_ambiguos(ctx.funcion)
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        if isinstance(sentencia, c.Decl | c.Mientras | c.HacerMientras | c.Para | c.Caso):
            continue
        for raiz in c.expresiones_de(sentencia):
            if not _aparicion_unica_de_asignacion(raiz):
                continue
            for sitio in sitios_de(raiz, sentencia):
                tipo = ctx.entorno.inferir(sitio.nodo)
                es_izable = (
                    tipo is not None
                    and tipo.es_escalar
                    and not sitio.perezoso
                    and not sitio.lvalue
                    and an.es_pura(sitio.nodo)
                    and not isinstance(sitio.nodo, c.Num)
                    and not an.identificadores_de(sitio.nodo) & ambiguos
                    and not (sitio.padre is sentencia and isinstance(sentencia, c.Expresion))
                )
                if es_izable and tipo is not None:
                    resultado.append((bloque, indice, sitio, tipo))
    return resultado


def _posicion_de_la_asignacion(
    bloque: c.Bloque, indice: int, asignacion: c.Expresion, azar: random.Random, alias: Mapping[str, str]
) -> int:
    """
    Elige donde colocar la asignacion de un temporal: justo antes de su uso o mas arriba.

    Contexto:
        Adelantar la carga de un valor por encima de sentencias que no lo tocan alarga su vida; es la
        forma en que muchos cierres de registros hacen que el valor ya este cargado. Solo se sube por
        encima de sentencias independientes de la asignacion (sin llamadas ni escrituras que la afecten).

    Args:
        bloque (c.Bloque): Bloque donde esta la sentencia que usa el temporal.
        indice (int): Posicion de esa sentencia.
        asignacion (c.Expresion): Asignacion del temporal.
        azar (random.Random): Generador de numeros aleatorios.
        alias (Mapping[str, str]): Campos que comparten almacenamiento en una ``union``.

    Returns:
        int: Posicion de insercion, entre la mas alta posible y ``indice``.

    Ejemplo:
        posicion = _posicion_de_la_asignacion(bloque, 5, asignacion, azar, alias)
    """
    efectos = an.efectos_de(asignacion, alias)
    mas_alta = indice
    while mas_alta > 0 and an.son_independientes(an.efectos_de(bloque.items[mas_alta - 1], alias), efectos):
        mas_alta -= 1
    return mas_alta + int(azar.random() * (indice - mas_alta + 1))


def introducir_temporal(ctx: Contexto) -> str | None:
    """
    Copia una subexpresion pura a una variable local declarada justo antes de su sentencia.

    Contexto:
        Un temporal alarga la vida de un valor y cambia el reparto de registros; es la reformulacion
        mas productiva en este compilador. Con probabilidad 1/2 sustituye todas las apariciones iguales de
        la expresion en la sentencia.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna subexpresion es apta.

    Ejemplo:
        descripcion = introducir_temporal(contexto)
    """
    elegido = _elegir(ctx.azar, _sitios_izables(ctx))
    if elegido is None:
        return None
    bloque, indice, sitio, tipo = elegido
    sentencia = bloque.items[indice]
    nombre = _nombre_temporal(ctx)
    clave = an.texto_de(sitio.nodo)
    copia = copy.deepcopy(sitio.nodo)
    if ctx.azar.random() < PROBABILIDAD_TODAS_LAS_APARICIONES:
        for raiz in c.expresiones_de(sentencia):
            for otro in list(sitios_de(raiz, sentencia)):
                if not otro.lvalue and not otro.perezoso and an.texto_de(otro.nodo) == clave:
                    c.reemplazar_hijo(otro.padre, otro.nodo, c.Id(nombre))
    else:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, c.Id(nombre))
    asignacion = c.Expresion(expr=c.Asigna("=", c.Id(nombre), copia))
    # La asignacion se inserta antes que la declaracion: esta se coloca al inicio del cuerpo y
    # desplazaria el indice de la sentencia.
    bloque.items.insert(
        _posicion_de_la_asignacion(bloque, indice, asignacion, ctx.azar, ctx.alias), asignacion
    )
    _declarar_temporal(ctx, nombre, tipo)
    return f"introducir_temporal({tipo.texto} {nombre} = {clave})"


def _usos_de(funcion: c.Funcion, nombre: str) -> list[tuple[c.Sentencia, Sitio]]:
    """Cada aparicion de un identificador con su sentencia."""
    usos: list[tuple[c.Sentencia, Sitio]] = []
    for _, _, sentencia in _sentencias(funcion):
        for raiz in c.expresiones_de(sentencia):
            usos.extend(
                (sentencia, sitio)
                for sitio in sitios_de(raiz, sentencia)
                if isinstance(sitio.nodo, c.Id) and sitio.nodo.nombre == nombre
            )
    return usos


def eliminar_temporal(ctx: Contexto) -> str | None:
    """
    Sustituye un temporal de un solo uso por la expresion que lo calcula.

    Contexto:
        Operacion inversa de ``introducir_temporal``: permite deshacer un temporal que el original
        no tenia, y quitar los del C de partida. Solo se aplica si la asignacion va justo antes del
        uso, no hay otras escrituras y el tipo de la expresion conserva todos los valores del temporal.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ningun temporal cumple las condiciones.

    Ejemplo:
        descripcion = eliminar_temporal(contexto)
    """
    candidatos: list[tuple[c.Bloque, int, Sitio]] = []
    ambiguos = nombres_ambiguos(ctx.funcion)
    declaradas = {
        s.nombre
        for _, _, s in _sentencias(ctx.funcion)
        if isinstance(s, c.Decl) and not s.inicial and s.nombre not in ambiguos
    }
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        if not (
            isinstance(sentencia, c.Expresion)
            and isinstance(sentencia.expr, c.Asigna)
            and sentencia.expr.op == "="
            and isinstance(sentencia.expr.destino, c.Id)
            and sentencia.expr.destino.nombre in declaradas
            and indice + 1 < len(bloque.items)
        ):
            continue
        nombre = sentencia.expr.destino.nombre
        usos = _usos_de(ctx.funcion, nombre)
        siguiente = bloque.items[indice + 1]
        lecturas = [u for u in usos if not u[1].lvalue]
        if len(usos) != 2 or len(lecturas) != 1 or lecturas[0][0] is not siguiente:
            continue
        sitio = lecturas[0][1]
        raiz = c.expresiones_de(siguiente)
        origen = ctx.entorno.inferir(sentencia.expr.valor)
        destino = ctx.entorno.locales.get(nombre)
        compatible = (
            origen is not None
            and destino is not None
            and an.promover(origen) == an.promover(destino)
            and (origen.texto == destino.texto or an.conserva_valor(origen, destino))
        )
        if (
            compatible
            and not an.identificadores_de(sentencia.expr.valor) & ambiguos
            and an.es_pura(sentencia.expr.valor)
            and not sitio.perezoso
            and raiz
            and all(_aparicion_unica_de_asignacion(r) for r in raiz)
        ):
            candidatos.append((bloque, indice, sitio))
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    bloque, indice, sitio = elegido
    asignacion = bloque.items[indice]
    assert isinstance(asignacion, c.Expresion) and isinstance(asignacion.expr, c.Asigna)  # noqa: S101
    destino_id = asignacion.expr.destino
    assert isinstance(destino_id, c.Id)  # noqa: S101
    c.reemplazar_hijo(sitio.padre, sitio.nodo, asignacion.expr.valor)
    del bloque.items[indice]
    _quitar_declaracion(ctx.funcion, destino_id.nombre)
    return f"eliminar_temporal({destino_id.nombre})"


def _quitar_declaracion(funcion: c.Funcion, nombre: str) -> None:
    """Quita la declaracion de una variable que ya no se usa."""
    for bloque in c.todos_los_bloques(funcion.cuerpo):
        for indice, sentencia in enumerate(bloque.items):
            if isinstance(sentencia, c.Decl) and sentencia.nombre == nombre:
                del bloque.items[indice]
                return


def _ancho_permitido(ctx: Contexto, declaracion: c.Decl, ambiguos: set[str]) -> list[an.Tipo] | None:
    """Tipos a los que una local entera cambia sin perder valores, o ``None`` si no admite el cambio.

    Una variable de nombre ambiguo, o que recibe expresiones que mencionan uno, no admite el cambio.
    """
    if declaracion.nombre in ambiguos:
        return None
    actual = an.parsear_tipo(declaracion.base, declaracion.estrellas)
    if (
        not actual.es_entero
        or declaracion.sufijo
        or declaracion.declarador
        or actual.texto not in an.TIPOS_ENTEROS_PERMITIDOS
    ):
        return None
    fuentes: list[c.Expr] = []
    if declaracion.inicial is not None:
        fuentes.append(declaracion.inicial)
    insensible = True
    for sentencia, sitio in _usos_de(ctx.funcion, declaracion.nombre):
        padre = sitio.padre
        if isinstance(padre, c.Asigna) and padre.destino is sitio.nodo:
            if padre.op != "=":
                return None
            fuentes.append(padre.valor)
            continue
        if sitio.lvalue:
            return None
        insensible = insensible and _uso_insensible_al_signo(sitio, sentencia)
    if not fuentes or any(an.identificadores_de(fuente) & ambiguos for fuente in fuentes):
        return None
    permitidos = []
    for nombre in an.TIPOS_ENTEROS_PERMITIDOS:
        nuevo = an.tipo_entero(nombre)
        if nuevo.texto == actual.texto:
            continue
        if an.promover(nuevo) != an.promover(actual) and not insensible:
            continue
        if all(_cabe(ctx, fuente, actual, nuevo) for fuente in fuentes):
            permitidos.append(nuevo)
    return permitidos


def _uso_insensible_al_signo(sitio: Sitio, sentencia: c.Sentencia) -> bool:
    """Una lectura no depende del signo del tipo si copia el valor tal cual o lo compara por igualdad."""
    padre = sitio.padre
    if isinstance(padre, c.Asigna):
        return padre.valor is sitio.nodo and padre.op == "="
    if isinstance(padre, c.Llamada):
        return sitio.nodo in padre.args
    if isinstance(padre, c.Binario) and padre.op in ("==", "!="):
        otro = padre.der if padre.izq is sitio.nodo else padre.izq
        valor = an.valor_de_literal(otro)
        return valor is not None and valor >= 0
    if isinstance(padre, c.Unario):
        return padre.op == "!"
    return padre is sentencia and isinstance(sentencia, c.Si)


def _cabe(ctx: Contexto, fuente: c.Expr, actual: an.Tipo, nuevo: an.Tipo) -> bool:
    """Indica si el valor de una fuente asignada cabe, sin cambiar, en el tipo actual y en el nuevo."""
    literal = an.valor_de_literal(fuente)
    if literal is not None:
        return all(t.rango[0] <= literal <= t.rango[1] for t in (actual, nuevo))
    tipo = ctx.entorno.inferir(fuente)
    return tipo is not None and an.conserva_valor(tipo, actual) and an.conserva_valor(tipo, nuevo)


def ancho_de_temporal(ctx: Contexto) -> str | None:
    """
    Cambia el tipo entero de una variable local entre ``s32``, ``u32``, ``s16`` y ``u16``.

    Contexto:
        El ancho de una variable decide si el compilador inserta extensiones (``sll``/``sra``) y que
        instruccion de carga usa. Solo se cambia cuando el rango de todo valor que recibe cabe en
        ambos tipos y el cambio no altera el tipo de las expresiones donde se lee (o esas lecturas no
        dependen del signo).

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna variable admite el cambio.

    Ejemplo:
        descripcion = ancho_de_temporal(contexto)
    """
    candidatos: list[tuple[c.Decl, an.Tipo]] = []
    ambiguos = nombres_ambiguos(ctx.funcion)
    for _, _, sentencia in _sentencias(ctx.funcion):
        if isinstance(sentencia, c.Decl):
            permitidos = _ancho_permitido(ctx, sentencia, ambiguos)
            candidatos.extend((sentencia, nuevo) for nuevo in permitidos or [])
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    declaracion, nuevo = elegido
    anterior = declaracion.base
    declaracion.base = nuevo.base
    ctx.entorno.locales[declaracion.nombre] = nuevo
    return f"ancho_temporal({declaracion.nombre}: {anterior} a {nuevo.texto})"


def copiar_parametro(ctx: Contexto) -> str | None:
    """
    Copia un parametro a una local al inicio de la funcion y usa la copia en todo el cuerpo.

    Contexto:
        Fija el registro del parametro como un temporal normal y deja libre al registro de argumento.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ningun parametro escalar es de solo lectura.

    Ejemplo:
        descripcion = copiar_parametro(contexto)
    """
    candidatos: list[tuple[str, an.Tipo]] = []
    ambiguos = nombres_ambiguos(ctx.funcion)
    for declarado in ctx.funcion.parametros:
        if declarado.nombre in ambiguos:
            continue
        tipo = ctx.entorno.locales.get(declarado.nombre)
        usos = _usos_de(ctx.funcion, declarado.nombre)
        escrito = any(
            sitio.lvalue or (isinstance(sitio.padre, c.Unario) and sitio.padre.op == "&") for _, sitio in usos
        )
        if tipo is not None and tipo.es_escalar and usos and not escrito:
            candidatos.append((declarado.nombre, tipo))
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    parametro, tipo = elegido
    nombre = _nombre_temporal(ctx)
    for _, sitio in _usos_de(ctx.funcion, parametro):
        c.reemplazar_hijo(sitio.padre, sitio.nodo, c.Id(nombre))
    _declarar_temporal(ctx, nombre, tipo)
    cuerpo = ctx.funcion.cuerpo
    cuerpo.items.insert(
        _fin_de_declaraciones(cuerpo), c.Expresion(expr=c.Asigna("=", c.Id(nombre), c.Id(parametro)))
    )
    return f"copiar_parametro({parametro} en {nombre})"


# ---------------------------------------------------------------------------------------------------
# Expresiones
# ---------------------------------------------------------------------------------------------------


def operandos_conmutados(ctx: Contexto) -> str | None:
    """
    Intercambia los operandos de un operador conmutativo, o invierte una comparacion y los suyos.

    Contexto:
        Con operandos puros el orden no cambia el valor; cambia cual se carga primero y que registro
        recibe cada uno (el que se carga primero va a la izquierda).

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay un operador aplicable con operandos puros.

    Ejemplo:
        descripcion = operandos_conmutados(contexto)
    """
    sitios = [
        sitio
        for sentencia, raiz in _todas_las_expresiones(ctx.funcion)
        for sitio in sitios_de(raiz, sentencia)
        if isinstance(sitio.nodo, c.Binario)
        and (sitio.nodo.op in OPERADORES_CONMUTATIVOS or sitio.nodo.op in RELACIONALES_INVERSOS)
        and an.es_pura(sitio.nodo)
    ]
    elegido = _elegir(ctx.azar, sitios)
    if elegido is None:
        return None
    nodo = elegido.nodo
    assert isinstance(nodo, c.Binario)  # noqa: S101
    antes = nodo.op
    nodo.izq, nodo.der = nodo.der, nodo.izq
    nodo.op = RELACIONALES_INVERSOS.get(nodo.op, nodo.op)
    return f"operandos_conmutados({antes})"


def _conversiones_de_acceso(ctx: Contexto) -> list[tuple[Sitio, c.Expr]]:
    """Pares (sitio, reemplazo equivalente) de indice a puntero y de puntero a indice."""
    pares: list[tuple[Sitio, c.Expr]] = []
    for sentencia, raiz in _todas_las_expresiones(ctx.funcion):
        for sitio in sitios_de(raiz, sentencia):
            nodo = sitio.nodo
            if isinstance(nodo, c.Indice):
                suma = c.Binario("+", copy.deepcopy(nodo.base), copy.deepcopy(nodo.indice))
                pares.append((sitio, c.Unario("*", suma)))
            elif isinstance(nodo, c.Unario) and nodo.op == "*" and isinstance(nodo.operando, c.Binario):
                suma = nodo.operando
                derecho = ctx.entorno.inferir(suma.der)
                if suma.op == "+" and not (derecho is not None and derecho.es_puntero):
                    pares.append((sitio, c.Indice(copy.deepcopy(suma.izq), copy.deepcopy(suma.der))))
            elif isinstance(nodo, c.Miembro) and nodo.flecha:
                pares.append((sitio, c.Miembro(c.Unario("*", copy.deepcopy(nodo.base)), False, nodo.campo)))
            elif (
                isinstance(nodo, c.Miembro)
                and isinstance(nodo.base, c.Unario)
                and nodo.base.op == "*"
                and not nodo.flecha
            ):
                pares.append((sitio, c.Miembro(copy.deepcopy(nodo.base.operando), True, nodo.campo)))
    return pares


def indice_o_puntero(ctx: Contexto) -> str | None:
    """
    Reescribe un acceso entre sus formas equivalentes: ``p[i]``/``*(p + i)`` y ``p->c``/``(*p).c``.

    Contexto:
        Las dos formas son identicas en C, pero el compilador las trata distinto al elegir la
        variable de induccion y el modo de direccionamiento.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay un acceso reescribible.

    Ejemplo:
        descripcion = indice_o_puntero(contexto)
    """
    elegido = _elegir(ctx.azar, _conversiones_de_acceso(ctx))
    if elegido is None:
        return None
    sitio, nuevo = elegido
    antes = an.texto_de(sitio.nodo)
    c.reemplazar_hijo(sitio.padre, sitio.nodo, nuevo)
    return f"indice_o_puntero({antes})"


# ---------------------------------------------------------------------------------------------------
# Control de flujo
# ---------------------------------------------------------------------------------------------------


def negar(condicion: c.Expr, azar: random.Random) -> c.Expr:
    """
    Construye la negacion de una condicion, empujandola hacia adentro cuando es posible.

    Contexto:
        Se usa en una posicion de verdad (``if``): ahi ``!!x`` es ``x``, una comparacion se invierte y
        De Morgan conserva el orden de evaluacion y el cortocircuito.

    Args:
        condicion (c.Expr): Condicion a negar.
        azar (random.Random): Decide si se envuelve con ``!`` en lugar de simplificar.

    Returns:
        c.Expr: Condicion contraria.

    Ejemplo:
        contraria = negar(c.Binario("<", c.Id("a"), c.Id("b")), random.Random(1))
    """
    if azar.random() < PROBABILIDAD_NEGACION_LITERAL:
        return c.Unario("!", condicion)
    if isinstance(condicion, c.Unario) and condicion.op == "!":
        return condicion.operando
    if isinstance(condicion, c.Binario) and condicion.op in NEGACION_DE_COMPARACION:
        return c.Binario(NEGACION_DE_COMPARACION[condicion.op], condicion.izq, condicion.der)
    if isinstance(condicion, c.Binario) and condicion.op in ("&&", "||"):
        contraria = "||" if condicion.op == "&&" else "&&"
        return c.Binario(contraria, negar(condicion.izq, azar), negar(condicion.der, azar))
    return c.Unario("!", condicion)


def condicion_invertida(ctx: Contexto) -> str | None:
    """
    Niega la condicion de un ``if`` con ``else`` e intercambia sus ramas.

    Contexto:
        El orden de las ramas decide cual queda como salto y cual como caida, y con ello la
        planificacion de los huecos de salto.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si la funcion no tiene un ``if`` con ``else``.

    Ejemplo:
        descripcion = condicion_invertida(contexto)
    """
    sitios = [s for _, _, s in _sentencias(ctx.funcion) if isinstance(s, c.Si) and s.sino is not None]
    elegido = _elegir(ctx.azar, sitios)
    if elegido is None or elegido.sino is None:
        return None
    antes = an.texto_de(elegido.cond)
    elegido.cond = negar(elegido.cond, ctx.azar)
    elegido.entonces, elegido.sino = elegido.sino, elegido.entonces
    return f"condicion_invertida({antes})"


def _para_a_mientras(bloque: c.Bloque, indice: int, para: c.Para) -> None:
    """Sustituye un ``for`` por su inicio y un ``while`` con el paso al final del cuerpo."""
    nuevos: list[c.Sentencia] = []
    if para.inicio is not None:
        nuevos.append(c.Expresion(expr=para.inicio, comentarios=para.comentarios))
    cuerpo = para.cuerpo
    if para.paso is not None:
        cuerpo.items.append(c.Expresion(expr=para.paso))
    condicion = para.cond if para.cond is not None else c.Num("1")
    nuevos.append(c.Mientras(cond=condicion, cuerpo=cuerpo))
    bloque.items[indice : indice + 1] = nuevos


def _mientras_a_para(bloque: c.Bloque, indice: int, mientras: c.Mientras, azar: random.Random) -> None:
    """Sustituye un ``while`` por un ``for``; con probabilidad 1/2 su ultima sentencia pasa a ser el paso."""
    cuerpo = mientras.cuerpo
    paso = None
    ultima = cuerpo.items[-1] if cuerpo.items else None
    if isinstance(ultima, c.Expresion) and not ultima.comentarios and azar.random() < 0.5:
        paso = ultima.expr
        cuerpo.items.pop()
    bloque.items[indice] = c.Para(None, mientras.cond, paso, cuerpo, comentarios=mientras.comentarios)


def bucle_for_o_while(ctx: Contexto) -> str | None:
    """
    Cambia un bucle ``for`` por ``while`` o un ``while`` por ``for``.

    Contexto:
        El compilador analiza ambos igual en teoria; en la practica la posicion de la inicializacion
        y del paso cambia la numeracion de pseudoregistros. Un bucle con ``continue`` propio no se
        toca: en la forma ``while`` el ``continue`` se saltaria el paso.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay un bucle convertible.

    Ejemplo:
        descripcion = bucle_for_o_while(contexto)
    """
    candidatos = [
        (bloque, indice, sentencia)
        for bloque, indice, sentencia in _sentencias(ctx.funcion)
        if isinstance(sentencia, c.Para | c.Mientras) and not _contiene_continuar(sentencia.cuerpo)
    ]
    elegido = _elegir(ctx.azar, candidatos)
    if elegido is None:
        return None
    bloque, indice, sentencia = elegido
    if isinstance(sentencia, c.Para):
        _para_a_mientras(bloque, indice, sentencia)
        return "bucle(for a while)"
    assert isinstance(sentencia, c.Mientras)  # noqa: S101
    _mientras_a_para(bloque, indice, sentencia, ctx.azar)
    return "bucle(while a for)"


# ---------------------------------------------------------------------------------------------------
# Asignaciones compuestas
# ---------------------------------------------------------------------------------------------------

OPERADORES_COMPUESTOS = frozenset({"+", "-", "|", "&", "^", "<<", ">>"})
OPERADORES_COMPUESTOS_CONMUTATIVOS = frozenset({"+", "|", "&", "^"})
FORMA_EXPANDIR = "expandir"
FORMA_COMPONER_IZQ = "componer_izq"
FORMA_COMPONER_DER = "componer_der"


def _es_destino_de_asignacion(expr: c.Expr) -> bool:
    """Un destino admite la forma compuesta si es una variable, un campo, un indice o ``*p``."""
    return isinstance(expr, c.Id | c.Miembro | c.Indice) or (isinstance(expr, c.Unario) and expr.op == "*")


def _forma_de_composicion(asignacion: c.Asigna) -> str | None:
    """Forma en que una asignacion simple ``x = x op e`` se compone, o ``None`` si no tiene esa forma."""
    valor = asignacion.valor
    if not (isinstance(valor, c.Binario) and valor.op in OPERADORES_COMPUESTOS and an.es_pura(valor)):
        return None
    destino = an.texto_de(asignacion.destino)
    if an.texto_de(valor.izq) == destino:
        return FORMA_COMPONER_IZQ
    if valor.op in OPERADORES_COMPUESTOS_CONMUTATIVOS and an.texto_de(valor.der) == destino:
        return FORMA_COMPONER_DER
    return None


def _formas_de_asignacion(ctx: Contexto) -> list[tuple[c.Asigna, str]]:
    """Asignaciones de la funcion que tienen una forma equivalente, con la forma a la que pasan."""
    formas: list[tuple[c.Asigna, str]] = []
    for sentencia, raiz in _todas_las_expresiones(ctx.funcion):
        for sitio in sitios_de(raiz, sentencia):
            nodo = sitio.nodo
            if not (
                isinstance(nodo, c.Asigna)
                and _es_destino_de_asignacion(nodo.destino)
                and an.es_pura(nodo.destino)
            ):
                continue
            if nodo.op == "=":
                forma = _forma_de_composicion(nodo)
            else:
                forma = (
                    FORMA_EXPANDIR
                    if nodo.op[:-1] in OPERADORES_COMPUESTOS and an.es_pura(nodo.valor)
                    else None
                )
            if forma is not None:
                formas.append((nodo, forma))
    return formas


def asignacion_compuesta(ctx: Contexto) -> str | None:
    """
    Pasa una asignacion entre ``x = x op e`` y ``x op= e`` para ``+ - | & ^ << >>``.

    Contexto:
        Con ``x op= e`` el compilador carga ``x`` una sola vez y conserva el valor en el registro del
        resultado; con ``x = x op e`` en dos sentencias separadas (una de las formas de partida del
        banderin ``|= a ... &= m``) deja una copia ``move`` entre registros. Las dos formas son la
        misma expresion en C: solo se aplican si el destino ``x`` y el operando ``e`` son puros
        (sin llamadas, asignaciones ni incrementos), de modo que ``x`` se evalua una vez en cualquiera
        de las dos y el orden de evaluacion de los operandos no importa. En los operadores
        conmutativos tambien se reconoce ``x = e op x``. Los operadores ``* / %`` no se tocan.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si la funcion no tiene una asignacion en ninguna de las dos
        formas con destino y operando puros.

    Ejemplo:
        descripcion = asignacion_compuesta(contexto)
    """
    elegido = _elegir(ctx.azar, _formas_de_asignacion(ctx))
    if elegido is None:
        return None
    nodo, forma = elegido
    antes = an.texto_de(nodo)
    if forma == FORMA_EXPANDIR:
        nodo.valor = c.Binario(nodo.op[:-1], copy.deepcopy(nodo.destino), nodo.valor)
        nodo.op = "="
    else:
        valor = nodo.valor
        assert isinstance(valor, c.Binario)  # noqa: S101 - ``_forma_de_composicion`` lo garantiza
        nodo.op = f"{valor.op}="
        nodo.valor = valor.der if forma == FORMA_COMPONER_IZQ else valor.izq
    return f"asignacion_compuesta({antes})"


# ---------------------------------------------------------------------------------------------------
# Locales: lectura anticipada, relectura, union y particion
# ---------------------------------------------------------------------------------------------------

DISTANCIA_MAXIMA_DE_LECTURA = 8


def _anidadas(sentencia: c.Sentencia) -> Iterator[c.Sentencia]:
    """Una sentencia y todas las que contiene, en orden de aparicion."""
    yield sentencia
    for bloque in c.bloques_hijos(sentencia):
        for interna in bloque.items:
            yield from _anidadas(interna)


def _nombres_en(sentencia: c.Sentencia) -> set[str]:
    """Identificadores que menciona una sentencia y lo que contiene; una declaracion con inicial cuenta."""
    nombres: set[str] = set()
    for interna in _anidadas(sentencia):
        if isinstance(interna, c.Decl) and interna.inicial is not None:
            nombres.add(interna.nombre)
        for raiz in c.expresiones_de(interna):
            nombres |= an.identificadores_de(raiz)
    return nombres


def _renombrar_en(sentencias: list[c.Sentencia], viejo: str, nuevo: str) -> None:
    """Cambia ``viejo`` por ``nuevo`` en cada aparicion de la variable dentro de las sentencias."""
    for sentencia in sentencias:
        for interna in _anidadas(sentencia):
            for raiz in c.expresiones_de(interna):
                for nodo in c.recorrer(raiz):
                    if isinstance(nodo, c.Id) and nodo.nombre == viejo:
                        nodo.nombre = nuevo


def _asigna_antes_de_leer(sentencia: c.Sentencia, nombre: str) -> bool:
    """La sentencia da valor a la variable sin leerla: ``x = e`` o ``for (x = e; ...)`` ``e`` sin ``x``."""
    expr = sentencia.expr if isinstance(sentencia, c.Expresion) else None
    if isinstance(sentencia, c.Para):
        expr = sentencia.inicio
    return (
        isinstance(expr, c.Asigna)
        and expr.op == "="
        and isinstance(expr.destino, c.Id)
        and expr.destino.nombre == nombre
        and nombre not in an.identificadores_de(expr.valor)
    )


def _empieza_asignando(sentencias: list[c.Sentencia], nombre: str) -> bool:
    """La primera sentencia que menciona la variable le da valor antes de leerla."""
    primera = next((s for s in sentencias if nombre in _nombres_en(s)), None)
    return primera is not None and _asigna_antes_de_leer(primera, nombre)


def _nombres_vedados(ctx: Contexto) -> set[str]:
    """Variables que las mutaciones de locales no tocan: ambiguas, con direccion tomada o parametros."""
    con_direccion = {ubicacion[2:] for ubicacion in _locales_con_direccion(ctx.funcion)}
    return nombres_ambiguos(ctx.funcion) | con_direccion | ctx.entorno.parametros


def _declaraciones_simples(ctx: Contexto) -> dict[str, tuple[c.Bloque, c.Decl]]:
    """Declaraciones de variables escalares o agregadas sin declarador, con su bloque, por nombre."""
    vedados = _nombres_vedados(ctx)
    simples: dict[str, tuple[c.Bloque, c.Decl]] = {}
    for bloque in c.todos_los_bloques(ctx.funcion.cuerpo):
        for sentencia in bloque.items:
            esta_permitida = (
                isinstance(sentencia, c.Decl)
                and not sentencia.sufijo
                and not sentencia.declarador
                and sentencia.nombre not in vedados
            )
            if isinstance(sentencia, c.Decl) and esta_permitida:
                simples[sentencia.nombre] = (bloque, sentencia)
    return simples


def _declarar_como(ctx: Contexto, nombre: str, modelo: c.Decl) -> None:
    """Declara ``nombre`` al inicio de la funcion con el mismo tipo que ``modelo``."""
    cuerpo = ctx.funcion.cuerpo
    cuerpo.items.insert(_fin_de_declaraciones(cuerpo), c.Decl(modelo.base, modelo.estrellas, nombre))
    ctx.entorno.locales[nombre] = ctx.entorno.locales.get(
        modelo.nombre, an.parsear_tipo(modelo.base, modelo.estrellas)
    )


# --- lectura anticipada de un campo --------------------------------------------------------------------


def _posiciones_de_lectura(
    ctx: Contexto, bloque: c.Bloque, indice: int, carga: c.Expr, memoria: dict[int, an.Efectos]
) -> list[int]:
    """
    Posiciones del bloque donde se puede leer ``carga`` en lugar de en la sentencia ``indice``.

    Se sube sentencia a sentencia mientras ninguna de las que se cruzan (con todo lo que contienen)
    escriba lo que la carga lee ni sea una barrera, sin pasar de la serie de declaraciones del bloque
    ni de ``DISTANCIA_MAXIMA_DE_LECTURA`` sentencias. ``memoria`` guarda los efectos ya calculados de
    cada sentencia (por identidad) para no recorrerla otra vez en cada candidato.
    """
    lectura = an.efectos_de(c.Expresion(expr=carga), ctx.alias)
    piso = max(_fin_de_declaraciones(bloque), indice - DISTANCIA_MAXIMA_DE_LECTURA)
    posiciones = [indice]
    posicion = indice
    while posicion > piso:
        vecina = bloque.items[posicion - 1]
        efectos = memoria.setdefault(id(vecina), an.efectos_profundos(vecina, ctx.alias))
        if an.escritura_alcanza(efectos, lectura):
            break
        posicion -= 1
        posiciones.append(posicion)
    return posiciones


def _cargas_adelantables(ctx: Contexto) -> list[tuple[c.Bloque, int, Sitio, an.Tipo, int]]:
    """Accesos escalares a campo o indice con cada posicion anterior donde se pueden leer."""
    vedados = _nombres_vedados(ctx) - ctx.entorno.parametros
    candidatos: list[tuple[c.Bloque, int, Sitio, an.Tipo, int]] = []
    memoria: dict[int, an.Efectos] = {}
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        if not isinstance(sentencia, c.Expresion | c.Devolver | c.Si | c.Seleccion):
            continue
        for raiz in c.expresiones_de(sentencia):
            if not _aparicion_unica_de_asignacion(raiz):
                continue
            for sitio in sitios_de(raiz, sentencia):
                tipo = ctx.entorno.inferir(sitio.nodo)
                es_carga = (
                    isinstance(sitio.nodo, c.Miembro | c.Indice)
                    and tipo is not None
                    and tipo.es_escalar
                    and not sitio.perezoso
                    and not sitio.lvalue
                    and an.es_pura(sitio.nodo)
                    and not an.identificadores_de(sitio.nodo) & vedados
                )
                if es_carga and tipo is not None:
                    candidatos.extend(
                        (bloque, indice, sitio, tipo, posicion)
                        for posicion in _posiciones_de_lectura(ctx, bloque, indice, sitio.nodo, memoria)
                    )
    return candidatos


def local_de_campo(ctx: Contexto) -> str | None:
    """
    Lee un campo o un elemento en una local nueva, asignada en una sentencia anterior del mismo bloque.

    Contexto:
        Cuando el original carga un valor antes de tocar otros (por ejemplo el tipo de una orden antes
        de modificar las banderas del objeto), la carga es la primera del bloque y el valor ocupa un
        registro propio durante todo el tramo; leerlo donde se usa lo carga mas tarde y con otro
        registro. La lectura solo sube por encima de sentencias que, con todo lo que contienen, no
        escriben esa memoria (ruta de campo solapada, escritura por puntero opaco o cambio de una
        variable de la direccion) y no hacen llamadas ni saltos. Se diferencia de
        ``introducir_temporal`` en que la sentencia que sube puede cruzar un ``if`` o un bucle que no
        toca la memoria y en que cada posicion posible es una variante distinta. La local es siempre
        nueva y del tipo exacto del campo, y las sentencias de usos con efectos propios se excluyen.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna lectura escalar se puede adelantar.

    Ejemplo:
        descripcion = local_de_campo(contexto)
    """
    elegido = _elegir(ctx.azar, _cargas_adelantables(ctx))
    if elegido is None:
        return None
    bloque, indice, sitio, tipo, posicion = elegido
    sentencia = bloque.items[indice]
    nombre = _nombre_temporal(ctx)
    clave = an.texto_de(sitio.nodo)
    copia = copy.deepcopy(sitio.nodo)
    if ctx.azar.random() < PROBABILIDAD_TODAS_LAS_APARICIONES:
        for raiz in c.expresiones_de(sentencia):
            for otro in list(sitios_de(raiz, sentencia)):
                if not otro.lvalue and not otro.perezoso and an.texto_de(otro.nodo) == clave:
                    c.reemplazar_hijo(otro.padre, otro.nodo, c.Id(nombre))
    else:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, c.Id(nombre))
    bloque.items.insert(posicion, c.Expresion(expr=c.Asigna("=", c.Id(nombre), copia)))
    _declarar_temporal(ctx, nombre, tipo)
    return f"local_de_campo({tipo.texto} {nombre} = {clave}, {indice - posicion} antes)"


# --- relectura en la condicion de un bucle -------------------------------------------------------------


def _carga_de_memoria(expr: c.Expr) -> bool:
    """Una expresion pura que lee memoria: contiene un campo, un indice o una desreferencia."""
    es_acceso = any(
        isinstance(n, c.Miembro | c.Indice) or (isinstance(n, c.Unario) and n.op == "*")
        for n in c.recorrer(expr)
    )
    return es_acceso and an.es_pura(expr)


def _asignacion_unica_de_local(
    sentencia: c.Sentencia, declaraciones: dict[str, tuple[c.Bloque, c.Decl]]
) -> tuple[str, c.Expr] | None:
    """Nombre y fuente si la sentencia da su unico valor a una local simple: ``x = e;`` o ``T x = e;``."""
    if isinstance(sentencia, c.Decl):
        if sentencia.inicial is not None and sentencia.nombre in declaraciones:
            return sentencia.nombre, sentencia.inicial
        return None
    if (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and isinstance(sentencia.expr.destino, c.Id)
        and sentencia.expr.destino.nombre in declaraciones
        and declaraciones[sentencia.expr.destino.nombre][1].inicial is None
    ):
        return sentencia.expr.destino.nombre, sentencia.expr.valor
    return None


def _es_uso_en_condicion_de_bucle(sentencia: c.Sentencia, nodo: c.Expr) -> bool:
    """El nodo forma parte de la condicion de un ``while``, ``do`` o ``for``."""
    if not isinstance(sentencia, c.Mientras | c.HacerMientras | c.Para) or sentencia.cond is None:
        return False
    return any(hijo is nodo for hijo in c.recorrer(sentencia.cond))


def _lecturas_de_local_guardada(
    ctx: Contexto, bloque: c.Bloque, indice: int, nombre: str, fuente: c.Expr
) -> list[Sitio] | None:
    """
    Lecturas de una local que se pueden sustituir por su fuente, o ``None`` si no se puede.

    Todas las apariciones deben ser lecturas posteriores a la asignacion y del mismo bloque, al menos
    una debe estar en la condicion de un bucle y nada de lo que hay entre la asignacion y la ultima
    lectura (bucles enteros incluidos) puede escribir lo que la fuente lee.
    """
    sentencia = bloque.items[indice]
    usos = _usos_de(ctx.funcion, nombre)
    escrituras = [sitio for _, sitio in usos if sitio.lvalue]
    lecturas = [(s, sitio) for s, sitio in usos if not sitio.lvalue]
    if len(escrituras) != (0 if isinstance(sentencia, c.Decl) else 1) or not lecturas:
        return None
    posteriores = bloque.items[indice + 1 :]
    posicion_de = {id(interna): j for j, s in enumerate(posteriores) for interna in _anidadas(s)}
    if any(id(s) not in posicion_de for s, _ in lecturas):
        return None
    if not any(_es_uso_en_condicion_de_bucle(s, sitio.nodo) for s, sitio in lecturas):
        return None
    lectura = an.efectos_de(c.Expresion(expr=fuente), ctx.alias)
    ultima = max(posicion_de[id(s)] for s, _ in lecturas)
    for intermedia in posteriores[: ultima + 1]:
        if an.escritura_alcanza(an.efectos_profundos(intermedia, ctx.alias), lectura):
            return None
    return [sitio for _, sitio in lecturas]


def _lecturas_releibles(ctx: Contexto) -> list[tuple[c.Bloque, int, str, c.Expr, list[Sitio]]]:
    """Locales de una sola asignacion desde memoria cuyas lecturas se pueden volver a hacer en su sitio."""
    declaraciones = _declaraciones_simples(ctx)
    vedados = _nombres_vedados(ctx) - ctx.entorno.parametros
    resultado: list[tuple[c.Bloque, int, str, c.Expr, list[Sitio]]] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        asignacion = _asignacion_unica_de_local(sentencia, declaraciones)
        if asignacion is None or sentencia.comentarios:
            continue
        nombre, fuente = asignacion
        origen, destino = ctx.entorno.inferir(fuente), ctx.entorno.locales.get(nombre)
        compatible = (
            origen is not None
            and destino is not None
            and an.promover(origen) == an.promover(destino)
            and (origen.texto == destino.texto or an.conserva_valor(origen, destino))
        )
        identificadores = an.identificadores_de(fuente)
        if not (
            compatible
            and _carga_de_memoria(fuente)
            and nombre not in identificadores
            and not identificadores & vedados
        ):
            continue
        sitios = _lecturas_de_local_guardada(ctx, bloque, indice, nombre, fuente)
        if sitios is not None:
            resultado.append((bloque, indice, nombre, fuente, sitios))
    return resultado


def releer_en_condicion(ctx: Contexto) -> str | None:
    """
    Sustituye una local que guarda una lectura de memoria por esa lectura en cada uso.

    Contexto:
        Si la cuenta de un bucle se guarda en una local, el compilador la carga una vez y la conserva en
        un registro con una copia; si se relee en la condicion, la carga de la guarda del bucle y la
        de la condicion se funden y la copia desaparece. Es la operacion inversa de guardar una
        lectura en una local. Solo se aplica a una local asignada una vez desde una expresion pura que
        lee memoria, con todas sus lecturas posteriores en el mismo bloque, al menos una en la condicion
        de un bucle y sin ninguna escritura que llegue a esa memoria (ni llamada) entre la asignacion y
        la ultima lectura, cuerpos de bucle incluidos. La local y su declaracion desaparecen.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local cumple las condiciones.

    Ejemplo:
        descripcion = releer_en_condicion(contexto)
    """
    elegido = _elegir(ctx.azar, _lecturas_releibles(ctx))
    if elegido is None:
        return None
    bloque, indice, nombre, fuente, sitios = elegido
    for sitio in sitios:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, copy.deepcopy(fuente))
    # Primero la asignacion: quitar antes la declaracion del mismo bloque desplazaria su posicion.
    asignacion = bloque.items.pop(indice)
    if not isinstance(asignacion, c.Decl):
        _quitar_declaracion(ctx.funcion, nombre)
    ctx.entorno.locales.pop(nombre, None)
    return f"releer_en_condicion({nombre} = {an.texto_de(fuente)})"


# --- union de dos locales de vidas disjuntas -----------------------------------------------------------


def _locales_unificables(ctx: Contexto) -> list[tuple[str, str]]:
    """
    Pares (primera, segunda) de locales del mismo tipo cuyas vidas no se solapan.

    La vida de una local es el conjunto de sentencias del cuerpo (con todo lo que contienen) que la
    mencionan. La segunda se funde en la primera si todas las sentencias de la primera terminan antes
    de la primera de la segunda, y esa primera sentencia le da valor antes de leerla. Una funcion con
    ``goto`` o etiquetas no se toca: un salto hacia atras alargaria la vida de la primera.
    """
    funcion = ctx.funcion
    cuerpo = funcion.cuerpo
    if any(isinstance(s, c.Etiqueta | c.Saltar) for _, _, s in _sentencias(funcion)):
        return []
    declaraciones = _declaraciones_simples(ctx)
    del_cuerpo = {s.nombre for s in cuerpo.items if isinstance(s, c.Decl)}
    menciones = [_nombres_en(s) for s in cuerpo.items]
    pares: list[tuple[str, str]] = []
    for primera, (_, decl_primera) in declaraciones.items():
        for segunda, (_, decl_segunda) in declaraciones.items():
            if (
                primera == segunda
                or primera not in del_cuerpo
                or decl_segunda.inicial is not None
                or not _tipos_unificables(ctx, decl_primera, decl_segunda)
            ):
                continue
            en_primera = [i for i, nombres in enumerate(menciones) if primera in nombres]
            en_segunda = [i for i, nombres in enumerate(menciones) if segunda in nombres]
            if (
                en_primera
                and en_segunda
                and max(en_primera) < min(en_segunda)
                and _asigna_antes_de_leer(cuerpo.items[min(en_segunda)], segunda)
            ):
                pares.append((primera, segunda))
    return pares


def unificar_locales(ctx: Contexto) -> str | None:
    """
    Funde dos locales del mismo tipo de vidas disjuntas en una sola.

    Contexto:
        Con una variable menos el compilador numera distinto los pseudoregistros y reparte de otro modo
        los registros salvados: dos contadores de bucles consecutivos pasan a ser el mismo registro.
        Se funde la segunda en la primera cuando todas las sentencias del cuerpo que mencionan la
        primera terminan antes de la primera que menciona la segunda, la segunda se asigna antes de
        leerse en su primera sentencia (una asignacion o el inicio de un ``for``), las dos tienen el mismo
        tipo, ninguna tiene direccion tomada, es parametro o nombre ambiguo, la primera esta
        declarada en el cuerpo de la funcion (para ser visible en todo el tramo) y la segunda no
        tiene inicializador. Se renombran las apariciones de la segunda y se retira su declaracion.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ningun par de locales cumple las condiciones.

    Ejemplo:
        descripcion = unificar_locales(contexto)
    """
    elegido = _elegir(ctx.azar, _locales_unificables(ctx))
    if elegido is None:
        return None
    primera, segunda = elegido
    _renombrar_en(ctx.funcion.cuerpo.items, segunda, primera)
    _quitar_declaracion(ctx.funcion, segunda)
    ctx.entorno.locales.pop(segunda, None)
    return f"unificar_locales({segunda} en {primera})"


# --- particion de una local compartida entre ramas -----------------------------------------------------


def _ramas_de_si(si: c.Si) -> list[list[c.Sentencia]]:
    """Cuerpos de las ramas de un ``if`` y de su cadena ``else if`` (como las escribe el escritor de C)."""
    ramas = [si.entonces.items]
    actual = si
    while actual.sino is not None:
        sino = actual.sino
        unico = sino.items[0] if len(sino.items) == 1 else None
        if isinstance(unico, c.Si) and not unico.comentarios and not sino.finales:
            actual = unico
            ramas.append(actual.entonces.items)
        else:
            ramas.append(sino.items)
            break
    return ramas


def _segmentos_de_seleccion(seleccion: c.Seleccion) -> list[list[c.Sentencia]]:
    """Sentencias que siguen a cada ``case`` o ``default`` de un ``switch`` (el primer segmento es previo)."""
    segmentos: list[list[c.Sentencia]] = [[]]
    for sentencia in seleccion.cuerpo.items:
        if isinstance(sentencia, c.Caso):
            segmentos.append([])
        else:
            segmentos[-1].append(sentencia)
    return segmentos


def _ramas_independientes(sentencia: c.Sentencia, nombre: str) -> list[list[c.Sentencia]] | None:
    """
    Ramas de un ``if`` o ``switch`` que mencionan la variable, o ``None`` si no se puede partir.

    Cada rama que la menciona debe empezar dandole valor; en un ``switch`` toda rama que la menciona,
    salvo la ultima, debe terminar en ``break`` o ``return`` (si no, caeria en la siguiente).
    """
    if isinstance(sentencia, c.Si):
        ramas = _ramas_de_si(sentencia)
    elif isinstance(sentencia, c.Seleccion):
        ramas = _segmentos_de_seleccion(sentencia)
    else:
        return None
    con_nombre = [rama for rama in ramas if any(nombre in _nombres_en(s) for s in rama)]
    if len(con_nombre) < 2 or not all(_empieza_asignando(rama, nombre) for rama in con_nombre):
        return None
    if isinstance(sentencia, c.Seleccion) and not all(
        rama and isinstance(rama[-1], c.Romper | c.Devolver) for rama in con_nombre[:-1]
    ):
        return None
    return con_nombre


def _locales_partibles(ctx: Contexto) -> list[tuple[str, list[list[c.Sentencia]]]]:
    """Variables locales cuyas apariciones estan todas en dos o mas ramas independientes de una sentencia."""
    resultado: list[tuple[str, list[list[c.Sentencia]]]] = []
    declaraciones = _declaraciones_simples(ctx)
    total = {
        nombre: len(_usos_de(ctx.funcion, nombre))
        for nombre, (_, d) in declaraciones.items()
        if not d.inicial
    }
    for _, _, sentencia in _sentencias(ctx.funcion):
        for nombre, cantidad in total.items():
            ramas = _ramas_independientes(sentencia, nombre)
            if ramas is None:
                continue
            dentro = sum(
                1
                for rama in ramas
                for s in rama
                for interna in _anidadas(s)
                for raiz in c.expresiones_de(interna)
                for nodo in c.recorrer(raiz)
                if isinstance(nodo, c.Id) and nodo.nombre == nombre
            )
            if dentro == cantidad:
                resultado.append((nombre, ramas))
    return resultado


def partir_local(ctx: Contexto) -> str | None:
    """
    Reparte una local usada en varias ramas de un ``if`` o ``switch`` en una local por rama.

    Contexto:
        Operacion inversa de ``unificar_locales``: una variable compartida por ramas excluyentes se
        reparte en un registro comun para todas; con una local por rama cada una vive solo en su
        tramo y el compilador la numera y la reparte aparte. Solo se parte una local sin
        inicializador, sin direccion tomada, cuyas apariciones estan todas dentro de las ramas de una
        misma sentencia (ni en sus condiciones ni fuera de ella), con dos o mas ramas que la mencionen
        y cada una empezando por darle valor. La primera rama conserva el nombre; las demas usan locales
        nuevas del mismo tipo con el nombre ``tmpN``.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local es partible.

    Ejemplo:
        descripcion = partir_local(contexto)
    """
    elegido = _elegir(ctx.azar, _locales_partibles(ctx))
    if elegido is None:
        return None
    nombre, ramas = elegido
    modelo = _declaraciones_simples(ctx)[nombre][1]
    nuevos: list[str] = []
    for rama in ramas[1:]:
        nuevo = _nombre_temporal(ctx)
        _renombrar_en(rama, nombre, nuevo)
        _declarar_como(ctx, nuevo, modelo)
        nuevos.append(nuevo)
    return f"partir_local({nombre} en {', '.join(nuevos)})"


# ---------------------------------------------------------------------------------------------------
# Copia de un campo en una local
# ---------------------------------------------------------------------------------------------------

OPERADORES_DE_COMPARACION = frozenset({"==", "!=", "<", ">", "<=", ">="})
OPERADORES_SENSIBLES_AL_SIGNO = frozenset({">>", "<", ">", "<=", ">="})
OPERADORES_DE_ASIGNACION_COMPUESTA = frozenset(f"{op}=" for op in OPERADORES_COMPUESTOS)


@dataclass(frozen=True)
class CopiaDeCampo:
    """Una local que copia el resultado de ``campo operador operando`` y se vuelve a almacenar en el campo.

    Attributes:
        bloque: Bloque que contiene la asignacion de la local y todos sus usos.
        indice: Posicion de la sentencia que da valor a la local.
        nombre: Nombre de la local.
        campo: Acceso a memoria cuyo valor se copia (``o->flags14``).
        operador: Operador de la primera operacion (``|``).
        operando: Segundo operando de esa operacion.
        primer_uso: Sentencia ``campo = local;`` que devuelve la copia al campo.
        almacen: Ultima sentencia ``campo = local op2 operando2;``, si existe.
        comparaciones: Lecturas de la local como operando de una comparacion.
    """

    bloque: c.Bloque
    indice: int
    nombre: str
    campo: c.Expr
    operador: str
    operando: c.Expr
    primer_uso: c.Expresion
    almacen: c.Expresion | None
    comparaciones: tuple[Sitio, ...]


def _es_acceso_a_memoria(expr: c.Expr) -> bool:
    """Un campo o un elemento sin efectos: el unico destino que admite la copia."""
    return isinstance(expr, c.Miembro | c.Indice) and an.es_pura(expr)


def _descomponer_copia(fuente: c.Expr) -> tuple[c.Expr, str, c.Expr] | None:
    """
    Separa ``campo op operando`` (o ``operando op campo`` si ``op`` conmuta) en sus tres partes.

    Devuelve ``None`` si la expresion no tiene esa forma, tiene efectos o el operando repite el campo.
    """
    if not (isinstance(fuente, c.Binario) and fuente.op in OPERADORES_COMPUESTOS and an.es_pura(fuente)):
        return None
    if _es_acceso_a_memoria(fuente.izq):
        campo, resto = fuente.izq, fuente.der
    elif fuente.op in OPERADORES_COMPUESTOS_CONMUTATIVOS and _es_acceso_a_memoria(fuente.der):
        campo, resto = fuente.der, fuente.izq
    else:
        return None
    clave = an.texto_de(campo)
    if any(an.texto_de(nodo) == clave for nodo in c.recorrer(resto)):
        return None
    return campo, fuente.op, resto


def _tipos_de_copia(campo: an.Tipo | None, local: an.Tipo | None) -> bool | None:
    """
    Compara el tipo del campo con el de la local que lo copia.

    Devuelve ``None`` si sustituir la local por el campo podria cambiar un valor: ambos deben ser
    enteros del mismo ancho, y si el ancho es menor de 32 bits tambien del mismo signo (la copia
    trunca igual que el campo). Si son de 32 bits con distinto signo la sustitucion conserva los bits
    pero no el resultado de ``>>`` ni el de las comparaciones de orden; se devuelve ``False`` para que
    el llamador las excluya. ``True`` si el signo coincide.
    """
    if campo is None or local is None or not (campo.es_entero and local.es_entero):
        return None
    if campo.ancho != local.ancho or (campo.ancho < 32 and campo.con_signo != local.con_signo):
        return None
    return campo.con_signo == local.con_signo


def _es_copia_al_campo(sentencia: c.Sentencia, clave: str, nombre: str) -> bool:
    """La sentencia es ``campo = local;``."""
    return (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and an.texto_de(sentencia.expr.destino) == clave
        and isinstance(sentencia.expr.valor, c.Id)
        and sentencia.expr.valor.nombre == nombre
    )


def _es_almacen_al_campo(sentencia: c.Sentencia, clave: str, nombre: str) -> bool:
    """La sentencia es ``campo = local op2 operando2;`` con ``operando2`` puro y sin la local."""
    if not (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and an.texto_de(sentencia.expr.destino) == clave
    ):
        return False
    valor = sentencia.expr.valor
    return (
        isinstance(valor, c.Binario)
        and valor.op in OPERADORES_COMPUESTOS
        and isinstance(valor.izq, c.Id)
        and valor.izq.nombre == nombre
        and an.es_pura(valor.der)
        and nombre not in an.identificadores_de(valor.der)
    )


def _operador_de_comparacion(sitio: Sitio) -> str | None:
    """Operador de comparacion que tiene al sitio como operando, o ``None`` si el padre es otra cosa."""
    padre = sitio.padre
    if isinstance(padre, c.Binario) and padre.op in OPERADORES_DE_COMPARACION:
        return padre.op
    return None


def _operador_de_almacen(almacen: c.Expresion | None) -> str | None:
    """Operador ``op2`` del almacen ``campo = local op2 operando2;``, o ``None`` si no hay almacen."""
    if (
        almacen is not None
        and isinstance(almacen.expr, c.Asigna)
        and isinstance(almacen.expr.valor, c.Binario)
    ):
        return almacen.expr.valor.op
    return None


def _clasificar_usos(
    posteriores: list[c.Sentencia],
    lecturas: list[tuple[c.Sentencia, Sitio]],
    posicion_de: dict[int, int],
    clave: str,
    nombre: str,
) -> tuple[c.Expresion, c.Expresion | None, list[Sitio]] | None:
    """
    Reparte las lecturas de la local en su primer uso, su almacen final y sus comparaciones.

    El primer uso debe ser ``campo = local;`` y el unico de su sentencia. Cualquier otra lectura es una
    comparacion o la ultima sentencia ``campo = local op2 operando2;`` (solo puede haber una y debe ir
    la ultima, porque despues de almacenarla el campo deja de valer lo mismo que la local). Una lectura
    de otro tipo hace que la local no se pueda propagar.
    """
    primero = min(posicion_de[id(s)] for s, _ in lecturas)
    ultimo = max(posicion_de[id(s)] for s, _ in lecturas)
    primer_uso = posteriores[primero]
    en_primero = [sitio for s, sitio in lecturas if posicion_de[id(s)] == primero]
    if len(en_primero) != 1 or not _es_copia_al_campo(primer_uso, clave, nombre):
        return None
    almacen: c.Expresion | None = None
    comparaciones: list[Sitio] = []
    for sentencia, sitio in lecturas:
        posicion = posicion_de[id(sentencia)]
        if posicion == primero:
            continue
        if sentencia is posteriores[posicion] and _es_almacen_al_campo(sentencia, clave, nombre):
            if posicion != ultimo or not isinstance(sentencia, c.Expresion):
                return None
            almacen = sentencia
        elif _operador_de_comparacion(sitio) is not None:
            comparaciones.append(sitio)
        else:
            return None
    assert isinstance(primer_uso, c.Expresion)  # noqa: S101 - ``_es_copia_al_campo`` lo garantiza
    return primer_uso, almacen, comparaciones


def _sin_escrituras_en_el_tramo(
    ctx: Contexto,
    tramo: list[c.Sentencia],
    lectura: an.Efectos,
    salvo: c.Sentencia | None = None,
) -> bool:
    """Ninguna sentencia del tramo (con su contenido) escribe lo que lee la expresion ni es barrera."""
    return not any(
        an.escritura_alcanza(an.efectos_profundos(sentencia, ctx.alias), lectura)
        for sentencia in tramo
        if sentencia is not salvo
    )


def _copia_propagable(
    ctx: Contexto, bloque: c.Bloque, indice: int, nombre: str, partes: tuple[c.Expr, str, c.Expr]
) -> CopiaDeCampo | None:
    """
    Comprueba que la local asignada en ``bloque.items[indice]`` se puede sustituir por su campo.

    Reglas: tipos compatibles (``_tipos_de_copia``), una sola asignacion de la local, todas sus
    lecturas despues de ella y en el mismo bloque, primer uso ``campo = local;``, usos restantes en
    comparaciones o en el almacen final, y ninguna escritura que alcance al campo ni llamada entre la
    copia y el ultimo uso, ni a lo que lee la primera operacion entre la asignacion y la copia.
    """
    campo, operador, operando = partes
    mismo_signo = _tipos_de_copia(ctx.entorno.inferir(campo), ctx.entorno.locales.get(nombre))
    usos = _usos_de(ctx.funcion, nombre)
    lecturas = [(s, sitio) for s, sitio in usos if not sitio.lvalue]
    esperadas = 0 if isinstance(bloque.items[indice], c.Decl) else 1
    if mismo_signo is None or len(usos) - len(lecturas) != esperadas or not lecturas:
        return None
    posteriores = bloque.items[indice + 1 :]
    posicion_de = {id(interna): j for j, s in enumerate(posteriores) for interna in _anidadas(s)}
    if any(id(s) not in posicion_de for s, _ in lecturas):
        return None
    clave = an.texto_de(campo)
    clasificados = _clasificar_usos(posteriores, lecturas, posicion_de, clave, nombre)
    if clasificados is None:
        return None
    primer_uso, almacen, comparaciones = clasificados
    operadores = {_operador_de_comparacion(s) for s in comparaciones} | {_operador_de_almacen(almacen)}
    if operadores & OPERADORES_SENSIBLES_AL_SIGNO and not mismo_signo:
        return None
    primero = min(posicion_de[id(s)] for s, _ in lecturas)
    ultimo = max(posicion_de[id(s)] for s, _ in lecturas)
    inicial = an.efectos_de(c.Expresion(expr=c.Binario(operador, campo, operando)), ctx.alias)
    lectura_del_campo = an.efectos_de(c.Expresion(expr=campo), ctx.alias)
    libre = _sin_escrituras_en_el_tramo(ctx, posteriores[:primero], inicial) and _sin_escrituras_en_el_tramo(
        ctx, posteriores[primero + 1 : ultimo + 1], lectura_del_campo, almacen
    )
    if not libre:
        return None
    return CopiaDeCampo(
        bloque, indice, nombre, campo, operador, operando, primer_uso, almacen, tuple(comparaciones)
    )


def _copias_de_campo(ctx: Contexto) -> list[CopiaDeCampo]:
    """Locales asignadas una vez desde ``campo op operando`` cuya copia al campo se puede eliminar."""
    declaraciones = _declaraciones_simples(ctx)
    vedados = _nombres_vedados(ctx) - ctx.entorno.parametros
    resultado: list[CopiaDeCampo] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        asignacion = _asignacion_unica_de_local(sentencia, declaraciones)
        if asignacion is None or sentencia.comentarios:
            continue
        nombre, fuente = asignacion
        partes = _descomponer_copia(fuente)
        if partes is None or nombre in an.identificadores_de(fuente):
            continue
        if an.identificadores_de(partes[0]) & vedados:
            continue
        copia = _copia_propagable(ctx, bloque, indice, nombre, partes)
        if copia is not None:
            resultado.append(copia)
    return resultado


def propagar_copia_de_campo(ctx: Contexto) -> str | None:
    """
    Elimina una local que copia ``campo op c`` y la devuelve al campo, usando asignaciones compuestas.

    Contexto:
        ``f = o->flags14 | 2; o->flags14 = f; ...; o->flags14 = f & mascara;`` crea una copia ``move``
        que el compilador mantiene en otro registro mientras vive ``f``. Con ``o->flags14 |= 2; ...;
        o->flags14 &= mascara;`` el valor cargado se reutiliza en el mismo registro y la copia
        desaparece. Solo se aplica si la local se asigna una vez desde un campo o elemento puro y un
        operando puro, su primer uso es ``campo = local;``,
        el resto de sus usos son comparaciones o un almacen final ``campo = local op2 c2;``, y entre la
        copia y el ultimo uso nada escribe el campo (ruta solapada, alias de union, ``*p``, ``p[i]``) ni
        llama a funciones: asi la local vale siempre lo mismo que el campo y sustituirla no cambia nada.
        El campo y la local deben ser enteros del mismo ancho; con distinto signo se excluyen ``>>`` y
        las comparaciones de orden.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local cumple las condiciones.

    Ejemplo:
        descripcion = propagar_copia_de_campo(contexto)
    """
    copia = _elegir(ctx.azar, _copias_de_campo(ctx))
    if copia is None:
        return None
    asignacion = copia.primer_uso.expr
    assert isinstance(asignacion, c.Asigna)  # noqa: S101 - ``_es_copia_al_campo`` lo garantiza
    asignacion.op = f"{copia.operador}="
    asignacion.valor = copia.operando
    for sitio in copia.comparaciones:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, copy.deepcopy(copia.campo))
    if copia.almacen is not None:
        reescritura = copia.almacen.expr
        assert isinstance(reescritura, c.Asigna)  # noqa: S101 - ``_es_almacen_al_campo`` lo garantiza
        valor = reescritura.valor
        assert isinstance(valor, c.Binario)  # noqa: S101 - ``_es_almacen_al_campo`` lo garantiza
        reescritura.op = f"{valor.op}="
        reescritura.valor = valor.der
    expandida = an.texto_de(c.Binario(copia.operador, copia.campo, copia.operando))
    descripcion = f"propagar_copia_de_campo({copia.nombre} = {expandida})"
    sentencia = copia.bloque.items.pop(copia.indice)
    if not isinstance(sentencia, c.Decl):
        _quitar_declaracion(ctx.funcion, copia.nombre)
    ctx.entorno.locales.pop(copia.nombre, None)
    return descripcion


def _compuesta_sobre_campo(
    sentencia: c.Sentencia, clave: str | None = None
) -> tuple[c.Asigna, c.Binario] | None:
    """
    Reconoce ``campo op= operando;`` con campo y operando puros.

    Con ``clave`` solo acepta el campo cuyo texto coincida. Devuelve la asignacion y su forma expandida
    ``campo op operando`` (un nodo nuevo que comparte los hijos).
    """
    if not (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op in OPERADORES_DE_ASIGNACION_COMPUESTA
        and _es_acceso_a_memoria(sentencia.expr.destino)
        and an.es_pura(sentencia.expr.valor)
    ):
        return None
    asignacion = sentencia.expr
    if clave is not None and an.texto_de(asignacion.destino) != clave:
        return None
    return asignacion, c.Binario(asignacion.op[:-1], asignacion.destino, asignacion.valor)


def _pares_de_compuestas(ctx: Contexto) -> list[tuple[c.Bloque, int, int, an.Tipo]]:
    """
    Pares (primera, siguiente) de asignaciones compuestas al mismo campo con una local posible entre ellas.

    Para cada ``campo op= c`` se toma la siguiente ``campo op2= c2`` del bloque si entre las dos nada
    (con todo lo que contiene) escribe el campo ni hace llamadas. El campo debe ser un entero y no
    depender de variables con la direccion tomada.
    """
    vedados = _nombres_vedados(ctx) - ctx.entorno.parametros
    pares: list[tuple[c.Bloque, int, int, an.Tipo]] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        primera = _compuesta_sobre_campo(sentencia)
        if primera is None or an.identificadores_de(primera[0].destino) & vedados:
            continue
        tipo = ctx.entorno.inferir(primera[0].destino)
        if tipo is None or not tipo.es_entero:
            continue
        clave = an.texto_de(primera[0].destino)
        lectura = an.efectos_de(c.Expresion(expr=primera[0].destino), ctx.alias)
        for posicion in range(indice + 1, len(bloque.items)):
            if _compuesta_sobre_campo(bloque.items[posicion], clave) is not None:
                pares.append((bloque, indice, posicion, tipo))
                break
            if an.escritura_alcanza(an.efectos_profundos(bloque.items[posicion], ctx.alias), lectura):
                break
    return pares


def introducir_copia_de_campo(ctx: Contexto) -> str | None:
    """
    Pasa dos asignaciones compuestas al mismo campo a una local que se copia al campo y se reutiliza.

    Contexto:
        Operacion inversa de ``propagar_copia_de_campo``: ``o->flags14 |= 2; ...; o->flags14 &= m;``
        pasa a ``f = o->flags14 | 2; o->flags14 = f; ...; o->flags14 = f & m;``. Permite que el barrido
        deshaga la propagacion y explore la forma con la copia explicita. La local lleva el tipo exacto
        del campo y la sustitucion solo se hace entre dos sentencias del mismo bloque sin escrituras
        al campo ni llamadas entre ellas, de modo que la local vale lo mismo que el campo en el segundo
        uso.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si la funcion no tiene dos compuestas al mismo campo.

    Ejemplo:
        descripcion = introducir_copia_de_campo(contexto)
    """
    elegido = _elegir(ctx.azar, _pares_de_compuestas(ctx))
    if elegido is None:
        return None
    bloque, primera_posicion, segunda_posicion, tipo = elegido
    primera = _compuesta_sobre_campo(bloque.items[primera_posicion])
    segunda = _compuesta_sobre_campo(bloque.items[segunda_posicion])
    assert primera is not None and segunda is not None  # noqa: S101 - ``_pares_de_compuestas`` lo garantiza
    nombre = _nombre_temporal(ctx)
    campo = primera[0].destino
    obtener = c.Expresion(
        expr=c.Asigna("=", c.Id(nombre), primera[1]), comentarios=bloque.items[primera_posicion].comentarios
    )
    devolver = c.Expresion(expr=c.Asigna("=", copy.deepcopy(campo), c.Id(nombre)))
    segunda[0].valor = c.Binario(segunda[1].op, c.Id(nombre), segunda[0].valor)
    segunda[0].op = "="
    bloque.items[primera_posicion : primera_posicion + 1] = [obtener, devolver]
    _declarar_temporal(ctx, nombre, tipo)
    return f"introducir_copia_de_campo({tipo.texto} {nombre} = {an.texto_de(primera[1])})"


# ---------------------------------------------------------------------------------------------------
# Ayudantes comunes de las mutaciones de variables, bucles y copias
# ---------------------------------------------------------------------------------------------------

NARROW_ANCHOS = ("u8", "s8", "u16", "s16")
ALCANCE_MAXIMO_DE_DESPLAZAMIENTO = 8


def _nombres_inseguros(ctx: Contexto) -> set[str]:
    """Nombres que el analisis por nombre no puede seguir: ambiguos o con la direccion tomada."""
    con_direccion = {ubicacion[2:] for ubicacion in _locales_con_direccion(ctx.funcion)}
    return nombres_ambiguos(ctx.funcion) | con_direccion


def _es_id(expr: c.Expr, nombre: str) -> bool:
    """La expresion es exactamente el identificador ``nombre``."""
    return isinstance(expr, c.Id) and expr.nombre == nombre


def _nombres_escritos(expr: c.Expr) -> list[str]:
    """Variables que una expresion escribe de forma directa (``x = e``, ``x++``), con repeticion."""
    escritos: list[str] = []
    for nodo in c.recorrer(expr):
        if isinstance(nodo, c.Asigna) and isinstance(nodo.destino, c.Id):
            escritos.append(nodo.destino.nombre)
        elif (
            isinstance(nodo, c.Postfijo) or (isinstance(nodo, c.Unario) and nodo.op in ("++", "--"))
        ) and isinstance(nodo.operando, c.Id):
            escritos.append(nodo.operando.nombre)
    return escritos


def _escrituras_en(sentencia: c.Sentencia, nombre: str) -> int:
    """Cantidad de escrituras directas de una variable en una sentencia y en todo lo que contiene."""
    total = 0
    for interna in _anidadas(sentencia):
        if isinstance(interna, c.Decl) and interna.nombre == nombre and interna.inicial is not None:
            total += 1
        for raiz in c.expresiones_de(interna):
            total += _nombres_escritos(raiz).count(nombre)
    return total


def _escritos_en_sentencia(sentencia: c.Sentencia) -> set[str]:
    """Variables que una sentencia escribe de forma directa, con todo lo que contiene."""
    escritos: set[str] = set()
    for interna in _anidadas(sentencia):
        if isinstance(interna, c.Decl) and interna.inicial is not None:
            escritos.add(interna.nombre)
        for raiz in c.expresiones_de(interna):
            escritos.update(_nombres_escritos(raiz))
    return escritos


def _tiene_salto_o_etiqueta(sentencia: c.Sentencia) -> bool:
    """Una sentencia (o algo que contiene) es un ``goto``, una etiqueta o una directiva del preprocesador."""
    return any(isinstance(s, c.Etiqueta | c.Saltar | c.Preprocesador) for s in _anidadas(sentencia))


def _incremento_unitario(expr: c.Expr, nombre: str) -> bool:
    """La expresion suma uno a la variable: ``x++``, ``++x`` o ``x += 1``."""
    if isinstance(expr, c.Postfijo | c.Unario):
        return expr.op == "++" and _es_id(expr.operando, nombre)
    return (
        isinstance(expr, c.Asigna)
        and expr.op == "+="
        and _es_id(expr.destino, nombre)
        and an.valor_de_literal(expr.valor) == 1
    )


# --- copias vigentes: variables que valen lo mismo en un punto de un bloque ------------------------------


def _raiz_de_copia(representantes: dict[str, str], nombre: str) -> str:
    """Representante de la clase de variables que valen lo mismo que ``nombre``."""
    return representantes.get(nombre, nombre)


def _olvidar_copia(representantes: dict[str, str], nombre: str) -> None:
    """Anula lo sabido de ``nombre`` y de toda variable cuya clase lo tenia de representante."""
    representantes.pop(nombre, None)
    for otro in [clave for clave, raiz in representantes.items() if raiz == nombre]:
        del representantes[otro]


def _copia_simple(sentencia: c.Sentencia) -> tuple[str, str] | None:
    """Destino y origen si la sentencia es ``x = y;`` o ``T x = y;`` entre dos variables."""
    if isinstance(sentencia, c.Decl):
        valor = sentencia.inicial
        return (sentencia.nombre, valor.nombre) if isinstance(valor, c.Id) else None
    if (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and isinstance(sentencia.expr.destino, c.Id)
        and isinstance(sentencia.expr.valor, c.Id)
    ):
        return sentencia.expr.destino.nombre, sentencia.expr.valor.nombre
    return None


def _copias_vigentes(ctx: Contexto, bloque: c.Bloque, indice: int) -> dict[str, str]:
    """
    Calcula que variables valen lo mismo justo antes de ``bloque.items[indice]``.

    Contexto:
        Base de las mutaciones que cambian una variable por otra equivalente en ese punto. Solo se
        siguen copias directas ``x = y;`` entre variables locales o parametros del mismo tipo escalar,
        sin direccion tomada ni nombre ambiguo, dentro de las sentencias anteriores del mismo bloque.
        Cualquier escritura posterior a cualquiera de las dos variables, o una etiqueta o un salto,
        anula lo sabido. Lo que ocurre antes del bloque no se supone: es la hipotesis mas conservadora.

    Args:
        ctx (Contexto): Contexto de la ronda.
        bloque (c.Bloque): Bloque que contiene la sentencia.
        indice (int): Posicion de la sentencia.

    Returns:
        dict[str, str]: Para cada variable con copia vigente, el representante de su clase; dos
        variables valen lo mismo si tienen el mismo representante (``_raiz_de_copia``).

    Ejemplo:
        vigentes = _copias_vigentes(ctx, bloque, 3)
    """
    inseguros = _nombres_inseguros(ctx)
    representantes: dict[str, str] = {}
    for previa in bloque.items[:indice]:
        if _tiene_salto_o_etiqueta(previa):
            representantes.clear()
            continue
        for escrito in _escritos_en_sentencia(previa):
            _olvidar_copia(representantes, escrito)
        copia = _copia_simple(previa)
        if copia is None:
            continue
        destino, origen = copia
        tipos = (ctx.entorno.locales.get(destino), ctx.entorno.locales.get(origen))
        if (
            destino != origen
            and not {destino, origen} & inseguros
            and tipos[0] is not None
            and tipos[0] == tipos[1]
            and tipos[0].es_escalar
        ):
            representantes[destino] = _raiz_de_copia(representantes, origen)
    return representantes


def _valen_lo_mismo(representantes: dict[str, str], a: str, b: str) -> bool:
    """Las dos variables tienen copia vigente de la otra (o de una misma tercera)."""
    return a != b and _raiz_de_copia(representantes, a) == _raiz_de_copia(representantes, b)


# ---------------------------------------------------------------------------------------------------
# Bucle: puntero que avanza a acceso indexado
# ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Avance:
    """Sentencia o paso de ``for`` que suma uno a una variable en cada vuelta de un bucle.

    Attributes:
        posicion: Posicion en el cuerpo, o la cantidad de sentencias del cuerpo si es el paso de un ``for``.
        sentencia: Sentencia del cuerpo que lo contiene, o ``None`` si es parte del paso de un ``for``.
    """

    posicion: int
    sentencia: c.Sentencia | None


def _avances_unitarios(bucle: c.Mientras | c.HacerMientras | c.Para, nombre: str) -> list[_Avance]:
    """Avances de uno de una variable: sentencias del cuerpo o el paso del ``for`` (entero o con coma)."""
    avances = [
        _Avance(posicion, sentencia)
        for posicion, sentencia in enumerate(bucle.cuerpo.items)
        if isinstance(sentencia, c.Expresion) and not sentencia.comentarios
        if _incremento_unitario(sentencia.expr, nombre)
    ]
    paso = bucle.paso if isinstance(bucle, c.Para) else None
    if paso is not None:
        partes = [paso.izq, paso.der] if isinstance(paso, c.Binario) and paso.op == "," else [paso]
        avances.extend(
            _Avance(len(bucle.cuerpo.items), None) for p in partes if _incremento_unitario(p, nombre)
        )
    return avances


def _quitar_avance(bucle: c.Mientras | c.HacerMientras | c.Para, avance: _Avance, nombre: str) -> None:
    """Elimina un avance de uno de la sentencia o del paso del bucle."""
    if avance.sentencia is not None:
        bucle.cuerpo.items.remove(avance.sentencia)
        return
    # ``_avances_unitarios`` solo da un avance sin sentencia cuando es parte del paso de un ``for``.
    assert isinstance(bucle, c.Para) and bucle.paso is not None  # noqa: S101
    paso = bucle.paso
    if isinstance(paso, c.Binario) and paso.op == ",":
        bucle.paso = paso.der if _incremento_unitario(paso.izq, nombre) else paso.izq
    else:
        bucle.paso = None


def _reemplazo_por_indice(nodo: c.Expr, puntero: str, base: c.Expr, contador: str) -> c.Expr | None:
    """Acceso indexado equivalente a ``*p``, ``p->c`` o ``p[k]`` cuando ``p`` vale ``base + contador``."""
    elemento = c.Indice(copy.deepcopy(base), c.Id(contador))
    if isinstance(nodo, c.Unario) and nodo.op == "*" and _es_id(nodo.operando, puntero):
        return elemento
    if isinstance(nodo, c.Miembro) and nodo.flecha and _es_id(nodo.base, puntero):
        return c.Miembro(elemento, False, nodo.campo)
    if (
        isinstance(nodo, c.Indice)
        and _es_id(nodo.base, puntero)
        and an.es_pura(nodo.indice)
        and puntero not in an.identificadores_de(nodo.indice)
    ):
        desplazamiento = an.valor_de_literal(nodo.indice)
        if desplazamiento == 0:
            return elemento
        return c.Indice(copy.deepcopy(base), c.Binario("+", c.Id(contador), nodo.indice))
    return None


def _inicio_de_puntero(sentencia: c.Sentencia) -> tuple[str, str, str] | None:
    """Puntero, base y contador si la sentencia es ``p = base + i;`` o ``p = &base[i];``."""
    if not (
        isinstance(sentencia, c.Expresion)
        and not sentencia.comentarios
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and isinstance(sentencia.expr.destino, c.Id)
    ):
        return None
    valor = sentencia.expr.valor
    if isinstance(valor, c.Unario) and valor.op == "&":
        valor = (
            c.Binario("+", valor.operando.base, valor.operando.indice)
            if isinstance(valor.operando, c.Indice)
            else valor
        )
    if (
        isinstance(valor, c.Binario)
        and valor.op == "+"
        and isinstance(valor.izq, c.Id)
        and isinstance(valor.der, c.Id)
    ):
        return sentencia.expr.destino.nombre, valor.izq.nombre, valor.der.nombre
    return None


def _elemento_coincide(puntero: an.Tipo, base: an.Tipo) -> bool:
    """El tipo del puntero es el de la direccion de un elemento de ``base`` (arreglo o puntero)."""
    if base.arreglo:
        return puntero.base == base.base and puntero.estrellas == base.estrellas + 1
    return base.es_puntero and puntero.texto == base.texto


@dataclass(frozen=True)
class _PunteroIndexable:
    """Un bucle cuyo puntero de recorrido se puede sustituir por ``base[contador]``.

    Attributes:
        bloque: Bloque que contiene la inicializacion y el bucle.
        inicio: Sentencia ``p = base + i;`` que precede al bucle.
        bucle: El bucle.
        puntero: Nombre del puntero.
        contador: Nombre del contador que avanza a la par.
        base: Base del recorrido.
        usos: Pares (sitio, acceso indexado) que sustituyen cada uso del puntero.
        avance: Avance de uno del puntero.
    """

    bloque: c.Bloque
    inicio: c.Sentencia
    bucle: c.Mientras | c.HacerMientras | c.Para
    puntero: str
    contador: str
    base: c.Expr
    usos: tuple[tuple[Sitio, c.Expr], ...]
    avance: _Avance


def _usos_indexables(
    bucle: c.Mientras | c.HacerMientras | c.Para, puntero: str, base: c.Expr, contador: str
) -> tuple[list[tuple[Sitio, c.Expr, int | None]], int] | None:
    """
    Reune los accesos al puntero dentro del bucle y la cantidad de apariciones del identificador.

    Cada acceso se da con la posicion de la sentencia del cuerpo que lo contiene (``None`` si esta en la
    condicion). Devuelve ``None`` si el puntero aparece en la inicializacion o en el paso del ``for``.
    """
    posicion_de = {id(interna): j for j, s in enumerate(bucle.cuerpo.items) for interna in _anidadas(s)}
    accesos: list[tuple[Sitio, c.Expr, int | None]] = []
    apariciones = 0
    for interna in _anidadas(bucle):
        for raiz in c.expresiones_de(interna):
            for sitio in sitios_de(raiz, interna):
                apariciones += int(_es_id(sitio.nodo, puntero))
                reemplazo = _reemplazo_por_indice(sitio.nodo, puntero, base, contador)
                if reemplazo is None:
                    continue
                if interna is bucle:
                    if raiz is not bucle.cond:
                        return None
                    accesos.append((sitio, reemplazo, None))
                else:
                    accesos.append((sitio, reemplazo, posicion_de[id(interna)]))
    return accesos, apariciones


def _punteros_indexables(ctx: Contexto) -> list[_PunteroIndexable]:
    """
    Bucles cuyo puntero de recorrido ``p = base + i`` avanza uno por vuelta a la par que el contador ``i``.

    El puntero es una local simple sin inicializador cuyas apariciones son la inicializacion que precede
    al bucle, un unico avance de uno y accesos ``*p``, ``p->c`` o ``p[k]`` fuera del tramo que queda
    entre el avance del puntero y el del contador. La base y el contador son locales o parametros que el
    bucle no escribe (el contador solo en su avance) y el bucle no tiene ``continue``.
    """
    declaraciones = _declaraciones_simples(ctx)
    inseguros = _nombres_inseguros(ctx)
    encontrados: list[_PunteroIndexable] = []
    for bloque, indice, bucle in _sentencias(ctx.funcion):
        if indice == 0 or not isinstance(bucle, c.Mientras | c.HacerMientras | c.Para):
            continue
        datos = _inicio_de_puntero(bloque.items[indice - 1])
        if datos is None or _contiene_continuar(bucle.cuerpo):
            continue
        puntero, nombre_base, contador = datos
        base = c.Id(nombre_base)
        declaracion = declaraciones.get(puntero)
        tipo_base = ctx.entorno.locales.get(nombre_base)
        tipo_contador = ctx.entorno.locales.get(contador)
        if (
            declaracion is None
            or declaracion[1].inicial is not None
            or len({puntero, nombre_base, contador}) != 3
            or tipo_base is None
            or {nombre_base, contador} & inseguros
            or not _elemento_coincide(
                an.parsear_tipo(declaracion[1].base, declaracion[1].estrellas), tipo_base
            )
            or tipo_contador is None
            or not tipo_contador.es_entero
        ):
            continue
        avances_p, avances_i = _avances_unitarios(bucle, puntero), _avances_unitarios(bucle, contador)
        usos = _usos_indexables(bucle, puntero, base, contador)
        if (
            usos is None
            or len(avances_p) != 1
            or len(avances_i) != 1
            or _escrituras_en(bucle, puntero) != 1
            or _escrituras_en(bucle, contador) != 1
            or _escrituras_en(bucle, nombre_base) != 0
            or usos[1] != len(usos[0]) + 1
            or len(_usos_de(ctx.funcion, puntero)) != usos[1] + 1
        ):
            continue
        desde, hasta = sorted((avances_p[0].posicion, avances_i[0].posicion))
        if any(posicion is not None and desde < posicion < hasta for _, _, posicion in usos[0]):
            continue
        encontrados.append(
            _PunteroIndexable(
                bloque,
                bloque.items[indice - 1],
                bucle,
                puntero,
                contador,
                base,
                tuple((sitio, reemplazo) for sitio, reemplazo, _ in usos[0]),
                avances_p[0],
            )
        )
    return encontrados


def bucle_por_indice(ctx: Contexto) -> str | None:
    """
    Sustituye el puntero que recorre un bucle por el acceso indexado ``base[i]`` en todas sus sentencias.

    Contexto:
        ``p = base + i; while (...) { ... *p ... p++; i++; }`` mantiene dos variables de induccion; con
        ``base[i]`` el compilador conserva solo el contador y calcula la direccion en cada acceso, lo
        que cambia el reparto de registros y la forma del bucle. ``indice_o_puntero`` solo convierte un
        acceso suelto; aqui se reescriben todos los accesos del bucle a la vez, porque convertir solo
        una parte dejaria vivos el puntero y el contador. Solo se aplica si el puntero vale siempre
        ``base + i`` en los puntos donde se usa (avanza una unidad por vuelta a la par que ``i``), si no
        se usa tras el bucle y si ni la base ni el contador se escriben en el bucle salvo el avance.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ningun bucle cumple las condiciones.

    Ejemplo:
        descripcion = bucle_por_indice(contexto)
    """
    candidato = _elegir(ctx.azar, _punteros_indexables(ctx))
    if candidato is None:
        return None
    for sitio, reemplazo in candidato.usos:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, reemplazo)
    _quitar_avance(candidato.bucle, candidato.avance, candidato.puntero)
    candidato.bloque.items.remove(candidato.inicio)
    _quitar_declaracion(ctx.funcion, candidato.puntero)
    ctx.entorno.locales.pop(candidato.puntero, None)
    return f"bucle_por_indice({candidato.puntero} por {an.texto_de(candidato.base)}[{candidato.contador}])"


# ---------------------------------------------------------------------------------------------------
# Locales: segunda local para una segunda lectura de un global y anchos por destino
# ---------------------------------------------------------------------------------------------------


def _global_asignado(ctx: Contexto, sentencia: c.Sentencia, nombre: str) -> str | None:
    """Nombre del global ``g`` si la sentencia es ``nombre = g;`` con ``g`` ajeno a las variables locales."""
    if (
        isinstance(sentencia, c.Expresion)
        and isinstance(sentencia.expr, c.Asigna)
        and sentencia.expr.op == "="
        and _es_id(sentencia.expr.destino, nombre)
        and isinstance(sentencia.expr.valor, c.Id)
        and sentencia.expr.valor.nombre not in ctx.entorno.locales
    ):
        return sentencia.expr.valor.nombre
    return None


def _locales_duplicables(ctx: Contexto) -> list[tuple[str, int, str]]:
    """
    Locales que se asignan dos veces desde el mismo global en tramos del cuerpo de vidas disjuntas.

    Devuelve (local, posicion de la segunda asignacion, global). La primera sentencia del cuerpo que
    menciona la local y la segunda asignacion son ``x = g;`` con el mismo ``g``; desde la segunda en
    adelante se usa la copia. Una funcion con ``goto`` o etiquetas no se toca.
    """
    if any(isinstance(s, c.Etiqueta | c.Saltar) for _, _, s in _sentencias(ctx.funcion)):
        return []
    cuerpo = ctx.funcion.cuerpo
    menciones = [_nombres_en(s) for s in cuerpo.items]
    candidatos: list[tuple[str, int, str]] = []
    for nombre, (_, declaracion) in _declaraciones_simples(ctx).items():
        indices = [i for i, nombres in enumerate(menciones) if nombre in nombres]
        if declaracion.inicial is not None or len(indices) < 2:
            continue
        primero = _global_asignado(ctx, cuerpo.items[indices[0]], nombre)
        candidatos.extend(
            (nombre, i, primero)
            for i in indices[1:]
            if primero is not None and _global_asignado(ctx, cuerpo.items[i], nombre) == primero
        )
    return candidatos


def duplicar_local_de_global(ctx: Contexto) -> str | None:
    """
    Da una segunda local a la segunda lectura del mismo global en un tramo posterior del cuerpo.

    Contexto:
        Cuando una local recibe el mismo global en dos tramos de vidas disjuntas, el compilador la
        mantiene en un unico registro; con dos locales cada lectura vive aparte y el reparto cambia.
        Es la operacion inversa de ``unificar_locales`` para el caso de una lectura de global y se
        parece a ``partir_local``, que reparte por ramas de un ``if``. Se aplica a una local simple sin
        inicializador cuya primera sentencia y otra posterior del cuerpo son ``x = g;`` con el mismo
        ``g`` ajeno a las variables locales; desde la segunda sentencia hasta el final del cuerpo la
        local pasa a ser una nueva del mismo tipo.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local se asigna dos veces desde el mismo global.

    Ejemplo:
        descripcion = duplicar_local_de_global(contexto)
    """
    elegido = _elegir(ctx.azar, _locales_duplicables(ctx))
    if elegido is None:
        return None
    nombre, posicion, global_leido = elegido
    modelo = _declaraciones_simples(ctx)[nombre][1]
    nuevo = _nombre_temporal(ctx)
    _renombrar_en(ctx.funcion.cuerpo.items[posicion:], nombre, nuevo)
    _declarar_como(ctx, nuevo, modelo)
    return f"duplicar_local_de_global({nombre} en {nuevo} = {global_leido})"


def _destino_estrecho(ctx: Contexto, sitio: Sitio) -> bool:
    """El sitio es el valor de ``destino = x;`` y el destino es un entero de 16 bits o menos."""
    padre = sitio.padre
    if not (isinstance(padre, c.Asigna) and padre.op == "=" and padre.valor is sitio.nodo):
        return False
    destino = ctx.entorno.inferir(padre.destino)
    return destino is not None and destino.es_entero and destino.ancho <= 16


def _escrituras_simples(sitios: list[tuple[c.Sentencia, Sitio]]) -> list[c.Expr] | None:
    """Valores asignados con ``=`` a la variable de los sitios, o ``None`` si alguna escritura no es ``=``."""
    valores: list[c.Expr] = []
    for _, sitio in sitios:
        if not sitio.lvalue:
            continue
        padre = sitio.padre
        if not (isinstance(padre, c.Asigna) and padre.op == "=" and padre.destino is sitio.nodo):
            return None
        valores.append(padre.valor)
    return valores


def _anchos_por_destino(ctx: Contexto) -> list[tuple[c.Decl, an.Tipo]]:
    """Locales de 16 o 32 bits que solo se copian a destinos de 16 bits o menos, con cada ancho nuevo."""
    candidatos: list[tuple[c.Decl, an.Tipo]] = []
    for nombre, (_, declaracion) in _declaraciones_simples(ctx).items():
        actual = an.parsear_tipo(declaracion.base, declaracion.estrellas)
        if not actual.es_entero or actual.ancho < 16 or actual.texto not in an.TIPOS_ENTEROS_PERMITIDOS:
            continue
        usos = _usos_de(ctx.funcion, nombre)
        escrituras = _escrituras_simples(usos)
        lecturas = [sitio for _, sitio in usos if not sitio.lvalue]
        if (
            escrituras is None
            or not (escrituras or declaracion.inicial is not None)
            or not lecturas
            or not all(_destino_estrecho(ctx, sitio) for sitio in lecturas)
        ):
            continue
        candidatos.extend(
            (declaracion, an.tipo_entero(texto)) for texto in ("s32", "s16", "u16") if texto != actual.texto
        )
    return candidatos


def ancho_de_local_de_campo(ctx: Contexto) -> str | None:
    """
    Cambia el tipo de una local que solo copia un valor a destinos de 16 bits o menos.

    Contexto:
        Una local que recibe un campo de 16 bits y se guarda en otros campos sin operar con ella puede
        declararse con el ancho del campo (``s16``/``u16``) o con 32 bits: el compilador inserta o evita
        extensiones segun el ancho y reparte los registros de otro modo. ``ancho_de_temporal`` exige que
        el valor se conserve en el tipo nuevo; aqui basta con que los 16 bits bajos se conserven, porque
        todas las lecturas son ``destino = x;`` con un destino de 16 bits o menos, que solo guarda esos
        bits, y las escrituras de la local son asignaciones simples. No se aplica a una local con otra
        lectura (comparacion, operacion, argumento), con direccion tomada, parametro o nombre ambiguo.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local cumple las condiciones.

    Ejemplo:
        descripcion = ancho_de_local_de_campo(contexto)
    """
    elegido = _elegir(ctx.azar, _anchos_por_destino(ctx))
    if elegido is None:
        return None
    declaracion, nuevo = elegido
    anterior = declaracion.base
    declaracion.base = nuevo.base
    ctx.entorno.locales[declaracion.nombre] = nuevo
    return f"ancho_de_local_de_campo({declaracion.nombre}: {anterior} a {nuevo.texto})"


# ---------------------------------------------------------------------------------------------------
# Locales: truncamiento dentro de la asignacion
# ---------------------------------------------------------------------------------------------------


def _valores_asignados(ctx: Contexto, declaracion: c.Decl) -> list[tuple[c.Expr, object, str]] | None:
    """
    Cada valor que recibe una local con el nodo que lo contiene y el atributo donde esta.

    Devuelve ``None`` si la local se escribe de otra forma que con ``=`` o su inicializador.
    """
    valores: list[tuple[c.Expr, object, str]] = []
    if declaracion.inicial is not None:
        valores.append((declaracion.inicial, declaracion, "inicial"))
    for _, sitio in _usos_de(ctx.funcion, declaracion.nombre):
        if not sitio.lvalue:
            continue
        padre = sitio.padre
        if not (isinstance(padre, c.Asigna) and padre.op == "=" and padre.destino is sitio.nodo):
            return None
        valores.append((padre.valor, padre, "valor"))
    return valores


def _truncamientos(ctx: Contexto) -> list[tuple[c.Decl, str, list[tuple[c.Expr, object, str]]]]:
    """Locales que pasan de un tipo estrecho a ``s32`` con molde, o de ``s32`` con molde al estrecho."""
    candidatos: list[tuple[c.Decl, str, list[tuple[c.Expr, object, str]]]] = []
    for _, (_, declaracion) in _declaraciones_simples(ctx).items():
        if declaracion.estrellas or declaracion.base not in (*NARROW_ANCHOS, "s32"):
            continue
        valores = _valores_asignados(ctx, declaracion)
        if not valores:
            continue
        if declaracion.base in NARROW_ANCHOS:
            candidatos.append((declaracion, "ensanchar", valores))
            continue
        moldes = {v.tipo for v, _, _ in valores if isinstance(v, c.Conversion)}
        if (
            len(moldes) == 1
            and next(iter(moldes)) in NARROW_ANCHOS
            and all(isinstance(v, c.Conversion) for v, _, _ in valores)
        ):
            candidatos.append((declaracion, "estrechar", valores))
    return candidatos


def truncar_en_asignacion(ctx: Contexto) -> str | None:
    """
    Pasa una local estrecha a 32 bits con un molde en cada asignacion, o la operacion inversa.

    Contexto:
        ``u16 d; d = v / 100;`` y ``s32 d; d = (u16)(v / 100);`` guardan el mismo valor en la variable,
        pero el compilador resuelve el truncamiento en sitios distintos: en la asignacion o al
        declarar el ancho de la variable. Las lecturas ven el mismo valor (el molde deja el resultado
        dentro del rango del tipo estrecho y las promociones de C hacen el resto), asi que solo se
        aplica a una local cuyas escrituras son todas asignaciones simples o su inicializador. La
        inversa solo se aplica si todos los valores asignados llevan el mismo molde estrecho.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local cumple las condiciones.

    Ejemplo:
        descripcion = truncar_en_asignacion(contexto)
    """
    elegido = _elegir(ctx.azar, _truncamientos(ctx))
    if elegido is None:
        return None
    declaracion, sentido, valores = elegido
    estrecho = declaracion.base
    for valor, contenedor, atributo in valores:
        if sentido == "ensanchar":
            if not (isinstance(valor, c.Conversion) and valor.tipo == estrecho):
                setattr(contenedor, atributo, c.Conversion(estrecho, valor))
        else:
            assert isinstance(valor, c.Conversion)  # noqa: S101 - ``_truncamientos`` lo garantiza
            setattr(contenedor, atributo, valor.operando)
            estrecho = valor.tipo
    nuevo = an.tipo_entero("s32") if sentido == "ensanchar" else an.parsear_tipo(estrecho)
    anterior = declaracion.base
    declaracion.base = nuevo.base
    ctx.entorno.locales[declaracion.nombre] = nuevo
    return f"truncar_en_asignacion({declaracion.nombre}: {anterior} a {nuevo.texto})"


# ---------------------------------------------------------------------------------------------------
# Copias vigentes: asignacion compuesta encadenada y alias en comparaciones
# ---------------------------------------------------------------------------------------------------


def _operando_de_encadenado(valor: c.Expr, nombre: str) -> tuple[str, c.Expr] | None:
    """Operador y operando si ``valor`` es ``nombre op e`` (o ``e op nombre`` con operador conmutativo)."""
    if not (isinstance(valor, c.Binario) and valor.op in OPERADORES_COMPUESTOS and an.es_pura(valor)):
        return None
    if _es_id(valor.izq, nombre):
        return valor.op, valor.der
    if valor.op in OPERADORES_COMPUESTOS_CONMUTATIVOS and _es_id(valor.der, nombre):
        return valor.op, valor.izq
    return None


def _encadenables(ctx: Contexto) -> list[tuple[c.Asigna, str, c.Expr]]:
    """
    Asignaciones ``res = reg op e`` donde ``res`` y ``reg`` valen lo mismo, con su operador y operando.

    Se reconocen en cualquier bloque, con las copias vigentes del propio bloque; ``res`` y ``reg`` son
    variables distintas y seguras (locales o parametros del mismo tipo escalar) y ``e`` es puro y no las
    menciona.
    """
    inseguros = _nombres_inseguros(ctx)
    encontradas: list[tuple[c.Asigna, str, c.Expr]] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        if not (
            isinstance(sentencia, c.Expresion)
            and isinstance(sentencia.expr, c.Asigna)
            and sentencia.expr.op == "="
            and isinstance(sentencia.expr.destino, c.Id)
            and isinstance(sentencia.expr.valor, c.Binario)
        ):
            continue
        asignacion, destino = sentencia.expr, sentencia.expr.destino.nombre
        if destino in inseguros or destino not in ctx.entorno.locales:
            continue
        vigentes = _copias_vigentes(ctx, bloque, indice)
        for equivalente in sorted({*vigentes, *vigentes.values()} - {destino}):
            partes = _operando_de_encadenado(asignacion.valor, equivalente)
            if (
                partes is not None
                and _valen_lo_mismo(vigentes, destino, equivalente)
                and not {destino, equivalente} & an.identificadores_de(partes[1])
            ):
                encontradas.append((asignacion, partes[0], partes[1]))
    return encontradas


def encadenar_compuesta(ctx: Contexto) -> str | None:
    """
    Pasa ``res = reg op e`` a ``res op= e`` cuando ``res`` y ``reg`` valen lo mismo en ese punto.

    Contexto:
        Tras ``res = reg;`` las dos variables son copias una de otra, de modo que ``res = reg + 1`` y
        ``res += 1`` calculan lo mismo, pero el compilador solo reutiliza el registro de ``res`` en la
        segunda. ``asignacion_compuesta`` solo reconoce ``x = x op e``; aqui cambia la fuente del operando
        izquierdo, y deja intactas las sentencias que luego releen la copia (``reg = res;``). La
        equivalencia se sigue con ``_copias_vigentes``: copias directas del mismo bloque sin escritura
        posterior de ninguna de las dos, entre variables seguras del mismo tipo escalar, y el operando
        puro y sin ellas.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna asignacion cumple las condiciones.

    Ejemplo:
        descripcion = encadenar_compuesta(contexto)
    """
    elegido = _elegir(ctx.azar, _encadenables(ctx))
    if elegido is None:
        return None
    asignacion, operador, operando = elegido
    antes = an.texto_de(asignacion)
    asignacion.op = f"{operador}="
    asignacion.valor = operando
    return f"encadenar_compuesta({antes})"


def _alias_en_igualdades(ctx: Contexto) -> list[tuple[c.Id, str]]:
    """Operandos identificador de una igualdad con las variables que valen lo mismo en ese punto."""
    encontrados: list[tuple[c.Id, str]] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        if not isinstance(sentencia, c.Expresion | c.Si | c.Devolver):
            continue
        vigentes = _copias_vigentes(ctx, bloque, indice)
        if not vigentes:
            continue
        for raiz in c.expresiones_de(sentencia):
            escritos = set(_nombres_escritos(raiz))
            for sitio in sitios_de(raiz, sentencia):
                nodo = sitio.nodo
                if not (isinstance(nodo, c.Binario) and nodo.op in ("==", "!=")):
                    continue
                for operando, otro in ((nodo.izq, nodo.der), (nodo.der, nodo.izq)):
                    if not isinstance(operando, c.Id) or operando.nombre in escritos:
                        continue
                    encontrados.extend(
                        (operando, alias)
                        for alias in sorted({*vigentes, *vigentes.values()} - escritos - {operando.nombre})
                        if _valen_lo_mismo(vigentes, operando.nombre, alias) and not _es_id(otro, alias)
                    )
    return encontrados


def sustituir_por_alias(ctx: Contexto) -> str | None:
    """
    Sustituye un operando de una igualdad por otra variable que vale lo mismo en ese punto.

    Contexto:
        ``p == c->x`` y ``c == c->x`` son la misma comparacion si ``c = p;`` ocurrio antes sin que
        ninguna se reasignara; el compilador, sin embargo, asigna registros distintos segun que variable
        se compare. ``operandos_conmutados`` solo intercambia lados. La mutacion solo actua en una
        sentencia de expresion, ``return`` o ``if`` (la condicion de un bucle se reevalua tras el
        cuerpo), con la equivalencia que da ``_copias_vigentes``, y no cuando la propia expresion
        escribe alguna de las dos variables. Como la sustitucion no anade lecturas de memoria, no hace
        falta comprobar escrituras intermedias a un campo.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay una igualdad con un operando sustituible.

    Ejemplo:
        descripcion = sustituir_por_alias(contexto)
    """
    elegido = _elegir(ctx.azar, _alias_en_igualdades(ctx))
    if elegido is None:
        return None
    operando, alias = elegido
    antes = operando.nombre
    operando.nombre = alias
    return f"sustituir_por_alias({antes} por {alias})"


# ---------------------------------------------------------------------------------------------------
# Coma: orden de los operandos
# ---------------------------------------------------------------------------------------------------


def _comas_independientes(ctx: Contexto) -> list[c.Binario]:
    """Comas de una sentencia de expresion o del inicio y paso de un ``for`` cuyos lados conmutan."""
    con_direccion = _locales_con_direccion(ctx.funcion)
    raices: list[c.Expr] = []
    for _, _, sentencia in _sentencias(ctx.funcion):
        if isinstance(sentencia, c.Expresion):
            raices.append(sentencia.expr)
        elif isinstance(sentencia, c.Para):
            raices.extend(e for e in (sentencia.inicio, sentencia.paso) if e is not None)
    comas: list[c.Binario] = []
    for raiz in raices:
        pila = [raiz]
        while pila:
            nodo = pila.pop()
            if not (isinstance(nodo, c.Binario) and nodo.op == ","):
                continue
            pila.extend((nodo.izq, nodo.der))
            izq = an.efectos_de(c.Expresion(expr=nodo.izq), ctx.alias)
            der = an.efectos_de(c.Expresion(expr=nodo.der), ctx.alias)
            if an.son_independientes(izq, der) and not con_direccion & (
                izq.escribe | izq.lee | der.escribe | der.lee
            ):
                comas.append(nodo)
    return comas


def conmutar_coma(ctx: Contexto) -> str | None:
    """
    Intercambia los dos lados de un operador coma cuyo valor se descarta.

    Contexto:
        ``i++, v++;`` y ``v++, i++;`` hacen lo mismo, pero el compilador emite los incrementos en el
        orden en que se escriben, lo que cambia que instruccion ocupa el hueco de salto de un bucle.
        Tambien se aplica al inicio y al paso de un ``for``. Solo se tocan comas cuyo resultado se
        descarta (sentencia de expresion, inicio o paso) y cuyos lados son independientes: ninguno
        escribe lo que el otro lee o escribe, sin llamadas ni variables con la direccion tomada.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay una coma cuyos lados conmuten.

    Ejemplo:
        descripcion = conmutar_coma(contexto)
    """
    coma = _elegir(ctx.azar, _comas_independientes(ctx))
    if coma is None:
        return None
    antes = an.texto_de(coma)
    coma.izq, coma.der = coma.der, coma.izq
    return f"conmutar_coma({antes})"


# ---------------------------------------------------------------------------------------------------
# Locales: reasignar a la medida de cada uso y fundir las reasignaciones
# ---------------------------------------------------------------------------------------------------


def _ventana_estable(ctx: Contexto, sentencias: list[c.Sentencia], lectura: an.Efectos) -> bool:
    """Ninguna de las sentencias (con su contenido) escribe lo que lee la expresion ni es barrera."""
    return not any(an.escritura_alcanza(an.efectos_profundos(s, ctx.alias), lectura) for s in sentencias)


def _reasignacion(
    ctx: Contexto, bloque: c.Bloque, posiciones: list[int], nombre: str, fuente: c.Expr
) -> Callable[[], str]:
    """Aplicacion que repite ``nombre = fuente;`` justo antes de cada sentencia de ``posiciones``."""

    def aplicar() -> str:
        for posicion in sorted(posiciones, reverse=True):
            repetida = c.Expresion(expr=c.Asigna("=", c.Id(nombre), copy.deepcopy(fuente)))
            bloque.items.insert(posicion, repetida)
        return f"reasignar_medida({nombre} = {an.texto_de(fuente)}, {len(posiciones)} reasignaciones)"

    return aplicar


def _reasignaciones_posibles(ctx: Contexto) -> list[Callable[[], str]]:
    """Locales asignadas una vez y usadas como factor en varias sentencias, con la expresion estable."""
    declaraciones = _declaraciones_simples(ctx)
    inseguros = _nombres_inseguros(ctx)
    aplicaciones: list[Callable[[], str]] = []
    for bloque, indice, sentencia in _sentencias(ctx.funcion):
        asignacion = _asignacion_unica_de_local(sentencia, declaraciones)
        if asignacion is None or sentencia.comentarios:
            continue
        nombre, fuente = asignacion
        identificadores = an.identificadores_de(fuente)
        if not an.es_pura(fuente) or nombre in identificadores or identificadores & inseguros:
            continue
        usos = _usos_de(ctx.funcion, nombre)
        lecturas = [(s, sitio) for s, sitio in usos if not sitio.lvalue]
        esperadas = 0 if isinstance(sentencia, c.Decl) else 1
        posteriores = bloque.items[indice + 1 :]
        posicion_de = {id(interna): j for j, s in enumerate(posteriores) for interna in _anidadas(s)}
        if (
            len(usos) - len(lecturas) != esperadas
            or not all(isinstance(s.padre, c.Binario) and s.padre.op == "*" for _, s in lecturas)
            or any(id(s) not in posicion_de for s, _ in lecturas)
        ):
            continue
        con_uso = sorted({posicion_de[id(s)] for s, _ in lecturas})
        if len(con_uso) < 2 or not _ventana_estable(
            ctx, posteriores[: con_uso[-1] + 1], an.efectos_de(c.Expresion(expr=fuente), ctx.alias)
        ):
            continue
        aplicaciones.append(_reasignacion(ctx, bloque, [indice + 1 + j for j in con_uso[1:]], nombre, fuente))
    return aplicaciones


def _fusion(bloque: c.Bloque, repetidas: list[c.Sentencia], nombre: str, fuente: c.Expr) -> Callable[[], str]:
    """Aplicacion que quita las asignaciones repetidas de ``nombre`` y deja la primera."""

    def aplicar() -> str:
        for sentencia in repetidas:
            bloque.items.remove(sentencia)
        return f"reasignar_medida({nombre} = {an.texto_de(fuente)}, fundidas {len(repetidas)})"

    return aplicar


def _fusiones_posibles(ctx: Contexto) -> list[Callable[[], str]]:
    """Locales asignadas varias veces con la misma expresion pura en un bloque, sin cambios entre ellas."""
    declaraciones = _declaraciones_simples(ctx)
    inseguros = _nombres_inseguros(ctx)
    aplicaciones: list[Callable[[], str]] = []
    for bloque in c.todos_los_bloques(ctx.funcion.cuerpo):
        grupos: dict[tuple[str, str], list[int]] = {}
        for indice, sentencia in enumerate(bloque.items):
            asignacion = _asignacion_unica_de_local(sentencia, declaraciones)
            if asignacion is not None and isinstance(sentencia, c.Expresion) and an.es_pura(asignacion[1]):
                grupos.setdefault((asignacion[0], an.texto_de(asignacion[1])), []).append(indice)
        for (nombre, _), indices in grupos.items():
            primera = bloque.items[indices[0]]
            fuente = _asignacion_unica_de_local(primera, declaraciones)
            assert fuente is not None  # noqa: S101 - ``grupos`` solo recoge asignaciones de locales
            identificadores = an.identificadores_de(fuente[1])
            repetidas = [bloque.items[i] for i in indices[1:]]
            if (
                not repetidas
                or nombre in identificadores
                or identificadores & inseguros
                or any(s.comentarios for s in repetidas)
                or _escrituras_en(ctx.funcion.cuerpo, nombre) != len(indices)
            ):
                continue
            entre = [s for s in bloque.items[indices[0] + 1 : indices[-1]] if s not in repetidas]
            if _ventana_estable(ctx, entre, an.efectos_de(c.Expresion(expr=fuente[1]), ctx.alias)):
                aplicaciones.append(_fusion(bloque, repetidas, nombre, fuente[1]))
    return aplicaciones


def reasignar_medida(ctx: Contexto) -> str | None:
    """
    Repite una asignacion antes de cada sentencia que usa la local como factor, o funde las repeticiones.

    Contexto:
        ``m = a->x; r1 = m * s; r2 = m * t;`` mantiene ``m`` viva en un registro entre los dos
        productos; con ``m = a->x;`` repetida antes de cada producto cada uso carga el valor justo antes
        de necesitarlo y el compilador reparte los registros de otro modo. La inversa funde las
        asignaciones iguales en una. Ambas exigen una expresion pura que ninguna sentencia de la
        ventana (con su contenido) escriba ni cruce con una llamada, una local sin direccion tomada,
        escrita solo por esas asignaciones, y en la expansion todos los usos son factores de productos
        en al menos dos sentencias distintas del mismo bloque.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local admite la expansion ni la fusion.

    Ejemplo:
        descripcion = reasignar_medida(contexto)
    """
    aplicacion = _elegir(ctx.azar, [*_reasignaciones_posibles(ctx), *_fusiones_posibles(ctx)])
    return None if aplicacion is None else aplicacion()


# ---------------------------------------------------------------------------------------------------
# Locales de tipos enteros distintos: ampliacion de la union
# ---------------------------------------------------------------------------------------------------


def _fuentes_simples(ctx: Contexto, nombre: str) -> list[c.Expr] | None:
    """Valores que recibe una variable con ``=``, o ``None`` si se escribe de otra forma."""
    return _escrituras_simples(_usos_de(ctx.funcion, nombre))


def _tipos_unificables(ctx: Contexto, primera: c.Decl, segunda: c.Decl) -> bool:
    """
    Dos locales se pueden fundir si tienen el mismo tipo o la segunda es una extension de la primera.

    La segunda cabe en la primera sin cambiar de valor y promueve al mismo tipo; ademas solo recibe
    valores con ``=`` que caben sin cambio en los dos tipos. Asi cada lectura de la segunda ve el mismo
    valor y la aritmetica que la usa conserva su signo.
    """
    if (primera.base, primera.estrellas) == (segunda.base, segunda.estrellas):
        return True
    ancha = an.parsear_tipo(primera.base, primera.estrellas)
    estrecha = an.parsear_tipo(segunda.base, segunda.estrellas)
    if not (
        ancha.es_entero
        and estrecha.es_entero
        and an.promover(ancha) == an.promover(estrecha)
        and an.conserva_valor(estrecha, ancha)
    ):
        return False
    fuentes = _fuentes_simples(ctx, segunda.nombre)
    return fuentes is not None and all(_cabe(ctx, fuente, estrecha, ancha) for fuente in fuentes)


# ---------------------------------------------------------------------------------------------------
# Sentencias: desplazar un avance varias posiciones
# ---------------------------------------------------------------------------------------------------


def _es_avance(ctx: Contexto, sentencia: c.Sentencia, inseguros: set[str]) -> bool:
    """La sentencia solo escribe una variable local escalar segura y no llama a funciones."""
    if not isinstance(sentencia, c.Expresion) or sentencia.comentarios:
        return False
    escritos = _nombres_escritos(sentencia.expr)
    tipo = ctx.entorno.locales.get(escritos[0]) if len(escritos) == 1 else None
    return (
        tipo is not None
        and tipo.es_escalar
        and escritos[0] not in inseguros
        and not any(isinstance(n, c.Llamada) for n in c.recorrer(sentencia.expr))
    )


def _desplazamientos(ctx: Contexto) -> list[tuple[c.Bloque, int, int]]:
    """Movimientos (bloque, origen, destino) de una sentencia de avance a mas de una posicion de distancia."""
    inseguros = _nombres_inseguros(ctx)
    con_direccion = _locales_con_direccion(ctx.funcion)
    movimientos: list[tuple[c.Bloque, int, int]] = []
    for bloque in c.todos_los_bloques(ctx.funcion.cuerpo):
        for origen, sentencia in enumerate(bloque.items):
            if not _es_avance(ctx, sentencia, inseguros):
                continue
            propios = an.efectos_de(sentencia, ctx.alias)
            for paso in (-1, 1):
                destino = origen
                while 0 <= destino + paso < len(bloque.items) and abs(destino + paso - origen) <= (
                    ALCANCE_MAXIMO_DE_DESPLAZAMIENTO
                ):
                    vecina = an.efectos_de(bloque.items[destino + paso], ctx.alias)
                    tocadas = propios.lee | propios.escribe | vecina.lee | vecina.escribe
                    if not an.son_independientes(propios, vecina) or con_direccion & tocadas:
                        break
                    destino += paso
                    if abs(destino - origen) >= 2:
                        movimientos.append((bloque, origen, destino))
    return movimientos


def desplazar_avance(ctx: Contexto) -> str | None:
    """
    Mueve una sentencia que avanza una variable a otra posicion del bloque, a dos o mas de distancia.

    Contexto:
        ``orden_de_sentencias`` solo intercambia vecinas. Colocar el avance de un puntero antes o despues
        de los del contador y de la entrada exige cruzar varias sentencias, y cada posicion intermedia
        da un orden de emision distinto. La sentencia solo escribe una variable local escalar sin
        direccion tomada, y cada sentencia que cruza es independiente de ella (sin barreras ni
        dependencias de lectura o escritura), de modo que el resultado es el mismo programa.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna sentencia de avance puede cruzar dos vecinas.

    Ejemplo:
        descripcion = desplazar_avance(contexto)
    """
    elegido = _elegir(ctx.azar, _desplazamientos(ctx))
    if elegido is None:
        return None
    bloque, origen, destino = elegido
    bloque.items.insert(destino, bloque.items.pop(origen))
    return f"desplazar_avance(de {origen} a {destino})"


# ---------------------------------------------------------------------------------------------------
# Direcciones: izar al principio y asignar antes del bucle
# ---------------------------------------------------------------------------------------------------


def _es_aritmetica_de_direccion(ctx: Contexto, expr: c.Expr, fijos: set[str]) -> bool:
    """
    Una expresion es una suma de direcciones que no cambia durante la funcion.

    Solo contiene literales, moldes, sumas y restas, parametros que nunca se escriben (``fijos``), y
    simbolos que no son variables escalares conocidas (tablas, etiquetas), con o sin ``&``.
    """
    if isinstance(expr, c.Num):
        return True
    if isinstance(expr, c.Id):
        return expr.nombre in fijos or (
            expr.nombre not in ctx.entorno.locales and expr.nombre not in ctx.entorno.tabla.globales
        )
    if isinstance(expr, c.Conversion):
        return _es_aritmetica_de_direccion(ctx, expr.operando, fijos)
    if isinstance(expr, c.Unario) and expr.op == "&":
        return (
            isinstance(expr.operando, c.Id)
            and expr.operando.nombre not in ctx.entorno.locales
            and expr.operando.nombre not in ctx.entorno.tabla.globales
        )
    if isinstance(expr, c.Binario) and expr.op in ("+", "-"):
        return _es_aritmetica_de_direccion(ctx, expr.izq, fijos) and _es_aritmetica_de_direccion(
            ctx, expr.der, fijos
        )
    return False


def _direcciones_izables(ctx: Contexto) -> list[tuple[Sitio, an.Tipo]]:
    """Moldes a puntero sobre una suma de direcciones fija, con el tipo de la local que los recibiria."""
    inseguros = _nombres_inseguros(ctx)
    fijos = {
        p for p in ctx.entorno.parametros if p not in inseguros and _escrituras_en(ctx.funcion.cuerpo, p) == 0
    }
    candidatos: list[tuple[Sitio, an.Tipo]] = []
    for sentencia, raiz in _todas_las_expresiones(ctx.funcion):
        for sitio in sitios_de(raiz, sentencia):
            nodo = sitio.nodo
            if not (isinstance(nodo, c.Conversion) and nodo.tipo.endswith("*")) or sitio.lvalue:
                continue
            tipo = an.parsear_tipo(nodo.tipo)
            if tipo.es_puntero and _es_aritmetica_de_direccion(ctx, nodo.operando, fijos):
                candidatos.append((sitio, tipo))
    return candidatos


def izar_direccion(ctx: Contexto) -> str | None:
    """
    Calcula una direccion fija ``(T*)((u8*)base + k)`` una vez, al principio del cuerpo, en una local.

    Contexto:
        Una direccion calculada con un molde sobre una base y un desplazamiento se recalcula en cada
        uso; guardarla en una local asignada antes de leer nada la fija en un registro. A diferencia de
        ``local_de_campo``, que adelanta lecturas de memoria, aqui solo se mueve aritmetica de
        direcciones que no depende de nada que cambie: literales, simbolos que no son variables escalares
        y parametros que la funcion nunca escribe. Con probabilidad 1/2 sustituye todas las apariciones
        iguales de la expresion.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si no hay un molde a puntero sobre una direccion fija.

    Ejemplo:
        descripcion = izar_direccion(contexto)
    """
    elegido = _elegir(ctx.azar, _direcciones_izables(ctx))
    if elegido is None:
        return None
    sitio, tipo = elegido
    nombre = _nombre_temporal(ctx)
    clave = an.texto_de(sitio.nodo)
    copia = copy.deepcopy(sitio.nodo)
    if ctx.azar.random() < PROBABILIDAD_TODAS_LAS_APARICIONES:
        for sentencia, raiz in list(_todas_las_expresiones(ctx.funcion)):
            for otro in list(sitios_de(raiz, sentencia)):
                if not otro.lvalue and an.texto_de(otro.nodo) == clave:
                    c.reemplazar_hijo(otro.padre, otro.nodo, c.Id(nombre))
    else:
        c.reemplazar_hijo(sitio.padre, sitio.nodo, c.Id(nombre))
    _declarar_temporal(ctx, nombre, tipo)
    cuerpo = ctx.funcion.cuerpo
    cuerpo.items.insert(_fin_de_declaraciones(cuerpo), c.Expresion(expr=c.Asigna("=", c.Id(nombre), copia)))
    return f"izar_direccion({tipo.texto} {nombre} = {clave})"


def _es_constante_de_direccion(ctx: Contexto, expr: c.Expr) -> bool:
    """Una direccion constante: suma de literales y simbolos que no son variables, sin parametros."""
    return _es_aritmetica_de_direccion(ctx, expr, set())


def _asignaciones_adelantables(ctx: Contexto) -> list[tuple[c.Decl, int]]:
    """Punteros inicializados con una direccion constante cuyo primer uso no abre el cuerpo."""
    cuerpo = ctx.funcion.cuerpo
    menciones = [_nombres_en(s) for s in cuerpo.items]
    candidatos: list[tuple[c.Decl, int]] = []
    for nombre, (bloque, declaracion) in _declaraciones_simples(ctx).items():
        if bloque is not cuerpo or declaracion.inicial is None or declaracion.estrellas == 0:
            continue
        usos = [
            i
            for i, nombres in enumerate(menciones)
            if nombre in nombres and i >= _fin_de_declaraciones(cuerpo)
        ]
        if (
            usos
            and usos[0] > _fin_de_declaraciones(cuerpo)
            and _es_constante_de_direccion(ctx, declaracion.inicial)
        ):
            candidatos.append((declaracion, usos[0]))
    return candidatos


def _locales_de_direccion_constante(ctx: Contexto) -> list[tuple[c.Decl, c.Expresion | None, c.Expr]]:
    """
    Punteros del cuerpo que reciben una direccion constante una sola vez y se leen despues.

    Devuelve la declaracion, la sentencia ``x = e;`` que da el valor (``None`` si lo da el inicializador) y
    la direccion.
    """
    cuerpo = ctx.funcion.cuerpo
    candidatos: list[tuple[c.Decl, c.Expresion | None, c.Expr]] = []
    for nombre, (bloque, declaracion) in _declaraciones_simples(ctx).items():
        if bloque is not cuerpo or declaracion.estrellas == 0 or _escrituras_en(cuerpo, nombre) != 1:
            continue
        asignacion: c.Expresion | None = None
        fuente = declaracion.inicial
        if fuente is None:
            propias = {nombre: (bloque, declaracion)}
            for sentencia in cuerpo.items:
                encontrada = _asignacion_unica_de_local(sentencia, propias)
                if (
                    isinstance(sentencia, c.Expresion)
                    and encontrada is not None
                    and not sentencia.comentarios
                ):
                    asignacion, fuente = sentencia, encontrada[1]
                    break
        lecturas = len(_usos_de(ctx.funcion, nombre)) - (asignacion is not None)
        if fuente is not None and lecturas > 0 and _es_constante_de_direccion(ctx, fuente):
            candidatos.append((declaracion, asignacion, fuente))
    return candidatos


def _asignar_antes(ctx: Contexto, declaracion: c.Decl, primer_uso: int) -> str:
    """Separa el inicializador de la declaracion y lo asigna justo antes del primer uso."""
    inicial = declaracion.inicial
    assert inicial is not None  # noqa: S101 - ``_asignaciones_adelantables`` lo garantiza
    declaracion.inicial = None
    ctx.funcion.cuerpo.items.insert(
        primer_uso, c.Expresion(expr=c.Asigna("=", c.Id(declaracion.nombre), inicial))
    )
    return f"asignar_antes_del_bucle({declaracion.nombre} = {an.texto_de(inicial)})"


def _acceso_directo(
    ctx: Contexto, declaracion: c.Decl, asignacion: c.Expresion | None, fuente: c.Expr
) -> str:
    """Sustituye cada lectura de la local por su direccion constante y quita la local."""
    nombre = declaracion.nombre
    for sentencia, sitio in _usos_de(ctx.funcion, nombre):
        if sentencia is not asignacion:
            c.reemplazar_hijo(sitio.padre, sitio.nodo, copy.deepcopy(fuente))
    if asignacion is not None:
        ctx.funcion.cuerpo.items.remove(asignacion)
    _quitar_declaracion(ctx.funcion, nombre)
    ctx.entorno.locales.pop(nombre, None)
    return f"asignar_antes_del_bucle({nombre} directo = {an.texto_de(fuente)})"


def asignar_antes_del_bucle(ctx: Contexto) -> str | None:
    """
    Asigna la direccion de una tabla justo antes de su primer uso, o la usa directamente sin local.

    Contexto:
        ``T* t = tabla;`` al declarar fija la direccion en un registro durante toda la funcion; asignarla
        justo antes del bucle donde se usa acorta esa vida y escribir la direccion en cada uso (acceso
        directo) la elimina. Solo se aplica a una local de puntero cuyo valor es una direccion
        constante (literales y simbolos que no son variables escalares conocidas, ni parametros), de
        modo que moverla no cambia lo que vale en ningun uso. La variante de acceso directo exige que la
        local solo reciba ese valor, una sola vez, y que se lea al menos una vez.

    Args:
        ctx (Contexto): Contexto de la ronda.

    Returns:
        str | None: Descripcion, o ``None`` si ninguna local de puntero recibe una direccion constante.

    Ejemplo:
        descripcion = asignar_antes_del_bucle(contexto)
    """
    adelantables = _asignaciones_adelantables(ctx)
    directas = _locales_de_direccion_constante(ctx)
    opciones: list[Callable[[], str]] = [
        partial(_asignar_antes, ctx, declaracion, uso) for declaracion, uso in adelantables
    ]
    opciones.extend(
        partial(_acceso_directo, ctx, declaracion, asignacion, fuente)
        for declaracion, asignacion, fuente in directas
    )
    opcion = _elegir(ctx.azar, opciones)
    return None if opcion is None else opcion()


# ---------------------------------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------------------------------

Mutacion = Callable[[Contexto], str | None]
MUTACIONES: tuple[tuple[str, Mutacion, float], ...] = (
    ("orden_sentencias", orden_de_sentencias, 3.0),
    ("orden_declaraciones", orden_de_declaraciones, 2.0),
    ("introducir_temporal", introducir_temporal, 4.0),
    ("eliminar_temporal", eliminar_temporal, 2.0),
    ("ancho_temporal", ancho_de_temporal, 2.0),
    ("copiar_parametro", copiar_parametro, 1.0),
    ("operandos_conmutados", operandos_conmutados, 3.0),
    ("indice_o_puntero", indice_o_puntero, 2.0),
    ("condicion_invertida", condicion_invertida, 2.0),
    ("bucle", bucle_for_o_while, 1.5),
    ("asignacion_compuesta", asignacion_compuesta, 2.0),
    ("local_de_campo", local_de_campo, 3.0),
    ("releer_en_condicion", releer_en_condicion, 1.5),
    ("unificar_locales", unificar_locales, 1.5),
    ("partir_local", partir_local, 1.5),
    ("propagar_copia_de_campo", propagar_copia_de_campo, 2.0),
    ("introducir_copia_de_campo", introducir_copia_de_campo, 1.0),
    ("bucle_por_indice", bucle_por_indice, 2.0),
    ("duplicar_local_de_global", duplicar_local_de_global, 1.5),
    ("ancho_de_local_de_campo", ancho_de_local_de_campo, 2.0),
    ("truncar_en_asignacion", truncar_en_asignacion, 1.5),
    ("encadenar_compuesta", encadenar_compuesta, 2.0),
    ("sustituir_por_alias", sustituir_por_alias, 2.0),
    ("conmutar_coma", conmutar_coma, 1.5),
    ("reasignar_medida", reasignar_medida, 1.5),
    ("desplazar_avance", desplazar_avance, 2.0),
    ("izar_direccion", izar_direccion, 1.0),
    ("asignar_antes_del_bucle", asignar_antes_del_bucle, 1.0),
)
INTENTOS_POR_MUTACION = 12
MAX_VECINOS_POR_MUTACION = 5000


def mutar(
    base: c.Funcion, tabla: an.TablaTipos, azar: random.Random, cantidad: int
) -> tuple[c.Funcion, list[str]]:
    """
    Aplica ``cantidad`` mutaciones al azar a una copia de la funcion.

    Contexto:
        Es lo que el motor de busqueda llama para generar cada variante. Una mutacion que no
        encuentra un sitio aplicable se sustituye por otra; si tras ``INTENTOS_POR_MUTACION`` intentos por
        mutacion no se logra la cantidad pedida, se devuelven las que se pudieron aplicar.

    Args:
        base (c.Funcion): Funcion de partida (no se modifica).
        tabla (an.TablaTipos): Tipos de campos y globales.
        azar (random.Random): Generador de numeros aleatorios.
        cantidad (int): Mutaciones a aplicar.

    Returns:
        tuple[c.Funcion, list[str]]: La funcion mutada y la descripcion de cada mutacion aplicada.

    Ejemplo:
        variante, aplicadas = mutar(base, tabla, random.Random(7), 2)
    """
    funcion = copy.deepcopy(base)
    ctx = Contexto(funcion, an.Entorno(tabla, funcion), azar, _nombres_de(funcion))
    operadores = [m[1] for m in MUTACIONES]
    pesos = [m[2] for m in MUTACIONES]
    aplicadas: list[str] = []
    intentos = 0
    while len(aplicadas) < cantidad and intentos < cantidad * INTENTOS_POR_MUTACION:
        intentos += 1
        descripcion = azar.choices(operadores, weights=pesos)[0](ctx)
        if descripcion is not None:
            aplicadas.append(descripcion)
    return funcion, aplicadas


class _Enumerador(random.Random):
    """Generador que no sortea: toma siempre el elemento ``indice`` y fija los valores de ``random()``."""

    def __init__(self, indice: int, valores: tuple[float, ...]) -> None:
        super().__init__(0)
        self.indice = indice
        self.valores = valores
        self.llamadas = 0
        self.total = 0

    def random(self) -> float:
        """Devuelve los valores fijados, uno por llamada y en orden."""
        valor = self.valores[self.llamadas % len(self.valores)]
        self.llamadas += 1
        return valor

    def choice(self, seq: Any) -> Any:  # noqa: ANN401 - misma firma que ``random.Random.choice``
        """Devuelve el elemento ``indice`` (o el ultimo) y anota cuantos habia."""
        self.total = max(self.total, len(seq))
        return seq[min(self.indice, len(seq) - 1)]


def vecinos(base: c.Funcion, tabla: an.TablaTipos) -> Iterator[tuple[c.Funcion, str]]:
    """
    Enumera, una a una, todas las variantes que resultan de aplicar UNA mutacion a la funcion.

    Contexto:
        El sorteo al azar tarda mucho en dar con una reformulacion concreta cuando hay cientos de
        sitios candidatos (una mejora de una sola mutacion puede tener una probabilidad del 0,1 %
        por variante). Recorrer el vecindario completo antes de sortear garantiza hallar cualquier
        mejora que esta a una mutacion del C original. Las dos decisiones aleatorias que toman las
        mutaciones (una u otra variante, y la posicion de un temporal) se enumeran con los valores 0 y 0,99.

    Args:
        base (c.Funcion): Funcion de partida (no se modifica).
        tabla (an.TablaTipos): Tipos de campos y globales.

    Yields:
        tuple[c.Funcion, str]: Una copia mutada y la descripcion de su mutacion; puede haber repetidas.

    Ejemplo:
        for variante, descripcion in vecinos(base, tabla):
            ...
    """
    for _, mutacion, _ in MUTACIONES:
        for valores in itertools.product((0.0, 0.99), repeat=2):
            indice = 0
            while indice < MAX_VECINOS_POR_MUTACION:
                funcion = copy.deepcopy(base)
                azar = _Enumerador(indice, valores)
                ctx = Contexto(funcion, an.Entorno(tabla, funcion), azar, _nombres_de(funcion))
                descripcion = mutacion(ctx)
                if descripcion is None:
                    break
                yield funcion, descripcion
                indice += 1
                if indice >= azar.total:
                    break


def contar_prohibidos(texto: str) -> list[int]:
    """
    Cuenta las apariciones de cada construccion que el proyecto no admite como estado final.

    Contexto:
        Base de ``variante_permitida``: ensamblador en linea, ``volatile``, ``register`` y ``GLOBAL_ASM``.

    Args:
        texto (str): Texto C.

    Returns:
        list[int]: Una cantidad por patron de ``PATRONES_PROHIBIDOS``, sin contar comentarios ni cadenas.

    Ejemplo:
        cantidades = contar_prohibidos("volatile int x;")
    """
    limpio = c.enmascarar(texto)
    return [len(patron.findall(limpio)) for patron in PATRONES_PROHIBIDOS]


def variante_permitida(texto_variante: str, texto_base: str) -> bool:
    """
    Indica si una variante cumple las reglas del proyecto respecto al C de partida.

    Contexto:
        Filtro final del motor: una variante que tenga mas apariciones de ``__asm__``, ``asm(``,
        ``volatile``, ``register`` o ``GLOBAL_ASM`` que el C de partida se descarta sin compilarla.

    Args:
        texto_variante (str): C de la variante.
        texto_base (str): C de partida.

    Returns:
        bool: Verdadero si ninguna construccion prohibida aumenta.

    Ejemplo:
        permitida = variante_permitida(variante, base)
    """
    return all(
        v <= b for v, b in zip(contar_prohibidos(texto_variante), contar_prohibidos(texto_base), strict=True)
    )
