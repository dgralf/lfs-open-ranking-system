import struct
import socket
import logging
from .state import STATE

# Packet Types
ISP_ISI = 1
ISP_VER = 2
ISP_TINY = 3
ISP_SMALL = 4
ISP_STA = 5
ISP_ISM = 10
ISP_MSO = 11
ISP_III = 12
ISP_MST = 13
ISP_MTC = 14
ISP_VTN = 16
ISP_RST = 17
ISP_NCN = 18
ISP_CNL = 19
ISP_CPR = 20
ISP_NPL = 21

import threading
import urllib.request
import re

def resolve_mod_name_from_web(mod_id: str):
    url = f"https://www.lfs.net/files/vehmods/{mod_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        match = re.search(r'<title>.*?Vehicle Mods - (.*?)</title>', html, re.IGNORECASE)
        if not match: match = re.search(r'<h1>(.*?)</h1>', html, re.IGNORECASE)
            
        if match:
            mod_name = match.group(1).strip()
            logging.info(f"Resolved Mod {mod_id} -> {mod_name}")
            # Update players with this ID
            with STATE.lock:
                for u, p in STATE.current_race['players'].items():
                    if p.get('car_id') == mod_id:
                        p['car'] = mod_name
    except Exception as e:
        logging.error(f"Mod Resolve Error {mod_id}: {e}")

def expand_mod_id(cname_bytes: bytes) -> str:
    if len(cname_bytes) > 3: cname_bytes = cname_bytes[:3]
    if len(cname_bytes) < 3: return "???"
    
    try:
        s = cname_bytes.decode('latin-1')
        if s.isalnum() and s.isascii(): return s
    except: pass
    
    val = int.from_bytes(cname_bytes, 'little')
    mod_id = f"{val:06X}"
    
    # Trigger resolution
    threading.Thread(target=resolve_mod_name_from_web, args=(mod_id,), daemon=True).start()
    return mod_id
ISP_PLP = 22
ISP_PLL = 23
ISP_LAP = 24
ISP_SPX = 25
ISP_PIT = 26
ISP_PSF = 27
ISP_PLA = 28
ISP_CCH = 29
ISP_PEN = 30
ISP_TOC = 31
ISP_FLG = 32
ISP_PFL = 33
ISP_FIN = 34
ISP_RES = 35
ISP_REO = 36
ISP_NLP = 37
ISP_MCI = 38
ISP_BFN = 42
ISP_AXI = 43
ISP_AXO = 44
ISP_BTN = 45
ISP_BTC = 46
ISP_BTT = 47

# Button Styles
ISB_C1 = 1
ISB_C2 = 2
ISB_C3 = 4
ISB_CLICK = 8
ISB_LIGHT = 16
ISB_DARK = 32
ISB_LEFT = 64
ISB_RIGHT = 128
ISB_COLOR_LIGHT_GREY = 0
ISB_COLOR_TITLE      = 1
ISB_COLOR_UNSELECTED = 2
ISB_COLOR_SELECTED   = 3
ISB_COLOR_OK         = 4
ISB_COLOR_CANCEL     = 5
ISB_COLOR_STRING     = 6
ISB_COLOR_UNAVAILABLE= 7

def send_packet(packet: bytes):
    if STATE.insim_sock:
        try:
            STATE.insim_sock.sendall(packet)
        except (BrokenPipeError, OSError) as e:
            logging.error(f"Failed to send packet: {e}. Marking connection dead.")
            STATE.insim_sock = None

