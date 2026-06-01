# Instalación del Bot Cliente (`system.py`)

Para que tu servidor envíe estadísticas a la red global **LFS Open Ranking System**, debes ejecutar nuestro Bot Cliente. Este programa actúa como intermediario entre tu servidor LFS y la red descentralizada de validadores.

## Requisitos Previos
1. **Python 3.12+** instalado en tu máquina (Windows o Linux).
2. La librería `cryptography` instalada (`pip install cryptography`).
3. Un servidor de Live for Speed en ejecución con el puerto InSim habilitado.
4. Un Token de Invitación generado desde tu Panel Web.

## Instalación Paso a Paso

1. Clona el repositorio oficial desde GitHub:
   ```bash
   git clone https://github.com/dgralf/lfs-open-ranking-system.git
   cd lfs-open-ranking-system/bot-client
   ```
2. Instala las dependencias necesarias: 
   ```bash
   pip install -r requirements.txt
   ```
3. Genera tu Token de Invitación:
   Ve a tu panel en [lfsrank.com](https://lfsrank.com/) y crea un nuevo servidor para recibir tu token `SRV-XXXXXX`.
4. Inicia el bot:
   Ejecuta el bot con tu token. El bot generará automáticamente su identidad criptográfica segura Ed25519, canjeará el token en la red global y se vinculará de forma segura a tu cuenta web.
   ```bash
   python3 system.py --host 127.0.0.1 --insim_port 29999 --admin tu_contraseña --invite_token SRV-XXXXXX
   ```

**Parámetros Disponibles:**
- `--host`: La IP de tu servidor LFS (por defecto `127.0.0.1`).
- `--insim_port`: El puerto InSim de tu servidor LFS.
- `--admin`: La contraseña de administrador InSim de tu servidor.
- `--invite_token`: El token único generado desde tu panel web.
- `--api_url`: La URL del nodo validador al que enviar los datos (por defecto: `http://validator.lfsrank.com/ingest`).

> [!TIP]
> Si estás en un **VPS Linux**, se recomienda usar un gestor de procesos como `screen` o `tmux` para que el bot siga en línea después de cerrar la consola.
