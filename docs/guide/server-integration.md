# Server Integration

If you own an LFS server (or host one on `lfs.net`), you can contribute to the global network by linking your server with the **LFS Open Ranking System** network.

## Requirements

- Access to your server's **InSim** port (this can be activated from the web panel if using LFS hosting).
- Your server must allow downloading mods (`AllowMods 1`).
- To install our Bot Client, you need Windows or Linux with **Python 3.12+**.
> [!TIP]
> **Recommendation:** We highly recommend installing the Bot on a low-cost Linux **VPS (Virtual Private Server)** (Ubuntu/Debian) to ensure 24/7 uptime and prevent players' statistics from being lost when you turn off your PC.

## LFS Server Configuration

Server configuration (Name, Welcome Message, passwords, etc.) is now managed directly from your control panel at [https://www.lfs.net/hosting](https://www.lfs.net/hosting). 

From there, ensure you have the following configured:
- **InSim**: Activate it and note down the Port and Admin Password (you will need them for the Bot).
- **Allow downloading mods**: Must be set to **Yes** (If not active, random multiclass races with mods will fail).

If you host your server on **lfs.net/hosting**, basic configuration is done via their web panel, but keep in mind these vital details for the Bot:

- **InSim IP Whitelist**: On LFS.net, the InSim port is active by default, but blocks all connections for security. You must go to the LFS panel and **add the IP of the machine where you run the Bot** to the whitelist so it can connect.
- **Mods**: Ensure the server is configured to allow downloading mods (usually enabled via commands like `/mods=`), otherwise the Bot won't be able to rotate classes.

---

## Bot Client Installation

The **Bot Client** is a lightweight Python program that connects your LFS server with our decentralized global network (P2P). It is responsible for sending InSim menus to the chat, recording lap times, and calculating ELO in real time.

1. Clone the official repository (`git clone https://github.com/dgralf/lfs-open-ranking-system.git`).
2. Navigate to the bot folder (`cd lfs-open-ranking-system/bot-client`) on your local PC or VPS (it doesn't have to be on the same machine as the LFS server, as long as it can reach the IP/Port).
3. Install the necessary dependencies (`pip install -r requirements.txt`).
4. **Register your User Account:** Join an LFS server running our system, type `!register`, and use the provided Auth Code to log in at [lfsrank.com](https://lfsrank.com/).
5. **Get your Server Token:** From the web dashboard, create a new server to obtain your `SRV-XXXXXX` Invite Token.
6. Run the bot. It will automatically generate your cryptographic identity and link to your web account: (`python3 system.py --host your-ip --insim_port 29999 --admin your_pass --invite_token SRV-XXXXXX`).

> [!WARNING]
> **InSim IP Whitelist (Mandatory):** Since your server is hosted on `lfs.net`, you must explicitly grant the bot permission to connect. Go to your server's control panel on the LFS.net website and navigate to **Access control** -> **Allow IP addresses to the InSim port**. Add the IP of the machine where you are running the bot (e.g., the IP of your VPS or your home's public IP). If this field is left empty, LFS will permanently block the bot's InSim connection.

## What exactly does the bot do?

Once connected, the bot will automate the entire server lifecycle:
- **Race Management**: Automatically detects the start and end of races.
- **Auto Voting**: If enabled, offers 5 random votes after a rotation ends (with random cars and weather).
- **Secure Syncing**: Securely transmits the verified results of each race to the Validator Node, which then registers it on the global network and updates the ELOs.
- **Useful Commands**: Enables commands like `!vote`, `!stats`, `!pb`, and `!admin` so your drivers can interact without leaving the track.
- **Multiclass Support**: Smartly selects car categories, dynamically mixing base cars with mods if you choose to.

## Privacy and Security

The Bot Client architecture guarantees your security:

- **Outbound Connections:** The bot does not require opening any ports on your router. It uses outbound connections, making it impossible for an external attacker to connect to your machine.
- **Open Source:** The `system.py` script is fully transparent. You can audit it to verify that it only reads InSim data and sends it to the network, without accessing personal files.
- **Total Encryption:** All communications with the P2P network are encrypted via **HTTPS (SSL/TLS)**.

> [!IMPORTANT]
> **Final Recommendation:** Although it is 100% safe to run it on your personal computer, we strongly recommend using a **VPS (Virtual Private Server)** both to ensure 24/7 uptime for your statistics and to maintain an extra layer of professional isolation and security for your home networks.
