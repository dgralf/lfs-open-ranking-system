# Proceso de Validación

El sistema **LFS Open Ranking System** se apoya en un robusto mecanismo de validación criptográfica para asegurar que nadie pueda falsear resultados de carreras o manipular el ELO de los pilotos, incluso siendo una red descentralizada.

## Flujo Criptográfico de una Carrera

1. **Generación Local:** Al finalizar la carrera, el Bot Cliente del `Servidor A` genera un archivo JSON en bruto que contiene las posiciones, los tiempos (PBs) y la información del circuito/mod.
2. **Firma Criptográfica:** Antes de emitirlo, el Bot Cliente calcula el hash SHA-256 de esos resultados en crudo, y lo firma digitalmente con su Llave Privada Ed25519 generada localmente.
3. **Emisión (Broadcast):** El Bot Cliente envía este paquete (Resultados + Hash + Firma) mediante un POST HTTP seguro al Nodo Validador (`/ingest`).
4. **Verificación de Firmas:** El `Nodo Validador` recibe el bloque. Consulta su base de datos descentralizada P2P (SQLite) para obtener la clave pública vinculada al `Servidor A`. Con ella, ejecuta un algoritmo matemático para comprobar que la firma fue generada efectivamente por el dueño del servidor y que el JSON no ha sido alterado en ruta.
5. **Consenso y Gossiping:** Si la firma es correcta y los tiempos son lógicos, el `Nodo Validador` acepta la carrera. Le añade su propia marca de tiempo, la guarda en el registro inmutable (blockchain) y la propaga por la red al resto de nodos para que todos tengan la misma información.
6. **Recálculo de ELO:** Inmediatamente después de la verificación exitosa, el sistema de puntuación entra en acción recalculando el ELO de todos los pilotos involucrados basándose en sus enfrentamientos directos en la carrera.

## Integración Centralizada, Ejecución Descentralizada

Para evitar que actores maliciosos saturen la red creando servidores falsos, el sistema implementa un mecanismo de autenticación híbrido mediante **Tokens de Invitación**.

1. **Autenticación de Usuario:** Los dueños de servidores inician sesión en el Portal Web oficial utilizando sus cuentas verificadas de LFS.
2. **Generación de Tokens:** Generan un Token de Invitación único (`SRV-`) para su nuevo servidor.
3. **Canjeo y Generación de Claves:** El bot arranca usando este token. Genera de forma segura sus propias claves criptográficas Ed25519 localmente, y envía la Clave Pública al Nodo Validador junto con el Token de Invitación.
4. **Sincronización Dual:** El Validador verifica el Token, registra la Clave Pública del servidor en el registro P2P inmutable, y sirve de puente creando el servidor de vuelta en la base de datos MySQL del Portal Web. Esto asegura la máxima seguridad contra botnets manteniendo el proceso de integración completamente fluido.

## Resistencia contra Trampas

Dado que los Nodos Validadores no se fían ciegamente de los datos:
- **Tiempos absurdos:** Si un servidor envía un tiempo de vuelta imposible para una clase, el validador puede rechazar el bloque.
- **Suplantación de Identidad:** Es matemáticamente imposible que un servidor "invente" una carrera a nombre de otro, ya que carece de su llave Ed25519 privada.
- **Carreras Vacías:** El sistema de ELO requiere un mínimo de competidores reales; las carreras en solitario solo sirven para registrar PBs (Personal Bests), pero no afectan al ranking competitivo.
