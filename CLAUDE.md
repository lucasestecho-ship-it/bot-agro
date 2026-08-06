# Capataz Campo (bot-agro)

Asistente de consultora agropecuaria de Lucas Estecho (Entre Ríos, Argentina). PWA Android + bot de Telegram + cuadrilla de agentes internos para recorridas de campo, audios, fotos, clientes, decisiones e informes profesionales (PDF/DOCX).

## Arquitectura

- **`main.py`** — app FastAPI (entrypoint `main:fastapi_app`). Contiene el bot de Telegram (webhook, NO polling en producción), la PWA `/campo`, generación de informes PDF/DOCX y la lógica de recorridas.
- **`llm.py`** — puerta única a los modelos de IA. `complete()` para texto, `transcribe()` para audios, con perfiles de modelo (`informe`, `rapido`, `vision`, `transcripcion`), reintentos y respaldo automático en otro proveedor.
- **`capataz.py`** — orquestador "Capataz": recibe eventos, enruta a los agentes, gestiona decisiones que Lucas aprueba/rechaza.
- **`agent_crew.py`** — cuadrilla de agentes internos (corren con OpenAI en producción): Cartera, Aqua, Hidro, Topo, Margen, Informes, Comercial, Recetas, Tero, Contralor, Ejecutor. Registry en `AGENT_SPECS`.
- **`geospatial_worker.py`** — análisis geoespacial: DEM/topografía, NDVI (rasters, KML/GeoJSON, descarga desde Copernicus CDSE).
- **`archive_manager.py` / `windows/archivar_supabase.py`** — tarea de Windows que archiva archivos pesados en la PC de Lucas. Descarga y **borra** del storage: es archivar, no respaldar.
- **`windows/respaldar_supabase.py`** — respaldo diario de la base a un ZIP fechado en Dropbox, con rotación. Solo lee (`/api/backup/*`), nunca borra. Cubre lo irrecuperable: recorridas, transcripciones, texto de informes, clientes, decisiones. Si se agrega una tabla nueva al esquema, hay que sumarla a `BACKUP_TABLES` en `main.py` o queda fuera del respaldo.
- **`gmail_drafts.py`** — borradores de correo vía Gmail API.
- **Infra:** Render Free (deploy automático al pushear a `main`), Supabase (storage temporal + cron), Telegram webhook.

## Reglas de oro (violarlas ya causó problemas reales)

1. **NUNCA inventar datos en informes.** Un informe de recorrida contiene SOLO las observaciones registradas (audios de Dani, agregados de Lucas). Prohibido agregar diagnósticos, prioridades, recomendaciones o "planes de acción" que nadie dictó. Regla ya reforzada en el prompt de informes y tests; no debilitarla.
2. **No inventar dosis, precios, fechas ni contactos** (cada agente lo tiene en sus instructions).
3. **Los entregables van a clientes reales.** PDF con identidad visual "Sol" (logo de sol), prolijos, en español rioplatense.
4. **Toda llamada a un modelo pasa por `llm.py`.** Prohibido `from openai import OpenAI`, `chat.completions.create` o `audio.transcriptions.create` fuera de ese archivo, y prohibido hardcodear nombres de modelo: se agrega un perfil en `MODEL_PROFILES`. Es lo que permite cambiar de proveedor con una variable de entorno en vez de una recorrida por el código. Hay un test que falla si `main.py` vuelve a llamar al proveedor directo.
5. **No romper el webhook de Telegram**: Render Free se duerme; el webhook lo despierta. `ENABLE_TELEGRAM_BOT` no debe volver a `false` en producción. Polling solo para desarrollo local.

## Flujo de trabajo

- Trabajar directo sobre este repo local. **Nada de bundles ni cherry-picks** (eso era el flujo viejo de Codex).
- Rama `agent/<descripcion>` desde `origin/main` → commit → `git push -u origin HEAD` → `gh pr create` → `gh pr merge --squash`. Render despliega `main` automáticamente.
- Antes de cualquier PR: correr `python -m pytest tests/` (deben pasar todos, ~47+).
- Lucas no es programador: explicarle en castellano simple qué se cambió y por qué; no pedirle que pegue comandos salvo que sea imprescindible.

## Comandos

```bash
pip install -r requirements.txt
python -m pytest tests/          # tests
sh start.sh                       # local: uvicorn main:fastapi_app, abre /campo
```

## Secretos

Tokens y claves viven en variables de entorno de Render / archivos locales fuera de git. Jamás hardcodear claves ni commitear `.pem`, tokens o refresh tokens.
