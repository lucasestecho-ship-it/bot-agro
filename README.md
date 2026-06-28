# Bot Agro

Bot de Telegram en Python con una PWA de campo en `/campo` para capturar audios y fotos con GPS y sincronizacion offline.

## Entrypoint actual

La app ASGI para despliegue es:

```bash
main:fastapi_app
```

El comando recomendado para Koyeb es:

```bash
sh start.sh
```

`start.sh` ejecuta:

```bash
exec uvicorn main:fastapi_app --host 0.0.0.0 --port "${PORT:-8000}"
```

## Probar localmente

1. Instalar dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Configurar variables de entorno sin claves reales en el codigo:

   ```bash
   export TELEGRAM_TOKEN="..."
   export OPENAI_API_KEY="..."
   export GOOGLE_SHEET_ID="..."
   export GOOGLE_CREDENTIALS_JSON='...'
   export MY_CHAT_ID="1144480769"
   export DATA_DIR="/tmp/campo_bot"
   export FIELD_APP_TOKEN=""
   export ENABLE_TELEGRAM_BOT="false"
   ```

3. Arrancar la app:

   ```bash
   sh start.sh
   ```

4. Abrir `http://localhost:8000/campo`.

Los items subidos se guardan en `DATA_DIR/field_items/YYYY-MM-DD/`. Si `DATA_DIR` no esta definido, usa `/tmp/campo_bot`.

## Desplegar en Koyeb Free

1. Crear una app nueva en Koyeb y conectar el repo de GitHub.
2. Elegir una instancia Free.
3. Configurar las variables de entorno:

   - `TELEGRAM_TOKEN`
   - `OPENAI_API_KEY`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_CREDENTIALS_JSON`
   - `MY_CHAT_ID`
   - `DATA_DIR` opcional, por defecto `/tmp/campo_bot`
   - `FIELD_APP_TOKEN` opcional para una etapa futura
   - `ENABLE_TELEGRAM_BOT=false` para probar primero solo `/campo`

4. Usar como Run command:

   ```bash
   sh start.sh
   ```

5. Abrir la URL publica de Koyeb y probar `/campo`.

## PWA de campo

La pantalla `/campo` permite:

- cargar recorrida/campo activo
- cargar sector opcional
- grabar audio desde el navegador
- sacar o subir foto
- capturar GPS si el navegador lo permite
- guardar items offline en el navegador
- sincronizar pendientes contra `POST /api/field-items`

Cada item guarda metadata: campo, sector, fecha/hora, latitud, longitud, precision GPS, tipo y estado.

## Fotos

Las fotos subidas desde `/campo` no se procesan con IA. El backend solo guarda el archivo como evidencia y escribe un JSON de metadata con `ai_processed: false`.

## Telegram

El bot de Telegram puede arrancar junto con FastAPI si:

```bash
ENABLE_TELEGRAM_BOT=true
```

Para la primera prueba en Koyeb conviene dejar:

```bash
ENABLE_TELEGRAM_BOT=false
```

Los comandos existentes `/recorrida_inicio`, `/cerrar_recorrida` y `/recorrida_cancelar` siguen registrados con los mismos handlers cuando el bot esta habilitado.
