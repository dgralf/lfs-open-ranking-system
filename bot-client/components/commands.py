from typing import List
import logging
from .state import STATE
from .api import fetch_api_get, send_to_api
from .insim import send_message, format_lap_time
from .tables import display_table_with_menu, get_msg

from .admin import admin_random_command

def cmd_rank(ucid: int, args: List[str]):
    if not STATE.config.get('stats', True): return
    page = 1
    if args and args[0].isdigit():
        page = int(args[0])
    
    limit = 10 
    offset = (page - 1) * limit
    
    # Use send_to_api (api_ingest.php)
    resp = send_to_api('get_rankings', {'limit': limit, 'offset': offset, 'type': 'drivers'})
    
    # Check both keys just in case
    rows = resp.get('players', []) if resp else []
    if not rows and 'rankings' in resp: rows = resp['rankings']
    
    if not rows:
        send_message(get_msg('err_no_data', ucid), ucid)
        return
    
    total_count = int(resp.get('count', 100))
    import math
    total_pages = math.ceil(total_count / limit)

    headers = ["^7#", "^7Pilot", "^7ELO", "^7Wins"]
    
    # Format rows with colors
    table_data = []
    
    # Determine global rank start? (Offset + 1)
    # The API might send 'global_rank'
    start_rank = offset + 1
    
    for i, r in enumerate(rows):
        rank = r.get('global_rank', start_rank + i)
        table_data.append([
            f"^7{rank}", 
            f"^3{r['uname']}", 
            f"^2{r.get('elo', 1500)}", 
            f"^7{r.get('wins', 0)}"
        ])
        
    logging.info(f"Show Rank Table: {len(table_data)} rows. Calls display_table_with_menu.")
    display_table_with_menu(ucid, "Ranking Global", headers, table_data, "!rank", page, total_pages)

def cmd_top(ucid: int):
    if not STATE.config.get('stats', True): return
    # Contextual Top (Current Track/Car)
    player = STATE.current_race['players'].get(ucid)
    if not player or not player.get('car'):
        send_message("^1Must be on track to see track records for your car.", ucid)
        return

    track = STATE.current_track
    car = player['car']
    
    if car == "UNK":
         send_message("^1Car not recognized.", ucid)
         return
    
    resp = send_to_api('get_top_times', {'track': track, 'car': car})
    rows = resp.get('times', []) if resp else []
    
    if not rows:
         send_message(f"^1No records found for {track}/{car}.", ucid)
         return

    logging.info(f"cmd_top: rows={len(rows)}")
    headers = ["^7#", "^7Pilot", "^7Time"]
    data = [[f"^7{i+1}", f"^3{r['uname']}", f"^2{format_lap_time(r['lap_time'])}"] for i, r in enumerate(rows)]
    display_table_with_menu(ucid, f"Top {track}/{car}", headers, data, "!top")

def cmd_topcars(ucid: int, args: list):
    # Alias to top for now, or could handle 'car' argument
    if not STATE.config.get('stats', True): return
    
    # If args provided (e.g. !topcars XFG), use that car
    target_car = None
    if args:
        target_car = args[0].upper()
        
    if target_car:
        track = STATE.current_track
        resp = send_to_api('get_top_times', {'track': track, 'car': target_car})
        rows = resp.get('times', []) if resp else []
        if not rows:
             send_message(f"^1No records for {track}/{target_car}", ucid)
             return
        
        headers = ["^7#", "^7Pilot", "^7Time"]
        data = [[f"^7{i+1}", f"^3{r['uname']}", f"^2{format_lap_time(r['lap_time'])}"] for i, r in enumerate(rows)]
        display_table_with_menu(ucid, f"Top {track}/{target_car}", headers, data, "!topcars")
    else:
        # Default to current car
        cmd_top(ucid)

