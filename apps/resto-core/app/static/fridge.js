(function () {
  const node = document.getElementById("fridge-data");
  const canvas = document.getElementById("fridge-chart");
  if (!node || !canvas || typeof Chart === "undefined") return;
  const data = JSON.parse(node.textContent || "{}");
  const gold = "#f5c542";
  const blue = "#3b82f6";
  const muted = "#8b93a7";
  const grid = "rgba(255,255,255,0.06)";
  const hours = Number(data.hours || 24);

  function tickLabel(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    if (hours >= 48) {
      return date.toLocaleString(undefined, { weekday: "short", hour: "numeric" });
    }
    return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }

  Chart.defaults.font.family = "Avenir Next, Segoe UI, Helvetica Neue, system-ui, sans-serif";
  Chart.defaults.color = muted;

  new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels || [],
      datasets: [
        {
          label: "Temperature",
          data: data.temperature || [],
          borderColor: gold,
          backgroundColor: "rgba(245, 197, 66, 0.16)",
          fill: true,
          tension: 0.25,
          pointRadius: (data.temperature || []).length > 40 ? 0 : 3,
          borderWidth: 3,
          spanGaps: true,
        },
        {
          label: "Min",
          data: data.min_ok || [],
          borderColor: blue,
          borderDash: [6, 6],
          pointRadius: 0,
          borderWidth: 1.5,
          fill: false,
        },
        {
          label: "Max",
          data: data.max_ok || [],
          borderColor: blue,
          borderDash: [6, 6],
          pointRadius: 0,
          borderWidth: 1.5,
          fill: false,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const iso = items[0] && items[0].label;
              const date = new Date(iso);
              if (Number.isNaN(date.getTime())) return iso;
              return date.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
            },
            label: (item) => `${item.dataset.label}: ${item.parsed.y}°F`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            maxTicksLimit: 8,
            callback: function (value) {
              return tickLabel(this.getLabelForValue(value));
            },
          },
          grid: { display: false },
        },
        y: {
          ticks: { callback: (value) => value + "°F" },
          grid: { color: grid },
          suggestedMin: Number(data.min_temp_f) - 4,
          suggestedMax: Number(data.max_temp_f) + 4,
        },
      },
    },
  });
})();
