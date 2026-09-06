const boot = JSON.parse(document.getElementById("boot").textContent);
const CIRC = 2 * Math.PI * 46;

const state = {
  fleet: boot.fleet,
  library: boot.library,
  roots: boot.roots || [],
  files: { root: (boot.roots[0] || {}).id || "", path: "", items: [], crumbs: [] },
  query: "",
};

function $(id) {
  return document.getElementById(id);
}

function bytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let value = n;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function uptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function icon(name) {
  return `<svg><use href="#i-${name}"></use></svg>`;
}

function setRing(kind, percent) {
  const svg = document.querySelector(`[data-ring="${kind}"]`);
  if (!svg) return;
  const tick = svg.querySelector(".tick");
  const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
  tick.style.strokeDasharray = String(CIRC);
  tick.style.strokeDashoffset = String(CIRC - (clamped / 100) * CIRC);
}

function renderVitals(data) {
  $("cpu-read").textContent = `${data.cpu.percent.toFixed(1)}%`;
  $("cpu-meta").textContent = `${data.cpu.cores} cores · load ${data.cpu.load.join(" / ")}`;
  $("mem-read").textContent = `${data.memory.percent.toFixed(1)}%`;
  $("mem-meta").textContent = `${bytes(data.memory.used)} of ${bytes(data.memory.total)}`;
  const disk = (data.disks || [])[0];
  $("disk-read").textContent = `${(disk ? disk.percent : 0).toFixed(1)}%`;
  $("disk-meta").textContent = disk ? `${disk.name} · ${bytes(disk.used)} / ${bytes(disk.total)}` : "primary volume";
  $("up-read").textContent = uptime(data.uptime);
  $("up-meta").textContent = data.host;
  $("host-label").textContent = data.host;
  setRing("cpu", data.cpu.percent);
  setRing("memory", data.memory.percent);
  setRing("disk", disk ? disk.percent : 0);
}

function renderFleet(data) {
  const board = $("fleet-board");
  const q = state.query.toLowerCase();
  $("fleet-meta").textContent = data.demo
    ? `Sample fleet · ${data.running} running of ${data.total}. Mount Docker to see this box live.`
    : `${data.running} running · ${data.stopped} stopped · ${data.total} containers`;
  board.innerHTML = (data.groups || [])
    .map((group) => {
      const tiles = group.items
        .filter((item) => {
          if (!q) return true;
          return `${item.title} ${item.name} ${item.group} ${item.description}`.toLowerCase().includes(q);
        })
        .map((item) => {
          const href = item.href || "#fleet";
          const extra = item.ports && item.ports.length ? item.ports.join(" · ") : item.image;
          return `<a class="tile ${item.running ? "" : "off"}" href="${href}" ${item.href ? 'target="_blank" rel="noreferrer"' : ""} title="${extra}">
            <i class="pip ${item.running ? "on" : ""}"></i>
            <span class="tile-icon" style="--tile:${item.color}">${icon(item.icon)}</span>
            <b>${item.title}</b>
            <small>${item.running ? "live" : item.state}</small>
          </a>`;
        })
        .join("");
      if (!tiles) return "";
      return `<section class="group"><p class="group-name">${group.name}</p><div class="tiles">${tiles}</div></section>`;
    })
    .join("") || `<p class="empty">Nothing in the fleet matches that search.</p>`;
}

function renderLibrary(data) {
  const cards = [
    { key: "films", icon: "film", color: "#ffc230", href: (data.apps.find((a) => a.id === "radarr") || {}).href },
    { key: "series", icon: "series", color: "#00a5e4", href: (data.apps.find((a) => a.id === "sonarr") || {}).href },
    { key: "grabs", icon: "grab", color: "#6ea8fe", href: (data.apps.find((a) => a.id === "qbittorrent") || {}).href },
    { key: "screen", icon: "screen", color: "#aa5cc3", href: data.screen.href },
  ];
  $("library-grid").innerHTML = cards
    .map((card) => {
      const block = data[card.key] || {};
      const app = data.apps.find((a) => a.icon === card.icon) || {};
      const status = app.status || (block.linked ? "up" : "unlinked");
      const count = block.videos || block.files || 0;
      const href = card.href || "#files";
      return `<a class="glass lib-card ${status}" href="${href}" ${card.href ? 'target="_blank" rel="noreferrer"' : ""}>
        <span class="badge"><i class="dot"></i>${status === "unlinked" ? "folder" : status}</span>
        <span class="lib-icon" style="background:${card.color}">${icon(card.icon)}</span>
        <span>${block.label}</span>
        <strong>${count || "—"}</strong>
        <em>${block.hint || ""}</em>
      </a>`;
    })
    .join("");
  const recent = (data.recent || []).filter((item) => {
    if (!state.query) return true;
    return item.name.toLowerCase().includes(state.query.toLowerCase());
  });
  $("recent-list").innerHTML = recent.length
    ? recent
        .map(
          (item) => `<li>
          <span class="file-kind">${icon(item.kind)}</span>
          <div><b>${item.name}</b><br><small>${item.root}${item.path ? " / " + item.path : ""}</small></div>
          <small>${bytes(item.size)}</small>
        </li>`
        )
        .join("")
    : `<li class="empty">Drop files into the library or grab folders and they will show up here.</li>`;
}

