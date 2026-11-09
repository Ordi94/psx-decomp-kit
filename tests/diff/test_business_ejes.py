"""Reglas de negocio de la puntuacion secundaria en tres ejes y de la prueba de ``-G``."""

import json
from pathlib import Path
from typing import Any

import pytest
from psxdecomp.diff import comparacion as diff
from psxdecomp.diff.ejes import EjesPuntuacion, calcular_ejes, ejes_desde_json

from construccion.test_compilacion import herramientas

from .test_comparacion import (
    COMPILACION,
    CONVENCIONES,
    RUTAS,
    EjecutorDiff,
    comparar_funcion,
    repo_diff,  # noqa: F401
)

# --- calcular_ejes: pares pequenos de listados --------------------------------------------------------


def test_dos_listados_iguales_no_tienen_diferencias() -> None:
    listado = ["addu $a0, $a1", "jr $ra", "nop"]
    assert calcular_ejes(listado, listado) == EjesPuntuacion(0, 0, 0)


def test_un_registro_distinto_en_una_linea_alineada_es_una_diferencia_de_operando() -> None:
    base = ["lw $v0, 0($a0)", "addu $v1, $v0, $a1", "jr $ra"]
    candidato = ["lw $v0, 0($a0)", "addu $v1, $v0, $a2", "jr $ra"]
    assert calcular_ejes(base, candidato) == EjesPuntuacion(operandos=1)


def test_dos_lineas_intercambiadas_cuentan_como_reordenacion_y_no_como_borrado() -> None:
    base = ["lw $v0, 0($a0)", "lw $v1, 4($a0)", "jr $ra"]
    candidato = ["lw $v1, 4($a0)", "lw $v0, 0($a0)", "jr $ra"]
    ejes = calcular_ejes(base, candidato)
    assert ejes.reordenadas == 1 and ejes.operandos == 0 and ejes.insertadas_o_borradas == 0


def test_una_linea_de_mas_o_de_menos_es_una_insercion_o_un_borrado() -> None:
    base = ["lw $v0, 0($a0)", "jr $ra"]
    assert calcular_ejes(base, ["lw $v0, 0($a0)", "nop", "jr $ra"]) == EjesPuntuacion(insertadas_o_borradas=1)
    assert calcular_ejes(base, ["jr $ra"]) == EjesPuntuacion(insertadas_o_borradas=1)


def test_los_tres_ejes_se_combinan_en_un_mismo_par() -> None:
    base = ["lw $v0, 0($a0)", "lw $v1, 4($a0)", "addu $a1, $v0, $v1", "sw $a1, 8($a0)", "jr $ra"]
    candidato = ["lw $v1, 4($a0)", "lw $v0, 0($a0)", "addu $a2, $v0, $v1", "nop", "sw $a1, 8($a0)", "jr $ra"]
    assert calcular_ejes(base, candidato) == EjesPuntuacion(
        operandos=1, reordenadas=1, insertadas_o_borradas=1
    )


def test_un_listado_vacio_solo_tiene_inserciones() -> None:
    assert calcular_ejes([], ["nop", "nop"]) == EjesPuntuacion(insertadas_o_borradas=2)
    assert calcular_ejes(["nop"], []) == EjesPuntuacion(insertadas_o_borradas=1)
    assert calcular_ejes([], []) == EjesPuntuacion()


def test_un_mnemonico_distinto_en_la_misma_posicion_es_borrado_mas_insercion() -> None:
    assert calcular_ejes(["addu $a0, $a1"], ["subu $a0, $a1"]) == EjesPuntuacion(insertadas_o_borradas=2)


def test_los_ejes_se_escriben_en_camel_case() -> None:
    assert EjesPuntuacion(2, 1, 3).como_json() == {
        "diferenciasDeOperando": 2,
        "lineasReordenadas": 1,
        "lineasInsertadasOBorradas": 3,
    }


# --- ejes_desde_json -----------------------------------------------------------------------------------


def columna(texto: str, mnemonico: str) -> dict[str, Any]:
    return {"mnemonic": mnemonico, "text": [{"text": texto}]}


def test_los_ejes_se_leen_de_las_filas_de_asm_differ_ignorando_direcciones_y_marcas() -> None:
    filas = [
        {"base": columna("100: lw $v0, 0($a0)", "lw"), "current": columna("0: lw $v0, 0($a0)", "lw")},
        {
            "base": columna("104: addu $v1, $v0, $a1", "addu"),
            "current": columna("4: addu $v1, $v0, $a2", "addu"),
        },
        {"base": {"mnemonic": "<label>", "text": [{"text": ".L1"}]}, "current": {"mnemonic": "<label>"}},
        {"base": columna("108: jr $ra", "jr"), "current": columna("8: jr $ra", "jr")},
        {"base": columna("10c: nop", "nop"), "current": {"mnemonic": "..."}},
        "no es una fila",
        {"base": "no es una columna"},
    ]
    assert ejes_desde_json(json.dumps({"rows": filas})) == EjesPuntuacion(
        operandos=1, insertadas_o_borradas=1
    )


