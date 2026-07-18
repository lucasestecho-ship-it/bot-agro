# Capataz Campo

PWA Android y cuadrilla de agentes para recorridas, audios, fotos, clientes, decisiones, informes y borradores de correo. FastAPI corre en Render; Supabase conserva temporalmente los datos y una tarea de Windows archiva los archivos pesados en la computadora.

La aplicacion anterior se llamaba internamente Bot Agro. La interfaz y el manifiesto ahora usan exclusivamente **Capataz Campo**.

## Entrypoint actual

La app ASGI para despliegue es:

```bash
main:fastapi_app
```

El comando local opcional es:

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

## Desplegar en Render Free

1. Crear un Web Service nuevo en Render y conectar el repo de GitHub.
2. Elegir plan Free.
3. Configurar las variables de entorno:

   - `DATA_DIR=/tmp/campo_bot`
   - `FIELD_APP_TOKEN=un_token_largo`
   - `ENABLE_TELEGRAM_BOT=false` para probar primero solo `/campo`

4. Usar como Build Command:

   ```bash
   pip install -r requirements.txt
   ```

5. Usar como Start Command:

   ```bash
   uvicorn main:fastapi_app --host 0.0.0.0 --port $PORT
   ```

6. Abrir la URL publica de Render y probar `/campo`.

Tambien se incluye `render.yaml` y una guia especifica en `README_RENDER.md`.

## PWA de campo

La pantalla `/campo` permite:

- cargar recorrida/campo activo
- cargar sector opcional
- grabar audio desde el navegador
- sacar o subir foto
- capturar GPS si el navegador lo permite
- guardar items offline en el navegador
- sincronizar pendientes contra `POST /api/field-items`
- impedir que una foto o un audio se suban sin recorrida activa
- verificar en Supabase que cada archivo conserve el mismo `session_id`
- recibir texto compartido desde Android
- asignar texto o audios a los agentes y mostrar arriba el trabajo terminado
- mostrar tareas atrasadas, para hoy y proximas
- subir automaticamente cuando hay conexion, sin pedir etiquetas despues de cada foto o audio
- mostrar decisiones tecnicas y economicas para aprobar o descartar
- recibir avisos push aunque la PWA no este abierta, cuando Web Push esta configurado
- generar informes de recorrida en PDF y DOCX, con una seccion economica y sin inventar precios
- generar automaticamente el informe cuando una recorrida queda cerrada y todos sus archivos subieron
- mostrar los informes, analisis y correos preparados como resultados de trabajo, no como simples recordatorios

Cada item guarda metadata: campo, sector, fecha/hora, latitud, longitud, precision GPS, tipo y estado.

## Cuadrilla de agentes

`Capataz` clasifica la entrada y llama solamente a los especialistas necesarios:

- `Cartera`: clientes, compromisos y proximo contacto.
- `Aqua`: sistema de agua a escala de campo.
- `Hidro`: caudal, presion, bombas, diametros y perdidas.
- `Topo`: cotas, pendientes, DEM, cuencas y ubicacion de obras.
- `Margen`: costos, beneficios, supuestos, sensibilidad y riesgo economico.
- `Informes`: estructura informes trazables.
- `Comercial`: oportunidades, propuestas y siguiente paso comercial.
- `Recetas`: controla datos obligatorios sin inventar dosis.
- `Tero`: planillas, formulas, unidades y validaciones.
- `Contralor`: audita las salidas antes de mostrar una decision.
- `Ejecutor`: convierte una decision aprobada por Lucas en tareas; no comunica ni ejecuta acciones externas por su cuenta.

Las notas simples de seguimiento no generan una segunda aprobacion innecesaria. Las decisiones tecnicas, de agua o economicas aparecen en **Por decidir** y solo crean tareas nuevas cuando Lucas las aprueba. Los agentes sí producen resultados antes de esa aprobación: analisis auditados, informes y borradores reales de Gmail.

## Entrada por Telegram desde WhatsApp

