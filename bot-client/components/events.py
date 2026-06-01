import logging
import time
import struct
from .state import STATE
from .api import send_to_api
from .insim import clean_string, send_message, format_lap_time, ISP_NPL, ISP_TINY, ISP_STA
from .elo import calculate_elo

def on_state(packet: bytes):
    if len(packet) < 28: return
    try:
        # Offset 20: Track (6 bytes) - Fixed from 24 (InSim docs: STA Size 28. Track starts at 20)
        track = clean_string(packet[20:26])
        with STATE.lock:
             if track and track != STATE.current_track:
                  STATE.current_track = track
                  logging.info(f"STA: Track Updated to {track}")
    except Exception as e:
        logging.error(f"STA Error: {e}")

def on_race_start(packet: bytes):
    if len(packet) < 28: return
    # ISP_RST
    try:
        # byte 4: Zero? No, RST structure:
        # 0: Size
        # 1: Type
        # 2: ReqI
        # 3: Zero
        # 4: RaceLaps (byte)
        # 5: QualMins (byte)
        # 6: NumP (byte)
        # 7: Timing (byte)
        # 8: Track (6 chars)
        
        laps, qual, nump = struct.unpack('BBB', packet[4:7])
        track = clean_string(packet[8:14])
        
        with STATE.lock:
            STATE.current_track = track
            STATE.current_race['track'] = track
            STATE.current_race['laps'] = laps
            STATE.current_race['num_players_at_start'] = nump
            STATE.current_race['results'] = []
            STATE.current_race['restarting'] = False # Reset flag
            STATE.current_race['race_token'] = STATE.current_race.get('race_token', 0) + 1 # New Race ID
            
        if qual > 0:
            STATE.current_race['status'] = 'qualifying'
            msg_key = "Qualifying"
        else:
            STATE.current_race['status'] = 'racing'
            msg_key = "Race"

        # Car Info Logic
        cars = set()
        logging.info(f"DEBUG: Active Players in STATE: {list(STATE.current_race['players'].keys())}")
        for ucid, p in STATE.current_race['players'].items():
            c = p.get('car')
            logging.info(f"DEBUG: P Check UCID {ucid}: data={p}")
            # Filter out known garbage
            c = p.get('car')
            # Filter out known garbage
            if c and isinstance(c, str) and len(c) >= 3:
                # remove color codes if any
                clean_c = clean_string(c)
                
                # DEBUG TRACE
                is_valid = clean_c not in ['UNK', '000000', '000', ''] and not clean_c.startswith('0')
                if not is_valid and c.isalnum() and len(c) == 3:
                     # Fallback for plain cars like "FOX" if clean_string killed it
                     clean_c = c
                     is_valid = True
                
                logging.info(f"DEBUG CAR: Raw='{c}' Clean='{clean_c}' Valid={is_valid}")
                
                if is_valid:
                     cars.add(clean_c)
        
        car_str = "/".join(sorted(cars)) if cars else "Active Cars"
        
        # Format message matching system2 style
        if qual > 0:
             # Qual Message: Track (Cars) Mins
             # "Clasificación: KY2 (XFG) 10 min."
             msg = f"^3Qualifying: ^7{track} ({car_str}) ^3{qual} min."
        else:
             # Race Message: Track (Cars) Laps
             # "Carrera: KY2 (XFG) 5 vueltas"
             msg = f"^7Race: ^3{track} ^7({car_str}) ^3{laps} laps"

        logging.info(f"RACE START ({msg_key}): {track} ({laps if qual==0 else qual} {'laps' if qual==0 else 'mins'}) Cars: {car_str}")
        send_message(msg)
        
    except Exception as e:
        logging.error(f"RST Error: {e}")

import threading

def force_race_end_countdown(wait_sec: int, token: int):
    time.sleep(wait_sec)
    # Check if race still running?
    with STATE.lock:
        if STATE.current_race.get('race_token', 0) != token:
             logging.info(f"Timer Ignored: Token Expect={STATE.current_race.get('race_token')} Got={token}")
             return
        if STATE.current_race.get('restarting'): return
        if STATE.current_race['status'] != 'racing': return
        STATE.current_race['restarting'] = True

    logging.info("Time Limit Reached. Forcing Restart.")
    
    # Send Results & Get ELO Updates from API
    resp = send_final_results()
    
    # --- ELO Broadcast (From API) ---
    if resp and 'updates' in resp:
        updates = resp['updates']
        # Map updates by uname for easy lookup
        updates_map = {u['uname']: u for u in updates}
        
        send_message("^3=== Race Results & ELO ===^8")
        
        # Display in order of race finish
        with STATE.lock:
            for r in STATE.current_race['results']:
                 uname = r['uname']
                 pos = r['position']
                 
                 if uname in updates_map:
                     upd = updates_map[uname]
                     new_elo = upd['new_elo'] # Category ELO
                     change = upd['change']
                     cat = upd.get('category', 'UNK')
                     
                     # Colorize Change
                     c_color = "^2+" if change >= 0 else "^1"
                     # Format: #1 Player (TBO): 1500 +10
                     msg = f"^7#{pos} {uname} ^8({cat}): ^3{new_elo} {c_color}{change:+d}"
                     send_message(msg)
    else:
        logging.warning("No ELO updates received from API.")

    # send_final_results() # Already called above
    
    # --- Rotation Logic ---
    with STATE.lock:
        STATE.consecutive_races += 1
        
    logging.info(f"Race Finished. Consecutive: {STATE.consecutive_races}/5")
    
    if STATE.consecutive_races >= 5:
        # Start Voting
        logging.info("Starting Voting Sequence...")
        from .voting import start_voting
        # Give LFS a moment to show results, then show voting
        time.sleep(5.0)
        start_voting()
    else:
        # Restart (Same Combo)
        send_message("^1Time Limit Reached! Restarting...")
        from .insim import send_packet
        send_message("/restart")
        
        remaining = 5 - STATE.consecutive_races
        send_message(f"^3Rotation: ^7Next Race ({STATE.consecutive_races + 1}/5). ^3{remaining} ^7left until vote.")

