(function () {
  const node = document.getElementById("finance-data");
  if (!node || typeof Chart === "undefined") return;
  const data = JSON.parse(node.textContent || "{}");
  const gold = "#f5c542";
  const blue = "#3b82f6";
  const muted = "#8b93a7";
  const grid = "rgba(255,255,255,0.06)";
  const palette = ["#f5c542", "#3b82f6", "#22c55e", "#f43f5e", "#a78bfa", "#fb923c", "#14b8a6", "#e879f9", "#94a3b8"];

  Chart.defaults.font.family = "Avenir Next, Segoe UI, Helvetica Neue, system-ui, sans-serif";
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;

  function money(value) {
    return "$" + Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function lineChart(id, datasets) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    new Chart(canvas, {
      type: "line",
      data: { labels: data.labels || [], datasets: datasets },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { callback: money }, grid: { color: grid }, beginAtZero: true },
        },
        plugins: { legend: { display: datasets.length > 1 } },
      },
    });
  }

  function doughnut(id, rows) {
    const canvas = document.getElementById(id);
    if (!canvas || !rows || !rows.length) return;
    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: rows.map((row) => row.name),
        datasets: [{ data: rows.map((row) => row.amount), backgroundColor: palette, borderWidth: 0 }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  lineChart("trend-chart", [
    {
      label: "Square sales",
      data: data.sales || [],
      borderColor: gold,
      backgroundColor: "rgba(245, 197, 66, 0.16)",
      fill: true,
      tension: 0.35,
      pointRadius: 2,
      borderWidth: 3,
    },
    {
      label: "Filed bills",
      data: data.spend || [],
      borderColor: blue,
      backgroundColor: "rgba(59, 130, 246, 0.14)",
      fill: true,
      tension: 0.35,
      pointRadius: 2,
      borderWidth: 3,
    },
  ]);
  lineChart("sales-chart", [
    {
      label: "Square sales",
      data: data.sales || [],
      borderColor: gold,
      backgroundColor: "rgba(245, 197, 66, 0.16)",
      fill: true,
      tension: 0.35,
      pointRadius: 2,
      borderWidth: 3,
    },
  ]);
  lineChart("vendor-trend-chart", [
    {
      label: "Vendor spend",
      data: data.spend || [],
      borderColor: blue,
      backgroundColor: "rgba(59, 130, 246, 0.14)",
      fill: true,
      tension: 0.35,
      pointRadius: 2,
      borderWidth: 3,
    },
  ]);
  doughnut("mix-chart", data.mix || []);
  doughnut("expense-chart", data.expense_mix || []);
})();
