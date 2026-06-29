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

### SQL para recorridas

Ejecutar en Supabase SQL Editor:

```sql
create table if not exists public.field_sessions (
  id text primary key,
  nombre text,
  campo text,
  sector text,
  estado text,
  started_at timestamptz,
  closed_at timestamptz,
  latitud_inicio double precision,
  longitud_inicio double precision,
  precision_gps_inicio double precision,
  notas text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.field_items
add column if not exists session_id text;

alter table public.field_items
add column if not exists transcript_status text,
add column if not exists transcript_text text,
add column if not exists transcript_error text,
add column if not exists transcript_model text,
add column if not exists transcript_at timestamptz;

create index if not exists idx_field_items_session_id
on public.field_items (session_id);

create table if not exists public.field_reports (
  id text primary key,
  session_id text,
  estado text,
  titulo text,
  resumen text,
  informe_markdown text,
  docx_storage_path text,
  docx_public_url text,
  error text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```

Los items viejos pueden quedar con `session_id` en `null`. La app sigue listandolos igual.

### Informes de recorrida

La app agrega un boton **Generar informe** en cada recorrida. El backend:

- lee la recorrida y sus items desde Supabase Database
- transcribe audios con OpenAI si todavia no tienen `transcript_text`
- guarda la transcripcion en `public.field_items`
- genera un informe tecnico en Markdown
- crea un DOCX con `python-docx`
- sube el DOCX a Supabase Storage en `reports/<campo>/<session_id>/...`
- guarda el resultado en `public.field_reports`

Endpoints:

- `POST /api/field-sessions/{session_id}/generate-report`
- `GET /api/field-sessions/{session_id}/report`

Las fotos no se interpretan con IA. Solo se insertan en el DOCX como evidencia junto con fecha, campo, sector, GPS, precision, archivo y link publico si existe.

Para generar informes se necesita `OPENAI_API_KEY`. Opcionalmente se puede configurar `FIELD_REPORT_MODEL`; si no esta definido, usa `gpt-4o-mini`.

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
