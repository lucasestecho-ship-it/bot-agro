const DB_NAME = "campo-pwa";
const STORE_NAME = "items";
const ACTIVE_SESSION_KEY = "campo.activeSession";
const SESSIONS_KEY = "campo.sessions";
const APP_TOKEN_KEY = "capataz.appToken";
const nativeFetch = window.fetch.bind(window);
let tokenPromptPromise = null;

function requestFreshAppToken() {
  if (!tokenPromptPromise) {
    tokenPromptPromise = Promise.resolve().then(() => (
      window.prompt("Clave personal de Capataz Campo", "")?.trim() || ""
    ));
  }
  return tokenPromptPromise;
}

window.fetch = async (input, init = {}) => {
  const requestUrl = typeof input === "string" ? input : input.url;
  const isPrivateApi = requestUrl.startsWith("/api/") && requestUrl !== "/api/health/campo";
  const options = { ...init };
  if (isPrivateApi) {
    const headers = new Headers(init.headers || {});
    const token = localStorage.getItem(APP_TOKEN_KEY) || "";
    if (token) headers.set("X-Field-App-Token", token);
    options.headers = headers;
  }
  let response = await nativeFetch(input, options);
  if (isPrivateApi && response.status === 401 && !options._tokenRetried) {
    const attemptedToken = new Headers(options.headers || {}).get("X-Field-App-Token") || "";
    const storedToken = localStorage.getItem(APP_TOKEN_KEY) || "";
    const token = storedToken && storedToken !== attemptedToken
      ? storedToken
      : await requestFreshAppToken();
    if (!token) return response;
    localStorage.setItem(APP_TOKEN_KEY, token);
    const headers = new Headers(options.headers || {});
    headers.set("X-Field-App-Token", token);
    response = await nativeFetch(input, { ...options, headers, _tokenRetried: true });
    if (response.status === 401) localStorage.removeItem(APP_TOKEN_KEY);
    window.setTimeout(() => { tokenPromptPromise = null; }, 250);
  }
  return response;
};
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
const noteInput = document.getElementById("noteInput");
const analyzeTextButton = document.getElementById("analyzeTextButton");
const sharedTextNotice = document.getElementById("sharedTextNotice");
const refreshDashboardButton = document.getElementById("refreshDashboardButton");
const agentWorkSummary = document.getElementById("agentWorkSummary");
const agentWorkList = document.getElementById("agentWorkList");
const emailDraftsBox = document.getElementById("emailDraftsBox");
const emailDraftsList = document.getElementById("emailDraftsList");
const todaySummary = document.getElementById("todaySummary");
const todayTasksList = document.getElementById("todayTasksList");
const clientsDatalist = document.getElementById("clientsDatalist");
const waterProjectsBox = document.getElementById("waterProjectsBox");
const waterProjectsList = document.getElementById("waterProjectsList");
const decisionsBox = document.getElementById("decisionsBox");
const decisionsList = document.getElementById("decisionsList");
const uncoveredClientsBox = document.getElementById("uncoveredClientsBox");
const uncoveredClientsSummary = document.getElementById("uncoveredClientsSummary");
const uncoveredClientsList = document.getElementById("uncoveredClientsList");
const notificationsButton = document.getElementById("notificationsButton");
const installButton = document.getElementById("installButton");
const draftDialog = document.getElementById("draftDialog");
const draftForm = document.getElementById("draftForm");
const draftClientInput = document.getElementById("draftClientInput");
const draftSummaryInput = document.getElementById("draftSummaryInput");
const draftAgents = document.getElementById("draftAgents");
const draftTasks = document.getElementById("draftTasks");
const addDraftTaskButton = document.getElementById("addDraftTaskButton");
const cancelDraftButton = document.getElementById("cancelDraftButton");

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
let recordingSession = null;
let currentDraft = null;
let currentDraftSourceText = "";
let draftsDeferredForSession = false;
let installPromptEvent = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}

function safeExternalUrl(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const parsed = new URL(value.trim(), window.location.origin);
    if (!["http:", "https:"].includes(parsed.protocol)) return "";
    return escapeHtml(parsed.href);
  } catch {
    return "";
  }
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from([...raw].map((character) => character.charCodeAt(0)));
}

async function enablePushNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    throw new Error("Este navegador no admite avisos en segundo plano");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Permiso de notificaciones bloqueado");

  const keyResponse = await fetch("/api/capataz/push/public-key");
  const keyData = await keyResponse.json();
  if (!keyResponse.ok || !keyData.ok) {
    throw new Error(keyData.detail || "Los avisos todavía no están configurados en el servidor");
  }
  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(keyData.public_key),
    });
  }
  const response = await fetch("/api/capataz/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subscription: subscription.toJSON() }),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  localStorage.setItem("capataz.pushEnabled", "true");
}

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

