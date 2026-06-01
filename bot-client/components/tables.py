from typing import List, Any
import time
import logging
import traceback
from .state import STATE
from .insim import (create_button, clear_table, ISB_DARK, ISB_LIGHT, ISB_CLICK, 
                   ISB_LEFT, ISB_COLOR_UNAVAILABLE, ISB_COLOR_TITLE, 
                   ISB_COLOR_CANCEL, ISB_COLOR_STRING, ISB_COLOR_SELECTED, 
                   ISB_COLOR_UNSELECTED)
# Removed local logging imports later

# --- Translations (Ported from system.py) ---
TRANSLATIONS = {
    'es': {
        'rank_pos': "^0Pos", 'rank_player': "^0Piloto", 'rank_wins': "^0Victorias", 'rank_elo': "^0ELO",
        'header_track': "^0Pista", 'header_car': "^0Coche", 'header_pilot': "^0Piloto", 'header_time': "^0Tiempo",
        'header_pos': "^0#", 'header_points': "^0Puntos", 'header_team': "^0Equipo", 'header_name': "^0Nombre",
        'header_nation': "^0Pais", 'header_members_short': "^0Mems",
        'top_wr_title': "Récords del Sistema", 'rank_title': "Ranking de Pilotos", 'topwins_title': "Top Victorias",
        'teams_rank_title': "Ranking de Equipos", 'nations_rank_title': "Ranking de Paises",
        'no_teams': "No hay equipos", 'err_no_data': "No hay datos.", 'err_track_car': "Debes estar en pista.",
        'cmd_cmd': "^0Comando", 'cmd_desc': "^0Descripción", 'help_title': "^1Comandos Disponibles",
        'btn_rank': "[Rank]", 'btn_topwins': "[Top Wins]", 'btn_topcars': "[Top Cars]",
        'btn_mypb': "[Mis PB]", 'btn_sr': "[Récords]", 'btn_teams': "[Equipos]", 'btn_nations': "[Países]",
    },
    'en': {
        'rank_pos': "^0Pos", 'rank_player': "^0Driver", 'rank_wins': "^0Wins", 'rank_elo': "^0ELO",
        'header_track': "^0Track", 'header_car': "^0Car", 'header_pilot': "^0Driver", 'header_time': "^0Time",
        'header_pos': "^0#", 'header_points': "^0Points", 'header_team': "^0Team", 'header_name': "^0Name",
        'header_nation': "^0Nation", 'header_members_short': "^0Mems",
        'top_wr_title': "System Records", 'rank_title': "Driver Ranking", 'topwins_title': "Wins Ranking",
        'teams_rank_title': "Teams Ranking", 'nations_rank_title': "Nations Ranking",
        'no_teams': "No teams found", 'err_no_data': "No data found.", 'err_track_car': "Must be on track.",
        'cmd_cmd': "^0Command", 'cmd_desc': "^0Description", 'help_title': "^1Available Commands",
        'btn_rank': "[Rank]", 'btn_topwins': "[Top Wins]", 'btn_topcars': "[Top Cars]",
        'btn_mypb': "[My PB]", 'btn_sr': "[Records]", 'btn_teams': "[Teams]", 'btn_nations': "[Nations]",
    }
}




def get_msg(key: str, ucid: int=0, **kwargs):
    # Determine language (stub: default ES)
    # In a full system, we'd check STATE.players[ucid].language
    lang = 'es' 
    t = TRANSLATIONS.get(lang, TRANSLATIONS['es'])
    msg = t.get(key, key) # Return key if missing
    try:
        return msg.format(**kwargs)
    except:
        return msg

# Local clear_table removed to use insim.clear_table (SubT 2)
# def clear_table(ucid: int): ...


def create_menu_buttons(ucid: int, current_cmd: str, start_y: int, req_i_counter: list):
    buttons = [
        ("!rank", "[Rank]", 200),
        ("!topwins", "[Top Wins]", 201),
        ("!topcars", "[Top Cars]", 202),
        ("!mypb", "[My PB]", 203),
        ("!sr", "[Records]", 204),
        ("!teams", "[Teams]", 205),
        ("!nations", "[Nations]", 206)
    ]
    req_is = {}
    
    cols = 4
    col_width = 25
    y = start_y
    base_x = 10 
    
    for i, (cmd, text, click_id) in enumerate(buttons):
        # Ensure click_id is within range. We hardcoded 200-206 which is fine.
        if cmd == current_cmd: continue
        
        row = i // cols
        col = i % cols
        
        x = base_x + (col * col_width)
        btn_y = y + (row * 5)
        
        style = ISB_LIGHT | ISB_CLICK | ISB_COLOR_UNSELECTED
        req_i = create_button(click_id, style, x, btn_y, col_width - 1, 4, text, ucid, req_i_counter)
        req_is[cmd] = req_i
    
    STATE.menu_buttons[ucid] = req_is

