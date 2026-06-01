# Nodos P2P y Descentralización

LFS Open Ranking System opera como una red descentralizada de nodos validadores. Ningún servidor tiene el monopolio de la verdad; para que una carrera se considere "oficial" (y afecte al ELO global), el bloque de la carrera debe ser procesado y firmado por un Nodo Validador.

## Funcionamiento Criptográfico

1. **Generación Local**: El Bot Cliente detecta el final de una carrera (mediante paquetes `IS_RES` para cada jugador vía InSim). Genera un objeto JSON en bruto con los resultados.
2. **Envío Seguro**: El Bot Cliente se autentica usando firmas Ed25519 y envía el JSON por HTTP `POST` a su Nodo Validador asignado (por defecto la API principal de LFSRank).
3. **Consenso en el Nodo**: El Nodo Validador recibe el JSON. Verifica que la firma criptográfica corresponda a la Clave Pública al servidor que dice ser, calcula un **Hash SHA-256** del bloque, e incorpora el `previous_hash` (el hash de la carrera anterior de ese mismo servidor) para formar una cadena irrompible.
4. **Firma**: El Nodo Validador firma todo el paquete criptográficamente usando su Llave Maestra.
5. **Retransmisión P2P (Gossiping)**: El bloque, ya firmado y codificado como oficial, se comparte y sincroniza con el resto de la red de nodos P2P.

## Transparencia y Récords

Cualquier nodo de la red puede verificar de forma matemática la legitimidad de las carreras pasadas comprobando que los hashes coinciden de principio a fin, creando un historial inmutable de PBs (Personal Bests) y variaciones de ELO.