async function syncSession(session, options = {}) {
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
    if (data.supabase_error) throw new Error(`Supabase no guardó la recorrida: ${data.supabase_error}`);

    let updated = { ...session, syncStatus: "sincronizada", errorMessage: "" };
    if (updated.estado === "cerrada" && options.deferClose) {
      updated.syncStatus = "cierre preparado";
    } else if (updated.estado === "cerrada" && updated.closedAt) {
      const closeResponse = await fetch(`/api/field-sessions/${encodeURIComponent(updated.id)}/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ closed_at: updated.closedAt }),
      });
      if (!closeResponse.ok) throw new Error(`HTTP ${closeResponse.status}`);
      const closeData = await closeResponse.json();
      if (closeData.report_queued) {
        appendDebug("Informe automático en cola.");
        window.setTimeout(renderSessions, 7000);
        window.setTimeout(loadDashboard, 7000);
        window.setTimeout(renderSessions, 25000);
        window.setTimeout(loadDashboard, 25000);
      }
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

async function syncLocalSessions(options = {}) {
  if (!navigator.onLine) return;
  const phase = options.phase || "all";
  const readySessionIds = options.readySessionIds || null;
  const sessions = getLocalSessions().filter((session) => {
    if (phase === "open") {
      return session.estado !== "cerrada" && session.syncStatus !== "sincronizada";
    }
    if (phase === "prepare_closed") {
      return session.estado === "cerrada" && session.syncStatus !== "cerrada sincronizada";
    }
    if (phase === "finalize_closed") {
      return session.estado === "cerrada"
        && session.syncStatus !== "cerrada sincronizada"
        && (!readySessionIds || readySessionIds.has(session.id));
    }
    if (session.estado === "cerrada") return session.syncStatus !== "cerrada sincronizada";
    return session.syncStatus !== "sincronizada";
  });
  for (const session of sessions) {
    await syncSession(session, { deferClose: phase === "prepare_closed" });
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

function requireActiveSession() {
  const session = getActiveSession();
  if (!session || session.estado !== "abierta") {
    alert("Primero iniciá una recorrida. Así el audio o la foto quedan asignados correctamente.");
    startSessionButton?.focus();
    return null;
  }
  return session;
}

function buildItem(type, blob, filename, options = {}) {
  const campo = requireCampo();
  if (!campo) return null;

  const activeSession = options.session || requireActiveSession();
  if (!activeSession) return null;

  const coords = currentPosition ? currentPosition.coords : {};
  const now = new Date();
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
    sessionId: activeSession.id,
    sessionName: activeSession.nombre,
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
  if (navigator.onLine) await uploadLocalItem(item);
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
        <span>${item.type === "audio" ? "Audio" : "Foto"} - ${escapeHtml(item.campo)}</span>
        <span class="pill ${escapeHtml(statusClass)}">${escapeHtml(item.status)}</span>
      </div>
      <div class="item-meta">${escapeHtml(item.sector || "sin sector")} - ${escapeHtml(new Date(item.createdAt).toLocaleString())} - ${escapeHtml(gps)}</div>
      ${item.photoLabel ? `<div class="item-meta">Comentario foto: ${escapeHtml(item.photoLabel)}</div>` : ""}
      ${item.audioLabel ? `<div class="item-meta">Comentario audio: ${escapeHtml(item.audioLabel)}</div>` : ""}
      ${item.sessionId ? `<div class="item-meta">Asignado a: ${escapeHtml(item.sessionName || item.sessionId)}${item.assignedSessionId ? " · verificado" : " · pendiente de verificar"}</div>` : ""}
      ${item.errorMessage ? `<div class="item-meta">Error: ${escapeHtml(item.errorMessage)}</div>` : ""}
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

function addSessionAssignmentControls(container, item, sessions) {
  if (!container || item.session_id || !sessions.length) return;
  const controls = document.createElement("div");
  controls.className = "assign-session-controls";
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Recorrida para asignar");
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = `${session.nombre || "Recorrida"} · ${session.campo || "sin campo"}`;
    select.appendChild(option);
  }
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Asignar a recorrida";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch(`/api/field-items/${encodeURIComponent(item.id)}/assign-session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: select.value }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      appendDebug(`Item ${item.id} asignado a ${data.session_name}.`);
      await renderServerItems();
      await renderSessions();
    } catch (error) {
      button.disabled = false;
      alert(`No pude asignar el archivo: ${error.message || error}`);
    }
  });
  controls.append(select, button);
  container.appendChild(controls);
}

