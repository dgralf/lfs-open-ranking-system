#!/usr/bin/env python3
# bot/system.py - Sistema ELO para LFS - v8.0.0 FINAL GOSSIP FIX

import argparse
import sys
import hashlib
from datetime import datetime
import json
import logging
import logging.handlers
import re
import threading
import time
import os
import struct
import socket
import random
import urllib.request
import urllib.error
import mysql.connector
from collections import Counter
from cachetools import TTLCache
from typing import Dict, Any, Optional, List
import string
import math
import traceback
from cryptography.hazmat.primitives.asymmetric import ed25519

# --- NEW: show_records ---
def show_records(ucid: int, page: int = 1):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            c.execute("SELECT COUNT(*) as count FROM track_records")
            total = c.fetchone()['count']
            limit = 10
            total_pages = math.ceil(total / limit) if total > 0 else 1
            offset = (page - 1) * limit
            
            c.execute("SELECT track, car, uname, lap_time FROM track_records ORDER BY track ASC, car ASC LIMIT %s OFFSET %s", (limit, offset))
            rows = c.fetchall()
            
            if not rows and page == 1:
                return send_message(get_msg('err_no_data', ucid), ucid)
                
            headers = [get_msg('header_track', ucid), get_msg('header_car', ucid), get_msg('header_pilot', ucid), get_msg('header_time', ucid)]
            data = [[r['track'], r['car'], r['uname'], format_lap_time(r['lap_time'])] for r in rows]
            
            PAGE_STATE[ucid] = {'cmd': '!sr', 'page': page, 'total_pages': total_pages}
            display_table_with_menu(ucid, get_msg('top_wr_title', ucid), headers, data, "!sr", page, total_pages)
    finally:
        conn.close()

# --- Logging Configuration ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s')
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, 'system.log')
log_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding='utf-8')
log_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logging.basicConfig(level=logging.INFO, handlers=[log_handler, console_handler])

# --- Global Data Structure ---
class GlobalState:
    def __init__(self):
        # --- Core Race State ---
        self.current_race: Dict[str, Any] = {
            'status': 'idle', 'players': {}, 'results': [],
            'num_players_at_start': 0, 'restarting': False,
            'started_players': {}
        }
        self.current_race_id: int = 0
        self.consecutive_races: int = 0
        self.previous_track: str = ""
        self.current_track: str = ""
        
        # --- Configuration & Filters ---
        self.current_allowed_cars: int = 0
        self.previous_allowed_cars: int = 0
        self.allowed_cars_filter: Optional[int] = None 
        self.server_name: str = "lfsrank.com"
        self.config: Dict[str, bool] = { 
            'voting': True, 'stats': True, 'help': True, 'welcome_msg': True 
        }
        
        # --- Infrastructure ---
        self.player_cache: TTLCache = TTLCache(maxsize=200, ttl=600)
        self.api_cache: TTLCache = TTLCache(maxsize=50, ttl=60)
        self.preloaded_rankings: List[Dict] = []  # For local speed
        self.insim_sock: Optional[socket.socket] = None
        self.lock: threading.RLock = threading.RLock()
        self.track_change_in_progress: bool = False
        
        # --- Voting & Timers ---
        self.active_vote: Optional[Dict] = None
        self.voting_active: bool = False # Legacy flag
        self.votes: Dict[int, int] = {}
        self.current_voting_options: List[Dict] = []
        self.voting_timer: Optional[threading.Timer] = None
        self.empty_server_timer: Optional[threading.Timer] = None
        self.qual_timer: Optional[threading.Timer] = None
        self.practice_timer: Optional[threading.Timer] = None
        self.on_track_plids: set = set()
        self.qual_finishing_players: set = set()

        # --- Mods Data ---
        self.mods: List[Dict] = []
        self.mod_map: Dict[str, str] = {} 
        self.pending_mod_resolutions: set = set()

        # --- Admin & Auth ---
        admins_env = os.environ.get('LFS_ADMINS', "")
        self.admin_list: List[str] = [a.strip() for a in admins_env.split(',') if a.strip()]
        logging.info(f"DEBUG: Loaded Admin List: {self.admin_list}")
        self.admin_pass: str = "" 

        # --- Initialization ---
        # self.load_persistence() # Defer until ARGS are loaded

    def load_persistence(self):
        """Loads state from JSON files with proper error handling."""
        state_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 1. Load Current Race State
        race_file = os.path.join(state_dir, 'current_race.json')
        if os.path.exists(race_file):
            try:
                with open(race_file, 'r') as f:
                    data = json.load(f)
                    self.current_allowed_cars = data.get('allowed_cars', 0)
                    self.consecutive_races = data.get('consecutive_races', 0)
                    self.allowed_cars_filter = data.get('allowed_cars_filter', None)
                    logging.info(f"Loaded persistence state: cars={self.current_allowed_cars}, races={self.consecutive_races}")
            except Exception as e:
                logging.error(f"Failed to load current_race.json: {e}")
        else:
             logging.info("No current_race.json found, starting fresh state.")

        # 2. Load Mods
        mods_file = os.path.join(state_dir, 'mods.json')
        if os.path.exists(mods_file):
            try:
                with open(mods_file, 'r') as f:
                    self.mods = json.load(f)
                    for m in self.mods:
                        if m.get('id'):
                            self.mod_map[m['name'].upper()] = m['id']
                            self.mod_map[m['id']] = m['name'] 
                    logging.info(f"Loaded {len(self.mods)} mods from mods.json")
            except Exception as e:
                logging.error(f"Failed to load mods.json: {e}")
        
        # 3. Load Blacklist (Global Consensus via API)
        self.blacklist = set()
        
        # Helper to fetch blacklist in main thread (blocking optional or async)
        # Since this is startup/reload, blocking is fine for simple script, 
        # but to avoid issues, let's try-catch API.
        try:
             # We construct payload manually because send_to_api expects action in arg 1
             # but here we want result immediately.
             # Actually, let's just use send_to_api synchronously-ish?
             pass 
             # We will do it below
        except: pass

        # Fetch from API
        try:
            resp = send_to_api('get_bad_combos', {})
            if resp and resp.get('status') == 'success':
                 for row in resp.get('blacklist', []):
                     self.blacklist.add( (row['track'], row['car_class']) )
                 logging.info(f"Loaded {len(self.blacklist)} blacklisted configs from Global Consensus.")
            else:
                 logging.warning("Failed to load blacklist from API.")
        except Exception as e:
            logging.error(f"Error loading blacklist: {e}")


STATE = GlobalState()
ARGS = None

# --- Globals for buttons ---
CLOSE_BUTTON_REQ_I: Dict[int, int] = {}
MENU_BUTTONS_REQ_I: Dict[int, Dict[str, int]] = {}
PAGE_STATE: Dict[int, Dict[str, Any]] = {} # ucid -> {cmd, page, total_pages, args}

# --- API HELPER ---

import cryptography.hazmat.primitives.serialization as serialization

def generate_identity():
    print("Generating Ed25519 Identity...")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    
    priv_bytes = priv_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    
    identity = {
        "private_key": priv_bytes.hex(),
        "public_key": pub_bytes.hex()
    }
    with open("identity.json", "w") as f:
        json.dump(identity, f, indent=4)
    print("identity.json created successfully. Public Key:", pub_bytes.hex())
    print("Keep this file safe!")
    sys.exit(0)

def register_node(name: str):
    if not os.path.exists("identity.json"):
        print("identity.json not found. Run the bot normally first or use --generate_identity.")
        sys.exit(1)
        
    with open("identity.json", "r") as f:
        identity = json.load(f)
        
    pub_key = identity["public_key"]
    print(f"=== LFSRank Node Identity ===")
    print(f"Server Name: {name}")
    print(f"Public Key:  {pub_key}")
    print("============================")
    print("\nTo join the decentralized LFSRank network, you must send this Public Key")
    print("to a trusted network administrator to receive a 'Vouch'.")
    print("Once vouched, your race results will be accepted by the network validators.")
    sys.exit(0)

def send_to_api(action: str, payload: Dict[str, Any]):
    try:
        if not ARGS.api_key and not getattr(STATE, 'identity', None):
            logging.warning("API Key missing, skipping API call.")
            return None
            
        data = payload.copy()
        data['action'] = action
        data['api_key'] = ARGS.api_key or STATE.identity.get('public_key', '')
        
        json_data = json.dumps(data).encode('utf-8')
        pub_key = ARGS.api_key or (getattr(STATE, 'identity', None) and STATE.identity.get('public_key', ''))
        headers = {
            'Content-Type': 'application/json',
            'X-API-KEY': pub_key,
            'X-Public-Key': pub_key
        }
        
        # Signing (Ed25519)
        private_key_hex = os.environ.get('INSIM_PRIVATE_KEY')
        if not private_key_hex and getattr(STATE, 'identity', None):
            private_key_hex = STATE.identity.get('private_key', '')
            
        if private_key_hex:
            try:
                private_bytes = bytes.fromhex(private_key_hex)
                priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
                signature = priv_key.sign(json_data)
                headers['X-Signature'] = signature.hex()
            except Exception as e:
                logging.error(f"Signing Error: {e}")

        req_url = ARGS.api_url
        req = urllib.request.Request(req_url, data=json_data, headers=headers)
        
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)
    except Exception as e:
        logging.error(f"Error sending to API {action}: {e}")
        return None

