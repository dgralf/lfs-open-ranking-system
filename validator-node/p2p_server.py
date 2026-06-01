import aiohttp
from aiohttp import web
import logging
import json

class P2PServer:
    def __init__(self, host, port, ingest_callback):
        self.host = host
        self.port = port
        self.ingest_callback = ingest_callback
        self.app = web.Application()
        self.setup_routes()
        self.runner = None

    def setup_routes(self):
        self.app.router.add_post('/ingest', self.handle_ingest)
        self.app.router.add_get('/status', self.handle_status)
        # Placeholder for gossip
        # self.app.router.add_post('/gossip', self.handle_gossip)

    async def handle_status(self, request):
        return web.json_response({'status': 'online', 'service': 'LFS Validator Node'})

    async def handle_ingest(self, request):
        try:
            # We expect a JSON payload with race results
            # Similar to what the Bot sends to the original PHP API
            data = await request.json()
            
            # Action check (The bot sends action='update_results' or similar in the payload usually? 
            # Actually the bot sends data as POST fields or JSON. 
            # In Phase 1 proposal: "Endpoint 1: POST /ingest (Accepts race results from Bots)."
            
            # The callback should return (success: bool, message: str)
            success, msg = await self.ingest_callback(data)
            
            if success:
                return web.json_response({'status': 'success', 'message': msg})
            else:
                return web.json_response({'status': 'error', 'message': msg}, status=400)
                
        except json.JSONDecodeError:
            return web.json_response({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        except Exception as e:
            logging.error(f"Ingest Error: {e}")
            return web.json_response({'status': 'error', 'message': str(e)}, status=500)

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        logging.info(f"[*] P2P Server listening on {self.host}:{self.port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
