# Deploy en Render Free

Esta configuracion despliega la app FastAPI `main:fastapi_app` para que funcionen:

- `GET /`
- `GET /campo`
- `GET /docs`
- `POST /api/field-items`

## Configuracion manual

En Render, crear un **Web Service** conectado al repo de GitHub.

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
uvicorn main:fastapi_app --host 0.0.0.0 --port $PORT
```

## Variables minimas para probar /campo

```bash
DATA_DIR=/tmp/campo_bot
FIELD_APP_TOKEN=un_token_largo
ENABLE_TELEGRAM_BOT=false
```

## Supabase Storage para archivos persistentes

Si `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y `SUPABASE_BUCKET` estan configuradas, cada audio o foto recibido por `POST /api/field-items` se guarda primero en `DATA_DIR` y despues se sube a Supabase Storage.

La ruta dentro del bucket usa campo y sector sanitizados:

```text
campo/sector/YYYY-MM-DD/nombre_archivo
```

Pasos:

1. Crear un proyecto en Supabase.
2. Ir a **Storage** y crear un bucket, por ejemplo `campo-items`.
3. Si queres que la app muestre links abribles directamente, crear el bucket como publico. Si el bucket es privado, igual se sube el archivo, pero el link publico puede no abrir.
4. Copiar la URL del proyecto desde **Project Settings > API**.
5. Copiar la **service_role key** desde **Project Settings > API**. No usar esta clave en frontend.
6. En Render, agregar:

   ```bash
   SUPABASE_URL=https://TU_PROYECTO.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=...
   SUPABASE_BUCKET=campo-items
   ```

Metadata guardada:

- `storage_status=supabase_uploaded` si Supabase confirmo la subida
- `storage_provider=supabase`
- `storage_path`
- `storage_public_url`
- `storage_status=local_only` si faltan variables Supabase
- `storage_status=supabase_error` y `storage_error` si falla, conservando el archivo local

`SUPABASE_SERVICE_ROLE_KEY` nunca debe exponerse en frontend; solo va como variable de entorno del backend en Render.

## Supabase Database para metadata

Para que la metadata no dependa de `/tmp` en Render, crear la tabla `public.field_items` en Supabase con estas columnas:

```text
id, tipo, campo, sector, fecha_hora, latitud, longitud, precision_gps,
nombre_archivo, estado, storage_status, storage_provider, storage_path,
storage_public_url, storage_error, created_at
```

El backend usa las mismas variables `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`. Despues de recibir el archivo y subirlo a Storage, hace upsert en `public.field_items` usando `id` como primary key.

`GET /api/field-items` lee primero desde Supabase Database. Si la DB falla o no esta configurada, vuelve al fallback local en `DATA_DIR/field_items`.

## Variables opcionales del bot

Necesarias si se habilita Telegram o las funciones del bot:

```bash
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
GOOGLE_SHEET_ID=...
GOOGLE_CREDENTIALS_JSON=...
MY_CHAT_ID=1144480769
```

Para esta primera prueba dejar:

```bash
ENABLE_TELEGRAM_BOT=false
```

## Blueprint

Tambien se incluye `render.yaml` con:

- plan Free
- runtime Python
- build command `pip install -r requirements.txt`
- start command `uvicorn main:fastapi_app --host 0.0.0.0 --port $PORT`
- `DATA_DIR=/tmp/campo_bot`
- variables opcionales para Supabase Storage
- `ENABLE_TELEGRAM_BOT=false`

## Verificaciones

- `main.py` expone `fastapi_app`.
- `/campo` devuelve `static/index.html`.
- `POST /api/field-items` guarda el archivo y un `.json` de metadata en `DATA_DIR/field_items/YYYY-MM-DD/`.
- Si Supabase esta configurado, sube el archivo al bucket y guarda metadata de storage.
- Si Supabase Database esta configurado, guarda o actualiza la metadata en `public.field_items`.
- Las fotos se guardan solo como evidencia con metadata. No se procesan con IA desde `/campo`.
