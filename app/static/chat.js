function csrfToken() {
  const m = document.cookie.match(/(?:^|; )docs_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Sign in required");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : res.statusText);
  return data;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderAnswer(text) {
  return escapeHtml(text).replace(
    /\[([^\]\n]+\.[a-z0-9]+)\]/gi,
    '<button type="button" class="cite" data-source="$1">[$1]</button>'
  );
}

const spaceSelect = document.getElementById("space-select");
const modelSelect = document.getElementById("model-select");
const threadList = document.getElementById("thread-list");
const messagesEl = document.getElementById("messages");
const input = document.getElementById("input");
const EMPTY_HTML = document.getElementById("empty")?.outerHTML || "";
let currentThread = null;
let spaces = [];

function bindChips(root) {
  root.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.q;
      document.getElementById("composer").requestSubmit();
    });
  });
}

function bindCites(root) {
  root.querySelectorAll(".cite").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.source;
      root.querySelectorAll(".source").forEach((el) => {
        const on = el.dataset.file === name;
        el.classList.toggle("open", on);
        if (on) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  });
}

async function boot() {
  const status = await fetch("/api/auth/status").then((r) => r.json());
  if (!status.setup_complete) {
    location.href = "/setup";
    return;
  }
  if (!status.user) {
    location.href = "/login";
    return;
  }
  document.getElementById("org-name") && (document.getElementById("org-name").textContent = status.org_name || "Internal");
  const name = status.user.name || status.user.email;
  const whoName = document.getElementById("who-name");
  if (whoName) whoName.textContent = name;
  document.getElementById("who").textContent = status.user.email;
  const av = document.getElementById("who-avatar");
  if (av) av.textContent = (name.trim()[0] || "A").toUpperCase();
  const spaceData = await api("/api/spaces");
  spaces = spaceData.spaces || [];
  const canManage =
    status.user.org_role === "org_admin" ||
    spaces.some((s) => s.role === "editor" || s.role === "admin");
  if (status.user.org_role === "org_admin") {
    document.getElementById("admin-link").hidden = false;
  }
  if (canManage) document.getElementById("lab-link").hidden = false;
  if (!spaces.length) {
    document.getElementById("empty")?.insertAdjacentHTML(
      "beforeend",
      "<p class='warn-banner'>You are not in any space yet. Ask an admin to add you.</p>"
    );
  }
  spaceSelect.innerHTML =
    `<option value="">All my spaces</option>` +
    spaces.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("");
  const models = await api("/api/chat/models");
  modelSelect.innerHTML = (models.models || [])
    .map(
      (m) =>
        `<option value="${m.id}">${escapeHtml(m.display_name)} (${m.tier})</option>`
    )
    .join("");
  bindChips(messagesEl);
  await refreshThreads();
}

async function refreshThreads() {
  const data = await api("/api/chat/threads");
  threadList.innerHTML = (data.threads || [])
    .map(
      (t) =>
        `<li>
          <button type="button" data-id="${t.id}" class="${t.id === currentThread ? "active" : ""}">${escapeHtml(t.title || "Chat")}</button>
          <button type="button" class="thread-del" data-del="${t.id}" aria-label="Delete chat">×</button>
        </li>`
    )
    .join("");
  threadList.querySelectorAll("button[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => openThread(btn.dataset.id));
  });
  threadList.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api(`/api/chat/threads/${btn.dataset.del}`, { method: "DELETE" });
      if (currentThread === btn.dataset.del) {
        currentThread = null;
        messagesEl.innerHTML = EMPTY_HTML;
        bindChips(messagesEl);
      }
      await refreshThreads();
    });
  });
}