def cmd_help(ucid: int, args: list):
    if not STATE.config.get('enable_help', True): return
    headers = ["Command", "Description"]
    
    # Define capabilities
    caps = [
        ["!rank", "Driver Ranking (ELO)"],
        ["!top", "Top 10 Times (Current Car)"],
        ["!topcars [car]", "Top 10 Times (Specific Car)"],
        ["!vote", "Vote next combo"],
        ["!register", "Get Web Password"],
        ["!help", "Available Commands"],
        ["!admin", "Admin Menu"],
        ["!badcombo", "Report Bad Combo"],
        ["!stats", "Stats Menu"],
        ["!tb", "Theoretical Best"],
        ["!sr", "System Records"],
        ["!teams", "Teams List"],
        ["!nations", "Nations Ranking"],
        ["!lang", "Change Language (es/en)"],
        ["!web", "Website Info"],
        ["!resetui", "Fix UI Glitches"],
        ["!track", "Track/Weather Info"]
    ]
    
    data = []
    for c_str, desc in caps:
        data.append([f"^2{c_str}", f"^7{desc}"])

    limit = 10
    page = 1
    if args and args[0].isdigit():
        page = int(args[0])
        
    import math
    total_items = len(data)
    total_pages = math.ceil(total_items / limit)
    
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    page_data = data[start_idx:end_idx]
    
    display_table_with_menu(ucid, "^1Available Commands", headers, page_data, "!help", page, total_pages)

# --- NEW ADMIN COMMANDS ---
def cmd_kick(ucid: int, args: list):
    """!kick <user/plid>"""
    # Check admin
    uname = state_uname(ucid)
    if not is_admin(uname, ucid): return
    
    if not args:
        send_message("^1Usage: !kick <username/plid>", ucid)
        return
        
    target = args[0]
    send_message(f"/kick {target}")

def cmd_ban(ucid: int, args: list):
    """!ban <user/plid> [days]"""
    uname = state_uname(ucid)
    if not is_admin(uname, ucid): return
    
    if not args:
        send_message("^1Usage: !ban <username/plid> [days]", ucid)
        return
        
    target = args[0]
    days = args[1] if len(args) > 1 else 0
    
    if days:
        send_message(f"/ban {target} {days}")
    else:
        send_message(f"/ban {target}")

def cmd_msg(ucid: int, args: list):
    """!msg <text> - Broadcast to all"""
    uname = state_uname(ucid)
    if not is_admin(uname, ucid): return
    
    text = " ".join(args)
    if not text: return
    
    send_message(f"^3Admin: ^7{text}")

def cmd_admin(ucid: int, args: list):
    # Import locally to avoid circular imports if any
    from .admin import admin_menu, is_admin, admin_random_command
    
    # Get uname safe
    uname = ""
    if ucid in STATE.connections:
         uname = STATE.connections[ucid].get('uname', 'Unknown')
    elif ucid in STATE.current_race['players']:
         uname = STATE.current_race['players'][ucid]['uname']

    if not args:
        # Show Admin Menu
        admin_menu(ucid, uname)
        return
        
    sub = args[0].lower()
    
    # Legacy/Shortcut handling
    if sub == 'random':
        admin_random_command(ucid, uname, args[1:])
        return
    elif sub == 'restart':
        if is_admin(uname, ucid):
             send_message("/restart")
        return
    elif sub == 'end':
        if is_admin(uname, ucid):
             send_message("/end")
        return
        
    # If generic subcommand, pass to menu handler which might handle it or ignore
    admin_menu(ucid, uname, args)

def state_uname(ucid):
    # Helper to get uname safe
    if ucid in STATE.connections:
         return STATE.connections[ucid].get('uname', 'Unknown')
    elif ucid in STATE.current_race['players']:
         return STATE.current_race['players'][ucid]['uname']
    return "Unknown"

def cmd_random(ucid: int, args: list):
    from .admin import admin_random_command
    uname = state_uname(ucid)
    admin_random_command(ucid, uname, args)
    
def handle_command(ucid: int, msg: str):
    parts = msg.split()
    if not parts: return
    cmd = parts[0].lower()
    args = parts[1:]
    
    logging.info(f"CMD RECV: {cmd} args={args} ucid={ucid}")

    # Routing
    if cmd == '!rank': cmd_rank(ucid, args)
    elif cmd == '!top': cmd_top(ucid)
    elif cmd == '!topcars': cmd_topcars(ucid, args)
    elif cmd == '!vote': cmd_vote(ucid, args)
    elif cmd == '!register': cmd_register(ucid, args)
    elif cmd == '!web' or cmd == '!website': cmd_web(ucid)
    elif cmd == '!badcombo': cmd_badcombo(ucid)
    
    # Ported commands
    elif cmd == '!topwins': cmd_topwins(ucid, args)
    elif cmd == '!sr': cmd_sr(ucid, args)
    elif cmd == '!team' or cmd == '!teams': cmd_teams(ucid, args)
    elif cmd == '!nations': cmd_nations(ucid, args)
    elif cmd == '!mypb' or cmd == '!pb': cmd_mypb(ucid, args)
    elif cmd == '!tb': cmd_tb(ucid, args)
    elif cmd == '!lang': cmd_lang(ucid, args)
    elif cmd == '!resetui': cmd_resetui(ucid)
    elif cmd == '!track': cmd_track(ucid)
    
    elif cmd == '!admin': 
         cmd_admin(ucid, args)
         
    elif cmd == '!random': 
         cmd_random(ucid, args)
         
    # New Admin Commands
    elif cmd == '!kick': cmd_kick(ucid, args)
    elif cmd == '!ban': cmd_ban(ucid, args)
    elif cmd == '!msg' or cmd == '!broadcast': cmd_msg(ucid, args)

    elif cmd == '!help': cmd_help(ucid, args)
    else:
         pass

