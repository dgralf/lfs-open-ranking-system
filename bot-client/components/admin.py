import random
import time
import threading
from .state import STATE
from .insim import send_message, send_packet
from .tables import get_msg

# Constants
VALID_TRACKS = [
    "BL1", "BL1R", "BL2", "BL2R", "BL3", "BL3R",
    "SO1", "SO1R", "SO2", "SO2R", "SO3", "SO3R", "SO4", "SO4R", "SO6", "SO6R",
    "FE1", "FE2", "FE3", "FE4", "FE5", "FE5R", "FE6", "FE6R",
    "KY1", "KY1R", "KY2", "KY2R", "KY3", "KY3R", 
    "KY4", "KY4R", "KY5", "KY5R", "KY6", "KY6R", "KY7", "KY7R", "KY8", "KY8R",
    "WE1", "WE1R", "WE2", "WE2R", "WE3", "WE3R", "WE4", "WE4R", "WE5", "WE5R", "WE6", "WE6R", "WE7", "WE7R",
    "AS1", "AS1R", "AS2", "AS2R", "AS3", "AS3R", "AS4", "AS4R", "AS5", "AS5R", "AS6", "AS6R", "AS7", "AS7R", "AS8", "AS8R", "AS9", "AS9R",
    "RO1", "RO2", "RO3", "RO4", "RO5", "RO6", "RO7", "RO8", "RO9", "RO10", "RO11"
]

BALANCED_CLASSES = [
    {"name": "UF1", "cars": ["UF1"], "code": 256},
    {"name": "XFG", "cars": ["XFG"], "code": 1},
    {"name": "XRG", "cars": ["XRG"], "code": 2},
    {"name": "XFG + XRG", "cars": ["XFG", "XRG"], "code": 1+2},
    {"name": "LX4", "cars": ["LX4"], "code": 32},
    {"name": "LX6", "cars": ["LX6"], "code": 64},
    {"name": "RB4", "cars": ["RB4"], "code": 8},
    {"name": "FXO", "cars": ["FXO"], "code": 16},
    {"name": "XRT", "cars": ["XRT"], "code": 4},
    {"name": "RAC", "cars": ["RAC"], "code": 512},
    {"name": "FZ5", "cars": ["FZ5"], "code": 1024},
    {"name": "RAC + FZ5", "cars": ["RAC", "FZ5"], "code": 512+1024},
    {"name": "UFR", "cars": ["UFR"], "code": 8192},
    {"name": "XFR", "cars": ["XFR"], "code": 4096},
    {"name": "UFR + XFR", "cars": ["UFR", "XFR"], "code": 8192+4096},
    {"name": "FXR", "cars": ["FXR"], "code": 32768},
    {"name": "XRR", "cars": ["XRR"], "code": 65536},
    {"name": "FZR", "cars": ["FZR"], "code": 131072},
    {"name": "GTR Mix", "cars": ["FXR", "XRR", "FZR"], "code": 229376},
    {"name": "MRT", "cars": ["MRT"], "code": 128},
    {"name": "FBM", "cars": ["FBM"], "code": 524288},
    {"name": "FOX", "cars": ["FOX"], "code": 2048},
    {"name": "FO8", "cars": ["FO8"], "code": 16384},
    {"name": "BF1", "cars": ["BF1"], "code": 262144},
]

def is_admin(uname: str, ucid: int = -1) -> bool:
    # 1. Config list
    # 2. InSim flag
    if ucid >= 0:
        with STATE.lock:
             # Need player tracking in STATE
             pass 
    return True # Stub for tests

def generate_balanced_config(allow_mods: bool = True, allow_standard: bool = True):
    pool = []
    if allow_standard:
        pool.extend(BALANCED_CLASSES)
    
    # Mods support? STATE.mods
    if allow_mods:
        for m in STATE.mods:
             # Mod objects usually have 'name' as ID or 'code'
             pool.append({
                 "name": m.get('name', 'Unknown Mod'), 
                 "cars": [m.get('id', 'MOD')], # For /cars command if needed, or /mods
                 "code": 0,
                 "mod_id": m.get('id'),
                 "is_mod": True
             })
             
    if not pool: return None 
    
    cls = random.choice(pool)
    track = random.choice(VALID_TRACKS)
    
    return {
        "track": track,
        "cars": cls["code"],
        "car_names": cls["cars"], # List of strings
        "name": f"{track} - {cls['name']}",
        "mod_id": cls.get("mod_id"),
        "is_mod": cls.get("is_mod", False)
    }

