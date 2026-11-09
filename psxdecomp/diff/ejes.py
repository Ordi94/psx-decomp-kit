"""Puntuacion secundaria de una comparacion en tres ejes.

La cifra de ``asm-differ`` (``current_score``) manda en la busqueda: es la funcion objetivo. Estos
tres contadores no la sustituyen; explican DE QUE esta hecha la diferencia para que una persona decida
que mutacion probar a continuacion:

* diferencias de registro u operando: lineas con el mismo mnemonico en ambos lados cuyo texto difiere;
* reordenacion: lineas presentes en ambos lados (con el mismo texto) pero en distinta posicion;
* insercion o borrado: lineas que solo existen en un lado.

Las funciones de este modulo no tocan disco ni procesos: reciben listados ya leidos.
"""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_PATRON_DIRECCION = re.compile(r"^\s*[0-9A-Fa-f]+:\s*")
_MNEMONICOS_NO_INSTRUCCION = frozenset({"<label>", "<data-ref>", "ERROR", "..."})


@dataclass(frozen=True)
class EjesPuntuacion:
    """Los tres contadores de la puntuacion secundaria.

    Attributes:
        operandos: Lineas alineadas con el mismo mnemonico y distinto registro u operando.
        reordenadas: Lineas presentes en los dos listados pero en distinta posicion.
        insertadas_o_borradas: Lineas que solo aparecen en un listado.
    """

    operandos: int = 0
    reordenadas: int = 0
    insertadas_o_borradas: int = 0

    def como_json(self) -> dict[str, int]:
        """
        Da los contadores con los nombres del JSON (camelCase).

        Contexto:
            Los escriben la salida JSON de ``diff`` y ``registro.jsonl`` del permutador.

        Returns:
            dict[str, int]: ``diferenciasDeOperando``, ``lineasReordenadas`` y ``lineasInsertadasOBorradas``.

        Ejemplo:
            datos = EjesPuntuacion(2, 1, 0).como_json()
        """
        return {
            "diferenciasDeOperando": self.operandos,
            "lineasReordenadas": self.reordenadas,
            "lineasInsertadasOBorradas": self.insertadas_o_borradas,
        }


def _mnemonico(linea: str) -> str:
    """Primera palabra de una instruccion."""
    return linea.split(None, 1)[0] if linea.split() else ""


def calcular_ejes(base: Sequence[str], candidato: Sequence[str]) -> EjesPuntuacion:
    """
    Calcula los tres ejes entre el listado del original y el del candidato.

    Contexto:
        Primero se alinean las lineas iguales (subsecuencia comun mas larga). Lo que queda sin alinear
        en cada lado se reparte: las lineas con el mismo texto en los dos lados son reordenaciones; entre
        las demas, las que comparten mnemonico son diferencias de operando; el resto se insertaron o se
        borraron. La suma de los ejes no es la puntuacion de ``asm-differ``: es una descripcion.

    Args:
        base (Sequence[str]): Instrucciones del original, una por elemento.
        candidato (Sequence[str]): Instrucciones del candidato.

    Returns:
        EjesPuntuacion: Los tres contadores; todos cero si los listados son iguales.

    Ejemplo:
        ejes = calcular_ejes(["addu $a0, $a1", "jr $ra"], ["addu $a0, $a2", "jr $ra"])
    """
    sobrantes_base: list[str] = []
    sobrantes_candidato: list[str] = []
    alineador = difflib.SequenceMatcher(None, list(base), list(candidato), autojunk=False)
    for etiqueta, inicio_b, fin_b, inicio_c, fin_c in alineador.get_opcodes():
        if etiqueta != "equal":
            sobrantes_base.extend(base[inicio_b:fin_b])
            sobrantes_candidato.extend(candidato[inicio_c:fin_c])
    comunes = Counter(sobrantes_base) & Counter(sobrantes_candidato)
    restantes_base = Counter(sobrantes_base) - comunes
    restantes_candidato = Counter(sobrantes_candidato) - comunes
    por_mnemonico_base = Counter(_mnemonico(linea) for linea in restantes_base.elements())
    por_mnemonico_candidato = Counter(_mnemonico(linea) for linea in restantes_candidato.elements())
    operandos = sum((por_mnemonico_base & por_mnemonico_candidato).values())
    libres = restantes_base.total() + restantes_candidato.total() - 2 * operandos
    return EjesPuntuacion(operandos=operandos, reordenadas=comunes.total(), insertadas_o_borradas=libres)


def _instruccion_de(columna: object) -> str | None:
    """Texto normalizado de la instruccion de una columna de ``asm-differ``, o ``None`` si no es una."""
    if not isinstance(columna, dict):
        return None
    mnemonico = columna.get("mnemonic")
    if not isinstance(mnemonico, str) or mnemonico in _MNEMONICOS_NO_INSTRUCCION:
        return None
    segmentos = columna.get("text")
    texto = (
        "".join(s.get("text", "") for s in segmentos if isinstance(s, dict))
        if isinstance(segmentos, list)
        else ""
    )
    return " ".join(_PATRON_DIRECCION.sub("", texto).split()) or mnemonico


def ejes_desde_json(salida: str) -> EjesPuntuacion | None:
    """
    Calcula los ejes a partir de la salida JSON de ``asm-differ``.

    Contexto:
        La salida de otro programa es entrada no confiable: si no tiene la forma esperada no se inventa
        nada y se devuelve ``None``; la puntuacion principal se lee aparte y no depende de esto.

    Args:
        salida (str): Texto JSON producido con ``--format=json``.

    Returns:
        EjesPuntuacion | None: Los ejes, o ``None`` si el JSON no trae filas legibles.

    Ejemplo:
        ejes = ejes_desde_json(salida_json)
    """
    try:
        filas = json.loads(salida).get("rows")
    except (ValueError, AttributeError):
        return None
    if not isinstance(filas, list):
        return None
    base: list[str] = []
    candidato: list[str] = []
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        for destino, clave in ((base, "base"), (candidato, "current")):
            instruccion = _instruccion_de(fila.get(clave))
            if instruccion is not None:
                destino.append(instruccion)
    return calcular_ejes(base, candidato)
