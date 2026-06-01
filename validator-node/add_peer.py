import sqlite3
import datetime
import os

DB_FILE = "validator_node.db"
SEED_PEER = os.environ.get("SEED_PEER", "https://validator.lfsrank.com")

try:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # P2P: Known Peers table check
    c.execute("INSERT OR REPLACE INTO peers (address, last_seen) VALUES (?, ?)", 
              (SEED_PEER, datetime.datetime.now().isoformat()))
    conn.commit()
    print(f"Successfully added {SEED_PEER} to peers table.")
    
    # Verify
    c.execute("SELECT * FROM peers")
    print("Current Peers:")
    for row in c.fetchall():
        print(row)
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
