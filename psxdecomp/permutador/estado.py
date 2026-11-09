"""Estado persistente del permutador en ``build/permutar/<funcion>/``.

La carpeta guarda lo que permite revisar un resultado y reanudar una busqueda interrumpida:

* ``mejor.c``: definicion de la mejor variante hallada, precedida por un comentario con su puntuacion.
* ``actual.c``: definicion desde la que continua la escalada.
* ``estado.json``: contadores y semilla (JSON en camelCase).
* ``registro.jsonl``: una linea por mejora, con iteracion, puntuacion y mutaciones aplicadas.

Nada de esto toca ``src/``. Todas las escrituras reemplazan el archivo de forma atomica: una
interrupcion a mitad deja el estado anterior completo, no uno a medias.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from psxdecomp.diff.ejes import EjesPuntuacion
from psxdecomp.dominio import RUTAS_SENCILLAS_POR_DEFECTO

VERSION_ESTADO = 1
BUILD_POR_DEFECTO = RUTAS_SENCILLAS_POR_DEFECTO["build"]
SUBCARPETA_PERMUTADOR = "permutar"
ARCHIVOS_DEL_ESTADO = ("mejor.c", "actual.c", "estado.json", "registro.jsonl")
REINTENTOS_DE_REEMPLAZO = 6
ESPERA_ENTRE_REEMPLAZOS_S = 0.05


@dataclass
class Estado:
    """Contadores de una busqueda.

    Attributes:
        funcion: Funcion que se permuta.
        archivo: Archivo de ``src/`` que la contiene.
        semilla: Semilla de la busqueda.
        ronda: Rondas completadas (cada una mide ``procesos`` variantes).
        iteraciones: Variantes medidas o descartadas hasta ahora.
        puntuacion_partida: Puntuacion del C original.
        puntuacion_actual: Puntuacion de ``actual.c``.
        puntuacion_mejor: Puntuacion de ``mejor.c``.
        rondas_sin_mejora: Rondas seguidas sin mejorar ``actual.c``.
        segundos: Tiempo acumulado en todas las sesiones.
        envolturas: Envolturas ``do { } while (0)`` que ``mejor.c`` anade respecto al C de partida: un
            candidato con envolturas debe justificarse con el volcado del compilador antes de aplicarse.
        mutaciones_intentadas: Variantes generadas por nombre de mutacion, acumuladas entre sesiones.
    """

    funcion: str
    archivo: str
    semilla: int
    puntuacion_partida: int
    puntuacion_actual: int
    puntuacion_mejor: int
    ronda: int = 0
    iteraciones: int = 0
    rondas_sin_mejora: int = 0
    segundos: float = 0.0
    envolturas: int = 0
    mutaciones_intentadas: dict[str, int] = field(default_factory=dict)


def carpeta_de(raiz: Path, funcion: str, build: str = BUILD_POR_DEFECTO) -> Path:
    """
    Da la carpeta de estado de una funcion.

    Contexto:
        Esta dentro de ``build/``, que ``clean`` elimina y git ignora.

    Args:
        raiz (Path): Raiz del repositorio.
        funcion (str): Nombre de la funcion (ya validado).
        build (str, opcional): Carpeta de salida del proyecto (``rutas.build`` del manifiesto);
            por omision la del manifiesto sin personalizar.

    Returns:
        Path: ``<build>/permutar/<funcion>``; el formato de lo que se guarda dentro no depende de ``build``.

    Ejemplo:
        carpeta = carpeta_de(Path("."), "func_ejemplo")
    """
    return raiz / build / SUBCARPETA_PERMUTADOR / funcion


def _reemplazar(temporal: str, destino: Path) -> None:
    """
    Reemplaza el destino por el archivo temporal, reintentando si otro proceso lo tiene abierto.

    Contexto:
        En Windows, ``os.replace`` falla con ``PermissionError`` mientras un antivirus o un indexador
        mantiene abierto el destino unos milisegundos. El fallo es transitorio: se reintenta unas pocas
        veces con una espera creciente y, si persiste, se propaga el ultimo error.

    Args:
        temporal (str): Ruta del archivo ya escrito.
        destino (Path): Archivo que se reemplaza.

    Raises:
        PermissionError: Si el destino sigue bloqueado tras ``REINTENTOS_DE_REEMPLAZO`` intentos.

    Ejemplo:
        _reemplazar(str(temporal), carpeta / "estado.json")
    """
    for intento in range(REINTENTOS_DE_REEMPLAZO - 1):
        try:
            os.replace(temporal, destino)
        except PermissionError:
            time.sleep(ESPERA_ENTRE_REEMPLAZOS_S * (intento + 1))
        else:
            return
    os.replace(temporal, destino)


def _escribir_atomico(destino: Path, contenido: str) -> None:
    """Escribe un archivo de texto reemplazandolo de una vez."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f"{destino.name}.", suffix=".tmp", dir=destino.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as salida:
            salida.write(contenido)
        _reemplazar(temporal, destino)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def reiniciar(carpeta: Path) -> None:
    """
    Borra el estado anterior de una funcion para empezar una busqueda nueva.

    Contexto:
        Sin ``--reanudar`` una corrida no hereda nada de la anterior; solo se borran los cuatro
        archivos propios, nunca otra cosa que hubiera en la carpeta.

    Args:
        carpeta (Path): Carpeta de estado.

    Ejemplo:
        reiniciar(carpeta_de(Path("."), "func_ejemplo"))
    """
    for nombre in ARCHIVOS_DEL_ESTADO:
        (carpeta / nombre).unlink(missing_ok=True)


