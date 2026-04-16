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
    prompt = f"""Clasificá el siguiente mensaje en UNA de estas categorías:
- receta: si habla de aplicación fitosanitaria, agroquímicos, pulverización, lotes, cultivos, productos como roundup, harrier, etc.
- tarea: si es algo para hacer, llamar a alguien, resolver algo, pendiente
- compra: si hay que comprar algo, un producto, material, insumo
- idea: si es una idea, post, contenido, proyecto futuro
- cliente: si menciona un cliente, visita, reunión, trabajo para alguien

Respondé ÚNICAMENTE con una de estas palabras: receta, tarea, compra, idea, cliente

Mensaje: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip().lower()

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
  "productos": [
    {{"producto": "nombre del producto 1", "dosis": "solo el número sin texto ni unidad", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha", "orden_carga": "número de orden de carga de este producto, null si no menciona"}},
    {{"producto": "nombre del producto 2", "dosis": "solo el número sin texto ni unidad", "unidad": "solo la unidad, ejemplo: kg/ha o L/ha o cc/ha", "orden_carga": "número de orden de carga de este producto, null si no menciona"}}
  ]
}}

REGLAS IMPORTANTES:
- El usuario puede dictar la orden de carga de distintas formas: "orden de carga 1 harrier bio, 2 roundup", o "primero harrier bio, segundo roundup", o "harrier bio primero, roundup segundo". En todos los casos asigná el número correspondiente: primero=1, segundo=2, tercero=3, cuarto=4, quinto=5.
- La orden de carga va DENTRO de cada producto, no es un campo global.
- La dosis es SOLO el número, sin unidad ni texto. Ejemplo: "2" no "2 kg/ha".
- La unidad va separada. Ejemplo: "kg/ha", "L/ha", "cc/ha".
- No uses markdown, no uses backticks, respondé SOLO el JSON puro.

El mensaje es: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_tarea(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""Extraé los datos de esta tarea y respondé SOLO con JSON puro:
{{
  "fecha": "{today}",
  "tarea": "descripción clara de la tarea",
  "persona": "nombre de la persona involucrada si menciona, sino null",
  "prioridad": "Alta, Media o Baja según la urgencia que transmite el mensaje. Si no se menciona, usá Media",
  "estado": "Pendiente"
}}
Mensaje: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_compra(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""Extraé los datos de esta compra y respondé SOLO con JSON puro:
{{
  "fecha": "{today}",
  "producto": "nombre del producto a comprar",
  "cantidad": "cantidad si menciona, sino null",
  "estado": "Pendiente"
}}
Mensaje: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_idea(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = f"""Extraé los datos de esta idea y respondé SOLO con JSON puro:
{{
  "fecha": "{today}",
  "idea": "descripción de la idea",
  "categoria": "una categoría corta: post, proyecto, producto, proceso u otra"
}}
Mensaje: {text}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("`
