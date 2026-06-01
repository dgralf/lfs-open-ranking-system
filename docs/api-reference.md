# REST API Reference

The LFS Open Ranking System relies on a decentralized network of **Validator Nodes** (P2P). You can interact with these nodes via their HTTP API.

> [!NOTE]
> Below are the endpoints exposed by the Python Validator Node (`p2p_server.py`). All responses are returned in `application/json` format.

---

## 📡 Node Status

Checks if the validator node is online and functioning.

- **URL**: `GET /status`

### Real Response (Example)
```json
{
  "status": "online",
  "service": "LFS Validator Node"
}
```

---

## 📥 Ingest Race Data

Receives raw race results from an LFS Bot Client. This endpoint expects a JSON payload containing cryptographic signatures and lap data, which the validator node will verify before broadcasting to the P2P network.

- **URL**: `POST /ingest`
- **Content-Type**: `application/json`

### Payload Example
```json
{
  "server_id": "My LFS Server",
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

### Real Response (Example)
```json
{
  "status": "success",
  "message": "Race data verified and queued for consensus."
}
```

> [!IMPORTANT]
> When configuring your Bot Client (`system.py`), the `--api_url` parameter must point to a validator node's `/ingest` endpoint. The official public validator is available at: `https://validator.lfsrank.com/ingest`.
