from pyrogram import Client
import asyncio


API_ID = 28878649
API_HASH = "38a07ed36a8c65efa63dc841441c54b5"

app = Client("my_account", api_id=API_ID, api_hash=API_HASH)

async def main():
    await app.start()