def guardar_estado(carpeta: Path, estado: Estado) -> None:
    """
    Escribe ``estado.json``.

    Contexto:
        El motor lo guarda tras cada ronda para poder reanudar.

    Args:
        carpeta (Path): Carpeta de estado.
        estado (Estado): Contadores.

    Ejemplo:
        guardar_estado(carpeta, estado)
    """
    datos = {
        "version": VERSION_ESTADO,
        "funcion": estado.funcion,
        "archivo": estado.archivo,
        "semilla": estado.semilla,
        "puntuacionPartida": estado.puntuacion_partida,
        "puntuacionActual": estado.puntuacion_actual,
        "puntuacionMejor": estado.puntuacion_mejor,
        "ronda": estado.ronda,
        "iteraciones": estado.iteraciones,
        "rondasSinMejora": estado.rondas_sin_mejora,
        "segundos": round(estado.segundos, 3),
        "envolturas": estado.envolturas,
        "mutacionesIntentadas": dict(sorted(estado.mutaciones_intentadas.items())),
    }
    _escribir_atomico(carpeta / "estado.json", json.dumps(datos, indent=2) + "\n")


def _entero(datos: dict[str, object], clave: str) -> int:
    """Lee un entero no negativo de los datos del estado."""
    valor = datos.get(clave)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise ValueError(f"estado.json: '{clave}' debe ser un entero no negativo")
    return valor


def _texto(datos: dict[str, object], clave: str) -> str:
    """Lee un texto no vacio de los datos del estado."""
    valor = datos.get(clave)
    if not isinstance(valor, str) or not valor:
        raise ValueError(f"estado.json: '{clave}' debe ser un texto no vacio")
    return valor


