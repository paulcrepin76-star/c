(function () {
  const node = document.getElementById("dash-data");
  if (!node || typeof Chart === "undefined") return;
  const data = JSON.parse(node.textContent || "{}");
  const teal = "#1a7a72";
  const ink = "#173033";
  const muted = "#5f7375";
  const palette = ["#1a7a72", "#d4a017", "#3d6b9a", "#b45a3c", "#6b7c85"];

  function money(value) {
    return "$" + Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  Chart.defaults.font.family = "Avenir Next, Segoe UI, Helvetica Neue, system-ui, sans-serif";
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;

  const salesCanvas = document.getElementById("sales-chart");
  if (salesCanvas) {
    new Chart(salesCanvas, {
      type: "line",
      data: {
        labels: data.labels || [],
        datasets: [
          {
            label: "Sales",
            data: data.sales || [],
            borderColor: teal,
            backgroundColor: "rgba(26, 122, 114, 0.12)",
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: "Invoice spend",
            data: data.purchases || [],
            borderColor: "#d4a017",
            backgroundColor: "rgba(212, 160, 23, 0.08)",
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              callback: function (value) {
                const label = this.getLabelForValue(value) || "";
                return label.slice(5);
              },
            },
            grid: { display: false },
          },
          y: {
            ticks: { callback: money },
            grid: { color: "#eef3f2" },
          },
        },
        plugins: {
          tooltip: {
            callbacks: { label: (ctx) => `${ctx.dataset.label}: ${money(ctx.parsed.y)}` },
          },
        },
      },
    });
  }

  const mixCanvas = document.getElementById("mix-chart");
  if (mixCanvas && (data.mix || []).length) {
    new Chart(mixCanvas, {
      type: "doughnut",
      data: {
        labels: data.mix.map((row) => row.name),
        datasets: [{ data: data.mix.map((row) => row.sales), backgroundColor: palette, borderWidth: 0 }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: { label: (ctx) => `${ctx.label}: ${money(ctx.parsed)}` },
          },
        },
      },
    });
  }

  const costCanvas = document.getElementById("cost-chart");
  if (costCanvas && (data.cost_bars || []).length) {
    new Chart(costCanvas, {
      type: "bar",
      data: {
        labels: data.cost_bars.map((row) => row.name),
        datasets: [{ label: "Cost %", data: data.cost_bars.map((row) => row.pct), backgroundColor: teal, borderRadius: 6, maxBarThickness: 42 }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { callback: (value) => value + "%" }, grid: { color: "#eef3f2" } },
        },
      },
    });
  }

  const vendorCanvas = document.getElementById("vendor-chart");
  if (vendorCanvas && (data.vendors || []).length) {
    new Chart(vendorCanvas, {
      type: "bar",
      data: {
        labels: data.vendors.map((row) => row.name),
        datasets: [{ label: "Spend", data: data.vendors.map((row) => row.spend), backgroundColor: ink, borderRadius: 6, maxBarThickness: 28 }],
      },
      options: {
        indexAxis: "y",
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { callback: money }, grid: { color: "#eef3f2" } },
          y: { grid: { display: false } },
        },
      },
    });
  }
})();
