# Hosting a Validator Node

LFS Open Ranking System allows the community to protect and verify race integrity by running independent **Validator Nodes**. These nodes process the results sent by bot clients, check for consensus, and synchronize the global P2P network.

## How to Set Up Your Own Validator Node

We no longer depend on a traditional PHP web server. Now, any machine with Python can become a native Validator Node on the P2P network.

1. **Prerequisites**: 
   - **Python 3.12+** installed on your VPS or server.
   - Open ports to receive HTTP POST requests from other nodes and bots (default is port `8080`).
2. Clone the repository and go to the validator folder:
   ```bash
   git clone https://github.com/dgralf/lfs-open-ranking-system.git
   cd lfs-open-ranking-system/validator-node
   ```
3. Install the Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy the `.env.example` file to `.env` and adjust the environment variables if you need to configure a specific database or custom ports.
5. Start the node:
   ```bash
   ./start_validator.sh
   ```
6. Share your node's URL and port (e.g., `http://your-vps-ip:8080/ingest`) with other server owners so they can point their bots to your validator using the `--api_url` parameter.

### What Does the Validator Do Internally?
The validator constantly listens for requests from LFS Bots and the Web Portal on its `/ingest` endpoint. Its primary roles include:
1. **Token Redemption:** When a bot connects using an `SRV-` Invite Token, the Validator verifies the token against its local SQLite registry, accepts the bot's Ed25519 public key, and acts as a bridge by automatically synchronizing the new server into the Web Portal's MySQL database.
2. **Signature Verification:** For every race result received, it checks the mathematical validity of the cryptographic signature to ensure the data truly came from the registered bot.
3. **Immutable Ledger:** It generates a signed block, calculates the SHA-256 hash, and permanently appends the race into the `validator_node.db` SQLite database (The P2P Blockchain).
4. **Elo Updates:** It safely updates the players' global ELO ladder.

Hosting a validator helps decentralize the ecosystem, ensuring that LFS Open Ranking System is always fast, immutable, and resistant to downtime.