def cargar_estado(carpeta: Path, funcion: str) -> Estado:
    """
    Lee ``estado.json`` de una busqueda anterior.

    Contexto:
        Lo usa ``--reanudar``. El archivo es entrada no confiable: se valida su forma y que
        corresponda a la funcion pedida.

    Args:
        carpeta (Path): Carpeta de estado.
        funcion (str): Funcion que se quiere reanudar.

    Returns:
        Estado: Contadores guardados.

    Raises:
        ValueError: Si no hay estado que reanudar, no es JSON valido, tiene una version o campos
            invalidos o pertenece a otra funcion.

    Ejemplo:
        estado = cargar_estado(carpeta, "func_ejemplo")
    """
    ruta = carpeta / "estado.json"
    if not ruta.is_file():
        raise ValueError(f"no hay una busqueda anterior de '{funcion}' que reanudar")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError:
        raise ValueError("estado.json no es JSON valido") from None
    if not isinstance(datos, dict) or datos.get("version") != VERSION_ESTADO:
        raise ValueError("estado.json tiene una version que esta herramienta no entiende")
    if datos.get("funcion") != funcion:
        raise ValueError(f"estado.json pertenece a otra funcion, no a '{funcion}'")
    segundos = datos.get("segundos")
    if isinstance(segundos, bool) or not isinstance(segundos, int | float) or segundos < 0:
        raise ValueError("estado.json: 'segundos' debe ser un numero no negativo")
    return Estado(
        funcion=funcion,
        archivo=_texto(datos, "archivo"),
        semilla=_entero(datos, "semilla"),
        puntuacion_partida=_entero(datos, "puntuacionPartida"),
        puntuacion_actual=_entero(datos, "puntuacionActual"),
        puntuacion_mejor=_entero(datos, "puntuacionMejor"),
        ronda=_entero(datos, "ronda"),
        iteraciones=_entero(datos, "iteraciones"),
        rondas_sin_mejora=_entero(datos, "rondasSinMejora"),
        segundos=float(segundos),
        envolturas=_entero({"envolturas": datos.get("envolturas", 0)}, "envolturas"),
        mutaciones_intentadas=_contadores(datos.get("mutacionesIntentadas", {})),
    )


def _contadores(valor: object) -> dict[str, int]:
    """Lee los contadores por mutacion: un objeto de nombres de texto y enteros no negativos."""
    if not isinstance(valor, dict):
        raise ValueError("estado.json: 'mutacionesIntentadas' debe ser un objeto")
    contadores: dict[str, int] = {}
    for nombre, cantidad in valor.items():
        if (
            not isinstance(nombre, str)
            or isinstance(cantidad, bool)
            or not isinstance(cantidad, int)
            or cantidad < 0
        ):
            raise ValueError("estado.json: 'mutacionesIntentadas' debe mapear nombres a enteros no negativos")
        contadores[nombre] = cantidad
    return contadores


def guardar_actual(carpeta: Path, texto_funcion: str) -> None:
    """
    Escribe ``actual.c``, la definicion desde la que continua la escalada.

    Contexto:
        Permite reanudar sin repetir la ruta de mutaciones que llevo hasta ahi.

    Args:
        carpeta (Path): Carpeta de estado.
        texto_funcion (str): Definicion de la funcion.

    Ejemplo:
        guardar_actual(carpeta, texto)
    """
    _escribir_atomico(carpeta / "actual.c", texto_funcion + "\n")


def cargar_actual(carpeta: Path) -> str:
    """
    Lee ``actual.c``.

    Contexto:
        Lo usa ``--reanudar``.

    Args:
        carpeta (Path): Carpeta de estado.

    Returns:
        str: Definicion de la funcion.

    Raises:
        ValueError: Si no existe.

    Ejemplo:
        texto = cargar_actual(carpeta)
    """
    ruta = carpeta / "actual.c"
    if not ruta.is_file():
        raise ValueError("falta actual.c: la busqueda anterior no se puede reanudar")
    return ruta.read_text(encoding="utf-8").rstrip("\n")


def marca_de_envolturas(envolturas: int) -> str:
    """
    Da la linea de comentario con que ``mejor.c`` declara que contiene envolturas.

    Contexto:
        Una envoltura ``do { } while (0)`` no genera codigo: solo es legitima si una persona la justifica
        con el volcado del compilador. La marca es una sola linea, fija y comprobable (``mejor.c`` la
        lleva si y solo si ``Estado.envolturas`` es mayor que cero).

    Args:
        envolturas (int): Cantidad de envolturas del candidato (mayor que cero).

    Returns:
        str: Comentario de una linea, sin salto de linea final.

    Ejemplo:
        linea = marca_de_envolturas(2)
    """
    return (
        f"/* El candidato contiene {envolturas} envolturas do {{ }} while (0) sin codigo "
        "que requieren justificacion con el volcado del compilador. */"
    )