async function openThread(id) {
  currentThread = id;
  const data = await api(`/api/chat/threads/${id}`);
  messagesEl.innerHTML = "";
  for (const msg of data.messages || []) {
    const clean = String(msg.content || "").replace(/\n<!--[\s\S]*-->$/, "");
    const meta = String(msg.content || "").match(/<!--([\s\S]*)-->$/);
    let sources = [];
    if (msg.role === "assistant" && meta) {
      try {
        sources = JSON.parse(meta[1]).sources || [];
      } catch {
        sources = [];
      }
    }
    appendBubble(msg.role, clean, sources);
  }
  if (!(data.messages || []).length) {
    messagesEl.innerHTML = EMPTY_HTML;
    bindChips(messagesEl);
  }
  await refreshThreads();
}

function appendBubble(role, text, sources = []) {
  document.getElementById("empty")?.remove();
  const art = document.createElement("article");
  art.className = `msg ${role}`;
  const src = sources.length
    ? `<div class="sources">${sources
        .map(
          (s) =>
            `<button type="button" class="source" data-file="${escapeHtml(s.source)}" title="${escapeHtml(s.snippet || "")}">
              <span class="source-title">${escapeHtml(s.source)}</span>
              <span class="source-snip">${escapeHtml(s.snippet || "")}</span>
            </button>`
        )
        .join("")}</div>`
    : "";
  art.innerHTML = `<div class="bubble">${role === "assistant" ? renderAnswer(text) : escapeHtml(text)}</div>${src}`;
  messagesEl.appendChild(art);
  art.querySelectorAll(".source").forEach((btn) => {
    btn.addEventListener("click", () => btn.classList.toggle("open"));
  });
  bindCites(art);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return art;
}

async function readSse(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}

document.getElementById("new-chat").addEventListener("click", async () => {
  const space_id = spaceSelect.value || null;
  const t = await api("/api/chat/threads", {
    method: "POST",
    body: JSON.stringify({ space_id }),
  });
  currentThread = t.id;
  messagesEl.innerHTML = EMPTY_HTML;
  bindChips(messagesEl);
  await refreshThreads();
});

document.getElementById("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = input.value.trim();
  if (!content) return;
  if (!currentThread) {
    const t = await api("/api/chat/threads", {
      method: "POST",
      body: JSON.stringify({ space_id: spaceSelect.value || null }),
    });
    currentThread = t.id;
  }
  appendBubble("user", content);
  input.value = "";
  input.style.height = "auto";
  const pending = document.createElement("article");
  pending.className = "msg assistant pending";
  pending.innerHTML = `<div class="bubble">Searching the records<span class="cursor">▍</span></div><div class="sources"></div>`;
  messagesEl.appendChild(pending);
  const bubble = pending.querySelector(".bubble");
  let text = "";
  try {
    const headers = { "Content-Type": "application/json" };
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
    const res = await fetch(`/api/chat/threads/${currentThread}/messages/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        content,
        model_id: modelSelect.value || null,
        space_id: spaceSelect.value || null,
      }),
    });
    if (res.status === 401) {
      location.href = "/login";
      return;
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : res.statusText);
    }
    let sources = [];
    await readSse(res, (ev) => {
      if (ev.status === "generating") {
        bubble.innerHTML = `Writing<span class="cursor">▍</span>`;
        if (ev.sources) sources = ev.sources;
      }
      if (ev.delta) {
        text += ev.delta;
        pending.classList.remove("pending");
        bubble.innerHTML = `${renderAnswer(text)}<span class="cursor">▍</span>`;
        bindCites(pending);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
      if (ev.done) sources = ev.sources || sources;
    });
    pending.remove();
    appendBubble("assistant", text, sources);
    await refreshThreads();
  } catch (err) {
    pending.classList.remove("pending");
    bubble.textContent = err.message;
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    document.getElementById("composer").requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

const sidebar = document.getElementById("sidebar");
const toggle = document.getElementById("sidebar-toggle");
const scrim = document.getElementById("scrim");
function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  if (scrim) scrim.hidden = true;
}
toggle?.addEventListener("click", () => {
  document.body.classList.toggle("sidebar-open");
  if (scrim) scrim.hidden = !document.body.classList.contains("sidebar-open");
});
scrim?.addEventListener("click", closeSidebar);

document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.href = "/login";
});

boot();