# Additional Constants for Logic
NO_LIGHTS_CLASSES = ["MRT", "FBM", "FOX", "FO8", "BF1"]
TARMAC_ONLY_CLASSES = ["UFR", "XFR", "UFR + XFR", "FXR", "XRR", "FZR", "GTR Mix", "MRT", "FBM", "FOX", "FO8", "BF1"]

def set_random_configuration(source: str, allow_mods=True, allow_standard=True):
    # 1. Force End of current session
    send_message("/end")
    time.sleep(1.0)
    
    config = generate_balanced_config(allow_mods, allow_standard)
    if not config: 
        send_message("^1No valid configuration found (check mods/classes)")
        return
    
    # 2. Apply New Config
    # Set Allowed Cars
    if config.get('mod_id'):
        import struct
        # Disable Standard Cars: ISP_SMALL (4) SubT 8 (ALC) - 0
        send_packet(struct.pack('<BBBBI', 2, 4, 0, 8, 0))
        time.sleep(0.2)
        send_message(f"/mods={config['mod_id']}")
        send_message(f"/cars=ALL") # Allow the mod
    else:
        # Standard Cars
        send_message("/mods=NONE")
        time.sleep(0.2)
        
        # Set specific standard cars
        if config.get('car_names'):
            car_str = "+".join(config['car_names'])
            send_message(f"/cars={car_str}")
        else:
            send_message(f"/cars=ALL")

    # ALIGNMENT WITH VOTING: Wait 5s before changing track
    send_message("^3Changing track in 5 seconds...")
    time.sleep(5.0)

    # --- Logic: Determine Class & Safe Weather ---
    is_formula = False
    if any(c in config['name'] for c in NO_LIGHTS_CLASSES):
        is_formula = True

    # Randomize Wind (0: None/Low, 1: Low/High, 2: Strong)
    r_wind = random.randint(0, 2)
    
    # Randomize Weather (1: Day, 2: Sunset, 3: Night)
    allowed_weather = [1, 2]
    if not is_formula and not any(c in config.get('car_names', []) for c in NO_LIGHTS_CLASSES):
        allowed_weather.append(3)
        
    r_weather = random.choice(allowed_weather)

    # Set Track
    send_message(f"/track {config['track']}")      # Set track
    send_message(f"/weather {r_weather}")          # Set weather
    send_message(f"/wind {r_wind}")                # Set wind
    
    # WAIT FOR TRACK LOAD
    time.sleep(8.0)
    
    # --- Random Time ---
    valid_hours = list(range(0, 24))
    r_hour = random.choice(valid_hours)
    r_min = random.choice([0, 15, 30, 45])
    send_message(f"/time set {r_hour:02}:{r_min:02}")
    
    # Night logic for lights (Floodlights)
    # Simple check: Night is roughly 22:00 to 06:00, or use InSim property? 
    # For LFS defaults:
    is_night_time = (r_weather == 3) # Weather 3 is night
    # Or based on hour if weather supports dynamic time? LFS supports set time.
    # Let's rely on time check for floodlights
    
    # Default flood logic
    send_message("/flood yes") # Always enable floods if needed, no harm in day? 
    # Actually /flood yes only works if there are lights.
    
    # Report Config
    wind_desc = ["Low", "High", "Strong"][r_wind]
    weather_desc = {1: "Day", 2: "Sunset", 3: "Night"}.get(r_weather, "Custom")
    
    msg = f"^3Random Config: ^7{config['name']} ^3@ ^7{config['track']} (Time {r_hour:02}:{r_min:02}, Wind {wind_desc})"
    send_message(msg)

    time.sleep(1.0)
    send_message("/restart")
    send_message(f"^2Random Config Applied: {config['name']}")

from .tables import display_table_with_menu, get_msg

