"""Reglas de negocio de la escritura atomica del estado ante un destino bloqueado un instante.

En Windows un antivirus puede mantener abierto el archivo de estado mientras se reemplaza: el fallo es
transitorio y no debe abortar una busqueda de minutos, pero un bloqueo permanente si debe notificarse
sin dejar archivos temporales.
"""

import os
import time
from pathlib import Path

import pytest
from psxdecomp.permutador import estado as est


def instalar_reemplazo_que_falla(
    monkeypatch: pytest.MonkeyPatch, fallos: int
) -> tuple[list[float], list[int]]:
    """Hace que ``os.replace`` falle ``fallos`` veces con ``PermissionError`` y luego funcione."""
    esperas: list[float] = []
    llamadas: list[int] = []
    real = os.replace

    def replace(origen: str, destino: Path) -> None:
        llamadas.append(1)
        if len(llamadas) <= fallos:
            raise PermissionError("bloqueado")
        real(origen, destino)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(time, "sleep", esperas.append)
    return esperas, llamadas


def test_un_bloqueo_transitorio_se_supera_con_esperas_crecientes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    esperas, llamadas = instalar_reemplazo_que_falla(monkeypatch, 2)
    est._escribir_atomico(tmp_path / "estado.json", "{}")
    assert (tmp_path / "estado.json").read_text(encoding="utf-8") == "{}"
    assert len(llamadas) == 3
    assert esperas == [est.ESPERA_ENTRE_REEMPLAZOS_S, est.ESPERA_ENTRE_REEMPLAZOS_S * 2]


def test_un_bloqueo_permanente_se_notifica_y_no_deja_temporales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, llamadas = instalar_reemplazo_que_falla(monkeypatch, 10**6)
    with pytest.raises(PermissionError):
        est._escribir_atomico(tmp_path / "estado.json", "{}")
    assert len(llamadas) == est.REINTENTOS_DE_REEMPLAZO
    assert list(tmp_path.iterdir()) == []


def test_sin_bloqueo_se_escribe_a_la_primera_y_sin_esperas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    esperas, llamadas = instalar_reemplazo_que_falla(monkeypatch, 0)
    est._escribir_atomico(tmp_path / "actual.c", "x")
    assert (tmp_path / "actual.c").read_text(encoding="utf-8") == "x"
    assert len(llamadas) == 1
    assert esperas == []