def on_result(packet: bytes):
    # ISP_RES
    if len(packet) < 84: return
    
    try:
        plid = packet[3] # PLID of player
        uname = clean_string(packet[4:28])
        pname = clean_string(packet[28:52])
        t_time = struct.unpack('<I', packet[68:72])[0] # Total Time
        b_lap = struct.unpack('<I', packet[72:76])[0]  # Best Lap
        
        # FILTER INVALID LAP TIMES (LFS Error Code 131072)
        if b_lap == 131072: b_lap = 0
        if t_time == 131072: t_time = 0 # Just in case

        # Determine Position
        pos = len(STATE.current_race['results']) + 1
        
        t_str = format_lap_time(t_time)
        
        is_qual = (STATE.current_race.get('status') == 'qualifying')
        
        # 1. Broadcast Result
        if is_qual:
             # Qual Result
             msg = f"^7Qual: {uname} ^3#{pos}^7 Time: ^2{t_str}"
             send_message(msg)
        else:
             # Race Result
             msg = f"^7{uname} finished ^3#{pos}^7. Time: ^2{t_str}"
             send_message(msg)
        
        # 2. Winner Logic (110% Timer) - RACE ONLY
        if pos == 1 and not is_qual:
             # Broadcast Victory
             send_message(f"^1VICTORY! ^7{uname} wins the race!")
             
             # Calculate 110% Wait
             wait_ms = t_time * 0.10
             wait_sec = max(30, int(wait_ms / 1000)) # Min 30s
             
             # Start Timer
             token = STATE.current_race.get('race_token', 0)
             threading.Thread(target=force_race_end_countdown, args=(wait_sec, token), daemon=True).start()
             
             send_message(f"^3Time Limit (110%): +{wait_sec}s")
             
        # 3. ELO Calculation
        # Check if ucid in players
        target_ucid = -1
        for u, p in STATE.current_race['players'].items():
             if p['uname'] == uname:
                  target_ucid = u
                  break
        
        old_elo = 1500
        if target_ucid != -1:
             old_elo = STATE.current_race['players'][target_ucid].get('elo', 1500)

        # 4. Save to API & State
        res_entry = {
            'uname': uname,
            'pname': pname,
            'total_time': t_time,
            'best_lap': b_lap,
            'position': pos,
            'track': STATE.current_track,
            'car': STATE.current_race['players'].get(target_ucid, {}).get('car', 'UNK'),
            'elo': old_elo # REQUIRED for ELO Calc
        }
        logging.info(f"Result Build: Uname={uname} ELO={old_elo}")
        STATE.current_race['results'].append(res_entry)
        
        # Check if ALL players have finished
        # Count started vs finished
        finished_count = len(STATE.current_race['results'])
        started_count = STATE.current_race.get('num_players_at_start', 999) # Default high to avoid premature end
        
        # RACE ONLY END LOGIC
        if not is_qual and finished_count >= started_count and started_count > 0:
             logging.info("All players finished. Ending race immediately.")
             token = STATE.current_race.get('race_token', 0)
             threading.Thread(target=force_race_end_countdown, args=(5, token), daemon=True).start() # 5s delay

    except Exception as e:
        logging.error(f"RES Error: {e}")

def send_final_results():
    with STATE.lock:
        results = STATE.current_race.get('results', [])
        track = STATE.current_race.get('track', 'UNK')
        
    if not results: return
    
    payload = {
        'track': track,
        'results': results,
        'server_name': STATE.config.get('server_name', 'LFS Server')
    }
    
    logging.info(f"Sending Batch Results to API: {len(results)} entries.")
    if results:
         logging.debug(f"Sample Payload Entry: {results[0]}")
    return send_to_api('process_race_results', payload)

