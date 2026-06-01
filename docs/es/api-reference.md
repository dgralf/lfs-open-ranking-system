# Referencia de la API REST

LFS Open Ranking System se basa en una red descentralizada de **Nodos Validadores** (P2P). Puedes interactuar con estos nodos mediante su API HTTP.

> [!NOTE]
> A continuación se detallan los endpoints expuestos por el Nodo Validador en Python (`p2p_server.py`). Todas las respuestas se devuelven en formato `application/json`.

---

## 📡 Estado del Nodo

Comprueba si el nodo validador está online y funcionando.

- **URL**: `GET /status`

### Respuesta Real (Ejemplo)
```json
{
  "status": "online",
  "service": "LFS Validator Node"
}
```

---

## 📥 Ingesta de Datos de Carreras

Recibe los resultados en bruto desde un Bot Cliente de LFS. Este endpoint espera un JSON que contiene las firmas criptográficas y los datos de las vueltas, que el nodo validador verificará antes de propagarlos a la red P2P.

- **URL**: `POST /ingest`
- **Content-Type**: `application/json`

### Ejemplo de Payload
```json
{
  "server_id": "Mi Servidor LFS",
  "signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "data": {
    "track": "BL1",
    "allowed_cars": "XFG",
    "results": [
      {
        "position": 1,
        "uname": "danielin",
        "total_time": 92350
      }
    ]
  }
}
```

### Respuesta Real (Ejemplo)
```json
{
  "status": "success",
  "message": "Race data verified and queued for consensus."
}
```

> [!IMPORTANT]
> Al configurar tu Bot Cliente (`system.py`), el parámetro `--api_url` debe apuntar al endpoint `/ingest` de un nodo validador. El validador público oficial está disponible en: `https://validator.lfsrank.com/ingest`.
