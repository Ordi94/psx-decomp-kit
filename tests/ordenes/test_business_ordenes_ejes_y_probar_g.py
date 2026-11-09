"""``diff --json`` y ``--probar-g``: salida de los tres ejes y paso previo que no escribe nada."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from psxdecomp.cli import comandos, main
from psxdecomp.construccion import compilacion
from psxdecomp.diff import comparacion
from psxdecomp.diff.comparacion import ResultadoDiff
from psxdecomp.diff.ejes import EjesPuntuacion
from psxdecomp.permutador import busqueda

from ordenes.ayudantes import Escenario, Registro, crear_escenario


@pytest.fixture
def escenario(tmp_path: Path) -> Escenario:
    return crear_escenario(tmp_path)


@pytest.fixture(autouse=True)
def herramientas_dobles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compilacion, "resolver_herramientas_compilacion", lambda *a, **k: object())
    monkeypatch.setattr(comandos, "resolver_herramienta", lambda *a, **k: Path("diff.py"))


def ejecutar(escenario: Escenario, *argv: str) -> int:
    return main(list(argv), escenario.entorno, Registro(), raiz=escenario.raiz)


def resultado(puntuacion: int, **cambios: Any) -> ResultadoDiff:
    return ResultadoDiff("rutina_a", "codigo/modulo_a.c", puntuacion, "cols", **cambios)


def test_diff_json_imprime_la_puntuacion_y_los_tres_ejes_sin_las_columnas(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ejes = EjesPuntuacion(2, 1, 0)
    monkeypatch.setattr(comparacion, "comparar_funcion", lambda *a, **k: resultado(40, ejes=ejes))
    assert ejecutar(escenario, "diff", "rutina_a", "--json") == 1
    datos = json.loads(capsys.readouterr().out)
    assert datos["puntuacion"] == 40 and datos["ejes"]["diferenciasDeOperando"] == 2


def test_diff_json_devuelve_cero_si_coincide(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(comparacion, "comparar_funcion", lambda *a, **k: resultado(0))
    assert ejecutar(escenario, "diff", "rutina_a", "--json") == 0
    assert json.loads(capsys.readouterr().out)["coincide"] is True


def doble_de_probar_g(monkeypatch: pytest.MonkeyPatch, llamadas: list[str]) -> None:
    def comparar_con_valores_g(*args: Any, **kwargs: Any) -> list[tuple[int, ResultadoDiff]]:
        llamadas.append("probar-g")
        return [(0, resultado(100)), (8, resultado(0))]

    monkeypatch.setattr(comparacion, "comparar_con_valores_g", comparar_con_valores_g)


def test_diff_probar_g_muestra_las_dos_cifras_antes_de_la_comparacion(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    orden: list[str] = []
    doble_de_probar_g(monkeypatch, orden)

    def comparar(*args: Any, **kwargs: Any) -> ResultadoDiff:
        orden.append("diff")
        return resultado(0)

    monkeypatch.setattr(comparacion, "comparar_funcion", comparar)
    assert ejecutar(escenario, "diff", "rutina_a", "--probar-g") == 0
    salida = capsys.readouterr().out
    assert orden == ["probar-g", "diff"]
    assert "-G0: puntuacion 100 (el declarado)" in salida and "-G8: puntuacion 0" in salida


def test_permutar_probar_g_muestra_las_cifras_y_sigue_con_la_busqueda(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    orden: list[str] = []
    doble_de_probar_g(monkeypatch, orden)

    def permutar(raiz: Path, funcion: str, *args: Any, **kwargs: Any) -> busqueda.Resumen:
        orden.append("permutar")
        return busqueda.Resumen(funcion, 1, 1, 1, 40, 40, raiz / "mejor.c", 1.0, Counter())

    monkeypatch.setattr(busqueda, "permutar_funcion", permutar)
    assert ejecutar(escenario, "permutar", "rutina_a", "--iteraciones", "1", "--probar-g") == 2
    assert orden == ["probar-g", "permutar"]
    assert "-G8: puntuacion 0" in capsys.readouterr().out


def test_sin_la_bandera_no_se_prueba_g(escenario: Escenario, monkeypatch: pytest.MonkeyPatch) -> None:
    orden: list[str] = []
    doble_de_probar_g(monkeypatch, orden)
    monkeypatch.setattr(comparacion, "comparar_funcion", lambda *a, **k: resultado(0))
    assert ejecutar(escenario, "diff", "rutina_a") == 0
    assert orden == []
