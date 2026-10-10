const datasetFilter = document.getElementById("datasetFilter");
const subtypeFilter = document.getElementById("subtypeFilter");
const fileTypeFilter = document.getElementById("fileTypeFilter");
const searchFilter = document.getElementById("searchFilter");
const selectVisible = document.getElementById("selectVisible");
const selectionSummary = document.getElementById("selectionSummary");
const downloadSelection = document.getElementById("downloadSelection");
const downloadMessage = document.getElementById("downloadMessage");
const fileList = document.getElementById("fileList");

let datasets = [];
let files = [];
let selectedIds = new Set();
let selectedFilesById = new Map();
let filesRequestId = 0;

datasetFilter.addEventListener("change", () => {
  populateSubtypes();
  loadFiles();
});
subtypeFilter.addEventListener("change", loadFiles);
fileTypeFilter.addEventListener("change", loadFiles);
searchFilter.addEventListener("input", renderFiles);
selectVisible.addEventListener("change", toggleVisibleFiles);
downloadSelection.addEventListener("click", startSelectionDownload);

async function loadPage() {
  try {
    const [catalogResponse, filesResponse] = await Promise.all([
      fetch("/api/upload/catalog"),
      fetch("/api/download/files"),
    ]);
    if (!catalogResponse.ok || !filesResponse.ok) {
      throw new Error("No se pudieron cargar los archivos disponibles.");
    }

    datasets = (await catalogResponse.json()).datasets || [];
    datasetFilter.replaceChildren(new Option("Todos los datasets", ""));
    for (const dataset of datasets) {
      datasetFilter.add(new Option(dataset.name, dataset.dataset_type));
    }

    const result = await filesResponse.json();
    files = result.files || [];
    renderFiles();
    if (result.truncated) {
      setMessage("Se muestran los primeros 5000 archivos. Usa los filtros para acotar la lista.");
    } else if (!files.length) {
      setMessage("No hay archivos completados disponibles para descargar.");
    } else {
      setMessage(`${files.length} archivos disponibles.`);
    }
  } catch (error) {
    setMessage(error.message, true);
  }
}

function populateSubtypes() {
  const selectedDataset = datasets.find(item => item.dataset_type === datasetFilter.value);
  subtypeFilter.replaceChildren(new Option("Todos los subtipos", ""));
  for (const subtype of selectedDataset?.subtypes || []) {
    subtypeFilter.add(new Option(subtype, subtype));
  }
  subtypeFilter.disabled = !selectedDataset || selectedDataset.subtypes.length === 0;
}

async function loadFiles() {
  const requestId = ++filesRequestId;
  setMessage("Cargando archivos...");
  const params = new URLSearchParams();
  if (datasetFilter.value) params.set("dataset_type", datasetFilter.value);
  if (subtypeFilter.value) params.set("subtype", subtypeFilter.value);
  if (fileTypeFilter.value) params.set("file_type", fileTypeFilter.value);

  try {
    const response = await fetch(`/api/download/files?${params}`);
    if (!response.ok) throw new Error("No se pudo cargar la lista de archivos.");
    const result = await response.json();
    if (requestId !== filesRequestId) return;
    files = result.files || [];
    renderFiles();
    setMessage(result.truncated
      ? "Se muestran los primeros 5000 archivos. Usa los filtros para acotar la lista."
      : `${files.length} archivos disponibles.`);
  } catch (error) {
    fileList.replaceChildren();
    setMessage(error.message, true);
  }
}

function visibleFiles() {
  const term = searchFilter.value.trim().toLocaleLowerCase();
  return files.filter(file => file.filename.toLocaleLowerCase().includes(term));
}

function renderFiles() {
  const visible = visibleFiles();
  fileList.replaceChildren();

  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty-state";
    cell.textContent = files.length ? "No hay coincidencias con la búsqueda." : "No hay archivos para mostrar.";
    row.appendChild(cell);
    fileList.appendChild(row);
  }

  for (const file of visible) {
    const row = document.createElement("tr");
    const checkboxCell = document.createElement("td");
    checkboxCell.className = "checkbox-column";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedIds.has(file.upload_id);
    checkbox.setAttribute("aria-label", `Seleccionar ${file.filename}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectedIds.add(file.upload_id);
        selectedFilesById.set(file.upload_id, file);
      } else {
        selectedIds.delete(file.upload_id);
        selectedFilesById.delete(file.upload_id);
      }
      updateSelectionSummary();
    });
    checkboxCell.appendChild(checkbox);

    const filenameCell = document.createElement("td");
    filenameCell.className = "filename-cell";
    filenameCell.textContent = file.filename;

    const datasetCell = document.createElement("td");
    datasetCell.textContent = `${file.dataset_type} / ${file.subtype || "Sin subtipo"}`;

    const formatCell = document.createElement("td");
    formatCell.textContent = file.filename.split(".").pop().toUpperCase();

    const sizeCell = document.createElement("td");
    sizeCell.textContent = formatBytes(file.file_size);

    const dateCell = document.createElement("td");
    dateCell.textContent = formatDate(file.created_at);

    row.append(checkboxCell, filenameCell, datasetCell, formatCell, sizeCell, dateCell);
    fileList.appendChild(row);
  }

  selectVisible.checked = visible.length > 0 && visible.every(file => selectedIds.has(file.upload_id));
  selectVisible.indeterminate = visible.some(file => selectedIds.has(file.upload_id)) && !selectVisible.checked;
  updateSelectionSummary();
}

function toggleVisibleFiles() {
  for (const file of visibleFiles()) {
    if (selectVisible.checked) {
      selectedIds.add(file.upload_id);
      selectedFilesById.set(file.upload_id, file);
    } else {
      selectedIds.delete(file.upload_id);
      selectedFilesById.delete(file.upload_id);
    }
  }
  renderFiles();
}

function updateSelectionSummary() {
  const totalSize = [...selectedFilesById.values()].reduce((total, file) => total + (file.file_size || 0), 0);
  selectionSummary.textContent = `${selectedIds.size} seleccionados · ${formatBytes(totalSize)}`;
  downloadSelection.disabled = selectedIds.size === 0;
}

function startSelectionDownload() {
  if (selectedIds.size === 0) return;
  if (selectedIds.size > 250) {
    setMessage("Puedes descargar hasta 250 archivos por selección.", true);
    return;
  }

  downloadSelection.disabled = true;
  setMessage("Iniciando descarga del ZIP seleccionado...");

  const form = document.createElement("form");
  form.method = "POST";
  form.action = "/api/download/selection";
  form.hidden = true;

  for (const uploadId of selectedIds) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "upload_ids";
    input.value = uploadId;
    form.appendChild(input);
  }

  document.body.appendChild(form);
  form.submit();
  form.remove();
  window.setTimeout(() => {
    downloadSelection.disabled = selectedIds.size === 0;
    setMessage("Si la descarga no comenzó, revisa tu conexión e inténtalo de nuevo.");
  }, 5000);
}

function formatBytes(value) {
  if (value === null || value === undefined) return "Desconocido";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(1)} ${units[unit]}`;
}

function formatDate(value) {
  if (!value) return "Desconocida";
  return new Date(value).toLocaleDateString("es", { year: "numeric", month: "short", day: "numeric" });
}

function setMessage(message, isError = false) {
  downloadMessage.textContent = message;
  downloadMessage.classList.toggle("error-state", isError);
}

loadPage();