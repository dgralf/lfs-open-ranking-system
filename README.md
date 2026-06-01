# LFS Open Ranking System

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Version](https://img.shields.io/badge/Version-2.0.0-green.svg)

LFS Open Ranking System is a global, decentralized ELO matchmaking and statistics tracking platform for **Live for Speed (LFS)**. It unifies drivers across multiple servers worldwide into a single competitive ladder, completely eliminating the fragmentation of local server trackers.

## 🌟 Key Features
- **Global ELO System:** A skill-based matchmaking score updated in real-time after every race, spanning across the entire P2P network.
- **Cryptographic P2P Consensus:** A decentralized, blockchain-like ledger powered by SQLite. Uses Ed25519 and SHA-256 to sign and verify race results, making it mathematically impossible to spoof times or manipulate scores.
- **Unified Web Dashboard:** A centralized portal to view global rankings, inspect raw block data via the Blockchain Explorer, and manage your connected servers and bot configurations in real-time.
- **Frictionless Authentication:** Automated cryptographic identity generation via `SRV_` invite tokens seamlessly bridges the gap between your local bots and the global Web Portal.

## 📖 Documentation
All the documentation on how to connect your server, install the bot, or host your own validator node can be found on our official documentation site:

👉 **[docs.lfsrank.com](https://docs.lfsrank.com/)**

---

## 🏗️ Architecture

The system is divided into two seamlessly integrated components:

### 1. Bot Client (For LFS Server Owners)
The lightweight Python daemon that runs alongside your LFS server. It connects to the InSim port, tracks race sessions, and transmits the results to the Global API.

### 2. Web Portal & Global API
The user-facing platform. It calculates the global ELO ladder based on the data received from all verified bots. It also provides a secure dashboard where server owners can generate API Keys to seamlessly connect their bots to the network.

---

## 🚀 Getting Started (Connecting your Server)

Joining the global network is completely automated.

1. **Link your LFS Account:**
   Join any official LFS Open Ranking System server and type `!register` in the chat. You will receive an Auth Code. Go to [lfsrank.com](https://lfsrank.com/) and use the code to link your LFS username.

2. **Generate an API Key:**
   Once logged into the Web Portal, go to the **Servers** tab and click **"Add Server"**. Click **"Generate Key"** to receive a unique API Key for your server.
   *(Alternatively, you can join any official connected LFS server and type `!register server` in the chat to generate your API Key directly in-game).*

3. **Install the Bot:**
   ```bash
   git clone https://github.com/dgralf/lfs-open-ranking-system.git
   cd lfs-open-ranking-system/bot-client
   pip install -r requirements.txt
   ```

4. **Configure your Server:**
   Rename the `.env.example` file to `.env` (or create a new `.env` file) inside the `bot-client` directory, and paste your API Key and InSim details:
   ```env
   API_KEY=your_server_api_key_here
   INSIM_HOST=127.0.0.1
   INSIM_PORT=29999
   INSIM_ADMIN_PASS=your_lfs_admin_pass
   ```

5. **Connect the Bot to the Network:**
   Run the bot. It will automatically authenticate using your API Key and start syncing races with the global ladder!
   ```bash
   ./start_bot.sh
   # Or manually:
   # python3 system.py
   ```

## 🤝 Contributing
Since LFS Open Ranking System is fully open-source, you are free to fork the bot client to add custom commands or logic for your community, as long as it correctly communicates with the Global API.

## 📝 License
This project is released under the [MIT License](LICENSE). Copyright © 2025-2026 LFS Open Ranking System Team.
