const DB_NAME = "campo-pwa";
const STORE_NAME = "items";
const campoInput = document.getElementById("campoInput");
const sectorInput = document.getElementById("sectorInput");
const talkButton = document.getElementById("talkButton");
const photoInput = document.getElementById("photoInput");
const itemsList = document.getElementById("itemsList");
const serverItemsList = document.getElementById("serverItemsList");
const connectionStatus = document.getElementById("connectionStatus");
const gpsStatus = document.getElementById("gpsStatus");
const gpsButton = document.getElementById("gpsButton");
const syncButton = document.getElementById("syncButton");
const forceSyncButton = document.getElementById("forceSyncButton");
const refreshServerButton = document.getElementById("refreshServerButton");
const debugLog = document.getElementById("debugLog");

let dbPromise;
let recorder;
let audioChunks = [];
let currentPosition = null;

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

function appendDebug(message) {
  if (!debugLog) return;
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
  debugLog.prepend(li);
}

function persistInputs() {
  localStorage.setItem("campo.activo", campoInput.value);
  localStorage.setItem("campo.sector", sectorInput.value);
}

function loadInputs() {
  campoInput.value = localStorage.getItem("campo.activo") || "";
  sectorInput.value = localStorage.getItem("campo.sector") || "";
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

function buildItem(type, blob, filename) {
  const campo = requireCampo();
  if (!campo) return null;

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
  };
}

async function addItem(type, blob, filename) {
  const item = buildItem(type, blob, filename);
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
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const items = data.items || [];

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
      li.innerHTML = `
        <div class="item-main">
          <span>${item.tipo === "audio" ? "Audio" : "Foto"} - ${item.campo || "sin campo"}</span>
          <span class="pill subido">${item.estado || "subido"}</span>
        </div>
        <div class="item-meta">${item.sector || "sin sector"} - ${formatServerDate(item.fecha_hora)} - ${gps}${accuracy}</div>
        <div class="item-meta">${item.nombre_archivo || ""}</div>
      `;
      serverItemsList.appendChild(li);
    }
  } catch {
    const error = document.createElement("li");
    error.textContent = "No pude cargar los items subidos.";
    serverItemsList.appendChild(error);
  }
}

async function uploadLocalItem(item) {
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
  form.append("file", item.blob, item.filename);

  try {
    appendDebug("POST /api/field-items enviado");
    const response = await fetch("/api/field-items", { method: "POST", body: form });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    if (!data.ok) throw new Error(data.detail || "respuesta sin ok true");

    appendDebug("Servidor respondió OK");
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
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (event) => {
    if (event.data.size) audioChunks.push(event.data);
  };
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    const blob = new Blob(audioChunks, { type: recorder.mimeType || "audio/webm" });
    await addItem("audio", blob, `audio-${Date.now()}.webm`);
  };
  recorder.start();
  talkButton.classList.add("recording");
  talkButton.textContent = "Grabando...";
}

function stopRecording() {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
  }
  talkButton.classList.remove("recording");
  talkButton.textContent = "Mantener para hablar";
}

talkButton.addEventListener("pointerdown", async () => {
  try {
    await startRecording();
  } catch {
    alert("No pude acceder al microfono.");
  }
});
talkButton.addEventListener("pointerup", stopRecording);
talkButton.addEventListener("pointercancel", stopRecording);
talkButton.addEventListener("pointerleave", stopRecording);

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file) return;
  await addItem("foto", file, file.name || `foto-${Date.now()}.jpg`);
  photoInput.value = "";
});

campoInput.addEventListener("input", persistInputs);
sectorInput.addEventListener("input", persistInputs);
gpsButton.addEventListener("click", refreshGps);
syncButton.addEventListener("click", syncPending);
if (forceSyncButton) {
  forceSyncButton.addEventListener("click", () => syncPending({ force: true }));
}
if (refreshServerButton) {
  refreshServerButton.addEventListener("click", renderServerItems);
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
refreshGps();
renderItems();
renderServerItems();
