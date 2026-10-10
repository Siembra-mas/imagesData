const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const statusList = document.getElementById("statusList");
const btnUpload = document.getElementById("btnUpload");
const btnDownload = document.getElementById("btnDownload");
const datasetType = document.getElementById("datasetType");
const datasetSubtype = document.getElementById("datasetSubtype");

let selectedFiles = [];
let datasetCatalog = [];

if (dropzone && fileInput) {
  dropzone.onclick = () => fileInput.click();
  dropzone.ondragover = (e) => { e.preventDefault(); dropzone.classList.add("dragover"); };
  dropzone.ondragleave = () => dropzone.classList.remove("dragover");
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) queueFiles(e.dataTransfer.files);
  };
  fileInput.onchange = () => {
    if (fileInput.files.length) queueFiles(fileInput.files);
  };
}

if (datasetType) {
  datasetType.onchange = () => {
    populateSubtypes();
    updateUploadButton();
    updateDownloadButton();
  };
}

loadDatasetCatalog();
loadSessionRole();
updateUploadButton();

async function loadSessionRole() {
  try {
    const response = await fetch("/api/auth/me");
    const session = await response.json();
    if (response.ok && session.role === "dataset_manager") {
      btnDownload.style.display = "block";
      updateDownloadButton();
    }
  } catch (error) {
    btnDownload.style.display = "none";
  }
}

async function loadDatasetCatalog() {
  try {
    const response = await fetch("/api/upload/catalog");
    if (!response.ok) throw new Error("No se pudo cargar el catálogo");
    datasetCatalog = (await response.json()).datasets || [];
    datasetType.innerHTML = '<option value="" selected disabled>Selecciona un tipo</option>';
    for (const dataset of datasetCatalog) {
      const option = document.createElement("option");
      option.value = dataset.dataset_type;
      option.textContent = dataset.name;
      datasetType.appendChild(option);
    }
  } catch (error) {
    datasetType.innerHTML = '<option value="" selected disabled>No se pudo cargar el catálogo</option>';
  }
}

function populateSubtypes() {
  const selected = datasetCatalog.find(item => item.dataset_type === datasetType.value);
  datasetSubtype.innerHTML = '<option value="" selected disabled>Selecciona un subtipo</option>';
  datasetSubtype.disabled = !selected || selected.subtypes.length === 0;
  for (const subtype of selected?.subtypes || []) {
    const option = document.createElement("option");
    option.value = subtype;
    option.textContent = subtype;
    datasetSubtype.appendChild(option);
  }
}

function queueFiles(files) {
  const allowedExtensions = ['.png', '.jpg', '.jpeg', '.webp', '.pdf', '.doc', '.docx', '.zip', '.rar'];

  for (const file of files) {
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (file.size === 0) {
      addStatus(file.name, "Rechazado: archivo vacío", "#f87171");
      continue;
    }
    if (!allowedExtensions.includes(extension)) {
      addStatus(file.name, "Rechazado: formato no admitido", "#f87171");
      continue;
    }
    if (!selectedFiles.some(f => f.name === file.name && f.size === file.size)) {
      selectedFiles.push(file);
      addStatus(file.name, "Listo para enviar", "#94a3b8");
    }
  }

  updateUploadButton();
}

function updateUploadButton() {
  if (!btnUpload) return;

  const canUpload = Boolean(datasetType?.value && datasetSubtype?.value) && selectedFiles.length > 0;
  btnUpload.disabled = !canUpload;
  btnUpload.style.opacity = canUpload ? "1" : "0.5";
  btnUpload.innerText = canUpload
    ? `Enviar ${selectedFiles.length} archivo(s)`
    : !datasetType?.value
      ? "Selecciona el tipo de dataset"
      : !datasetSubtype?.value
        ? "Selecciona el subtipo"
        : "Selecciona archivos para subir";
}

function updateDownloadButton() {
  if (!btnDownload) return;
  btnDownload.disabled = !datasetType?.value || !datasetSubtype?.value;
}

function downloadDataset() {
  if (!datasetType?.value || !datasetSubtype?.value) return;
  const url = `/api/download/datasets/${encodeURIComponent(datasetType.value)}`;
  window.location.href = url;
}

function addStatus(name, text, color) {
  const safeName = name.replace(/[^a-zA-Z0-9]/g, "");
  const id = "st-" + safeName;
  let item = document.getElementById(id + "-container");

  if (!item) {
    item = document.createElement("div");
    item.className = "file-item";
    item.id = id + "-container";
    const filename = document.createElement("span");
    filename.textContent = name;
    const status = document.createElement("span");
    status.id = id;
    status.textContent = text;
    item.append(filename, status);
    statusList.prepend(item);
  } else {
    document.getElementById(id).innerText = text;
  }
  document.getElementById(id).style.color = color;
  return id;
}

