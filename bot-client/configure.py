#!/usr/bin/env python3
import os
import requests
import argparse
import sys
from dotenv import load_dotenv

# Load .env
load_dotenv()

API_URL = os.getenv('API_URL', 'https://lfsrank.com/api/api_ingest.php')
API_KEY = os.getenv('API_KEY')

def main():
    parser = argparse.ArgumentParser(description='LFS Server Feature Configuration CLI')
    parser.add_argument('--voting', choices=['on', 'off'], help='Enable/Disable Voting')
    parser.add_argument('--stats', choices=['on', 'off'], help='Enable/Disable Stats Commands')
    parser.add_argument('--help-cmds', choices=['on', 'off'], dest='help_cmds', help='Enable/Disable Help Commands')
    parser.add_argument('--welcome', choices=['on', 'off'], help='Enable/Disable Welcome Message')
    
    args = parser.parse_args()

    if not API_KEY:
        print("Error: API_KEY not found in .env variable.")
        sys.exit(1)

    # Build config payload
    config_update = {}
    
    # Map 'on'/'off' to boolean
    if args.voting: config_update['voting'] = (args.voting == 'on')
    if args.stats: config_update['stats'] = (args.stats == 'on')
    if args.help_cmds: config_update['help'] = (args.help_cmds == 'on')
    if args.welcome: config_update['welcome_msg'] = (args.welcome == 'on')

    if not config_update:
        print("No changes specified. Use --help to see options.")
        sys.exit(0)

    print(f"Updating configuration: {config_update} ...")
    
    try:
        payload = {
            'action': 'update_config',
            'api_key': API_KEY,
            'config': config_update
        }
        res = requests.post(API_URL, json=payload, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data['status'] == 'success':
                print(f"Success! New Config: {data['config']}")
            else:
                print(f"Error: {data.get('message', 'Unknown error')}")
        else:
            print(f"HTTP Error: {res.status_code} - {res.text}")
            
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    main()
