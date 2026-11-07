"""Ayudantes comunes de las pruebas de las mutaciones: cabecera sintetica, contexto y aplicacion."""

import random
from collections.abc import Callable

from psxdecomp.permutador import analisis as an
from psxdecomp.permutador import c
from psxdecomp.permutador import mutaciones as mut

CABECERA = """
typedef struct Nodo {
    s32 valor;
    s16 corto;
    u16 ancho;
    s32 clave;
    u8 byte;
    struct Nodo* sig;
} Nodo;
typedef struct Mundo {
    s32 escala;
    Nodo* cabeza;
} Mundo;
extern s32 D_global;
extern s32 D_otra;
extern Nodo tabla[8];
"""
TIPOS = frozenset({"Nodo", "Mundo"})
FIRMA = "void f(Nodo* p, Nodo* q, Mundo* m, s32 a, s32 b)"

Mutacion = Callable[[mut.Contexto], str | None]


def azar(semilla: int) -> random.Random:
    """Generador reproducible; la busqueda es estocastica, no criptografica."""
    return random.Random(semilla)  # noqa: S311


def preparar(texto: str, semilla: int = 0) -> mut.Contexto:
    """Construye el contexto de una ronda sobre el texto de una funcion ``f``."""
    tabla = an.construir_tabla([CABECERA])
    funcion = c.analizar_funcion(texto, "f", TIPOS)
    return mut.Contexto(funcion, an.Entorno(tabla, funcion), azar(semilla), mut._nombres_de(funcion))


def cuerpo(*lineas: str, firma: str = FIRMA) -> str:
    """Escribe una funcion ``f`` con la firma dada y las lineas como cuerpo, sangradas como el escritor."""
    return firma + "\n{\n" + "\n".join(f"    {linea}" for linea in lineas) + "\n}"


def aplicar(mutacion: Mutacion, texto: str, semilla: int = 0) -> tuple[str | None, str]:
    """
    Aplica una mutacion y devuelve su descripcion y el C resultante.

    Comprueba de paso la ida y vuelta: el C resultante se vuelve a leer y a escribir sin cambios.
    """
    ctx = preparar(texto, semilla)
    descripcion = mutacion(ctx)
    resultado = c.imprimir_funcion(ctx.funcion)
    assert c.imprimir_funcion(c.analizar_funcion(resultado, "f", TIPOS)) == resultado
    return descripcion, resultado


def sin_cambio(mutacion: Mutacion, texto: str) -> None:
    """Comprueba que la mutacion no se aplica y deja el arbol exactamente como estaba."""
    descripcion, resultado = aplicar(mutacion, texto)
    assert descripcion is None
    assert resultado == c.imprimir_funcion(c.analizar_funcion(texto, "f", TIPOS))


def todas_las_variantes(mutacion: Mutacion, texto: str) -> set[str]:
    """Todos los resultados distintos de la mutacion al recorrer sus alternativas con varias semillas."""
    resultados: set[str] = set()
    for semilla in range(40):
        descripcion, resultado = aplicar(mutacion, texto, semilla)
        if descripcion is not None:
            resultados.add(resultado)
    return resultados