def send_message(msg: str, ucid: int = 0):
    """Sends a message to a specific connection or globally. FIXES APPLIED."""
    # Ensure encoding
    try:
        msg_bytes = msg.encode('latin-1')
    except:
        msg_bytes = msg.encode('utf-8', errors='ignore')

    if ucid > 0:
        # IS_MTC (Msg To Connection) - Type 14
        # Max message 128 bytes incl zero
        msg_bytes = (msg_bytes[:127] + b'\x00')
        total_len = 8 + len(msg_bytes)
        padding = (4 - (total_len % 4)) % 4
        msg_bytes_padded = msg_bytes + (b'\x00' * padding)
        total_size = 8 + len(msg_bytes_padded)
        
        # FIX: Size is in bytes, BUT InSim spec says "Size: 4. N = 4 * Size"
        # Wait, check documentation in system.py prompt:
        # "The first byte is the size of the packet... value * 4 = real size?"
        # NO. "The first byte is the size of the packet" usually means Size*4 in standard InSim?
        # Let's check system.py usage: `total_size // 4`.
        # BUT system2.py also used `total_size // 4`.
        # However, the user said system2 was better/newer.
        # The IS_MST (Global Msg) uses `17` (which is 68 bytes / 4).
        # So `// 4` IS CORRECT for InSim protocol "Size" byte.
        # THE BUG IN SYSTEM.PY WAS likely sending `pkt_size` that wasn't a multiple or incorrect struct.
        # Wait. system.py MST struct: `pack('<BBBB64s', 17, ...)` -> 17*4=68. Correct.
        # Why did I think there was a bug?
        # Ah, maybe system2.py had it right or system.py was misaligned?
        # Let's verify IS_MTC.
        # IS_MTC is variable size.
        # system2.py: `pack(..., total_size // 4, ...)`
        # This seems correct for InSim.
        
        # HOWEVER, the log showed "Broken Pipe" on `!rank` which sends IS_MST or IS_MTC?
        # `IS_MST` (Global) -> 68 bytes.
        # `IS_MTC` (User) -> Variable.
        
        # Let's stick to standard `// 4` sizing but ensure padding is PERFECT.
        
        packet = struct.pack(f'<BBBBBBBB{len(msg_bytes_padded)}s', 
                             total_size // 4, ISP_MTC, 0, 0, ucid, 0, 0, 0, msg_bytes_padded)
    else:
        # IS_MST (Msg Type) - Type 13 - Global Msg
        # Fixed size 64 bytes msg. Struct size 68 bytes.
        msg_bytes = (msg_bytes[:63] + b'\x00')
        # MSG is 64 bytes (last being zero).
        # Struct: Size(1), Type(1), ReqI(1), Zero(1), Msg(64). Total 68.
        # 68 / 4 = 17.
        packet = struct.pack('<BBBB64s', 17, ISP_MST, 0, 0, msg_bytes)
    
    send_packet(packet)

def clean_string(data) -> str:
    try:
        if isinstance(data, str):
            return data.strip()
        decoded = data.decode('latin-1', errors='ignore')
        return decoded.split('\x00')[0].strip()
    except:
        return ""

def format_lap_time(ms: int) -> str:
    if not isinstance(ms, (int, float)): return "-"
    if ms == 0: return "-"
    ms = int(ms)
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    hundredths = (ms % 1000) // 10
    return f"{minutes}:{seconds:02d}.{hundredths:02d}"

# --- Button Utils ---

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
    
    # Smart Tracking
    if ucid not in STATE.active_buttons:
        STATE.active_buttons[ucid] = set()
    STATE.active_buttons[ucid].add(click_id)
    
    return req_i

def clear_table(ucid: int):
    # Smart Clear: Only delete buttons we know are active.
    # Prevents flooding (SubT 1 loop) and overlapping (SubT 2 failure).
    if ucid in STATE.active_buttons and STATE.active_buttons[ucid]:
        # Copy set to iterate (though we clear it after)
        # Using list to avoid runtime change issues if concurrency
        buttons_to_clear = list(STATE.active_buttons[ucid])
        
        for click_id in buttons_to_clear:
            try:
                # SubT 1 (BFN_DEL_BTN)
                send_packet(struct.pack('<BBBBBBBB', 2, ISP_BFN, 0, 1, ucid, click_id, 0, 0))
            except: pass
            
        STATE.active_buttons[ucid].clear()
    else:
        # Fallback if no tracking (e.g. after restart): Try safe range or Clear All?
        # Use Clear All (SubT 2) as fallback, although "unreliable" it's better than nothing.
        try:
             send_packet(struct.pack('<BBBBBBBB', 2, ISP_BFN, 0, 2, ucid, 0, 0, 0))
        except: pass

    if ucid in STATE.close_buttons: del STATE.close_buttons[ucid]
    if ucid in STATE.menu_buttons: del STATE.menu_buttons[ucid]