def send_discord_webhook(results: List[Dict], track: str):
    url = STATE.config.get('discord_webhook')
    if not url: return

    try:
        fields = []
        for i, res in enumerate(results[:3]): # Top 3
            t_time = res.get('total_time', 0)
            time_str = format_lap_time(t_time) if t_time > 0 else "DNF"
            fields.append({
                "name": f"#{i+1} {res['uname']}",
                "value": f"Car: {res.get('car','?')}\nTime: {time_str}",
                "inline": True
            })
            
        data = {
            "embeds": [{
                "title": f"­ƒÅü Race Results: {track}",
                "color": 3066993, # Green-ish
                "fields": fields,
                "footer": {"text": f"LFS Ranking System ÔÇó {STATE.server_name}"},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }
        
        req = urllib.request.Request(url, json.dumps(data).encode('utf-8'), {
            'Content-Type': 'application/json', 
            'User-Agent': 'LFSBot/21.0'
        })
        with urllib.request.urlopen(req, timeout=5) as response:
            pass
            
    except Exception as e:
        logging.error(f"Discord Webhook Failed: {e}")

# --- STYLE CONSTANTS (LFS INSIM) ---
ISB_COLOR_LIGHT_GREY = 0 # Not user editable
ISB_COLOR_TITLE      = 1 # Yellow
ISB_COLOR_UNSELECTED = 2 # Black
ISB_COLOR_SELECTED   = 3 # White
ISB_COLOR_OK         = 4 # Green
ISB_COLOR_CANCEL     = 5 # Red
ISB_COLOR_STRING     = 6 # Pale Blue
ISB_COLOR_UNAVAILABLE= 7 # Grey

ISB_CLICK = 8
ISB_LIGHT = 16
ISB_DARK  = 32
ISB_LEFT  = 64
ISB_RIGHT = 128


def get_car_names(bitmask: int, lang: str = 'es') -> str:
    CARS = ["XFG", "XRG", "XRT", "RB4", "FXO", "LX4", "LX6", "MRT", "UF1", "RAC", "FZ5", "FOX", "XFR", "UFR", "FO8", "FXR", "XRR", "FZR", "BF1", "FBM"]
    found = []
    
    t = TRANSLATIONS.get(lang, TRANSLATIONS['es'])

    if bitmask == 0: 
        # Check if mods are active?
        if STATE.config.get('mod_id') or STATE.config.get('cars_mod_ids'):
             return "Mods/Custom"
        return t.get('car_any', "Todos / Custom")
    
    vals = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288]
    for i, v in enumerate(vals):
        if (bitmask & v):
            if i < len(CARS): found.append(CARS[i])
            
    if len(found) == len(CARS): return t.get('car_all', "Todos")
    if not found: return t.get('car_unknown', "Desconocido")
    if len(found) == len(CARS): return t.get('car_all', "Todos")
    if not found: return t.get('car_unknown', "Desconocido")
    return "/".join(found)

def expand_mod_id(cname_bytes: bytes) -> str:
    """Converts 3-byte CName to Hex Mod ID if not official."""
    if len(cname_bytes) > 3: cname_bytes = cname_bytes[:3]
    if len(cname_bytes) < 3: return "???"
    
    # Check official: Alphanumeric string
    try:
        s = cname_bytes.decode('latin-1')
        # Official cars are ASCII Alphanumeric (e.g. XFG) and usually 3 chars
        if s.isalnum() and s.isascii(): return s
    except: pass
    
    # It is a mod -> Hex String of Little Endian Int
    val = int.from_bytes(cname_bytes, 'little')
    mod_id = f"{val:06X}"
    
    # Auto-resolve if unknown
    if mod_id not in STATE.mod_map:
        # Avoid spamming requests for the same unknown ID
        if mod_id not in getattr(STATE, 'pending_mod_resolutions', set()):
            if not hasattr(STATE, 'pending_mod_resolutions'): STATE.pending_mod_resolutions = set()
            STATE.pending_mod_resolutions.add(mod_id)
            threading.Thread(target=resolve_mod_name_from_web, args=(mod_id,), daemon=True).start()
            
    return mod_id

def resolve_mod_name_from_web(mod_id: str):
    url = f"https://www.lfs.net/files/vehmods/{mod_id}"
    logging.info(f"Resolving Mod ID {mod_id} from {url}...")
    try:
        # Better headers to look like a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        # Try multiple patterns
        import re
        # Pattern 1: Title (LFS - Files - Vehicle Mods - NAME)
        match = re.search(r'<title>.*?Vehicle Mods - (.*?)</title>', html, re.IGNORECASE)
        
        # Pattern 2: H1 (If title fails)
        if not match:
             match = re.search(r'<h1>(.*?)</h1>', html, re.IGNORECASE)
             
        if match:
            mod_name = match.group(1).strip()
            logging.info(f"Resolved Mod {mod_id} -> {mod_name}")
            
            with STATE.lock:
                STATE.mod_map[mod_id] = mod_name
                # Update mods list
                found = False
                for m in STATE.mods:
                    if m.get('id') == mod_id:
                        m['name'] = mod_name # Update name if it was wrong? or populate
                        found = True
                        break
                    if m['name'].upper() == mod_name.upper() and not m.get('id'):
                         m['id'] = mod_id
                         found = True
                         break
                
                if not found:
                    STATE.mods.append({"name": mod_name, "id": mod_id})
                    
                # Save to file
                try:
                    with open(os.path.join(os.path.dirname(__file__), 'mods.json'), 'w') as f:
                        json.dump(STATE.mods, f, indent=4)
                    logging.info(f"Saved {mod_name} to mods.json")
                except Exception as e:
                    logging.error(f"Error saving mods.json: {e}")
            
            # Update active players
            with STATE.lock:
                for uid, p in STATE.current_race['players'].items():
                     if p.get('car') == mod_id:
                         p['car'] = mod_name
                         logging.info(f"Updated Player {p.get('uname')} car to {mod_name}")
                    
    except Exception as e:
        logging.error(f"Failed to resolve Mod {mod_id}: {e}")
    finally:
        if hasattr(STATE, 'pending_mod_resolutions'):
            STATE.pending_mod_resolutions.discard(mod_id)

# --- TRANSLATIONS ---
TRANSLATIONS = {
    'es': {
        'welcome_base': "^7Bienvenido ^3{uname}^7! Usa ^2!help^7 para ver comandos.",
        'welcome_reg': "^7?Nuevo? Escribe ^2!register^7 para guardar tu progreso.",
        'help_title': "^1Comandos Disponibles",
        'top_title': "^1Top 10 Tiempos ({track} - {car})",
        'teams_title': "^1Top Equipos",
        'pb_title': "^3PB Actual ({track}/{car})",
        'tb_title': "^3Mejor Teorico ({track}/{car})",
        'wr_title': "^1Record ({track}/{car})",
        'no_pb': "^7Sin registro",
        'no_wr': "^7Sin registro",
        'pb_msg': "^3PB Actual ({track}/{car}): ^2{time}",
        'wr_msg': "^1Record ({track}/{car}): ^7{holder} - ^3{time}^7",
        'tb_msg': "^3Mejor Teorico ({track}/{car}): ^1{time}^7 ({splits})",
        'lang_set': "^7Idioma cambiado a ^2Espanol^7.",
        'cmd_desc': "^3Descripcion",
        'cmd_cmd': "^3Comando",
        'desc_top': "^7Top 10 Tiempos (Combo actual)",
        'desc_teams': "^7Top Equipos",
        'desc_pb': "^7Tu PB (Pista/Coche actual)",
        'desc_tb': "^7Mejor Teorico (Mejores parciales)",
        'desc_wr': "^7Record del Servidor (SR)",
        'desc_stats': "^7Estadisticas globales",
        'desc_reg': "^7Obtener contrasena web",
        'desc_vote': "^7Votar siguiente combo",
        'desc_lang': "^7Cambiar idioma (es/en)",
        'desc_rank': "^7Ranking de pilotos (ELO)",
        'desc_topwins': "^7Top victorias",
        'desc_topcars': "^7Coches mas usados",
        'desc_elo': "^7Ver tu ELO",
        'desc_team': "^7Gestion de equipos",
        'desc_nations': "^7Ranking de paises",
        'desc_resetui': "^7Resetear interfaz",
        'desc_mods': "^7Ver Mods activos",
        'desc_random': "^7Randomizar Grid (Admin)",
        'desc_allcars': "^7Todos los coches (Admin)",
        'desc_admin': "^7Menu de Admin",
        'desc_badcombo': "^7Reportar Combo Malo",
        'err_track_car': "Debes estar en pista con un coche.",
        'err_no_data': "No hay datos registrados.",
        'vote_started': "^2íVotacion iniciada! ^3!vote [ID]^2 para votar.",
        'vote_ended': "^3Votacion finalizada. ^7Ganador: ^2{name} ^7({votes} votos)",

        'vote_cancelled': "^1Votacion cancelada por insuficientes votos.",
        'voting_cancelled': "^1Votacion cancelada por Admin.",
        'vote_registered': "^2Voto registrado.",
        'new_pb': "^3íNUEVO PB! ^7{uname} registra su primer tiempo en {track} con {car}: ^2{time}^7",
        'impr_pb': "^3íPB! ^7{uname} mejora su record en {track} con {car}: ^2{time}^7 (^1-{diff}^7)",
        'new_wr': "^1íNUEVO RECORD! ^7{uname} establece el record en {track} con {car}: ^3{time}^7",
        'impr_wr': "^1íRECORD DEL SERVIDOR! ^7{uname} rompe el record en {track} con {car}: ^3{time}^7 (^1-{diff}^7)",
        'btn_rank': "[Rank]",
        'btn_topwins': "[Top Wins]",
        'btn_topcars': "[Top Cars]",
        'btn_mypb': "[Mis PB]",
        'btn_sr': "[Records]",
        'btn_teams': "[Equipos]",
        'btn_nations': "[Paises]",
        'team_usage_join': "Uso: !team join <ID>",
        'invalid_id': "ID invalido",
        'db_error': "Error de BD",
        'team_not_found': "Equipo no encontrado",
        'already_in_team': "Ya estas en este equipo",
        'already_in_a_team': "Ya estas en un equipo. Usa !team leave",
        'team_join_success': "Te has unido a ^2{name}^7 (ID: {id})",
        'not_in_team': "No estas en ningun equipo",
        'team_leave_success': "Has salido del equipo",
        'team_help_msg': "^3Comandos de Equipo:\n^2!team info^7 - Info\n^2!team create <nombre>^7 - Crear\n^2!team join <id>^7 - Unirse\n^2!team leave^7 - Salir\n^2!team pending^7 - Solicitudes",
        'team_menu_title': "Gestión de Equipo",
        'team_btn_info': "Ver Información",
        'team_desc_info': "Muestra los miembros y stats",
        'team_btn_pending': "Solicitudes",
        'team_desc_pending': "Aceptar/Rechazar miembros",
        'team_btn_leave': "Abandonar",
        'team_desc_leave': "Salir de este equipo",
        'team_btn_create': "Crear Equipo",
        'team_btn_join': "Unirse",
        'team_usage_decline': "Uso: !team decline <usuario>",
        'team_usage_promote': "Uso: !team promote <usuario>",
        'team_accepted': "^2Has aceptado a {user} en el equipo",
        'team_declined': "^1Has rechazado a {user}",
        'team_kicked': "^1Has expulsado a {user} del equipo",
        'team_promoted': "^3Has modificado los permisos de {user}",
        'team_left': "^1Has abandonado tu equipo",
        'no_pending_requests': "No hay solicitudes pendientes",
        'api_error': "^1Error conectando con la base de datos central",
        'not_in_a_team': "^1No estás en ningún equipo",
        'no_permission': "^1No tienes permisos para hacer esto",
        'cannot_target_self': "^1No puedes usar este comando en ti mismo",
        'target_not_in_team': "^1Ese usuario no está en el equipo",
        'target_already_in_team': "^1Ese usuario ya está en otro equipo",
        'no_request': "^1No hay ninguna solicitud de ese usuario",
        
        'team_info_msg': "Equipo: ^2{name}^7 | Puntos: {points} | Miembros: {members}",
        'no_teams': "No hay equipos creados",
        'teams_list_title': "^3Lista de Equipos:^7\n",
        'must_be_on_track_tb': "Debes estar en pista para ver tu TB.",
        'cmd_disabled': "^1Comando desactivado en este servidor.",
        'vote_menu': "^3Menu de Votacion:\n^2!vote skip ^7- Saltar Pista (Random)\n^2!vote restart ^7- Reiniciar\n^2!vote cancel ^7- Cancelar",
        'vote_active': "^3Votacion en curso: ^2{type}^7. Votos: ^2{yes}/{needed}^7. ^2!vote yes^7 para votar.",
        'vote_passed': "^2íVotacion Aprobada! ^3Ejecutando...",
        'vote_failed': "^1Votacion Fallida (Tiempo/Votos insuficientes).",
        'vote_already': "^1Ya has votado.",
        'no_vote_active': "^1No hay votacion activa. Usa !vote start",
        'vote_started_user': "^2{uname} ^3inicio votacion: ^2{type}^7. Escribe ^2!vote yes ^7para apoyar.",
        'no_splits': "No tienes parciales registrados para este combo.",
        'no_pbs_target': "No hay PBs registrados para {target}",
        'invalid_track': "Pista invalida",
        'invalid_car': "Coche invalido",
        'pb_target_track_car': "PB en {track} con {car}: ^2{uname}^7 - ^3{time}^7",
        'no_pb_target_track_car': "No hay PB registrado en {track} con {car}",
        'no_pbs_track': "No hay PBs en {track}",
        'user_unknown': "Usuario desconocido.",
        'already_registered': "^1Ya estas registrado. ^7Usa tu contrasena en la web.",
        'reg_code_msg': "^7Tu codigo de verificacion es: ^3{code}",
        'reg_code_help': "^7Ingresalo en ^3lfsrank.com^7 para completar el registro.",
        'reg_code_expiry': "^7Este codigo expira en 10 minutos.",
        'reg_error': "Error al generar el codigo.",
        'reg_disabled': "^1Registro desactivado actualmente.",
        'reg_srv_gen': "^2íToken de Servidor Generado!",
        'reg_srv_token': "^3Token: ^7{token}",
        'reg_srv_help': "^7Pon este token en la consola del bot al iniciarlo.",
        'reg_srv_fail': "^1Error al generar token: {err}",
        'reg_type': "Tipo",
        'reg_info': "Informacion",
        'reg_web_prof': "^3Perfil Web",
        'reg_web_goto': "^7Ve a ^2lfsrank.com/login",
        'reg_login_code': "^3Codigo Login",
        'reg_new_srv': "^3Nuevo Servidor",
        'reg_click': "^7Click para registrar",
        'reg_menu_title': "Menu de Registro",
        'reg_fail': "^1Fallo en el registro: {err}",
        # Admin Panel
        'adm_race_ctrl': "Control de Carrera",
        'adm_race_ctrl_desc': "Start, Stop, Restart...",
        'adm_rot': "Forzar Rotacion",
        'adm_rot_desc': "Forzar combos aleatorios...",
        'adm_mc': "Multi-Clase",
        'adm_mc_desc': "Max Cats: {max}",
        'adm_cats': "Clases Permitidas",
        'adm_cats_desc': "Activar/Desactivar GTI, TBO...",
        'adm_mods': "Mods ({state})",
        'adm_mods_desc': "Permitir descargar Mods",
        'adm_reset_cars': "Resetear !setcars",
        'adm_reset_cars_desc': "Limpia el filtro de !setcars",
        'adm_abort_vote': "Abortar Votacion",
        'adm_abort_vote_desc': "Cancela la votacion actual",
        'adm_action': "Accion",
        'adm_open': "Abrir",
        'adm_run': "Ejecutar",
        'adm_select': "Elegir",
        'adm_toggle': "Cambiar",
        'adm_main_title': "Panel de Admin - MAIN",
        'adm_start': "Iniciar Carrera",
        'adm_start_desc': "Fuerza inicio (/start)",
        'adm_restart': "Reiniciar",
        'adm_restart_desc': "Reinicia la sesion (/restart)",
        'adm_end': "Finalizar Sesion",
        'adm_end_desc': "Termina la sesion (/end)",
        'adm_force_vote': "Iniciar Votacion",
        'adm_force_vote_desc': "Fuerza votacion inmediata",
        'adm_back': "<- Volver",
        'adm_back_desc': "Volver al Menu Principal",
        'adm_ctrl_title': "Admin - CONTROL DE CARRERA",
        'adm_rand': "Config Aleatoria",
        'adm_rand_desc': "Auto (Mix/Mods)",
        'adm_rand_std': "Aleatorio STD",
        'adm_rand_std_desc': "Solo Coches Vanilla",
        'adm_rand_mods': "Aleatorio MODS",
        'adm_rand_mods_desc': "Solo Mods",
        'adm_rot_title': "Admin - ROTACION",
        'adm_mc_max': "Max Categorias: {n}",
        'adm_mc_single': "Monocategoria",
        'adm_mc_dual': "Dual Class",
        'adm_mc_tri': "Tri Class",
        'adm_mc_quad': "Quad Class",
        'adm_fixed': "Modo Fijo ({state})",
        'adm_fixed_desc': "ON: Fija exacto. OFF: Aleatorio hasta max",
        'adm_mc_title': "Admin - MULTI-CLASE",
        'adm_cat_toggle': "Cambiar {c}",
        'adm_cat_curr': "Actual: {status}",
        'adm_allow_all': "Permitir Todos",
        'adm_allow_all_desc': "Habilita todas las categorias",
        'adm_category': "Categoria",
        'adm_status': "Estado",
        'adm_cats_title': "Admin - CLASES PERMITIDAS",


        'top_wr_title': "Records del Sistema",
        'no_wr_track': "No hay records en {track}",
        'vote_registered': "Voto registrado!",
        'stats_title': "Estadisticas",
        'stats_players': "Jugadores",
        'stats_avg_elo': "ELO Promedio",
        'stats_races': "Carreras",
        'rank_title': "Ranking de Pilotos",
        'rank_pos': "^3Pos",
        'rank_player': "^3Jugador",
        'rank_elo': "^3ELO",
        'rank_wins': "^3Victorias",
        'teams_rank_title': "Ranking de Equipos",
        'nations_rank_title': "Ranking de Paises",
        'topwins_title': "Top Victorias",
        'topcars_title': "Coches Mas Usados",
        'topcars_car': "^3Coche",
        'topcars_uses': "^3Usos",
        'no_car_data': "Sin datos de coches.",
        'elo_msg': "{uname}, tu ELO es: ^2{elo}^7",
        'team_create_usage': "Uso: !team create <nombre>",
        'team_name_len': "El nombre no puede exceder 30 caracteres",
        'team_exists': "Ya existe un equipo con ese nombre",
        'team_created': "Equipo ^2{name}^7 creado. Eres el jefe (ID: {id})",
        'lang_usage': "Uso/Use: !lang <es|en>",
        'lang_options': "Idiomas/Languages: es, en",
        'vote_title': "VOTA PROXIMA CARRERA",
        'vote_time': "Tiempo: {time}s",
        'close_btn': "Cerrar",
        'team_info_msg': "Equipo: ^2{name}^7 | Puntos: {points} | Miembros: {members}",
        'team_list_title': "^3Lista de Equipos:^7\n",
        'team_request_sent': "Solicitud enviada para unirse a ^2{name}^7",
        'team_request_exists': "Ya tienes una solicitud pendiente para este equipo",
        'team_request_not_found': "Solicitud no encontrada",
        'team_member_added': "Anadido ^2{uname}^7 al equipo",
        'team_member_kicked': "Expulsado ^2{uname}^7 del equipo",
        'team_not_leader': "Solo el jefe de equipo puede hacer esto",
        'team_pending_title': "Solicitudes Pendientes",
        'team_no_pending': "No hay solicitudes pendientes",
        'team_request_declined': "Solicitud de {uname} rechazada",
        'team_promoted': "Has ascendido a {uname} a jefe",
        'team_usage_accept': "Uso: !team accept <usuario>",
        'team_usage_kick': "Uso: !team kick <usuario>",
        'vote_no_votes': "Sin votos. Reiniciando.",
        'setcars_success': "^2Coches fijados para votacion: ^3{cars}",
        'setcars_reset': "^2Restriccion de coches eliminada. Votacion normal.",
        'err_no_valid_cars': "^1No se encontraron coches validos en el comando. Usa nombres como XFG, GTR, etc.",
        'qual_ended_msg': "^3Clasificacion Finalizada. ^2Iniciando Carrera...",
        'vote_winner_simple': "^7GANADOR: ^2{name}",
        'restart_msg': "^3Reinicio en {time}...",
        'admin_only_random': "Solo los admins pueden usar este comando",
        'admin_only': "Solo los admins pueden usar este comando",
        'new_config_msg': "NUEVA CONFIGURACION ({source})!",
        'random_activated': "{uname} activo configuracion ALEATORIA!",
        'changing_track_wait': "^3Cambiando de circuito en 10 segundos...",
        # Table Headers
        'header_track': "^3Pista",
        'header_car': "^3Coche",
        'header_pilot': "^3Piloto",
        'header_player': "^3Piloto",
        'header_elo': "^3ELO",
        'header_time': "^3Tiempo",
        'header_pos': "^3#",
        'header_team': "^3Equipo",
        'header_points': "^3Puntos",
        'header_role': "^3Rol",
        'header_member': "^3Miembro",
        'header_user': "^3Usuario",
        'header_date': "^3Fecha",
        'header_acc': "^3Acc",
        'header_dec': "^3Dec",
        'header_kick': "^3Kick",
        'header_prom': "^3Prom",
        'header_name': "^3Nombre",
        'header_members_short': "^3Mems",
        # Race Control
        'qual_start_msg': "^3Clasificacion: ^7{track} ({car_names}) ^3{qual_mins} min.",
        'race_start_msg': "^7Carrera: ^3{track} ^7({car_names}) ^3{laps} vueltas",
        'race_finished_pos': "^7{uname} ha terminado ^3#{pos}^7. Tiempo: ^2{t_str}",
        'race_winner': "^1íVICTORIA! ^7{uname} gana la carrera con ^2{t_str}",
        'results_separator': "^7--- ^3Resultados ^7---",
        'voting_remaining_msg': "^7Faltan ^3{remaining}^7 carreras para la votacion.",
        'qual_finished_restart': "^1Clasificacion Finalizada. Iniciando Carrera...",
        'track_empty_skip': "^3Pista vacia por 1 minuto. Saltando Clasificacion...",
        'time_extra_expired': "^1Tiempo extra expirado. Iniciando carrera...",
        'qual_overtime_start': "^3Clasificacion terminada. Esperando ^2{wait:.0f}s ^3para finalizar vueltas (110%).",
        'session_finished': "^1Sesion Finalizada. Iniciando Carrera...",
        'qual_time_expired': "^3Tiempo expirado. Termina tu vuelta.",
        'time_limit_reached': "^1Tiempo limite alcanzado. Procesando resultados...",
        'time_limit_warn': "^3Tiempo limite (110%): {time} (+{wait}s)",
        'api_sync_error': "^1Error sincronizando resultados con la API.",
        # Cars
        'car_any': "Todos los Coches",
        'car_all': "Todos",
        'car_unknown': "Desconocido",
        'invalid_car_selection': "Seleccion de coche invalida",
        'btn_kick': "KICK",
        'btn_prom': "PROM",
        'header_kick': "Kick",
        'header_prom': "Prom",
        'role_leader': "Jefe",
        'role_member': "Miembro",
        'records_title': "Records en {track}",
        'track_loaded': "^2Pista Cargada. ^3íHaced /ready cuando esteis listos!",
        'ui_reset_wait': "^3Reset UI... Espere...",
        'ui_reset_done': "^2UI Reset Completado.",
        'vote_random_choice': "^3Sin votos. Eligiendo opcion aleatoria...",
        'sys_record_msg': "^3íRECORD DE SISTEMA! ^7{uname} en {track}: ^3{time}",
        'elo_change_msg': "^3#{pos} ^7{uname}{car}: ^3{elo} ^7({change}^7)",
        'elo_no_change_msg': "^3#{pos} ^7{uname}{car}: (Sin cambios)",
        'header_nation': "^3Pais",
        'header_wins': "^3Victorias",
        'track_info': "^3Pista: ^7{track} ({len} km) | ^3Viento: ^7{wind} | ^3Clima: ^7{weather}",
        'web_info': "^3Ranking Web: ^2https://lfsrank.com",
        'rank_header_pos': "^3#",
        'rank_header_pilot': "^3Piloto",
        'rank_header_elo': "^3ELO",
        'rank_header_wins': "^3Wins",
        'topwins_header_pos': "^3#",
        'topwins_header_pilot': "^3Piloto",
        'topwins_header_wins': "^3Victorias",
        'stats_not_found': "^1No se encontraron estadisticas.",
        'qual_results_title': "^3--- RESULTADOS DE CLASIFICACION ---",
        'qual_no_times': "^7(No times recorded)",
    },
    'en': {
        'welcome_base': "^7Welcome ^3{uname}^7! Use ^2!help^7 for commands.",
        'welcome_reg': "^7New? Type ^2!register^7 to save your progress.",
        'help_title': "^1Available Commands",
        'top_title': "^1Top 10 Times ({track} - {car})",
        'teams_title': "^1Top Teams",
        'pb_title': "^3Current PB ({track}/{car})",
        'tb_title': "^3Theoretical Best ({track}/{car})",
        'wr_title': "^1Record ({track}/{car})",
        'no_pb': "^7No record",
        'no_wr': "^7No record",
        'pb_msg': "^3PB: ^7{track} - {car} - ^3{time}",
        'wr_msg': "^3SYSTEM RECORD: ^7{track} - {car} - ^2{holder} ^7- ^3{time}",
        'tb_msg': "^3Theoretical Best ({track}/{car}): ^1{time}^7 ({splits})",
        'lang_set': "^7Language changed to ^2English^7.",
        'cmd_desc': "^3Description",
        'cmd_cmd': "^3Command",
        'desc_top': "^7Top 10 Times (Current Combo)",
        'desc_teams': "^7Top Teams",
        'desc_pb': "^7Your PB (Current Track/Car)",
        'desc_tb': "^7Theoretical Best (Best Splits)",
        'desc_wr': "^7Server Record (SR)",
        'desc_stats': "^7Global Stats",
        'desc_reg': "^7Get Web Password",
        'desc_vote': "^7Vote Next Combo",
        'desc_lang': "^7Change Language (es/en)",
        'desc_rank': "^7Driver Ranking (ELO)",
        'desc_topwins': "^7Top Wins",
        'desc_topcars': "^7Most Used Cars",
        'desc_elo': "^7View your ELO",
        'desc_team': "^7Team Management",
        'desc_nations': "^7Nations Ranking",
        'desc_resetui': "^7Reset UI",
        'err_track_car': "You must be on track with a car.",
        'err_no_data': "No data found.",
        'vote_started': "^3Voting started! ^7Use buttons or !vote <id>",
        'desc_mods': "^7View active Mods",
        'cmd_disabled': "^1Command disabled on this server.",
        'vote_menu': "^3Voting Menu:\n^2!vote skip ^7- Skip Track (Random)\n^2!vote restart ^7- Restart\n^2!vote cancel ^7- Cancel",
        'desc_admin': "^7Admin Menu",
        'setcars_reset': "^2Car restriction removed. Normal voting.",
        'vote_active': "^3Voting in progress: ^2{type}^7. Votes: ^2{yes}/{needed}^7. ^2!vote yes^7 to support.",
        'vote_already': "^1You have already voted.",
        'desc_random': "^7Randomize Grid (Admin)",
        'err_no_valid_cars': "^1No valid cars found in command. Use names like XFG, GTR, etc.",
        'desc_badcombo': "^7Report Bad Combo",
        'setcars_success': "^2Cars fixed for voting: ^3{cars}",
        'vote_passed': "^2Voting Passed! ^3Executing...",
        'vote_failed': "^1Voting Failed (Time/Votes insufficient).",
        'vote_started_user': "^2{uname} ^3started a vote: ^2{type}^7. Type ^2!vote yes ^7to support.",
        'no_vote_active': "^1No active voting. Use !vote start",
        'desc_allcars': "^7All cars (Admin)",
        'voting_cancelled': "^1Voting cancelled by Admin.",
        'qual_ended_msg': "^3Qualification Ended. ^2Starting Race...",
        'vote_cancelled': "^1Voting cancelled due to insufficient votes.",

        'vote_ended': "^3Voting ended. ^7Winner: ^2{name} ^7({votes} votes)",
        'new_pb': "^3NEW PB! ^7{uname} sets first time on {track} in {car}: ^2{time}^7",
        'impr_pb': "^3PB! ^7{uname} improves on {track} in {car}: ^2{time}^7 (^1-{diff}^7)",
        'new_wr': "^1NEW RECORD! ^7{uname} sets record on {track} in {car}: ^3{time}^7",
        'impr_wr': "^1SERVER RECORD! ^7{uname} breaks record on {track} in {car}: ^3{time}^7 (^1-{diff}^7)",
        'btn_rank': "[Rank]",
        'btn_topwins': "[Top Wins]",
        'btn_topcars': "[Top Cars]",
        'btn_mypb': "[My PB]",
        'btn_sr': "[Records]",
        'btn_teams': "[Teams]",
        'btn_nations': "[Nations]",
        'team_usage_join': "Usage: !team join <ID>",
        'invalid_id': "Invalid ID",
        'db_error': "DB Error",
        'team_not_found': "Team not found",
        'already_in_team': "You are already in this team",
        'already_in_a_team': "You are already in a team. Use !team leave",
        'team_join_success': "Joined team ^2{name}^7 (ID: {id})",
        'not_in_team': "You are not in any team",
        'team_leave_success': "You left the team",
        'team_help_msg': "^3Team Commands:\n^2!team info^7 - Info\n^2!team create <name>^7 - Create\n^2!team join <id>^7 - Join\n^2!team leave^7 - Leave\n^2!team pending^7 - Requests",
        'team_menu_title': "Team Management",
        'team_btn_info': "View Info",
        'team_desc_info': "Show members and stats",
        'team_btn_pending': "Pending Requests",
        'team_desc_pending': "Accept/Decline members",
        'team_btn_leave': "Leave Team",
        'team_desc_leave': "Leave this team",
        'team_btn_create': "Create Team",
        'team_btn_join': "Join Team",
        'team_usage_decline': "Usage: !team decline <user>",
        'team_usage_promote': "Usage: !team promote <user>",
        'team_accepted': "^2You have accepted {user} into the team",
        'team_declined': "^1You have declined {user}",
        'team_kicked': "^1You have kicked {user} from the team",
        'team_promoted': "^3You have modified permissions for {user}",
        'team_left': "^1You have left your team",
        'no_pending_requests': "No pending requests",
        'api_error': "^1Error connecting to central database",
        'not_in_a_team': "^1You are not in a team",
        'no_permission': "^1You don't have permission to do this",
        'cannot_target_self': "^1You cannot use this command on yourself",
        'target_not_in_team': "^1That user is not in the team",
        'target_already_in_team': "^1That user is already in a team",
        'no_request': "^1There is no request from that user",
        
        'team_info_msg': "Team: ^2{name}^7 | Points: {points} | Members: {members}",
        'no_teams': "No teams created",
        'teams_list_title': "^3Teams List:^7\n",
        'must_be_on_track_tb': "You must be on track to see your TB.",
        'no_splits': "No splits recorded for this combo.",
        'no_pbs_target': "No PBs found for {target}",
        'invalid_track': "Invalid track",
        'invalid_car': "Invalid car",
        'pb_target_track_car': "PB on {track} in {car}: ^2{uname}^7 - ^3{time}^7",
        'no_pb_target_track_car': "No PB recorded on {track} in {car}",
        'no_pbs_track': "No PBs on {track}",
        'user_unknown': "Error: Could not identify your user.",
        'already_registered': "^1Already registered. ^7Use your password on the web.",
        'reg_code_msg': "^3Your registration code is: ^2{code}",
        'reg_code_help': "^7Enter it on the web to complete registration/login.",
        'reg_code_expiry': "^7This code expires in 10 minutes.",
        'reg_error': "Error generating code.",
        'reg_disabled': "^1Registration is currently disabled.",
        'reg_srv_gen': "^2Server Token Generated!",
        'reg_srv_token': "^3Token: ^7{token}",
        'reg_srv_help': "^7Put this token in your bot console when starting.",
        'reg_srv_fail': "^1Token generation failed: {err}",
        'reg_type': "Type",
        'reg_info': "Information",
        'reg_web_prof': "^3Web Profile",
        'reg_web_goto': "^7Go to ^2lfsrank.com/login",
        'reg_login_code': "^3Login Code",
        'reg_new_srv': "^3New Server",
        'reg_click': "^7Click to register",
        'reg_menu_title': "Registration Menu",
        'reg_fail': "^1Registration failed: {err}",
        # Admin Panel
        'adm_race_ctrl': "Race Control",
        'adm_race_ctrl_desc': "Start, Stop, Restart...",
        'adm_rot': "Force Rotation",
        'adm_rot_desc': "Force Random Combos...",
        'adm_mc': "Multi-Class",
        'adm_mc_desc': "Max Cats: {max}",
        'adm_cats': "Allowed Classes",
        'adm_cats_desc': "Toggle GTI, TBO, GTR...",
        'adm_mods': "Mods ({state})",
        'adm_mods_desc': "Toggle Mods Allow",
        'adm_reset_cars': "Reset !setcars",
        'adm_reset_cars_desc': "Clear user !setcars Filter",
        'adm_abort_vote': "Abort Vote",
        'adm_abort_vote_desc': "Cancel Current Vote",
        'adm_action': "Action",
        'adm_open': "Open",
        'adm_run': "Run",
        'adm_select': "Select",
        'adm_toggle': "Toggle",
        'adm_main_title': "Admin Panel - MAIN",
        'adm_start': "Start Race",
        'adm_start_desc': "Force Start (/start)",
        'adm_restart': "Restart",
        'adm_restart_desc': "Restart Session (/restart)",
        'adm_end': "End Session",
        'adm_end_desc': "End Session (/end)",
        'adm_force_vote': "Start Vote",
        'adm_force_vote_desc': "Force New Voting",
        'adm_back': "<- Back",
        'adm_back_desc': "Return to Main Menu",
        'adm_ctrl_title': "Admin - RACE CONTROL",
        'adm_rand': "Random Config",
        'adm_rand_desc': "Auto (Mix/Mods)",
        'adm_rand_std': "Random STD",
        'adm_rand_std_desc': "Standard Cars Only",
        'adm_rand_mods': "Random MODS",
        'adm_rand_mods_desc': "Mods Only",
        'adm_rot_title': "Admin - ROTATION",
        'adm_mc_max': "Set Max Categories: {n}",
        'adm_mc_single': "Single Spec",
        'adm_mc_dual': "Dual Class",
        'adm_mc_tri': "Tri Class",
        'adm_mc_quad': "Quad Class",
        'adm_fixed': "Fixed Mode ({state})",
        'adm_fixed_desc': "If ON, exact number is forced. If OFF, random up to max.",
        'adm_mc_title': "Admin - MULTI-CLASS",
        'adm_cat_toggle': "Toggle {c}",
        'adm_cat_curr': "Current: {status}",
        'adm_allow_all': "Allow All",
        'adm_allow_all_desc': "Enable all categories",
        'adm_category': "Category",
        'adm_status': "Status",
        'adm_cats_title': "Admin - ALLOWED CLASSES",


        'top_wr_title': "System Records",
        'no_wr_track': "No records on {track}",
        'vote_registered': "Vote registered!",
        'stats_title': "Statistics",
        'stats_players': "Drivers",
        'stats_avg_elo': "Avg ELO",
        'stats_races': "Races",
        'rank_title': "Driver Ranking",
        'rank_pos': "^3Pos",
        'rank_player': "^3Driver",
        'rank_elo': "^3ELO",
        'rank_wins': "^3Wins",
        'topwins_title': "Wins Ranking",
        'topcars_title': "Most Used Cars",
        'topcars_car': "^3Car",
        'topcars_uses': "^3Uses",
        'no_car_data': "No car data.",
        'elo_msg': "{uname}, your ELO is: ^2{elo}^7",
        'team_create_usage': "Usage: !team create <name>",
        'team_name_len': "Name cannot exceed 30 chars",
        'team_exists': "Team name already exists",
        'team_created': "Team ^2{name}^7 created. You are the leader (ID: {id})",
        'lang_usage': "Uso/Use: !lang <es|en>",
        'lang_options': "Idiomas/Languages: es, en",
        'vote_title': "VOTE NEXT RACE",
        'vote_time': "Time: {time}s",
        'close_btn': "Close",
        'team_info_msg': "Team: ^2{name}^7 | Points: {points} | Members: {members}",
        'team_list_title': "^3Teams List:^7\n",
        'team_request_sent': "Request sent to join ^2{name}^7",
        'team_request_exists': "You already have a pending request for this team",
        'team_request_not_found': "Request not found",
        'team_member_added': "Added ^2{uname}^7 to the team",
        'team_member_kicked': "Kicked ^2{uname}^7 from the team",
        'team_not_leader': "Only the team leader can do this",
        'team_pending_title': "Pending Requests",
        'team_no_pending': "No pending requests",
        'team_request_declined': "Declined request from {uname}",
        'team_promoted': "Promoted {uname} to leader",
        'team_usage_accept': "Usage: !team accept <username>",
        'team_usage_kick': "Usage: !team kick <username>",
        'vote_no_votes': "No votes. Restarting.",
        'vote_winner_simple': "^7WINNER: ^2{name}",
        'restart_msg': "^3Restart in {time}...",
        'admin_only_random': "Only admins can use this command",
        'admin_only': "Only admins can use this command",
        'new_config_msg': "NEW CONFIG ({source})!",
        'random_activated': "{uname} activated RANDOM config!",
        'changing_track_wait': "^3Changing track in 10 seconds...",
        # HEADERS
        'header_track': "^3Track",
        'header_car': "^3Car",
        'header_pilot': "^3Driver",
        'header_player': "^3Driver",
        'header_elo': "^3ELO",
        'header_time': "^3Time",
        'header_pos': "^3#",
        'header_team': "^3Team",
        'header_points': "^3Points",
        'header_role': "^3Role",
        'header_member': "^3Member",
        'header_user': "^3User",
        'header_date': "^3Date",
        'header_acc': "^3Acc",
        'header_dec': "^3Dec",
        'header_kick': "^3Kick",
        'header_prom': "^3Prom",
        'header_name': "^3Name",
        'header_members_short': "^3Mems",
        # Race Control
        'qual_start_msg': "^3Qualification: ^7{track} ({car_names}) ^3{qual_mins} min.",
        'race_start_msg': "^7Race: ^3{track} ^7({car_names}) ^3{laps} laps",
        'race_finished_pos': "^7{uname} finished ^3#{pos}^7. Time: ^2{t_str}",
        'race_winner': "^1VICTORY! ^7{uname} wins the race with ^2{t_str}",
        'results_separator': "^7--- ^3Results ^7---",
        'voting_remaining_msg': "^7^3{remaining}^7 races remaining until voting.",
        'qual_finished_restart': "^1Qualification Finished. Starting Race...",
        'track_empty_skip': "^3Track empty for 1 minute. Skipping Qualification...",
        'time_extra_expired': "^1Extra time expired. Starting race...",
        'qual_overtime_start': "^3Qual Finished. Waiting ^2{wait:.0f}s ^3for finishes (110% rule).",
        'session_finished': "^1Session Finished. Starting Race...",
        'qual_time_expired': "^3Time expired. Finish your lap.",
        'time_limit_reached': "^1Time limit reached. Processing results...",
        'time_limit_warn': "^3Time limit (110%): {time} (+{wait}s)",
        'api_sync_error': "^1Error syncing results with API.",
        # Cars
        'car_unknown': "Unknown",
        'btn_kick': "KICK",
        'btn_prom': "PROM",
        'header_kick': "Kick",
        'header_prom': "Prom",
        'role_leader': "Leader",
        'role_member': "Member",
        'car_all': "All",
        'car_any': "Any Car",
        'invalid_car_selection': "Invalid car selection",
        'nations_rank_title': "Nations Rank",
        'teams_rank_title': "Teams Rank",
        'records_title': "Records at {track}",
        'track_loaded': "^2Track Loaded. ^3Type /ready when ready!",
        'ui_reset_wait': "^3Reset UI... Wait...",
        'ui_reset_done': "^2UI Reset Complete.",
        'vote_random_choice': "^3No votes. Choosing random option...",
        'sys_record_msg': "^3SYSTEM RECORD! ^7{uname} at {track}: ^3{time}",
        'elo_change_msg': "^3#{pos} ^7{uname}{car}: ^3{elo} ^7({change}^7)",
        'elo_no_change_msg': "^3#{pos} ^7{uname}{car}: (No change)",
        'header_nation': "^3Nation",
        'header_wins': "^3Wins",
        'track_info': "^3Track: ^7{track} ({len} km) | ^3Wind: ^7{wind} | ^3Weather: ^7{weather}",
        'web_info': "^3Web Ranking: ^2https://lfsrank.com",
        'rank_header_pos': "^3#",
        'rank_header_pilot': "^3Driver",
        'rank_header_elo': "^3ELO",
        'rank_header_wins': "^3Wins",
        'topwins_header_pos': "^3#",
        'topwins_header_pilot': "^3Driver",
        'topwins_header_wins': "^3Wins",
        'stats_not_found': "^1Stats not found.",
        'qual_results_title': "^3--- QUALIFICATION RESULTS ---",
        'qual_no_times': "^7(No times recorded)",
    },
}

def get_msg(key: str, ucid: int, **kwargs) -> str:
    lang = 'es'
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            lang = STATE.current_race['players'][ucid].get('language', 'es')
    
    msg = TRANSLATIONS.get(lang, TRANSLATIONS['es']).get(key, key)
    try:
        return msg.format(**kwargs)
    except KeyError:
        return msg

def broadcast_localized(key: str, **kwargs):
    """Sends a message to ALL connected players, localized to their language."""
    # Snapshot of players to avoid lock issues during iteration
    players_copy = {}
    with STATE.lock:
        players_copy = STATE.current_race['players'].copy()
        
    for ucid in players_copy.keys():
        # Handle special kwargs that might differ per user (like car names)
        # For now, we assume kwargs are static strings unless handled specifically.
        # But car names DO depend on language.
        
        # We can pass a callback in kwargs? No, too complex.
        # Simple solution: If 'car_names_bitmask' is in kwargs, we compute car_names.
        current_kwargs = kwargs.copy()
        
        if 'car_names_bitmask' in kwargs:
             bitmask = kwargs['car_names_bitmask']
             lang = players_copy[ucid].get('language', 'es')
             current_kwargs['car_names'] = get_car_names(bitmask, lang)
             # Remove bitmask from kwargs passed to format
             del current_kwargs['car_names_bitmask']

        msg = get_msg(key, ucid, **current_kwargs)
        send_message(msg, ucid)

# --- CAR AND TRACK LISTS ---
# CORRECTED AND SORTED CAR_LIST
CAR_LIST = {
    1: "XFG",
    2: "XRG",
    4: "XRT",
    8: "RB4",
    16: "FXO",
    32: "LX4",
    64: "LX6",
    128: "MRT",
    256: "UF1",
    512: "RAC",
    1024: "FZ5",
    2048: "FOX",
    4096: "XFR",
    8192: "UFR",
    16384: "FO8",
    32768: "FXR",   # FIXED (Previously FZR was here)
    65536: "XRR",
    131072: "FZR",  # FIXED (Previously FXR was here)
    262144: "BF1",
    524288: "FBM"
}

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
    {"name": "FXR", "cars": ["FXR"], "code": 32768},     # FIXED
    {"name": "XRR", "cars": ["XRR"], "code": 65536},     # OK
    {"name": "FZR", "cars": ["FZR"], "code": 131072},    # FIXED
    {"name": "GTR Mix", "cars": ["FXR", "XRR", "FZR"], "code": 229376}, # Sum of the 3
    {"name": "MRT", "cars": ["MRT"], "code": 128},
    {"name": "FBM", "cars": ["FBM"], "code": 524288},
    {"name": "FOX", "cars": ["FOX"], "code": 2048},
    {"name": "FO8", "cars": ["FO8"], "code": 16384},
    {"name": "BF1", "cars": ["BF1"], "code": 262144},
]

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