async function renderServerItems() {
  if (!serverItemsList) return;

  serverItemsList.innerHTML = "";
  try {
    const response = await fetch("/api/field-items");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.supabase_error || `HTTP ${response.status}`);
    const items = data.items || [];
    let assignableSessions = [];
    try {
      const sessionsResponse = await fetch("/api/field-sessions");
      const sessionsData = await sessionsResponse.json();
      if (sessionsResponse.ok && sessionsData.ok) {
        assignableSessions = (sessionsData.sessions || []).filter((session) => session.id && !session.legacy);
      }
    } catch {
      assignableSessions = [];
    }
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
      const safeStorageLink = safeExternalUrl(storageLink);
      const storageStatus = item.storage_status || "local_only";
      const storageProvider = item.storage_provider ? ` (${item.storage_provider})` : "";
      li.innerHTML = `
        <div class="item-main">
          <span>${item.tipo === "audio" ? "Audio" : "Foto"} - ${escapeHtml(item.campo || "sin campo")}</span>
          <span class="pill subido">${escapeHtml(item.estado || "subido")}</span>
        </div>
        <div class="item-meta">${escapeHtml(item.sector || "sin sector")} - ${escapeHtml(formatServerDate(item.fecha_hora))} - ${escapeHtml(gps + accuracy)}</div>
        ${item.photo_label ? `<div class="item-meta">Comentario foto: ${escapeHtml(item.photo_label)}</div>` : ""}
        ${item.audio_label ? `<div class="item-meta">Comentario audio: ${escapeHtml(item.audio_label)}</div>` : ""}
        ${item.session_id ? `<div class="item-meta">Asignado a: ${escapeHtml(item.session_nombre || item.session_id)} · verificado en Supabase</div>` : `<div class="item-meta">SIN RECORRIDA ASIGNADA</div>`}
        <div class="item-meta">${escapeHtml(item.nombre_archivo || "")}</div>
        <div class="item-meta">${escapeHtml(storageStatus + storageProvider)}${safeStorageLink ? ` - <a href="${safeStorageLink}" target="_blank" rel="noopener">archivo</a>` : ""}</div>
        ${item.storage_error ? `<div class="item-meta">Storage error: ${escapeHtml(item.storage_error)}</div>` : ""}
      `;
      addSessionAssignmentControls(li, item, assignableSessions);
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
  const hasActiveSession = Boolean(session && session.estado === "abierta");
  campoInput.disabled = hasActiveSession;
  if (sessionNameInput) sessionNameInput.disabled = hasActiveSession;
  talkButton.disabled = !hasActiveSession;
  photoInput.disabled = !hasActiveSession;
  photoInput.closest(".photo-button")?.classList.toggle("disabled", !hasActiveSession);
  if (!session) {
    activeSessionStatus.textContent = "Sin recorrida activa · audio y foto bloqueados";
    return;
  }
  activeSessionStatus.textContent = `Recorrida activa: ${session.nombre || session.id} · archivos vinculados a ${session.id.slice(0, 8)}`;
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
          <span>${escapeHtml(session.nombre || "Recorrida sin nombre")}${session.legacy ? " (datos viejos)" : ""}</span>
          <span class="pill ${session.estado === "cerrada" ? "subido" : "subiendo"}">${escapeHtml(session.estado || "abierta")}</span>
        </div>
        <div class="item-meta">${escapeHtml(session.campo || "sin campo")} - ${escapeHtml(session.sector || "sin sector")}</div>
        <div class="item-meta">Inicio: ${escapeHtml(formatServerDate(session.started_at))}${session.closed_at ? ` - Cierre: ${escapeHtml(formatServerDate(session.closed_at))}` : ""}</div>
        <div class="item-meta">Items asociados: ${Number(session.items_count || 0)}${session.has_items ? "" : " - sin items asociados"}</div>
        ${session.items_error ? `<div class="item-meta">Items ERROR: ${escapeHtml(session.items_error)}</div>` : ""}
        <div class="item-meta">Informe: ${escapeHtml(reportState)}${report.progress_message ? ` - ${escapeHtml(report.progress_message)}` : ""}${report.error ? ` - ${escapeHtml(report.error)}` : ""}</div>
        <div class="session-actions">
          <button class="generate-report-button" type="button" data-session-id="${escapeHtml(session.id)}" data-report-state="${escapeHtml(reportState)}">${escapeHtml(reportButtonText)}</button>
          ${safeExternalUrl(report.pdf_public_url) ? `<a class="button-link" href="${safeExternalUrl(report.pdf_public_url)}" target="_blank" rel="noopener">Abrir informe PDF</a>` : ""}
          ${safeExternalUrl(report.docx_public_url) ? `<a class="button-link" href="${safeExternalUrl(report.docx_public_url)}" target="_blank" rel="noopener">Abrir informe DOCX</a>` : ""}
        </div>
        ${reportMarkdown ? `<pre class="report-preview">${escapeHtml(reportMarkdown.slice(0, 1200))}</pre>` : ""}
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
      pdf_public_url: data.pdf_public_url || "",
      informe_markdown: data.informe_markdown || "",
      error: data.error || "",
    };
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    return { estado: "error", progress_message: "", docx_public_url: "", pdf_public_url: "", informe_markdown: "", error: message };
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
  try {
    const url = `/api/field-sessions/${encodeURIComponent(sessionId)}/generate-report${force ? "?force=true" : ""}`;
    const response = await fetch(url, { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    appendDebug("Informe en proceso.");
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 5000));
      const report = await fetchSessionReport(sessionId);
      button.textContent = report.progress_message || "Generando...";
      if (report.estado === "done") {
        appendDebug("Informe PDF y DOCX listos.");
        await renderSessions();
        return;
      }
      if (report.estado === "error") throw new Error(report.error || "Error al generar informe");
    }
    appendDebug("El informe sigue generándose. Podés cerrar la app y volver más tarde.");
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    appendDebug(`Informe ERROR: ${message}`);
  } finally {
    button.disabled = false;
  }
  await renderSessions();
}

async function uploadLocalItem(item) {
  if (item.sessionId) {
    const session = getLocalSessions().find((entry) => entry.id === item.sessionId);
    if (session) {
      const sessionSynced = await syncSession(session);
      if (!sessionSynced) {
        item.status = "error";
        item.serverConfirmed = false;
        item.errorMessage = "La recorrida no se guardó en Supabase; el archivo no se subió para evitar que quede huérfano.";
        await storeItem(item);
        await renderItems();
        return;
      }
    }
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
  // client_id conserva el UUID local para que una resubida sea idempotente.
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
    if (!data.assigned_session_id || data.assigned_session_id !== item.sessionId) {
      throw new Error("El servidor no confirmó la recorrida del archivo");
    }

    appendDebug("Servidor respondió OK");
    if (data.storage_error) appendDebug(`Storage ERROR: ${data.storage_error}`);
    if (data.metadata_error) appendDebug(`Metadata ERROR: ${data.metadata_error}`);
    item.status = "subido confirmado";
    item.serverConfirmed = true;
    item.serverId = data.id || "";
    item.assignedSessionId = data.assigned_session_id;
    if (data.capataz_draft) {
      queueDraft(data.capataz_draft, data.transcript_text || item.audioLabel || item.photoLabel || "");
    }
    if (data.capataz_error) appendDebug(`Capataz: ${data.capataz_error}`);
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
  await syncLocalSessions({ phase: "open" });
  // Una recorrida cerrada offline debe existir en el servidor antes de subir sus archivos,
  // pero se finaliza recien despues de que todos sus items quedaron confirmados.
  await syncLocalSessions({ phase: "prepare_closed" });
  const items = await getItems();
  const shouldForce = Boolean(options.force);
  const uploadable = items.filter((entry) => {
    if (entry.status === "subiendo") return false;
    if (shouldForce) return entry.status !== "subido confirmado";
    return entry.status !== "subido confirmado";
  });

  if (!uploadable.length) {
    appendDebug("No hay items locales para subir.");
  }

  for (const item of uploadable) {
    await uploadLocalItem(item);
  }
  const refreshedItems = await getItems();
  const readyClosedSessionIds = new Set(
    getLocalSessions()
      .filter((session) => session.estado === "cerrada")
      .filter((session) => !refreshedItems.some(
        (item) => item.sessionId === session.id && item.status !== "subido confirmado"
      ))
      .map((session) => session.id)
  );
  await syncLocalSessions({ phase: "finalize_closed", readySessionIds: readyClosedSessionIds });
  await renderItems();
  await renderServerItems();
  await renderSessions();
}

async function startFieldSession() {
  const existing = getActiveSession();
  if (existing && existing.estado === "abierta") {
    alert(`Ya está activa la recorrida “${existing.nombre || existing.campo}”. Cerrala antes de iniciar otra.`);
    return;
  }
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
    await syncPending();
  }
}