def guardar_mejor(
    carpeta: Path, texto_funcion: str, puntuacion: int, partida: int, envolturas: int = 0
) -> Path:
    """
    Escribe ``mejor.c``: la mejor definicion con un comentario que declara su puntuacion.

    Contexto:
        Es el candidato que una persona aplica despues de leerlo; nunca se escribe en
        ``src/``. Si el candidato contiene envolturas, una segunda linea de comentario lo declara
        (``marca_de_envolturas``) para que se justifique antes de aplicarlo.

    Args:
        carpeta (Path): Carpeta de estado.
        texto_funcion (str): Definicion de la mejor variante.
        puntuacion (int): Su puntuacion.
        partida (int): Puntuacion del C original.
        envolturas (int, opcional): Envolturas que el candidato anade al C original.

    Returns:
        Path: Ruta de ``mejor.c``.

    Ejemplo:
        ruta = guardar_mejor(carpeta, texto, 0, 10, envolturas=1)
    """
    destino = carpeta / "mejor.c"
    cabecera = f"/* Candidato del permutador: puntuacion {puntuacion} (el C original puntua {partida}). */\n"
    if envolturas > 0:
        cabecera += marca_de_envolturas(envolturas) + "\n"
    _escribir_atomico(destino, cabecera + texto_funcion + "\n")
    return destino


def cargar_mejor(carpeta: Path) -> str:
    """
    Lee la definicion de ``mejor.c`` sin sus lineas de comentario iniciales.

    Contexto:
        Lo usa ``--reanudar``. El archivo lleva una o dos lineas de comentario antes de la definicion
        (la puntuacion y, con envolturas, su marca).

    Args:
        carpeta (Path): Carpeta de estado.

    Returns:
        str: Definicion de la funcion, sin salto de linea final.

    Ejemplo:
        texto = cargar_mejor(carpeta)
    """
    lineas = (carpeta / "mejor.c").read_text(encoding="utf-8").rstrip("\n").split("\n")
    primera = next((i for i, linea in enumerate(lineas) if not linea.startswith("/* ")), len(lineas))
    return "\n".join(lineas[primera:])


def anadir_registro(
    carpeta: Path,
    iteracion: int,
    puntuacion: int,
    mutaciones: list[str],
    *,
    envolturas: int = 0,
    ejes: EjesPuntuacion | None = None,
) -> None:
    """
    Agrega una linea a ``registro.jsonl`` por cada mejora.

    Contexto:
        Documenta que reformulaciones llevaron a cada mejora, para saber cuales funcionan. Cada linea
        declara cuantas envolturas contiene la variante aceptada (``envolturas``, cero si ninguna) y la
        puntuacion secundaria en tres ejes (``ejes``), que no interviene en la busqueda.

    Args:
        carpeta (Path): Carpeta de estado.
        iteracion (int): Numero de iteracion en que se hallo.
        puntuacion (int): Puntuacion lograda.
        mutaciones (list[str]): Mutaciones aplicadas a la variante respecto a la anterior.
        envolturas (int, opcional): Envolturas que la variante anade al C original.
        ejes (EjesPuntuacion | None, opcional): Ejes de la variante, si se pudieron calcular.

    Ejemplo:
        anadir_registro(carpeta, 41, 10, ["orden_sentencias(posiciones 3 y 4)"])
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    datos: dict[str, object] = {
        "iteracion": iteracion,
        "puntuacion": puntuacion,
        "mutaciones": mutaciones,
        "envolturas": envolturas,
    }
    if ejes is not None:
        datos["ejes"] = ejes.como_json()
    linea = json.dumps(datos)
    with (carpeta / "registro.jsonl").open("a", encoding="utf-8", newline="\n") as salida:
        salida.write(linea + "\n")
