import threading
import argparse
from cachetools import TTLCache

# Global Configuration and State
ARGS = argparse.Namespace(
    api_key='', 
    api_url='http://127.0.0.1:8080/api', 
    admin_pass='', 
    host='127.0.0.1', 
    port=29999,
    game_port=63392
)

class GlobalState:
    def __init__(self):
        self.lock = threading.RLock() # Reentrant lock matching system.py usage
        self.insim_sock = None
        self.running = True
        self.connections = {} # Key: UCID, Val: {uname, pname, admin}
        
        # State Data
        self.current_race = {
            'status': 'idle',
            'track': 'BL1', 
            'weather': 0, 
            'wind': 0,
            'laps': 0,
            'players': {}, # Key: UCID, Val: {plid, uname, car, etc}
            'results': [],
            'qual_results': [],
            'started_players': {}, # Snapshot for DNF
            'race_token': 0,
            'num_players_at_start': 0
        }
        self.current_track = "BL1"
        self.current_weather = 0
        self.current_wind = 0
        self.current_allowed_cars = 0 # 0=All
        self.previous_track = None
        self.previous_allowed_cars = None
        self.consecutive_races = 0
        
        # Caches
        self.api_cache = TTLCache(maxsize=100, ttl=60)
        self.player_cache = TTLCache(maxsize=1000, ttl=300)
        self.preloaded_rankings = []
        
        # Config
        self.config = {
            'voting': True,
            'stats': True,
            'help': True,
            'welcome_msg': True,
            'teams': True,
            'enable_mods': True,
            'vote_ratio': 0.5,
            'vote_duration': 60.0,
            'server_name': "LFS Server"
        }
        self.mods = [] # List of available mods
        self.mod_map = {} # ID -> Name
        
        # Voting / UI State
        self.active_vote = None
        self.voting_active = False
        self.voting_timer = None
        
        self.page_state = {} # Per UCID paging state
        self.menu_buttons = {} # Per UCID button IDs
        self.close_buttons = {} # Per UCID close btn IDs
        self.active_buttons = {} # Per UCID set of active ClickIDs for Smart Clear

        # Timers
        self.qual_timer = None
        self.qual_finishing_players = set()
        self.practice_timer = None
        
        self.silent_mode = False
        self.server_name = "LFS Server"

STATE = GlobalState()
