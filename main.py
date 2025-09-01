from fastapi import FastAPI, Request, Form, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pyrogram.enums import ChatType
from pyrogram.errors import SessionPasswordNeeded

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from database import get_db, Base, engine, SessionLocal
from models import UserSession
import os

from TelegramClientManager import TelegramClientManager

# Створюємо таблиці, якщо ще немає
Base.metadata.create_all(bind=engine)

API_ID =
API_HASH =

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# менеджер клієнтів
tg_manager = TelegramClientManager(API_ID, API_HASH)


@app.get("/user/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    result = db.execute(select(UserSession).where(UserSession.id == user_id))
    user_session = result.scalars().first()

    if not user_session:
        raise HTTPException(status_code=404, detail="User not found")

    # Для виводу в терміналі
    print(user_session)

    # Для повернення в API
    return {
        "id": user_session.id,
        "phone": user_session.phone
    }


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "sent": False})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, phone: str = Form(...),
                code: str = Form(None), phone_code_hash: str = Form(None),
                password: str = Form(None),
                db: Session = Depends(get_db)):
    session_name = phone
    # 👈 унікальна сесія на юзера
    client = await tg_manager.get_client(session_name)

    user_session = db.query(UserSession).filter(UserSession.phone == phone).first()
    try:
        if user_session:
            # сесія вже є → підключаємо клієнта
            response = RedirectResponse(url="/ui/chats", status_code=303)
            response.set_cookie(key="session_name", value=user_session.session_name, httponly=True)
            return response
            # якщо немає — йдемо по стандартному флоу
        if password:
            await client.check_password(password)
            response = RedirectResponse(url="/ui/chats", status_code=303)
            response.set_cookie(key="session_name", value=session_name, httponly=True)
            user_session = UserSession(phone=phone, session_name=session_name)
            db.add(user_session)
            db.commit()
            return response
        elif code and phone_code_hash:
            try:
                await client.sign_in(phone, phone_code_hash, code)
                response = RedirectResponse(url="/ui/chats", status_code=303)
                user_session = UserSession(phone=phone, session_name=session_name)
                db.add(user_session)
                db.commit()
                response.set_cookie(key="session_name", value=session_name, httponly=True)
                return response
            except SessionPasswordNeeded:
                return templates.TemplateResponse("login.html",
                                                  {"request": request, "need_password": True,
                                                   "phone": phone})
        else:
            sent_code = await client.send_code(phone)

            return templates.TemplateResponse("login.html",
                                              {"request": request, "sent": True, "phone": phone,
                                               "phone_code_hash": sent_code.phone_code_hash})
    except Exception as e:
        return HTMLResponse(f"<h2>❌ Error: {e}</h2>")


@app.get("/logout")
async def logout(request: Request):
    session_name = request.cookies.get("session_name")

    # зупиняємо клієнт у менеджері
    await tg_manager.stop_client(session_name)

    # видаляємо з БД
    db: Session = SessionLocal()
    try:
        user_session = db.query(UserSession).filter_by(session_name=session_name).first()
        if user_session:
            db.delete(user_session)
            db.commit()
    finally:
        db.close()

    # видаляємо файл сесії
    session_file = f"{session_name}.session"
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except Exception as e:
            return {"status": f"error deleting session file: {e}"}

    return {"status": "session deleted, please login again"}


@app.get("/chats")
async def get_chats(request: Request):
    session_name = request.cookies.get("session_name")
    client = await tg_manager.get_client(session_name)
    chats = []
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        title = chat.title if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL] else \
            f"{chat.first_name or ''} {chat.last_name or ''}".strip() or "Private user"

        # аватарка

        photo_url = None
        # if chat.photo:
        #     photo_url = await client.download_media(chat.photo.small_file_id)

        chats.append({
            "chat_id": chat.id,
            "title": title,
            "type": chat.type.value,
            "photo": photo_url
        })
    return chats