Con `ENABLE_TELEGRAM_BOT=true`, el bot privado acepta texto, audio, foto y PDF. En Android se puede usar **Compartir** desde WhatsApp, elegir Telegram y seleccionar el chat del bot. La entrada se transcribe o lee, se guarda, se asigna a la cuadrilla y el bot devuelve un resumen del trabajo.

Solo se atiende el chat configurado en `MY_CHAT_ID`. El handler nuevo no depende de Google Sheets ni de Google Drive.

## Borradores de Gmail

Si la entrada pide un correo, una respuesta, una propuesta o un presupuesto, `Comercial` e `Informes` preparan el texto y el backend llama unicamente a `users.drafts.create`. No existe una ruta para enviar el mensaje. Lucas lo revisa y lo envia desde Gmail.

Variables de Render:

```text
GMAIL_CLIENT_ID
GMAIL_CLIENT_SECRET
GMAIL_REFRESH_TOKEN
GMAIL_SENDER=lucas.estecho@gmail.com
```

La autorizacion inicial se realiza una sola vez en Windows con `windows/configurar_gmail.ps1`.
Para uso duradero, el proyecto OAuth externo no debe quedar en estado `Testing`, porque Google limita esos refresh tokens a siete dias cuando se solicitan permisos de Gmail.

## Archivo local y limpieza de Supabase

`windows/instalar_archivador.ps1` configura dos tareas de Windows: al iniciar sesion y todos los dias a las 20:00. El archivador:

1. pide a Render un manifiesto con URLs de descarga temporales;
2. descarga cada archivo a `Documents\CapatazCampo\Archivo`;
3. verifica que la descarga no este vacia o incompleta y calcula SHA-256;
4. confirma a Render la ruta exacta, tamaño y hash;
5. recien entonces Render elimina ese objeto puntual de Supabase Storage.

La `service_role` permanece en Render. Windows guarda solamente `FIELD_APP_TOKEN` en el Administrador de credenciales.
Los originales de una recorrida no entran al manifiesto mientras siga abierta, el informe este en proceso o el informe haya fallado.

## Migracion de Supabase

Ejecutar completa [`supabase/capataz_campo.sql`](supabase/capataz_campo.sql) desde Supabase SQL Editor. Es idempotente y no borra registros anteriores.

El error anterior de vinculacion podia quedar oculto: el archivo se mostraba como subido aunque Supabase hubiera rechazado la metadata. Ahora la PWA exige estos tres pasos antes de confirmar una carga:

1. la recorrida debe existir en Supabase;
2. la metadata del archivo debe guardarse sin error;
3. una lectura posterior debe devolver el mismo `session_id`.

Si cualquiera falla, el item queda visible en estado `error` para poder reintentarlo y no aparece falsamente como asignado.

Los items históricos con `session_id` vacío aparecen como **SIN RECORRIDA ASIGNADA** dentro del panel técnico. Se pueden vincular manualmente a una recorrida real; la app vuelve a leer Supabase y confirma la reparación antes de actualizar la pantalla.

## Fotos

Las fotos subidas desde `/campo` no se procesan con IA. El backend solo guarda el archivo como evidencia y escribe un JSON de metadata con `ai_processed: false`.

## Seguridad y consistencia

En Render, `FIELD_APP_TOKEN` es obligatorio. La PWA lo pide una sola vez y lo conserva en el telefono. La clave `service_role` nunca sale del backend. Las confirmaciones, las aprobaciones y sus tareas se guardan mediante funciones transaccionales de Supabase: se guarda todo o no se guarda nada.

## Activar Telegram

El bot puede arrancar junto con FastAPI si:

```bash
ENABLE_TELEGRAM_BOT=true
```

Durante la migracion se deja apagado; se cambia a `true` despues de ejecutar el SQL nuevo y desplegar:

```bash
ENABLE_TELEGRAM_BOT=false
```

Los comandos disponibles son `/start` y `/status`. El flujo normal consiste en compartirle texto, audio, foto o PDF.
