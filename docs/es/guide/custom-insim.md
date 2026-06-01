# InSim Personalizado y Libertad Total

Una de las mayores ventajas de integrar tu servidor en el ecosistema **LFS Open Ranking System** es que **no te obligamos a usar un bot de código cerrado**.

## Tienes Control Absoluto

Tu servidor aloja su propio Bot Cliente (`system.py`). Dado que es un script de Python de código abierto que descargas y configuras tú mismo, tienes total libertad para:
- **Modificar mensajes**: Cambiar todos los textos que el bot envía a la pantalla, botones e idiomas.
- **Añadir comandos personalizados**: Escribir tu propio código para detectar comandos en el chat (ej. `!reglas`, `!discord` o scripts de penalizaciones).
- **Lógica InSim Avanzada**: Controlar paradas en boxes, diseño de la parrilla de salida, scripts de puntuación de drift, o cualquier otra cosa que ofrezca el protocolo InSim.

> [!TIP]
> **El único requisito estricto** es mantener intacta la sección del bot que empaqueta los resultados de la carrera (`IS_RES`) en el JSON estándar y hace POST a la API del Nodo Validador (`/ingest`) firmándolo digitalmente con tu llave Ed25519 generada localmente.

Mientras tu paquete de datos mantenga el formato correcto y se envíe al Nodo Validador con tu clave de autenticación, tu servidor seguirá contribuyendo al ELO global. ¡Siéntete libre de hacer un fork de nuestro bot y adaptarlo 100% a las necesidades de tu comunidad!