def cmd_tb(ucid: int, args: list):
    """Theoretical Best - !tb"""
    if not STATE.config.get('stats', True): return
    uname = ""
    if ucid in STATE.current_race['players']:
         uname = STATE.current_race['players'][ucid]['uname']
    if not uname: return
    
    track = STATE.current_track
    car = STATE.current_race['players'].get(ucid, {}).get('car', 'N/A')
    
    # API for TB? Assuming 'records' with sort='splits' or similar?
    # system2.py uses specific TB calculation or storage.
    # We will query 'records' for now.
    send_message(f"^3TB Calculation ({track}/{car}) - Not fully implemented in API yet.", ucid)

def cmd_lang(ucid: int, args: list):
    """Change Language - !lang es/en"""
    if not args:
         send_message("^3Usage: ^2!lang es ^7or ^2!lang en", ucid)
         return
    
    lang = args[0].lower()
    if lang not in ['es', 'en']:
         send_message("^1Invalid language. Use es or en.", ucid)
         return
         
    # Update State (In-Memory only for now)
    # Ideally should persist to DB via API or local file?
    # For now session only.
    if ucid in STATE.current_race['players']:
         STATE.current_race['players'][ucid]['language'] = lang
    
    send_message(f"^2Language set to {lang.upper()}", ucid)

def cmd_resetui(ucid: int):
    """Force UI Reset - !resetui"""
    from .tables import clear_table
    clear_table(ucid)
    send_message("^2UI Reset performed.", ucid)

def cmd_track(ucid: int):
    """Ref: system2.py cmd_track"""
    if not STATE.config.get('enable_track', True): return
    t = STATE.current_track
    w = STATE.weather
    send_message(f"^3Pista: ^7{t} | ^3Clima: ^7{w}", ucid)


# --- Restored Commands ---


# --- Restored Commands with Feature Checks ---

def cmd_register(ucid: int, args: list):
    uname = state_uname(ucid)
    
    # Player Web Registration Logic
    if not STATE.config.get('register', True):
        send_message("^1Registration is currently disabled.", ucid)
        return
        
    if not uname: return
    
    # Server Registration Logic (Generate Token)
    if args and args[0].lower() == 'server':
        resp = send_to_api('generate_server_token', {'uname': uname})
        if resp and resp.get('status') == 'success':
            token = resp.get('token')
            send_message(f"^2Server Token Generated!", ucid)
            send_message(f"^3Token: ^7{token}", ucid)
            send_message(f"^7Put this token in your bot console when starting your new server.", ucid)
        else:
            err = resp.get('message', 'Unknown error') if resp else "Network/Timeout error"
            send_message(f"^1Token generation failed: {err}", ucid)
        return
    
    # Send to API (P2P Node generates Web login code)
    resp = send_to_api('generate_auth_code', {'uname': uname})
    
    if resp and resp.get('status') == 'success' and resp.get('code'):
        code = resp['code']
        headers = ["Type", "Information"]
        data = [
            ["^3Web Profile", f"^7Go to ^2lfsrank.com/login"],
            ["^3Login Code", f"^2{code}"],
            ["^3Nuevo Servidor", "^7Click para registrar"]
        ]
        # Map the 3rd row to "!register server"
        commands = [None, None, "!register server"]
        display_table_with_menu(ucid, "Registration Menu", headers, data, "!register", commands=commands)
    else:
        err = resp.get('message', 'Unknown') if resp else "Network Error"
        send_message(f"^1Registration failed: {err}", ucid)

