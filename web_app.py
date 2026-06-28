import json
import logging
import mimetypes
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from main import (
    TELEGRAM_TOKEN,
    cmd_cerrar_recorrida,
    cmd_recorrida_cancelar,
    cmd_recorrida_inicio,
    enviar_recordatorios,
    handle_message,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
FIELD_ITEMS_DIR = DATA_DIR / "field_items"
STATIC_DIR = BASE_DIR / "static"


def build_telegram_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("recorrida_inicio", cmd_recorrida_inicio))
    app.add_handler(CommandHandler("cerrar_recorrida", cmd_cerrar_recorrida))
    app.add_handler(CommandHandler("recorrida_cancelar", cmd_recorrida_cancelar))
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL,
            handle_message,
        )
    )
    app.job_queue.run_daily(
        enviar_recordatorios,
        time=datetime.strptime("11:00", "%H:%M").time(),
    )
    return app


def safe_extension(upload: UploadFile, item_type: str) -> str:
    extension = Path(upload.filename or "").suffix.lower()
    if extension:
        return extension[:12]

    guessed = mimetypes.guess_extension(upload.content_type or "")
    if guessed:
        return guessed

    return ".webm" if item_type == "audio" else ".jpg"


@asynccontextmanager
async def lifespan(app: FastAPI):
    telegram_app = None
    run_bot = os.environ.get("RUN_TELEGRAM_BOT", "1").lower() not in {"0", "false", "no"}

    if run_bot:
        if not TELEGRAM_TOKEN:
            logger.warning("TELEGRAM_TOKEN no configurado: FastAPI inicia sin bot de Telegram.")
        else:
            telegram_app = build_telegram_application()
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling()
            logger.info("Bot de Telegram iniciado junto con FastAPI.")

    try:
        yield
    finally:
        if telegram_app:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()


app = FastAPI(title="Bot Agro Campo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return RedirectResponse(url="/campo")


@app.get("/campo")
async def campo():
    return FileResponse(STATIC_DIR / "campo.html")


@app.post("/api/field-items")
async def create_field_item(
    item_type: str = Form(...),
    campo: str = Form(...),
    sector: str = Form(""),
    captured_at: str = Form(...),
    latitude: str = Form(""),
    longitude: str = Form(""),
    gps_accuracy: str = Form(""),
    client_id: str = Form(""),
    file: UploadFile = File(...),
):
    item_type = item_type.strip().lower()
    if item_type not in {"audio", "foto"}:
        raise HTTPException(status_code=400, detail="item_type debe ser audio o foto")
    if not campo.strip():
        raise HTTPException(status_code=400, detail="campo es obligatorio")

    now = datetime.utcnow()
    item_id = uuid.uuid4().hex
    item_dir = FIELD_ITEMS_DIR / now.strftime("%Y-%m-%d")
    item_dir.mkdir(parents=True, exist_ok=True)

    extension = safe_extension(file, item_type)
    stored_filename = f"{now.strftime('%H%M%S')}_{item_id}_{item_type}{extension}"
    file_path = item_dir / stored_filename

    with file_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    metadata = {
        "ok": True,
        "id": item_id,
        "client_id": client_id,
        "item_type": item_type,
        "campo": campo.strip(),
        "sector": sector.strip(),
        "captured_at": captured_at,
        "latitude": latitude,
        "longitude": longitude,
        "gps_accuracy": gps_accuracy,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "stored_file": str(file_path),
        "received_at": now.isoformat() + "Z",
        "ai_processed": False,
    }

    metadata_path = file_path.with_suffix(file_path.suffix + ".json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "id": item_id}
