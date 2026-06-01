import time
import json
import logging
from datetime import datetime
from .state import STATE
from .api import fetch_api_get
from .insim import send_message, format_lap_time

def sync_server_config():
    try:
        from .state import ARGS
        from .api import send_to_api
        
        logging.info("Sync: Starting Server Config Sync...")
        players = []
        track = "UNK"
        with STATE.lock:
             for p in STATE.current_race['players'].values():
                 players.append({
                     'uname': p['uname'], 
                     'nick': p.get('nick', ''),
                     'car': p.get('car', 'UNK'),
                     'plid': p.get('plid', 0),
                     'last_lap': format_lap_time(p.get('last_lap', 0)) if p.get('last_lap', 0) > 0 else '0.000',
                     'laps': p.get('laps', 0)
                 })
             track = STATE.current_track
             
        # payload
        payload = {
            'data': {
                'ip': ARGS.host,
                'port': ARGS.game_port, 
                'track': track,
                'name': STATE.server_name, 
                'players': players
            }
        }
        
        logging.info(f"Sync: Sending Payload (Track={track}, Players={len(players)})")
        resp = send_to_api('update_server_status', payload)
        
        if resp and resp.get('status') == 'success':
            logging.info("Sync: API reported Success")
            cfg = resp.get('config')
            if cfg and isinstance(cfg, dict):
                with STATE.lock:
                    updated_keys = []
                    for k, v in cfg.items():
                         # Type conversion if needed? JSON is usually strings/bools/ints
                         # Our config uses 1/0 or True/False.
                         # If API sends "1", Python might take it as string "1" (Truth-y).
                         # Safe to just assign.
                         if STATE.config.get(k) != v:
                             STATE.config[k] = v
                             updated_keys.append(k)
                    
                    if updated_keys:
                        logging.info(f"Config Synced: {updated_keys}")
        else:
             logging.warning(f"Sync: API Failed or Invalid Response: {resp}")
                        
    except Exception as e:
        logging.error(f"Sync Config Error: {e}")

def scheduler_loop():
    logging.info("Scheduler Thread Started")
    last_sync = 0
    
    while STATE.running:
        try:
            time.sleep(1)
            now = time.time()
            
            # Helper to execute commands
            def exec_cmd(cmd_data):
                from .commands import handle_command, cmd_admin
                from .insim import send_message
                
                cmd = cmd_data['command']
                args_str = cmd_data.get('args', '')
                args = args_str.split() if args_str else []
                
                logging.info(f"Executing Remote Command: {cmd} {args}")
                
                # Special cases
                if cmd == 'msg':
                    send_message(f"^3Admin: ^7{args_str}")
                elif cmd == 'kick':
                    if args:
                        send_message(f"/kick {args[0]}")
                elif cmd == 'ban':
                    if len(args) >= 2:
                        send_message(f"/ban {args[0]} {args[1]}") # user days
                    elif args:
                        send_message(f"/ban {args[0]}")
                elif cmd == 'restart':
                    send_message("/restart")
                elif cmd == 'next': # next track/end
                    send_message("/end")
                else:
                    # Generic fallback
                    send_message(f"/{cmd} {args_str}")

            # Polling (Every 5s)
            if now - last_sync > 5:
                # 1. Sync Config & Fetch Commands
                sync_server_config() # Modified to use server_poll?
                # Actually, let's keep sync_server_config separate or merge?
                # The plan said "handle_server_poll: New endpoint... fetch pending commands and sync config in one go"
                # But p2p_node.py implementation of handle_server_poll ONLY returns commands.
                # So we keep sync_server_config for config, and add command polling.
                
                # Command Polling
                from .state import ARGS
                from .api import send_to_api
                
                # Server ID? Using '0' or HOST/PORT to identify?
                # API typically needs a fixed ID from env.
                # Let's assume passed in env or config.
                server_id = STATE.config.get('server_id', 1) # Default 1 for now
                
                resp = send_to_api('server_poll', {'server_id': server_id})
                if resp and resp.get('status') == 'success':
                    cmds = resp.get('commands', [])
                    for c in cmds:
                        exec_cmd(c)
                
                last_sync = now
            
        except Exception as e:
            logging.error(f"Scheduler Error: {e}")
            time.sleep(5)

