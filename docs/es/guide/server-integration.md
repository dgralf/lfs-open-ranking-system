# Integración para Servidores

Si eres dueño de un servidor de LFS (o tienes uno alojado en `lfs.net`), puedes contribuir a la red global vinculando tu servidor con la red de **LFS Open Ranking System**.

## Requisitos

- Acceso al puerto **InSim** de tu servidor (se puede activar desde la web si usas hosting de LFS).
- Tu Servidor debe permitir descargar Mods (`AllowMods 1`).
- Para instalar nuestro Bot Cliente, necesitas Windows o Linux con **Python 3.12+**. 
> [!TIP]
> **Recomendación:** Recomendamos encarecidamente instalar el Bot en un **VPS (Servidor Privado Virtual)** de bajo coste con Linux (Ubuntu/Debian) para asegurar un uptime del 24/7 y evitar que se pierdan las estadísticas de los jugadores cuando apagas tu PC.

## Configuración del Servidor LFS

Si alojas tu servidor en **lfs.net/hosting**, la configuración base se realiza desde su panel web, pero ten en cuenta estos detalles vitales para el Bot:

- **InSim IP Whitelist**: En LFS.net, el puerto InSim está activo por defecto, pero por seguridad bloquea todas las conexiones. Debes ir al panel de LFS y **añadir la IP de la máquina donde ejecutas el Bot** a la lista blanca (Whitelist) para que le permita conectarse.
- **Mods**: Asegúrate de que el servidor está configurado para permitir descargar mods (usualmente habilitado por defecto o mediante comandos `/mods=`), de lo contrario el Bot no podrá rotar categorías.

---

## Instalación del Bot Cliente

El **Bot Cliente** es un programa ligero de Python que conecta tu servidor de LFS con nuestra red global descentralizada (P2P). Es el encargado de enviar los menús InSim al chat, grabar los tiempos y calcular el ELO en tiempo real.

1. Clona el repositorio oficial (`git clone https://github.com/dgralf/lfs-open-ranking-system.git`).
2. Navega a la carpeta del bot (`cd lfs-open-ranking-system/bot-client`) en tu PC local o VPS (no tiene por qué estar en la misma máquina que el servidor LFS, siempre que pueda alcanzar la IP/Puerto).
3. Instala las dependencias necesarias (`pip install -r requirements.txt`).
4. **Registra tu Cuenta de Usuario:** Entra a un servidor de LFS que use nuestro sistema, escribe `!register`, y usa el Código de Autenticación para iniciar sesión en [lfsrank.com](https://lfsrank.com/).
5. **Obtén el Token de tu Servidor:** Desde el panel web, crea un nuevo servidor para obtener tu Token de Invitación `SRV-XXXXXX`.
6. Ejecuta el bot. Automáticamente generará tu identidad criptográfica y se enlazará a tu cuenta web: (`python3 system.py --host tu-ip --insim_port 29999 --admin tu_pass --invite_token SRV-XXXXXX`).

> [!WARNING]
> **Lista Blanca de IPs InSim (Obligatorio):** Dado que tu servidor está alojado en `lfs.net`, debes dar permiso explícito al bot para conectarse. Ve al panel de control de tu servidor en la web de LFS.net y navega a **Access control** -> **Allow IP addresses to the InSim port**. Añade la IP de la máquina donde estás corriendo el bot (por ejemplo la IP de tu VPS o la IP pública de tu casa). Si esta casilla se deja vacía, LFS bloqueará permanentemente la conexión InSim del bot.

## ¿Qué hace el bot exactamente?

Una vez conectado, el bot automatizará todo el ciclo de vida del servidor:
- **Gestión de Carreras**: Detectará automáticamente el inicio y final de las carreras.
- **Votaciones Automáticas**: Si activas la opción, ofrecerá 5 votaciones aleatorias al acabar una rotación (con coches y clima al azar).
- **Sincronización Segura**: Transmitirá de forma segura los resultados verificados de cada carrera al Nodo Validador, el cual se encarga de registrarla en la red global y actualizar los ELOs.
- **Comandos Útiles**: Habilitará comandos como `!vote`, `!stats`, `!pb`, y `!admin` para que tus pilotos interactúen sin salir de pista.
- **Soporte Multiclase**: Seleccionará categorías de forma inteligente, mezclando coches base con mods dinámicamente si así lo decides.

## Privacidad y Seguridad

El diseño de la arquitectura del Bot Cliente garantiza tu seguridad:

- **Conexiones Salientes:** El bot no requiere abrir ningún puerto en tu router. Funciona mediante conexiones salientes, lo que hace imposible que un atacante externo se conecte a tu máquina.
- **Código Abierto (Open Source):** El script `system.py` es totalmente transparente. Puedes auditarlo para comprobar que solo lee datos de InSim y los envía a la red, sin acceder a archivos personales.
- **Cifrado Total:** Todas las comunicaciones con la red P2P viajan cifradas por **HTTPS (SSL/TLS)**.

> [!IMPORTANT]
> **Recomendación Final:** Aunque es 100% seguro correrlo en tu ordenador personal, recomendamos fervientemente el uso de un **VPS (Servidor Privado Virtual)** tanto para asegurar un Uptime del 24/7 de tus estadísticas, como por mantener una capa extra de aislamiento y seguridad profesional de tus redes domésticas.
