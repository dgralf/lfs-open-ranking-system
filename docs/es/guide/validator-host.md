# Alojar un Nodo Validador

LFS Open Ranking System permite a la comunidad proteger y verificar la integridad de las carreras ejecutando **Nodos Validadores** independientes. Estos nodos procesan los resultados enviados por los bots clientes, comprueban el consenso y sincronizan la red P2P global.

## Cómo montar tu propio Nodo Validador

Ya no dependemos de un servidor web tradicional en PHP. Ahora, cualquier máquina con Python puede convertirse en un Nodo Validador nativo de la red P2P.

1. **Requisitos Previos**: 
   - **Python 3.12+** instalado en tu VPS o servidor.
   - Puertos abiertos para recibir peticiones HTTP POST de otros nodos y bots (por defecto el puerto `8080`).
2. Clona el repositorio y ve a la carpeta del validador:
   ```bash
   git clone https://github.com/dgralf/lfs-open-ranking-system.git
   cd lfs-open-ranking-system/validator-node
   ```
3. Instala las dependencias de Python:
   ```bash
   pip install -r requirements.txt
   ```
4. Copia el archivo `.env.example` como `.env` y ajusta las variables de entorno si necesitas configurar una base de datos o puertos específicos.
5. Inicia el nodo:
   ```bash
   ./start_validator.sh
   ```
6. Comparte la URL y puerto de tu nodo (ej. `http://tu-vps-ip:8080/ingest`) con otros dueños de servidores para que apunten sus bots a tu validador mediante el parámetro `--api_url`.

### ¿Qué hace el Validador por dentro?
El validador escucha constantemente peticiones de los Bots de LFS y del Portal Web en su endpoint `/ingest`. Sus roles principales incluyen:
1. **Canjeo de Tokens:** Cuando un bot se conecta usando un Token de Invitación `SRV-`, el Validador verifica el token contra su registro local SQLite, acepta la clave pública Ed25519 del bot, y actúa como un puente sincronizando automáticamente el nuevo servidor hacia la base de datos MySQL del Portal Web.
2. **Verificación de Firmas:** Para cada resultado de carrera recibido, comprueba la validez matemática de la firma criptográfica para asegurar que los datos provienen genuinamente del bot registrado.
3. **Libro Mayor Inmutable:** Genera un bloque firmado, calcula el hash SHA-256, y anexa permanentemente la carrera en la base de datos SQLite `validator_node.db` (La Blockchain P2P).
4. **Actualizaciones de Elo:** Actualiza de forma segura la escalera global de ELO de los jugadores.

Alojar un validador ayuda a descentralizar el ecosistema, asegurando que LFS Open Ranking System sea siempre rápido, inmutable y resistente a caídas.
