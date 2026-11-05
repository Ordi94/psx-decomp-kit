# Contribuir

## Entorno

```
python -m pip install -e ".[particion,comparacion,dev]"
```

Antes de proponer un cambio deben pasar, sin avisos:

```
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
```

`pytest` exige cobertura del 100 % de lineas y ramas del paquete `psxdecomp`: un cambio sin pruebas que lo
cubran no se acepta. `mypy` corre en modo estricto.

## Estilo

- Python 3.13. Nombres en `snake_case` (modulos, funciones, variables), `PascalCase` en clases y
  `MAYUSCULAS` en constantes. El JSON que produce el kit usa `camelCase`.
- El codigo se divide en capas: las reglas puras (sin E/S) no dependen de las que tocan disco o procesos.
- Todo lo que depende del proyecto consumidor se lee del manifiesto `psxdecomp.toml`; el kit no contiene
  nombres de juegos, rutas ni direcciones propias de un proyecto.
- Toda entrada externa (manifiesto, archivos, respuestas de red) se valida con listas de admitidos y cotas, y
  los mensajes de error no revelan rutas de la maquina.
- Cada funcion publica lleva docstring con las secciones `Contexto`, `Args`, `Returns`, `Raises` y `Ejemplo`:

  ```python
  def nombre_funcion(par1: Tipo, par2: Tipo | None = None) -> Tipo:
      """
      Descripcion clara de lo que hace la funcion.

      Contexto:
          Donde se usa dentro del sistema.

      Args:
          par1 (Tipo): Descripcion.
          par2 (Tipo, opcional): Descripcion si aplica.

      Returns:
          Tipo: Que retorna y en que condiciones.

      Raises:
          ExceptionType: Por que y cuando se lanza.

      Ejemplo:
          resultado = nombre_funcion(valor1, valor2)
      """
  ```

## Pruebas

- Ademas de cubrir lineas, se prueban las reglas de negocio en archivos `tests/test_business_*.py`, con
  nombres que describen la regla (`test_..._rechaza_...`, `test_..._no_aplica_si_...`).
- Las pruebas no necesitan Wine ni el SDK: la ejecucion de procesos y la red se simulan. Las que dependen de
  enlaces simbolicos se omiten, con el motivo visible, donde el sistema no los permite.

## Commits

Mensajes en tono tecnico: una linea de resumen en imperativo y, si hace falta, un parrafo con el problema y la
decision. Un cambio por commit, con sus pruebas.
