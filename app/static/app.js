const thread = document.getElementById("thread");
const form = document.getElementById("ask-form");
const questionEl = document.getElementById("question");
const askBtn = document.getElementById("ask-btn");
const ingestBtn = document.getElementById("ingest-btn");
const resetBtn = document.getElementById("reset-btn");
const fileInput = document.getElementById("file-input");
const ingestStatus = document.getElementById("ingest-status");
const fileList = document.getElementById("file-list");
const fileCount = document.getElementById("file-count");
const statusDot = document.querySelector(".dot");
const statusLabel = document.getElementById("status-label");

const STOP = new Set([
  "a", "an", "and", "are", "at", "be", "can", "do", "for", "from", "get", "how",
  "in", "is", "many", "of", "on", "or", "the", "to", "what", "who",
]);

let mode = "hybrid";
let busy = false;
let spaceId = "";
const introHTML = thread.querySelector(".intro")?.outerHTML || "";
const labSpace = document.getElementById("lab-space");

function setBusy(next) {
  busy = next;
  askBtn.disabled = next;
  ingestBtn.disabled = next;
}

document.querySelectorAll(".seg").forEach((btn) => {
  btn.addEventListener("click", () => {
    mode = btn.dataset.mode;
    document.querySelectorAll(".seg").forEach((el) => el.classList.toggle("active", el === btn));
  });
});

function bindChips(root) {
  root.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      questionEl.value = chip.dataset.q;
      ask(chip.dataset.q);
    });
  });
}

bindChips(thread);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function highlight(text, question) {
  const escaped = escapeHtml(text);
  const terms = (question || "")
    .toLowerCase()
    .match(/[a-z0-9]+(?:-[a-z0-9]+)*/g) || [];
  const uniq = [...new Set(terms.filter((t) => t.length > 2 && !STOP.has(t)))].sort(
    (a, b) => b.length - a.length
  );
  let out = escaped;
  for (const term of uniq) {
    const re = new RegExp(`(${term})`, "gi");
    out = out.replace(re, "<mark>$1</mark>");
  }
  return out;
}

function renderAnswer(text) {
  return escapeHtml(text).replace(
    /\[([^\]\n]+\.[a-z0-9]+)\]/gi,
    '<button type="button" class="cite" data-source="$1">[$1]</button>'
  );
}

function bindCites(root) {
  root.querySelectorAll(".cite").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.source;
      let target = null;
      root.querySelectorAll(".source").forEach((el) => {
        const match = el.dataset.file === name;
        el.open = match;
        if (match && !target) target = el;
      });
      target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
}

