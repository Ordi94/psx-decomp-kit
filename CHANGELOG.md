# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado es semantico.

## [0.3.0] - 2026-11-09

### Anadido

Doce mutaciones nuevas del buscador de variantes del permutador, cada una con las comprobaciones de seguridad
semantica de las existentes:

- `mover_sentencia_a_distancia`: mueve una sentencia de dos a ocho posiciones dentro de su bloque, sin cruzar
  etiquetas, saltos, `return` ni bucles sin fin, y respetando las dependencias de lectura y escritura; una
  declaracion con inicializador se mueve entera dentro de la serie de declaraciones o deja la declaracion y mueve
  solo la asignacion.
- `envolver_en_bloque`: envuelve un rango de sentencias contiguas en `do { ... } while (0);` si contiene una
  llamada o abarca todo el bloque, sin anadir codigo. El estado (`envolturas`), cada linea de `registro.jsonl`
  y `mejor.c` (un comentario de una linea) declaran las envolturas del candidato.
- `dividir_local_multiset`: reparte una local asignada varias veces en locales frescas de una sola asignacion.
- `expandir_local`: sustituye una local de una sola asignacion y un solo uso por su expresion.
- `cadena_de_asignacion`: pasa `a = e; b = e;` a `a = b = e;` y la inversa.
- `dividir_asignacion`: parte `r = a + b + c;` en dos pasos (`r = a + b; r = r + c;` o `r = a; r += b + c;`) y
  une las dos sentencias de vuelta.
- `ajustar_desigualdad`: cambia `a < k` por `a <= k - 1` y `a > k` por `a >= k + 1` (y las inversas) sin
  desbordar el tipo.
- `forma_de_acceso_a_struct`: alterna `a[i].c`, `(a + i)->c`, `(&a[i])->c` y `(*(a + i)).c`.
- `cast_en_subexpresion`: anade o quita un molde de ancho entero sobre una subexpresion aritmetica cuando no
  cambia el valor.
- `ancho_de_variable_de_retorno`: pasa a 16 bits una local de 32 bits que solo recibe retornos de llamadas y solo
  se lee truncada.
- `limite_en_local_antes_del_incremento`: lee el limite de un bucle `do` en una local justo antes del avance.
- `copia_local_por_rama`: copia un puntero en su definicion y lo usa solo dentro de una rama de un `if`.

Otros cambios:

- Opciones del compilador por archivo: la clave `opciones = ["-fno-schedule-insns"]` junto a `g` en el archivo de
  opciones de compilacion se anade al comando del compilador de ese archivo, despues de las opciones globales,
  en `build`, `diff`, `probar` y `permutar`. Sin la clave el comando no cambia.
- Puntuacion secundaria en tres ejes (diferencias de operando, lineas reordenadas, lineas insertadas o borradas):
  se calcula en `diff --json` y en cada linea de `registro.jsonl`; la cifra de siempre sigue siendo la funcion
  objetivo de la busqueda.
- `--probar-g` en `diff` y `permutar`: muestra la cifra con `-G0` y con `-G8` antes de comparar o buscar, sin
  escribir nada.
- `estado.json` guarda las variantes generadas por mutacion (`mutacionesIntentadas`).

### Cambiado

- `registro.jsonl` incluye `envolturas` en cada linea y, cuando se pudo calcular, `ejes`.
- `--reanudar` lee `mejor.c` saltando todas las lineas de comentario iniciales, no solo la primera.

## [0.2.0] - 2026-11-07

### Anadido

Once mutaciones nuevas del buscador de variantes del permutador, cada una con las comprobaciones de seguridad
semantica de las existentes:

- `bucle_por_indice`: sustituye el puntero que recorre un bucle por el acceso indexado `base[i]` en todas las
  sentencias del bucle.