RALLY_TRACKS = ["BL3", "BL3R", "FE5", "FE5R", "FE6", "FE6R"]
TARMAC_TRACKS = [t for t in VALID_TRACKS if t not in RALLY_TRACKS]

# Classes that must stay on Tarmac (Slicks, Formula, Kart)
TARMAC_ONLY_CLASSES = [
    "UFR", "XFR", "UFR + XFR", "FXR", "XRR", "FZR", "GTR Mix",
    "MRT", "FBM", "FOX", "FO8", "BF1"
]

# Small/Kart tracks (No big cars here)
SMALL_TRACKS = ["WE4", "WE4R", "WE5", "WE5R", "AS1", "AS1R", "RO6", "RO7", "RO11", "KY8", "KY8R"]
# Big/Fast classes that shouldn't race on small tracks
BIG_CLASSES = [
    "UFR", "XFR", "UFR + XFR", "FXR", "XRR", "FZR", "GTR Mix", "FO8", "BF1"
]

# Track Lengths in KM (Approx)
TRACK_LENGTHS = {
    "BL1": 3.3, "BL2": 3.3, "BL3": 1.8,
    "SO1": 2.0, "SO2": 2.0, "SO3": 1.3, "SO4": 4.0, "SO5": 3.1, "SO6": 2.9,
    "FE1": 1.6, "FE2": 3.1, "FE3": 3.5, "FE4": 6.6, "FE5": 2.0,
    "KY1": 3.0, "KY2": 5.1, "KY3": 7.4,
    "KY4": 3.0, "KY5": 3.0, "KY6": 3.0, "KY7": 3.0, "KY8": 1.0,
    "WE1": 4.4, "WE2": 5.8, "WE3": 0.0, "WE4": 0.5, "WE5": 1.3,
    "WE6": 3.0, "WE7": 3.0,
    "AS1": 1.9, "AS2": 3.1, "AS3": 5.6, "AS4": 8.1, "AS5": 8.8, "AS6": 8.0, "AS7": 5.2,
    "AS8": 3.0, "AS9": 3.0,
    "RO1": 3.1, "RO2": 2.7, "RO3": 2.4, "RO4": 3.3, "RO5": 1.0, "RO6": 1.6, "RO7": 3.9, "RO8": 3.6, "RO9": 2.2, "RO10": 4.1, "RO11": 2.7
}

# Est Avg Speed in KM/H (Conservative estimates)
CLASS_SPEEDS = {
    "UF1": 105, "XFG": 130, "XRG": 130, "XFG + XRG": 130,
    "RB4": 150, "FXO": 160, "XRT": 160, "LX4": 150, "LX6": 160,
    "RAC": 165, "FZ5": 170, "RAC + FZ5": 168,
    "MRT": 110, "FBM": 170, "FOX": 180,
    "XFR": 190, "UFR": 190, "UFR + XFR": 190,
    "FXR": 195, "XRR": 195, "FZR": 195, "GTR Mix": 195,
    "FO8": 220, "BF1": 250
}
def get_expected_lap_time_ms(track: str, class_name: str) -> float:
    base_track = track[:3]
    if track.startswith("RO") and len(track) >= 4 and track[2:4].isdigit():
        base_track = track[:4]
        
    if track.endswith("R") and track not in TRACK_LENGTHS:
         if track[:-1] in TRACK_LENGTHS:
             base_track = track[:-1]
             
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as c:
                target_cars = []
                for cls in BALANCED_CLASSES:
                    if cls['name'] == class_name:
                        target_cars = cls['cars']
                        break
                
                if not target_cars and class_name in CLASS_SPEEDS:
                     target_cars = [class_name]

                if target_cars:
                    placeholders = ', '.join(['%s'] * len(target_cars))
                    query = f"SELECT AVG(lap_time) FROM track_records WHERE track = %s AND car IN ({placeholders}) AND lap_time > 20000"
                    c.execute(query, [track] + target_cars)
                    row = c.fetchone()
                    if row and row[0]:
                        return float(row[0])
    except Exception as e:
        logging.error(f"Error fetching historical lap data for expected time: {e}")
    finally:
        if 'conn' in locals() and conn: conn.close()

    # Fallback to length / speed calculation
    length_km = TRACK_LENGTHS.get(base_track, TRACK_LENGTHS.get(track, 3.0))
    speed_kmh = CLASS_SPEEDS.get(class_name, 150)
    expected_hours = length_km / speed_kmh
    return expected_hours * 3600.0 * 1000.0


def calculate_laps(track: str, class_name: str, duration_min: int = 10) -> int:
    # Handle Reverse/Club suffix (assume same length approx, or strip)
    # BL1R -> BL1. BL2C is gone.
    base_track = track[:3] # BL1, SO4
    # Handling numeric suffixes > 9 (RO10, RO11) -> 4 chars
    if track.startswith("RO") and len(track) >= 4 and track[2:4].isdigit():
        base_track = track[:4]
    elif track.startswith("AS") and len(track) >= 4 and track[2:4].isdigit(): # AS10? No.
         pass
    
    # Strip 'R' if at end and not part of name (RO11R?)
    if track.endswith("R") and track not in TRACK_LENGTHS: # Simple strip check
         if track[:-1] in TRACK_LENGTHS:
             base_track = track[:-1]
    
    # Try to get average lap time from DB
    avg_lap_msg = ""
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as c:
                # Map class_name to car codes if possible, or just query by car IN (...)
                # CLASS_SPEEDS keys are "UF1", "XFG + XRG", etc.
                # Need to resolve class string to list of cars
                target_cars = []
                # Find matching class in BALANCED_CLASSES to get exact car list
                for cls in BALANCED_CLASSES:
                    if cls['name'] == class_name:
                        target_cars = cls['cars'] # e.g. ['XFG', 'XRG']
                        break
                
                if not target_cars and class_name in CLASS_SPEEDS:
                     # Fallback if class_name matches a car name exactly
                     target_cars = [class_name]

                if target_cars:
                    placeholders = ', '.join(['%s'] * len(target_cars))
                    query = f"SELECT AVG(lap_time) FROM track_records WHERE track = %s AND car IN ({placeholders}) AND lap_time > 20000"
                    c.execute(query, [track] + target_cars)
                    row = c.fetchone()
                    if row and row[0]:
                        avg_lap_display = float(row[0])
                        # If we have avg lap, use it!
                        # Laps = Duration / AvgLap
                        laps = int((duration_min * 60 * 1000) / avg_lap_display)
                        logging.info(f"Using Historical Data for {track} ({class_name}): Avg Lap {avg_lap_display/1000:.2f}s -> {laps} laps")
                        return max(2, laps)
    except Exception as e:
        logging.error(f"Error fetching historical lap data: {e}")
    finally:
        if conn: conn.close()

    length_km = TRACK_LENGTHS.get(base_track, TRACK_LENGTHS.get(track, 3.0))
    speed_kmh = CLASS_SPEEDS.get(class_name, 150)
    
    dist_needed = (speed_kmh * duration_min) / 60.0
    laps = int(round(dist_needed / length_km))
    return max(2, laps) # Minimum 2 laps


# --- Check if is admin ---
def is_admin(uname: str, ucid: int = -1) -> bool:
    # 1. Check Hardcoded/Config Admin List
    if uname and uname.lower() in [admin.lower() for admin in STATE.admin_list]:
        logging.info(f"DEBUG: is_admin TRUE (List match) for {uname}")
        return True
    
    # 2. Check InSim Admin Flag (if UCID provided)
    if ucid >= 0:
        with STATE.lock:
             if ucid in STATE.current_race['players']:
                 if STATE.current_race['players'][ucid].get('admin', False):
                     logging.info(f"DEBUG: is_admin TRUE (InSim Flag) for {uname} (UCID {ucid})")
                     return True
    
    logging.info(f"DEBUG: is_admin FALSE for {uname} (UCID {ucid}). Admins: {STATE.admin_list}")
    return False

# --- Base Categories for Multi-Class ---
BASE_CATEGORIES = [
    {"name": "GTI", "cars": ["XFG", "XRG"], "code": 1 | 2},
    {"name": "TBO", "cars": ["XRT", "RB4", "FXO"], "code": 4 | 8 | 16},
    {"name": "GTR", "cars": ["FXR", "XRR", "FZR"], "code": 32768 | 65536 | 131072},
    {"name": "U17", "cars": ["UFR", "XFR"], "code": 8192 | 4096},
    {"name": "LRF", "cars": ["LX4", "LX6"], "code": 32 | 64},
    {"name": "UF1", "cars": ["UF1"], "code": 256},
    {"name": "FZ5", "cars": ["FZ5"], "code": 1024},
    {"name": "MRT", "cars": ["MRT"], "code": 128},
    {"name": "FBM", "cars": ["FBM"], "code": 524288},
    {"name": "FOX", "cars": ["FOX"], "code": 2048},
    {"name": "FO8", "cars": ["FO8"], "code": 16384},
    {"name": "BF1", "cars": ["BF1"], "code": 262144}
]

# --- Generate balanced configuration ---
def generate_balanced_config(allow_mods: bool = True, allow_standard: bool = True) -> Dict:
    # Check for Admin Override
    override_cars = getattr(STATE, 'allowed_cars_filter', None)
    
    if override_cars:
        # User defined cars
        cls_code = override_cars
        cls_name = "Admin Selection"
        # We don't easily know if it's TARMAC or RALLY without looking up cars.
        possible_tracks = VALID_TRACKS
    else:
        # 1. Read Multi-Class Config from STATE
        max_multi = int(STATE.config.get('max_multi_class', 1))
        fixed_multi = bool(STATE.config.get('multi_class_fixed', False))
        allowed_classes = STATE.config.get('allowed_classes', [])
        
        num_classes = max_multi if fixed_multi else random.randint(1, max(1, max_multi))
        
        # 2. Build Pools
        pool_std = []
        if allow_standard:
            for c in BASE_CATEGORIES:
                if not allowed_classes or c['name'] in allowed_classes:
                    pool_std.append(c)
                    
        pool_mods = []
        if allow_mods:
            valid_mods = [m for m in STATE.mods if m.get('id')]
            for m in valid_mods:
                pool_mods.append({
                    "name": m['name'],
                    "cars": [m['name']],
                    "code": 0,
                    "mod_id": m['id']
                })
        
        # Combine pools if both are allowed
        chosen_pool = []
        if allow_mods and allow_standard:
            chosen_pool = pool_std + pool_mods
        elif allow_mods:
            chosen_pool = pool_mods
        else:
            chosen_pool = pool_std
            
        if not chosen_pool:
            chosen_pool = BASE_CATEGORIES # Fallback
            
        # 3. Select Multiple Classes
        num_to_pick = min(num_classes, len(chosen_pool))
        selected_classes = random.sample(chosen_pool, max(1, num_to_pick))
        
        # 4. Combine them
        cls_code = 0
        car_names_list = []
        mod_ids = []
        combined_class_names = []
        
        for c in selected_classes:
            cls_code |= c['code']
            car_names_list.extend(c['cars'])
            combined_class_names.append(c['name'])
            if c.get('mod_id'):
                mod_ids.append(c['mod_id'])
                
        cls_name = " + ".join(combined_class_names)
        car_names = " + ".join(car_names_list)
        mod_id = ",".join(mod_ids) if mod_ids else None
        is_mod_race = len(mod_ids) > 0
    
        # Filter tracks based on class type
        possible_tracks = VALID_TRACKS
        
        # If any selected class requires tarmac or is a big class, restrict tracks
        requires_tarmac = any(c in TARMAC_ONLY_CLASSES for c in combined_class_names) or is_mod_race
        is_big = any(c in BIG_CLASSES for c in combined_class_names)
        
        if requires_tarmac:
            possible_tracks = TARMAC_TRACKS
            
        if is_big:
            possible_tracks = [t for t in possible_tracks if t not in SMALL_TRACKS]

    if not possible_tracks: possible_tracks = VALID_TRACKS # Fallback
    
    track = random.choice(possible_tracks)

    if (track == STATE.previous_track and cls_code == STATE.previous_allowed_cars):
         # Avoid recursion depth issues if only 1 option exists
         if override_cars:
             pass 
         else:
             return generate_balanced_config()
             
    # Resolve car names (Optional, for display)
    if override_cars:
       # Reconstruct names from bitmask
        CAR_BITMASKS = {
            'XFG': 1, 'XRG': 2, 'XRT': 4, 'RB4': 8, 'FXO': 16, 'LX4': 32, 'LX6': 64, 'MRT': 128,
            'UF1': 256, 'RAC': 512, 'FZ5': 1024, 'FOX': 2048, 'XFR': 4096, 'UFR': 8192, 'FO8': 16384,
            'FXR': 32768, 'XRR': 65536, 'FZR': 131072, 'BF1': 262144, 'FBM': 524288
        }
        found = []
        for name, mask in CAR_BITMASKS.items():
            if (cls_code & mask): found.append(name)
        car_names = " + ".join(found)
    else:
        pass # Already combined above

    return {"track": track, "cars": cls_code, "name": f"{track} - {car_names}", "class": cls_name, "mod_id": mod_id}

# --- Generate voting options (AHORA 5 OPCIONES) ---
def generate_random_voting_options() -> List[Dict]:
    options = []
    used = set()
    while len(options) < 5: # CAMBIO: 5 opciones en lugar de 10
        config = generate_balanced_config()
        key = (config["track"], config["cars"])
        if key in used: continue
        used.add(key)
        options.append({"name": config["name"], "track": config["track"], "cars": config["cars"], "mod_id": config.get("mod_id")})
    return options
def set_random_configuration(source: str = "auto", allow_mods: bool = True, allow_standard: bool = True, config: Dict = None):
    with STATE.lock:
        if getattr(STATE, 'track_change_in_progress', False):
            logging.info("Ignored set_random_configuration: already in progress.")
            return
        STATE.track_change_in_progress = True
    
    # 1. Force End of current session
    send_message("/end")
    time.sleep(1.0)
    
    if config is None:
        config = generate_balanced_config(allow_mods=allow_mods, allow_standard=allow_standard)
    logging.info(f"{source.upper()} -> Config: {config['name']}")
    
    # 2. Apply New Config
    
    # 2. Apply New Config
    base_cars = config.get('cars', 0)
    mod_ids = config.get('mod_id')

    # Clear UI just to be safe
    for btn_id in range(0, 255):
        send_packet(struct.pack('<BBBBBBBB', 2, 42, 0, 1, 0, btn_id, 0, 0))
    
    send_message("/mods=NONE")
    time.sleep(0.1)

    if mod_ids:
        mods_str = mod_ids.replace(",", "+")
        send_message(f"/mods={mods_str}")
        logging.info(f"Set Mods: {mods_str}")
        time.sleep(0.2)

    if base_cars > 0:
        # Translate bitmask to string of names for LFS chat command
        CAR_BITMASKS = {
            'XFG': 1, 'XRG': 2, 'XRT': 4, 'RB4': 8, 'FXO': 16, 'LX4': 32, 'LX6': 64, 'MRT': 128,
            'UF1': 256, 'RAC': 512, 'FZ5': 1024, 'FOX': 2048, 'XFR': 4096, 'UFR': 8192, 'FO8': 16384,
            'FXR': 32768, 'XRR': 65536, 'FZR': 131072, 'BF1': 262144, 'FBM': 524288
        }
        found_cars = [name for name, mask in CAR_BITMASKS.items() if (base_cars & mask)]
        cars_str = "+".join(found_cars)
        
        send_message(f"/cars {cars_str}")
        logging.info(f"Set Cars: {cars_str} (Mask: {base_cars})")
        time.sleep(0.2)
    elif mod_ids:
        # Only mods allowed, disable all base cars
        send_message("/cars=NONE")
        logging.info("Set Cars: NONE (Mods Only)")
        time.sleep(0.2)
    else:
        # Fallback if no cars found
        logging.error("No cars found in config!")
        send_message("/cars XFG")
        
    time.sleep(0.5)

    # ALIGNMENT WITH VOTING: Wait 10s before changing track
    broadcast_localized('changing_track_wait')
    time.sleep(10.0)
    
    # --- Logic: Determine Class & Safe Weather ---
    NO_LIGHTS_CLASSES = ["MRT", "FBM", "FOX", "FO8", "BF1"]
    is_formula = False
    
    # Heuristic: Check if config name or class implies formula
    # Or check if 'cars' bitmask matches single formula cars? 
    # For now, rely on config.get('class') if available, or name check
    if config.get('class') in NO_LIGHTS_CLASSES:
        is_formula = True
    elif any(c in config['name'].upper() for c in NO_LIGHTS_CLASSES):
         is_formula = True

    # Randomize Wind (0: None/Low, 1: Low/High, 2: Strong)
    r_wind = random.randint(0, 2)
    
    # Randomize Weather (1: Day, 2: Sunset, 3: Night)
    # If Formula, restrict to 1-2
    allowed_weather = [1, 2]
    if not is_formula:
        allowed_weather.append(3)
        
    r_weather = random.choice(allowed_weather)

    # Set Track & Weather (IS_MST)
    qual_mins = STATE.config.get('qualify_duration', 8)
    race_laps_cfg = STATE.config.get('race_laps', 0)
    laps = race_laps_cfg if race_laps_cfg > 0 else calculate_laps(config['track'], config['name'], 10)
    
    # Command: /track [TRACK] [WEATHER] /qual [MINS] /laps [LAPS] /wind [WIND]
    cmd_str = f"/track {config['track']} /weather {r_weather} /qual {qual_mins} /laps {laps} /wind {r_wind}"
    send_message(cmd_str)
    # track_cmd = cmd_str.encode('latin-1')
    # track_cmd_padded = track_cmd.ljust(64, b'\x00')
    # send_packet(struct.pack('<BBBB64s', 17, 13, 0, 0, track_cmd_padded)) 
    
    # WAIT FOR TRACK LOAD
    time.sleep(12.0)
    broadcast_localized("track_loaded")

    # --- Random Time (New 0.7G+ Command) ---
    valid_hours = list(range(0, 24))
    
    # Rockingham has no floodlights -> No Night for No-Light cars
    if is_formula and config['track'].startswith("RO"):
         valid_hours = list(range(7, 18)) # 07:00 - 17:59
         
    r_hour = random.choice(valid_hours)
    r_min = random.choice([0, 15, 30, 45])
    send_message(f"/time set {r_hour:02}:{r_min:02}")
    
    # Auto Floodlights based on time and class
    # Formula/No-Headlight Classes logic
    # NO_LIGHTS_CLASSES = ["MRT", "FBM", "FOX", "FO8", "BF1"] # Already defined above
    
    # Check override - ALREADY DONE ABOVE
    # is_formula = False ...


    # Night logic for lights
    night_start = 17 
    night_end = 7
    is_night = (r_hour >= night_start or r_hour < night_end)

    if is_night:
        send_message("/flood yes")
        if is_formula:
             logging.info("Formula Class at Night: Floodlights forced ON.")
    else:
        send_message("/flood no")
    
    # Report Config
    wind_desc = ["Low", "High", "Strong"][r_wind]
    weather_desc = {1: "Day", 2: "Sunset", 3: "Night"}.get(r_weather, "Custom Time")
    
    msg = f"^3Random Config: ^7{config['name']} ^3@ ^7{config['track']} (Time {r_hour:02}:{r_min:02}, Wind {wind_desc})"
    send_message(msg)

    time.sleep(0.5)
    # Restart to begin session
    send_message("/restart")
    send_message(get_msg('new_config_msg', 0, source=source))
    send_message(f"{config['track']} - {config['name'].split(' - ', 1)[1] if ' - ' in config['name'] else config['name']}")

    with STATE.lock:
        STATE.previous_track = config['track']
        STATE.previous_allowed_cars = config['cars']
        STATE.current_allowed_cars = config['cars']
        STATE.current_config_name = config.get('name', '')
        STATE.consecutive_races = 0 # Reset counter on manual random? Yes.
        STATE.track_change_in_progress = False
    
    time.sleep(1)
    request_full_state_update()

    request_full_state_update()

# --- ADMIN COMMAND: !random ---
def admin_random_command(ucid: int, uname: str, args: list = []):
    # Only allow if admin (and not voting period?)
    if not is_admin(uname, ucid):
        send_message(get_msg('admin_only', ucid), ucid)
        return
    
    # Parse filter args
    allow_mods = True
    allow_standard = True
    
    if args:
        sub = args[0].lower()
        if sub in ['mods', 'mod']:
             allow_standard = False
             logging.info(f"ADMIN {uname} !random MODS ONLY")
             send_message(f"^3!random: ^2MODS ONLY")
        elif sub in ['std', 'standard', 'original', 'ori']:
             allow_mods = False
             logging.info(f"ADMIN {uname} !random STANDARD ONLY")
             send_message(f"^3!random: ^2STANDARD CARS ONLY")
    
    logging.info(f"ADMIN {uname} executed !random filter=[Mods:{allow_mods}, Std:{allow_standard}]")
    send_message(get_msg('random_activated', 0, uname=uname))
    threading.Thread(target=lambda: set_random_configuration("admin", allow_mods, allow_standard), daemon=True).start()

# --- Utilities ---
def get_db_connection():
    try:
        return mysql.connector.connect(
            host=ARGS.db_host, user=ARGS.db_user, password=ARGS.db_pass,
            database=ARGS.db_name, connection_timeout=10
        )
    except mysql.connector.Error as e:
        logging.error(f"DB Connection Error: {e}")
        return None

def calculate_elo(results: list):
    n = len(results)
    if n < 2: return
    K_FACTOR = 32
    for p_i in results:
        actual = (n - p_i['position']) / (n - 1)
        expected = sum(1 / (1 + 10 ** ((p_j['elo'] - p_i['elo']) / 400)) for p_j in results if p_j != p_i) / (n - 1)
        change = K_FACTOR * (actual - expected)
        p_i['new_elo'] = round(p_i['elo'] + change)
        p_i['elo_change'] = p_i['new_elo'] - p_i['elo']

def clean_string(data: bytes) -> str:
    try:
        decoded = data.decode('latin-1', errors='ignore')
        return decoded.split('\x00')[0].strip()
    except:
        return ""

def send_packet(packet: bytes):
    if STATE.insim_sock:
        try:
            STATE.insim_sock.sendall(packet)
        except (BrokenPipeError, OSError) as e:
            logging.error(f"Failed to send packet: {e}. Marking for reconnection.")
            STATE.insim_sock = None

