const DB_NAME = "campo-pwa";
const STORE_NAME = "items";
const ACTIVE_SESSION_KEY = "campo.activeSession";
const SESSIONS_KEY = "campo.sessions";
const campoInput = document.getElementById("campoInput");
const sectorInput = document.getElementById("sectorInput");
const sessionNameInput = document.getElementById("sessionNameInput");
const talkButton = document.getElementById("talkButton");
const recordingControls = document.getElementById("recordingControls");
const recordingDuration = document.getElementById("recordingDuration");
const stopRecordingButton = document.getElementById("stopRecordingButton");
const cancelRecordingButton = document.getElementById("cancelRecordingButton");
const photoInput = document.getElementById("photoInput");
const itemsList = document.getElementById("itemsList");
const serverItemsList = document.getElementById("serverItemsList");
const sessionsList = document.getElementById("sessionsList");
const connectionStatus = document.getElementById("connectionStatus");
const gpsStatus = document.getElementById("gpsStatus");
const gpsButton = document.getElementById("gpsButton");
const syncButton = document.getElementById("syncButton");
const forceSyncButton = document.getElementById("forceSyncButton");
const refreshServerButton = document.getElementById("refreshServerButton");
const refreshSessionsButton = document.getElementById("refreshSessionsButton");
const startSessionButton = document.getElementById("startSessionButton");
const closeSessionButton = document.getElementById("closeSessionButton");
const activeSessionStatus = document.getElementById("activeSessionStatus");
const debugLog = document.getElementById("debugLog");

let dbPromise;
let recorder;
let audioChunks = [];
let currentPosition = null;
let recordingStartedAt = 0;
let recordingTimer = null;
let cancelCurrentRecording = false;
let longPressTimer = null;
let longPressRecording = false;
let suppressNextClick = false;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

async function storeItem(item) {
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(item);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

async function getItems() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).getAll();
    request.onsuccess = () => {
      const items = request.result.map(normalizeLocalItem);
      resolve(items.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
    };
    request.onerror = () => reject(request.error);
  });
}

function normalizeLocalItem(item) {
  if (item.status === "subido" && !item.serverConfirmed) {
    return { ...item, status: "pendiente" };
  }
  return item;
}

