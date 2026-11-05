# Politica de seguridad

## Versiones con soporte

Se corrige la ultima version publicada.

## Como reportar una vulnerabilidad

No abra una incidencia publica. Use el aviso privado de GitHub:
<https://github.com/Ordi94/psx-decomp-kit/security/advisories/new>

Incluya la version del kit, el sistema operativo, los pasos para reproducirlo y su efecto. Se acusa recibo en
un plazo razonable y se coordina la publicacion de la correccion con quien reporta.

## Alcance

Interesan especialmente: salidas de las rutas del proyecto (`..`, enlaces simbolicos), ejecucion no prevista
de comandos, descargas sin verificacion de huella y mensajes de error que filtren datos de la maquina.