def send_message(msg: str, ucid: int = 0):
    msg_bytes = msg.encode('latin-1')
    if ucid > 0:
        # IS_MTC (Msg To Connection) - Type 14
        msg_bytes = (msg_bytes[:127] + b'\x00')
        total_len = 8 + len(msg_bytes)
        padding = (4 - (total_len % 4)) % 4
        msg_bytes_padded = msg_bytes + (b'\x00' * padding)
        total_size = 8 + len(msg_bytes_padded)
        packet = struct.pack(f'<BBBBBBBB{len(msg_bytes_padded)}s', total_size // 4, 14, 0, 0, ucid, 0, 0, 0, msg_bytes_padded)
    else:
        # IS_MST (Msg Type) - Type 13 - Global Msg
        msg_bytes = (msg_bytes[:63] + b'\x00')
        packet = struct.pack('<BBBB64s', 17, 13, 0, 0, msg_bytes)
    send_packet(packet)

# --- Generate verification code ---
def generate_verification_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# --- Create button ---
def create_button(click_id: int, style: int, L: int, T: int, W: int, H: int, text: str, ucid: int, req_i_counter: list):
    req_i = req_i_counter[0]
    req_i_counter[0] += 1
    if req_i_counter[0] > 255: req_i_counter[0] = 1
    
    if len(text) > 240: text = text[:237] + "..."
    text_bytes = text.encode('latin-1')
    
    text_len = len(text_bytes)
    padding = (4 - ((12 + text_len) % 4)) % 4
    padded_text = text_bytes + (b'\x00' * padding)
    
    total_size = 12 + len(padded_text)
    
    packet = struct.pack(
        f'<BBBBBBBBBBBB{len(padded_text)}s',
        total_size // 4, 45, req_i, ucid,
        click_id, 0, style, 0,
        L, T, W, H, padded_text
    )
    send_packet(packet)
    return req_i

# --- Button menu ---
def create_menu_buttons(ucid: int, current_cmd: str, start_y: int, req_i_counter: list):
    buttons = [
        ("!rank", get_msg('btn_rank', ucid), 200),
        ("!topwins", get_msg('btn_topwins', ucid), 201),
        ("!topcars", get_msg('btn_topcars', ucid), 202),
        ("!mypb", get_msg('btn_mypb', ucid), 203),
        ("!sr", get_msg('btn_sr', ucid), 204),
        ("!teams", get_msg('btn_teams', ucid), 205),
        ("!nations", get_msg('btn_nations', ucid), 206)
    ]
    req_is = {}
    
    # Grid Layout: 4 Columns
    cols = 4
    col_width = 25
    y = start_y
    base_x = 10 # Matches table start
    
    for i, (cmd, text, click_id) in enumerate(buttons):
        if cmd == current_cmd: continue
        
        row = i // cols
        col = i % cols
        
        x = base_x + (col * col_width)
        btn_y = y + (row * 5)
        
        # Style: LIGHT + CLICK + UNSELECTED
        style = ISB_LIGHT | ISB_CLICK | ISB_COLOR_UNSELECTED
        req_i = create_button(click_id, style, x, btn_y, col_width - 1, 4, text, ucid, req_i_counter)
        req_is[cmd] = req_i
    
    MENU_BUTTONS_REQ_I[ucid] = req_is

# --- Table with menu ---
def display_table_with_menu(ucid: int, title: str, headers: List[str], data: List[List[str]], source_cmd: str, page: int = 1, total_pages: int = 1):
    clear_table(ucid)
    time.sleep(0.05)
    
    req_i_counter = [1]
    
    base_l, table_w, title_w, close_l = 10, 140, 130, 10 + 140 - 8
    bg_height = 8 + (len(data) + 1) * 5 + 25

    # 1. Background: ID 50
    create_button(50, ISB_DARK | ISB_COLOR_UNAVAILABLE, base_l, 70, table_w, bg_height, "", ucid, req_i_counter)
    
    # 2. Title: ID 51
    title_text = f"{title} ^7({page}/{total_pages})" if total_pages > 1 else title
    create_button(51, ISB_DARK | ISB_COLOR_TITLE, base_l + 2, 71, title_w, 4, title_text, ucid, req_i_counter)
    
    # 3. Close Button: ID 52
    close_req_i = create_button(52, ISB_LIGHT | ISB_CLICK | ISB_COLOR_CANCEL, close_l, 71, 6, 4, "[X]", ucid, req_i_counter)
    CLOSE_BUTTON_REQ_I[ucid] = close_req_i

    # Dynamic Column Widths
    # If 4 cols (Track, Car, Pilot, Time), allocate more to Car/Pilot
    # Total width ~136 (140-4).
    # Default: Even split.
    if len(headers) == 4:
         # Standard !sr table: Track(6), Car(30), Pilot(20), Time(15) -> Total ~70chars
         # Weights: 0.1, 0.4, 0.3, 0.2
         col_widths = [int((table_w - 4) * 0.15), int((table_w - 4) * 0.45), int((table_w - 4) * 0.25), int((table_w - 4) * 0.15)]
    else:
         col_width = (table_w - 4) // max(len(headers), 1)
         col_widths = [col_width] * len(headers)

    # 4. Headers: ID 60+
    current_x = base_l + 2
    for i, header in enumerate(headers):
        w = col_widths[i]
        create_button(60 + i, ISB_DARK | ISB_LEFT | ISB_COLOR_STRING, current_x, 76, w - 1, 4, " " + header[:20], ucid, req_i_counter)
        current_x += w

    row_y = 81
    start_id = 100 # Rows start at 100
    for row_idx, row in enumerate(data):
        current_x = base_l + 2
        for col_idx, cell in enumerate(row):
            w = col_widths[col_idx] if col_idx < len(col_widths) else (table_w // len(row))
            # Rough char limit based on width (approx 1.5 chars per unit width? No, button width is virtual units)
            # Just let InSim truncate or use a larger safe limit like 30
            cell_str = str(cell)[:32]
            # 5. Rows: ID 100 + row*10 + col
            create_button(
                start_id + row_idx * 10 + col_idx,
                ISB_DARK | ISB_LEFT | ISB_COLOR_SELECTED | ISB_CLICK,
                current_x,
                row_y + row_idx * 5,
                w - 1, 4, " " + cell_str, ucid, req_i_counter)
            current_x += w


    menu_y = row_y + len(data) * 5 + 5

    # 6. Pagination: ID 53, 54
    if total_pages > 1:
        # Prev (<) - ID 53
        if page > 1:
            create_button(53, ISB_LIGHT | ISB_CLICK | ISB_COLOR_SELECTED, base_l + 2, menu_y, 8, 4, "<", ucid, req_i_counter)
        
        # Next (>) - ID 54
        if page < total_pages:
            create_button(54, ISB_LIGHT | ISB_CLICK | ISB_COLOR_SELECTED, base_l + 12, menu_y, 8, 4, ">", ucid, req_i_counter)
        
        menu_y += 5

    # Save state for interaction
    existing_state = PAGE_STATE.get(ucid, {})
    existing_rows = existing_state.get('rows', []) if existing_state.get('cmd') == source_cmd else []
    
    PAGE_STATE[ucid] = {
        'cmd': source_cmd,
        'page': page,
        'total_pages': total_pages,
        'rows': existing_rows if existing_rows else [
            {'sys_id': i, 'uname': r[1] if len(r) > 1 else ''} 
            for i, r in enumerate(data)
        ] 
    }

    create_menu_buttons(ucid, source_cmd, menu_y, req_i_counter)

# --- Clear buttons ---
def clear_table(ucid: int):
    # Standard IS_BFN (Type 42) SubT 2 (BFN_CLEAR) proved unreliable for ghosts.
    # We switch to explicitly deleting the range 40-250 using SubT 1 (BFN_DEL_BTN).
    
    # We batch these slightly to avoid total socket lockup, but valid packet size (2) is key.
    for i in range(40, 250):
        try:
            # Size=2(8 bytes), Type=42(ISP_BFN), ReqI=0, SubT=1(DEL_BTN), UCID=ucid, ClickID=i...
            send_packet(struct.pack('<BBBBBBBB', 2, 42, 0, 1, ucid, i, 0, 0))
        except: pass
    
    # Clear state tracking
    if ucid in CLOSE_BUTTON_REQ_I: del CLOSE_BUTTON_REQ_I[ucid]
    if ucid in MENU_BUTTONS_REQ_I: del MENU_BUTTONS_REQ_I[ucid]

def force_reset_ui(ucid: int):
    # "Hostile Takeover" of legacy IDs to ensure clearing
    # Robust/Slow clear to prevent Broken Pipe
    send_message(get_msg('ui_reset_wait', ucid), ucid)
    
    # We loop through ALL potential UI IDs (New and Old)
    # Range 40 to 250 covers all used IDs
    for i in range(40, 250):
         # Create 1x1 button off-screen to steal ownership
         try: 
             create_button(i, 0, 0, 0, 1, 1, "", ucid, [1])
             time.sleep(0.002) # Vital delay to prevent socket flood
         except: pass
    
    # Now clear
    clear_table(ucid)
    send_message(get_msg('ui_reset_done', ucid), ucid)

# --- Voting table ---
def display_voting_table(ucid: int):
    clear_table(ucid)
    time.sleep(0.05)
    start_id = 150
    req_i_counter = [1]
    base_l, table_w, title_w, close_l = 10, 120, 110, 10 + 120 - 8

    bg_height = 8 + len(STATE.current_voting_options) * 5 + 10
    
    # Background
    create_button(start_id, ISB_DARK | ISB_COLOR_UNAVAILABLE, base_l, 60, table_w, bg_height, "", ucid, req_i_counter)
    
    # Title (Yellow)
    create_button(start_id + 1, ISB_DARK | ISB_COLOR_TITLE, base_l + 2, 61, title_w, 5, get_msg('vote_title', ucid), ucid, req_i_counter)
    # Calculate time left using END TIME
    with STATE.lock: # Lock to check state
         end_time = getattr(STATE, 'voting_end_time', 0)
         
    time_left = max(0, int(end_time - time.time()))
    # Timer (Pale Blue)
    create_button(start_id + 2, ISB_DARK | ISB_COLOR_STRING, base_l + 2, 67, 30, 4, get_msg('vote_time', ucid, time=time_left), ucid, req_i_counter)

    # Close (Red)
    close_req_i = create_button(199, ISB_LIGHT | ISB_CLICK | ISB_COLOR_CANCEL, close_l, 61, 8, 5, get_msg('close_btn', ucid), ucid, req_i_counter)
    CLOSE_BUTTON_REQ_I[ucid] = close_req_i

    y = 72
    for i, opt in enumerate(STATE.current_voting_options):
        click_id = 240 + i
        # Base style: LIGHT + CLICK + LEFT
        style = ISB_LIGHT | ISB_CLICK | ISB_LEFT | ISB_COLOR_UNSELECTED
        
        # If selected: Change to OK (Green)
        if ucid in STATE.votes and STATE.votes[ucid] == i:
            style = ISB_LIGHT | ISB_CLICK | ISB_LEFT | ISB_COLOR_OK
            
        create_button(click_id, style, base_l + 2, y, table_w - 6, 4, f"{i+1}. {opt['name']}", ucid, req_i_counter)
        y += 5

# --- on_button_click ---
def on_button_click(packet: bytes):
    if len(packet) < 8: return
    _, _, req_i, ucid, click_id, _, _, _ = struct.unpack('<BBBBBBBB', packet)
    
    # Close Button - ID 52 (New) OR ID 199 (Legacy/Ghost)
    if click_id == 52 or click_id == 199:
        if click_id == 199:
            force_reset_ui(ucid) # Use the new function for legacy cleanup
        else:
            clear_table(ucid) # For new buttons, just clear the table
        if ucid in PAGE_STATE: del PAGE_STATE[ucid]
        return
        
    # Visual Voting Menu
    if 240 <= click_id <= 245:
        if STATE.voting_end_time > 0:
            opt = click_id - 240
            STATE.votes[ucid] = opt
            uname = STATE.current_race['players'].get(ucid, {}).get('uname', 'Alguien')
            send_message(f"^3{uname}^7 voted for option {opt+1}")
        return

    # Pagination - IDs 53, 54 OR 180, 181 (Legacy)
    if click_id in [53, 54]:
        state = PAGE_STATE.get(ucid)
        if state:
            new_page = state['page']
            if click_id == 53: new_page -= 1 # Prev
            elif click_id == 54: new_page += 1 # Next
            
            if 1 <= new_page <= state['total_pages']:
                 cmd = state['cmd']
                 args = state.get('args', [])
                 if cmd == "!rank": show_rank(ucid, new_page)
                 elif cmd == "!topwins": show_topwins(ucid, new_page)
                 elif cmd == "!team": teams_list(ucid, new_page)
                 elif cmd == "!sr": show_records(ucid, new_page)
                 elif cmd == "!teams": show_teams(ucid, new_page)
                 elif cmd == "!nations": show_nations(ucid, new_page)
                 elif cmd == "!help": cmd_help(ucid, new_page)
        return

    # Bottom Menu Buttons - IDs 200-206
    if 200 <= click_id <= 206:
        if click_id == 200: show_rank(ucid)
        elif click_id == 201: show_topwins(ucid)
        elif click_id == 202: show_topcars(ucid)
        elif click_id == 203: cmd_pb(ucid, [])
        elif click_id == 204: cmd_wr(ucid, [])
        elif click_id == 205: show_teams(ucid)
        elif click_id == 206: show_nations(ucid)
        return

    # Interaction Logic for Tables - IDs 100-239
    # NOTE: Legacy IDs (110-200) overlap with New IDs.
    # This is fine as we want to handle clicks on both if they map to rows.
    if 100 <= click_id < 240: # Table Row Clicks
        row_idx = (click_id - 100) // 10
        # Check for legacy mapping?
        # Legacy: row 0 starts at 110. New: row 0 starts at 100.
        # If we see ID 110: It could be New Row 1 OR Legacy Row 0.
        # We assume New ID scheme is active.
        
        col_idx = (click_id - 100) % 10
        
        state = PAGE_STATE.get(ucid)
        
        if state and state.get('cmd') == '!badcombo':
            handle_badcombo_click(ucid, click_id)
            return

        logging.info(f"TABLE CLICK: ucid={ucid} click_id={click_id} row={row_idx} col={col_idx} cmd={state.get('cmd') if state else 'None'}")

        if state and 'rows' in state and row_idx < len(state['rows']):
            target_data = state['rows'][row_idx]
            target_uname = target_data.get('uname')
            uname = STATE.current_race['players'].get(ucid, {}).get('uname')
            
            logging.info(f"ACTION TARGET: {target_uname} | Leader: {state.get('is_leader')}")

            if state['cmd'] == '!team info' and state.get('is_leader'):
                 if col_idx == 2: # Kick
                     team_kick(ucid, uname, [target_uname])
                     team_info(ucid, uname) # Refresh
                 elif col_idx == 3: # Promote
                     team_promote(ucid, uname, [target_uname])
                     team_info(ucid, uname) # Refresh
            
            elif state['cmd'] == '!team pending':
                 if col_idx == 2: # Accept
                     team_accept(ucid, uname, [target_uname])
                     team_pending(ucid, uname) # Refresh
                 elif col_idx == 3: # Decline
                     team_decline(ucid, uname, [target_uname])
                     team_pending(ucid, uname) # Refresh
            
            elif state['cmd'] == '!team_menu':
                action_id = target_data.get('id')
                if action_id == 'team_info': team_info(ucid, uname)
                elif action_id == 'team_pending': team_pending(ucid, uname)
                elif action_id == 'team_leave': team_leave(ucid, uname)
                elif action_id == 'team_create': send_message(get_msg('team_create_usage', ucid), ucid)
                elif action_id == 'team_join': send_message(get_msg('team_usage_join', ucid), ucid)
                
            elif state['cmd'] == '!register':
                if target_data.get('id') == 'server':
                    cmd_register(ucid, ['server'])
                    
            elif state['cmd'].startswith('!admin'):
                if col_idx == 2: # ACTION button
                    action_id = target_data.get('id')
                    uname = STATE.current_race['players'].get(ucid, {}).get('uname', 'Server') # Re-fetch to be safe
                    # Verify admin again just in case
                    if not is_admin(uname, ucid): return 
                    
                    if state['cmd'] == '!admin':
                        if action_id == 'menu_control': show_admin_control(ucid)
                        elif action_id == 'menu_rotation': show_admin_rotation(ucid)
                        elif action_id == 'menu_multiclass': show_admin_multiclass(ucid)
                        elif action_id == 'menu_categories': show_admin_categories(ucid)
                        elif action_id == 'toggle_mods':
                            with STATE.lock:
                                 STATE.config['allow_mods'] = not STATE.config.get('allow_mods', True)
                                 save_live_data()
                                 sync_config_to_api()
                            show_admin_menu(ucid)
                        elif action_id == 'reset_cars':
                            with STATE.lock:
                                STATE.allowed_cars_filter = None
                            send_message(get_msg('setcars_reset', ucid), ucid)
                            show_admin_menu(ucid)
                        elif action_id == 'abort_vote':
                            with STATE.lock:
                                if getattr(STATE, 'voting_active', False):
                                    if STATE.voting_timer: STATE.voting_timer.cancel()
                                    STATE.voting_active = False
                                    send_message("^1Admin aborted the vote.", 0)
                            show_admin_menu(ucid)

                    elif state['cmd'] == '!admin_control':
                        if action_id == 'start': send_message("/start")
                        elif action_id == 'restart': send_message("/restart")
                        elif action_id == 'end': send_message("/end")
                        elif action_id == 'force_vote':
                            with STATE.lock:
                                 STATE.current_voting_options = generate_random_voting_options()
                            import threading
                            threading.Thread(target=start_voting, daemon=True).start()
                        elif action_id == 'back': show_admin_menu(ucid)

                    elif state['cmd'] == '!admin_rotation':
                        if action_id == 'random': admin_random_command(ucid, uname)
                        elif action_id == 'random_std': admin_random_command(ucid, uname, ['std'])
                        elif action_id == 'random_mods': admin_random_command(ucid, uname, ['mods'])
                        elif action_id == 'back': show_admin_menu(ucid)

                    elif state['cmd'] == '!admin_multiclass':
                        with STATE.lock:
                            if action_id == 'mc_1': STATE.config['max_multi_class'] = 1
                            elif action_id == 'mc_2': STATE.config['max_multi_class'] = 2
                            elif action_id == 'mc_3': STATE.config['max_multi_class'] = 3
                            elif action_id == 'mc_4': STATE.config['max_multi_class'] = 4
                            elif action_id == 'toggle_fixed':
                                STATE.config['multi_class_fixed'] = not STATE.config.get('multi_class_fixed', False)
                            
                            if action_id != 'back':
                                save_live_data()
                                sync_config_to_api()
                        
                        if action_id == 'back': show_admin_menu(ucid)
                        else: show_admin_multiclass(ucid)

                    elif state['cmd'] == '!admin_categories':
                        with STATE.lock:
                            allowed = STATE.config.get('allowed_classes', [])
                            
                            if action_id.startswith('toggle_cat_'):
                                cat = target_data['cat']
                                if not allowed:
                                    # If empty, all are allowed. Let's populate it with everything EXCEPT the toggled one
                                    cats = ['GTI', 'TBO', 'GTR', 'U17', 'LRF', 'UF1', 'FZ5', 'MRT', 'FBM', 'FOX', 'FO8', 'BF1']
                                    cats.remove(cat)
                                    STATE.config['allowed_classes'] = cats
                                else:
                                    if cat in allowed: allowed.remove(cat)
                                    else: allowed.append(cat)
                                    STATE.config['allowed_classes'] = allowed
                            elif action_id == 'allow_all':
                                STATE.config['allowed_classes'] = [] # Empty means all
                                
                            if action_id != 'back':
                                save_live_data()
                                sync_config_to_api()
                        
                        if action_id == 'back': show_admin_menu(ucid)
                        else: show_admin_categories(ucid)
            
            elif state['cmd'] == '!badcombo':
                 if col_idx == 2: # REPORT button
                     reason_id = target_data.get('id')
                     reason_name = target_data.get('name')
                     
                     # Get current state
                     c_track = STATE.previous_track
                     c_cars = STATE.previous_allowed_cars
                     # Determine car name/class string
                     c_class_name = "Unknown"
                     # Try to reverse lookup or use generated name potentially?
                     # For now, store the raw code or name from config if available?
                     # STATE doesn't store full config object, only track/cars code.
                     # We can try to use STATE.current_race info if running, or just store code.
                     
                     # Better: Let's store simple string for now.
                     c_car_str = str(c_cars)
                     
                     # Environment (Time/Weather) - Not strictly tracked in STATE globally easily
                     # We might need to fetch it or rely on what we set.
                     # For now, store 0/0 and rely on track/car primarily.
                     
                     conn = get_db_connection()
                     if conn:
                         try:
                             with conn.cursor() as c:
                                 c.execute("""
                                     INSERT INTO config_reports (track, car_class, reason, reporter, reporter_ucid)
                                     VALUES (%s, %s, %s, %s, %s)
                                 """, (c_track, c_car_str, reason_name, uname, ucid))
                                 conn.commit()
                             send_message(f"^3Report Submitted: ^2{reason_name}", ucid)
                             logging.info(f"REPORT: {uname} reported {c_track}/{c_car_str} for {reason_name}")
                             clear_table(ucid) # Close menu on submit
                             del PAGE_STATE[ucid]
                         except Exception as e:
                             logging.error(f"Failed to save report: {e}")
                             send_message("^1Error saving report.", ucid)
                         finally:
                             conn.close()
                             
        return

    # Menu Buttons
    if ucid in MENU_BUTTONS_REQ_I:
        for cmd, btn_req_i in MENU_BUTTONS_REQ_I[ucid].items():
            if req_i == btn_req_i:
                clear_table(ucid)
                time.sleep(0.1)
                uname = STATE.current_race['players'].get(ucid, {}).get('uname', '')
                if cmd == "!rank": show_rank(ucid)
                elif cmd == "!topwins": show_topwins(ucid)
                elif cmd == "!topcars": show_topcars(ucid)
                elif cmd == "!mypb": cmd_pb(ucid, [])
                elif cmd == "!sr": cmd_wr(ucid, [])
                elif cmd == "!teams": show_teams(ucid)
                elif cmd == "!nations": show_nations(ucid)
                return
    with STATE.lock:
        if STATE.voting_active and 210 <= click_id < 210 + len(STATE.current_voting_options):
            option_idx = click_id - 210
            STATE.votes[ucid] = option_idx
            send_message(get_msg('vote_registered', ucid), ucid)
            display_voting_table(ucid)
            if len(STATE.votes) >= len(STATE.current_race['players']):
                if hasattr(STATE, 'voting_timer') and STATE.voting_timer:
                     STATE.voting_timer.cancel()
                import threading
                threading.Thread(target=end_voting, daemon=True).start()

# --- Table Commands ---
def show_stats(ucid: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            c.execute("SELECT COUNT(*) as total_players, AVG(elo) as avg_elo FROM players")
            player_stats = c.fetchone()
            c.execute("SELECT COUNT(*) as total_races FROM races")
            race_stats = c.fetchone()
            headers = [get_msg('stats_title', ucid), get_msg('stats_players', ucid)]
            data = [
                [get_msg('stats_players', ucid), player_stats['total_players']],
                [get_msg('stats_avg_elo', ucid), round(player_stats['avg_elo'] or 0)],
                [get_msg('stats_races', ucid), race_stats['total_races']],
            ]
        display_table_with_menu(ucid, get_msg('stats_title', ucid), headers, data, "!stats")
    finally:
        conn.close()

def show_rank(ucid: int, page: int = 1):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            # Count Total
            c.execute("SELECT COUNT(*) as count FROM players")
            total = c.fetchone()['count']
            limit = 10
            total_pages = math.ceil(total / limit)
            offset = (page - 1) * limit
            
            c.execute("SELECT uname, elo, wins FROM players ORDER BY elo DESC LIMIT %s OFFSET %s", (limit, offset))
            players = c.fetchall()
            headers = [get_msg('header_pos', ucid), 
                       get_msg('header_player', ucid), 
                       get_msg('header_elo', ucid), 
                       get_msg('header_wins', ucid)]
            data = [[offset + i + 1, p['uname'], p['elo'], p['wins']] for i, p in enumerate(players)]
            
            PAGE_STATE[ucid] = {'cmd': '!rank', 'page': page, 'total_pages': total_pages}
            display_table_with_menu(ucid, get_msg('rank_title', ucid), headers, data, "!rank", page, total_pages)
    finally:
        conn.close()

def show_topwins(ucid: int, page: int = 1):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            c.execute("SELECT COUNT(*) as count FROM players WHERE wins > 0")
            total = c.fetchone()['count']
            limit = 10
            total_pages = math.ceil(total / limit)
            offset = (page - 1) * limit
            
            c.execute("SELECT uname, wins FROM players ORDER BY wins DESC, elo DESC LIMIT %s OFFSET %s", (limit, offset))
            players = c.fetchall()
            headers = [get_msg('rank_pos', ucid), get_msg('rank_player', ucid), get_msg('rank_wins', ucid)]
            data = [[offset + i + 1, p['uname'], p['wins']] for i, p in enumerate(players)]
            
            PAGE_STATE[ucid] = {'cmd': '!topwins', 'page': page, 'total_pages': total_pages}
            display_table_with_menu(ucid, get_msg('topwins_title', ucid), headers, data, "!topwins", page, total_pages)
    finally:
        conn.close()

def fetch_api_json(endpoint: str, params: Dict = None, use_cache: bool = True) -> Any:
    key = None
    if use_cache:
        # Create a cache key based on endpoint and sorted params
        param_str = ""
        if params:
            param_str = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
        key = f"{endpoint}?{param_str}"
        
        if key in STATE.api_cache:
            return STATE.api_cache[key]

    try:
        base_url = "https://lfsrank.com/api/" 
        if not base_url.endswith('/'): base_url += '/'
        
        # Use urllib.parse.urlencode for safety, though manual join was here before
        query = ""
        if params:
            # simple join to match previous logic, or upgrade to urlencode if desired
            # keeping it simple as per original to avoid imports if not present (though urllib.parse is standard)
            query = "?" + "&".join([f"{k}={v}" for k, v in params.items()])
            
        url = f"{base_url}{endpoint}{query}"
        # logging.info(f"API Fetch: {url}")
        
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.load(response)
            if data.get('status') == 'success':
                if use_cache and key:
                    STATE.api_cache[key] = data
                return data
    except Exception as e:
        logging.error(f"API Error ({endpoint}): {e}")
    return None

def show_topcars(ucid: int):
    # Try DB first
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                c.execute("SELECT car, COUNT(*) as uses FROM player_race_stats WHERE car != '' GROUP BY car ORDER BY uses DESC LIMIT 5")
                rows = c.fetchall()
                data = [[i+1, r['car'], r['uses']] for i, r in enumerate(rows)]
                
                headers = [get_msg('rank_pos', ucid), get_msg('topcars_car', ucid), get_msg('topcars_uses', ucid)]
                display_table_with_menu(ucid, get_msg('topcars_title', ucid), headers, data, "!topcars")
                return
        except Exception as e:
            logging.error(f"DB TopCars Error: {e}")
        finally:
            conn.close()

    # Fallback / Lite Mode
    resp = fetch_api_json('stats_global.php')
    if resp and 'stats' in resp and 'top_cars' in resp['stats']:
        top_cars = resp['stats']['top_cars'] # List of {car, uses}
        headers = [get_msg('rank_pos', ucid), get_msg('topcars_car', ucid), get_msg('topcars_uses', ucid)]
        data = [[i+1, c['car'], c['uses']] for i, c in enumerate(top_cars[:5])]
        display_table_with_menu(ucid, get_msg('topcars_title', ucid), headers, data, "!topcars")
    else:
        send_message(get_msg('stats_not_found', ucid), ucid)

def show_elo(ucid: int, uname: str):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                c.execute("SELECT elo FROM players WHERE uname = %s", (uname,))
                elo = (c.fetchone() or {}).get('elo', 1500)
            send_message(get_msg('elo_msg', ucid, uname=uname, elo=elo), ucid)
            return
        except: pass
        finally: conn.close()
    
    # API Fallback
    resp = fetch_api_json('api_player.php', {'uname': uname})
    if resp and 'player' in resp:
        elo = resp['player'].get('elo', 1500)
        send_message(get_msg('elo_msg', ucid, uname=uname, elo=elo), ucid)
    else:
         send_message(get_msg('user_unknown', ucid), ucid)



# --- MOD COMMANDS ---
def cmd_mods(ucid: int, args: List[str]):
    if not STATE.mods:
        return send_message(get_msg('err_no_mods', ucid, default="No mods configured."), ucid)
    
    page = 1
    if args and args[0].isdigit(): page = int(args[0])
    
    # Show list of mods (paginated)
    mods_with_id = [m for m in STATE.mods if m.get('id')]
    if not mods_with_id:
         return send_message(get_msg('err_no_mods_id', ucid, default="Mods configured but no IDs set."), ucid)
         
    limit = 15
    total = len(mods_with_id)
    total_pages = math.ceil(total / limit)
    page = max(1, min(page, total_pages))
    
    start = (page - 1) * limit
    page_items = mods_with_id[start:start+limit]
    
    lines = [f"^3Mods Page {page}/{total_pages}:"]
    for m in page_items:
        lines.append(f"^7{m['name']} (^2{m['id']}^7)")
        
    msg = "\n".join(lines)
    send_message(msg, ucid)

def cmd_setmod(ucid: int, uname: str, args: List[str]):
    if not is_admin(uname):
        return send_message(get_msg('err_no_admin', ucid), ucid)
        
    if not args:
        return send_message("^7Usage: !setmod <Mod Name | Mod ID>", ucid)
        
    query = " ".join(args).upper()
    target_id = None
    
    # Check if query matches an ID directly (6 hex chars)
    if len(query) == 6 and all(c in string.hexdigits for c in query):
        target_id = query
    elif query in STATE.mod_map:
        target_id = STATE.mod_map[query]
    else:
        # Partial search
        for m in STATE.mods:
            if m.get('id') and query in m['name'].upper():
                 target_id = m['id']
                 break
    
    if target_id:
        with STATE.lock:
            # We treat this as an 'Admin Override' similar to setcars, but for a mod.
            # We can't mix Mods + Official cars easily via ACI packet without InSim 9 logic, 
            # so we use /allowmod which restricts to THAT mod only usually?
            # Actually /allowmod adds to allowed list?
            # User wants to set the server to this mod.
            STATE.allowed_cars_filter = 0 # 0 usually means 'any' in bitmask logic, but we need to signal 'MOD'
            # We probably need a separate state for 'Current Mod'.
            # But for simplicity, let's just execute the command.
            pass
            
        send_message(f"/allowmod {target_id}")
        send_message(f"^2Mod allowed: {target_id}")
    else:
        send_message("^1Mod not found.", ucid)

# --- TEAM COMMANDS ---
def show_team_menu(ucid: int, uname: str):
    res = send_to_api('get_team_info', {'uname': uname})
    
    actions = []
    if res and res.get('status') == 'success':
        team = res.get('team', {})
        is_leader = False
        members = team.get('members_data', [])
        for m in members:
            if m.get('uname') == uname and m.get('role') in ['jefe', 'admin']:
                is_leader = True
                
        actions.append({'id': 'team_info', 'name': get_msg('team_btn_info', ucid), 'desc': get_msg('team_desc_info', ucid)})
        if is_leader:
            actions.append({'id': 'team_pending', 'name': get_msg('team_btn_pending', ucid), 'desc': get_msg('team_desc_pending', ucid)})
        actions.append({'id': 'team_leave', 'name': get_msg('team_btn_leave', ucid), 'desc': get_msg('team_desc_leave', ucid)})
    else:
        actions.append({'id': 'team_create', 'name': get_msg('team_btn_create', ucid), 'desc': get_msg('team_create_usage', ucid)})
        actions.append({'id': 'team_join', 'name': get_msg('team_btn_join', ucid), 'desc': get_msg('team_usage_join', ucid)})
        
    headers = [get_msg('adm_action', ucid), get_msg('cmd_desc', ucid), get_msg('adm_open', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_open', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!team_menu', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('team_menu_title', ucid), headers, data, "!team_menu")

def team_create(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_create_usage', ucid), ucid)
    name = " ".join(args).strip()
    if len(name) > 30:
        return send_message(get_msg('team_name_len', ucid), ucid)
    
    res = send_to_api('team_create', {'uname': uname, 'name': name})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_created', ucid, name=res.get('name'), id=res.get('team_id')), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_request_join(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_usage_join', ucid), ucid)
    try:
        team_id = int(args[0])
    except:
        return send_message(get_msg('invalid_id', ucid), ucid)

    res = send_to_api('team_request_join', {'uname': uname, 'team_id': team_id})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_request_sent', ucid, name=res.get('name')), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_accept(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_usage_accept', ucid), ucid)
    target_uname = args[0]
    
    res = send_to_api('team_accept', {'uname': uname, 'target_uname': target_uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_accepted', ucid, user=target_uname), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_kick(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_usage_kick', ucid), ucid)
    target_uname = args[0]
    
    res = send_to_api('team_kick', {'uname': uname, 'target_uname': target_uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_kicked', ucid, user=target_uname), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_decline(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_usage_decline', ucid), ucid)
    target_uname = args[0]
    
    res = send_to_api('team_decline', {'uname': uname, 'target_uname': target_uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_declined', ucid, user=target_uname), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_promote(ucid: int, uname: str, args: List[str]):
    if len(args) < 1:
        return send_message(get_msg('team_usage_promote', ucid), ucid)
    target_uname = args[0]
    
    res = send_to_api('team_promote', {'uname': uname, 'target_uname': target_uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_promoted', ucid, user=target_uname), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_pending(ucid: int, uname: str):
    res = send_to_api('get_team_pending', {'uname': uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') != 'success':
        msg_key = res.get('message', 'api_error')
        return send_message(get_msg(msg_key, ucid), ucid)
        
    requests = res.get('requests', [])
    if not requests:
        return send_message(get_msg('no_pending_requests', ucid), ucid)
        
    headers = [get_msg('header_player', ucid), get_msg('header_date', ucid), get_msg('btn_accept', ucid), get_msg('btn_decline', ucid)]
    data = []
    rows_context = []
    for r in requests:
        date_str = str(r.get('created_at', ''))[:10]
        data.append([f"^2{r['uname']}", f"^7{date_str}", f"^2[{get_msg('btn_accept', ucid).upper()}]", f"^1[{get_msg('btn_decline', ucid).upper()}]"])
        rows_context.append({'uname': r['uname']})
        
    PAGE_STATE[ucid] = {'cmd': '!team pending', 'page': 1, 'total_pages': 1, 'rows': rows_context, 'is_leader': True}
    display_table_with_menu(ucid, get_msg('team_pending_title', ucid), headers, data, "!team pending")

def team_leave(ucid: int, uname: str):
    res = send_to_api('team_leave', {'uname': uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') == 'success':
        send_message(get_msg('team_left', ucid), ucid)
    else:
        msg_key = res.get('message', 'api_error')
        send_message(get_msg(msg_key, ucid), ucid)

def team_info(ucid: int, uname: str):
    res = send_to_api('get_team_info', {'uname': uname})
    if not res: return send_message(get_msg('api_error', ucid), ucid)
    
    if res.get('status') != 'success':
        msg_key = res.get('message', 'api_error')
        return send_message(get_msg(msg_key, ucid), ucid)
        
    team = res.get('team', {})
    members = team.get('members_data', [])
    
    is_viewer_leader = False
    for m in members:
        if m['uname'] == uname and m['role'] in ['jefe', 'admin']:
            is_viewer_leader = True

    title = f"^3[TEAM] ^7{team['name']} ^3- {team['points']} PTS"
    headers = [get_msg('header_player', ucid), get_msg('header_role', ucid)]
    if is_viewer_leader:
        headers.extend([get_msg('btn_kick', ucid), get_msg('btn_promote', ucid)])
        
    data = []
    rows_context = []
    for m in members:
        row = [f"^2{m['uname']}", f"^7{m['role']}"]
        if is_viewer_leader:
            if m['uname'] != uname:
                row.extend([f"^1[{get_msg('btn_kick', ucid).upper()}]", f"^3[{get_msg('btn_promote', ucid).upper()}]"])
            else:
                row.extend(["", ""])
        data.append(row)
        rows_context.append({'uname': m['uname']})
        
    PAGE_STATE[ucid] = {'cmd': '!team info', 'page': 1, 'total_pages': 1, 'rows': rows_context, 'is_leader': is_viewer_leader}
    display_table_with_menu(ucid, title, headers, data, "!team info")

def teams_list(ucid: int, page: int = 1):
    res = fetch_api_json('get_rankings', {'type': 'teams', 'limit': 10, 'offset': (page-1)*10}, use_cache=False)
    if not res or res.get('status') != 'success':
        return send_message(get_msg('api_error', ucid), ucid)
        
    teams = res.get('rankings', [])
    total = res.get('count', 0)
    
    if not teams:
        return send_message(get_msg('no_teams', ucid), ucid)
        
    limit = 10
    total_pages = math.ceil(total / limit) if total > 0 else 1
    
    headers = ["^3ID", get_msg('header_name', ucid), get_msg('header_points', ucid), get_msg('header_members_short', ucid)]
    data = []
    for t in teams:
        data.append([f"^1{t.get('team_id', '')}", f"^2{t.get('name', '')}", f"^3{t.get('total_wins', 0)}", f"^7{t.get('member_count', 0)}"])
        
    PAGE_STATE[ucid] = {'cmd': '!team', 'page': page, 'total_pages': total_pages}
    display_table_with_menu(ucid, get_msg('teams_title', ucid), headers, data, "!team", page, total_pages)

# --- COMMAND HANDLER ---
def cmd_help(ucid: int, page: int = 1):
    lang = 'es'
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            lang = STATE.current_race['players'][ucid].get('language', 'es')
    
    t = TRANSLATIONS.get(lang, TRANSLATIONS['es'])
    headers = [get_msg('cmd_cmd', ucid), get_msg('cmd_desc', ucid)]
    
    # Define capabilities with Key to check config
    # Format: [CmdStr, DescKey, ConfigKey]
    caps = [
        ["!stats", 'desc_stats', 'stats'],
        ["!rank", 'desc_rank', 'stats'],
        ["!top", 'desc_top', 'stats'],
        ["!topwins", 'desc_topwins', 'stats'],
        ["!topcars", 'desc_topcars', 'stats'],
        ["!pb", 'desc_pb', 'stats'],
        ["!sr", 'desc_wr', 'stats'],
        ["!tb", 'desc_tb', 'stats'],
        ["!elo", 'desc_elo', 'stats'],
        ["!team", 'desc_team', 'teams'],
        ["!teams", 'desc_teams', 'teams'],
        ["!nations", 'desc_nations', 'teams'],
        ["!vote", 'desc_vote', 'voting'],
        ["!register", 'desc_reg', 'register'],
        ["!lang", 'desc_lang', 'help'],
        ["!resetui", 'desc_resetui', 'help'],
        ["!mods", 'desc_mods', 'help'],
        ["!random", 'desc_random', 'help'],
        ["!allcars", 'desc_allcars', 'help'],
        ["!admin", 'desc_admin', 'help'],
        ["!badcombo", 'desc_badcombo', 'voting']
    ]
    
    data = []
    for c_str, d_key, cfg_key in caps:
        # Check enabled
        if cfg_key:
             is_enabled = STATE.config.get(cfg_key, True)
             if isinstance(is_enabled, str) and is_enabled.lower() in ['0', 'false', 'off']: is_enabled = False
             if is_enabled is False or is_enabled == 0: continue
        
        data.append([f"^2{c_str}", t.get(d_key, "Desc")])

    limit = 10
    total_items = len(data)
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    data = data[start_idx:end_idx]

    display_table_with_menu(ucid, t['help_title'], headers, data, "!help", page, total_pages)


def preload_rankings_loop():
    """Background task to fetch top 500 rankings periodically for local speed."""
    while True:
        try:
            # logging.info("Preloading bookings (Top 500)...")
            data = fetch_api_json("rankings.php", {'limit': 500, 'offset': 0}, use_cache=False)
            if data and 'rankings' in data:
                with STATE.lock:
                    STATE.preloaded_rankings = data['rankings']
                # logging.info(f"Preloaded {len(STATE.preloaded_rankings)} rankings.")
        except Exception as e:
            logging.error(f"Preload Error: {e}")
        
        time.sleep(300)  # Every 5 minutes

def fetch_rankings_api(page: int, limit: int = 15) -> List[Dict]:
    """Helper to fetch rankings from API when DB is not available."""
    # Try preloaded first
    offset = (page - 1) * limit
    with STATE.lock:
        if STATE.preloaded_rankings and len(STATE.preloaded_rankings) > offset:
            # We have at least some data for this page locally
            # If the page extends beyond what we have, we might return partial or need to fetch
            # But usually folks look at top pages.
            end = offset + limit
            if end <= len(STATE.preloaded_rankings):
                # We have the full page locally!
                return STATE.preloaded_rankings[offset:end]

    try:
        offset = (page - 1) * limit
        base_url = "https://lfsrank.com/api/" # http://.../api
        url = f"{base_url}/rankings.php?limit={limit}&offset={offset}"
        
        # Use existing cache for these dedicated calls too
        return fetch_api_json("rankings.php", {'limit': limit, 'offset': offset}).get('rankings', [])
    except Exception as e:
        logging.error(f"API Rank Fetch Error: {e}")
    return []
    params = {'limit': limit, 'offset': (page - 1) * limit}
    data = fetch_api_json('rankings.php', params)
    if data and 'rankings' in data:
        return data['rankings']
    return []

def cmd_rank(ucid: int, args: List[str]):
    page = 1
    if args and args[0].isdigit():
        page = int(args[0])
    
    limit = 15
    offset = (page - 1) * limit
    
    headers = [get_msg('rank_header_pos', ucid), get_msg('rank_header_pilot', ucid), get_msg('rank_header_elo', ucid), get_msg('rank_header_wins', ucid)]
    data = []

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                c.execute("SELECT uname, elo, wins FROM players ORDER BY elo DESC LIMIT %s OFFSET %s", (limit, offset))
                rows = c.fetchall()
        except Exception as e:
            logging.error(f"Error in cmd_rank DB: {e}")
            rows = []
        finally:
            conn.close()
    else:
        # Fallback to API
        rows = fetch_rankings_api(page, limit)

    # Process rows (common for both DB and API results)
    for i, r in enumerate(rows):
        # API might return different keys? JSON from API: uname, elo, wins. Matches.
        # DB row: uname, elo, wins. Matches.
        data.append([str(offset + i + 1), r['uname'], str(r['elo']), str(r['wins'])])
    
    if not data and not conn:
        # Only show error if both failed
        send_message(get_msg('db_error', ucid) + " / API Error", ucid)
        return

    display_table_with_menu(ucid, f"Global Ranking (Page {page})", headers, data, f"!rank {page}")

def cmd_topwins(ucid: int):
    headers = [get_msg('topwins_header_pos', ucid), get_msg('topwins_header_pilot', ucid), get_msg('topwins_header_wins', ucid)]
    data = []

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                c.execute("SELECT uname, wins FROM players ORDER BY wins DESC LIMIT 15")
                rows = c.fetchall()
                for i, r in enumerate(rows):
                    data.append([str(i+1), r['uname'], str(r['wins'])])
        except Exception as e:
            logging.error(f"DB TopWins Error: {e}")
        finally:
            conn.close()
    
    if not data:
        # API Fallback
        resp = fetch_api_json('rankings.php', {'sort': 'wins', 'limit': 15})
        if resp and 'rankings' in resp:
            for i, r in enumerate(resp['rankings']):
                data.append([str(i+1), r['uname'], str(r['wins'])])
                
    if data:
        display_table_with_menu(ucid, "Top Victorias", headers, data, "!topwins")
    else:
        send_message(get_msg('db_error', ucid) + " / API Error", ucid)

def cmd_me(ucid: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            with STATE.lock:
                uname = STATE.current_race['players'].get(ucid, {}).get('uname')
            
            if not uname: return
            
            c.execute("SELECT elo, wins, races_completed, total_laps, total_distance FROM players WHERE uname = %s", (uname,))
            r = c.fetchone()
            
            if r:
                msg = f"^3Stats de {uname}:^7\nELO: ^2{r['elo']}^7 | Wins: ^2{r['wins']}^7 | Carreras: ^2{r['races_completed']}^7"
                send_message(msg, ucid)
                msg2 = f"Laps: ^2{r['total_laps']}^7 | Dist: ^2{r['total_distance']:.1f} km"
                send_message(msg2, ucid)
            else:
                send_message(get_msg('stats_not_found', ucid), ucid)
    finally:
        conn.close()

def cmd_allcars(ucid: int):
    logging.info("ACTIVATING ALL CARS + MODS")
    send_message("/cars all")
    send_message("/mid 1") # Enable Mod Support Check
    
    count = 0
    for m in STATE.mods:
        if m.get('id'):
            send_message(f"/allowmod {m['id']}")
            count += 1
            time.sleep(0.1) # Prevent flooding
            
    send_message(f"^2All standard cars and {count} mods allowed!")

def cmd_list_mods(ucid: int):
    msg = "^3Mods Configurados: "
    for m in STATE.mods:
        msg += f"^7{m['name']}, "
    send_message(msg[:-2], ucid)

def cmd_setmod(ucid: int, args: List[str]):
    if not args: return send_message("^1Uso: !setmod <ModID/Nombre>", ucid)
    query = " ".join(args).upper()
    
    mod_id = None
    # 1. Search by exact ID in map
    if query in STATE.mod_map:
        mod_id = query
    elif query in STATE.mod_map.values():
        # Iterate to find ID (slow but fine)
        for mid, name in STATE.mod_map.items():
            if name == query:
                mod_id = mid
                break
    
    # 2. Search by fuzzy name in STATE.mods
    if not mod_id:
        for m in STATE.mods:
            if m['name'].upper() == query or m['id'] == query:
                mod_id = m['id']
                break
    
    # 3. If raw ID provided (6 chars hex)
    if not mod_id and len(query) == 6:
        mod_id = query
        
    if mod_id:
        send_message(f"/allowmod {mod_id}")
        send_message(f"^2Mod {mod_id} permitido.")
    else:
        send_message("^1Mod no encontrado.")

def cmd_lang(ucid: int, args: List[str]):
    logging.info(f"DEBUG: cmd_lang called for UCID {ucid} with args: {args}")

    if not args:
        return send_message(get_msg('lang_usage', ucid), ucid)
    
    new_lang = args[0].lower()
    if new_lang not in ['es', 'en']:
        return send_message(get_msg('lang_options', ucid), ucid)
    
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as c:
            with STATE.lock:
                if ucid in STATE.current_race['players']:
                    uname = STATE.current_race['players'][ucid]['uname']
                    STATE.current_race['players'][ucid]['language'] = new_lang
                    c.execute("UPDATE players SET language = %s WHERE uname = %s", (new_lang, uname))
                    conn.commit()
                    send_message(get_msg('lang_set', ucid), ucid)
                else:
                    send_message("^1Error: No te encuentro en la lista de jugadores. ^7Reconecta para arreglarlo.", ucid)
    finally:
        conn.close()

def cmd_top(ucid: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            with STATE.lock:
                player = STATE.current_race['players'].get(ucid)
                current_car = player['car'] if player else None
            current_track = STATE.current_track

            if not current_track:
                current_track = "FE1" # Fallback for track
            
            if not current_car or current_car == 'N/A':
                # If car is unknown, we cannot query for a specific car's top times.
                # The !top command is designed for track/car combinations.
                # Let's fail gracefully like !pb does when car is missing.
                return send_message(get_msg('err_track_car', ucid), ucid)

            c.execute("SELECT uname, lap_time FROM track_records WHERE track = %s AND car = %s ORDER BY lap_time ASC LIMIT 10", (current_track, current_car))
            rows = c.fetchall()
            if not rows:
                return send_message(get_msg('err_no_data', ucid), ucid)

            headers = ["^3#", get_msg('header_pilot', ucid), get_msg('header_time', ucid)]
            data = [[f"^1{i+1}", f"^7{r['uname']}", f"^2{format_lap_time(r['lap_time'])}"] for i, r in enumerate(rows)]
            display_table_with_menu(ucid, get_msg('top_title', ucid, track=current_track, car=current_car), headers, data, "!top")
    finally:
        conn.close()

def cmd_tb(ucid: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            with STATE.lock:
                player = STATE.current_race['players'].get(ucid)
                if not player: return
                uname = player['uname']
                current_car = player['car']
            current_track = STATE.current_track

            if not current_track or not current_car or current_car == 'N/A':
                return send_message(get_msg('must_be_on_track_tb', ucid), ucid)

            c.execute("""
                SELECT split_number, MIN(split_time) as best_split 
                FROM split_times 
                WHERE uname = %s AND track = %s AND car = %s 
                GROUP BY split_number 
                ORDER BY split_number ASC
            """, (uname, current_track, current_car))
            rows = c.fetchall()
            
            if not rows:
                return send_message(get_msg('no_splits', ucid), ucid)

            total_time = 0
            split_strs = []
            for r in rows:
                total_time += r['best_split']
                split_strs.append(f"S{r['split_number']}: ^2{format_lap_time(r['best_split'])}^7")
            
            msg = f"^3Theoretical TB ({current_track}/{current_car}): ^1{format_lap_time(total_time)}^7 (" + ", ".join(split_strs) + ")"
            send_message(msg, ucid)
    finally:
        conn.close()

def show_badcombo_menu(ucid: int):
    # Reasons for reporting - Updated based on user feedback
    reasons = [
        {'id': 'no_lights', 'name': 'No Lights @ Night', 'desc': 'Car has no lights in dark conditions'},
        {'id': 'wrong_tires', 'name': 'Slicks on Dirt', 'desc': 'Car unsuitable for surface (Rally/Road mismatch)'},
        {'id': 'too_big', 'name': 'Car Too Big', 'desc': 'Car too large for small track (e.g. Karting)'},
        {'id': 'broken_mod', 'name': 'Broken Mod/Track', 'desc': 'Glitched geometry or unplayable'},
        {'id': 'other', 'name': 'Other / Troll', 'desc': 'Other issue'},
    ]
    
    headers = ["Report Reason", "Description", "Submit"]
    data = []
    
    for r in reasons:
        data.append([
            f"^3{r['name']}",
            f"^7{r['desc']}",
            f"^1[REPORT]"
        ])
        
    PAGE_STATE[ucid] = {'cmd': '!badcombo', 'rows': reasons, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, "Report Config Mala", headers, data, "!badcombo")

def sync_config_to_api():
    if not getattr(ARGS, 'api_key', None): return
    threading.Thread(target=send_to_api, args=('save_server_config', {'config': STATE.config}), daemon=True).start()

def show_admin_menu(ucid: int):
    state_mods = '^2ON' if STATE.config.get('allow_mods', True) else '^1OFF'
    actions = [
        {'id': 'menu_control', 'name': get_msg('adm_race_ctrl', ucid), 'desc': get_msg('adm_race_ctrl_desc', ucid)},
        {'id': 'menu_rotation', 'name': get_msg('adm_rot', ucid), 'desc': get_msg('adm_rot_desc', ucid)},
        {'id': 'menu_multiclass', 'name': get_msg('adm_mc', ucid), 'desc': get_msg('adm_mc_desc', ucid, max=STATE.config.get('max_multi_class', 1))},
        {'id': 'menu_categories', 'name': get_msg('adm_cats', ucid), 'desc': get_msg('adm_cats_desc', ucid)},
        {'id': 'toggle_mods', 'name': get_msg('adm_mods', ucid, state=state_mods), 'desc': get_msg('adm_mods_desc', ucid)},
        {'id': 'reset_cars', 'name': get_msg('adm_reset_cars', ucid), 'desc': get_msg('adm_reset_cars_desc', ucid)},
        {'id': 'abort_vote', 'name': get_msg('adm_abort_vote', ucid), 'desc': get_msg('adm_abort_vote_desc', ucid)},
    ]
    headers = [get_msg('adm_action', ucid), get_msg('cmd_desc', ucid), get_msg('adm_open', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_open', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!admin', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('adm_main_title', ucid), headers, data, "!admin")

def show_admin_control(ucid: int):
    actions = [
        {'id': 'start', 'name': get_msg('adm_start', ucid), 'desc': get_msg('adm_start_desc', ucid)},
        {'id': 'restart', 'name': get_msg('adm_restart', ucid), 'desc': get_msg('adm_restart_desc', ucid)},
        {'id': 'end', 'name': get_msg('adm_end', ucid), 'desc': get_msg('adm_end_desc', ucid)},
        {'id': 'force_vote', 'name': get_msg('adm_force_vote', ucid), 'desc': get_msg('adm_force_vote_desc', ucid)},
        {'id': 'back', 'name': get_msg('adm_back', ucid), 'desc': get_msg('adm_back_desc', ucid)},
    ]
    headers = [get_msg('adm_action', ucid), get_msg('cmd_desc', ucid), get_msg('adm_run', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_run', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!admin_control', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('adm_ctrl_title', ucid), headers, data, "!admin_control")

def show_admin_rotation(ucid: int):
    actions = [
        {'id': 'random', 'name': get_msg('adm_rand', ucid), 'desc': get_msg('adm_rand_desc', ucid)},
        {'id': 'random_std', 'name': get_msg('adm_rand_std', ucid), 'desc': get_msg('adm_rand_std_desc', ucid)},
        {'id': 'random_mods', 'name': get_msg('adm_rand_mods', ucid), 'desc': get_msg('adm_rand_mods_desc', ucid)},
        {'id': 'back', 'name': get_msg('adm_back', ucid), 'desc': get_msg('adm_back_desc', ucid)},
    ]
    headers = [get_msg('adm_action', ucid), get_msg('cmd_desc', ucid), get_msg('adm_run', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_run', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!admin_rotation', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('adm_rot_title', ucid), headers, data, "!admin_rotation")

def show_admin_multiclass(ucid: int):
    max_mc = int(STATE.config.get('max_multi_class', 1))
    fixed = bool(STATE.config.get('multi_class_fixed', False))
    fixed_str = "^2ON" if fixed else "^1OFF"
    
    actions = [
        {'id': 'mc_1', 'name': get_msg('adm_mc_max', ucid, n=1), 'desc': f"{'^2[ACTIVE]' if max_mc == 1 else ''} {get_msg('adm_mc_single', ucid)}"},
        {'id': 'mc_2', 'name': get_msg('adm_mc_max', ucid, n=2), 'desc': f"{'^2[ACTIVE]' if max_mc == 2 else ''} {get_msg('adm_mc_dual', ucid)}"},
        {'id': 'mc_3', 'name': get_msg('adm_mc_max', ucid, n=3), 'desc': f"{'^2[ACTIVE]' if max_mc == 3 else ''} {get_msg('adm_mc_tri', ucid)}"},
        {'id': 'mc_4', 'name': get_msg('adm_mc_max', ucid, n=4), 'desc': f"{'^2[ACTIVE]' if max_mc == 4 else ''} {get_msg('adm_mc_quad', ucid)}"},
        {'id': 'toggle_fixed', 'name': get_msg('adm_fixed', ucid, state=fixed_str), 'desc': get_msg('adm_fixed_desc', ucid)},
        {'id': 'back', 'name': get_msg('adm_back', ucid), 'desc': get_msg('adm_back_desc', ucid)},
    ]
    headers = [get_msg('adm_action', ucid), get_msg('cmd_desc', ucid), get_msg('adm_select', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_select', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!admin_multiclass', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('adm_mc_title', ucid), headers, data, "!admin_multiclass")

def show_admin_categories(ucid: int):
    cats = ['GTI', 'TBO', 'GTR', 'U17', 'LRF', 'UF1', 'FZ5', 'MRT', 'FBM', 'FOX', 'FO8', 'BF1']
    allowed = STATE.config.get('allowed_classes', [])
    
    actions = []
    for c in cats:
        is_on = (not allowed) or (c in allowed)
        status = "^2[ON]" if is_on else "^1[OFF]"
        actions.append({'id': f'toggle_cat_{c}', 'name': get_msg('adm_cat_toggle', ucid, c=c), 'desc': get_msg('adm_cat_curr', ucid, status=status), 'cat': c})
        
    actions.append({'id': 'allow_all', 'name': get_msg('adm_allow_all', ucid), 'desc': get_msg('adm_allow_all_desc', ucid)})
    actions.append({'id': 'back', 'name': get_msg('adm_back', ucid), 'desc': get_msg('adm_back_desc', ucid)})
    
    headers = [get_msg('adm_category', ucid), get_msg('adm_status', ucid), get_msg('adm_toggle', ucid)]
    data = [[f"^3{act['name']}", f"^7{act['desc']}", f"^2[{get_msg('adm_toggle', ucid).upper()}]"] for act in actions]
    PAGE_STATE[ucid] = {'cmd': '!admin_categories', 'rows': actions, 'page': 1, 'total_pages': 1}
    display_table_with_menu(ucid, get_msg('adm_cats_title', ucid), headers, data, "!admin_categories")


def show_teams(ucid: int, page: int = 1):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            c.execute("SELECT COUNT(*) as count FROM teams")
            total = c.fetchone()['count']
            limit = 10
            total_pages = math.ceil(total / limit) if total > 0 else 1
            offset = (page - 1) * limit
            
            c.execute("SELECT name, points FROM teams ORDER BY points DESC LIMIT %s OFFSET %s", (limit, offset))
            rows = c.fetchall()
            
            headers = [get_msg('header_pos', ucid), get_msg('header_team', ucid), get_msg('header_points', ucid)]
            data = [[offset + i + 1, f"^7{r['name']}", f"^2{r['points']}"] for i, r in enumerate(rows)]
            
            PAGE_STATE[ucid] = {'cmd': '!teams', 'page': page, 'total_pages': total_pages}
            display_table_with_menu(ucid, get_msg('teams_rank_title', ucid), headers, data, "!teams", page, total_pages)
    finally:
        conn.close()

def show_nations(ucid: int, page: int = 1):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor(dictionary=True) as c:
            # Aggregate wins by nation. Filter out NULLs.
            c.execute("SELECT COUNT(DISTINCT nation) as count FROM players WHERE nation IS NOT NULL AND nation != ''")
            res = c.fetchone()
            total = res['count'] if res else 0
            
            limit = 10
            total_pages = math.ceil(total / limit) if total > 0 else 1
            offset = (page - 1) * limit
            
            # Group by nation and sum wins
            c.execute("""
                SELECT nation, SUM(wins) as total_wins 
                FROM players 
                WHERE nation IS NOT NULL AND nation != '' 
                GROUP BY nation 
                ORDER BY total_wins DESC 
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = c.fetchall()
            
            headers = [get_msg('rank_pos', ucid), get_msg('header_nation', ucid), get_msg('header_wins', ucid)]
            data = [[offset + i + 1, f"^7{r['nation']}", f"^2{r['total_wins']}"] for i, r in enumerate(rows)]
            
            PAGE_STATE[ucid] = {'cmd': '!nations', 'page': page, 'total_pages': total_pages}
            display_table_with_menu(ucid, get_msg('nations_rank_title', ucid), headers, data, "!nations", page, total_pages)
    finally:
        conn.close()

def cmd_pb(ucid: int, args: List[str]):
    uname = ""
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            uname = STATE.current_race['players'][ucid]['uname']
    
    if not uname: return

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                if not args:
                    # Case 1: My PB on Current Track/Car
                    track = STATE.current_track
                    car = ""
                    with STATE.lock:
                        if ucid in STATE.current_race['players']:
                            car = STATE.current_race['players'][ucid].get('car', 'N/A')
                    
                    if not track or not car or car == 'N/A':
                        return send_message(get_msg('err_track_car', ucid), ucid)

                    # Fix: Ensure uname is clean
                    clean_uname = re.sub(r'\^[A-Za-z0-9]', '', uname)
                    c.execute("SELECT lap_time FROM track_records WHERE uname = %s AND track = %s AND car = %s", (clean_uname, track, car))
                    row = c.fetchone()
                    if row:
                        send_message(get_msg('pb_msg', ucid, track=track, car=car, time=format_lap_time(row['lap_time'])), ucid)
                    else:
                        send_message(get_msg('pb_title', ucid, track=track, car=car) + ": " + get_msg('no_pb', ucid), ucid)
                    return

                # Case 2: Target User or Target Track
                target = args[0]
                # Heuristic: If arg is a track or car, handle differently?
                # Simplified: Assume it's a username query if not a known track
                
                # Check if it looks lik a track
                if target.upper() in VALID_TRACKS:
                     # Show PBs on track?
                     pass # Not implemented fully in legacy either?
                else:
                    # Show partial PBs for user
                    c.execute("SELECT track, car, lap_time FROM track_records WHERE uname = %s ORDER BY lap_time ASC LIMIT 5", (target,))
                    rows = c.fetchall()
                    if not rows: return send_message(get_msg('no_pbs_target', ucid, target=target), ucid)
                    headers = [get_msg('header_track', ucid), get_msg('header_car', ucid), get_msg('header_time', ucid)]
                    data = [[r['track'], r['car'], format_lap_time(r['lap_time'])] for r in rows]
                    display_table_with_menu(ucid, f"PB de {target}", headers, data, "!pb")
        finally:
            conn.close()
    else:
        # API Fallback (Only supports current track/car PB for now)
        if not args:
            track = STATE.current_track
            car = ""
            with STATE.lock:
                if ucid in STATE.current_race['players']:
                    car = STATE.current_race['players'][ucid].get('car', 'N/A')
            
            if not track or not car or car == 'N/A':
                 return send_message(get_msg('err_track_car', ucid), ucid)

            resp = fetch_api_json('api_player.php', {'uname': uname, 'track': track, 'car': car})
            if resp and 'pb' in resp and resp['pb']:
                t_str = format_lap_time(int(resp['pb']['time']))
                send_message(get_msg('pb_msg', ucid, track=track, car=car, time=t_str), ucid)
            else:
                 send_message(get_msg('pb_title', ucid, track=track, car=car) + ": " + get_msg('no_pb', ucid), ucid)
        else:
             send_message(get_msg('db_error', ucid) + " / API Limited", ucid)

def cmd_track(ucid: int):
    track = STATE.current_track
    curr_len = TRACK_LENGTHS.get(track, 0.0)
    # Placeholder for weather/wind as we don't parse NPL detailed info yet or RST
    wind = "0" 
    weather = "0"
    send_message(get_msg('track_info', ucid, track=track, len=curr_len, wind=wind, weather=weather), ucid)

def cmd_web(ucid: int):
    send_message(get_msg('web_info', ucid), ucid)

def cmd_register(ucid: int, args: list = []):
    uname = ""
    with STATE.lock:
        if ucid in STATE.current_race.get('players', {}):
            uname = STATE.current_race['players'][ucid].get('uname', '')
            
    if not STATE.config.get('register', True):
        send_message(get_msg('reg_disabled', ucid), ucid)
        return
        
    if not uname: return
    
    # Server Registration Logic (Generate Token)
    if args and args[0].lower() == 'server':
        resp = send_to_api('generate_server_token', {'uname': uname})
        if resp and resp.get('status') == 'success':
            token = resp.get('token')
            send_message(get_msg('reg_srv_gen', ucid), ucid)
            send_message(get_msg('reg_srv_token', ucid, token=token), ucid)
            send_message(get_msg('reg_srv_help', ucid), ucid)
        else:
            err = resp.get('message', 'Unknown error') if resp else "Network/Timeout error"
            send_message(get_msg('reg_srv_fail', ucid, err=err), ucid)
        return
    
    # Send to API (P2P Node generates Web login code)
    resp = send_to_api('generate_auth_code', {'uname': uname})
    
    if resp and resp.get('status') == 'success' and resp.get('code'):
        code = resp['code']
        headers = [get_msg('reg_type', ucid), get_msg('reg_info', ucid)]
        data = [
            [get_msg('reg_web_prof', ucid), get_msg('reg_web_goto', ucid)],
            [get_msg('reg_login_code', ucid), f"^2{code}"],
            [get_msg('reg_new_srv', ucid), get_msg('reg_click', ucid)]
        ]
        # Setup PAGE_STATE to make the 3rd row clickable
        PAGE_STATE[ucid] = {'cmd': '!register', 'rows': [{'id': 'web'}, {'id': 'code'}, {'id': 'server'}]}
        display_table_with_menu(ucid, get_msg('reg_menu_title', ucid), headers, data, "!register")
    else:
        err = resp.get('message', 'Unknown') if resp else "Network Error"
        send_message(get_msg('reg_fail', ucid, err=err), ucid)

def cmd_wr(ucid: int, args: List[str]):
    conn = get_db_connection()
    if not conn: return send_message(get_msg('db_error', ucid), ucid)
    try:
        with conn.cursor(dictionary=True) as c:
            current_track = STATE.current_track
            if not args:
                with STATE.lock:
                    player = STATE.current_race['players'].get(ucid)
                    current_car = player.get('car', 'N/A') if player else None
                
                if current_track and current_car and current_car != 'N/A':
                    c.execute("SELECT uname, lap_time FROM track_records WHERE track = %s AND car = %s", (current_track, current_car))
                    row = c.fetchone()
                    if row:
                        send_message(get_msg('wr_msg', ucid, track=current_track, car=current_car, holder=row['uname'], time=format_lap_time(row['lap_time'])), ucid)
                    else:
                        send_message(get_msg('wr_title', ucid, track=current_track, car=current_car) + ": " + get_msg('no_wr', ucid), ucid)
                    return

                # Call paginated show_records
                show_records(ucid)
                return
            else:
                track = args[0].upper()
                car = args[1].upper() if len(args) > 1 else None
                if track not in VALID_TRACKS: return send_message(get_msg('invalid_track', ucid), ucid)
                if car and car not in CAR_LIST.values(): return send_message(get_msg('invalid_car', ucid), ucid)
                
                if car:
                    c.execute("SELECT uname, lap_time FROM track_records WHERE track = %s AND car = %s", (track, car))
                    row = c.fetchone()
                    if row: send_message(get_msg('wr_msg', ucid, track=track, car=car, holder=row['uname'], time=format_lap_time(row['lap_time'])), ucid)
                    else: send_message(get_msg('wr_title', ucid, track=track, car=car) + ": " + get_msg('no_wr', ucid), ucid)
                else:
                    c.execute("SELECT car, uname, lap_time FROM track_records WHERE track = %s ORDER BY lap_time ASC", (track,))
                    rows = c.fetchall()
                    if not rows: return send_message(get_msg('no_wr_track', ucid, track=track), ucid)
                    headers = [get_msg('header_car', ucid), get_msg('header_pilot', ucid), get_msg('header_time', ucid)]
                    data = [[r['car'], r['uname'], format_lap_time(r['lap_time'])] for r in rows]
                    display_table_with_menu(ucid, get_msg('records_title', ucid, track=track), headers, data, "!sr")
    finally:
        conn.close()

# --- INSIM HANDLERS ---

def on_new_connection(packet: bytes):
    if len(packet) < 56: return
    try:
        _, _, req_i, ucid, uname_b, pname_b, admin, total, flags, sp3 = struct.unpack('<BBBB24s24sBBBB', packet[:56])
    except struct.error as e:
        logging.error(f"Failed to unpack NCN packet: {e}")
        return

    uname = clean_string(uname_b)
    pname = clean_string(pname_b)

    if ucid == 0:
        logging.info(f"HOST Connected (UCID 0). Ignoring player registration.")
        return

    with STATE.lock:
        # --- CANCEL ROTATION IF SOMEONE JOINS ---
        if STATE.empty_server_timer and STATE.empty_server_timer.is_alive():
            logging.info("Player connected. Canceling empty server rotation.")
            STATE.empty_server_timer.cancel()
            STATE.empty_server_timer = None

        if ucid not in STATE.current_race['players']:
            STATE.current_race['players'][ucid] = {}
        
        player = STATE.current_race['players'][ucid]
        player['uname'] = uname
        player['pname'] = pname
        player['admin'] = (admin > 0)
        
        # Retrieve language from DB
        conn = get_db_connection()
        lang = 'es'
        tid = None
        if conn:
            try:
                with conn.cursor() as c:
                    c.execute("SELECT language, team_id FROM players WHERE uname = %s", (uname,))
                    row = c.fetchone()
                    if row:
                        if row[0]: lang = row[0]
                        if row[1]: tid = row[1]
            except Exception as e:
                logging.error(f"Error retrieving player data for {uname}: {e}")
            finally:
                conn.close()
        
        STATE.current_race['players'][ucid]['language'] = lang
        STATE.current_race['players'][ucid]['team_id'] = tid
        
        logging.info(f"NEW CONNECTION (NCN): {uname} (UCID: {ucid})")
        # Only send welcome if it's a NEW connection (ReqI == 0)
        # If ReqI > 0, it's a response to a status request (IS_TINY_NCN)
        if req_i == 0:
            if STATE.config.get('welcome_msg', True):
                cust_msg = STATE.config.get('welcome_msg_text', '')
                if cust_msg:
                    # Allow formatting with uname
                    try:
                        formatted = cust_msg.format(uname=uname)
                        send_message(formatted, ucid)
                    except:
                        send_message(cust_msg, ucid)
                else:
                    send_message(get_msg('welcome_base', ucid, uname=uname), ucid)
                
                if STATE.config.get('register', True):
                    send_message(get_msg('welcome_reg', ucid), ucid)

def on_connection_leave(packet: bytes):
    # ISP_CNL - Packet Type 19
    if len(packet) < 8: return
    
    # Structure: Size, Type, ReqI, UCID, Reason, Total, Sp2, Sp3
    try:
         _, _, _, ucid, _, total, _, _ = struct.unpack('<BBBBBBBB', packet[:8])
    except:
        return

    with STATE.lock:
        if ucid in STATE.current_race['players']:
            pname = STATE.current_race['players'][ucid].get('uname', 'Unknown')
            logging.info(f"DISCONNECT (CNL): {pname} (UCID: {ucid}). Total remaining: {total}")
            del STATE.current_race['players'][ucid]
        
        # --- EMPTY SERVER LOGIC ---
        # If total reported by LFS is 0, or our local list is empty
        if total == 0 or len(STATE.current_race['players']) == 0:
            logging.info("Empty server. Starting rotation timer (30s)...")
            if STATE.empty_server_timer:
                STATE.empty_server_timer.cancel()
            
            # Rotate to random configuration after 30 seconds of inactivity
            # CHECK: Only if Auto Random is enabled
            if STATE.config.get('auto_random', True):
                logging.info("Auto-Rotation Enabled. Timer started.")
                rot_time = float(STATE.config.get('rotation_time', 30.0))
                STATE.empty_server_timer = threading.Timer(rot_time, lambda: set_random_configuration("empty_server_rotation"))
                STATE.empty_server_timer.start()
            else:
                logging.info("Auto-Rotation Disabled in Config.")

def on_player_join(packet: bytes):
    if len(packet) < 44: return
    try:
        # LFS NPL: 0=Size, 1=Type, 2=ReqI, 3=PLID, 4=UCID
        if len(packet) < 44: return
        plid = packet[3]
        ucid, cname_b = struct.unpack('<B35x4s', packet[4:44])
    except struct.error as e:
        logging.error(f"Failed to unpack NPL packet: {e}")
        return

    if ucid == 0: return

    # Parse Car Name using expand_mod_id (supports Mods)
    car_code = expand_mod_id(cname_b[:3])
    
    # Resolve Name if it's a known mod ID
    
    # Resolve Name if it's a known mod ID
    if car_code in STATE.mod_map:
        car = STATE.mod_map[car_code]
    else:
        car = car_code
    
    # Fallback to simple clean if it was official, but expand_mod_id handles official too
    # clean_string might effectively be done by decode in expand_mod_id
    
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            player_state = STATE.current_race['players'][ucid]
            player_state['plid'] = plid
            player_state['car'] = car
            
            uname = player_state.get('uname', 'Unknown')
            logging.info(f"PLAYER ON TRACK (NPL): {uname} | PLID: {plid} | Car: {car} ({car_code})")
            
            # Track Active Players for Qual Skip
            if hasattr(STATE, 'on_track_plids'):
                STATE.on_track_plids.add(plid)
                if STATE.current_race.get('status') == 'qualifying':
                     STATE.current_race['last_qual_activity'] = time.time()

def on_car_select(packet: bytes):
    if len(packet) < 8: return
    ucid = packet[3]
    if ucid == 0: return
    
    cname_b = packet[4:8]
    # Parse Car Name using expand_mod_id (supports Mods)
    car_code = expand_mod_id(cname_b[:3])
    
    # Resolve Name if it's a known mod ID
    if car_code in STATE.mod_map:
        car = STATE.mod_map[car_code]
    else:
        car = car_code
        
    if not car: return
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            STATE.current_race['players'][ucid]['car'] = car
            logging.info(f"MANUAL SELECTION: UCID {ucid} -> {car} ({car_code})")

# --- FINAL FIX: ROBUST MESSAGE CLEARING ---
def on_message(packet: bytes):
    if len(packet) < 10: return
    ucid = packet[4]
    user_type = packet[6]
    text_start = packet[7]
    
    if user_type == 0 or ucid == 0: return # Ignorar mensajes del sistema y Host

    try:
        msg_raw = packet[text_start:]
        msg = clean_string(msg_raw)
    except Exception:
        return

    # 1. Clear LFS colors and formats (e.g. ^L, ^7, ^1)
    clean_msg = re.sub(r'\^[A-Za-z0-9]', '', msg)

    # 2. Look for a '!' command in the clean message
    if '!' not in clean_msg:
        if msg: logging.info(f"CHAT (UCID {ucid}): {msg} -> IGNORADO (No es comando)")
        return

    # 3. Cut everything before the '!' (name prefixes, tags, etc.)
    # E.g. "G] : !top" -> "!top"
    try:
        command_part = clean_msg[clean_msg.index('!'):]
        
        # --- ALIAS PROCESSING ---
        aliases_str = STATE.config.get('command_aliases', '')
        if aliases_str:
             for line in aliases_str.split('\n'):
                 if '=' in line:
                     parts = line.split('=', 1)
                     alias = parts[0].strip().lower()
                     target = parts[1].strip().lower()
                     cmd_lower = command_part.lower()
                     
                     if cmd_lower == alias or cmd_lower.startswith(alias + ' '):
                          # Replace logic
                          # e.g. alias=!votar, target=!vote
                          # cmd=!votar skip -> !vote skip
                          command_part = target + command_part[len(alias):]
                          logging.info(f"ALIAS RESOLVED: {alias} -> {target}")
                          break
        # ------------------------
    except ValueError:
        return

    logging.info(f"COMANDO DETECTADO (UCID {ucid}): {command_part}")
    
    parts = command_part.split()
    cmd = parts[0].lower()
    args = parts[1:]
    
    uname = ""
    with STATE.lock:
        if ucid in STATE.current_race['players']:
            uname = STATE.current_race['players'][ucid]['uname']
    
    # --- COMMAND TOGGLES CHECK ---
    feature_map = {
        '!vote': 'voting',
        '!stats': 'stats', '!top': 'stats', '!rank': 'stats', '!topwins': 'stats', '!tb': 'stats', '!mypb': 'enable_pb', '!sr': 'stats', '!topcars': 'stats',
        '!elo': 'stats',
        '!team': 'teams', '!nations': 'teams',
        '!register': 'register',
        '!help': 'help',
        '!mods': 'enable_mods',
        '!pb': 'enable_pb',
        '!track': 'enable_track', '!tr': 'enable_track',
        '!web': 'enable_web', '!website': 'enable_web'
    }
    
    feat_key = feature_map.get(cmd)
    if feat_key:
        is_enabled = STATE.config.get(feat_key, True) # Default to True (Enabled)
        logging.info(f"CMD CHECK: {cmd} -> Key: {feat_key}, Val: {is_enabled} ({type(is_enabled)}) - Config: {STATE.config}")
        # Handle string "0" or "false" from JSON if loose typing
        if isinstance(is_enabled, str) and is_enabled.lower() in ['0', 'false', 'off']: is_enabled = False
        if is_enabled is False or is_enabled == 0:
            return send_message(get_msg('cmd_disabled', ucid), ucid)

    # Command dispatcher
    if cmd in ['!register', '!webpass']:
        cmd_register(ucid, args)
    elif cmd == '!rank':
        cmd_rank(ucid, args)
    elif cmd == '!topwins':
        cmd_topwins(ucid)
    elif cmd == '!topcars':
        show_topcars(ucid)
    elif cmd == '!stats':
        cmd_me(ucid)
    elif cmd == '!help':
        cmd_help(ucid)
    elif cmd == '!top':
        cmd_top(ucid)
    elif cmd == '!tb':
        cmd_tb(ucid)
    elif cmd == '!sr':
        cmd_wr(ucid, args)
    elif cmd == '!mypb':
        cmd_pb(ucid, [])
    # Team Commands
    elif cmd == '!team':
        if len(args) > 0:
            sub = args[0].lower()
            if sub == 'create': team_create(ucid, uname, args[1:])
            elif sub == 'join': team_request_join(ucid, uname, args[1:])
            elif sub == 'leave': team_leave(ucid, uname)
            elif sub == 'accept': team_accept(ucid, uname, args[1:])
            elif sub == 'decline': team_decline(ucid, uname, args[1:])
            elif sub == 'kick': team_kick(ucid, uname, args[1:])
            elif sub == 'promote': team_promote(ucid, uname, args[1:])
            elif sub == 'pending': team_pending(ucid, uname)
            elif sub == 'info': team_info(ucid, uname)
            elif sub == 'list': teams_list(ucid, args[1:])
            else: show_team_menu(ucid, uname)
        else:
            show_team_menu(ucid, uname)
    # New Commands around here
    elif cmd == '!nations':
        show_nations(ucid)
    elif cmd == '!mods':
        cmd_list_mods(ucid)
    elif cmd == '!allcars':
        if is_admin(uname, ucid):
            cmd_allcars(ucid)
        else:
            send_message(get_msg('admin_only', ucid), ucid)
    
    # ... check existing code structure
    elif cmd == '!setmod':
        if is_admin(uname, ucid):
            cmd_setmod(ucid, args)
        else:
            send_message(get_msg('admin_only', ucid), ucid)

    elif cmd == '!vote':
         cmd_vote(ucid, args)
    
    elif cmd == '!badcombo':
        cmd_badcombo(ucid)
    # Old dispatcher commands merged into main dispatcher
    elif cmd in ["!tr", "!track"]: 
        if STATE.config.get('help', True): cmd_track(ucid)
    elif cmd in ["!web", "!website"]: 
        cmd_web(ucid)
    elif cmd == "!elo": 
        if STATE.config.get('stats', True): show_elo(ucid, uname)
    elif cmd == "!teams": 
        show_teams(ucid)
    elif cmd == "!pb": 
        cmd_pb(ucid, args)
    elif cmd == "!lang": 
        cmd_lang(ucid, args)
    elif cmd == "!random": admin_random_command(ucid, uname, args)
    elif cmd == "!badcombo": show_badcombo_menu(ucid)
    elif cmd == "!admin":
        if is_admin(uname, ucid):
            show_admin_menu(ucid)
        else:
             send_message(get_msg('admin_only', ucid), ucid)
    elif cmd == "!setcars":
        if is_admin(uname, ucid):
            if not args:
                send_message(get_msg('err_arg_missing', ucid), ucid)
            else:
                arg = args[0].upper()
                if arg in ['RESET', 'ALL', 'TODOS']:
                    with STATE.lock:
                        STATE.allowed_cars_filter = None
                        save_live_data()
                    send_message(get_msg('setcars_reset', ucid), ucid)
                else:
                    CAR_BITMASKS = {
                        'XFG': 1, 'XRG': 2, 'XRT': 4, 'RB4': 8, 'FXO': 16, 'LX4': 32, 'LX6': 64, 'MRT': 128,
                        'UF1': 256, 'RAC': 512, 'FZ5': 1024, 'FOX': 2048, 'XFR': 4096, 'UFR': 8192, 'FO8': 16384,
                        'FXR': 32768, 'XRR': 65536, 'FZR': 131072, 'BF1': 262144, 'FBM': 524288
                    }
                    requested_cars = arg.split('+')
                    path_mask = 0
                    valid_names = []
                    for c in requested_cars:
                         c = c.strip()
                         if c in CAR_BITMASKS:
                             path_mask |= CAR_BITMASKS[c]
                             valid_names.append(c)
                    
                    if path_mask > 0:
                         with STATE.lock:
                             STATE.allowed_cars_filter = path_mask
                             save_live_data()
                         cars_str = "+".join(valid_names)
                         send_message(get_msg('setcars_success', ucid, cars=cars_str), ucid)
                    else:
                         send_message(get_msg('err_no_valid_cars', ucid), ucid)
        else:
            send_message(get_msg('err_no_admin', ucid), ucid)

def connect_insim(host: str, port: int, admin_pass: str) -> Optional[socket.socket]:
    for attempt in range(5):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((host, port))
            
            flags = 1 | 32 
            
            isi_packet = struct.pack(
                '<BBBBHHBBH16s16s',
                44 // 4, # Size/4
                1, # ISP_ISI
                1, # ReqI
                0, # Zero
                0, # UDPPort
                flags,
                9, # InSimVer
                0, # Prefix
                200, # Interval (ms)
                admin_pass.encode('latin-1')[:16],
                b"LFS_ELO_BOT"[:16]
            )
            sock.sendall(isi_packet)
            # Request Server Info (TINY_ISM)
            # Size 4, Type 3 (TINY), ReqI 1, SubT 10 (TINY_ISM)
            tiny_ism = struct.pack('<BBBB', 1, 3, 1, 10)
            sock.sendall(tiny_ism)
            
            # Request All Connections (TINY_NCN) -> SubT 13
            tiny_ncn = struct.pack('<BBBB', 1, 3, 1, 13)
            sock.sendall(tiny_ncn)
            
            # Request All Players (TINY_NPL) -> SubT 14
            tiny_npl = struct.pack('<BBBB', 1, 3, 1, 14)
            sock.sendall(tiny_npl)
            logging.info(f"Connected to InSim at {host}:{port}")
            sock.settimeout(None)
            return sock
        except Exception as e:
            logging.error(f"Attempt {attempt + 1}/5 failed: {e}")
            time.sleep(5 + attempt * 2)
    return None

def handle_packet(packet: bytes):
    if len(packet) < 2: return
    pkt_type = packet[1]

    try:
        if pkt_type == 3:   # ISP_TINY
            on_tiny(packet)
        elif pkt_type == 5: # ISP_STA (State)
            on_state(packet)
        elif pkt_type == 8:   # ISP_SLC
            on_car_select(packet)
        elif pkt_type == 11: # ISP_MSO (Incoming Message)
            on_message(packet)
        elif pkt_type == 17: # ISP_RST
            on_race_start(packet)
        elif pkt_type == 18: # ISP_NCN
            on_new_connection(packet)
        elif pkt_type == 19: # ISP_CNL (NUEVO: Connection Leave)
            on_connection_leave(packet)
        elif pkt_type == 21: # ISP_NPL
            on_player_join(packet)
        elif pkt_type == 23: # ISP_PLL (Player Leave Race - Spectate/Pit)
            on_player_leave_race(packet)
        elif pkt_type == 24: # ISP_LAP
            on_lap(packet)
        elif pkt_type == 25: # ISP_SPX
            on_split(packet)
        elif pkt_type == 35: # ISP_RES
            on_result(packet)
        elif pkt_type == 38: # ISP_MCI
            on_mci(packet)
        elif pkt_type == 46: # ISP_BTC
            on_button_click(packet)
        elif pkt_type == 10: # ISP_ISM (Info)
            on_ism(packet)
    except Exception as e:
        logging.error(f"Error handling packet type {pkt_type}: {e}")
        logging.error(traceback.format_exc())

def on_ism(packet: bytes):
    # struct IS_ISM { byte Size; byte Type; byte ReqI; byte Zero; byte Host; byte Zero1; byte Zero2; byte Zero3; char HName[32]; };
    if len(packet) < 40: return
    try:
        # HName starts at offset 8, length 32
        hname_bytes = packet[8:40]
        hname = hname_bytes.decode('utf-8', errors='ignore').strip('\x00')
        # Filter LFS colors
        hname_clean = re.sub(r'\^[0-7]', '', hname)
        
        with STATE.lock:
            STATE.server_name = hname_clean
            logging.info(f"Updated Server Name from ISM: {STATE.server_name}")
    except Exception as e:
        logging.error(f"Error parsing ISP_ISM: {e}")


def on_tiny(packet: bytes):
    if len(packet) < 4: return
    reqi, subt = struct.unpack('<BB', packet[2:4])
    logging.info(f"TINY Packet Received: SubT={subt}")
    if subt == 0: # TINY_NONE - Keep Alive
        send_packet(struct.pack('<BBBB', 1, 3, 0, 0))
    elif subt == 14: # TINY_REN - Race End
        with STATE.lock:
             status = STATE.current_race['status']
             
             if status == 'qualifying':
                 logging.info("Qualifying Finished (TINY_REN). Checking for active laps...")
                 STATE.current_race['status'] = 'qualifying_overtime'
                 
                 # Identify players currently on track (checking last cache or assuming active plids)
                 # We can use started_players or just players dict which contains NPLs (on track)
                 active_plids = []
                 for p in STATE.current_race['players'].values():
                     # Only if they are physically on track? 
                     # NPL means they are on track.
                     active_plids.append(p['plid'])
                 
                 if not active_plids:
                     logging.info("No active players. Restarting immediately.")
                     broadcast_localized("qual_finished_restart")
                     time.sleep(1)
                     send_message("/restart", 0)
                 else:
                     STATE.qual_finishing_players = set(active_plids)
                     broadcast_localized("qual_time_expired")
                     threading.Thread(target=check_qual_overtime, daemon=True).start()
                 
             elif status == 'racing':
                 logging.info("Race Finished (TINY_REN). Processing results immediately.")
                 threading.Thread(target=process_and_display_results, daemon=True).start()

def on_state(packet: bytes):
    if len(packet) < 28: return
    try:
        num_p = packet[12]
        race_in_prog = packet[15]
        qual_mins = packet[16]
        track_bytes = packet[20:26]
        track = track_bytes.split(b'\0', 1)[0].decode('utf-8', errors='ignore')
        
        logging.info(f"ISP_STA: Track='{track}', RaceInProg={race_in_prog}, NumP={num_p}")
        
        with STATE.lock:
            if track and track.strip():
                STATE.current_track = track
                
            old_status = STATE.current_race.get('status', 'idle')
            
            # Detect End of Qualification via State?
            # If we were in 'qualifying' and race_in_prog becomes 0?
            # Or if race_in_prog becomes 1?
            
            # Update internal state if needed
            # But be careful not to override 'qualifying_overtime' logic if we want THAT to handle it.
            # If LFS sends RaceInProg=0 (No Race) when Qual time ends?
            
            if old_status in ['qualifying', 'qualifying_overtime']:
                 if race_in_prog == 0: # State changed to No Race
                     logging.info("ISP_STA: Qualification Ended (RaceInProg=0). Sending /restart to start Race.")
                     STATE.current_race['status'] = 'qualifying_overtime'
                     broadcast_localized("session_finished")
                     time.sleep(1)
                     send_message("/restart", 0)
            
    except Exception as e:
        logging.error(f"Error parsing ISP_STA: {e}")

def check_qual_overtime():
    start_wait = time.time()
    
    # Calculate Dynamic Max Wait based on Best Lap of the SESSION
    best_lap = 0
    with STATE.lock:
        laps = []
        for p in STATE.current_race['players'].values():
            bl = p.get('best_lap', 0)
            logging.info(f"QUAL CHECK: Player {p.get('uname')} (PLID {p.get('plid')}) - BestLap: {bl}")
            if bl > 0:
                laps.append(bl)
        
        if laps:
            best_lap = min(laps)

    # USER REQUEST: "if no time in 8 min, skip to race"
    if best_lap == 0:
        logging.info("Qual Time Expired and NO times set. Using default fallback (120s) to allow first laps.")
        # Default fallback if no one set a time yet (e.g. short qual)
        max_wait = 120.0
    else:
        # USER REQUEST: "110% margin of best time"
        # best_lap is in ms. 
        # Example: 1:00.000 (60000ms) * 1.1 = 66000ms = 66s.
        max_wait = (best_lap * 1.1) / 1000.0
    
    # Cap at reasonable max (e.g. 5 mins) to prevent infinite loops
    if max_wait > 300: max_wait = 300
    if max_wait < 30: max_wait = 30 # Minimum 30s just in case
    
    logging.info(f"Qual Overtime: Waiting {max_wait:.1f}s (Based on BestLap: {format_lap_time(best_lap)})")

    broadcast_localized("qual_overtime_start", wait=max_wait)

    while True:
        with STATE.lock:
             if STATE.current_race['status'] != 'qualifying_overtime':
                 return
             
             remaining = len(STATE.qual_finishing_players)
             if remaining == 0:
                 logging.info("All players finished/pitted. Restarting.")
                 break
        
        if time.time() - start_wait > max_wait:
            logging.info("Qual Overtime Timeout. Forcing End.")
            broadcast_localized("time_extra_expired")
            break
            
        time.sleep(1)
    
    with STATE.lock:
        if STATE.current_race['status'] == 'qualifying_overtime':
             # broadcast_localized("qual_finished_restart") -> Moved to force_race_start_now
             # Use centralized end logic
             force_race_start_now()

def on_player_leave_race(packet: bytes): # ISP_PLL
    if len(packet) < 4: return
    plid = packet[3]
    with STATE.lock:
        # Remove from players list logic if needed, but mainly for Qual Overtime
        # Usually NPL adds, PLL removes from track (spectating/pitting)
        # If they pit, they send PLL? Or just disappear? 
        # PLL = Player Leave (Spectate). Pitting is usually implied by PLL if they go to specs/garage.
        # Check standard InSim PLL usage.
        
        # Remove from qual finishing set
        if hasattr(STATE, 'qual_finishing_players') and plid in STATE.qual_finishing_players:
            STATE.qual_finishing_players.discard(plid)
            
        # Update On-Track List (for Empty Qual Check)
        if hasattr(STATE, 'on_track_plids') and plid in STATE.on_track_plids:
            STATE.on_track_plids.discard(plid)
            logging.info(f"Player Left Track (PLID {plid}). Remaining: {len(STATE.on_track_plids)}")

        # Also remove from players dict as they are no longer "In Race" (on track)
        found_ucid = None
        for u, p in STATE.current_race['players'].items():
            if p.get('plid') == plid:
                # Mark as not on track
                p['plid'] = None 
                found_ucid = u
                break
        
def monitor_qual_emptiness(race_token):
    logging.info("Starting Emptiness Monitor...")
    # Initialize activity timestamp
    with STATE.lock:
        STATE.current_race['last_qual_activity'] = time.time()
        
    while True:
        time.sleep(5)
        with STATE.lock:
             # Check if race changed
             if STATE.current_race.get('race_token') != race_token: return
             
             # If race actually started, we can stop the qual monitor
             if STATE.current_race.get('status') == 'racing': return
             
             # Calculate active players (having a valid PLID means on track)
             on_track_count = 0
             for p in STATE.current_race['players'].values():
                 if p.get('plid') is not None:
                     on_track_count += 1
             
             # Check time since last activity
             last_act = STATE.current_race.get('last_qual_activity', time.time())
             idle_time = time.time() - last_act
             
             # Dynamic Timeout
             if on_track_count > 0:
                 best_lap = 0
                 laps = [p.get('best_lap', 0) for p in STATE.current_race['players'].values() if p.get('best_lap', 0) > 0]
                 if laps: best_lap = min(laps)
                 
                 if best_lap > 0:
                     # 110% of best lap
                     expected_ms = best_lap
                 else:
                     # Use combo's expected lap time if nobody has set a lap yet
                     class_name = getattr(STATE, 'current_allowed_cars_filter', 'UF1')
                     expected_ms = get_expected_lap_time_ms(STATE.current_track, class_name)
                 
                 # 110% of the expected lap, but minimum 120s to account for out-laps and crashes
                 timeout = max(120.0, (expected_ms * 1.1) / 1000.0)
             else:
                 timeout = 60.0
             
             if idle_time >= timeout:
                 if on_track_count > 0:
                     logging.info(f"Idle for {idle_time:.1f}s despite {on_track_count} players. Skipping to next combo.")
                 else:
                     logging.info(f"Empty (No players) for {idle_time:.1f}s. Skipping to next combo.")

                 # Change to Race instead of skipping combo
                 force_race_start_now()
                 return

def on_mci(packet: bytes):
    if len(packet) < 4: return
    try:
        numc = packet[3]
        offset = 4
        with STATE.lock:
            for _ in range(numc):
                if offset + 28 > len(packet): break
                node, lap, plid, position, info, sp3, _pad, x, y, z, speed, direction, heading, angvel = struct.unpack('<HBBBBBBiiiHHHh', packet[offset:offset+28])
                player = next((p for p in STATE.current_race['players'].values() if p.get('plid') == plid), None)
                if player:
                    player['position'] = position
                    player['laps_done'] = lap - 1 if lap > 0 else 0
                    
                    # Detect Stopped Cars during Qual Overtime
                    if STATE.current_race.get('status') == 'qualifying_overtime':
                        # Speed unit: 32768 = 100 m/s. So 1 m/s = 327.
                        if speed < 327: 
                            player['stopped_ticks'] = player.get('stopped_ticks', 0) + 1
                            # MCI usually 4-5 times per sec. 
                            # Increased threshold to 120 ticks (~30s) to avoid kicking spinning players.
                            if player['stopped_ticks'] > 120:
                                if plid in getattr(STATE, 'qual_finishing_players', set()):
                                    STATE.qual_finishing_players.discard(plid)
                                    logging.info(f"Player {player['uname']} stopped ({speed}) for >30s. Removing from Qual Overtime.")
                        else:
                             player['stopped_ticks'] = 0
                             
                offset += 28
    except Exception:
        pass

def receive_packets(sock: socket.socket):
    buffer = b''
    while True:
        try:
            data = sock.recv(4096)
            if not data: break
            buffer += data
            while len(buffer) >= 4:
                packet_size = buffer[0] * 4
                if packet_size == 0: 
                    buffer = buffer[1:]
                    continue
                if len(buffer) < packet_size: break
                
                packet = buffer[:packet_size]
                buffer = buffer[packet_size:]
                
                handle_packet(packet)
        except Exception as e:
            logging.error(f"Error in receive_packets: {e}")
            break
            break
    STATE.insim_sock = None

def force_race_start_now():
    """Helper to send restart command to start race."""
    broadcast_localized("qual_finished_restart")
    time.sleep(1)
    send_message("/restart")

def end_qualification():
    """Called when qualification timer expires."""
    active_plids = []
    with STATE.lock:
        STATE.qual_timer = None
        current_status = STATE.current_race.get('status')
        # If we are not qualifying anymore, do nothing
        if current_status != 'qualifying':
            return 
            
        # Check for active players
        for p in STATE.current_race['players'].values():
            if p.get('plid') is not None:
                active_plids.append(p['plid'])
    
    if not active_plids:
        logging.info("Qual Timer Expired. No active players. Forcing race start.")
        force_race_start_now()
    else:
        logging.info(f"Qual Timer Expired. {len(active_plids)} players on track. Entering Overtime.")
        with STATE.lock:
            STATE.current_race['status'] = 'qualifying_overtime'
            STATE.qual_finishing_players = set(active_plids)
            
        broadcast_localized("qual_time_expired")
        threading.Thread(target=check_qual_overtime, daemon=True).start()

def on_race_start(packet: bytes):
    if len(packet) < 28: return
    
    # RST Packet Structure:
    # 4: RaceLaps, 5: QualMins, 6: NumP, 8-14: Track
    try:
        laps = packet[4]
        qual_mins = packet[5]
        num_players = packet[6]
        track = clean_string(packet[8:14]).upper()
        
        with STATE.lock:
            STATE.current_track = track
            STATE.current_race['track'] = track
            STATE.current_race['laps'] = laps
            
            if qual_mins > 0:
                 STATE.current_race['status'] = 'qualifying'
            else:
                 STATE.current_race['status'] = 'racing'

            logging.info(f"RST/RaceStart: Track={track}, Laps={laps}, Q={qual_mins}")
            
    except Exception as e:
        logging.error(f"Error parsing RST: {e}")
        return

    with STATE.lock:
        STATE.current_race.update({
            'status': 'racing', 'results': [], 'restarting': False,
            'num_players_at_start': num_players,
            'started_players': {},
            'race_token': time.time()
        })
        STATE.current_track = track
        for ucid, p in STATE.current_race['players'].items():
            p.update({'splits': [], 'laps_done': 0, 'current_split': 0, 'split_time': 0, 'last_lap_time': 0, 'position': 0, 'finished': False})
            # Snapshot for DNF detection (only if they are effectively in race? assume everyone connected is)
            STATE.current_race['started_players'][p['uname']] = {
                'uname': p['uname'],
                'car': p.get('car', 'UNK'),
                'team_id': p.get('team_id')
            }
    
    
    # Use getattr to default to 0
    allowed = getattr(STATE, 'current_allowed_cars', 0)
    
    # Use config name to get the FULL list of allowed cars (including empty ones)
    car_names = getattr(STATE, 'current_config_name', None)
    if car_names:
        if ' - ' in car_names:
            car_names = car_names.split(' - ', 1)[1]
    else:
        # Detect cars from active players (fallback)
        active_cars = set()
        with STATE.lock:
             for ucid, p in STATE.current_race['players'].items():
                 c = p.get('car')
                 if c: active_cars.add(c)
                 
        if active_cars:
            car_names = "/".join(sorted(active_cars))
        else:
            car_names = None
        
    if qual_mins > 0:
        logging.info(f"QUAL START: {track}, Mins={qual_mins}, Players={num_players}")
        if car_names:
            broadcast_localized("qual_start_msg", track=track, car_names=car_names, qual_mins=qual_mins)
        else:
            broadcast_localized("qual_start_msg", track=track, car_names_bitmask=allowed, qual_mins=qual_mins)
        
        with STATE.lock: 
            STATE.current_race['status'] = 'qualifying'
            # Remove legacy reset, relying on TINY_NPL
            # STATE.on_track_plids = set() 
            
            # Start Qualification Timer
            if STATE.qual_timer:
                STATE.qual_timer.cancel()
            
            # Duration in seconds + buffer (5s)
            duration = qual_mins * 60 + 5
            STATE.qual_timer = threading.Timer(duration, end_qualification)
            STATE.qual_timer.daemon = True
            STATE.qual_timer.start()
            logging.info(f"Qual Timer started for {duration}s")
            
        # Send TINY_NPL to refresh on-track status
        send_packet(struct.pack('<BBBB', 1, 3, 0, 8)) # TINY_NPL = 8
            
        # Start Empty Monitor
        threading.Thread(target=monitor_qual_emptiness, args=(STATE.current_race['race_token'],), daemon=True).start()

        # No DB insert for Qual? Or insert as 'qualification'? 
        # User only cares about Race results usually.
        # We can skip DB insert or mark it.
        # Let's Skip DB insert for Qual to avoid "Race ID" confusion.
    else:
        logging.info(f"RACE START: {track}, Laps={laps}, Players={num_players}")
        
        # Force NPL update (Type 14 = TINY_NPL) with ReqI=1
        send_packet(struct.pack('<BBBB', 1, 3, 1, 14))

        def announce_race_start():
             time.sleep(2.0) # Wait for NPL packets to be processed
             
             car_msg = getattr(STATE, 'current_config_name', None)
             if car_msg:
                 if ' - ' in car_msg:
                     car_msg = car_msg.split(' - ', 1)[1]
             else:
                 active_cars = set()
                 with STATE.lock:
                      for ucid, p in STATE.current_race['players'].items():
                          c = p.get('car')
                          if c: active_cars.add(c)
                 
                 car_msg = None
                 if active_cars:
                     car_msg = "/".join(sorted(active_cars))
                     
             if car_msg:
                  broadcast_localized("race_start_msg", track=track, car_names=car_msg, laps=laps)
             else:
                  # If state empty, fallback to allowed but log it
                  logging.warning("Active cars empty on Race Start (Delayed). Fallback to Allowed.")
                  broadcast_localized("race_start_msg", track=track, car_names_bitmask=allowed, laps=laps)
        
        threading.Thread(target=announce_race_start, daemon=True).start()
        
        request_full_state_update()
        
        # Ensure Race ID is reset
        STATE.current_race_id = 0
        
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as c:
                    # Fetch Previous Hash
                    c.execute("SELECT signature FROM races ORDER BY id DESC LIMIT 1")
                    row = c.fetchone()
                    prev_hash = row[0] if row and row[0] else 'GENESIS'
                    
                    # Generate Signature
                    race_date_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    results_json = json.dumps([])
                    payload = f"{prev_hash}{results_json}{race_date_str}"
                    signature = hashlib.sha256(payload.encode('utf-8')).hexdigest()

                    c.execute("INSERT INTO races (results, track, allowed_cars, previous_hash, signature, race_date) VALUES (%s, %s, %s, %s, %s, %s)", 
                              (results_json, STATE.current_track, STATE.current_allowed_cars, prev_hash, signature, race_date_str))
                    STATE.current_race_id = c.lastrowid
                    conn.commit()
                # STATE.current_race_id = 0 # Dummy ID for logging
                logging.info(f"Race Started. Status: racing. Race ID: {STATE.current_race_id}")
            except Exception as e:
                logging.error(f"Error DB Race Start: {e}")
            finally:
                conn.close()
        else:
             logging.error("DB Connection failed at Race Start.")

    # Practice Mode Detection (Legacy / Fallback)
    # We now handle 'waiting_for_ready' explicitly in end_voting, but if manual /track usage:
    if qual_mins == 0 and laps == 0:
        # If we arrived here manually, we might be in practice.
        # But end_voting overrides this usually.
        with STATE.lock: 
            if STATE.current_race['status'] != 'waiting_for_ready':
                STATE.current_race['status'] = 'practice'
                logging.info("PRACTICE START (Manual?)")

def start_qual_session():
    with STATE.lock: STATE.current_race['status'] = 'qualifying' # Assume successful start? Or wait for TINY?
    broadcast_localized("qual_start_msg_header")
    laps = getattr(STATE, 'next_laps', 5)
    
    logging.info("START_QUAL_SESSION: Sending /ready...")
    
    # /ready to set ready
    commands = [
        "/ready"
    ]
    for cmd in commands:
        logging.info(f"Sending Command: {cmd}")
        send_message(cmd, 0)
        time.sleep(1.0)
        
    # Reset practice timer if it exists
    if hasattr(STATE, 'practice_timer') and STATE.practice_timer:
        STATE.practice_timer.cancel()

    # Handling Qualification Status - Removed Redundant Block (Merged above)
    # if qual_mins > 0: ... handled above


def on_result(packet: bytes):
    if len(packet) < 20: return
    # CRITICAL FIX: Ignore results if not racing (e.g. Qualification results)
    if STATE.current_race.get('status') != 'racing':
        return

    plid = packet[3]
    with STATE.lock:
        player_entry = None
        for p in STATE.current_race['players'].values():
            if p.get('plid') == plid:
                player_entry = p
                break
        
        if player_entry:
            uname = player_entry['uname']
            if not any(r['uname'] == uname for r in STATE.current_race['results']):
                # Extract time (Offset 68, uint32)
                t_time = 0
                if len(packet) >= 72:
                    t_time = struct.unpack('<I', packet[68:72])[0]

                best_lap = 0
                if len(packet) >= 76:
                    best_lap = struct.unpack('<I', packet[72:76])[0]

                STATE.current_race['results'].append({
                    'uname': uname, 
                    'car': player_entry.get('car', 'N/A'), 
                    'team_id': player_entry.get('team_id'),
                    'total_time': t_time,
                    'best_lap': best_lap
                })
                
                pos = len(STATE.current_race['results'])
                t_str = format_lap_time(t_time)
                
                broadcast_localized("race_finished_pos", uname=uname, pos=pos, t_str=t_str)
                if pos == 1:
                    broadcast_localized("race_winner", uname=uname, t_str=t_str)
                    # Flexible timeout: 110% of winner time
                    # means wait (time * 0.1) seconds
                    wait_ms = t_time * 0.10
                    wait_sec = max(30, int(wait_ms / 1000)) # Min 30s
                    
                    race_token = STATE.current_race.get('race_token')
                    threading.Thread(target=force_race_end_countdown, args=(wait_sec, race_token), daemon=True).start()
                    broadcast_localized("time_limit_warn", time=format_lap_time(int(t_time * 1.1)), wait=wait_sec)
        
        if len(STATE.current_race['results']) >= STATE.current_race['num_players_at_start'] and not STATE.current_race.get('restarting'):
            STATE.current_race['restarting'] = True
            threading.Thread(target=process_and_display_results, daemon=True).start()

def process_and_display_results():
    with STATE.lock:
        logging.info(f"Processing results. Status: {STATE.current_race['status']}, Results: {len(STATE.current_race.get('results', []))}")
        # Relaxed check: logic flow relies on results being ready.
        if STATE.current_race['status'] != 'racing' and not STATE.current_race.get('results'):
            logging.info("Ignoring result processing: Status is not 'racing' and no results.")
            # STATE.current_race['status'] = 'idle'  <-- Don't force idle, might be waiting
            return
        
        # If we have results, we proceed even if status got messed up (e.g. to 'finished' by duplicate call)
        if STATE.current_race['status'] == 'finished':
             logging.info("Results already processed (Status: finished). Ignoring.")
             return

        
        if (STATE.current_track == STATE.previous_track and
            STATE.current_allowed_cars == STATE.previous_allowed_cars):
            STATE.consecutive_races += 1
        else:
            STATE.consecutive_races = 1
            STATE.previous_track = STATE.current_track
            STATE.previous_allowed_cars = STATE.current_allowed_cars

        # Voting check moved to end to ensure results are processed first


        STATE.current_race['status'] = 'finished'
        
        # Detect DNFs (Started but not in Results)
        started = STATE.current_race.get('started_players', {})
        finished_unames = set(r['uname'] for r in STATE.current_race['results'])
        
        for p_data in started.values():
            if p_data['uname'] not in finished_unames:
                STATE.current_race['results'].append({
                    'uname': p_data['uname'],
                    'car': p_data.get('car', 'UNK'),
                    'team_id': p_data.get('team_id'),
                    'total_time': 0, # 0 = DNF
                    'best_lap': 0
                })

        for i, res in enumerate(STATE.current_race['results']): res['position'] = i + 1
        results_copy = list(STATE.current_race['results'])

    is_single_player = len(results_copy) < 2
    is_single_player = len(results_copy) < 2
    
    # --- API INTEGRATION ---
    # Prepare payload for API
    api_results = []
    for res in results_copy:
        api_results.append({
            'uname': res['uname'],
            'position': res['position'],
            'car': res.get('car', 'UNK'),
            'best_lap': res.get('best_lap', 0),    # Best lap in race (ms)
            'total_time': res.get('total_time', 0) # Total race time (ms)
        })

    payload = {
        'track': STATE.current_track,
        'server_name': "LFS Elo Bot", # Or get from config
        'results': api_results
    }
    
    logging.info("Sending race results to API...")
    response = send_to_api('process_race_results', payload)
    
    if response and response.get('status') == 'success':
        updates = response.get('updates', {})
        # Update local STATE/DB with new ELOs if needed, or just display
        broadcast_localized("results_separator")
        for res in results_copy:
            uname = res['uname']
            car = f" ({res.get('car', '')})"
            
            if uname in updates:
                new_elo = updates[uname]['new_elo']
                diff = updates[uname]['elo_diff']
                res['new_elo'] = new_elo
                res['elo_change'] = diff
                # change = f"+{diff}" if diff >= 0 else str(diff)
                # send_message(f"#{res['position']} {uname}{car}: {new_elo} ({change})")
            else:
                 res['new_elo'] = res.get('elo', 1500)
                 res['elo_change'] = 0
                 # send_message(f"#{res['position']} {uname}{car}: (Sin cambios)")
    else:
        logging.error("API failed to process results. Fallback to local (Partial).")
        broadcast_localized("api_sync_error")
        # Ensure keys exist for fallback
        for res in results_copy:
            res['new_elo'] = res.get('elo', 1500)
            res['elo_change'] = 0

    # SEND DISCORD WEBHOOK
    send_discord_webhook(results_copy, STATE.current_track)

    # UPDATE LOCAL DB FOR TEAMS ONLY (Since API might not handle teams yet?)
    # or just rely on API. The user said "quiero que funcione con la api".
    # Assuming API handles ELO/Races. Team points might be lost if API doesn't do it.
    # api_ingest.php didn't seem to have team logic.
    # I will keep LOCAL Team updates for now to be safe.
    
    conn = get_db_connection()
    if conn:
        try:
             # Just Team Points update locally
            team_points = {}
            if not is_single_player:
                num_racers = len(results_copy)
                for res in results_copy:
                    if res.get('team_id'):
                        points = num_racers - res['position'] + 1
                        team_points[res['team_id']] = team_points.get(res['team_id'], 0) + points

            with conn.cursor() as c:
                for tid, pts in team_points.items():
                    c.execute("UPDATE teams SET points = points + %s WHERE id = %s", (pts, tid))
            conn.commit()
        except Exception as e:
            logging.error(f"Error local team update: {e}")
        finally:
            conn.close()

    broadcast_localized("results_separator")
    for res in results_copy:
        car = f" ({res.get('car', '')})"
        if 'elo_change' not in res:
            res['elo_change'] = 0
            
        change = res.get('elo_change', 0)
        c_str = f"^2+{change}" if change > 0 else f"^1{change}"
        if change == 0:
             broadcast_localized("elo_no_change_msg", pos=res['position'], uname=res['uname'], car=car)
        else:
             broadcast_localized("elo_change_msg", pos=res['position'], uname=res['uname'], car=car, elo=res.get('new_elo', 1500), change=c_str)

    logging.info(f"Cons. Races: {STATE.consecutive_races} / 5")
    if STATE.consecutive_races >= 5:
        # Race 5/5 Finished -> Results shown -> Start Voting
        logging.info("Starting Voting (Race 5 Finished)")
        STATE.current_race['status'] = 'voting'
        STATE.current_voting_options = generate_random_voting_options()
        threading.Thread(target=start_voting, daemon=True).start()
    else:
        # Race X/5 Finished -> Results shown -> Restart
        logging.info("Restarting Race (Race < 5)")
        remaining = 5 - STATE.consecutive_races
        broadcast_localized("voting_remaining_msg", remaining=remaining)
        threading.Thread(target=race_restart_countdown, daemon=True).start()

def force_race_end_countdown(duration, race_token):
    """Waits 'duration' seconds after winner finishes, then ends race if still running."""
    time.sleep(duration)
    with STATE.lock:
        if STATE.current_race.get('race_token') != race_token:
            return # Race changed, abort

        if STATE.current_race['status'] == 'racing' and not STATE.current_race.get('restarting'):
             broadcast_localized("time_limit_reached")
             # Do not send /end to avoid "Results Screen" or stopping flow.
             # Just trigger logic.
             STATE.current_race['restarting'] = True
             threading.Thread(target=process_and_display_results, daemon=True).start() 

def start_voting():
    STATE.voting_active = True
    STATE.votes = {}
    send_message(get_msg('vote_started', 0))
    
    # Store End Time for UI display
    STATE.voting_end_time = time.time() + 60.0
    
    for ucid in list(STATE.current_race['players'].keys()):
        display_voting_table(ucid)
    STATE.voting_timer = threading.Timer(60.0, end_voting)
    STATE.voting_timer.start()

def end_voting():
    with STATE.lock:
        STATE.voting_active = False
        votes_copy = STATE.votes.copy()
    for ucid in STATE.current_race['players'].keys():
        clear_table(ucid)
    if not votes_copy:
        send_message(get_msg('vote_random_choice', 0))
        winner_idx = random.randrange(len(STATE.current_voting_options))
    else:
        count = Counter(votes_copy.values())
        max_votes = max(count.values())
        winners = [idx for idx, cnt in count.items() if cnt == max_votes]
        winner_idx = random.choice(winners)
    
    opt = STATE.current_voting_options[winner_idx]
    
    send_message(get_msg('vote_winner_simple', 0, name=opt['name']))
    
    # Delegate to the robust apply method
    import threading
    threading.Thread(target=lambda: set_random_configuration(source="voting", config=opt), daemon=True).start()
    
    with STATE.lock: STATE.current_race['status'] = 'waiting_for_ready'
    # Auto-start removed. Waiting for players to set ready.
    if hasattr(STATE, 'practice_timer') and STATE.practice_timer:
        STATE.practice_timer.cancel()
    STATE.practice_timer = None

def race_restart_countdown():
    broadcast_localized("restart_msg", time="10s")
    time.sleep(10)
    send_message("/restart")

def request_full_state_update():
    # TINY_NCN (13), TINY_NPL (14), TINY_MCI (17), TINY_RST (6)
    for subt in [13, 14, 17, 6]:
        send_packet(struct.pack('<BBBB', 1, 3, 1, subt))
        time.sleep(0.05)


def end_qualifying():
    with STATE.lock:
        logging.info("Qualifying ended. Displaying times and moving to race.")
        
        # 1. Get session times
        results = []
        for ucid, p in STATE.current_race['players'].items():
            if p.get('best_lap', 0) > 0:
                results.append({
                    'uname': p['uname'],
                    'car': p.get('car', 'UNK'),
                    'best_lap': p['best_lap']
                })
        
        # Sort by Best Lap ASC
        results.sort(key=lambda x: x['best_lap'])
        
        # 2. Mostrar Tabla
        broadcast_localized("results_separator")
        broadcast_localized("qual_results_title")
        for i, res in enumerate(results):
            t_str = format_lap_time(res['best_lap'])
            send_message(f"#{i+1} {res['uname']} ({res['car']}): ^2{t_str}")
        
        if not results:
            broadcast_localized("qual_no_times")

        # 3. Restart to Race
        STATE.current_race['restarting'] = True
        # Set status to waiting to prevent double triggers
        STATE.current_race['status'] = 'waiting_for_race'
    
    time.sleep(1) 
    broadcast_localized("session_finished")
    time.sleep(2)
    logging.info("Sending /restart to start race...")
    force_race_start_now()

def on_split(packet: bytes):
    if len(packet) < 16: return
    try:
        _, _, _, plid, stime, etime, split, _, _, _ = struct.unpack('<BBBBIIBBBB', packet[:16])
    except: return

    with STATE.lock:
        player = next((p for p in STATE.current_race['players'].values() if p.get('plid') == plid), None)
        if not player: return # Player not found (maybe spectating?)
        
        # Qual Overtime Check
        status = STATE.current_race['status']
        if status == 'qualifying_overtime':
            # plid is already defined from the packet
            if plid in getattr(STATE, 'qual_finishing_players', set()):
                STATE.qual_finishing_players.discard(plid)
                logging.info(f"Player {player['uname']} finished lap. Remaining: {len(STATE.qual_finishing_players)}")
                if not STATE.qual_finishing_players:
                    logging.info("All players finished qualifying overtime. Ending Qualifying.")
                    threading.Thread(target=end_qualifying, daemon=True).start()
                    return # Do not process split further if race is ending
        
        # Normal race logic
        if STATE.current_race.get('status') == 'qualifying':
             STATE.current_race['last_qual_activity'] = time.time()

             
        if 'splits' not in player: player['splits'] = []
        # Avoid duplicates
        if not any(s['split'] == split and abs(s['stime'] - stime) < 100 for s in player['splits']):
            player['splits'].append({'split': split, 'stime': stime, 'etime': etime})
        player['current_split'] = split
        player['split_time'] = stime
        save_live_data()

def on_lap(packet: bytes):
    if len(packet) < 20: return
    try:
        _, _, _, plid, laptime, etime, laps_done, flags, _, _, _, _ = struct.unpack('<BBBBIIHHBBBB', packet[:20])
        logging.info(f"LAP DEBUG: PLID={plid} Time={laptime} Flags={flags}")
    except: return

    if laptime == 0: return

    with STATE.lock:
        player = next((p for p in STATE.current_race['players'].values() if p.get('plid') == plid), None)
        track = STATE.current_track
    
    if not player: return
    
    # Qual Overtime Check
    with STATE.lock:
         status = STATE.current_race['status']
         
         if status == 'qualifying':
             STATE.current_race['last_qual_activity'] = time.time()
             
         if status == 'qualifying_overtime':
             if plid in getattr(STATE, 'qual_finishing_players', set()):
                 STATE.qual_finishing_players.discard(plid)
                 logging.info(f"Player {player['uname']} finished lap. Remaining: {len(STATE.qual_finishing_players)}")
                 if not STATE.qual_finishing_players:
                      logging.info("All players finished overtime. Ending Qualifying.")
                      threading.Thread(target=end_qualifying, daemon=True).start()

    uname = player['uname']
    car = player.get('car', 'DESCONOCIDO')
    splits = player.get('splits', [])
    player['splits'] = []
    player['laps_done'] = laps_done
    player['last_lap_time'] = laptime
    player['current_split'] = 0
    # Capture best lap for API
    if 'best_lap' not in player or laptime < player['best_lap']:
        player['best_lap'] = laptime

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor(dictionary=True) as c:
                # Only insert Lap Times if we have a valid Race ID (RACE Mode)
                if STATE.current_race_id > 0:
                    c.execute("INSERT INTO lap_times (race_id, uname, lap_number, lap_time, total_time) VALUES (%s, %s, %s, %s, %s)",
                              (STATE.current_race_id, uname, laps_done, laptime, etime))
                    
                    # Splits
                    for s in splits:
                        c.execute("INSERT INTO split_times (race_id, uname, lap_number, split_number, split_time, total_time, track, car) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                  (STATE.current_race_id, uname, laps_done, s['split'], s['stime'], s['etime'], track, car))

                # PB (Always check, even in Qual)
                c.execute("SELECT lap_time FROM personal_bests WHERE uname = %s AND track = %s AND car = %s", (uname, track, car))
                old_rows = c.fetchall()
                old = old_rows[0] if old_rows else None
                if not old or laptime < old['lap_time']:
                    c.execute("INSERT INTO personal_bests (uname, track, car, lap_time, laps_completed) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE lap_time = VALUES(lap_time), laps_completed = VALUES(laps_completed)", (uname, track, car, laptime, laps_done))
                    
                    diff_str = format_lap_time(old['lap_time'] - laptime) if old else ""
                    if old:
                        broadcast_localized("impr_pb", uname=uname, track=track, car=car, time=format_lap_time(laptime), diff=diff_str)
                    else:
                        broadcast_localized("new_pb", uname=uname, track=track, car=car, time=format_lap_time(laptime))

                # WR
                c.execute("SELECT lap_time FROM track_records WHERE track = %s AND car = %s", (track, car))
                wr_rows = c.fetchall()
                wr = wr_rows[0] if wr_rows else None
                if not wr or laptime < wr['lap_time']:
                    c.execute("INSERT INTO track_records (track, car, uname, lap_time, laps_completed) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE lap_time = VALUES(lap_time), uname = VALUES(uname), laps_completed = VALUES(laps_completed)", (track, car, uname, laptime, laps_done))
                    broadcast_localized("sys_record_msg", uname=uname, track=track, time=format_lap_time(laptime))
                
            conn.commit()
        except Exception as e:
            logging.error(f"Error on_lap DB: {e}")
        finally:
            conn.close()
    save_live_data()

def format_lap_time(ms: int) -> str:
    if ms <= 0: return "0.000"
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{minutes}:{seconds:02d}.{millis:03d}" if minutes > 0 else f"{seconds}.{millis:03d}"

def save_live_data():
    try:
        data = {
            'server_name': getattr(STATE, 'server_name', 'LFS Server'),
            'status': STATE.current_race.get('status', 'offline'),
            'track': STATE.current_track,
            'allowed_cars': getattr(STATE, 'current_allowed_cars', 0),
            'consecutive_races': getattr(STATE, 'consecutive_races', 0),
            'allowed_cars_filter': getattr(STATE, 'allowed_cars_filter', None),
            'players': {},
            'results': STATE.current_race.get('results', [])
        }
        with STATE.lock:
            for ucid, p in STATE.current_race['players'].items():
                data['players'][ucid] = {
                    'uname': p['uname'],
                    'car': p.get('car', 'N/A'),
                    'position': p.get('position', 0),
                    'lap': p.get('laps_done', 0) + 1,
                    'last_lap': format_lap_time(p.get('last_lap_time', 0)),
                    'split': format_lap_time(p.get('split_time', 0)) if p.get('current_split') else '-'
                }
        
        file_path = os.path.join(ARGS.web_dir, 'current_race.json')
        temp_path = file_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f)
        os.replace(temp_path, file_path)
    except: pass

def json_save_loop():
    last_api_update = 0
    while True:
        save_live_data()
        
        # API Server Status Update (Every 2s for instant toggle)
        if time.time() - last_api_update > 2 and (ARGS.api_key or getattr(STATE, 'identity', None)):
            try:
                logging.info(f'Sending API Heartbeat Name: {STATE.server_name}')
                server_info = {
                    'ip': ARGS.host,
                    'port': ARGS.insim_port,
                    'name': STATE.server_name,
                    'track': STATE.current_track,
                    'status': STATE.current_race.get('status', 'unknown'),
                    'players': []
                }
                with STATE.lock:
                    for p in STATE.current_race['players'].values():
                        # Format similar to save_live_data but for API
                        p_data = {
                            'uname': p['uname'],
                            'car': p.get('car', 'N/A'),
                            'position': p.get('position', 0),
                            'lap': p.get('laps_done', 0) + 1,
                            'last_lap': format_lap_time(p.get('last_lap_time', 0)),
                            'split': format_lap_time(p.get('split_time', 0)) if p.get('current_split') else '-'
                        }
                        server_info['players'].append(p_data)
                        
                resp = send_to_api('update_server_status', server_info)
                # CONFIG SYNC
                if resp and isinstance(resp, dict) and 'config' in resp and resp['config']:
                    new_cfg = resp['config']
                    with STATE.lock:
                        # Merge or Replace? Merge for safety.
                        STATE.config.update(new_cfg)
                        if 'admins' in new_cfg and isinstance(new_cfg['admins'], list):
                            # Append to existing env admins so both work
                            admins_env = os.environ.get('LFS_ADMINS', "")
                            env_list = [a.strip() for a in admins_env.split(',') if a.strip()]
                            STATE.admin_list = list(set(env_list + new_cfg['admins']))
                # No excessive logging for sync to avoid spam, maybe debug
                pass
                
            except Exception as e:
                logging.error(f"Error sending server status: {e}")
        
        time.sleep(1)

def main_loop():
    while True:
        try:
            STATE.insim_sock = connect_insim(ARGS.host, ARGS.insim_port, ARGS.admin)
            if STATE.insim_sock:
                request_full_state_update()
                receiver = threading.Thread(target=receive_packets, args=(STATE.insim_sock,), daemon=True)
                receiver.start()
                
                while receiver.is_alive():
                    time.sleep(1)
        except Exception:
            logging.exception("Critical Error")
        time.sleep(20)

def request_full_state_update():
    """Requests full state update (NCN + PLR + RST + ISM) from InSim."""
    if not STATE.insim_sock: return
    try:
        logging.info("Requested full state update (NCN + PLR + RST + ISM)")
        # TINY_NCN (13), TINY_NPL (14), TINY_SST (7), TINY_ISM (10)
        send_packet(struct.pack('<BBBB', 1, 3, 1, 13)) # NCN
        time.sleep(0.1)
        send_packet(struct.pack('<BBBB', 1, 3, 1, 14)) # NPL
        time.sleep(0.1)
        send_packet(struct.pack('<BBBB', 1, 3, 1, 7))  # SST (provides Track via ISP_STA)
        time.sleep(0.1)
        send_packet(struct.pack('<BBBB', 1, 3, 1, 10)) # ISM
    except Exception as e:
        logging.error(f"Error requesting full update: {e}")

def setup_args():
    if '--generate_identity' in sys.argv:
        generate_identity()
        sys.exit(0)
    if '--register_node' in sys.argv:
        idx = sys.argv.index('--register_node')
        name = sys.argv[idx+1]
        if '--api_url' not in sys.argv:
            print('Error: --api_url is required for registration')
            sys.exit(1)
        idx_api = sys.argv.index('--api_url')
        api_url = sys.argv[idx_api+1]
        class DummyArgs:
            pass
        global ARGS
        ARGS = DummyArgs()
        ARGS.api_url = api_url
        register_node(name)
        sys.exit(0)
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--insim_port', type=int, required=True)
    parser.add_argument('--admin', default='')
    parser.add_argument('--db_host', default='localhost')
    parser.add_argument('--db_user', default='root')
    parser.add_argument('--db_pass', default=None, help='Database Password')
    parser.add_argument('--db_name', default='lfs_elo', help='Database Name')
    parser.add_argument('--web_dir', default='/var/www/html', help='Web Directory')
    parser.add_argument('--api_url', default='https://validator.lfsrank.com/ingest', help='API URL')
    parser.add_argument('--api_key', default='', help='API Key')
    parser.add_argument('--invite_token', default='', help='Server registration token')

    parser.add_argument('--generate_identity', action='store_true', help='Generate Ed25519 identity keys')
    parser.add_argument('--register_node', type=str, help='Register this node on the network with the given server name')

    return parser.parse_args()




# --- NEW COMMANDS (MODS/ALLCARS) ---
def cmd_list_mods(ucid: int):
    if not STATE.mods:
         return send_message("^3No hay mods configurados.", ucid)
    msg = "^3Mods Configurados: "
    for m in STATE.mods:
        msg += f"^7{m['name']} ({m['id']}), "
    send_message(msg[:-2], ucid)

def cmd_setmod(ucid: int, args: list):
    if not args: return send_message("^1Uso: !setmod <ModID/Nombre>", ucid)
    query = " ".join(args).upper()
    
    mod_id = None
    if query in STATE.mod_map: mod_id = query
    elif query in STATE.mod_map.values():
        for mid, name in STATE.mod_map.items():
            if name == query:
                mod_id = mid
                break
    
    if not mod_id:
        for m in STATE.mods:
            if m['name'].upper() == query or m['id'] == query:
                mod_id = m['id']
                break
    
    if not mod_id and len(query) == 6: mod_id = query
        
    if mod_id:
        send_message(f"/allowmod {mod_id}")
        send_message(f"^2Mod {mod_id} permitido.")
    else:
        send_message("^1Mod no encontrado.")

# --- BADCOMBO SYSTEM ---
REPORT_REASONS = {
    1: {"text": "Car without lights (Night)", "desc": "Night track without lights"},
    2: {"text": "No dirt tires (RallyX)", "desc": "Car unsuitable for dirt"},
    3: {"text": "Car too big (Karting)", "desc": "Car too wide/long"}
}

def cmd_badcombo(ucid: int):
    # Determine page state
    headers = ["Reason", "Description", "Report"]
    data = []
    
    # Reasons 1, 2, 3
    # ID base for buttons: 300 + reason_id or use row logic.
    # We will use row logic (Col 2 clicks).
    
    for rid, info in REPORT_REASONS.items():
        data.append([
            f"^3{info['text']}",
            f"^7{info['desc']}",
            f"^1[REPORTAR]"
        ])
    
    PAGE_STATE[ucid] = {'cmd': '!badcombo', 'rows': list(REPORT_REASONS.items()), 'page': 1}
    display_table_with_menu(ucid, "Report Combo", headers, data, "!badcombo")

def handle_badcombo_click(ucid: int, click_id: int):
    # Table click IDs: 100 + row*10 + col
    # Col 2 is Report button.
    # Row 0 -> 102 (Reason 1)
    # Row 1 -> 112 (Reason 2)
    # Row 2 -> 122 (Reason 3)
    
    if click_id % 10 == 2:
        row_idx = (click_id - 100) // 10
        # Check bounds
        rids = list(REPORT_REASONS.keys())
        if 0 <= row_idx < len(rids):
            reason_id = rids[row_idx]
            r = REPORT_REASONS[reason_id]
            
            logging.info(f"REPORT BADCOMBO: User {ucid} ({STATE.current_race['players'][ucid]['uname']}) reported: {r['text']}")
            
            # API Report (Global Consensus)
            payload = {
                'action': 'report_combo',
                'track': STATE.current_track,
                'car': STATE.current_allowed_cars,
                'reason': r['text'],
                'reporter': STATE.current_race['players'][ucid]['uname'],
                'reporter_ucid': ucid
            }
            # Run in thread to not block
            threading.Thread(target=send_to_api, args=('report_combo', payload)).start()
            
            
            send_message(f"^2Reporte enviado: ^7{r['text']}", ucid)
            clear_table(ucid)
            
            # Trigger VOTE SKIP if not active
            if not STATE.active_vote:
                p_count = len(STATE.current_race['players'])
                if p_count < 1: p_count = 1
                
                vote_ratio = float(STATE.config.get('vote_ratio', 0.5))
                needed = int(p_count * vote_ratio) + 1
                vote_dur = float(STATE.config.get('vote_duration', 60.0))
                
                STATE.active_vote = {
                    'type': 'skip',
                    'initiator': ucid,
                    'expires': time.time() + vote_dur,
                    'votes': {ucid},
                    'needed': needed,
                    'reason': r['text'] # Store reason
                }
                
                uname = STATE.current_race['players'][ucid]['uname']
                msg = f"^3Vote started by ^7{uname}^3 to SKIP COMBO (Report: {r['text']}). ^7!vote y / !vote n"
                send_message(msg, 0)
                
                check_vote_pass()
            else:
                 send_message("^1There is already a vote in progress.", ucid)

def cmd_allcars(ucid: int):
    logging.info("ACTIVATING ALL CARS + MODS")
    send_message("/cars all")
    send_message("/mid 1")
    count = 0
    for m in STATE.mods:
        if m.get('id'):
            send_message(f"/allowmod {m['id']}")
            count += 1
            time.sleep(0.05)
    send_message(f"^2All standard cars and {count} mods allowed!")

# --- VOTING LOGIC ---
def cmd_vote(ucid: int, args: list):
    # If voting is active, allow casting vote via chat
    if getattr(STATE, 'voting_active', False):
        if not args:
            send_message("^3Usa !vote 1, !vote 2, etc. o haz clic en los botones.", ucid)
            return
            
        if args[0].isdigit():
            opt_idx = int(args[0]) - 1
            if 0 <= opt_idx < len(STATE.current_voting_options):
                with STATE.lock:
                    STATE.votes[ucid] = opt_idx
                send_message("^2Voto registrado.", ucid)
                display_voting_table(ucid)
                
                # Check if everyone voted
                with STATE.lock:
                    if len(STATE.votes) >= len(STATE.current_race['players']):
                        # End early
                        if hasattr(STATE, 'voting_timer') and STATE.voting_timer:
                             STATE.voting_timer.cancel()
                        import threading
                        threading.Thread(target=end_voting, daemon=True).start()
            else:
                send_message("^1Invalid option.", ucid)
        return
        
    # If voting is NOT active, only admins can force it early
    uname = ""
    with STATE.lock:
        if ucid in STATE.current_race.get('players', {}):
             uname = STATE.current_race['players'][ucid].get('uname', '')
             
    if not is_admin(uname, ucid):
        send_message("^1No active vote. (Will pop up at the end of round)", ucid)
        return
        
    # Admin forces vote
    send_message("^3The Administrator has forced a track vote!")
    with STATE.lock:
        STATE.current_race['status'] = 'voting'
        STATE.current_voting_options = generate_random_voting_options()
    import threading
    threading.Thread(target=start_voting, daemon=True).start()

if __name__ == '__main__':
    ARGS = setup_args()
    
    # --- Auto-generate identity & Interactive Invite Flow ---
    if not ARGS.api_key and not __import__('os').path.exists('identity.json'):
        if not ARGS.invite_token:
            print("=== LFSRank Server Setup ===")
            print("No identity found. If you have an invite token, you can join the decentralized network.")
            print("To get a token, type '!register' -> 'Registrar Servidor' on any trusted LFSRank server.")
            token = input("Enter your invite token (or press Enter to skip): ").strip()
            if token: 
                ARGS.invite_token = token
        
        import cryptography.hazmat.primitives.serialization as serialization
        print("Generating Ed25519 Identity...")
        priv_key = ed25519.Ed25519PrivateKey.generate()
        pub_key = priv_key.public_key()
        priv_bytes = priv_key.private_bytes(encoding=serialization.Encoding.Raw, format=serialization.PrivateFormat.Raw, encryption_algorithm=serialization.NoEncryption())
        pub_bytes = pub_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        
        identity = {"private_key": priv_bytes.hex(), "public_key": pub_bytes.hex()}
        with open("identity.json", "w") as f:
            json.dump(identity, f, indent=4)
        print(f"Identity created! Public Key: {pub_bytes.hex()}")
        
        STATE.identity = identity
        
        if ARGS.invite_token:
            srv_name = input("Enter your server's name: ").strip() or "New Server"
            print(f"Redeeming token {ARGS.invite_token}...")
            # We need to send this to the API. 
            # We manually bypass send_to_api because send_to_api signs the request automatically if identity exists, 
            # but redeem_server_token does NOT require signature (or rather, the server isn't trusted yet so the validator will reject it if we sign and it fails).
            # Actually, the validator ignores the signature if action is redeem_server_token.
            resp = send_to_api('redeem_server_token', {'token': ARGS.invite_token, 'new_name': srv_name, 'new_key': pub_bytes.hex()})
            if resp and resp.get('status') == 'success':
                print(f"SUCCESS: {resp.get('message')}")
            else:
                err = resp.get('message', 'Unknown Error') if resp else 'Network Error'
                print(f"FAILED: {err}")
                print("Continuing as an untrusted node...")
            print("===========================\n")
            time.sleep(2)
            
    if not ARGS.api_key and getattr(STATE, 'identity', None) is None and __import__('os').path.exists('identity.json'):
        with open('identity.json', 'r') as f:
            STATE.identity = __import__('json').load(f)
    STATE.load_persistence() #    # Start Threads
    
    t_save = threading.Thread(target=json_save_loop, daemon=True)
    t_save.start()

    t_preload = threading.Thread(target=preload_rankings_loop, daemon=True)
    t_preload.start()
    main_loop()