def test_una_columna_sin_texto_usa_el_mnemonico() -> None:
    filas = [{"base": {"mnemonic": "nop"}, "current": {"mnemonic": "nop", "text": "no es lista"}}]
    assert ejes_desde_json(json.dumps({"rows": filas})) == EjesPuntuacion()


@pytest.mark.parametrize("salida", ["no es json", "[]", "{}", '{"rows": "x"}', "null"])
def test_una_salida_sin_filas_legibles_no_inventa_ejes(salida: str) -> None:
    assert ejes_desde_json(salida) is None


# --- comparacion: JSON, ejes y --probar-g -------------------------------------------------------------


def test_la_comparacion_calcula_los_ejes_sin_cambiar_la_puntuacion(repo_diff: Any) -> None:  # noqa: F811
    filas = [
        {
            "base": columna("0: addu $v1, $a0, $zero", "addu"),
            "current": columna("0: addu $v1, $a1, $zero", "addu"),
        },
        {"base": columna("4: jr $ra", "jr"), "current": columna("4: jr $ra", "jr")},
    ]
    resultado = comparar_funcion(
        repo_diff, "rutina_a", herramientas(), Path("diff.py"), EjecutorDiff(5, filas=filas)
    )
    assert resultado.puntuacion == 5
    assert resultado.ejes == EjesPuntuacion(operandos=1)


def test_una_salida_sin_filas_deja_los_ejes_sin_calcular(repo_diff: Any) -> None:  # noqa: F811
    resultado = comparar_funcion(repo_diff, "rutina_a", herramientas(), Path("diff.py"), EjecutorDiff(0))
    assert resultado.ejes is None


def test_el_json_de_diff_lleva_la_puntuacion_y_los_tres_ejes() -> None:
    resultado = diff.ResultadoDiff("f", "codigo/a.c", 40, "", ejes=EjesPuntuacion(1, 2, 3))
    datos = json.loads(diff.resultado_a_json(resultado))
    assert datos == {
        "funcion": "f",
        "archivo": "codigo/a.c",
        "puntuacion": 40,
        "coincide": False,
        "truncado": False,
        "bytesIguales": None,
        "ejes": {"diferenciasDeOperando": 1, "lineasReordenadas": 2, "lineasInsertadasOBorradas": 3},
    }
    sin_ejes = json.loads(diff.resultado_a_json(diff.ResultadoDiff("f", "codigo/a.c", 0, "")))
    assert sin_ejes["ejes"] is None and sin_ejes["coincide"] is True


def test_probar_g_compila_con_g0_y_g8_sin_escribir_el_resultado_ni_el_toml(repo_diff: Any) -> None:  # noqa: F811
    ejecutor = EjecutorDiff(7)
    resultados = diff.comparar_con_valores_g(
        repo_diff,
        "rutina_a",
        herramientas(),
        Path("diff.py"),
        ejecutor,
        rutas=RUTAS,
        convenciones=CONVENCIONES,
        compilacion=COMPILACION,
        nombre_ejecutable="EJEC_001.00",
    )
    assert [(g, r.puntuacion) for g, r in resultados] == [(0, 7), (8, 7)]
    compilaciones = [c for c in ejecutor.comandos if Path(c[0]).name == "CC1PSX.EXE"]
    assert [[a for a in c if a.startswith("-G")] for c in compilaciones] == [["-G0"], ["-G8"]]
    assert not (repo_diff / "salida" / "diff" / "rutina_a.resultado.json").exists()
    assert not (repo_diff / "datos").exists()


def test_el_resumen_de_probar_g_marca_el_umbral_declarado_y_avisa_que_no_escribe() -> None:
    resultados = [(0, diff.ResultadoDiff("f", "a.c", 100, "")), (8, diff.ResultadoDiff("f", "a.c", 0, ""))]
    lineas = diff.formatear_probar_g(resultados, 0)
    assert lineas[0] == "-G0: puntuacion 100 (el declarado)"
    assert lineas[1] == "-G8: puntuacion 0"
    assert "no se modifica" in lineas[2]


def test_comparar_con_guardar_falso_no_toca_el_resultado_guardado(repo_diff: Any) -> None:  # noqa: F811
    ruta = repo_diff / "salida" / "diff" / "rutina_a.resultado.json"
    comparar_funcion(repo_diff, "rutina_a", herramientas(), Path("diff.py"), EjecutorDiff(3))
    antes = ruta.read_text(encoding="utf-8")
    diff.comparar_funcion(
        repo_diff,
        "rutina_a",
        herramientas(),
        Path("diff.py"),
        EjecutorDiff(99),
        rutas=RUTAS,
        convenciones=CONVENCIONES,
        compilacion=COMPILACION,
        nombre_ejecutable="EJEC_001.00",
        valor_g=8,
        guardar=False,
    )
    assert ruta.read_text(encoding="utf-8") == antes