async function startRecording() {
  if (recorder && recorder.state === "recording") return;
  recordingSession = requireActiveSession();
  if (!recordingSession) return;
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
      recordingSession = null;
      appendDebug("Grabacion cancelada.");
      return;
    }
    if (durationMs < 1000) {
      appendDebug("Audio demasiado corto, no se guardo.");
      alert("Audio demasiado corto, no se guardó.");
      recordingSession = null;
      return;
    }
    const blob = new Blob(audioChunks, { type: recorder.mimeType || "audio/webm" });
    if (!blob.size) {
      appendDebug("Audio vacio, no se guardo.");
      recordingSession = null;
      return;
    }
    const session = recordingSession;
    recordingSession = null;
    await addItem("audio", blob, `audio-${Date.now()}.webm`, { session });
  };
  recorder.start();
  setRecordingUi(true);
}

function setRecordingUi(isRecording) {
  talkButton.classList.toggle("recording", isRecording);
  talkButton.textContent = isRecording ? "Grabando..." : "Tocar para grabar";
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
    recordingSession = null;
    alert("No pude acceder al microfono.");
  }
}

function getDraftQueue() {
  return readJsonStorage("capataz.draftQueue", []);
}

function saveDraftQueue(queue) {
  localStorage.setItem("capataz.draftQueue", JSON.stringify(queue));
}

function queueDraft(draft, sourceText = "") {
  if (!draft) return;
  const queue = getDraftQueue();
  if (queue.some((entry) => entry?.draft?.draft_id === draft.draft_id)) return;
  queue.push({ draft, sourceText });
  saveDraftQueue(queue);
  draftsDeferredForSession = false;
  openNextDraft();
}

function finishCurrentDraft() {
  const queue = getDraftQueue();
  queue.shift();
  saveDraftQueue(queue);
  currentDraft = null;
  currentDraftSourceText = "";
  if (draftDialog?.open) draftDialog.close();
  window.setTimeout(openNextDraft, 100);
}

function deferCurrentDraft() {
  currentDraft = null;
  currentDraftSourceText = "";
  draftsDeferredForSession = true;
  if (draftDialog?.open) draftDialog.close();
  appendDebug("Borrador conservado para revisar más tarde.");
}

function renderDraftAgents() {
  if (!draftAgents || !currentDraft) return;
  draftAgents.innerHTML = "";
  for (const agent of currentDraft.agents || []) {
    const badge = document.createElement("span");
    badge.className = "agent-badge";
    if (agent === "Margen") badge.classList.add("economic");
    if (agent === "Agua") badge.classList.add("water");
    badge.textContent = agent;
    draftAgents.appendChild(badge);
  }
}

function renderDraftTasks() {
  if (!draftTasks || !currentDraft) return;
  draftTasks.innerHTML = "";
  const tasks = currentDraft.tasks || [];
  if (!tasks.length) {
    const empty = document.createElement("p");
    empty.className = "section-copy";
    empty.textContent = "No detecté un compromiso. Podés guardar solamente la nota o agregar una tarea.";
    draftTasks.appendChild(empty);
    return;
  }
  tasks.forEach((task, index) => {
    const card = document.createElement("div");
    card.className = "draft-task";
    card.dataset.index = String(index);

    const titleLabel = document.createElement("label");
    titleLabel.textContent = "Tarea";
    const titleInput = document.createElement("input");
    titleInput.className = "draft-task-title";
    titleInput.value = task.title || "";
    titleLabel.appendChild(titleInput);

    const grid = document.createElement("div");
    grid.className = "draft-task-grid";
    const dueLabel = document.createElement("label");
    dueLabel.textContent = "Fecha";
    const dueInput = document.createElement("input");
    dueInput.type = "date";
    dueInput.className = "draft-task-due";
    dueInput.value = task.due_date || "";
    dueLabel.appendChild(dueInput);

    grid.append(dueLabel);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "remove-draft-task";
    removeButton.textContent = "Quitar tarea";
    removeButton.addEventListener("click", () => {
      collectDraftFromForm();
      currentDraft.tasks.splice(index, 1);
      renderDraftTasks();
    });
    card.append(titleLabel, grid, removeButton);
    draftTasks.appendChild(card);
  });
}

