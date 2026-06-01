# LFS P2P Developer Guide

## Overview
The LFS P2P Node acts as a sovereign data source for race statistics and ELO rankings. Unlike the old central website, YOU control the data.

This guide explains how to extract data from your node to build:
*   Website Leaderboards
*   Discord Bots
*   Mobile Apps

---

## 1. HTTP API (JSON)
The easiest way to get data is via the built-in HTTP API.

**Base URL**: `http://127.0.0.1:8080`

### Get Top Rankings
*   **Endpoint**: `GET /api/rankings`
*   **Response**:
    ```json
    {
        "status": "success",
        "rankings": [
            {"uname": "RacerA", "elo": 1520, "wins": 5, "races": 10},
            {"uname": "RacerB", "elo": 1490, "wins": 1, "races": 8}
        ]
    }
    ```

### Get Race History (Explorer)
*   **Endpoint**: `GET /api/races?page=1&limit=20`
*   **Response**:
    ```json
    {
        "status": "success",
        "races": [
            {
                "id": 105,
                "track": "BL1",
                "results": "[...]", 
                "created_at": "2026-01-10T..." 
            }
        ],
        "total": 500,
        "page": 1
    }
    ```

### Example Code

**Python**:
```python
import requests

response = requests.get("http://127.0.0.1:8080/api/rankings")
data = response.json()

for player in data['rankings']:
    print(f"{player['uname']}: {player['elo']} ELO")
```

**JavaScript (Frontend)**:
```javascript
fetch("http://127.0.0.1:8080/api/rankings")
  .then(response => response.json())
  .then(data => {
    console.log("Top Players:", data.rankings);
  });
```

---

## 2. Direct Database Access (SQLite)
For advanced analysis (SQL queries), you can read the database file directly. The file is **SQLite3** format.

**File Path**: `/root/lfs/validator/validator_node.db`

### Schema
*   **`players` table**:
    *   `uname` (Text, PK): LFS Username
    *   `elo` (Int): Current ELO Rating
    *   `wins` (Int): Total Wins
    *   `races` (Int): Total Races Run

*   **`races` table**:
    *   `id` (Int, PK)
    *   `results` (JSON): Raw race result dump
    *   `track` (Text): Track Code (e.g., BL1, AS1)
    *   `created_at` (Text): Timestamp

### Example Query
```sql
-- Find top 5 players with more than 10 races
SELECT * FROM players 
WHERE races > 10 
ORDER BY elo DESC 
LIMIT 5;
```

---

## 3. Remote Access (Website on different Server)
If your website is on a **Different IP** (e.g. Validator is `1.2.3.4`, Website is `5.6.7.8`), you must expose the API safely.

**Configuration on Validator Server (Nginx)**:
```nginx
server {
    listen 80;
    server_name validator.my-domain.com;

    location /api/ {
        # Allow ONLY your website IP
        allow 5.6.7.8;
        deny all;

        proxy_pass http://127.0.0.1:8080/;
    }
}
```
**Usage**:
Your website PHP code should now call:
`http://validator.my-domain.com/api/rankings`

**Warning**: NEVER open Port 8080 directly in the Python script (`p2p_node.py`). Always use Nginx as a shield.
