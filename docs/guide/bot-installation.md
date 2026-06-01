# Bot Client Installation (`system.py`)

For your server to send statistics to the global **LFS Open Ranking System** network, you must run our Bot Client. This program acts as an intermediary between your LFS server and the decentralized validator network.

## Prerequisites
1. **Python 3.12+** installed on your machine (Windows or Linux).
2. The `cryptography` library installed (`pip install cryptography`).
3. A Live for Speed server running with the InSim port enabled.
4. An Invite Token generated from your Web Dashboard.

## Step-by-Step Installation

1. Clone the official repository from GitHub:
   ```bash
   git clone https://github.com/dgralf/lfs-open-ranking-system.git
   cd lfs-open-ranking-system/bot-client
   ```
2. Install the necessary dependencies: 
   ```bash
   pip install -r requirements.txt
   ```
3. Generate your Invite Token:
   Go to your dashboard on [lfsrank.com](https://lfsrank.com/) and create a new server to receive your `SRV-XXXXXX` token.
4. Start the bot:
   Run the bot with your token. The bot will automatically generate its secure Ed25519 identity, redeem the token on the global network, and securely link itself to your web account.
   ```bash
   python3 system.py --host 127.0.0.1 --insim_port 29999 --admin your_pass --invite_token SRV-XXXXXX
   ```

**Available Parameters:**
- `--host`: Your LFS server IP (default `127.0.0.1`).
- `--insim_port`: Your LFS server InSim port.
- `--admin`: Your server's InSim admin password.
- `--invite_token`: The unique token generated from your web dashboard.
- `--api_url`: The URL of the validator node to send data to (default: `http://validator.lfsrank.com/ingest`).

> [!TIP]
> If you are on a **Linux VPS**, it is recommended to use a process manager like `screen` or `tmux` so the bot stays online after closing the console.