def on_new_connection(packet: bytes):
    # ISP_NCN
    # Capture UName (License)
    if len(packet) < 56: return
    try:
        ucid = packet[3] # Correct Offset
        uname = clean_string(packet[4:28]) # 24 chars UName
        pname = clean_string(packet[28:52]) # 24 chars PName
        admin = packet[52]
        
        with STATE.lock:
            STATE.connections[ucid] = {
                'uname': uname, # LFS License
                'pname': pname, # Nickname
                'admin': admin,
                'elo': 1500 # Default
            }
            
        logging.info(f"NCN: UCID={ucid} License={uname} Nick={pname}")
        
        # Async Fetch ELO
        def fetch_elo(u_name, u_cid):
             resp = send_to_api('get_player_elo', {'uname': u_name})
             if resp and resp.get('status') == 'success':
                  elo = resp.get('elo', 1500)
                  with STATE.lock:
                       if u_cid in STATE.connections:
                            STATE.connections[u_cid]['elo'] = elo
                            logging.info(f"ELO Updated for UCID {u_cid} ({u_name}): {elo}")
                            
                       # Also update if already in race players (rare but possible)
                       if u_cid in STATE.current_race['players']:
                            STATE.current_race['players'][u_cid]['elo'] = elo
        
        threading.Thread(target=fetch_elo, args=(uname, ucid), daemon=True).start()
    except Exception as e:
        logging.error(f"NCN Error: {e}")

def on_new_player(packet: bytes):
    # ISP_NPL (21)
    if len(packet) < 6: return 
    
    try:
        # Proper unpacking
        # 0: Size, 1: Type, 2: ReqI, 3: PLID, 4: UCID, 5: PType, 6: Flags (2)
        # 8: PName(24), 32: Plate(8), 40: Car(4)
        
        plid = packet[3]
        ucid = packet[4]
        ptype = packet[5]
        flags = struct.unpack('<H', packet[6:8])[0]
        
        pname = clean_string(packet[8:32])
        plate = clean_string(packet[32:40])
        
        # Car Parsing with Mod Support
        try:
             cname_raw = packet[40:44] 
             from .insim import expand_mod_id
             car = expand_mod_id(cname_raw)
        except Exception as e:
             logging.error(f"NPL Car Parse Error: {e}")
             car = "UNK"
        
        with STATE.lock:
            # Ensure player exists in structure
            if ucid not in STATE.current_race['players']:
                STATE.current_race['players'][ucid] = {}
            
            # Retrieve License & ELO from Connections Cache (from NCN)
            # If NCN followed by NPL, we should have data.
            license_uname = pname # Fallback
            nick = pname # Fallback
            p_elo = 1500
            
            if ucid in STATE.connections:
                conn_data = STATE.connections[ucid]
                license_uname = conn_data.get('uname', pname)
                nick = conn_data.get('pname', pname)
                p_elo = conn_data.get('elo', 1500)
                
            STATE.current_race['players'][ucid].update({
                'plid': plid,
                'ucid': ucid,
                'uname': license_uname, # License
                'pname': pname,         # Race Name
                'nick': nick,           # Connection Nick
                'plate': plate,
                'car': car,
                'elo': p_elo,
                # Init stats if missing
                'laps': STATE.current_race['players'][ucid].get('laps', 0),
                'last_lap': STATE.current_race['players'][ucid].get('last_lap', 0)
            })
            
        logging.info(f"NPL: {pname} (UCID {ucid} PLID {plid}) Car: {car}")
        
    except Exception as e:
        logging.error(f"NPL Error: {e}")

def on_lap(packet: bytes):
    # ISP_LAP (24)
    if len(packet) < 12: return
    
    try:
        plid = packet[3]
        ltime, etime = struct.unpack('<II', packet[4:12])
        
        # Filter Invalid
        if ltime == 131072: return
            
        # Find Player
        ucid = -1
        player = None
        with STATE.lock:
            for u, p in STATE.current_race['players'].items():
                if p.get('plid') == plid:
                    ucid = u
                    player = p
                    break
        
        if not player: return
        
        uname = player['uname']
        track = STATE.current_track
        car = player.get('car', 'UNK')
        t_str = format_lap_time(ltime)
        
        logging.info(f"LAP: {uname} {track} {car} {t_str}")
        
        # Update Player State
        with STATE.lock:
            if ucid in STATE.current_race['players']:
                STATE.current_race['players'][ucid]['last_lap'] = ltime
                STATE.current_race['players'][ucid]['laps'] = STATE.current_race['players'][ucid].get('laps', 0) + 1

        # Send to API for PB check
        payload = {
            'uname': uname,
            'track': track,
            'car': car,
            'lap_time': ltime
        }
        
        def check_lap_async(p_load, p_ucid, p_uname, p_t_str, p_car):
            resp = send_to_api('process_lap', p_load)
            if resp and resp.get('status') == 'success':
                if resp.get('new_sr'):
                    send_message(f"^1New Server Record! ^7{p_uname} ^3({p_car}) ^2{p_t_str}")
                elif resp.get('new_pb'):
                    send_message(f"^2New PB! ^7{p_uname} ^3({p_car}) ^2{p_t_str}")
                
        threading.Thread(target=check_lap_async, args=(payload, ucid, uname, t_str, car), daemon=True).start()
        
    except Exception as e:
        logging.error(f"LAP Error: {e}")
