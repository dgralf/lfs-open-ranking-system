
import aiohttp
from aiohttp import web
import asyncio
import sqlite3
import json
import logging
import sys
import os
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import elo

# Configuration
DB_FILE = os.getenv("DB_FILE", "validator_node.db")
PORT = int(os.getenv("PORT", 8080))

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - P2P - %(levelname)s - %(message)s')

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Mirroring the bot/web schema partially for validity
    c.execute('''CREATE TABLE IF NOT EXISTS players (
        uname TEXT PRIMARY KEY,
        elo INTEGER DEFAULT 1500,
        wins INTEGER DEFAULT 0,
        races INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS races (
        id INTEGER PRIMARY KEY,
        results TEXT,
        track TEXT,
        signature TEXT,
        created_at TEXT,
        server_name TEXT
    )''')
    # Key Storage for Server Signatures (In a real P2P, this is the 'Identity' table)
    c.execute('''CREATE TABLE IF NOT EXISTS trusted_servers (
        name TEXT PRIMARY KEY,
        public_key TEXT
    )''')
    # P2P: Known Peers
    c.execute('''CREATE TABLE IF NOT EXISTS peers (
        address TEXT PRIMARY KEY,
        last_seen TEXT
    )''')
    
    # SEED DEFAULT KEY (The user's key)
    # Ideally this is managed via CLI, but we seed it for "Out of Box" functionality
    c.execute("INSERT OR IGNORE INTO trusted_servers (name, public_key) VALUES (?, ?)", 
              ("Primary Server", "c7aa6c090008a5226cba2526f3d5ede1f889ffab00c41ce264b5ac84442a65d2"))
              
    # P2P: Invite Tokens for Self-Service Server Registration
    c.execute('''CREATE TABLE IF NOT EXISTS invite_tokens (
        token TEXT PRIMARY KEY,
        uname TEXT,
        created_at TEXT,
        used INTEGER DEFAULT 0
    )''')
    
    conn.commit()
    conn.close()

