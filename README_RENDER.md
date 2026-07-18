# Capataz Campo en Render

Esta configuracion despliega la app FastAPI `main:fastapi_app` para que funcionen:

- `GET /`
- `GET /campo`
- `GET /docs`
- `POST /api/field-items`
- `GET /api/capataz/dashboard`
- `POST /api/capataz/analyze`
- `POST /api/capataz/confirm`

Antes del primer despliegue de esta version, ejecutar completo en Supabase SQL Editor:

```text
supabase/capataz_campo.sql
```

La migracion agrega las columnas necesarias para conservar `session_id`, la cuadrilla de agentes, decisiones, tareas, proyectos de agua, suscripciones push, borradores de Gmail, archivos recibidos por Telegram y el manifiesto del archivador local. Tambien crea las funciones transaccionales. No borra datos anteriores.

El orden de activacion de esta version es importante:

1. subir la rama y abrir el PR, sin fusionar todavia;
2. ejecutar `supabase/capataz_campo.sql` completo;
3. fusionar y esperar el deploy de Render;
4. cargar OAuth de Gmail;
5. cambiar `ENABLE_TELEGRAM_BOT=true` y desplegar;
6. instalar el archivador de Windows.

La migracion debe ir antes del deploy porque el tablero nuevo lee `email_drafts` y `archive_objects`.

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

Para la app web actual en Render, sin Telegram y sin Google Drive, las variables reales son:

```bash
DATA_DIR=/tmp/campo_bot
ENABLE_TELEGRAM_BOT=false
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key
SUPABASE_BUCKET=campo-items
OPENAI_API_KEY=tu_openai_api_key
FIELD_APP_TOKEN=una_clave_larga_y_unica
```

Opcional:

```bash
FIELD_REPORT_MODEL=gpt-4o-mini
CAPATAZ_AGENT_MODEL=gpt-4o-mini
```

Para Gmail:

```bash
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
GMAIL_SENDER=lucas.estecho@gmail.com
```

La app usa OAuth de usuario y crea borradores; no puede usar la cuenta de servicio de Google Sheets para un Gmail personal.

`SUPABASE_SERVICE_ROLE_KEY` y `OPENAI_API_KEY` van solo en Render, nunca en el frontend.
Google Drive no se usa para la app `/campo`.

Si Render, Supabase u OpenAI estan configurados y falta `FIELD_APP_TOKEN`, las rutas privadas responden 503. Esto evita publicar una API con `service_role` sin proteccion.

## Avisos push en Android

1. En una computadora con Python, instalar `pywebpush` y generar un par VAPID:

   ```bash
   pip install pywebpush
   mkdir vapid
   cd vapid
   vapid --gen
   vapid --applicationServerKey
   ```

2. Cargar en Render:

   - `VAPID_PUBLIC_KEY`: el valor `Application Server Key`.
   - `VAPID_PRIVATE_KEY`: el contenido completo de `private_key.pem`.
   - `VAPID_SUBJECT`: un `mailto:correo@dominio.com` o una URL propia.

3. No subir los archivos PEM al repositorio. Estan ignorados por `.gitignore`.
4. Desplegar, abrir la PWA en Android y tocar **Activar avisos**.

Para que Supabase despierte Render y envie los avisos todos los dias a las 08:00 de Argentina, habilitar `pg_cron` y `pg_net` y programar una llamada. Reemplazar URL y token:

```sql
select cron.schedule(
  'capataz-recordatorios-diarios',
  '0 11 * * *',
  $$
  select net.http_post(
    url := 'https://TU_APP_RENDER.onrender.com/api/capataz/reminders/dispatch',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Field-App-Token', 'EL_MISMO_FIELD_APP_TOKEN_DE_RENDER'
    ),
    body := '{}'::jsonb
  );
  $$
);
```

`11:00 UTC` equivale a `08:00` de Argentina. El endpoint notifica pendientes y tambien reintenta materializar en Gmail los borradores preparados que hubieran quedado en espera.

## Archivar y liberar Supabase desde Windows

Despues del deploy, abrir PowerShell dentro del repo actualizado y ejecutar:

```powershell
.\windows\instalar_archivador.ps1
```

El instalador pide el mismo `FIELD_APP_TOKEN` de Render y usa por defecto:

```text
C:\Users\Lucas Estecho\Documents\CapatazCampo\Archivo
```

No copia la `SUPABASE_SERVICE_ROLE_KEY` a Windows. El borrado remoto ocurre en Render y solamente despues de que el cliente confirma una descarga completa con SHA-256, tamaño y ruta exacta.
Las evidencias de campo solo se ofrecen al archivador cuando la recorrida esta cerrada y existe un informe con estado `done`.

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

Ejecutar en Supabase SQL Editor. Es idempotente: sirve para crear lo que falte sin borrar datos viejos.

