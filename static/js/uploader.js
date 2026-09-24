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
  const allowedTypes = ['image/png', 'image/jpeg', 'image/webp'];
  const allowedExtensions = ['.png', '.jpg', '.jpeg', '.webp'];

  for (const file of files) {
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowedTypes.includes(file.type) || !allowedExtensions.includes(extension)) {
      addStatus(file.name, "Rechazado: formato no válido", "#f87171");
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
    ? `Enviar ${selectedFiles.length} imagen(es)`
    : !datasetType?.value
      ? "Selecciona el tipo de dataset"
      : !datasetSubtype?.value
        ? "Selecciona el subtipo"
        : "Selecciona imágenes para subir";
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
    item.innerHTML = `<span>${name}</span><span id="${id}">${text}</span>`;
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
  btnUpload.innerText = "Subiendo imágenes...";

  const queue = [...selectedFiles];
  selectedFiles = [];

  for (const file of queue) {
    await uploadSingleFile(file);
  }

  btnUpload.innerText = "Carga finalizada";
  setTimeout(() => {
    btnUpload.innerText = "Selecciona imágenes para subir";
  }, 2500);
}

async function uploadSingleFile(file) {
  addStatus(file.name, "Validando y subiendo...", "#38bdf8");

  try {
    const formData = new FormData();
    formData.append("dataset_type", datasetType.value);
    formData.append("subtype", datasetSubtype.value);
    formData.append("file", file);
    const res = await fetch("/api/upload/images", {
      method: "POST",
      body: formData
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Error al firmar");
    }

    await res.json();
    addStatus(file.name, "Procesando en segundo plano", "#4ade80");

  } catch (err) {
    addStatus(file.name, err.message, "#f87171");
  }
}