from pyrogram import Client
from typing import Dict

class TelegramClientManager:
    def __init__(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self._clients: Dict[str, Client] = {}

    async def get_client(self, session_name: str) -> Client:
        if session_name not in self._clients:
            client = Client(session_name, self.api_id, self.api_hash)
            await client.start()
            self._clients[session_name] = client

        return self._clients[session_name]

    async def stop_client(self, session_name: str):
        if session_name in self._clients:
            await self._clients[session_name].disconnect()
            del self._clients[session_name]

    async def stop_all(self):
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()