```sql
create table if not exists public.field_items (
  id text primary key,
  tipo text,
  campo text,
  sector text,
  fecha_hora timestamptz,
  latitud double precision,
  longitud double precision,
  precision_gps double precision,
  nombre_archivo text,
  estado text,
  storage_status text,
  storage_provider text,
  storage_path text,
  storage_public_url text,
  storage_error text,
  photo_label text,
  audio_label text,
  created_at timestamptz default now()
);

alter table public.field_items
add column if not exists id text,
add column if not exists tipo text,
add column if not exists campo text,
add column if not exists sector text,
add column if not exists fecha_hora timestamptz,
add column if not exists latitud double precision,
add column if not exists longitud double precision,
add column if not exists precision_gps double precision,
add column if not exists nombre_archivo text,
add column if not exists estado text,
add column if not exists storage_status text,
add column if not exists storage_provider text,
add column if not exists storage_path text,
add column if not exists storage_public_url text,
add column if not exists storage_error text,
add column if not exists photo_label text,
add column if not exists audio_label text,
add column if not exists session_id text,
add column if not exists transcript_status text,
add column if not exists transcript_text text,
add column if not exists transcript_error text,
add column if not exists transcript_model text,
add column if not exists transcript_at timestamptz,
add column if not exists created_at timestamptz default now();

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

alter table public.field_sessions
add column if not exists id text,
add column if not exists nombre text,
add column if not exists campo text,
add column if not exists sector text,
add column if not exists estado text,
add column if not exists started_at timestamptz,
add column if not exists closed_at timestamptz,
add column if not exists latitud_inicio double precision,
add column if not exists longitud_inicio double precision,
add column if not exists precision_gps_inicio double precision,
add column if not exists notas text,
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create table if not exists public.field_reports (
  id text primary key,
  session_id text,
  estado text,
  titulo text,
  resumen text,
  informe_markdown text,
  docx_storage_path text,
  docx_public_url text,
  pdf_storage_path text,
  pdf_public_url text,
  error text,
  progress_message text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.field_reports
add column if not exists id text,
add column if not exists session_id text,
add column if not exists estado text,
add column if not exists titulo text,
add column if not exists resumen text,
add column if not exists informe_markdown text,
add column if not exists docx_storage_path text,
add column if not exists docx_public_url text,
add column if not exists pdf_storage_path text,
add column if not exists pdf_public_url text,
add column if not exists error text,
add column if not exists progress_message text,
add column if not exists started_at timestamptz,
add column if not exists finished_at timestamptz,
add column if not exists created_at timestamptz default now(),
add column if not exists updated_at timestamptz default now();

create index if not exists idx_field_items_session_id
on public.field_items (session_id);

create index if not exists idx_field_items_campo_sector_no_session
on public.field_items (campo, sector)
where session_id is null;

create index if not exists idx_field_items_fecha_hora
on public.field_items (fecha_hora desc);

create index if not exists idx_field_sessions_started_at
on public.field_sessions (started_at desc);

create index if not exists idx_field_reports_session_id
on public.field_reports (session_id);

create index if not exists idx_field_reports_created_at
on public.field_reports (created_at desc);
```

Los items viejos pueden quedar con `session_id` en `null`. La app sigue listandolos igual.
Ademas, `/api/field-sessions` crea recorridas virtuales para esos items viejos, agrupadas por `campo` y `sector`, con nombre `Recorrida anterior - <campo>`.

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
- `GET /api/health/campo`

Las fotos no se interpretan con IA. Se insertan en el PDF y el DOCX como evidencia junto con fecha, campo, sector, GPS, precision, archivo y link publico si existe. El informe incorpora una seccion economica, pero deja explicitamente pendientes los precios, cantidades u horizontes no registrados.

Para generar informes se necesita `OPENAI_API_KEY`. Opcionalmente se puede configurar `FIELD_REPORT_MODEL`; si no esta definido, usa `gpt-4o-mini`.

## Diagnostico de campo

Abrir:

```text
https://TU_APP_RENDER.onrender.com/api/health/campo
```

Debe mostrar:

- `env.SUPABASE_URL=true`
- `env.SUPABASE_SERVICE_ROLE_KEY=true`
- `env.SUPABASE_BUCKET=true`
- `env.OPENAI_API_KEY=true` para generar informes
- `storage.can_write=true`
- `storage.can_read=true`
- `tables.field_items.exists=true`
- `tables.field_sessions.exists=true`
- `tables.field_reports.exists=true`
- `missing_columns=[]` en las tres tablas

Si aparece una columna faltante, ejecutar el SQL anterior completo.

## Probar campo viejo, ejemplo San Ignacio

1. Abrir `/api/health/campo` y confirmar que no falten columnas.
2. Abrir `/campo`.
3. Tocar **Actualizar** en Recorridas.
4. Buscar una tarjeta llamada `Recorrida anterior - San Ignacio`.
5. Confirmar que muestre `Items asociados` mayor a 0.
6. Tocar **Generar informe**.
7. Si falla, la tarjeta debe mostrar el error real. Tambien se puede abrir `/api/field-sessions/<session_id>/report` copiando el `session_id` desde la respuesta de `/api/field-sessions`.

## Variables opcionales del bot

Necesarias si se habilita Telegram o las funciones del bot:

```bash
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
MY_CHAT_ID=1144480769
```

Durante la migracion dejar:

```bash
ENABLE_TELEGRAM_BOT=false
```

Despues de ejecutar la migracion y verificar el deploy, cambiarla a `true`. El bot nuevo guarda en Supabase y no usa Google Sheets ni Google Drive.

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