def admin_menu(ucid: int, uname: str, args: list = []):
    if not is_admin(uname, ucid):
         send_message("^1Admin only", ucid)
         return

    # --- ACTION HANDLER ---
    if args:
        sub = args[0].lower()
        
        # Generic Toggle Handler
        if sub.startswith('toggle_'):
            key = sub.replace('toggle_', '')
            # Mapping for shortcut keys if any
            key_map = {
                'mods': 'enable_mods',
                'pb': 'enable_pb',
                'track': 'enable_track', 
                'web': 'enable_web',
                'help': 'enable_help',
                'admin': 'enable_admin'
            }
            real_key = key_map.get(key, key)
            
            with STATE.lock:
                curr = STATE.config.get(real_key, True) # Default to True usually
                STATE.config[real_key] = not curr
                new_val = STATE.config[real_key]
                STATUS_COLOR = "^2ON" if new_val else "^1OFF"
                send_message(f"^3System: ^7{real_key} set to {STATUS_COLOR}", ucid)
                
            # Quick Refresh
            admin_menu(ucid, uname)
            return

        # Legacy/Specific Commands
        if sub == 'random':
             threading.Thread(target=lambda: set_random_configuration("admin", True, True), daemon=True).start()
             return
        elif sub == 'force_vote':
             from .voting import start_voting, generate_voting_options
             with STATE.lock: STATE.current_voting_options = generate_voting_options()
             start_voting()
             return
        elif sub == 'abort_vote':
             from .voting import end_voting_early
             end_voting_early()
             return
        elif sub == 'reset_cars':
             send_message(f"/mods=NONE"); send_message(f"/cars=ALL"); send_message("^3Cars Reset.")
             return
        elif sub == 'restart':
             send_message("/restart")
             return
        elif sub == 'end':
             send_message("/end")
             return

    # --- MENU RENDERER ---
    # Structure definition matching user request
    # (Category, [ (Label, ConfigKey, Command/ToggleKey) ])
    menu_def = [
        ("General", [
            ("Enable Admin (!admin)", "enable_admin", "toggle_admin"),
            ("Enable Help (!help)", "enable_help", "toggle_help"),
        ]),
        ("Features", [
            ("Enable Voting (!vote)", "voting", "toggle_voting"),
            ("Enable Stats (!stats)", "stats", "toggle_stats"),
            ("Enable Teams (!teams)", "teams", "toggle_teams"),
            ("Enable Register (!register)", "register", "toggle_register"),
            ("Enable Mods List (!mods)", "enable_mods", "toggle_mods"),
            ("Enable PB (!pb)", "enable_pb", "toggle_pb"),
            ("Enable Track Info (!track)", "enable_track", "toggle_track"),
            ("Enable Website (!web)", "enable_web", "toggle_web"),
            ("Auto Random Config", "auto_random", "toggle_auto_random"),
        ]),
        ("Social", [
            ("Welcome Messages", "welcome_msg", "toggle_welcome_msg"),
        ]),
        ("Actions", [
            ("Force Vote", "", "force_vote"),
            ("Abort Vote", "", "abort_vote"),
            ("Random (Mix)", "", "random"),
            ("Reset Cars", "", "reset_cars"),
            ("Restart Race", "", "restart"),
             # "End Race", "", "end" # Maybe too dangerous to have easily clicked?
        ])
    ]

    headers = ["Feature", "Status", "Action"]
    data = []
    cmds = []
    
    with STATE.lock:
        cfg = STATE.config
        
        for cat, items in menu_def:
            # Header Row
            data.append([f"^1{cat}", "", ""]) # Category Header
            cmds.append("") # No action
            
            for label, key, cmd in items:
                # Value & Button Text
                status = ""
                btn = ""
                
                if key: # It's a toggle
                    val = cfg.get(key, True) # Default True
                    status = "^2ON" if val else "^1OFF"
                    btn = "^3Toggle"
                else: # It's an action
                    status = "-"
                    btn = "^7Run"
                    if "Restart" in label: btn = "^1Run"
                
                data.append([f"^7{label}", status, btn])
                cmds.append(cmd)
            
            # Add spacer
            # data.append(["", "", ""]); cmds.append("")

    display_table_with_menu(ucid, "^1Admin Control Panel", headers, data, "!admin", 1, 100, commands=cmds)

def admin_random_command(ucid: int, uname: str, args: list = []):
     # Legacy Wrapper / Alias
     admin_menu(ucid, uname, ['random'] + args)