function renderRoots() {
  $("root-chips").innerHTML = state.roots
    .map(
      (root) =>
        `<button type="button" class="chip ${root.id === state.files.root ? "on" : ""}" data-root="${root.id}">${root.name}</button>`
    )
    .join("");
}

function renderFiles(data) {
  state.files = { root: data.root, path: data.path || "", items: data.items || [], crumbs: data.crumbs || [] };
  $("crumbs").innerHTML = (data.crumbs || [])
    .map((crumb) => `<button type="button" class="crumb" data-path="${crumb.path}">${crumb.name}</button>`)
    .join("<span>/</span>");
  const q = state.query.toLowerCase();
  const items = (data.items || []).filter((item) => !q || item.name.toLowerCase().includes(q));
  $("file-list").innerHTML = items.length
    ? items
        .map((item) => {
          const open = item.kind === "folder"
            ? `data-open="${item.path}"`
            : `href="/api/files/download?root=${encodeURIComponent(item.root)}&path=${encodeURIComponent(item.path)}"`;
          const tag = item.kind === "folder" ? "button" : "a";
          return `<${tag} class="file-row" ${open}>
            <span class="file-kind">${icon(item.kind)}</span>
            <div class="grow"><b>${item.name}</b><br><small>${item.kind}</small></div>
            <small>${item.kind === "folder" ? "" : bytes(item.size)}</small>
            <button type="button" class="danger" data-del="${item.path}">Delete</button>
          </${tag}>`;
        })
        .join("")
    : `<p class="empty">This folder is empty.</p>`;
}

async function loadFiles(root, path) {
  if (!root) return;
  const url = `/api/files?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path || "")}`;
  const res = await fetch(url);
  if (!res.ok) {
    $("file-list").innerHTML = `<p class="empty">That folder is not mounted yet.</p>`;
    return;
  }
  renderFiles(await res.json());
}

function tickClock() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString([], { hour12: false });
  const hour = now.getHours();
  $("greet").textContent = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function watchNav() {
  const links = document.querySelectorAll("[data-nav]");
  const sections = [...links].map((link) => document.getElementById(link.dataset.nav));
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        links.forEach((link) => link.classList.toggle("on", link.dataset.nav === entry.target.id));
      });
    },
    { rootMargin: "-40% 0px -50% 0px" }
  );
  sections.forEach((section) => section && io.observe(section));
}

async function refresh() {
  try {
    const [sys, fleet, lib] = await Promise.all([
      fetch("/api/system").then((r) => r.json()),
      fetch("/api/fleet").then((r) => r.json()),
      fetch("/api/library").then((r) => r.json()),
    ]);
    renderVitals(sys);
    state.fleet = fleet;
    state.library = lib;
    renderFleet(fleet);
    renderLibrary(lib);
  } catch (err) {
    console.warn(err);
  }
}

function bind() {
  $("q").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderFleet(state.fleet);
    renderLibrary(state.library);
    if (state.files.root) renderFiles(state.files);
  });
  $("root-chips").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-root]");
    if (!btn) return;
    renderRoots();
    loadFiles(btn.dataset.root, "");
    state.files.root = btn.dataset.root;
    [...$("root-chips").children].forEach((chip) => chip.classList.toggle("on", chip.dataset.root === btn.dataset.root));
  });
  $("crumbs").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-path]");
    if (!btn) return;
    loadFiles(state.files.root, btn.dataset.path);
  });
  $("file-list").addEventListener("click", (event) => {
    const del = event.target.closest("[data-del]");
    if (del) {
      event.preventDefault();
      event.stopPropagation();
      if (!confirm("Delete this?")) return;
      const body = new FormData();
      body.set("root", state.files.root);
      body.set("path", del.dataset.del);
      fetch("/api/files/delete", { method: "POST", body }).then((r) => r.json()).then(renderFiles);
      return;
    }
    const open = event.target.closest("[data-open]");
    if (open) {
      event.preventDefault();
      loadFiles(state.files.root, open.dataset.open);
    }
  });
  async function makeFolder() {
    const name = $("mkdir-name").value.trim();
    if (!name || !state.files.root) return;
    const body = new FormData();
    body.set("root", state.files.root);
    body.set("path", state.files.path || "");
    body.set("name", name);
    const res = await fetch("/api/files/mkdir", { method: "POST", body });
    if (!res.ok) {
      $("file-list").innerHTML = `<p class="empty">Could not create that folder.</p>`;
      return;
    }
    $("mkdir-name").value = "";
    renderFiles(await res.json());
  }
  $("mkdir-btn").addEventListener("click", makeFolder);
  $("mkdir-name").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      makeFolder();
    }
  });
  $("upload-input").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const body = new FormData();
    body.set("root", state.files.root);
    body.set("path", state.files.path || "");
    body.set("file", file);
    fetch("/api/files/upload", { method: "POST", body }).then((r) => r.json()).then(renderFiles);
    event.target.value = "";
  });
}

renderVitals(boot.system);
renderFleet(boot.fleet);
renderLibrary(boot.library);
renderRoots();
if (state.files.root) loadFiles(state.files.root, "");
tickClock();
setInterval(tickClock, 1000);
setInterval(refresh, 4000);
watchNav();
bind();