function collectDraftFromForm() {
  if (!currentDraft) return null;
  currentDraft.client_name = draftClientInput?.value.trim() || "";
  currentDraft.summary = draftSummaryInput?.value.trim() || "";
  const collected = [];
  for (const card of draftTasks?.querySelectorAll(".draft-task") || []) {
    const original = currentDraft.tasks?.[Number(card.dataset.index)] || {};
    const title = card.querySelector(".draft-task-title")?.value.trim() || "";
    if (!title) continue;
    collected.push({
      ...original,
      title,
      due_date: card.querySelector(".draft-task-due")?.value || null,
      agent: original.agent || "Cartera",
      priority: original.priority || "media",
    });
  }
  currentDraft.tasks = collected;
  return currentDraft;
}

function openNextDraft() {
  if (!draftDialog || draftDialog.open || currentDraft || draftsDeferredForSession) return;
  const entry = getDraftQueue()[0];
  if (!entry) return;
  currentDraft = entry.draft;
  currentDraftSourceText = entry.sourceText || "";
  draftClientInput.value = currentDraft.client_name || "";
  draftSummaryInput.value = currentDraft.summary || "";
  renderDraftAgents();
  renderDraftTasks();
  if (typeof draftDialog.showModal === "function") draftDialog.showModal();
  else draftDialog.setAttribute("open", "");
}