async function fetchJson(url, options) {
  const headers = { ...(options && options.headers ? options.headers : {}) };
  const m = document.cookie.match(/(?:^|; )docs_csrf=([^;]*)/);
  if (m) headers["X-CSRF-Token"] = decodeURIComponent(m[1]);
  const res = await fetch(url, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function renderFiles(files) {
  fileCount.textContent = String(files.length);
  if (!files.length) {
    fileList.innerHTML = '<li class="empty">Nothing indexed yet.</li>';
    return;
  }
  fileList.innerHTML = files.map((name) => `<li>${escapeHtml(name)}</li>`).join("");
}

async function refreshHealth() {
  try {
    const qs = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : "";
    const docs = spaceId ? await fetchJson(`/api/docs${qs}`) : null;
    const health = await fetchJson("/api/health");
    const ollama = health.ollama;
    const modelReady = health.ollama_model_ready;
    const files = docs ? docs.files : health.indexed_files || [];
    const chunks = docs ? docs.chunk_count : health.indexed_chunks;
    const needs = (docs ? docs.chunk_count === 0 : health.needs_ingest);
    if (needs) {
      statusDot.dataset.state = "warn";
      statusLabel.textContent = "Index empty — ingest the folder";
    } else if (!ollama) {
      statusDot.dataset.state = "warn";
      statusLabel.textContent = `Indexed ${chunks} chunks · Ollama down`;
    } else if (!modelReady) {
      statusDot.dataset.state = "warn";
      statusLabel.textContent = `Indexed ${chunks} chunks · pull ${health.ollama_model}`;
    } else {
      statusDot.dataset.state = "ok";
      statusLabel.textContent = `Indexed ${chunks} chunks · ${health.ollama_model}`;
    }
    renderFiles(files);
  } catch (err) {
    statusDot.dataset.state = "bad";
    statusLabel.textContent = "API unreachable";
  }
}

function appendMessage(role, html, extraClass = "") {
  const wrap = document.createElement("article");
  wrap.className = `msg ${role} ${extraClass}`.trim();
  wrap.innerHTML = html;
  const intro = thread.querySelector(".intro");
  if (intro) intro.remove();
  thread.appendChild(wrap);
  thread.scrollTop = thread.scrollHeight;
  return wrap;
}

function ranksLabel(src) {
  const parts = [];
  if (src.dense_rank) parts.push(`dense #${src.dense_rank}`);
  if (src.bm25_rank) parts.push(`bm25 #${src.bm25_rank}`);
  if (src.fused_score != null) parts.push(`rrf ${src.fused_score.toFixed(4)}`);
  return parts.join(" · ");
}

function renderSources(sources, question) {
  if (!sources.length) return '<p class="hint">No chunks retrieved.</p>';
  return `<div class="sources">${sources
    .map(
      (src, i) => `
      <details class="source" data-file="${escapeHtml(src.source)}"${i === 0 ? " open" : ""}>
        <summary>
          <span class="source-title">${escapeHtml(src.source)}${src.page ? ` · p.${src.page}` : ""}</span>
          <span class="ranks">${escapeHtml(ranksLabel(src))}</span>
        </summary>
        <p>${highlight(src.snippet, question)}</p>
      </details>`
    )
    .join("")}</div>`;
}

function renderCompare(rows, activeMode, question) {
  if (!rows || !rows.length) return "";
  return `<div class="compare">${rows
    .map(
      (row) => `
      <div class="compare-card${row.mode === activeMode ? " active" : ""}">
        <h3>#1 ${escapeHtml(row.mode)}</h3>
        <p>${escapeHtml(row.source || "—")}</p>
        ${row.snippet ? `<p class="compare-snip">${highlight(row.snippet, question)}</p>` : ""}
      </div>`
    )
    .join("")}</div>`;
}

async function ask(rawQuestion) {
  const question = (rawQuestion || "").trim();
  if (!question || busy) return;

  questionEl.value = "";
  appendMessage("user", `<div class="bubble">${escapeHtml(question)}</div>`);
  const pending = appendMessage("assistant", `<div class="bubble">Searching the records…</div>`, "pending");
  setBusy(true);
  try {
    const data = await fetchJson("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode, space_id: spaceId || null }),
    });
    const note = data.generation_error
      ? `<p class="warn-banner">${escapeHtml(data.generation_error)}</p>`
      : "";
    const bits = [data.answer_kind || "answer"];
    if (data.lexical) bits.push("identifier query");
    if (data.total_ms != null) bits.push(`${Math.round(data.total_ms)} ms`);
    pending.classList.remove("pending");
    pending.innerHTML = `
      <div class="bubble">${renderAnswer(data.answer)}</div>
      <p class="meta-line">${escapeHtml(bits.join(" · "))}</p>
      ${note}
      ${renderCompare(data.top_by_mode, data.mode, question)}
      ${renderSources(data.sources || [], question)}
    `;
    bindCites(pending);
  } catch (err) {
    pending.classList.remove("pending");
    pending.innerHTML = `<div class="bubble">${escapeHtml(err.message)}</div>`;
  } finally {
    setBusy(false);
    thread.scrollTop = thread.scrollHeight;
    questionEl.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(questionEl.value);
});

questionEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

resetBtn.addEventListener("click", () => {
  thread.innerHTML = introHTML;
  bindChips(thread);
  questionEl.value = "";
  questionEl.focus();
});

async function runIngest(files) {
  setBusy(true);
  ingestStatus.textContent = "Indexing the docs folder…";
  try {
    const options = { method: "POST" };
    if (files && files.length) {
      const body = new FormData();
      for (const file of files) body.append("files", file);
      options.body = body;
    } else {
      options.headers = { "Content-Type": "application/json" };
      options.body = "{}";
    }
    const qs = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : "";
    const data = await fetchJson(`/api/ingest${qs}`, options);
    ingestStatus.textContent = `Indexed ${data.chunk_count} chunks from ${data.files.length} files.`;
    await refreshHealth();
  } catch (err) {
    ingestStatus.textContent = err.message;
  } finally {
    setBusy(false);
    fileInput.value = "";
  }
}

async function bootLab() {
  try {
    const status = await fetch("/api/auth/status").then((r) => r.json());
    if (status.setup_complete && !status.user) {
      location.href = "/login";
      return;
    }
    if (status.setup_complete && labSpace) {
      const data = await fetchJson("/api/spaces");
      const list = data.spaces || [];
      labSpace.innerHTML = list
        .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
        .join("");
      spaceId = labSpace.value || "";
      labSpace.addEventListener("change", () => {
        spaceId = labSpace.value;
        refreshHealth();
      });
    } else if (labSpace) {
      labSpace.innerHTML = `<option value="">Global demo index</option>`;
    }
  } catch {
    /* lab still works against the global index before setup */
  }
  refreshHealth();
}

ingestBtn.addEventListener("click", () => runIngest());
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) runIngest(fileInput.files);
});

bootLab();
setInterval(refreshHealth, 15000);