@app.get("/messages/{chat_id}")
async def get_messages(request: Request, chat_id: int, limit: int = 50, before_id: int = None, after_id: int = None):
    session_name = request.cookies.get("session_name")
    client = await tg_manager.get_client(session_name)

    messages = []
    if before_id:
        async for msg in client.get_chat_history(chat_id, limit=limit, offset_id=before_id):
            messages.append(msg)
    elif after_id:
        async for msg in client.get_chat_history(chat_id, limit=limit, offset_id=after_id):
            if msg.id > after_id:
                messages.append(msg)
    else:
        async for msg in client.get_chat_history(chat_id, limit=limit):
            messages.append(msg)

    result = [serialize_message(m) for m in sorted(messages, key=lambda x: x.id)]
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse('<a href="/ui/chats" style="font-family:system-ui;">Відкрити список чатів</a>')


@app.get("/ui/chats", response_class=HTMLResponse)
async def ui_chats(request: Request):
    session_name = request.cookies.get("session_name")
    return templates.TemplateResponse("chats.html", {"request": request, "session_name": session_name})


@app.get("/ui/chats/{chat_id}", response_class=HTMLResponse)
async def ui_chat_messages(chat_id: int, request: Request):
    session_name = request.cookies.get("session_name")
    return templates.TemplateResponse("messages.html",
                                      {"request": request, "chat_id": chat_id, "session_name": session_name})


@app.get("/file/{file_id}")
async def download_file(file_id: str, request: Request):
    try:
        session_name = request.cookies.get("session_name")
        client = await tg_manager.get_client(session_name)
        file_path = await client.download_media(file_id)
        if not file_path:
            return JSONResponse({"error": "Failed to download media"}, status_code=500)
        return FileResponse(file_path, filename=os.path.basename(file_path))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def serialize_message(m):
    data = {
        "id": m.id,
        "date": m.date.isoformat() if m.date else None,
        "text": m.text or m.caption or None,
        "media": None,
        "forwarded": None,
        "from_user": {
            "id": m.from_user.id if m.from_user else None,
            "first_name": m.from_user.first_name if m.from_user else None,
            "username": m.from_user.username if m.from_user else None,
            "is_self": m.from_user.is_self if m.from_user else False,
        }
    }

    # фото
    if m.photo:
        data["media"] = {
            "type": "photo",
            "file_id": m.photo.file_id,
            "width": m.photo.width,
            "height": m.photo.height
        }

    # відео
    elif m.video:
        data["media"] = {
            "type": "video",
            "file_id": m.video.file_id,
            "width": m.video.width,
            "height": m.video.height,
            "duration": m.video.duration
        }

    # документ
    elif m.document:
        data["media"] = {
            "type": "document",
            "file_id": m.document.file_id,
            "file_name": m.document.file_name
        }

    # голосові повідомлення
    elif m.voice:
        data["media"] = {
            "type": "voice",
            "file_id": m.voice.file_id,
            "duration": m.voice.duration
        }

    # відео повідомлення
    elif m.video_note:
        data["media"] = {
            "type": "video_note",
            "file_id": m.video_note.file_id,
            "duration": m.video_note.duration,
            "length": m.video_note.length
        }

    # стікери
    elif m.sticker:
        data["media"] = {
            "type": "sticker",
            "file_id": m.sticker.file_id,
            "width": m.sticker.width,
            "height": m.sticker.height,
            "emoji": m.sticker.emoji
        }

    # анімації/GIF
    elif m.animation:
        data["media"] = {
            "type": "animation",
            "file_id": m.animation.file_id,
            "width": m.animation.width,
            "height": m.animation.height,
            "duration": m.animation.duration
        }

    # переслане
    if m.forward_from or m.forward_from_chat:
        data["forwarded"] = {
            "from_user": {
                "id": m.forward_from.id if m.forward_from else None,
                "first_name": m.forward_from.first_name if m.forward_from else None,
                "username": m.forward_from.username if m.forward_from else None
            } if m.forward_from else None,
            "from_chat": {
                "id": m.forward_from_chat.id if m.forward_from_chat else None,
                "title": m.forward_from_chat.title if m.forward_from_chat else None,
                "type": m.forward_from_chat.type.value if m.forward_from_chat else None
            } if m.forward_from_chat else None,
        }

    return data
