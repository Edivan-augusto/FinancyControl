document.addEventListener("DOMContentLoaded", () => {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("pdf_files");
  const categoryOptions = Array.isArray(window.CATEGORY_OPTIONS)
    ? window.CATEGORY_OPTIONS
    : [];

  if (dropZone && fileInput) {
    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf")
      );
      if (files.length) {
        fileInput.files = e.dataTransfer.files;
      }
    });
  }

  const merchantSearch = document.getElementById("merchant-search");

  function applyMerchantFilter() {
    const term = (merchantSearch?.value || "").toLowerCase();
    document.querySelectorAll(".merchant-item").forEach((item) => {
      const name = item
        .querySelector(".merchant-name")
        .textContent.toLowerCase();
      item.style.display = name.includes(term) ? "" : "none";
    });
  }

  function updateEmptyMessages() {
    const unassignedEmpty = document.getElementById("merchant-unassigned-empty");
    const assignedEmpty = document.getElementById("merchant-assigned-empty");
    const unassignedCount =
      document.querySelectorAll("#merchant-list .merchant-item").length;
    const assignedCount =
      document.querySelectorAll("#merchant-list-assigned .merchant-item").length;
    if (unassignedEmpty) {
      unassignedEmpty.classList.toggle("d-none", unassignedCount > 0);
    }
    if (assignedEmpty) {
      assignedEmpty.classList.toggle("d-none", assignedCount > 0);
    }
  }

  function createCategorySelect(merchant) {
    const select = document.createElement("select");
    select.className = "form-select form-select-sm merchant-category-select";
    select.setAttribute("data-merchant", merchant);

    const optEmpty = document.createElement("option");
    optEmpty.value = "";
    optEmpty.textContent = "Selecione...";
    select.appendChild(optEmpty);

    categoryOptions.forEach((cat) => {
      const opt = document.createElement("option");
      opt.value = cat;
      opt.textContent = cat;
      select.appendChild(opt);
    });

    attachCategorySelect(select);
    return select;
  }

  function createClearButton(merchant) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-outline-danger btn-sm merchant-clear-btn";
    btn.setAttribute("data-merchant", merchant);
    btn.textContent = "Remover";
    attachClearButton(btn);
    return btn;
  }

  function attachCategorySelect(select) {
    select.addEventListener("change", async (e) => {
      const merchant = e.target.getAttribute("data-merchant");
      const category = e.target.value;
      if (!merchant || !category) return;
      const item = e.target.closest(".merchant-item");
      const totalText =
        item?.querySelector("small")?.textContent?.trim() || "";
      const merchantName = item?.querySelector(".merchant-name")?.textContent || merchant;

      try {
        const resp = await fetch("/update-category", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ merchant, category }),
        });
        const data = await resp.json();
        if (!data.ok) {
          console.error("Erro ao salvar categoria:", data.error);
          return;
        }

        // Move item to "assigned" list without reloading
        if (item) item.remove();

        const assignedList = document.getElementById("merchant-list-assigned");
        if (!assignedList) return;

        const newItem = document.createElement("div");
        newItem.className =
          "d-flex align-items-start justify-content-between merchant-item mb-2";

        const info = document.createElement("div");
        info.className = "merchant-info";
        const nameDiv = document.createElement("div");
        nameDiv.className = "merchant-name";
        nameDiv.textContent = merchantName.trim();
        const small = document.createElement("small");
        small.className = "text-muted d-block";
        small.textContent = totalText;
        const badge = document.createElement("span");
        badge.className = "badge bg-secondary mt-1";
        badge.textContent = category;
        info.appendChild(nameDiv);
        info.appendChild(small);
        info.appendChild(badge);

        const actions = document.createElement("div");
        actions.className = "merchant-actions";
        actions.appendChild(createClearButton(merchant));

        newItem.appendChild(info);
        newItem.appendChild(actions);

        assignedList.appendChild(newItem);
        updateEmptyMessages();
        applyMerchantFilter();
      } catch (err) {
        console.error("Erro ao salvar categoria", err);
      }
    });
  }

  function attachClearButton(btn) {
    btn.addEventListener("click", async (e) => {
      const merchant = e.target.getAttribute("data-merchant");
      if (!merchant) return;
      const item = e.target.closest(".merchant-item");
      const totalText =
        item?.querySelector("small")?.textContent?.trim() || "";
      const merchantName = item?.querySelector(".merchant-name")?.textContent || merchant;

      try {
        const resp = await fetch("/clear-category", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ merchant }),
        });
        const data = await resp.json();
        if (!data.ok) {
          console.error("Erro ao remover categoria:", data.error);
          return;
        }

        // Move item back to "unassigned" list without reloading
        if (item) item.remove();

        const unassignedList = document.getElementById("merchant-list");
        if (!unassignedList) return;

        const newItem = document.createElement("div");
        newItem.className =
          "d-flex align-items-start justify-content-between merchant-item mb-2";

        const info = document.createElement("div");
        info.className = "merchant-info";
        const nameDiv = document.createElement("div");
        nameDiv.className = "merchant-name";
        nameDiv.textContent = merchantName.trim();
        const small = document.createElement("small");
        small.className = "text-muted";
        small.textContent = totalText;
        info.appendChild(nameDiv);
        info.appendChild(small);

        const actions = document.createElement("div");
        actions.className = "merchant-actions";
        actions.appendChild(createCategorySelect(merchant));

        newItem.appendChild(info);
        newItem.appendChild(actions);

        unassignedList.appendChild(newItem);
        updateEmptyMessages();
        applyMerchantFilter();
      } catch (err) {
        console.error("Erro ao remover categoria", err);
      }
    });
  }

  if (merchantSearch) {
    merchantSearch.addEventListener("input", applyMerchantFilter);
  }

  document.querySelectorAll(".merchant-category-select").forEach((select) => {
    attachCategorySelect(select);
  });

  document.querySelectorAll(".merchant-clear-btn").forEach((btn) => {
    attachClearButton(btn);
  });

  updateEmptyMessages();

  const merchantCtx = document.getElementById("chart-merchant");
  const categoryCtx = document.getElementById("chart-category");

  if (merchantCtx && chartMerchantData.labels.length) {
    new Chart(merchantCtx, {
      type: "bar",
      data: {
        labels: chartMerchantData.labels,
        datasets: [
          {
            label: "Gasto (R$)",
            data: chartMerchantData.values,
            backgroundColor: "rgba(220, 53, 69, 0.7)",
          },
        ],
      },
      options: {
        indexAxis: "y",
        scales: {
          x: {
            ticks: {
              callback: (value) => `R$ ${value.toFixed(2)}`,
            },
          },
        },
      },
    });
  }

  if (categoryCtx && chartCategoryData.labels.length) {
    new Chart(categoryCtx, {
      type: "doughnut",
      data: {
        labels: chartCategoryData.labels,
        datasets: [
          {
            data: chartCategoryData.values,
            backgroundColor: [
              "#0d6efd",
              "#dc3545",
              "#198754",
              "#fd7e14",
              "#6f42c1",
              "#20c997",
              "#ffc107",
            ],
          },
        ],
      },
      options: {
        plugins: {
          legend: {
            position: "bottom",
          },
        },
      },
    });
  }
});