async function analyzeTextIntake() {
  const text = noteInput?.value.trim() || "";
  if (!text) {
    noteInput?.focus();
    return;
  }
  analyzeTextButton.disabled = true;
  analyzeTextButton.textContent = "Analizando...";
  try {
    const response = await fetch("/api/capataz/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, field_name: campoInput.value.trim(), source: "texto_app" }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    queueDraft(data.draft, text);
  } catch (error) {
    alert(`No pude analizar la nota: ${error.message || error}`);
  } finally {
    analyzeTextButton.disabled = false;
    analyzeTextButton.textContent = "Asignar a los agentes";
  }
}

async function confirmCurrentDraft() {
  const draft = collectDraftFromForm();
  if (!draft) return;
  const confirmButton = document.getElementById("confirmDraftButton");
  confirmButton.disabled = true;
  confirmButton.textContent = "Guardando...";
  try {
    const response = await fetch("/api/capataz/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft, source_text: currentDraftSourceText }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    if (noteInput && noteInput.value.trim() === currentDraftSourceText.trim()) noteInput.value = "";
    appendDebug(`Capataz guardó ${data.tasks?.length || 0} tarea(s).`);
    if (data.crew_queued) {
      appendDebug("La cuadrilla está analizando la entrada.");
      window.setTimeout(loadDashboard, 7000);
      window.setTimeout(loadDashboard, 20000);
      window.setTimeout(loadDashboard, 45000);
    }
    finishCurrentDraft();
    await loadDashboard();
  } catch (error) {
    alert(`No pude guardar: ${error.message || error}`);
  } finally {
    confirmButton.disabled = false;
    confirmButton.textContent = "Confirmar y guardar";
  }
}

function taskDateLabel(task, bucket) {
  if (!task.due_date) return "sin fecha";
  if (bucket === "overdue") return `atrasada desde ${task.due_date}`;
  if (bucket === "today") return "para hoy";
  return `para ${task.due_date}`;
}

function createTaskListItem(task, bucket) {
  const li = document.createElement("li");
  li.classList.add(bucket);
  const main = document.createElement("div");
  main.className = "item-main";
  const title = document.createElement("span");
  title.textContent = task.title || "Tarea sin título";
  main.append(title);

  const meta = document.createElement("div");
  meta.className = "item-meta";
  meta.textContent = `${task.client_name || "sin cliente"} · ${taskDateLabel(task, bucket)}`;

  const actions = document.createElement("div");
  actions.className = "task-actions";
  const done = document.createElement("button");
  done.type = "button";
  done.textContent = "Hecho";
  done.addEventListener("click", async () => {
    done.disabled = true;
    try {
      const response = await fetch(`/api/capataz/tasks/${encodeURIComponent(task.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "done" }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadDashboard();
    } catch (error) {
      done.disabled = false;
      alert(`No pude cerrar la tarea: ${error.message || error}`);
    }
  });
  actions.appendChild(done);
  li.append(main, meta, actions);
  return li;
}

function createDecisionListItem(decision) {
  const li = document.createElement("li");
  li.className = "decision-card";

  const title = document.createElement("strong");
  title.textContent = decision.client_name || decision.topic || "Decisión pendiente";
  const summary = document.createElement("div");
  summary.textContent = decision.summary || "Análisis listo para revisar";

  const recommendation = document.createElement("div");
  recommendation.className = "item-meta";
  recommendation.textContent = `Recomendación: ${decision.recommendation || "revisar antes de ejecutar"}`;
  const economic = document.createElement("div");
  economic.className = "item-meta";
  economic.textContent = `Económico: ${decision.economic_summary || "faltan datos para cuantificar"}`;

  const missing = decision.missing_data || [];
  const missingData = document.createElement("div");
  missingData.className = "item-meta";
  missingData.textContent = missing.length ? `Falta: ${missing.join(" · ")}` : "Sin datos faltantes marcados";

  const actions = document.createElement("div");
  actions.className = "decision-actions";
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "Aprobar y crear tareas";
  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "reject-decision";
  reject.textContent = "Descartar";

  const updateDecision = async (action) => {
    approve.disabled = true;
    reject.disabled = true;
    try {
      const response = await fetch(`/api/capataz/decisions/${encodeURIComponent(decision.id)}/${action}`, {
        method: "POST",
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      await loadDashboard();
    } catch (error) {
      approve.disabled = false;
      reject.disabled = false;
      alert(`No pude actualizar la decisión: ${error.message || error}`);
    }
  };
  approve.addEventListener("click", () => updateDecision("approve"));
  reject.addEventListener("click", () => updateDecision("reject"));
  actions.append(approve, reject);
  li.append(title, summary, recommendation, economic, missingData, actions);
  return li;
}

function createUncoveredClientItem(client) {
  const li = document.createElement("li");
  const title = document.createElement("strong");
  title.textContent = client.name || "Cliente sin nombre";
  const controls = document.createElement("div");
  controls.className = "client-frequency-controls";
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Frecuencia para ${client.name || "cliente"}`);
  for (const [days, label] of [["", "Elegir frecuencia"], ["7", "Semanal"], ["15", "Cada 15 días"], ["30", "Mensual"], ["60", "Cada 2 meses"], ["90", "Cada 3 meses"]]) {
    const option = document.createElement("option");
    option.value = days;
    option.textContent = label;
    option.selected = String(client.followup_days || "") === days;
    select.appendChild(option);
  }
  const email = document.createElement("input");
  email.type = "email";
  email.placeholder = "Correo del cliente";
  email.value = client.email || "";
  email.setAttribute("aria-label", `Correo para ${client.name || "cliente"}`);
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "Guardar";
  save.addEventListener("click", async () => {
    if (!select.value) return;
    save.disabled = true;
    try {
      const response = await fetch(`/api/capataz/clients/${encodeURIComponent(client.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          followup_days: Number(select.value),
          email: email.value.trim() || null,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      await loadDashboard();
    } catch (error) {
      save.disabled = false;
      alert(`No pude guardar la frecuencia: ${error.message || error}`);
    }
  });
  controls.append(select, email, save);
  li.append(title, controls);
  return li;
}

async function showDueNotification(dashboard) {
  if (localStorage.getItem("capataz.pushEnabled") === "true") return;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const due = [...(dashboard.tasks?.overdue || []), ...(dashboard.tasks?.today || [])];
  if (!due.length) return;
  const hash = `${dashboard.date}:${due.map((task) => task.id).sort().join(",")}`;
  if (localStorage.getItem("capataz.lastNotification") === hash) return;
  const registration = await navigator.serviceWorker?.ready;
  if (!registration) return;
  await registration.showNotification("Capataz Campo", {
    body: `${due.length} tarea(s) para revisar hoy`,
    icon: "/static/logo.png",
    badge: "/static/logo.png",
    tag: "capataz-daily",
    data: { url: "/campo" },
  });
  localStorage.setItem("capataz.lastNotification", hash);
}

function normalizeAgentOutput(run) {
  const output = run?.output;
  if (output && typeof output === "object") return output;
  if (typeof output === "string") {
    try {
      const parsed = JSON.parse(output);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
  return {};
}

function formatWorkTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
}

async function prepareEmailForEvent(eventId, button) {
  button.disabled = true;
  button.textContent = "Preparando...";
  try {
    const response = await fetch(`/api/capataz/events/${encodeURIComponent(eventId)}/email-draft`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    button.textContent = "Preparar correo";
    alert(`No pude preparar el correo: ${error.message || error}`);
  }
}

function createAgentWorkCard(group, emailByEvent) {
  const card = document.createElement("article");
  card.className = "work-card";
  const runs = group.runs;
  const statuses = runs.map((run) => String(run.status || "").toLowerCase());
  const processing = statuses.some((status) => ["queued", "running"].includes(status));
  const failed = statuses.some((status) => ["error", "failed"].includes(status));
  if (processing) card.classList.add("processing");
  if (failed) card.classList.add("failed");

  const heading = document.createElement("div");
  heading.className = "work-card-title";
  const title = document.createElement("strong");
  title.textContent = group.inputSummary || "Trabajo recibido";
  const state = document.createElement("span");
  state.className = `work-state${processing ? " processing" : failed ? " failed" : ""}`;
  state.textContent = processing ? "trabajando" : failed ? "con error" : "terminado";
  heading.append(title, state);

  const agents = document.createElement("div");
  agents.className = "work-card-agents";
  for (const run of runs) {
    const badge = document.createElement("span");
    badge.className = "agent-badge";
    badge.textContent = run.agent || "Agente";
    agents.appendChild(badge);
  }

  const preferredRun = runs.find((run) => run.agent === "Contralor")
    || [...runs].reverse().find((run) => normalizeAgentOutput(run).summary)
    || runs[0];
  const output = normalizeAgentOutput(preferredRun);
  const summary = document.createElement("div");
  summary.className = "work-card-summary";
  summary.textContent = output.summary
    || (processing ? "Los agentes están procesando la entrada." : "Trabajo terminado; abrí la decisión si requiere aprobación.");

  const meta = document.createElement("div");
  meta.className = "work-card-meta item-meta";
  const finished = runs.map((run) => run.finished_at || run.created_at).filter(Boolean).sort().at(-1);
  meta.textContent = formatWorkTime(finished);

  const actions = document.createElement("div");
  actions.className = "work-card-actions";
  if (!processing && !emailByEvent.has(group.eventId)) {
    const emailButton = document.createElement("button");
    emailButton.type = "button";
    emailButton.textContent = "Preparar correo";
    emailButton.addEventListener("click", () => prepareEmailForEvent(group.eventId, emailButton));
    actions.appendChild(emailButton);
  }
  card.append(heading, agents, summary, meta);
  if (actions.childElementCount) card.appendChild(actions);
  return card;
}

function createReportWorkCard(report) {
  const card = document.createElement("article");
  const status = String(report.estado || "").toLowerCase();
  const processing = status === "generando";
  const hasDeliverable = Boolean(safeExternalUrl(report.pdf_public_url) || safeExternalUrl(report.docx_public_url));
  const missingFile = status === "done" && !hasDeliverable;
  const failed = status === "error" || missingFile;
  card.className = `work-card${processing ? " processing" : failed ? " failed" : ""}`;
  const heading = document.createElement("div");
  heading.className = "work-card-title";
  const title = document.createElement("strong");
  title.textContent = report.titulo || "Informe de recorrida";
  const state = document.createElement("span");
  state.className = `work-state${processing ? " processing" : failed ? " failed" : ""}`;
  state.textContent = processing ? "generando" : missingFile ? "sin archivo" : failed ? "con error" : "terminado";
  heading.append(title, state);
  const agents = document.createElement("div");
  agents.className = "work-card-agents";
  const badge = document.createElement("span");
  badge.className = "agent-badge";
  badge.textContent = "Informes";
  agents.appendChild(badge);
  const summary = document.createElement("div");
  summary.className = "work-card-summary";
  summary.textContent = missingFile
    ? "El registro dice terminado, pero no existe un PDF o DOCX descargable. No se cuenta como trabajo entregado."
    : report.resumen || report.progress_message || report.error || "Informe listo";
  const actions = document.createElement("div");
  actions.className = "work-card-actions email-card-actions";
  for (const [url, label] of [[report.pdf_public_url, "Abrir PDF"], [report.docx_public_url, "Abrir DOCX"]]) {
    const safeUrl = safeExternalUrl(url);
    if (!safeUrl || status !== "done") continue;
    const link = document.createElement("a");
    link.className = "button-link";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    actions.appendChild(link);
  }
  card.append(heading, agents, summary);
  if (actions.childElementCount) card.appendChild(actions);
  return card;
}

function renderAgentWork(runs, emailDrafts, reports = []) {
  if (!agentWorkList || !agentWorkSummary) return;
  agentWorkList.innerHTML = "";
  const emailByEvent = new Map(emailDrafts.filter((item) => item.event_id).map((item) => [item.event_id, item]));
  const groups = new Map();
  for (const run of runs) {
    const eventId = run.event_id || run.id || `sin-evento-${groups.size}`;
    if (!groups.has(eventId)) groups.set(eventId, { eventId, inputSummary: run.input_summary || "", runs: [] });
    const group = groups.get(eventId);
    group.runs.push(run);
    if (!group.inputSummary && run.input_summary) group.inputSummary = run.input_summary;
  }
  const workGroups = [...groups.values()].slice(0, 10);
  const completed = workGroups.filter((group) => group.runs.every((run) => ["completed", "fallback"].includes(String(run.status || "").toLowerCase()))).length;
  const processing = workGroups.filter((group) => group.runs.some((run) => ["queued", "running"].includes(String(run.status || "").toLowerCase()))).length;
  const finishedReports = reports.filter((report) => (
    report.estado === "done" && (safeExternalUrl(report.pdf_public_url) || safeExternalUrl(report.docx_public_url))
  )).length;
  const processingReports = reports.filter((report) => report.estado === "generando").length;
  agentWorkSummary.textContent = `${completed + finishedReports} trabajo(s) terminado(s) · ${processing + processingReports} en proceso`;
  for (const report of reports.slice(0, 5)) agentWorkList.appendChild(createReportWorkCard(report));
  if (!workGroups.length && !reports.length) {
    const empty = document.createElement("p");
    empty.className = "empty-work";
    empty.textContent = "Todavía no hay trabajos. Mandales una nota acá o compartí texto, audio, foto o PDF a tu bot de Telegram.";
    agentWorkList.appendChild(empty);
    return;
  }
  for (const group of workGroups) agentWorkList.appendChild(createAgentWorkCard(group, emailByEvent));
}

function renderEmailDrafts(emailDrafts) {
  if (!emailDraftsBox || !emailDraftsList) return;
  emailDraftsList.innerHTML = "";
  emailDraftsBox.hidden = !emailDrafts.length;
  for (const draft of emailDrafts.slice(0, 10)) {
    const card = document.createElement("article");
    card.className = "email-card";
    const title = document.createElement("strong");
    title.textContent = draft.subject || "Correo preparado";
    const meta = document.createElement("div");
    meta.className = "item-meta";
    const destination = draft.to_email || "destinatario pendiente";
    const state = draft.status === "gmail_created" ? "borrador creado en Gmail" : "preparado; falta sincronizar con Gmail";
    meta.textContent = `${draft.client_name || "sin cliente"} · ${destination} · ${state}`;
    const actions = document.createElement("div");
    actions.className = "email-card-actions";
    if (draft.status === "gmail_created") {
      const open = document.createElement("a");
      open.className = "button-link";
      open.href = "https://mail.google.com/mail/u/0/#drafts";
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      open.textContent = "Abrir borradores de Gmail";
      actions.appendChild(open);
    } else {
      const sync = document.createElement("button");
      sync.type = "button";
      sync.textContent = "Crear en Gmail";
      sync.addEventListener("click", async () => {
        sync.disabled = true;
        sync.textContent = "Sincronizando...";
        try {
          const response = await fetch("/api/capataz/email-drafts/sync", { method: "POST" });
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
          if (!data.configured) throw new Error("Gmail todavía no está conectado en Render");
          await loadDashboard();
        } catch (error) {
          sync.disabled = false;
          sync.textContent = "Crear en Gmail";
          alert(`No pude crear el borrador en Gmail: ${error.message || error}`);
        }
      });
      actions.appendChild(sync);
    }
    card.append(title, meta);
    if (actions.childElementCount) card.appendChild(actions);
    emailDraftsList.appendChild(card);
  }
}

async function loadDashboard() {
  if (!todayTasksList) return;
  try {
    const response = await fetch("/api/capataz/dashboard");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    const agentRuns = data.agent_activity || [];
    const emailDrafts = data.email_drafts || [];
    renderAgentWork(agentRuns, emailDrafts, data.recent_reports || []);
    renderEmailDrafts(emailDrafts);
    todayTasksList.innerHTML = "";
    const overdue = data.tasks?.overdue || [];
    const today = data.tasks?.today || [];
    const upcoming = data.tasks?.upcoming || [];
    const noDate = data.tasks?.no_date || [];
    const visible = [
      ...overdue.map((task) => [task, "overdue"]),
      ...today.map((task) => [task, "today"]),
      ...upcoming.slice(0, 5).map((task) => [task, "upcoming"]),
      ...noDate.map((task) => [task, "no-date"]),
    ];
    todaySummary.textContent = `${overdue.length} atrasada(s) · ${today.length} para hoy · ${upcoming.length} próxima(s)`;
    if (!visible.length) {
      const empty = document.createElement("li");
      empty.textContent = "No hay tareas cargadas. Mandale una nota o un audio al Capataz.";
      todayTasksList.appendChild(empty);
    } else {
      for (const [task, bucket] of visible) todayTasksList.appendChild(createTaskListItem(task, bucket));
    }

    clientsDatalist.innerHTML = "";
    for (const client of data.clients || []) {
      const option = document.createElement("option");
      option.value = client.name || "";
      clientsDatalist.appendChild(option);
    }

    const decisions = data.pending_decisions || [];
    if (decisionsBox && decisionsList) {
      decisionsList.innerHTML = "";
      decisionsBox.hidden = !decisions.length;
      for (const decision of decisions) decisionsList.appendChild(createDecisionListItem(decision));
    }

    const uncoveredClients = data.clients_without_next_action || [];
    if (uncoveredClientsBox && uncoveredClientsList && uncoveredClientsSummary) {
      uncoveredClientsList.innerHTML = "";
      uncoveredClientsBox.hidden = !uncoveredClients.length;
      uncoveredClientsSummary.textContent = `${uncoveredClients.length} cliente(s) sin próximo paso`;
      for (const client of uncoveredClients) {
        uncoveredClientsList.appendChild(createUncoveredClientItem(client));
      }
    }

    const projects = data.water_projects || [];
    waterProjectsList.innerHTML = "";
    waterProjectsBox.hidden = !projects.length;
    for (const project of projects) {
      const li = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = project.client_name || project.title || "Proyecto de agua";
      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = project.next_action || project.title || "Sin próxima acción";
      li.append(title, meta);
      waterProjectsList.appendChild(li);
    }
    await showDueNotification(data);
  } catch (error) {
    if (agentWorkSummary) agentWorkSummary.textContent = `No pude cargar el trabajo: ${error.message || error}`;
    todaySummary.textContent = `No pude cargar el seguimiento: ${error.message || error}`;
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
  const session = requireActiveSession();
  if (!session) {
    photoInput.value = "";
    return;
  }
  await addItem("foto", file, file.name || `foto-${Date.now()}.jpg`, { session });
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
if (analyzeTextButton) {
  analyzeTextButton.addEventListener("click", analyzeTextIntake);
}
if (refreshDashboardButton) {
  refreshDashboardButton.addEventListener("click", loadDashboard);
}
if (addDraftTaskButton) {
  addDraftTaskButton.addEventListener("click", () => {
    collectDraftFromForm();
    currentDraft.tasks = currentDraft.tasks || [];
    currentDraft.tasks.push({ title: "", due_date: null, priority: "media", agent: "Cartera", notes: "" });
    renderDraftTasks();
  });
}
if (cancelDraftButton) {
  cancelDraftButton.addEventListener("click", deferCurrentDraft);
}
if (draftForm) {
  draftForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await confirmCurrentDraft();
  });
}
if (notificationsButton) {
  notificationsButton.addEventListener("click", async () => {
    notificationsButton.disabled = true;
    try {
      await enablePushNotifications();
      notificationsButton.textContent = "Avisos activados";
    } catch (error) {
      notificationsButton.textContent = "Activar avisos";
      alert(error.message || error);
    } finally {
      notificationsButton.disabled = false;
    }
  });
  if (localStorage.getItem("capataz.pushEnabled") === "true") {
    notificationsButton.textContent = "Avisos activados";
  }
}
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPromptEvent = event;
  if (installButton) installButton.hidden = false;
});
if (installButton) {
  installButton.addEventListener("click", async () => {
    if (!installPromptEvent) return;
    await installPromptEvent.prompt();
    installPromptEvent = null;
    installButton.hidden = true;
  });
}
window.addEventListener("online", async () => {
  setConnectionStatus();
  appendDebug("Conexion online. Sincronizando pendientes.");
  await syncPending();
});
window.addEventListener("offline", setConnectionStatus);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((error) => {
    appendDebug(`No se pudo iniciar el servicio de avisos: ${error.message || error}`);
  });
}

loadInputs();
const sharedText = localStorage.getItem("capataz.sharedText") || "";
if (sharedText && noteInput) {
  noteInput.value = sharedText;
  localStorage.removeItem("capataz.sharedText");
  if (sharedTextNotice) sharedTextNotice.hidden = false;
}
setConnectionStatus();
renderActiveSession();
refreshGps();
renderItems();
renderServerItems();
renderSessions();
loadDashboard();
openNextDraft();
window.setInterval(loadDashboard, 15 * 60 * 1000);