def display_table_with_menu(ucid: int, title: str, headers: List[str], data: List[List[str]], source_cmd: str, page: int = 1, total_pages: int = 1, context_data: Any = None, commands: List[str] = None):
    try:
        logging.info(f"Display Table: '{title}' for UCID {ucid} ({len(data)} rows)")
        # Context preservation logic
        if context_data is None:
            existing = STATE.page_state.get(ucid)
            if existing and existing.get('cmd') == source_cmd and 'context_rows' in existing:
                 context_data = existing['context_rows']
    
        clear_table(ucid)
        time.sleep(0.2)
        
        req_i_counter = [1]
        
        # FIX: Limit Rows to avoid ID Collision with Menu (ID 200+)
        # Start ID 70. 70 + 12*10 = 190. Safe.
        # 70 + 13*10 = 200. COLLISION.
        MAX_ROWS = 12
        if len(data) > MAX_ROWS:
            data = data[:MAX_ROWS]
            
        base_l, table_w, title_w, close_l = 10, 140, 130, 10 + 140 - 8
        bg_height = 8 + (len(data) + 1) * 5 + 25
    
        # 1. Background
        create_button(50, ISB_DARK | ISB_COLOR_UNAVAILABLE, base_l, 70, table_w, bg_height, "", ucid, req_i_counter)
        
        # Back Button REMOVED per user request
        
        # 2. Title
        title_text = f"{title} ^7({page}/{total_pages})" if total_pages > 1 else title
        create_button(51, ISB_DARK | ISB_COLOR_TITLE, base_l + 2, 71, title_w, 4, title_text, ucid, req_i_counter)
        
        # 3. Close
        close_req_i = create_button(52, ISB_LIGHT | ISB_CLICK | ISB_COLOR_CANCEL, close_l, 71, 6, 4, "[X]", ucid, req_i_counter)
        STATE.close_buttons[ucid] = close_req_i
    
        # Column Widths
        if len(headers) == 4:
             col_widths = [int((table_w - 4) * 0.15), int((table_w - 4) * 0.45), int((table_w - 4) * 0.25), int((table_w - 4) * 0.15)]
        else:
             col_width = (table_w - 4) // max(len(headers), 1)
             col_widths = [col_width] * len(headers)
    
        current_x = base_l + 2
        for i, header in enumerate(headers):
            w = col_widths[i]
            create_button(60 + i, ISB_LIGHT | ISB_LEFT | ISB_COLOR_STRING, current_x, 76, w - 1, 4, " " + header[:20], ucid, req_i_counter)
            current_x += w
            time.sleep(0.01)
    
        # 5. Rows
        row_y = 81
        start_id = 70 # Lower start ID to avoid overflow (Max 239)
        for row_idx, row in enumerate(data):
            current_x = base_l + 2
            # Determine Row Command (if any)
            # Typically users click the first cell or entire row?
            # Creating individual cells.
            for col_idx, cell in enumerate(row):
                w = col_widths[col_idx] if col_idx < len(col_widths) else (table_w // len(row))
                cell_str = str(cell)[:32]
                create_button(
                    start_id + row_idx * 10 + col_idx,
                    ISB_DARK | ISB_LEFT | ISB_COLOR_SELECTED | ISB_CLICK,
                    current_x,
                    row_y + row_idx * 5,
                    w - 1, 4, " " + cell_str, ucid, req_i_counter)
                current_x += w
            time.sleep(0.01)
    
        menu_y = row_y + len(data) * 5 + 5
    
        # 6. Pagination
        if total_pages > 1:
            if page > 1:
                create_button(53, ISB_LIGHT | ISB_CLICK | ISB_COLOR_SELECTED, base_l + 2, menu_y, 8, 4, "<", ucid, req_i_counter)
            
            if page < total_pages:
                create_button(54, ISB_LIGHT | ISB_CLICK | ISB_COLOR_SELECTED, base_l + 12, menu_y, 8, 4, ">", ucid, req_i_counter)
            
            menu_y += 5
    
        # Save state
        visual_rows = [
                {'sys_id': i, 'uname': r[1] if len(r) > 1 else ''} 
                for i, r in enumerate(data)
        ]
        
        STATE.page_state[ucid] = {
            'cmd': source_cmd,
            'page': page,
            'total_pages': total_pages,
            'rows': context_data if context_data else visual_rows,
            'context_rows': context_data,
            'row_commands': commands # Store custom commands
        }
    
        create_menu_buttons(ucid, source_cmd, menu_y, req_i_counter)
    except Exception as e:
        logging.error(f"Display Table Error: {e}")
        logging.error(traceback.format_exc())

def on_button_click(packet: bytes):
    if len(packet) < 8: return
    try:
        # ISP_BTC: Size(0), Type(1), ReqI(2), UCID(3), ClickID(4), Inst(5), CFlags(6), Sp3(7)
        ucid = packet[3]
        click_id = packet[4]
        
        logging.info(f"BTN CLICK: {click_id} UCID:{ucid}")
        
        # Check standard menu buttons
        # 50, 51, 52 (Close), 53 (<), 54 (>)
        
        if click_id == 52 or click_id == 239: # Close / Back
             clear_table(ucid)
             return
             
        if click_id == 53 or click_id == 54: # Pagination
             page_state = STATE.page_state.get(ucid)
             if page_state:
                 cmd = page_state.get('cmd')
                 page = page_state.get('page', 1)
                 total = page_state.get('total_pages', 1)
                 
                 new_page = page - 1 if click_id == 53 else page + 1
                 if 1 <= new_page <= total:
                     from .commands import handle_command
                     handle_command(ucid, f"{cmd} {new_page}")
             return
             
        # Check Help Menu buttons
        # Range 200-220 usually
        # Mapping: 200=!rank, 201=!topwins, etc.
        # Hardcoded map as per create_menu_buttons
        
        btn_map = {
            200: "!rank",
            201: "!topwins",
            202: "!topcars",
            203: "!mypb",
            204: "!sr",
            205: "!teams",
            206: "!nations",
            120: "!register",
            121: "!register",
            130: "!help",
            131: "!help",
            140: "!admin",
            141: "!admin",
            150: "!badcombo",
            151: "!badcombo"
        }
        
        # --- Voting Logic ---
        if STATE.voting_active and 210 <= click_id <= 240: # Voting range
             from .voting import handle_vote_click
             handle_vote_click(ucid, click_id)
             return
             
        # --- Table Row Click Logic ---
        # IDs 70 to 190 (approx)
        if 70 <= click_id <= 200:
             # Determine Row Index
             # ID = 70 + row * 10 + col
             # row = (ID - 70) // 10
             row_idx = (click_id - 70) // 10
             
             page_state = STATE.page_state.get(ucid)
             if page_state and 'row_commands' in page_state:
                 cmds = page_state['row_commands']
                 if cmds and 0 <= row_idx < len(cmds):
                     cmd_str = cmds[row_idx]
                     if cmd_str:
                         # Execute Command
                         # Check if it starts with ! or just dispatch handle_command
                         # Or we can treat it as !admin <cmd_str> if passed from admin menu?
                         # No, `admin_menu` passed raw ["random", "restart"].
                         # We need to prepend "!admin " or just run it?
                         # The `display_table_with_menu` call had `!admin` as source_cmd.
                         # But `cmds` might be generic.
                         # Let's assume the command string is fully qualified or sub-command.
                         # User passed `commands=["random", "restart"]`.
                         # We should probably run `handle_command(ucid, f"!admin {cmd_str}")`.
                         # But `cmd_str` could be anything.
                         # Let's check if it starts with ! or /
                         
                         full_cmd = f"!admin {cmd_str}" if not cmd_str.startswith('!') and not cmd_str.startswith('/') else cmd_str
                         from .commands import handle_command
                         handle_command(ucid, full_cmd)
                         return

        # --- End Voting ---
        
        if click_id in btn_map:
             from .commands import handle_command
             handle_command(ucid, btn_map[click_id])
             
    except Exception as e:
        logging.error(f"BTC Error: {e}")
