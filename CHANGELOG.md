# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el versionado es semantico.

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
