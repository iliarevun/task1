from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import SessionPasswordNeeded
from fastapi.responses import RedirectResponse


API_ID = 28878649
API_HASH = "38a07ed36a8c65efa63dc841441c54b5"
SESSION_NAME = "my_account"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

tg_client: Client | None = None

@app.on_event("startup")
async def startup():
    global tg_client
    if tg_client is None:
        tg_client = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)
    await tg_client.connect()

@app.on_event("shutdown")
async def shutdown():
    global tg_client
    if tg_client and tg_client.is_connected:
        await tg_client.disconnect()

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "sent": False})

@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    phone: str = Form(...),
    code: str = Form(None),
    phone_code_hash: str = Form(None),
    password: str = Form(None)
):
    global tg_client

    try:
        if password:
            await tg_client.check_password(password)
            return RedirectResponse(url="/ui/chats", status_code=303)

        elif code and phone_code_hash:
            try:
                await tg_client.sign_in(phone, phone_code_hash, code)
                return RedirectResponse(url="/ui/chats", status_code=303)
            except SessionPasswordNeeded:
                return templates.TemplateResponse("login.html", {
                    "request": request,
                    "need_password": True,
                    "phone": phone
                })

        else:
            sent_code = await tg_client.send_code(phone)
            return templates.TemplateResponse("login.html", {
                "request": request,
                "sent": True,
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash
            })

    except Exception as e:
        return HTMLResponse(f"<h2>❌ Error: {e}</h2>")

@app.get("/logout")
async def logout():
    global tg_client

    if tg_client is None:
        return {"status": "no client exists"}

    if tg_client.is_connected:
        try:
            await tg_client.log_out()
        except ConnectionError:
            pass
    tg_client = None
    return RedirectResponse(url="/login", status_code=303)


@app.get("/chats")
async def get_chats():
    chats = []
    async for dialog in tg_client.get_dialogs():
        chat = dialog.chat
        title = chat.title if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL] else \
            f"{chat.first_name or ''} {chat.last_name or ''}".strip() or "Private user"
        chats.append({"chat_id": chat.id, "title": title, "type": chat.type.value})
    return chats

@app.get("/messages/{chat_id}")
async def get_messages(chat_id: int, limit: int = 50, before_id: int = None, after_id: int = None):
    messages = []
    if before_id:
        async for msg in tg_client.get_chat_history(chat_id, limit=limit, offset_id=before_id):
            messages.append(msg)
    elif after_id:
        async for msg in tg_client.get_chat_history(chat_id, limit=limit, offset_id=after_id):
            if msg.id > after_id:
                messages.append(msg)
    else:
        async for msg in tg_client.get_chat_history(chat_id, limit=limit):
            messages.append(msg)

    result = []
    for m in sorted(messages, key=lambda x: x.id):
        result.append({
            "id": m.id,
            "text": m.text,
            "date": m.date.isoformat() if m.date else None,
            "from_user": {
                "id": m.from_user.id if m.from_user else None,
                "first_name": m.from_user.first_name if m.from_user else None,
                "username": m.from_user.username if m.from_user else None,
                "is_self": m.from_user.is_self if m.from_user else False,
            }
        })
    return JSONResponse(result)

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse('<a href="/ui/chats" style="font-family:system-ui;">Відкрити список чатів</a>')

@app.get("/ui/chats", response_class=HTMLResponse)
async def ui_chats(request: Request):
    return templates.TemplateResponse("chats.html", {"request": request})

@app.get("/ui/chats/{chat_id}", response_class=HTMLResponse)
async def ui_chat_messages(chat_id: int, request: Request):
    return templates.TemplateResponse("messages.html", {"request": request, "chat_id": chat_id})