function readJsonStorage(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function getLocalSessions() {
  return readJsonStorage(SESSIONS_KEY, []);
}

function saveLocalSessions(sessions) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

function getActiveSession() {
  return readJsonStorage(ACTIVE_SESSION_KEY, null);
}

function saveActiveSession(session) {
  if (session) {
    localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(session));
  } else {
    localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

function upsertLocalSession(session) {
  const sessions = getLocalSessions();
  const index = sessions.findIndex((entry) => entry.id === session.id);
  if (index >= 0) {
    sessions[index] = { ...sessions[index], ...session };
  } else {
    sessions.push(session);
  }
  saveLocalSessions(sessions);
}

function currentSessionPayload(session) {
  return {
    id: session.id,
    nombre: session.nombre,
    campo: session.campo,
    sector: session.sector,
    estado: session.estado,
    started_at: session.startedAt,
    closed_at: session.closedAt || null,
    latitud_inicio: session.latitudInicio,
    longitud_inicio: session.longitudInicio,
    precision_gps_inicio: session.precisionGpsInicio,
    notas: session.notas || "",
    created_at: session.createdAt,
  };
}

async function syncSession(session) {
  if (!session || !navigator.onLine) return false;
  try {
    appendDebug(`Sincronizando recorrida ${session.nombre || session.id}...`);
    const response = await fetch("/api/field-sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentSessionPayload(session)),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error(data.detail || data.supabase_error || "respuesta sin ok true");
    if (data.supabase_error) appendDebug(`Recorrida Supabase ERROR: ${data.supabase_error}`);

    let updated = { ...session, syncStatus: "sincronizada", errorMessage: "" };
    if (updated.estado === "cerrada" && updated.closedAt) {
      const closeResponse = await fetch(`/api/field-sessions/${encodeURIComponent(updated.id)}/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ closed_at: updated.closedAt }),
      });
      if (!closeResponse.ok) throw new Error(`HTTP ${closeResponse.status}`);
      updated.syncStatus = "cerrada sincronizada";
    }
    upsertLocalSession(updated);
    if (getActiveSession()?.id === updated.id) saveActiveSession(updated);
    appendDebug("Recorrida sincronizada.");
    return true;
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    const updated = { ...session, syncStatus: "error", errorMessage: message };
    upsertLocalSession(updated);
    if (getActiveSession()?.id === updated.id) saveActiveSession(updated);
    appendDebug(`Recorrida ERROR: ${message}`);
    return false;
  }
}

async function syncLocalSessions() {
  if (!navigator.onLine) return;
  const sessions = getLocalSessions().filter((session) => {
    if (session.estado === "cerrada") return session.syncStatus !== "cerrada sincronizada";
    return session.syncStatus !== "sincronizada";
  });
  for (const session of sessions) {
    await syncSession(session);
  }
}

function appendDebug(message) {
  if (!debugLog) return;
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
  debugLog.prepend(li);
}

function persistInputs() {
  localStorage.setItem("campo.activo", campoInput.value);
  localStorage.setItem("campo.sector", sectorInput.value);
  if (sessionNameInput) localStorage.setItem("campo.sessionName", sessionNameInput.value);
}

function loadInputs() {
  campoInput.value = localStorage.getItem("campo.activo") || "";
  sectorInput.value = localStorage.getItem("campo.sector") || "";
  if (sessionNameInput) sessionNameInput.value = localStorage.getItem("campo.sessionName") || "";
}

function setConnectionStatus() {
  const online = navigator.onLine;
  connectionStatus.textContent = online ? "online" : "offline";
  connectionStatus.classList.toggle("online", online);
}

function refreshGps() {
  if (!navigator.geolocation) {
    gpsStatus.textContent = "GPS no disponible";
    return;
  }

  gpsStatus.textContent = "Buscando GPS...";
  navigator.geolocation.getCurrentPosition(
    (position) => {
      currentPosition = position;
      const { latitude, longitude, accuracy } = position.coords;
      gpsStatus.textContent = `${latitude.toFixed(5)}, ${longitude.toFixed(5)} (${Math.round(accuracy)} m)`;
    },
    () => {
      gpsStatus.textContent = "GPS sin permiso o sin señal";
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

function requireCampo() {
  const campo = campoInput.value.trim();
  if (!campo) {
    campoInput.focus();
    alert("Carga el campo activo antes de guardar.");
    return null;
  }
  return campo;
}

function buildItem(type, blob, filename, options = {}) {
  const campo = requireCampo();
  if (!campo) return null;

  const coords = currentPosition ? currentPosition.coords : {};
  const now = new Date();
  const activeSession = getActiveSession();
  return {
    id: crypto.randomUUID(),
    type,
    campo,
    sector: sectorInput.value.trim(),
    createdAt: now.toISOString(),
    latitude: coords.latitude ?? "",
    longitude: coords.longitude ?? "",
    gpsAccuracy: coords.accuracy ?? "",
    status: "pendiente",
    filename,
    contentType: blob.type,
    blob,
    sessionId: activeSession ? activeSession.id : "",
    sessionName: activeSession ? activeSession.nombre : "",
    photoLabel: options.photoLabel || "",
    audioLabel: options.audioLabel || "",
  };
}

async function addItem(type, blob, filename, options = {}) {
  const item = buildItem(type, blob, filename, options);
  if (!item) return;
  await storeItem(item);
  await renderItems();
  appendDebug("Item local creado en estado pendiente.");
}

async function renderItems() {
  const items = await getItems();
  itemsList.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "Sin items todavia.";
    itemsList.appendChild(empty);
    return;
  }

  for (const item of items) {
    const li = document.createElement("li");
    const gps = item.latitude && item.longitude
      ? `${Number(item.latitude).toFixed(5)}, ${Number(item.longitude).toFixed(5)}`
      : "sin GPS";
    const statusClass = item.status === "subido confirmado" ? "subido" : item.status;
    li.innerHTML = `
      <div class="item-main">
        <span>${item.type === "audio" ? "Audio" : "Foto"} - ${item.campo}</span>
        <span class="pill ${statusClass}">${item.status}</span>
      </div>
      <div class="item-meta">${item.sector || "sin sector"} - ${new Date(item.createdAt).toLocaleString()} - ${gps}</div>
      ${item.photoLabel ? `<div class="item-meta">Comentario foto: ${item.photoLabel}</div>` : ""}
      ${item.audioLabel ? `<div class="item-meta">Comentario audio: ${item.audioLabel}</div>` : ""}
      ${item.sessionId ? `<div class="item-meta">Recorrida: ${item.sessionName || item.sessionId}</div>` : ""}
      ${item.errorMessage ? `<div class="item-meta">Error: ${item.errorMessage}</div>` : ""}
    `;
    itemsList.appendChild(li);
  }
}

function formatServerDate(value) {
  if (!value) return "sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function renderServerItems() {
  if (!serverItemsList) return;

  serverItemsList.innerHTML = "";
  try {
    const response = await fetch("/api/field-items");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.supabase_error || `HTTP ${response.status}`);
    const items = data.items || [];
    if (data.supabase_error) {
      const warning = document.createElement("li");
      warning.textContent = `Supabase ERROR: ${data.supabase_error}`;
      serverItemsList.appendChild(warning);
    }

    if (!items.length) {
      const empty = document.createElement("li");
      empty.textContent = "Sin items subidos en el servidor.";
      serverItemsList.appendChild(empty);
      return;
    }

    for (const item of items) {
      const li = document.createElement("li");
      const gps = item.latitud && item.longitud
        ? `${Number(item.latitud).toFixed(5)}, ${Number(item.longitud).toFixed(5)}`
        : "sin GPS";
      const accuracy = item.precision_gps ? ` - precision ${Math.round(Number(item.precision_gps))} m` : "";
      const storageLink = item.storage_public_url || item.drive_link || "";
      const storageStatus = item.storage_status || "local_only";
      const storageProvider = item.storage_provider ? ` (${item.storage_provider})` : "";
      li.innerHTML = `
        <div class="item-main">
          <span>${item.tipo === "audio" ? "Audio" : "Foto"} - ${item.campo || "sin campo"}</span>
          <span class="pill subido">${item.estado || "subido"}</span>
        </div>
        <div class="item-meta">${item.sector || "sin sector"} - ${formatServerDate(item.fecha_hora)} - ${gps}${accuracy}</div>
        ${item.photo_label ? `<div class="item-meta">Comentario foto: ${item.photo_label}</div>` : ""}
        ${item.audio_label ? `<div class="item-meta">Comentario audio: ${item.audio_label}</div>` : ""}
        ${item.session_id ? `<div class="item-meta">Recorrida: ${item.session_nombre || item.session_id} (${item.session_id})</div>` : ""}
        <div class="item-meta">${item.nombre_archivo || ""}</div>
        <div class="item-meta">${storageStatus}${storageProvider}${storageLink ? ` - <a href="${storageLink}" target="_blank" rel="noopener">archivo</a>` : ""}</div>
        ${item.storage_error ? `<div class="item-meta">Storage error: ${item.storage_error}</div>` : ""}
      `;
      serverItemsList.appendChild(li);
    }
  } catch (error) {
    const errorItem = document.createElement("li");
    const message = error && error.message ? error.message : String(error);
    errorItem.textContent = `No pude cargar los items subidos: ${message}`;
    serverItemsList.appendChild(errorItem);
  }
}

function renderActiveSession() {
  const session = getActiveSession();
  if (!activeSessionStatus) return;
  if (!session) {
    activeSessionStatus.textContent = "Sin recorrida activa";
    return;
  }
  activeSessionStatus.textContent = `Recorrida activa: ${session.nombre || session.id}`;
}

async function renderSessions() {
  if (!sessionsList) return;
  sessionsList.innerHTML = "";
  try {
    const response = await fetch("/api/field-sessions");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.supabase_error || `HTTP ${response.status}`);
    const sessions = data.sessions || [];
    if (data.supabase_error) {
      const warning = document.createElement("li");
      warning.textContent = `Supabase ERROR: ${data.supabase_error}`;
      sessionsList.appendChild(warning);
    }
    if (!sessions.length) {
      const empty = document.createElement("li");
      empty.textContent = "Sin recorridas subidas.";
      sessionsList.appendChild(empty);
      return;
    }

    for (const session of sessions) {
      const li = document.createElement("li");
      const report = await fetchSessionReport(session.id);
      const reportState = report.estado || "sin informe";
      const reportMarkdown = report.informe_markdown || "";
      const reportButtonText = reportState === "error" ? "Reintentar informe" : "Generar informe";
      li.innerHTML = `
        <div class="item-main">
          <span>${session.nombre || "Recorrida sin nombre"}${session.legacy ? " (datos viejos)" : ""}</span>
          <span class="pill ${session.estado === "cerrada" ? "subido" : "subiendo"}">${session.estado || "abierta"}</span>
        </div>
        <div class="item-meta">${session.campo || "sin campo"} - ${session.sector || "sin sector"}</div>
        <div class="item-meta">Inicio: ${formatServerDate(session.started_at)}${session.closed_at ? ` - Cierre: ${formatServerDate(session.closed_at)}` : ""}</div>
        <div class="item-meta">Items asociados: ${session.items_count ?? 0}${session.has_items ? "" : " - sin items asociados"}</div>
        ${session.items_error ? `<div class="item-meta">Items ERROR: ${session.items_error}</div>` : ""}
        <div class="item-meta">Informe: ${reportState}${report.progress_message ? ` - ${report.progress_message}` : ""}${report.error ? ` - ${report.error}` : ""}</div>
        <div class="session-actions">
          <button class="generate-report-button" type="button" data-session-id="${session.id}" data-report-state="${reportState}">${reportButtonText}</button>
          ${report.docx_public_url ? `<a class="button-link" href="${report.docx_public_url}" target="_blank" rel="noopener">Abrir informe DOCX</a>` : ""}
        </div>
        ${reportMarkdown ? `<pre class="report-preview">${reportMarkdown.slice(0, 1200)}</pre>` : ""}
      `;
      sessionsList.appendChild(li);
      const button = li.querySelector(".generate-report-button");
      if (button) {
        button.addEventListener("click", () => generateReportForSession(session.id, button, reportState === "error"));
      }
    }
  } catch (error) {
    const errorItem = document.createElement("li");
    const message = error && error.message ? error.message : String(error);
    errorItem.textContent = `No pude cargar las recorridas: ${message}`;
    sessionsList.appendChild(errorItem);
  }
}

async function fetchSessionReport(sessionId) {
  try {
    const response = await fetch(`/api/field-sessions/${encodeURIComponent(sessionId)}/report`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.supabase_error || `HTTP ${response.status}`);
    return {
      estado: data.estado || "sin informe",
      progress_message: data.progress_message || "",
      docx_public_url: data.docx_public_url || "",
      informe_markdown: data.informe_markdown || "",
      error: data.error || "",
    };
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    return { estado: "error", progress_message: "", docx_public_url: "", informe_markdown: "", error: message };
  }
}

async function generateReportForSession(sessionId, button, force = false) {
  if (!navigator.onLine) {
    appendDebug("No se puede generar informe sin conexion.");
    return;
  }
  button.disabled = true;
  button.textContent = "Generando...";
  appendDebug(`Generando informe de recorrida ${sessionId}...`);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 30000);
  try {
    const url = `/api/field-sessions/${encodeURIComponent(sessionId)}/generate-report${force ? "?force=true" : ""}`;
    const response = await fetch(url, {
      method: "POST",
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    appendDebug("Informe listo.");
  } catch (error) {
    const message = error && error.name === "AbortError"
      ? "La generacion sigue en proceso. Consulta el informe en unos segundos."
      : (error && error.message ? error.message : String(error));
    appendDebug(`Informe ERROR: ${message}`);
  } finally {
    window.clearTimeout(timeoutId);
    button.disabled = false;
  }
  await renderSessions();
}

async function uploadLocalItem(item) {
  if (item.sessionId) {
    const session = getLocalSessions().find((entry) => entry.id === item.sessionId);
    if (session) await syncSession(session);
  }

  appendDebug(`Intentando subir item ${item.id}...`);
  item.status = "subiendo";
  item.errorMessage = "";
  await storeItem(item);
  await renderItems();

  const form = new FormData();
  form.append("item_type", item.type);
  form.append("campo", item.campo);
  form.append("sector", item.sector);
  form.append("captured_at", item.createdAt);
  form.append("latitude", item.latitude);
  form.append("longitude", item.longitude);
  form.append("gps_accuracy", item.gpsAccuracy);
  form.append("client_id", item.id);
  form.append("session_id", item.sessionId || "");
  form.append("photo_label", item.photoLabel || "");
  form.append("audio_label", item.audioLabel || "");
  form.append("file", item.blob, item.filename);

  try {
    appendDebug("POST /api/field-items enviado");
    const response = await fetch("/api/field-items", { method: "POST", body: form });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    if (!data.ok) throw new Error(data.detail || data.metadata_error || data.storage_error || "respuesta sin ok true");

    appendDebug("Servidor respondió OK");
    if (data.storage_error) appendDebug(`Storage ERROR: ${data.storage_error}`);
    if (data.metadata_error) appendDebug(`Metadata ERROR: ${data.metadata_error}`);
    item.status = "subido confirmado";
    item.serverConfirmed = true;
    item.serverId = data.id || "";
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    appendDebug(`Error al subir: ${message}`);
    item.status = "error";
    item.serverConfirmed = false;
    item.errorMessage = message;
  }

  await storeItem(item);
  await renderItems();
}

async function syncPending(options = {}) {
  if (!navigator.onLine) {
    appendDebug("Error al subir: sin conexión");
    return;
  }
  await syncLocalSessions();
  const items = await getItems();
  const shouldForce = Boolean(options.force);
  const uploadable = items.filter((entry) => {
    if (entry.status === "subiendo") return false;
    if (shouldForce) return true;
    return entry.status !== "subido confirmado";
  });

  if (!uploadable.length) {
    appendDebug("No hay items locales para subir.");
  }

  for (const item of uploadable) {
    await uploadLocalItem(item);
  }
  await renderItems();
  await renderServerItems();
  await renderSessions();
}

async function startFieldSession() {
  const campo = requireCampo();
  if (!campo) return;
  const coords = currentPosition ? currentPosition.coords : {};
  const now = new Date().toISOString();
  const nombre = (sessionNameInput ? sessionNameInput.value.trim() : "") || `Recorrida ${new Date().toLocaleString()}`;
  const session = {
    id: crypto.randomUUID(),
    nombre,
    campo,
    sector: sectorInput.value.trim(),
    estado: "abierta",
    startedAt: now,
    closedAt: "",
    latitudInicio: coords.latitude ?? "",
    longitudInicio: coords.longitude ?? "",
    precisionGpsInicio: coords.accuracy ?? "",
    notas: "",
    createdAt: now,
    syncStatus: "pendiente",
  };
  saveActiveSession(session);
  upsertLocalSession(session);
  renderActiveSession();
  appendDebug(`Recorrida iniciada: ${nombre}`);
  if (navigator.onLine) {
    await syncSession(session);
    await renderSessions();
  }
}

async function closeFieldSession() {
  const session = getActiveSession();
  if (!session) {
    appendDebug("No hay recorrida activa para cerrar.");
    return;
  }
  const closed = {
    ...session,
    estado: "cerrada",
    closedAt: new Date().toISOString(),
    syncStatus: "cerrada pendiente",
  };
  saveActiveSession(null);
  upsertLocalSession(closed);
  renderActiveSession();
  appendDebug(`Recorrida cerrada: ${closed.nombre || closed.id}`);
  if (navigator.onLine) {
    await syncSession(closed);
    await renderSessions();
  }
}

async function startRecording() {
  if (recorder && recorder.state === "recording") return;
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];
  cancelCurrentRecording = false;
  recordingStartedAt = Date.now();
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (event) => {
    if (event.data.size) audioChunks.push(event.data);
  };
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    window.clearInterval(recordingTimer);
    recordingTimer = null;
    const durationMs = Date.now() - recordingStartedAt;
    setRecordingUi(false);
    if (cancelCurrentRecording) {
      appendDebug("Grabacion cancelada.");
      return;
    }
    if (durationMs < 1000) {
      appendDebug("Audio demasiado corto, no se guardo.");
      alert("Audio demasiado corto, no se guardó.");
      return;
    }
    const blob = new Blob(audioChunks, { type: recorder.mimeType || "audio/webm" });
    if (!blob.size) {
      appendDebug("Audio vacio, no se guardo.");
      return;
    }
    const audioLabel = (window.prompt("Comentario del audio", "") || "").trim();
    await addItem("audio", blob, `audio-${Date.now()}.webm`, { audioLabel });
  };
  recorder.start();
  setRecordingUi(true);
}

function setRecordingUi(isRecording) {
  talkButton.classList.toggle("recording", isRecording);
  talkButton.textContent = isRecording ? "Grabando..." : "Mantener para hablar";
  if (recordingControls) recordingControls.hidden = !isRecording;
  if (isRecording) {
    updateRecordingDuration();
    recordingTimer = window.setInterval(updateRecordingDuration, 500);
  }
}

function updateRecordingDuration() {
  if (!recordingDuration || !recordingStartedAt) return;
  const seconds = Math.floor((Date.now() - recordingStartedAt) / 1000);
  recordingDuration.textContent = `Grabando... ${seconds} s`;
}

function stopRecording(options = {}) {
  if (recorder && recorder.state === "recording") {
    cancelCurrentRecording = Boolean(options.cancel);
    recorder.stop();
  }
}

async function toggleRecording() {
  if (recorder && recorder.state === "recording") {
    stopRecording();
    return;
  }
  try {
    await startRecording();
  } catch {
    alert("No pude acceder al microfono.");
  }
}

talkButton.addEventListener("click", async () => {
  if (suppressNextClick) {
    suppressNextClick = false;
    return;
  }
  await toggleRecording();
});

talkButton.addEventListener("pointerdown", () => {
  longPressRecording = false;
  window.clearTimeout(longPressTimer);
  longPressTimer = window.setTimeout(async () => {
    if (!(recorder && recorder.state === "recording")) {
      longPressRecording = true;
      suppressNextClick = true;
      await toggleRecording();
    }
  }, 450);
});
talkButton.addEventListener("pointerup", () => {
  window.clearTimeout(longPressTimer);
  if (longPressRecording) stopRecording();
});
talkButton.addEventListener("pointercancel", () => {
  window.clearTimeout(longPressTimer);
  if (longPressRecording) stopRecording({ cancel: true });
});
talkButton.addEventListener("pointerleave", () => {
  window.clearTimeout(longPressTimer);
  if (longPressRecording) stopRecording();
});

if (stopRecordingButton) {
  stopRecordingButton.addEventListener("click", () => stopRecording());
}
if (cancelRecordingButton) {
  cancelRecordingButton.addEventListener("click", () => stopRecording({ cancel: true }));
}

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file) return;
  const photoLabel = (window.prompt("Etiqueta o comentario de la foto", "") || "").trim();
  await addItem("foto", file, file.name || `foto-${Date.now()}.jpg`, { photoLabel });
  photoInput.value = "";
});

campoInput.addEventListener("input", persistInputs);
sectorInput.addEventListener("input", persistInputs);
if (sessionNameInput) {
  sessionNameInput.addEventListener("input", persistInputs);
}
gpsButton.addEventListener("click", refreshGps);
syncButton.addEventListener("click", syncPending);
if (startSessionButton) {
  startSessionButton.addEventListener("click", startFieldSession);
}
if (closeSessionButton) {
  closeSessionButton.addEventListener("click", closeFieldSession);
}
if (forceSyncButton) {
  forceSyncButton.addEventListener("click", () => syncPending({ force: true }));
}
if (refreshServerButton) {
  refreshServerButton.addEventListener("click", renderServerItems);
}
if (refreshSessionsButton) {
  refreshSessionsButton.addEventListener("click", renderSessions);
}
window.addEventListener("online", () => {
  setConnectionStatus();
  appendDebug("Conexion online. Toca Sincronizar para subir pendientes.");
});
window.addEventListener("offline", setConnectionStatus);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js");
}

loadInputs();
setConnectionStatus();
renderActiveSession();
refreshGps();
renderItems();
renderServerItems();
renderSessions();
