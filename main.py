import os
import json
import logging
import tempfile
import base64
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from pdf2image import convert_from_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
MY_CHAT_ID = 1144480769

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

def image_to_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def transcribe_image_base64(image_base64):
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Transcribi todo el texto que ves en esta imagen de forma completa y ordenada. "
                            "Si es un presupuesto, factura, nota o documento, extrae todos los datos visibles: "
                            "cliente, montos, conceptos, fechas, condiciones, totales, observaciones. "
                            "Devuelve el texto plano sin formato especial."
                        )
                    }
                ]
            }
        ],
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

def transcribe_image(image_path):
    image_base64 = image_to_base64(image_path)
    return transcribe_image_base64(image_base64)

def transcribe_pdf(pdf_path):
    pages = convert_from_path(pdf_path, dpi=150)
    textos = []
    for i, page in enumerate(pages):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            page.save(tmp.name, "JPEG")
            texto_pagina = transcribe_image(tmp.name)
            os.unlink(tmp.name)
            textos.append(f"--- Pagina {i+1} ---\n{texto_pagina}")
    return "\n\n".join(textos)

def clasificar_mensaje(text):
    prompt = (
        "Clasifica el siguiente mensaje en UNA de estas categorias:\n"
        "- receta: aplicacion fitosanitaria, agroquimicos, pulverizacion, lotes, cultivos, productos como roundup, harrier, etc.\n"
        "- cliente_nuevo: registrar nuevo cliente, oportunidad comercial, contacto nuevo, posible trabajo\n"
        "- cliente_consulta: consultar estado de clientes, ver pendientes, ver seguimientos\n"
        "- cliente_update: actualizar estado de cliente existente, cambiar fecha, marcar cerrado, perdido, etc.\n"
        "- tarea: algo para hacer, pendiente, recordatorio de accion\n"
        "- recorrida: visita a campo, recorrida tecnica, inspeccion, reporte de visita\n"
        "- presupuesto: presupuesto enviado, cotizacion, propuesta economica, factura, nota de pedido\n"
        "- compra: comprar material, insumo, herramienta\n"
        "- idea: idea de negocio, contenido, post, mejora, proyecto futuro\n\n"
        "Responde UNICAMENTE con una de estas palabras: receta, cliente_nuevo, cliente_consulta, cliente_update, tarea, recorrida, presupuesto, compra, idea\n\n"
        f"Mensaje: {text}"
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip().lower()

def extract_receta(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Sos un asistente agronomo. Extrae datos de aplicacion fitosanitaria y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "usa {today} si no menciona",\n'
        '  "campo": "nombre del campo",\n'
        '  "cultivo": "cultivo",\n'
        '  "lote": "nombre del lote",\n'
        '  "labor": "Pulverizacion",\n'
        '  "superficie": "numero o null",\n'
        '  "productos": [\n'
        '    {"producto": "nombre", "dosis": "solo numero", "unidad": "kg/ha o L/ha o cc/ha", "orden_carga": "numero o null"}\n'
        '  ]\n'
        '}\n'
        'REGLAS: orden de carga: primero=1, segundo=2, etc. Dosis solo numero. Solo JSON sin markdown.\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_cliente_nuevo(text):
    today = datetime.now().strftime("%d/%m/%Y")
    fecha_default = (datetime.now() + timedelta(days=3)).strftime("%d/%m/%Y")
    prompt = (
        "Extrae datos de este nuevo cliente y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "cliente": "nombre del cliente",\n'
        '  "empresa": "empresa o establecimiento o null",\n'
        '  "zona": "zona o localidad o null",\n'
        '  "provincia": "provincia o null",\n'
        '  "contacto": "nombre de contacto o null",\n'
        '  "telefono": "telefono o null",\n'
        '  "email": "email o null",\n'
        '  "origen": "como llego: recomendacion, instagram, web, conocido, etc. o null",\n'
        '  "necesidad": "que necesita o null",\n'
        '  "tipo_trabajo": "aguadas, caminos, apotreramiento, topografia, pasturas, asesoramiento integral, otro o null",\n'
        '  "estado": "nuevo, contactado, reunion pendiente, presupuesto pendiente, presupuesto enviado, en seguimiento, cerrado, perdido",\n'
        '  "proxima_accion": "que hay que hacer o null",\n'
        f'  "fecha_seguimiento": "fecha DD/MM/YYYY, si no menciona usa {fecha_default}",\n'
        '  "presupuesto": "monto o pendiente",\n'
        '  "probabilidad_cierre": "alta, media, baja o null",\n'
        '  "prioridad": "alta, media, baja",\n'
        '  "observaciones": "cualquier dato extra o null"\n'
        '}\n'
        f'Hoy es {today}. Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_cliente_update(text):
    prompt = (
        "El usuario quiere actualizar un cliente. Responde SOLO JSON puro:\n"
        "{\n"
        '  "cliente": "nombre del cliente a actualizar",\n'
        '  "nuevo_estado": "nuevo estado o null",\n'
        '  "proxima_accion": "nueva accion o null",\n'
        '  "fecha_seguimiento": "nueva fecha DD/MM/YYYY o null",\n'
        '  "observaciones": "nueva observacion o null"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_tarea(text):
    today = datetime.now().strftime("%d/%m/%Y")
    fecha_default = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    prompt = (
        "Extrae datos de esta tarea y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "tarea": "descripcion de la tarea",\n'
        '  "cliente": "cliente relacionado o null",\n'
        '  "categoria": "comercial, tecnico, compra, administrativo, contenido",\n'
        '  "responsable": "nombre o Lucas si no menciona",\n'
        '  "estado": "pendiente",\n'
        '  "prioridad": "alta, media, baja",\n'
        f'  "fecha_limite": "fecha DD/MM/YYYY, si no menciona usa {fecha_default}",\n'
        '  "observaciones": "extra o null"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_recorrida(text):
    today = datetime.now().strftime("%d/%m/%Y")
    fecha_default = (datetime.now() + timedelta(days=14)).strftime("%d/%m/%Y")
    prompt = (
        "Extrae datos de esta recorrida de campo y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "cliente": "nombre del cliente o campo",\n'
        '  "campo": "nombre del campo o lote o null",\n'
        '  "zona": "zona o localidad o null",\n'
        '  "resumen": "resumen general de la visita",\n'
        '  "problemas": "problemas detectados o null",\n'
        '  "recomendaciones": "recomendaciones o null",\n'
        '  "urgencia": "alta, media, baja",\n'
        f'  "proxima_visita": "fecha DD/MM/YYYY, si no menciona usa {fecha_default}",\n'
        '  "observaciones": "extra o null"\n'
        '}\n'
        f'Hoy es {today}. Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def extract_presupuesto(text):
    today = datetime.now().strftime("%d/%m/%Y")
    prompt = (
        "Extrae datos de este presupuesto y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "cliente": "nombre del cliente",\n'
        '  "trabajo": "tipo de trabajo",\n'
        '  "descripcion": "descripcion del trabajo o null",\n'
        '  "honorarios": "monto o 0",\n'
        '  "viaticos": "monto o 0",\n'
        '  "total": "monto total o 0",\n'
        '  "estado": "borrador, enviado, aprobado, rechazado",\n'
        f'  "fecha_envio": "fecha DD/MM/YYYY o {today}",\n'
        '  "fecha_respuesta": "fecha esperada o pendiente",\n'
        '  "observaciones": "extra o null"\n'
        '}\n'
        f'Hoy es {today}. Mensaje: {text}'
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
        "Extrae datos de esta compra y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "cliente_obra": "cliente u obra relacionada o null",\n'
        '  "material": "nombre del material o producto",\n'
        '  "cantidad": "cantidad o null",\n'
        '  "unidad": "unidad de medida o null",\n'
        '  "proveedor": "proveedor o a definir",\n'
        '  "precio_unitario": "precio o 0",\n'
        '  "total": "total o 0",\n'
        '  "estado": "a cotizar, cotizado, pedido, recibido",\n'
        '  "observaciones": "extra o null"\n'
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
        "Extrae datos de esta idea y responde SOLO JSON puro:\n"
        "{\n"
        f'  "fecha": "{today}",\n'
        '  "tipo": "contenido, negocio, mejora, producto, proceso u otro",\n'
        '  "idea": "descripcion de la idea",\n'
        '  "cliente_tema": "cliente o tema relacionado o general",\n'
        '  "estado": "nueva",\n'
        '  "observaciones": "extra o null"\n'
        '}\n'
        f'Mensaje: {text}'
    )
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def get_clientes_activos():
    try:
        hoja = get_google_sheet().worksheet("clientes")
        return hoja.get_all_records()
    except Exception as e:
        logger.error(f"Error obteniendo clientes: {e}")
        return []

def buscar_y_actualizar_cliente(nombre, nuevo_estado=None, proxima_accion=None, fecha_seguimiento=None, observaciones=None):
    try:
        hoja = get_google_sheet().worksheet("clientes")
        clientes = hoja.col_values(2)
        nombre_lower = nombre.strip().lower()
        for i, c in enumerate(clientes):
            if c.strip().lower() == nombre_lower:
                fila = i + 1
                if nuevo_estado:
                    hoja.update_cell(fila, 12, nuevo_estado)
                if proxima_accion:
                    hoja.update_cell(fila, 13, proxima_accion)
                if fecha_seguimiento:
                    hoja.update_cell(fila, 14, fecha_seguimiento)
                if observaciones:
                    hoja.update_cell(fila, 18, observaciones)
                return True
        return False
    except Exception as e:
        logger.error(f"Error actualizando cliente: {e}")
        return False

def calcular_consumo(dosis, superficie):
    try:
        return round(float(str(dosis).replace(",", ".")) * float(str(superficie).replace(",", ".")), 2)
    except:
        return ""

def save_receta(worksheet, data, receta_num):
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

async def enviar_recordatorios(context):
    try:
        today = datetime.now().date()
        clientes = get_clientes_activos()
        pendientes_hoy = []
        atrasados = []

        for c in clientes:
            estado = str(c.get("Estado", "")).lower()
            if estado in ["cerrado", "perdido"]:
                continue
            fecha_seg = c.get("Fecha seguimiento", "")
            cliente = c.get("Cliente", "")
            proxima = c.get("Proxima accion", "")
            if fecha_seg:
                try:
                    fecha = datetime.strptime(fecha_seg, "%d/%m/%Y").date()
                    dias_diff = (today - fecha).days
                    if fecha == today:
                        pendientes_hoy.append("- " + cliente + ": " + proxima)
                    elif dias_diff > 0:
                        atrasados.append("- " + cliente + " (hace " + str(dias_diff) + " dias): " + proxima)
                except:
                    pass

        if not pendientes_hoy and not atrasados:
            return

        msg = "Buenos dias! Resumen comercial:\n\n"
        if pendientes_hoy:
            msg += "PARA HOY:\n" + "\n".join(pendientes_hoy) + "\n\n"
        if atrasados:
            msg += "ATRASADOS:\n" + "\n".join(atrasados) + "\n"

        await context.bot.send_message(chat_id=MY_CHAT_ID, text=msg)

    except Exception as e:
        logger.error(f"Error en recordatorios: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id

    try:
        text = None
        es_archivo = False

        if message.voice:
            await context.bot.send_message(chat_id=chat_id, text="Transcribiendo audio...")
            file = await context.bot.get_file(message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                text = transcribe_audio(tmp.name)
                os.unlink(tmp.name)

        elif message.photo:
            await context.bot.send_message(chat_id=chat_id, text="Leyendo imagen...")
            photo = message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                text = transcribe_image(tmp.name)
                os.unlink(tmp.name)
            es_archivo = True

        elif message.document:
            mime = message.document.mime_type or ""
            if mime.startswith("image/"):
                await context.bot.send_message(chat_id=chat_id, text="Leyendo imagen...")
                file = await context.bot.get_file(message.document.file_id)
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    await file.download_to_drive(tmp.name)
                    text = transcribe_image(tmp.name)
                    os.unlink(tmp.name)
                es_archivo = True
            elif mime == "application/pdf":
                await context.bot.send_message(chat_id=chat_id, text="Leyendo PDF...")
                file = await context.bot.get_file(message.document.file_id)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    await file.download_to_drive(tmp.name)
                    text = transcribe_pdf(tmp.name)
                    os.unlink(tmp.name)
                es_archivo = True
            else:
                await context.bot.send_message(chat_id=chat_id, text="Formato no soportado. Manda texto, audio, imagen o PDF.")
                return

        elif message.text:
            text = message.text

        else:
            await context.bot.send_message(chat_id=chat_id, text="Solo puedo procesar texto, audio, imagenes o PDFs.")
            return

        await context.bot.send_message(chat_id=chat_id, text="Procesando...")

        # Si tiene caption, combinarlo con el texto extraido
        if es_archivo and message.caption:
            text = message.caption + "\n\n" + text

        categoria = clasificar_mensaje(text)
        sh = get_google_sheet()

        if categoria == "receta":
            data = extract_receta(text)
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
            rows = save_receta(worksheet, data, receta_num)

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

        elif categoria == "cliente_nuevo":
            data = extract_cliente_nuevo(text)
            sh.worksheet("clientes").append_row([
                data.get("fecha", ""),
                data.get("cliente", ""),
                data.get("empresa", ""),
                data.get("zona", ""),
                data.get("provincia", ""),
                data.get("contacto", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("origen", ""),
                data.get("necesidad", ""),
                data.get("tipo_trabajo", ""),
                data.get("estado", ""),
                data.get("proxima_accion", ""),
                data.get("fecha_seguimiento", ""),
                data.get("presupuesto", ""),
                data.get("probabilidad_cierre", ""),
                data.get("prioridad", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Cliente guardado!\n\n"
                "Cliente: " + str(data.get("cliente", "")) + "\n"
                "Empresa: " + str(data.get("empresa", "") or "-") + "\n"
                "Zona: " + str(data.get("zona", "") or "-") + "\n"
                "Tipo de trabajo: " + str(data.get("tipo_trabajo", "") or "-") + "\n"
                "Estado: " + str(data.get("estado", "")) + "\n"
                "Proxima accion: " + str(data.get("proxima_accion", "") or "-") + "\n"
                "Seguimiento: " + str(data.get("fecha_seguimiento", "")) + "\n"
                "Prioridad: " + str(data.get("prioridad", ""))
            )

        elif categoria == "cliente_consulta":
            clientes = get_clientes_activos()
            activos = [c for c in clientes if str(c.get("Estado", "")).lower() not in ["cerrado", "perdido"]]
            if not activos:
                respuesta = "No hay clientes activos en seguimiento."
            else:
                lineas = ["Clientes activos:\n"]
                for c in activos:
                    lineas.append(
                        "- " + str(c.get("Cliente", "")) + "\n"
                        "  Estado: " + str(c.get("Estado", "")) + "\n"
                        "  Proxima accion: " + str(c.get("Proxima accion", "")) + "\n"
                        "  Seguimiento: " + str(c.get("Fecha seguimiento", "")) + "\n"
                    )
                respuesta = "\n".join(lineas)

        elif categoria == "cliente_update":
            data = extract_cliente_update(text)
            nombre = data.get("cliente", "")
            ok = buscar_y_actualizar_cliente(
                nombre,
                nuevo_estado=data.get("nuevo_estado"),
                proxima_accion=data.get("proxima_accion"),
                fecha_seguimiento=data.get("fecha_seguimiento"),
                observaciones=data.get("observaciones")
            )
            if ok:
                respuesta = "Cliente " + nombre + " actualizado."
            else:
                respuesta = "No encontre el cliente '" + nombre + "'. Verifica el nombre."

        elif categoria == "tarea":
            data = extract_tarea(text)
            sh.worksheet("tareas").append_row([
                data.get("fecha", ""),
                data.get("tarea", ""),
                data.get("cliente", ""),
                data.get("categoria", ""),
                data.get("responsable", ""),
                data.get("estado", ""),
                data.get("prioridad", ""),
                data.get("fecha_limite", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Tarea guardada!\n\n"
                + str(data.get("tarea", "")) + "\n"
                "Cliente: " + str(data.get("cliente", "") or "-") + "\n"
                "Categoria: " + str(data.get("categoria", "")) + "\n"
                "Prioridad: " + str(data.get("prioridad", "")) + "\n"
                "Fecha limite: " + str(data.get("fecha_limite", ""))
            )

        elif categoria == "recorrida":
            data = extract_recorrida(text)
            sh.worksheet("recorridas").append_row([
                data.get("fecha", ""),
                data.get("cliente", ""),
                data.get("campo", ""),
                data.get("zona", ""),
                data.get("resumen", ""),
                data.get("problemas", ""),
                data.get("recomendaciones", ""),
                data.get("urgencia", ""),
                data.get("proxima_visita", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Recorrida guardada!\n\n"
                "Cliente: " + str(data.get("cliente", "")) + "\n"
                "Campo: " + str(data.get("campo", "") or "-") + "\n"
                "Resumen: " + str(data.get("resumen", "")) + "\n"
                "Urgencia: " + str(data.get("urgencia", "")) + "\n"
                "Proxima visita: " + str(data.get("proxima_visita", ""))
            )

        elif categoria == "presupuesto":
            data = extract_presupuesto(text)
            sh.worksheet("presupuestos").append_row([
                data.get("fecha", ""),
                data.get("cliente", ""),
                data.get("trabajo", ""),
                data.get("descripcion", ""),
                data.get("honorarios", ""),
                data.get("viaticos", ""),
                data.get("total", ""),
                data.get("estado", ""),
                data.get("fecha_envio", ""),
                data.get("fecha_respuesta", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Presupuesto guardado!\n\n"
                "Cliente: " + str(data.get("cliente", "")) + "\n"
                "Trabajo: " + str(data.get("trabajo", "")) + "\n"
                "Total: " + str(data.get("total", "")) + "\n"
                "Estado: " + str(data.get("estado", "")) + "\n"
                "Fecha envio: " + str(data.get("fecha_envio", ""))
            )

        elif categoria == "compra":
            data = extract_compra(text)
            sh.worksheet("compras").append_row([
                data.get("fecha", ""),
                data.get("cliente_obra", ""),
                data.get("material", ""),
                data.get("cantidad", ""),
                data.get("unidad", ""),
                data.get("proveedor", ""),
                data.get("precio_unitario", ""),
                data.get("total", ""),
                data.get("estado", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Compra guardada!\n\n"
                + str(data.get("material", "")) + "\n"
                "Cantidad: " + str(data.get("cantidad", "") or "-") + " " + str(data.get("unidad", "") or "") + "\n"
                "Obra: " + str(data.get("cliente_obra", "") or "-") + "\n"
                "Estado: " + str(data.get("estado", ""))
            )

        elif categoria == "idea":
            data = extract_idea(text)
            sh.worksheet("ideas").append_row([
                data.get("fecha", ""),
                data.get("tipo", ""),
                data.get("idea", ""),
                data.get("cliente_tema", ""),
                data.get("estado", ""),
                data.get("observaciones", "")
            ])
            respuesta = (
                "Idea guardada!\n\n"
                + str(data.get("idea", "")) + "\n"
                "Tipo: " + str(data.get("tipo", "")) + "\n"
                "Tema: " + str(data.get("cliente_tema", "") or "-")
            )

        else:
            respuesta = "No pude clasificar el mensaje. Intenta ser mas especifico."

        await context.bot.send_message(chat_id=chat_id, text=respuesta)

    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Error al procesar: " + str(e))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(
        filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL,
        handle_message
    ))

    # Recordatorio diario a las 8am Argentina (UTC-3 = 11:00 UTC)
    app.job_queue.run_daily(
        enviar_recordatorios,
        time=datetime.strptime("11:00", "%H:%M").time()
    )

    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
