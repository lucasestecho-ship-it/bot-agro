# Bot Agro

Bot de Telegram para registrar recetas, clientes, tareas, presupuestos, compras y recorridas. La app web minima de campo vive en `/campo` y permite guardar audios y fotos con GPS y sincronizacion offline.

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
   export DATA_DIR="./data"
   ```

   Para probar solo la PWA y el endpoint sin arrancar Telegram:

   ```bash
   export RUN_TELEGRAM_BOT=0
   ```

3. Arrancar FastAPI:

   ```bash
   uvicorn web_app:app --reload --host 0.0.0.0 --port 8000
   ```

4. Abrir `http://localhost:8000/campo`.

Los items subidos se guardan en `DATA_DIR/field_items/YYYY-MM-DD/`. Cada archivo queda junto a un `.json` con metadata: campo, sector, fecha/hora, latitud, longitud, precision GPS, tipo y estado. Las fotos de `/campo` se guardan solo como evidencia y no se envian a OpenAI ni se interpretan automaticamente.

## Railway

Railway usa el `Procfile`:

```bash
web: uvicorn web_app:app --host 0.0.0.0 --port $PORT
```

Variables esperadas:

- `TELEGRAM_TOKEN`
- `OPENAI_API_KEY`
- `GOOGLE_SHEET_ID`
- `GOOGLE_CREDENTIALS_JSON`
- `DATA_DIR` opcional, por defecto `./data`
- `RUN_TELEGRAM_BOT` opcional, usar `0` solo para desactivar el bot en pruebas

El bot de Telegram se inicia en paralelo con FastAPI. Los comandos existentes `/recorrida_inicio`, `/cerrar_recorrida` y `/recorrida_cancelar` siguen registrados con los mismos handlers.
