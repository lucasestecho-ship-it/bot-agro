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
CDSE_NDVI_YEARS=9
CDSE_NDVI_WIDTH=768
CDSE_NDVI_HEIGHT=768
CDSE_MAX_CLOUD_PERCENT=60
```

El bot agrupa el paquete durante ocho segundos para recibir todos sus componentes. Para NDVI, la forma recomendada es un ZIP con el Shapefile de lotes (`SHP`, `SHX`, `DBF`, `PRJ`) y el pedido `hacer informe NDVI multianual por lote`. El campo `Name` o `Nombre` debe identificar los lotes y distinguir Forestal/Monte/Eucalipto/Pino. Para reproducir el indice integrado del informe Don Policarpo, agregar:

- un Shapefile de suelos con campo `UC` o `Unidad` y `Aptitud` entre 0 y 100;
- un DEM GeoTIFF para elevacion y pendiente por lote.

El motor descarga nueve cortes estacionales comparables, calcula P90 anual, mediana multianual, estabilidad, cambio reciente, ambientes y ranking, y devuelve por Telegram un PDF de ocho paginas. UC 40, UC 9 y UC 37 usan las aptitudes de la referencia; para otras unidades debe venir `Aptitud` o configurarse `SOIL_APTITUDE_MAP_JSON`, por ejemplo `{"Serie A": 80, "Serie B": 45}`. Solo con cobertura edafica completa aplica 65% respuesta satelital + 35% aptitud; de lo contrario informa que el ranking es satelital. Si las credenciales no estan configuradas, no inventa un NDVI.

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
4. Revisar Borradores en Gmail; no debe existir ningún mensaje enviado. Para una prueba controlada, copiar el comando exacto `/enviar_correo email-...` que devuelve el bot y comprobar que solo ese borrador se envia una vez.
5. Hacer una recorrida con una foto y un audio, cerrarla y esperar el informe PDF/DOCX automático.
6. Ejecutar el archivador manual y comprobar que el archivo existe en Windows antes de verificar que desapareció de Supabase Storage.
7. Compartir un ZIP con lotes SHP/SHX/DBF/PRJ y pedir `hacer informe NDVI multianual por lote`; debe devolver un PDF NDVI de ocho paginas. Agregar suelos y DEM para obtener la entrega completa como Don Policarpo.
8. Para topografia, compartir el perimetro, el DEM GeoTIFF y pedir `preparar informe topografico para agua`; debe devolver el PDF topografico de diez paginas.
