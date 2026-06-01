import random
import threading
import logging
import time
from typing import List, Dict
from .state import STATE

# Deferred imports to avoid cycles:
# from .insim import send_message, send_packet, get_msg
# from .tables import create_menu_buttons, clear_table, display_table_with_menu


# Valid Combos (Simplified for now)
TRACKS = ['BL1', 'BL2', 'SO1', 'SO2', 'FE1', 'FE2', 'FE3', 'FE4', 'AU1', 'AU2', 'KY1', 'KY2', 'WE1', 'WE2']
CARS = ['XFG', 'XRG', 'XRT', 'RB4', 'FXO', 'LX4', 'LX6', 'MRT', 'FZ5', 'FZR', 'XFR', 'UFR']

def generate_random_voting_options(num_options=5) -> List[Dict]:
    options = []
    attempts = 0
    while len(options) < num_options and attempts < 100:
        attempts += 1
        t = random.choice(TRACKS)
        c = random.choice(CARS)
        
        # Simple Logic: 50% chance of single car, 50% chance of class?
        # For now single car to match simple storage
        
        opt = {
            'track': t,
            'cars': c,
            'name': f"{t} ({c})",
            'votes': 0
        }
        
        # Avoid dupes
        if any(o['track'] == t and o['cars'] == c for o in options):
            continue
            
        options.append(opt)
    
    # Ensure Current Combo is not 1st option (Optional)
    return options

def start_voting():
    if STATE.voting_active: return

    STATE.voting_active = True
    STATE.votes = {} # ucid -> option_index
    STATE.current_voting_options = generate_random_voting_options()
    STATE.voting_end_time = time.time() + 60.0
    
    from .insim import send_message
    msg = "^3Voting Started! ^7Use buttons to vote."
    send_message(msg)
    
    # Show Table to all players
    for ucid in list(STATE.current_race['players'].keys()):
        display_voting_ui(ucid) # Wrapper or direct call
        
    # Timer
    STATE.voting_timer = threading.Timer(60.0, end_voting)
    STATE.voting_timer.start()

def end_voting():
    if not STATE.voting_active: return
    STATE.voting_active = False
    if STATE.voting_timer: STATE.voting_timer.cancel()
    
    # Tally
    counts = [0] * len(STATE.current_voting_options)
    for ucid, opt_idx in STATE.votes.items():
        if 0 <= opt_idx < len(STATE.current_voting_options):
            counts[opt_idx] += 1
            
    # Determine Winner
    # If tie? Random among winners.
    max_votes = -1
    winners = []
    
    for i, c in enumerate(counts):
        if c > max_votes:
            max_votes = c
            winners = [i]
        elif c == max_votes:
            winners.append(i)
            
    winner_idx = random.choice(winners) if winners else 0
    winner_opt = STATE.current_voting_options[winner_idx]
    
    from .insim import send_message
    msg = f"^1Vote Finished! ^7Winner: ^3{winner_opt['name']} ^7({max_votes} votes)"
    send_message(msg)
    
    # Apply Config
    apply_configuration(winner_opt)
    
    # Reset
    with STATE.lock:
        STATE.consecutive_races = 0

def apply_configuration(opt):
    # Send /track and /cars
    # InSim usually prevents /track if not Admin?
    # Provided bot has admin pass, it can send /track via MST (Message).
    # Or IS_MSO with UserType=1 (System).
    # Let's use send_message with "/track X" which InsIm supports if Admin.
    
    track = opt['track']
    cars = opt['cars']
    
    from .insim import send_message
    # Force End (per user request)
    send_message("/end")
    time.sleep(1.0)
    
    # Command: /track X
    send_message(f"/track {track}")
    
    # Wait for track change? No, it happens.
    # Cars: /cars X
    # Need to wait a bit?
    # We can send it immediately, LFS queues it.
    
    time.sleep(1.0) # Safety
    send_message(f"/cars {cars}")

def handle_vote_click(ucid, click_id):
    if not STATE.voting_active: return
    
    # Assuming ClickIDs for voting are 210, 211, 212, 213, 214...
    # Based on system2 logic
    base_id = 210
    opt_idx = click_id - base_id
    
    if 0 <= opt_idx < len(STATE.current_voting_options):
        STATE.votes[ucid] = opt_idx
        msg = f"^7You voted for: ^3{STATE.current_voting_options[opt_idx]['name']}"
        from .insim import send_message_to_user # Need this
        # send_message_to_user(ucid, msg) # Implementation needed in insim.py
        # Or just refresh UI
        display_voting_ui(ucid)

def display_voting_ui(ucid):
    # Customized table for Voting
    # Header: "VOTING - 60s"
    # Options as Buttons
    from .insim import create_button
    
    remaining = int(max(0, STATE.voting_end_time - time.time()))
    
    # Clear previous?
    # clear_table(ucid) # Maybe too aggressive if chatting?
    # Use specific range?
    
    # Header
    create_button(ucid, 209, 20, 20, 60, 5, f"^3VOTE NEXT COMBO ({remaining}s)", 80) # ISB_DARK
    
    y = 30
    base_id = 210
    
    # Counts for display
    # (Calculate on fly)
    counts = [0] * len(STATE.current_voting_options)
    for v in STATE.votes.values():
        if 0 <= v < len(counts): counts[v] += 1
        
    total_votes = len(STATE.votes)
    
    for i, opt in enumerate(STATE.current_voting_options):
        # Highlight if selected
        is_selected = (STATE.votes.get(ucid) == i)
        style = 240 if is_selected else 16 # Light/Green if selected? 
        # Standard: 16 (Light). Selected: 128 (Color)?
        # Let's use system2 styles if possible. 
        # ISB_LIGHT(16) | ISB_CLICK(8) -> 24?
        # ISB_DARK(32)?
        
        btn_style = 16 | 8 # Light + Click
        if is_selected: btn_style = 64 | 8 # Color + Click (Greenish?)
        
        # Text: "Track (Car) [X votes]"
        txt = f"{opt['name']} [{counts[i]}]"
        
        create_button(ucid, base_id + i, 20, y, 60, 5, txt, btn_style)
        y += 6

    # Close button? Not needed, it persists till end.