async function startUpload() {
  if (!btnUpload || !datasetType?.value || !datasetSubtype?.value || selectedFiles.length === 0) return;

  btnUpload.disabled = true;
  btnUpload.style.opacity = "0.5";
  btnUpload.innerText = "Subiendo archivos...";

  const queue = [...selectedFiles];
  selectedFiles = [];

  try {
    for (const file of queue) {
      await uploadSingleFile(file);
    }
  } catch (error) {
    console.error("Error inesperado durante la carga", error);
  } finally {
    btnUpload.innerText = "Carga finalizada";
    window.setTimeout(updateUploadButton, 2500);
  }
}

function createUploadId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("El navegador no permite iniciar una carga segura. Abre la aplicación con HTTPS.");
  }

  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function uploadSingleFile(file) {
  addStatus(file.name, "Iniciando carga fragmentada...", "#38bdf8");

  try {
    const chunkSize = 10 * 1024 * 1024; // 10MB por petición
    const totalChunks = Math.ceil(file.size / chunkSize);
    const uploadId = createUploadId();
    let processingUploadId = null;

    for (let i = 0; i < totalChunks; i++) {
      const start = i * chunkSize;
      const end = Math.min(start + chunkSize, file.size);
      const chunk = file.slice(start, end);
      let chunkSha256 = null;
      if (globalThis.crypto?.subtle) {
        const hashBuffer = await globalThis.crypto.subtle.digest("SHA-256", await chunk.arrayBuffer());
        chunkSha256 = Array.from(new Uint8Array(hashBuffer), byte => byte.toString(16).padStart(2, "0")).join("");
      }

      const formData = new FormData();
      formData.append("dataset_type", datasetType.value);
      formData.append("subtype", datasetSubtype.value);
      formData.append("filename", file.name);
      formData.append("upload_id", uploadId);
      formData.append("chunk_index", i);
      formData.append("total_chunks", totalChunks);
      if (chunkSha256) formData.append("chunk_sha256", chunkSha256);
      formData.append("file", chunk);

      let uploaded = false;
      for (let attempt = 1; attempt <= 3 && !uploaded; attempt++) {
        addStatus(file.name, `Subiendo parte ${i + 1} de ${totalChunks}${attempt > 1 ? ` (intento ${attempt})` : ""}...`, "#facc15");

        try {
          const res = await fetch("/api/upload/files", {
            method: "POST",
            body: formData
          });

          if (res.ok) {
            const result = await res.json().catch(() => ({}));
            if (i === totalChunks - 1) processingUploadId = result.upload_id || null;
            uploaded = true;
            continue;
          }

          const err = await res.json().catch(() => ({}));
          const message = err.detail || `Error en el fragmento ${i + 1}`;
          if (res.status < 500 && res.status !== 429) throw new Error(message);
          if (attempt === 3) throw new Error(`El servidor rechazó la parte ${i + 1}: ${message}`);
        } catch (error) {
          if (!(error instanceof TypeError)) throw error;
          if (attempt === 3) {
            throw new Error(`No se pudo enviar la parte ${i + 1} de ${totalChunks}. Revisa la conexión y vuelve a intentarlo.`);
          }
          addStatus(file.name, `Conexión interrumpida; reintentando parte ${i + 1}...`, "#b45309");
          await new Promise(resolve => window.setTimeout(resolve, attempt * 1500));
        }
      }
    }

    if (!processingUploadId) {
      throw new Error("El servidor no confirmó el procesamiento del archivo.");
    }

    await waitForUploadResult(file, processingUploadId);

  } catch (err) {
    addStatus(file.name, err.message, "#f87171");
  }
}

async function waitForUploadResult(file, uploadId) {
  const startedAt = Date.now();
  let delay = 1500;
  let connectionFailures = 0;

  while (Date.now() - startedAt < 30 * 60 * 1000) {
    addStatus(file.name, "Guardando en almacenamiento...", "#2563eb");
    await new Promise(resolve => window.setTimeout(resolve, delay));

    let response;
    try {
      response = await fetch(`/api/upload/status/${encodeURIComponent(uploadId)}`);
      connectionFailures = 0;
    } catch (error) {
      connectionFailures += 1;
      addStatus(file.name, `Sin conexión para consultar el resultado; reintentando (${connectionFailures})...`, "#b45309");
      delay = Math.min(delay * 1.5, 10000);
      continue;
    }

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw new Error("La sesión terminó antes de confirmar el guardado. Inicia sesión y consulta con el administrador.");
      }
      if (response.status >= 500 || response.status === 429) {
        addStatus(file.name, "El servidor no pudo consultar el resultado; reintentando...", "#b45309");
        delay = Math.min(delay * 1.5, 10000);
        continue;
      }
      throw new Error(`No se pudo consultar el estado del archivo (HTTP ${response.status}).`);
    }

    const result = await response.json();
    if (result.status === "completed") {
      addStatus(file.name, "Listo: archivo guardado", "#059669");
      return;
    }
    if (result.status === "failed") {
      throw new Error(result.message || "No se pudo guardar el archivo.");
    }

    delay = Math.min(delay * 1.5, 10000);
  }

  addStatus(file.name, "Carga recibida; no se pudo confirmar el guardado. Revisa la conexión e inténtalo más tarde.", "#b45309");
}