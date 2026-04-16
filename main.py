import os
import json
import logging
import tempfile
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh.worksheet("Hoja 1")

def get_superficie_from_hoja2(lote):
    """Busca la superficie de un lote en la Hoja 2 (col A=lote, col B=superficie)."""
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        hoja2 = sh.worksheet("Hoja 2")

        lotes = hoja2.col_values(1)        # Columna A
        superficies = hoja2.col_values(2)  # Columna B

        lote_normalizado = lote.strip().lower()
        for i, nombre in enumerate(lotes):
            if nombre.strip().lower() == lote_normalizado:
                if i < len(superficies):
                    return superficies[i]
        return None
    except Exception as e:
        logger.warning(f"No se pudo obtener superficie de Hoja 2: {e}")
        return None

def get_next_receta_number(worksheet):
    values = worksheet.col_values(11)  # Columna K = Receta
    nums = []
    for v in values[1:]:  # saltar encabezado
        try:
            n = int(v)
            if n > 0:
                nums.append(n)
        except:
            pass
    return max(nums) + 1 if nums else 1

def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text

def extract_data_with_gpt(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""Sos un asistente agrónomo. El usuario te dicta datos de una aplicación fitosanitaria.
Extraé la información y respondé ÚNICAMENTE con JSON puro, sin texto adicional, sin explicaciones, sin markdown, sin backticks, solo el JSON puro:
{{
  "fecha": "usá {today} si no menciona otra fecha",
  "campo": "nombre del campo",
  "cultivo": "cultivo",
  "lote": "nombre del lote",
  "labor": "Pulverización",
  "superficie": "número de hectáreas solo el número, null si no menciona",
  "orden_carga": "número si lo menciona, sino null",
  "productos": [
    {{"producto": "nombre del producto 1", "dosis": "solo el número sin texto ni unidad, ejemplo: 2", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha"}},
    {{"producto": "nombre del producto 2", "dosis": "solo el número sin texto ni unidad, ejemplo: 0.1", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha"}}
  ]
}}
IMPORTANTE: No uses markdown, no uses backticks, respondé SOLO el JSON puro sin ningún formato adicional.
El mensaje es: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def save_to_sheet(worksheet, data, receta_num):
    rows = []
    for producto in data["productos"]:
        row = [
            data.get("fecha", ""),
            data.get("campo", ""),
            data.get("cultivo", ""),
            data.get("lote", ""),
            data.get("labor", "Pulverización"),
            data.get("superficie", ""),
            producto.get("producto", ""),
            producto.get("dosis", ""),
            producto.get("unidad", ""),
            data.get("orden_carga", ""),
            receta_num
        ]
        rows.append(row)

    for row in rows:
        worksheet.append_row(row)

    return rows

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id

    try:
        text = None

        # Si es audio/voz
        if message.voice:
            await context.bot.send_message(chat_id=chat_id, text="🎙️ Transcribiendo audio...")

            file = await context.bot.get_file(message.voice.file_id)

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                text = transcribe_audio(tmp.name)
                os.unlink(tmp.name)

        # Si es texto
        elif message.text:
            text = message.text

        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Solo puedo procesar mensajes de texto o audio.")
            return

        await context.bot.send_message(chat_id=chat_id, text="🔄 Procesando datos...")

        # Extraer datos con GPT
        data = extract_data_with_gpt(text)

        # Si no se mencionó superficie, buscarla en Hoja 2
        superficie_desde_hoja2 = False
        if not data.get("superficie") or data.get("superficie") == "null":
            sup = get_superficie_from_hoja2(data.get("lote", ""))
            if sup:
                data["superficie"] = sup
                superficie_desde_hoja2 = True

        # Guardar en Sheet
        worksheet = get_sheet()
        receta_num = get_next_receta_number(worksheet)
        rows = save_to_sheet(worksheet, data, receta_num)

        # Armar respuesta
        productos_texto = "\n".join([f"  • {r[6]}: {r[7]} {r[8]}" for r in rows])
        sup_label = f"{data.get('superficie')} ha _(desde registro de lotes)_" if superficie_desde_hoja2 else f"{data.get('superficie')} ha"
        respuesta = f"""✅ *Receta #{receta_num} guardada!*

📅 Fecha: {data.get('fecha')}
🌾 Campo: {data.get('campo')}
🌱 Cultivo: {data.get('cultivo')}
📍 Lote: {data.get('lote')}
📐 Superficie: {sup_label}

🧪 Productos:
{productos_texto}"""

        await context.bot.send_message(chat_id=chat_id, text=respuesta, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error al procesar: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