def cmd_vote(ucid: int, args: list):
    if not STATE.config.get('voting', True):
        send_message("^1Voting is disabled.", ucid)
        return
        
    from .voting import start_voting, vote_option
    
    if args and args[0].isdigit():
        vote_option(ucid, int(args[0]))
    else:
        start_voting()

def cmd_web(ucid: int):
    if not STATE.config.get('enable_web', True):
         return # Silent disable
    send_message("^3Website: ^7https://lfsrank.com", ucid)

def cmd_badcombo(ucid: int):
    send_message("^3Thanks for the feedback. Admins notified.", ucid)
    
def cmd_topwins(ucid: int, args: list):
    if not STATE.config.get('stats', True): return
    resp = send_to_api('get_top_wins', {})
    if resp and resp.get('status') == 'success':
        rows = resp.get('topwins', [])
        headers = ["#", "Pilot", "Wins"]
        data = [[f"{i+1}", r['uname'], str(r['wins'])] for i, r in enumerate(rows)]
        display_table_with_menu(ucid, "Top Wins", headers, data, "!topwins")

def cmd_sr(ucid: int, args: list):
    if not STATE.config.get('stats', True): return
    track = STATE.current_track
    player = STATE.current_race['players'].get(ucid)
    car = player.get('car', 'XFG') if player else 'XFG'
    
    resp = send_to_api('get_sr', {'track': track, 'car': car})
    if resp and resp.get('status') == 'success' and resp.get('sr'):
        sr = resp['sr']
        t_str = format_lap_time(sr['lap_time'])
        send_message(f"^3System Record ({track}/{car}): ^7{sr['uname']} - ^2{t_str}", ucid)
    else:
        send_message(f"^3No System Record for {track}/{car}", ucid)

def cmd_mypb(ucid: int, args: list):
    if not STATE.config.get('enable_pb', True): return
    track = STATE.current_track
    player = STATE.current_race['players'].get(ucid)
    if not player or not player.get('uname'): return
    car = player.get('car', 'XFG')
    uname = player['uname']
    
    resp = send_to_api('get_pb', {'track': track, 'car': car, 'uname': uname})
    if resp and resp.get('status') == 'success' and resp.get('pb'):
        pb = resp['pb']
        t_str = format_lap_time(pb['lap_time'])
        send_message(f"^3Personal Best ({track}/{car}): ^2{t_str}", ucid)
    else:
        send_message(f"^3No PB found for {track}/{car}", ucid)

def cmd_teams(ucid: int, args: list):
    if not STATE.config.get('teams', True): return
    # Refactored to use send_to_api
    resp = send_to_api('get_rankings', {'type': 'teams', 'limit': 10})
    if resp and resp.get('status') == 'success':
        rows = resp.get('rankings', [])
        headers = ["#", "Team", "Wins"]
        data = [[f"{i+1}", r['name'], str(r['total_wins'])] for i, r in enumerate(rows)]
        display_table_with_menu(ucid, "Top Teams", headers, data, "!teams")

def cmd_nations(ucid: int, args: list):
    if not STATE.config.get('teams', True): return # Nations grouped with Teams toggle?
    resp = send_to_api('get_country_stats', {'limit': 10})
    if resp and resp.get('status') == 'success':
        rows = resp.get('nations', [])
        headers = ["Nation", "Players", "Avg ELO"]
        data = [[r['nation'], str(r['count']), str(int(r['avg_elo']))] for r in rows]
        display_table_with_menu(ucid, "Nations Rank", headers, data, "!nations")



def cmd_stats(ucid: int, args: list):
    if not STATE.config.get('stats', True): return
    player = STATE.current_race['players'].get(ucid)
    if not player or not player.get('uname'): return
    
    resp = send_to_api('get_player_rank', {'uname': player['uname']})
    if resp and resp.get('status') == 'success' and resp.get('rank'):
        r = resp['rank']
        msg = f"^3Stats for {player['uname']}: ^7Rank: ^3#{r['position']} ^7ELO: ^3{r['elo']} ^7Wins: ^3{r['wins']}"
        send_message(msg, ucid)
    else:
        # Fallback to local ELO
        local_elo = player.get('elo', 1500)
        send_message(f"^3Stats for {player['uname']}: ^7ELO: ^3{local_elo} ^8(API Unavailable)", ucid)
