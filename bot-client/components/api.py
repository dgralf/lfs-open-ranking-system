import urllib.request
import urllib.error
import urllib.parse
import json
import ssl
import time
import os
import logging
from .state import ARGS
from cryptography.hazmat.primitives.asymmetric import ed25519

def send_to_api(action: str, payload: dict):
    try:
        if not ARGS.api_key:
            logging.warning("API Key missing, skipping API call.")
            return None
            
        data = payload.copy()
        data['action'] = action
        data['api_key'] = ARGS.api_key
        
        json_data = json.dumps(data).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-API-KEY': ARGS.api_key,
            'User-Agent': 'LFSBot/2.0 Modular'
        }
        
        # Signing (Ed25519)
        private_key_hex = os.environ.get('INSIM_PRIVATE_KEY')
        if private_key_hex:
            try:
                private_bytes = bytes.fromhex(private_key_hex)
                priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
                signature = priv_key.sign(json_data)
                headers['X-Signature'] = signature.hex()
            except Exception as e:
                logging.error(f"Signing Error: {e}")

        # Route logic
        url = ARGS.api_url
        if action == 'live':
            # Assuming ARGS.api_url points to an ingest script or base API
            # Heuristic: if it ends in .php, strip it.
            # But let's follow system2 logic:
             if 'api_ingest.php' in url:
                base = url.rsplit('/', 1)[0]
                url = f"{base}/live"
             # If just base URL, append /live?
             elif not url.endswith('.php'):
                 url = f"{url.rstrip('/')}/live"

        req = urllib.request.Request(url, data=json_data, headers=headers)
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            return json.load(response)
            
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
            logging.error(f"API {action} Failed {e.code}: {err_body}")
        except:
            logging.error(f"API {action} Failed {e.code}")
        return None
    except Exception as e:
        logging.error(f"Error sending to API {action}: {e}")
        return None

def fetch_api_get(endpoint: str, params: dict = None):
    try:
        if not params: params = {}
        
        # Prepare URL
        base = ARGS.api_url
        if 'api_ingest.php' in base:
             base = base.rsplit('/', 1)[0] 
        if base.endswith('/'): base = base[:-1]
             
        if not endpoint.startswith('/'): endpoint = '/' + endpoint
        if endpoint.startswith('/api/'): endpoint = endpoint[4:] # Strip dup
        
        full_url = f"{base}{endpoint}" # endpoint already has /
        
        if params:
            query_string = urllib.parse.urlencode(params)
            full_url += f"?{query_string}"
            
        logging.debug(f"API GET: {full_url}")
        
        req = urllib.request.Request(full_url)
        if ARGS.api_key:
            req.add_header('X-API-KEY', ARGS.api_key)
        req.add_header('User-Agent', 'LFSBot/2.0 Modular')
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
             return json.load(response)
             
    except urllib.error.HTTPError as e:
        try:
             # Try to read body
             logging.error(f"API GET Error {e.code}: {e.read().decode()}")
        except:
             logging.error(f"API GET Error {e.code}")
        return {}
    except Exception as e:
        logging.error(f"API GET Error {endpoint}: {e}")
        return {}
