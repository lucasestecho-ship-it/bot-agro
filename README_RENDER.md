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
GOOGLE_DRIVE_FOLDER_ID=id_de_la_carpeta_drive
ENABLE_TELEGRAM_BOT=false
```

Variables opcionales/necesarias si se habilita Telegram o las funciones del bot:

```bash
TELEGRAM_TOKEN=...
OPENAI_API_KEY=...
GOOGLE_SHEET_ID=...
GOOGLE_CREDENTIALS_JSON=...
MY_CHAT_ID=1144480769
```

## Google Drive para archivos de campo

Si `GOOGLE_DRIVE_FOLDER_ID` esta configurado, cada audio o foto recibido por `POST /api/field-items` se guarda primero en `DATA_DIR` y despues se sube a esa carpeta de Google Drive.

Para configurarlo:

1. Crear una carpeta en Google Drive para los archivos de campo.
2. Abrir la carpeta y copiar el ID desde la URL. En una URL como:

   ```text
   https://drive.google.com/drive/folders/XXXXXXXXXXXX
   ```

   el valor `XXXXXXXXXXXX` es `GOOGLE_DRIVE_FOLDER_ID`.

3. Buscar el email de la service account dentro de `GOOGLE_CREDENTIALS_JSON`, en el campo `client_email`.
4. Compartir la carpeta de Drive con ese email como Editor.
5. En Render, agregar:

   ```bash
   GOOGLE_DRIVE_FOLDER_ID=XXXXXXXXXXXX
   ```

Metadata guardada:

- `storage_status=drive_uploaded` si Drive confirmo la subida
- `drive_file_id`
- `drive_web_link`
- `storage_status=local_only` si no hay `GOOGLE_DRIVE_FOLDER_ID`
- `storage_status=drive_error` si Drive fallo, conservando el archivo local

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
- `GOOGLE_DRIVE_FOLDER_ID` opcional para subir audios/fotos a Drive
- `ENABLE_TELEGRAM_BOT=false`

## Verificaciones

- `main.py` expone `fastapi_app`.
- `/campo` devuelve `static/index.html`.
- `POST /api/field-items` guarda el archivo y un `.json` de metadata en `DATA_DIR/field_items/YYYY-MM-DD/`.
- Las fotos se guardan solo como evidencia con metadata. No se procesan con IA desde `/campo`.
