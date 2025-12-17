document.addEventListener("DOMContentLoaded", () => {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("pdf_files");

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

  if (merchantSearch) {
    merchantSearch.addEventListener("input", () => {
      const term = merchantSearch.value.toLowerCase();
      document.querySelectorAll(".merchant-item").forEach((item) => {
        const name = item
          .querySelector(".merchant-name")
          .textContent.toLowerCase();
        item.style.display = name.includes(term) ? "" : "none";
      });
    });
  }

  document
    .querySelectorAll(".merchant-category-select")
    .forEach((select) => {
      select.addEventListener("change", async (e) => {
        const merchant = e.target.getAttribute("data-merchant");
        const category = e.target.value;
        if (!merchant || !category) return;
        try {
          const resp = await fetch("/update-category", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ merchant, category }),
          });
          const data = await resp.json();
          if (!data.ok) {
            console.error("Erro ao salvar categoria:", data.error);
          } else {
            // Recarrega para atualizar gráficos/tabela
            window.location.reload();
          }
        } catch (err) {
          console.error("Erro ao salvar categoria", err);
        }
      });
    });

  document.querySelectorAll(".merchant-clear-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const merchant = e.target.getAttribute("data-merchant");
      if (!merchant) return;
      try {
        const resp = await fetch("/clear-category", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ merchant }),
        });
        const data = await resp.json();
        if (!data.ok) {
          console.error("Erro ao remover categoria:", data.error);
        } else {
          window.location.reload();
        }
      } catch (err) {
        console.error("Erro ao remover categoria", err);
      }
    });
  });

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
