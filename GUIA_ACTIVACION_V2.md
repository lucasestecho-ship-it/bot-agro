# Activacion de Capataz Campo v2

Esta version convierte la app en una mesa de trabajo: Telegram recibe material, la cuadrilla lo procesa, los informes se generan al cerrar recorridas y Gmail recibe borradores listos para revisar.

## 1. Antes de fusionar

Ejecutar en Supabase SQL Editor el contenido completo de:

```text
supabase/capataz_campo.sql
```

El resultado final `items_sin_recorrida` debe seguir dando `0`.

## 2. Desplegar

Fusionar el PR y esperar **Deploy live** en Render. Verificar:

```text
https://bot-agro-campo.onrender.com/api/health/campo
```

## 3. Telegram

En Render, confirmar que `TELEGRAM_TOKEN` y `MY_CHAT_ID` ya tienen valor. Cambiar:

```text
ENABLE_TELEGRAM_BOT=true
```

Guardar y esperar el deploy. En Telegram, abrir el bot y enviar `/status`. Desde WhatsApp: **Compartir > Telegram > chat del bot**.

## 4. Gmail de Lucas

En Google Cloud:

1. habilitar Gmail API;
2. configurar la pantalla de consentimiento;
3. para una prueba corta, agregar `lucas.estecho@gmail.com` como usuario de prueba;
4. para que la autorizacion no caduque a los siete dias, cambiar el estado de publicacion a **In production** antes de generar el token definitivo;
5. crear un cliente OAuth de tipo **Desktop app**;
6. descargar el JSON.

En PowerShell, dentro del repo actualizado:

```powershell
.\windows\configurar_gmail.ps1
```

Elegir `lucas.estecho@gmail.com` en el navegador. El asistente crea:

```text
Documents\CapatazCampo\gmail_render_variables.json
```

Copiar sus cuatro valores a Render y borrar el JSON local cuando se haya confirmado que Gmail funciona. No subirlo a GitHub ni mandarlo por chat.

## 4 bis. NDVI Sentinel automatico

En el panel Sentinel Hub de Copernicus Data Space, crear un OAuth Client y guardar en Render:

```text
CDSE_CLIENT_ID
CDSE_CLIENT_SECRET
CDSE_NDVI_LOOKBACK_DAYS=45
CDSE_MAX_CLOUD_PERCENT=30
```

El bot agrupa KML, GeoTIFF y XML auxiliares de un mismo envio. Calcula topografia desde el DEM y, si el texto pide NDVI, usa el KML como area de interes para solicitar Sentinel-2 L2A. Si las credenciales no estan configuradas, no inventa un NDVI: termina la topografia y muestra el faltante.

## 5. Archivador de Supabase

En la misma PowerShell:

```powershell
.\windows\instalar_archivador.ps1
```

Ingresar `FIELD_APP_TOKEN` cuando lo pida. Se crean tareas a las 20:00 y al iniciar sesion. Para una prueba manual:

```powershell
& "$env:LOCALAPPDATA\CapatazCampo\runner\.venv\Scripts\python.exe" "$env:LOCALAPPDATA\CapatazCampo\runner\archivar_supabase.py" --verbose
```

Los archivos quedan en:

```text
C:\Users\Lucas Estecho\Documents\CapatazCampo\Archivo
```

## 6. Prueba funcional

1. Compartir al bot: `Doña Elena. Prepará un correo a prueba@example.com con un resumen y no lo envíes.`
2. Esperar `Trabajo terminado` en Telegram.
3. Abrir `/campo`: debe aparecer el trabajo de los agentes y el correo preparado.
4. Revisar Borradores en Gmail; no debe existir ningún mensaje enviado.
5. Hacer una recorrida con una foto y un audio, cerrarla y esperar el informe PDF/DOCX automático.
6. Ejecutar el archivador manual y comprobar que el archivo existe en Windows antes de verificar que desapareció de Supabase Storage.
7. Compartir juntos un KML, un DEM GeoTIFF y el pedido `analizar topografia para agua y NDVI`; debe responder una sola vez con cotas y pendientes calculadas. El NDVI se agrega si CDSE esta configurado.
