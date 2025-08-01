import server
import execution
import json
from aiohttp import web
import logging
from protocol import BinaryEventTypes


class PromptServer(server.PromptServer):    
    def __init__(self, loop):
        super().__init__(loop)
        self.current_session = None
        self.routes._items = list(filter(
            lambda r: r.path not in ["/history", "/queue"] and r.method == "GET",
            self.routes._items
        ))
        routes = self.routes

        @routes.post("/prompt/validate")
        async def prompt_validate(request):
            json_data =  await request.json()
            if "prompt" in json_data:
                prompt = json_data["prompt"]
                valid = await execution.validate_prompt("", prompt)
                if not valid[0]:                    
                    return web.json_response({"error": valid[1], "node_errors": valid[3]}, status=400)
            else:
                return web.json_response({"error": "no prompt", "node_errors": []}, status=400)
            return web.Response(status=200)
        
        @routes.get("/history")
        async def get_history(request):
            return web.json_response([])

        @routes.get("/queue")
        async def get_queue(request):
            return web.json_response({
                "queue_running": [],
                "queue_pending": [],
            })

    def get_queue_info(self):
        return {}
    
    def set_current_session(self, session):
        self.current_session = session

    def send_sync(self, event, data, sid=None):
        if self.current_session is None:
            return

        if not (event == BinaryEventTypes.UNENCODED_PREVIEW_IMAGE or 
                event == BinaryEventTypes.PREVIEW_IMAGE_WITH_METADATA or 
                isinstance(data, (bytes, bytearray))):
            try:
                self.current_session.progress(json.dumps({"type": event, "data": data}))
            except Exception as e:
                logging.error(f"Error sending sync message: {e}")