- `duplicar_local_de_global`: da una segunda local a la segunda lectura del mismo global en un tramo posterior.
- `ancho_de_local_de_campo`: cambia el ancho de una local que solo se copia a destinos de 16 bits o menos.
- `truncar_en_asignacion`: pasa una local estrecha a 32 bits con un molde en la asignacion, y la inversa.
- `encadenar_compuesta`: convierte `res = reg + c` en `res += c` cuando `res` y `reg` valen lo mismo.
- `sustituir_por_alias`: cambia un operando de una igualdad por otra variable que vale lo mismo en ese punto.
- `conmutar_coma`: intercambia los lados de una coma cuyo valor se descarta, tambien en el `for`.
- `reasignar_medida`: repite la asignacion de una local usada como factor antes de cada uso, y funde las repeticiones.
- `desplazar_avance`: mueve una sentencia de avance a dos o mas posiciones de distancia.
- `izar_direccion`: calcula una direccion fija `(T*)((u8*)base + k)` una vez al principio del cuerpo.
- `asignar_antes_del_bucle`: asigna la direccion de una tabla justo antes de su primer uso, o la usa sin local.

### Cambiado

- `unificar_locales` funde tambien una local entera estrecha dentro de una de 32 bits que la contiene, si solo
  recibe valores que caben en ambos tipos.
- `orden_sentencias` intercambia dos almacenes a campos de igual nombre de estructuras conocidas y distintas.
- El README documenta la tabla de mutaciones con su peso.

### Corregido

- La escritura del estado del permutador reintenta el reemplazo del archivo cuando Windows lo tiene abierto
  un instante (antivirus, indexador) en lugar de abortar la busqueda con un error de permisos.

## [0.1.1] - 2026-11-05

### Corregido

- La cobertura de la limpieza forzada no dependia del sistema operativo: el manejador que reintenta el borrado
  de un archivo de solo lectura solo se ejecutaba en Windows y la integracion continua en Linux fallaba por
  cobertura. El manejador es ahora una funcion de modulo (`_forzar_borrado`) con el mismo comportamiento, y
  las pruebas lo ejercitan de forma identica en ambos sistemas.

## [0.1.0] - 2026-11-04

Primera version publicable del kit.

### Incluye

- Manifiesto `psxdecomp.toml`: cargador, validacion con listas de admitidos y cotas, confinamiento de rutas a la
  raiz del proyecto y mensajes de error sin rutas de la maquina.
- Linea de ordenes `python -m psxdecomp.cli`: `split`, `build`, `verify`, `clean`, `diff`, `probar`, `permutar`,
  `verificar-config`, `progreso` y `comprobar`; entrada reutilizable (`main`, `construir_parser`) para que un
  proyecto conserve su propia orden.
- Extensiones por `[plugins]`: subcomandos, ganchos antes de construir y despues de verificar, y agrupado propio
  de subsistemas para el progreso.
- Construccion: compilacion de los archivos C con el compilador original del SDK, ensamblado del resto, enlace
  en el orden del script del enlazador y verificacion por huella SHA-256.
- Comparacion funcion a funcion con `asm-differ`, banco de variantes y coherencia de las lineas de pendiente.
- Permutador: busqueda de la forma de C que hace coincidir una funcion, con estado reanudable.
- Progreso: medicion por zona y subsistema, documento en Markdown y JSON y seccion del README del proyecto.
- Toolchain: instalacion idempotente con verificacion de huella, extraccion de zip, 7z, rar e ISO 9660, y
  adaptacion a Windows o Linux (Wine y binutils nativos).
- Variables de entorno con prefijo propio (`PSXDECOMP_`) y alias configurable por proyecto.
- Paquete tipado (`py.typed`), cobertura del 100 % de lineas y ramas, `mypy` estricto y `ruff` sin avisos.
- Integracion continua en GitHub Actions (Linux y Windows, Python 3.13): `ruff`, `mypy` y `pytest` con cobertura.
- Documentos de comunidad: `CONTRIBUTING.md` y `SECURITY.md`.

### Dependencias

`requests` y `PyYAML`; extras `particion` (`splat64`), `comparacion` (`rapidfuzz`, `Levenshtein`, `cxxfilt`,
`colorama`, `watchdog`) y `dev`.

### No incluye

Binarios del SDK, del compilador ni de ningun juego.
