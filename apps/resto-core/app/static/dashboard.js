(function () {
  const node = document.getElementById("dash-data");
  if (!node || typeof Chart === "undefined") return;
  const data = JSON.parse(node.textContent || "{}");
  const gold = "#f5c542";
  const blue = "#3b82f6";
  const pink = "#f472b6";
  const orange = "#fb923c";
  const muted = "#8b93a7";
  const grid = "rgba(255,255,255,0.06)";
  const palette = ["#22c55e", "#3b82f6", "#f43f5e", "#f5c542", "#a78bfa"];

  function money(value) {
    return "$" + Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  Chart.defaults.font.family = "Avenir Next, Segoe UI, Helvetica Neue, system-ui, sans-serif";
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;

  function dayLabel(value, axis) {
    const label = axis.getLabelForValue(value) || "";
    return label.slice(5);
  }

  const houseCanvas = document.getElementById("house-chart");
  if (houseCanvas) {
    new Chart(houseCanvas, {
      type: "line",
      data: {
        labels: data.house_labels || data.labels || [],
        datasets: [
          {
            label: "Temperature",
            data: data.temperature || [],
            yAxisID: "y",
            borderColor: gold,
            backgroundColor: "rgba(245, 197, 66, 0.16)",
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            borderWidth: 3,
            spanGaps: true,
          },
          {
            label: "Cameras",
            data: data.cameras || [],
            yAxisID: "y1",
            borderColor: blue,
            backgroundColor: "rgba(59, 130, 246, 0.14)",
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            borderWidth: 3,
            spanGaps: true,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            ticks: { maxTicksLimit: 8, callback: function (value) { return dayLabel(value, this); } },
            grid: { display: false },
          },
          y: {
            position: "left",
            ticks: { callback: (value) => value + "°F" },
            grid: { color: grid },
            title: { display: true, text: "Temperature" },
          },
          y1: {
            position: "right",
            ticks: { precision: 0 },
            grid: { drawOnChartArea: false },
            title: { display: true, text: "Cameras" },
            suggestedMin: 0,
            suggestedMax: 4,
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const ordersCanvas = document.getElementById("orders-chart");
  if (ordersCanvas && (data.months || []).length) {
    const gradient = ordersCanvas.getContext("2d").createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, pink);
    gradient.addColorStop(1, orange);
    new Chart(ordersCanvas, {
      type: "bar",
      data: {
        labels: data.months,
        datasets: [{ label: "Orders", data: data.month_orders || [], backgroundColor: gradient, borderRadius: 8, maxBarThickness: 28 }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { precision: 0 }, grid: { color: grid } },
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
        cutout: "68%",
        plugins: {
          tooltip: {
            callbacks: { label: (ctx) => `${ctx.label}: ${money(ctx.parsed)}` },
          },
        },
      },
    });
  }

  function drawSpark(canvas, values, color) {
    const nums = (values || []).map((v) => Number(v) || 0);
    if (!canvas || !nums.length) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width = canvas.clientWidth || 120;
    const h = canvas.height = 36;
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const span = max - min || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    nums.forEach((value, index) => {
      const x = (index / Math.max(nums.length - 1, 1)) * (w - 2) + 1;
      const y = h - 4 - ((value - min) / span) * (h - 8);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  document.querySelectorAll("canvas.spark").forEach((canvas) => {
    const key = canvas.getAttribute("data-spark");
    drawSpark(canvas, key === "spend" ? data.spend_spark : data.sales_spark, key === "spend" ? gold : blue);
  });
})();
