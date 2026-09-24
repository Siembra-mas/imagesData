const datasetList = document.getElementById("datasetList");

async function loadDatasets() {
  try {
    const response = await fetch("/api/upload/catalog");
    if (!response.ok) throw new Error("No se pudo cargar el catálogo");

    const { datasets } = await response.json();
    datasetList.replaceChildren();

    if (!datasets.length) {
      datasetList.innerHTML = '<p class="empty-state">No hay datasets disponibles.</p>';
      return;
    }

    for (const dataset of datasets) {
      const item = document.createElement("div");
      item.className = "dataset-row";
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(dataset.name)}</strong>
          <span>${dataset.subtypes.length} subtipo(s) configurado(s)</span>
        </div>
        <a class="btn-primary download-action" href="/api/download/datasets/${encodeURIComponent(dataset.dataset_type)}">
          Descargar ZIP
        </a>
      `;
      datasetList.appendChild(item);
    }
  } catch (error) {
    datasetList.innerHTML = '<p class="empty-state error-state">No se pudo cargar el catálogo.</p>';
  }
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

loadDatasets();