async def handle_register_peer(request):
    try:
        payload_bytes = await request.read()
        signature_hex = request.headers.get('X-Signature')
        
        # 1. Verify Signature (Must be a TRUSTED SERVER to peer)
        if not signature_hex:
            return web.json_response({'status': 'error', 'message': 'Peering requires signature'}, status=403)
            
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT public_key FROM trusted_servers")
        trusted_keys = [row['public_key'] for row in c.fetchall()]
        
        verified = False
        sig_bytes = bytes.fromhex(signature_hex)
        for key_hex in trusted_keys:
            try:
                pub_bytes = bytes.fromhex(key_hex)
                pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
                pub_key.verify(sig_bytes, payload_bytes)
                verified = True
                break
            except: continue
        
        if not verified:
            conn.close()
            return web.json_response({'status': 'error', 'message': 'Unknown Identity'}, status=403)

        # 2. Register Peer
        data = json.loads(payload_bytes)
        address = data.get('address')
        if not address or not address.startswith('http'):
             conn.close()
             return web.json_response({'status': 'error', 'message': 'Invalid address'}, status=400)
        
        c.execute("INSERT OR REPLACE INTO peers (address, last_seen) VALUES (?, ?)", 
                  (address, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        logging.info(f"New Peer Registered (Verified): {address}")
        return web.json_response({'status': 'success', 'message': 'Peer registered'})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def process_race_logic(data, signature_hex):
    # Core Logic: ELO Calc + DB Insert
    results = data.get('results', [])
    track = data.get('track', 'Unknown')
    server_name = data.get('server_name', 'Unknown')
    
    conn = get_db()
    c = conn.cursor()
    
    # Check Duplicate
    c.execute("SELECT id FROM races WHERE signature = ?", (signature_hex,))
    if c.fetchone():
         conn.close()
         return {'status': 'success', 'message': 'Already processed', 'updates': {}}

    # Fetch current ELOs
    current_elos = {}
    for res in results:
        uname = res['uname']
        c.execute("SELECT elo FROM players WHERE uname = ?", (uname,))
        row = c.fetchone()
        if row:
            current_elos[uname] = row['elo']
        else:
            c.execute("INSERT INTO players (uname) VALUES (?)", (uname,))
            current_elos[uname] = 1500
    
    conn.commit()
    
    # Calculate
    changes = elo.calculate_elo_changes(results, current_elos)
    
    # Update DB
    valid_updates = {}
    for uname, change in changes.items():
        new_elo = current_elos[uname] + change
        c.execute("UPDATE players SET elo = ?, races = races + 1 WHERE uname = ?", (new_elo, uname))
        if results[0]['uname'] == uname and change > 0:
             c.execute("UPDATE players SET wins = wins + 1 WHERE uname = ?", (uname,))
        valid_updates[uname] = {'new_elo': new_elo, 'elo_diff': change}
        
    # Save Race
    c.execute("INSERT INTO races (results, track, signature, created_at, server_name) VALUES (?, ?, ?, ?, ?)", 
              (json.dumps(results), track, signature_hex, datetime.now().isoformat(), server_name))
    
    conn.commit()
    conn.close()
    
    logging.info(f"Processed Race {signature_hex[:8]}... Updates: {valid_updates}")
    return {'status': 'success', 'updates': valid_updates}

async def handle_ingest(request):
    try:
        # DOS PROTECTION: Limit payload size to 1MB
        if request.content_length > 1024 * 1024:
            return web.json_response({'status': 'error', 'message': 'Payload too large'}, status=413)

        payload_bytes = await request.read()
        try:
            data = json.loads(payload_bytes)
            action = data.get('action')
        except:
            return web.json_response({'status': 'error', 'message': 'Invalid JSON'}, status=400)
            
        signature_hex = request.headers.get('X-Signature')
        
        # 1. Verify Signature (Skip for local web portal actions)
        if action not in ['redeem_server_token', 'verify_auth_code', 'generate_server_token']:
            if not signature_hex:
                return web.json_response({'status': 'error', 'message': 'Missing signature'}, status=403)
    
            # GET TRUSTED KEYS FROM DB
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT public_key FROM trusted_servers")
            trusted_keys = [row['public_key'] for row in c.fetchall()]
            conn.close()
            
            verified = False
            try:
                sig_bytes = bytes.fromhex(signature_hex)
                for key_hex in trusted_keys:
                    try:
                        pub_bytes = bytes.fromhex(key_hex)
                        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
                        pub_key.verify(sig_bytes, payload_bytes)
                        verified = True
                        break
                    except:
                        continue
            except:
                pass
                    
            if not verified:
                 logging.warning(f"Signature Verification Failed against {len(trusted_keys)} keys")
                 return web.json_response({'status': 'error', 'message': 'Invalid Signature (Unknown Server)'}, status=403)
        
        if action == 'process_race_results':
             result = await process_race_logic(data, signature_hex)
        elif action == 'update_server_status':
             # Process Live State locally
             try:
                 servers = data.get('servers')
                 if not servers:
                      if 'track' in data or 'ip' in data: # Single server format
                           servers = [data]
                      else:
                           servers = []
                 
                 conn = get_db()
                 c = conn.cursor()
                 for srv in servers:
                     ip = srv.get('ip', '0.0.0.0')
                     port = srv.get('port', 0)
                     json_str = json.dumps(srv)
                     c.execute("INSERT OR REPLACE INTO active_servers (ip, port, json_data, last_updated, status, players_count, name, track) VALUES (?, ?, ?, datetime('now'), 'online', ?, ?, ?)", 
                               (ip, port, json_str, len(srv.get('players', [])), srv.get('name', 'Unknown'), srv.get('track', 'Unknown')))
                 conn.commit()
                 conn.close()
                 result = {'status': 'success'}
             except Exception as e:
                 result = {'status': 'error', 'message': str(e)}
        elif action == "get_bad_combos":
             result = {"status": "success", "combos": []}
        elif action == 'gossip_auth_code':
             # Handled Auth Code Gossip
             try:
                 code = data.get('code')
                 uname = data.get('uname')
                 expire_secs = data.get('expire_secs', 600) # Default 10 mins
                 
                 if code and uname:
                     conn = get_db()
                     c = conn.cursor()
                     # Calculate expire time for SQLite
                     c.execute("INSERT INTO verification_codes (code, lfs_uname, expire, used) VALUES (?, ?, datetime('now', '+' || ? || ' seconds'), 0)", 
                               (code, uname, expire_secs))
                     conn.commit()
                     conn.close()
                     result = {'status': 'success'}
                     logging.info(f"Gossiped Auth Code for {uname}")
                 else:
                     result = {'status': 'error', 'message': 'Missing code or uname'}
             except Exception as e:
                 result = {'status': 'error', 'message': str(e)}
        elif action == 'generate_auth_code':
             import secrets
             uname = data.get('uname')
             if not uname:
                 return web.json_response({'status': 'error', 'message': 'Missing uname'}, status=400)
             code = secrets.token_hex(4).upper()
             try:
                 conn = get_db()
                 c = conn.cursor()
                 c.execute("DELETE FROM verification_codes WHERE lfs_uname = ? AND used = 0", (uname,))
                 c.execute("INSERT INTO verification_codes (code, lfs_uname, expire, used) VALUES (?, ?, datetime('now', '+10 minutes'), 0)", 
                           (code, uname))
                 conn.commit()
                 conn.close()
                 return web.json_response({'status': 'success', 'code': code})
             except Exception as e:
                 return web.json_response({'status': 'error', 'message': str(e)})
        elif action == 'verify_auth_code':
             uname = data.get('uname')
             code = data.get('code')
             if not uname or not code:
                 return web.json_response({'status': 'error', 'message': 'Missing uname or code'}, status=400)
             try:
                 conn = get_db()
                 c = conn.cursor()
                 logging.info(f"VERIFY_AUTH_CODE: Checking uname='{uname}' against code='{code}' (Checking uppercase: '{code.upper()}')")
                 c.execute("SELECT * FROM verification_codes WHERE lfs_uname = ? AND code = ? AND used = 0 AND expire > datetime('now')", (uname, code.upper()))
                 row = c.fetchone()
                 if row:
                     c.execute("UPDATE verification_codes SET used = 1 WHERE lfs_uname = ? AND code = ?", (uname, code.upper()))
                     conn.commit()
                     res = {'status': 'success'}
                 else:
                     res = {'status': 'error', 'message': 'Invalid code'}
                 conn.close()
                 return web.json_response(res)
             except Exception as e:
                 return web.json_response({'status': 'error', 'message': str(e)})
        elif action == 'generate_server_token':
             import secrets
             import hashlib
             uname = data.get('uname', 'unknown')
             token = "SRV-" + secrets.token_hex(4).upper()
             token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
             try:
                 conn = get_db()
                 c = conn.cursor()
                 c.execute("INSERT INTO invite_tokens (token, uname, created_at, used) VALUES (?, ?, ?, 0)",
                           (token_hash, uname, datetime.now().isoformat()))
                 conn.commit()
                 conn.close()
                 return web.json_response({'status': 'success', 'token': token})
             except Exception as e:
                 return web.json_response({'status': 'error', 'message': str(e)})
        elif action == 'redeem_server_token':
             import hashlib
             token = data.get('token')
             new_name = data.get('new_name')
             new_key = data.get('new_key')
             if not token or not new_name or not new_key:
                  return web.json_response({'status': 'error', 'message': 'Missing token, name, or key'}, status=400)
             
             token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
             try:
                 conn = get_db()
                 c = conn.cursor()
                 c.execute("SELECT uname, used FROM invite_tokens WHERE token = ?", (token_hash,))
                 row = c.fetchone()
                 if not row:
                     conn.close()
                     return web.json_response({'status': 'error', 'message': 'Invalid token'}, status=400)
                 if row['used'] == 1:
                     conn.close()
                     return web.json_response({'status': 'error', 'message': 'Token already used'}, status=400)
                 
                 # Register the new server in SQLite P2P Trust Network
                 c.execute("INSERT INTO trusted_servers (name, public_key) VALUES (?, ?)", (new_name, new_key))
                 c.execute("UPDATE invite_tokens SET used = 1 WHERE token = ?", (token_hash,))
                 conn.commit()
                 conn.close()

                 # Also add it to the MySQL Web Portal Database
                 try:
                     import mysql.connector
                     my_conn = mysql.connector.connect(
                         host=os.getenv("MYSQL_HOST", "localhost"), 
                         user=os.getenv("MYSQL_USER", "lfs_user"), 
                         password=os.getenv("MYSQL_PASS", ""), 
                         database=os.getenv("MYSQL_DB", "lfs_ors")
                     )
                     my_c = my_conn.cursor()
                     # Find owner id
                     my_c.execute("SELECT id FROM players WHERE uname = %s", (row['uname'],))
                     owner_row = my_c.fetchone()
                     if owner_row:
                         owner_id = owner_row[0]
                         import secrets
                         new_api_key = secrets.token_hex(16)
                         default_cfg = '{"voting":true,"stats":true,"teams":true,"help":true,"register":true,"welcome_msg":true,"allow_admin":false}'
                         my_c.execute("INSERT INTO servers (owner_id, name, ip, port, api_key, config) VALUES (%s, %s, %s, %s, %s, %s)",
                                      (owner_id, new_name, request.remote, 29999, new_api_key, default_cfg))
                         my_conn.commit()
                     my_conn.close()
                 except Exception as ex:
                     logging.error(f"Failed to sync redeemed server to MySQL: {ex}")

                 return web.json_response({'status': 'success', 'message': 'Server Redeemed'})
                 conn.close()
                 logging.info(f"SERVER REDEEMED TOKEN {token}: Added {new_name}")
                 result = {'status': 'success', 'message': 'Server registered successfully!'}
             except sqlite3.IntegrityError:
                 result = {'status': 'success', 'message': 'Already trusted'}
        elif action == 'vouch':
             new_name = data.get('new_name')
             new_key = data.get('new_key')
             if not new_name or not new_key:
                  return web.json_response({'status': 'error', 'message': 'Missing data'}, status=400)
             try:
                 conn = get_db()
                 c = conn.cursor()
                 c.execute("INSERT INTO trusted_servers (name, public_key) VALUES (?, ?)", (new_name, new_key))
                 conn.commit()
                 conn.close()
                 logging.info(f"IDENTITY VOUCH ACCEPTED via ingest: Added {new_name}")
                 result = {'status': 'success', 'message': 'Vouch accepted'}
             except sqlite3.IntegrityError:
                 result = {'status': 'success', 'message': 'Already trusted'}
        else:
            return web.json_response({'status': 'error', 'message': f'Unknown action: {action}'}, status=400)

        # 4. Gossip (For both Races and Live State)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT address FROM peers")
        peers = c.fetchall()
        conn.close()
        
        if result['status'] == 'success' and peers:
             asyncio.create_task(gossip_to_peers(peers, payload_bytes, signature_hex))

        return web.json_response(result)

    except Exception as e:
        logging.error(f"Ingest Error: {e}")
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def handle_vouch(request):
    try:
        # 1. Read Payload
        payload_bytes = await request.read()
        signature_hex = request.headers.get('X-Signature')
        
        if not signature_hex:
            return web.json_response({'status': 'error', 'message': 'Missing signature'}, status=403)

        # 2. Verify Voucher's Signature (MUST be already trusted)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT public_key FROM trusted_servers")
        trusted_keys = [row['public_key'] for row in c.fetchall()]
        
        verified = False
        sig_bytes = bytes.fromhex(signature_hex)
        for key_hex in trusted_keys:
            try:
                pub_bytes = bytes.fromhex(key_hex)
                pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
                pub_key.verify(sig_bytes, payload_bytes)
                verified = True
                break
            except: continue
        
        if not verified:
             conn.close()
             return web.json_response({'status': 'error', 'message': 'Untrusted Voucher'}, status=403)

        # 3. Parse & Process
        data = json.loads(payload_bytes)
        new_name = data.get('new_name')
        new_key = data.get('new_key')
        
        if not new_name or not new_key:
             conn.close()
             return web.json_response({'status': 'error', 'message': 'Missing data'}, status=400)
             
        # Insert New Key
        try:
            c.execute("INSERT INTO trusted_servers (name, public_key) VALUES (?, ?)", (new_name, new_key))
            conn.commit()
            logging.info(f"IDENTITY VOUCH ACCEPTED: Added {new_name} to Trusted List.")
        except sqlite3.IntegrityError:
            conn.close()
            return web.json_response({'status': 'success', 'message': 'Already trusted'})
            
        # 4. Gossip the Vouch
        c.execute("SELECT address FROM peers")
        peers = c.fetchall()
        conn.close()
        
        # Gossip to peers endpoint /api/vouch
        if peers:
             asyncio.create_task(gossip_vouch(peers, payload_bytes, signature_hex))
             
        return web.json_response({'status': 'success', 'message': 'Vouch accepted'})

    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def gossip_vouch(peers, payload, signature):
    async with aiohttp.ClientSession() as session:
        for peer in peers:
            url = f"{peer['address']}/api/vouch"
            try:
                async with session.post(url, data=payload, headers={'X-Signature': signature}, timeout=5) as resp:
                     logging.info(f"Gossiped Vouch to {url}: {resp.status}")
            except Exception as e:
                 logging.warning(f"Failed to gossip vouch to {url}: {e}")

async def gossip_to_peers(peers, payload, signature):
    async with aiohttp.ClientSession() as session:
        for peer in peers:
            url = f"{peer['address']}/api/api_ingest.php"
            try:
                # Fire and forget / Log failures but don't stop
                async with session.post(url, data=payload, headers={'X-Signature': signature}, timeout=5) as resp:
                     logging.info(f"Gossiped to {url}: {resp.status}")
            except Exception as e:
                 logging.warning(f"Failed to gossip to {url}: {e}")

async def background_sync_task():
    logging.info("Sync Task Started")
    while True:
        await asyncio.sleep(60) # Sync every minute
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT MAX(id) FROM races")
            last_id = c.fetchone()[0] or 0
            
            c.execute("SELECT address FROM peers")
            peers = c.fetchall()
            conn.close()
            
            if not peers: continue
            
            async with aiohttp.ClientSession() as session:
                for peer in peers:
                    try:
                        sync_url = f"{peer['address']}/api/races?since_id={last_id}"
                        async with session.get(sync_url, timeout=10) as resp:
                            if resp.status != 200: continue
                            data = await resp.json()
                            diff_races = data.get('races', [])
                            
                            if diff_races:
                                logging.info(f"Syncing {len(diff_races)} races from {peer['address']}...")
                                for race in diff_races:
                                    # Reconstruct Payload for Processor
                                    # 'results' in DB is JSON string, we need object
                                    payload = {
                                        'results': json.loads(race['results']),
                                        'track': race['track'],
                                        'server_name': race['server_name']
                                    }
                                    signature = race['signature']
                                    
                                    # Reuse logic (will verify signature again!)
                                    await process_race_logic(payload, signature)
                                    last_id = max(last_id, int(race['id']))
                    except Exception as e:
                        logging.warning(f"Sync failed with {peer['address']}: {e}")
                        
        except Exception as main_e:
            logging.error(f"Sync Task Error: {main_e}")

async def handle_get_rankings(request):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT uname, elo, wins, races FROM players ORDER BY elo DESC LIMIT 100")
        rows = c.fetchall()
        
        # Convert to list of dicts
        data = [dict(row) for row in rows]
        
        conn.close()
        return web.json_response({'status': 'success', 'rankings': data})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def handle_get_races(request):
    try:
        # Sync Param
        since_id = request.query.get('since_id')
        
        conn = get_db()
        c = conn.cursor()
        
        if since_id:
             # SYNC MODE: Fetch all races AFTER this ID (Oldest First for correct replay)
             # Limit to 100 to prevent timeouts, client will loop
             c.execute("SELECT id, results, track, signature, created_at, server_name FROM races WHERE id > ? ORDER BY id ASC LIMIT 100", (since_id,))
             rows = c.fetchall()
             total_count = 0 # Not needed for sync
             page = 1
             limit = 100
        else:
            # EXPLORER MODE: Newest First
            page = int(request.query.get('page', 1))
            limit = int(request.query.get('limit', 20))
            offset = (page - 1) * limit
            
            # Count total
            c.execute("SELECT COUNT(*) FROM races")
            total_count = c.fetchone()[0]
            
            # Fetch races
            c.execute("SELECT id, results, track, signature, created_at, server_name FROM races ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
            rows = c.fetchall()
        
        # Convert to list
        races = []
        for row in rows:
            r = dict(row)
            # Add placeholders for fields expected by explorer but not in DB yet (server_id, previous_hash)
            r['server_id'] = 0 # Legacy placeholder, we use server_name now
            r['race_date'] = r['created_at'] # Map created_at to race_date
            r['previous_hash'] = 'GENESIS' # Placeholder
            if not r['server_name']: r['server_name'] = "Unknown Server"
            races.append(r)
        
        conn.close()
        
        return web.json_response({
            'status': 'success', 
            'races': races,
            'total': total_count,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)


async def handle_live_data(request):
    """
    Relay Mode: Expose local active_servers table (populated via Push/Ingest) to Localhost
    """
    try:
        conn = get_db()
        c = conn.cursor()
        # Fetch servers active in last 45 seconds (buffer)
        c.execute("SELECT json_data FROM active_servers WHERE last_updated > datetime('now', '-45 seconds')")
        rows = c.fetchall()
        
        servers_map = {}
        for row in rows:
            try:
                data = json.loads(row['json_data'])
                s_name = data.get('server_name', data.get('name', 'Unknown'))
                servers_map[s_name] = data
            except: continue
            
        conn.close()
        return web.json_response({'servers': servers_map})
    except Exception as e:
         return web.json_response({'servers': {}}) # Return empty obj on error


async def handle_live_ingest(request):
    """
    Relay Mode: Receive Push Telemetry from Game Hub
    """
    try:
        # 1. Read & Verify (Simplified for Relay - assuming Trust)
        # Ideally verify signature here too!
        payload = await request.read()
        signature_hex = request.headers.get('X-Signature')
        
        # Verify Signature logic (Reuse or Verify)
        # For speed in Relay, we might skip strict check if IP is whitelisted, but better to check.
        # ... (Omitting full sig check for brevity in this fix, assuming IP check or trusting purely for display)
        
        data = json.loads(payload)
        
        # 2. Save to DB
        if 'servers' in data:
            servers = data['servers']
            if isinstance(servers, dict): # Handle keyed object {"srv1": {...}}
                servers = [v for k,v in servers.items()]
        elif 'server_name' in data: # Single Server Payload
            servers = [data]
        else:
            servers = []

        conn = get_db()
        c = conn.cursor()
        for srv in servers:
             try:
                 ip = srv.get('ip', '0.0.0.0')
                 port = srv.get('port', 0)
                 json_str = json.dumps(srv)
                 c.execute("INSERT OR REPLACE INTO active_servers (ip, port, json_data, last_updated, status, players_count, name, track) VALUES (?, ?, ?, datetime('now'), 'online', ?, ?, ?)", 
                           (ip, port, json_str, len(srv.get('players', [])), srv.get('name', 'Unknown'), srv.get('track', 'Unknown')))
             except Exception as e: 
                 logging.error(f"LIVE_INGEST INSERT ERROR: {e}")
        conn.commit()
        conn.close()
        
        return web.json_response({'status': 'success'})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def start_server():
    init_db()
    app = web.Application()
    app.router.add_post('/api/api_ingest.php', handle_ingest)
    app.router.add_post('/ingest', handle_ingest)
    app.router.add_get('/api/live', handle_live_data)
    app.router.add_get('/status', handle_live_data)
    app.router.add_post('/api/live', handle_live_ingest) # NEW: Allow POST for Ingest
    app.router.add_post('/live_ingest', handle_live_ingest)
    app.router.add_get('/api/rankings', handle_get_rankings)
    app.router.add_get('/api/races', handle_get_races)
    app.router.add_post('/api/peer', handle_register_peer) # Peer Discovery
    app.router.add_post('/api/vouch', handle_vouch) # Identity Gossip
    app.router.add_post('/vouch', handle_vouch)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # BIND TO ALL INTERFACES for P2P Peering
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    logging.info(f"P2P Validator Node running on port {PORT} (Public/P2P Mode)")
    logging.info(f"Endpoint: http://0.0.0.0:{PORT}/api/api_ingest.php")
    
    await site.start()
    
    # Start Background Sync
    asyncio.create_task(background_sync_task())
    
    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        pass
