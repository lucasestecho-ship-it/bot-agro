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

def get_google_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)

def get_sheet():
    return get_google_sheet().worksheet("Hoja 1")

def get_superficie_from_hoja2(lote):
    try:
        hoja2 = get_google_sheet().worksheet("Hoja 2")
        lotes = hoja2.col_values(1)
        superficies = hoja2.col_values(2)
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
    values = worksheet.col_values(11)
    nums = []
    for v in values[1:]:
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

def clasificar_mensaje(text):
    prompt = (
        "Clasificá el siguiente mensaje en UNA de estas categorías:\n"
        "- receta: si habla de aplicación fitosanitaria, agroquímicos, pulverización, lotes, cultivos, productos como roundup, harrier, etc.\n"
        "- tarea: si es algo para hacer, llamar a alguien, resolver algo, pendiente\n"
        "- compra: si hay que comprar algo, un producto, material, insumo\n"
        "- idea: si es una idea, post, contenido, proyecto futuro, algo que estaria bueno hacer, propuesta de redes sociales, tema para publicar, contenido para instagram, facebook, youtube u otras plataformas\n"
        "- cliente: si menciona un cliente, visita, reunion, trabajo para alguien\n\n"
        "Responde UNICAMENTE con una de estas palabras: receta, tarea, compra, idea, cliente\n\n"
        f"Mensaje: {text}"
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip().lower()

def extract_data_with_gpt(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Sos un asistente agronomo. El usuario te dicta datos de una aplicacion fitosanitaria.\n"
        "Extrae la informacion y responde UNICAMENTE con JSON puro, sin texto adicional, sin explicaciones, sin markdown, sin backticks, solo el JSON puro:\n"
        "{\n"
        f'  "fecha": "usa {today} si no menciona otra fecha",\n'
        '  "campo": "nombre del campo",\n'
        '  "cultivo": "cultivo",\n'
        '  "lote": "nombre del lote",\n'
        '  "labor": "Pulverizacion",\n'
        '  "superficie": "numero de hectareas solo el numero, null si no menciona",\n'
        '  "productos": [\n'
        '    {"producto": "nombre del producto 1", "dosis": "solo el numero sin texto ni unidad", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha", "orden_carga": "numero de orden de carga de este producto, null si no menciona"},\n'
        '    {"producto": "nombre del producto 2", "dosis": "solo el numero sin texto ni unidad", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha", "orden_carga": "numero de orden de carga de este producto, null si no menciona"}\n'
        '  ]\n'
        '}\n\n'
        'REGLAS IMPORTANTES:\n'
        '- El usuario puede dictar la orden de carga de distintas formas: "orden de carga 1 harrier bio, 2 roundup", o "primero harrier bio, segundo roundup", o "harrier bio primero, roundup segundo". En todos los casos asigna el numero correspondiente: primero=1, segundo=2, tercero=3, cuarto=4, quinto=5.\n'
        '- La orden de carga va DENTRO de cada producto, no es un campo global.\n'
        '- La dosis es SOLO el numero, sin unidad ni texto. Ejemplo: "2" no "2 kg/ha".\n'
        '- La unidad va separada. Ejemplo: "kg/ha", "L/ha", "cc/ha".\n'
        '- No uses markdown, no uses backticks, responde SOLO el JSON puro.\n\n'
        f'El mensaje es: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_tarea(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Extrae los datos de esta tarea y responde SOLO con JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "tarea": "descripcion clara de la tarea",\n'
        '  "persona": "nombre de la persona involucrada si menciona, sino null",\n'
        '  "prioridad": "Alta, Media o Baja segun la urgencia que transmite el mensaje. Si no se menciona, usa Media",\n'
        '  "estado": "Pendiente"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_compra(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Extrae los datos de esta compra y responde SOLO con JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "producto": "nombre del producto a comprar",\n'
        '  "cantidad": "cantidad si menciona, sino null",\n'
        '  "estado": "Pendiente"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_idea(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Extrae los datos de esta idea y responde SOLO con JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "idea": "descripcion de la idea",\n'
        '  "categoria": "una categoria corta: post, proyecto, producto, proceso u otra"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_cliente(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Extrae los datos de este mensaje de cliente y responde SOLO con JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "cliente": "nombre del cliente o empresa",\n'
        '  "tema": "de que se trata, que quiere o necesita",\n'
        '  "prioridad": "Alta, Media o Baja segun la urgencia. Si no se menciona, usa Media",\n'
        '  "estado": "Pendiente"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def calcular_consumo(dosis, superficie):
    try:
        return round(float(str(dosis).replace(",", ".")) * float(str(superficie).replace(",", ".")), 2)
    except:
        return ""

def save_to_sheet(worksheet, data, receta_num):
    rows = []
    for producto in data["productos"]:
        superficie = data.get("superficie", "")
        dosis = producto.get("dosis", "")
        consumo = calcular_consumo(dosis, superficie)
        row = [
            data.get("fecha", ""),
            data.get("campo", ""),
            data.get("cultivo", ""),
            data.get("lote", ""),
            data.get("labor", "Pulverizacion"),
            superficie,
            producto.get("producto", ""),
            dosis,
            producto.get("unidad", ""),
            producto.get("orden_carga", ""),
            receta_num,
            "",
            consumo
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

        if message.voice:
            await context.bot.send_message(chat_id=chat_id, text="Transcribiendo audio...")
            file = await context.bot.get_file(message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                text = transcribe_audio(tmp.name)
                os.unlink(tmp.name)

        elif message.text:
            text = message.text

        else:
            await context.bot.send_message(chat_id=chat_id, text="Solo puedo procesar mensajes de texto o audio.")
            return

        await context.bot.send_message(chat_id=chat_id, text="Procesando...")

        categoria = clasificar_mensaje(text)
        sh = get_google_sheet()

        if categoria == "receta":
            data = extract_data_with_gpt(text)
            data["campo"] = (data.get("campo") or "").lower()
            data["lote"] = (data.get("lote") or "").lower()
            data["cultivo"] = (data.get("cultivo") or "").lower()

            superficie_desde_hoja2 = False
            if not data.get("superficie") or data.get("superficie") == "null":
                sup = get_superficie_from_hoja2(data.get("lote", ""))
                if sup:
                    data["superficie"] = sup
                    superficie_desde_hoja2 = True

            worksheet = sh.worksheet("Hoja 1")
            receta_num = get_next_receta_number(worksheet)
            rows = save_to_sheet(worksheet, data, receta_num)

            productos_texto = "\n".join([
                "  - " + r[6] + ": " + str(r[7]) + " " + r[8] + " | orden: " + str(r[9]) + " | consumo: " + str(r[12])
                for r in rows
            ])
            sup_label = str(data.get("superficie")) + " ha (desde registro de lotes)" if superficie_desde_hoja2 else str(data.get("superficie")) + " ha"
            respuesta = (
                "Receta #" + str(receta_num) + " guardada!\n\n"
                "Fecha: " + str(data.get("fecha")) + "\n"
                "Campo: " + str(data.get("campo")) + "\n"
                "Cultivo: " + str(data.get("cultivo")) + "\n"
                "Lote: " + str(data.get("lote")) + "\n"
                "Superficie: " + sup_label + "\n\n"
                "Productos:\n" + productos_texto
            )

        elif categoria == "tarea":
            data = extract_tarea(text)
            sh.worksheet("Hoja 3").append_row([
                data.get("fecha", ""),
                data.get("tarea", ""),
                data.get("persona", ""),
                data.get("prioridad", ""),
                data.get("estado", "Pendiente")
            ])
            respuesta = (
                "Tarea guardada!\n\n"
                + str(data.get("tarea")) + "\n"
                "Persona: " + str(data.get("persona") or "-") + "\n"
                "Prioridad: " + str(data.get("prioridad")) + "\n"
                "Estado: " + str(data.get("estado"))
            )

        elif categoria == "compra":
            data = extract_compra(text)
            sh.worksheet("Hoja 4").append_row([
                data.get("fecha", ""),
                data.get("producto", ""),
                data.get("cantidad", ""),
                data.get("estado", "Pendiente")
            ])
            respuesta = (
                "Compra guardada!\n\n"
                + str(data.get("producto")) + "\n"
                "Cantidad: " + str(data.get("cantidad") or "-") + "\n"
                "Estado: " + str(data.get("estado"))
            )

        elif categoria == "idea":
            data = extract_idea(text)
            sh.worksheet("Hoja 5").append_row([
                data.get("fecha", ""),
                data.get("idea", ""),
                data.get("categoria", "")
            ])
            respuesta = (
                "Idea guardada!\n\n"
                + str(data.get("idea")) + "\n"
                "Categoria: " + str(data.get("categoria"))
            )

        elif categoria == "cliente":
            data = extract_cliente(text)
            sh.worksheet("Hoja 6").append_row([
                data.get("fecha", ""),
                data.get("cliente", ""),
                data.get("tema", ""),
                data.get("prioridad", ""),
                data.get("estado", "Pendiente")
            ])
            respuesta = (
                "Cliente guardado!\n\n"
                + str(data.get("cliente")) + "\n"
                "Tema: " + str(data.get("tema")) + "\n"
                "Prioridad: " + str(data.get("prioridad")) + "\n"
                "Estado: " + str(data.get("estado"))
            )

        else:
            respuesta = "No pude clasificar el mensaje. Intenta ser mas especifico."

        await context.bot.send_message(chat_id=chat_id, text=respuesta)

    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Error al procesar: " + str(e))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
