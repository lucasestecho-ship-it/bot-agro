const DB_NAME = "campo-pwa";
const STORE_NAME = "items";
const campoInput = document.getElementById("campoInput");
const sectorInput = document.getElementById("sectorInput");
const talkButton = document.getElementById("talkButton");
const photoInput = document.getElementById("photoInput");
const itemsList = document.getElementById("itemsList");
const connectionStatus = document.getElementById("connectionStatus");
const gpsStatus = document.getElementById("gpsStatus");
const gpsButton = document.getElementById("gpsButton");
const syncButton = document.getElementById("syncButton");

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
    request.onsuccess = () => resolve(request.result.sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
    request.onerror = () => reject(request.error);
  });
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
  await syncPending();
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
    li.innerHTML = `
      <div class="item-main">
        <span>${item.type === "audio" ? "Audio" : "Foto"} - ${item.campo}</span>
        <span class="pill ${item.status}">${item.status}</span>
      </div>
      <div class="item-meta">${item.sector || "sin sector"} - ${new Date(item.createdAt).toLocaleString()} - ${gps}</div>
    `;
    itemsList.appendChild(li);
  }
}

async function syncPending() {
  if (!navigator.onLine) return;
  const items = await getItems();
  for (const item of items.filter((entry) => entry.status !== "subido")) {
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
      const response = await fetch("/api/field-items", { method: "POST", body: form });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      item.status = "subido";
    } catch (error) {
      item.status = "error";
    }
    await storeItem(item);
  }
  await renderItems();
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
window.addEventListener("online", () => {
  setConnectionStatus();
  syncPending();
});
window.addEventListener("offline", setConnectionStatus);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js");
}

loadInputs();
setConnectionStatus();
refreshGps();
renderItems();
syncPending();
