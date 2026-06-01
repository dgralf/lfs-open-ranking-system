# LFS InSim Bot (Reference Implementation)
This bot is a fully functional base example of an InSim client. It connects to the Live for Speed server via InSim and sends cryptographically signed race data to the Global API. You are free to use it as-is, fork it to add your own custom features, or build your own client from scratch.

## Setup
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your LFS server details and API key.

## Running
Run the startup script:
```bash
./start_insim.sh
```

## Features
- Connects to LFS InSim (TCP)
- Tracks player connections/disconnections
- Tracks race results
- Sends data to `api_ingest.php`
- Handles basic chat commands (`!ping`)

## Structure
- `main.py`: Entry point and event handlers
- `insim.py`: InSim protocol implementation
- `api.py`: API communication
- `config.py`: Configuration loading
