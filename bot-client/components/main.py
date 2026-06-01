import socket
import logging
import time
import struct
import threading
import sys

from .state import STATE, ARGS
from .insim import clean_string, ISP_MSO, ISP_RST, ISP_RES, ISP_NPL, ISP_MTC, ISP_BTN, ISP_BTC, ISP_NCN, ISP_LAP, ISP_STA, ISP_ISM
from .commands import handle_command
from .events import on_race_start, on_result, on_new_player, on_new_connection, on_lap
from .tables import on_button_click
from .scheduler import scheduler_loop

def connect_insim():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)

        # Clear State on (Re)Connect to prevent Ghost Players
        with STATE.lock:
             STATE.connections.clear()
             STATE.current_race['players'].clear()
             STATE.current_race['results'] = []
             STATE.active_buttons.clear() # Clear button tracking too

        sock.connect((ARGS.host, ARGS.port))
        
        admin_pass = ARGS.admin_pass.encode('latin-1')
        iname = b"LFS Open Rank"
        # Let struct package pad them
        
        # IS_ISI
        # Flags:
        # 1: RES (Result)
        # 2: NLP (Node Lap)
        # 4: MCI (Multi Car Info)
        # 8: CON (Connection)
        # 16: OBH (Object Hit)
        # 32: HL (Hot Lap)
        # 64: AXM (AutoX)
        # 2048: MSO_COLS (Msg Colors)
        # Flags: 1 (RES) | 32 (HL) = 33
        # Matches system2.py configuration
        flags = 33
        interval = 200
        prefix = 0 # Matches system2.py
        
        # InSim Ver 9 (as per system2.py)
        packet = struct.pack('<BBBBHHBBH16s16s', 11, 1, 1, 0, 0, flags, 9, prefix, interval, admin_pass, iname)
        sock.sendall(packet)
        STATE.insim_sock = sock
        logging.info(f"Connected to InSim (Ver 9, Size 11, Flags {flags})")
        
        # Request Info (TINY_ISM) - SubT 10
        sock.sendall(struct.pack('<BBBB', 1, 3, 1, 10))
        # TINY_SST (7) Removed - Causes Disconnect Loop on this server
        # Request Connections (TINY_NCN) - SubT 13
        sock.sendall(struct.pack('<BBBB', 1, 3, 1, 13))
        # Request Players (TINY_NPL) - SubT 14
        sock.sendall(struct.pack('<BBBB', 1, 3, 1, 14))
        
        sock.settimeout(None) # Disable timeout for receive loop
        return True
    except Exception as e:
        logging.error(f"Connection failed: {e}")
        time.sleep(30) # Anti-Ban wait: Increased to 30s
        return False

def handle_packet(packet: bytes):
    if len(packet) < 4: return
    ptype = packet[1]
    
    if ptype == ISP_MSO:
        if len(packet) < 8: return
        ucid = packet[4] # Fixed: UCID is at offset 4 (offset 3 is Zero)
        text_start = packet[7]
        raw_msg = packet[8:]
        msg = clean_string(raw_msg)
        
        logging.info(f"MSO: UCID={ucid} TextStart={text_start} Msg='{msg}' Raw='{raw_msg}'")
        
        # Helper: If TextStart is valid, slice from it?
        # InSim MSO: Msg contains "User: Message". TextStart is index of M.
        # But TextStart is index relative to... Msg start?
        # Let's try slicing if TextStart > 0
        
        # If msg starts with !, it might be hidden msg.
        if msg.startswith('!'):
            handle_command(ucid, msg)
        elif text_start > 0:
            # Try to extract actual text
            # packet[8 + text_start :]
            # But clean_string might have stripped nulls.
            # Let's clean the sliced raw bytes.
            actual_msg_bytes = raw_msg[text_start:]
            actual_msg = clean_string(actual_msg_bytes)
            logging.info(f"MSO Sliced: '{actual_msg}'")
            if actual_msg.startswith('!'):
                 handle_command(ucid, actual_msg)
            
    elif ptype == ISP_RST:
        logging.info(f"RST RAW: {packet.hex()}")
        on_race_start(packet)
    elif ptype == ISP_RES:
        logging.info(f"RES RAW: {packet.hex()}")
        on_result(packet)
    elif ptype == ISP_NCN:
        on_new_connection(packet)
    elif ptype == ISP_NPL:
        on_new_player(packet)
    elif ptype == ISP_BTC: # Button Click
        on_button_click(packet)
    elif ptype == ISP_LAP:
        logging.info(f"LAP RAW: {packet.hex()}")
        on_lap(packet)
    elif ptype == ISP_ISM:
        # Host Name is at offset 8 (32 bytes)
        # Struct: Size(1), Type(1), ReqI(1), Zero(1), Host(1), Prom(1), UCID(1), Zero(1), HName(32)
        if len(packet) >= 40:
             raw_name = packet[8:40]
             sname = clean_string(raw_name)
             STATE.server_name = sname
             logging.info(f"Server Name Updated: {sname}")
    elif ptype == ISP_STA:
        from .events import on_state
        on_state(packet)

def receive_loop():
    buffer = b''
    while STATE.running:
        if not STATE.insim_sock:
             time.sleep(1)
             # Try reconnect?
             if not connect_insim():
                 time.sleep(5)
             continue
             
        try:
            data = STATE.insim_sock.recv(4096)
            if not data:
                logging.info("Disconnected.")
                STATE.insim_sock = None
                continue
                
            buffer += data
            while len(buffer) >= 4:
                # Standard InSim: Size byte is Size/4.
                # So PacketLen = buffer[0] * 4.
                p_len = buffer[0] * 4
                if len(buffer) < p_len: break
                
                packet = buffer[:p_len]
                buffer = buffer[p_len:]
                
                try:
                    handle_packet(packet)
                except Exception as e:
                    logging.error(f"Packet Error: {e}")
                    
        except Exception as e:
            logging.error(f"Recv Error: {e}")
            STATE.insim_sock = None

def main():
    # Load .env (Manual Parse)
    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

    # Update ARGS from Env
    ARGS.host = os.getenv('INSIM_HOST', '127.0.0.1')
    ARGS.port = int(os.getenv('INSIM_PORT', 29999))
    ARGS.admin_pass = os.getenv('INSIM_ADMIN_PASS', '')
    ARGS.api_key = os.getenv('API_KEY', '')
    ARGS.api_url = os.getenv('API_URL', 'http://127.0.0.1:8080/api')

    # Config Logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    logging.info(f"Starting Bot... Connecting to {ARGS.host}:{ARGS.port}")
    
    if not connect_insim():
        # Keep trying in loop or exit
        logging.error("Initial connection failed.")
    
    t = threading.Thread(target=receive_loop, daemon=True)
    t.start()
    
    t_sched = threading.Thread(target=scheduler_loop, daemon=True)
    t_sched.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        STATE.running = False


if __name__ == "__main__":
    main()
