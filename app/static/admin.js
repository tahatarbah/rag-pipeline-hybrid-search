function csrfToken() {
  const m = document.cookie.match(/(?:^|; )docs_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Sign in");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : res.statusText);
  return data;
}

function escapeHtml(v) {
  return String(v).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function selectedSpace() {
  return document.getElementById("upload-space").value;
}

async function pollJob(spaceId) {
  const statusEl = document.getElementById("job-status");
  const bar = document.getElementById("ingest-bar");
  const fill = document.getElementById("ingest-fill");
  bar.hidden = false;
  for (let i = 0; i < 50; i += 1) {
    const data = await api(`/api/spaces/${spaceId}/ingest`);
    const job = data.job;
    if (!job) {
      statusEl.textContent = "No ingest job yet.";
      return;
    }
    const pct = Number(job.percent || 0);
    fill.style.width = `${pct}%`;
    statusEl.textContent = `${job.status}: ${job.progress || ""}`;
    if (job.status === "done" || job.status === "error") {
      fill.style.width = job.status === "done" ? "100%" : "0%";
      if (job.error) statusEl.textContent = `error: ${job.error}`;
      await load();
      return;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
}

async function loadMembers(spaceId) {
  if (!spaceId) {
    document.getElementById("members").innerHTML = "";
    return;
  }
  try {
    const data = await api(`/api/spaces/${spaceId}/members`);
    document.getElementById("members").innerHTML = `<ul>${(data.members || [])
      .map(
        (m) =>
          `<li>${escapeHtml(m.email)} · ${escapeHtml(m.role)}
          <button type="button" data-kick="${escapeHtml(m.email)}">remove</button></li>`
      )
      .join("")}</ul>`;
    document.querySelectorAll("[data-kick]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/spaces/${spaceId}/members/${encodeURIComponent(btn.dataset.kick)}`, {
          method: "DELETE",
        });
        loadMembers(spaceId);
      });
    });
  } catch {
    document.getElementById("members").innerHTML = "";
  }
}

async function load() {
  const opsRes = await fetch("/api/admin/ops");
  if (opsRes.status === 401) {
    location.href = "/login";
    return;
  }
  const isAdmin = opsRes.ok;
  if (isAdmin) {
    const ops = await opsRes.json();
    const h = ops.health;
    document.getElementById("health").innerHTML = `
    <p>Ollama: ${h.ollama ? "up" : "down"} · Disk free: ${h.disk_free_mb ?? "?"} MB</p>
    <p>Embeddings: ${escapeHtml(h.embedding_model || "hash")}</p>
    <p>Spaces: ${(h.spaces || []).map((s) => `${escapeHtml(s.name)} (${s.chunk_count} chunks)`).join(" · ") || "none"}</p>
    <p class="hint">Watch <code>/health</code> and <code>/metrics</code> on this host. Nothing phones home.</p>
  `;
    const u = ops.usage;
    document.getElementById("usage").innerHTML = `
    <p><strong>${u.calls}</strong> calls · <strong>${u.prompt_tokens + u.completion_tokens}</strong> tokens · est. $${Number(u.estimated_cost || 0).toFixed(4)}</p>
    <ul>${(u.by_model || [])
      .map((m) => `<li>${escapeHtml(m.model_id || "—")}: ${m.tokens} tokens, ${m.calls} calls</li>`)
      .join("")}</ul>
  `;
    const models = await api("/api/admin/models");
    document.getElementById("models").innerHTML = `<ul>${(models.models || [])
      .map(
        (m) =>
          `<li>${escapeHtml(m.display_name)} · ${m.provider}/${escapeHtml(m.model_id)} · ${m.tier} · ${m.ready ? "ready" : m.status}
        <button type="button" data-toggle="${m.id}" data-on="${m.enabled ? 0 : 1}">${m.enabled ? "Disable" : "Enable"}</button></li>`
      )
      .join("")}</ul>`;
    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/admin/models/${btn.dataset.toggle}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: btn.dataset.on === "1" }),
        });
        load();
      });
    });
    const users = await api("/api/admin/users");
    document.getElementById("users").innerHTML = `<ul>${(users.users || [])
      .map((p) => `<li>${escapeHtml(p.email)} · ${p.tier} · ${p.org_role}</li>`)
      .join("")}</ul>`;
  } else {
    document.getElementById("health").innerHTML =
      "<p>Space editor: upload and reindex below. Org-wide health is for organization admins.</p>";
    document.getElementById("usage").innerHTML = "<p class='hint'>Token usage is visible to organization admins.</p>";
    document.getElementById("model-form").hidden = true;
    document.getElementById("user-form").hidden = true;
  }
  const spaces = await api("/api/spaces");
  const list = spaces.spaces || [];
  document.getElementById("spaces").innerHTML = `<ul>${list
    .map(
      (s) =>
        `<li>${escapeHtml(s.name)} · ${s.chunk_count} chunks · ${(s.files || [])
          .map(
            (f) =>
              `${escapeHtml(f)} <button type="button" data-del="${s.id}" data-file="${escapeHtml(f)}">remove</button>`
          )
          .join(", ")}</li>`
    )
    .join("")}</ul>`;
  document.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/spaces/${btn.dataset.del}/documents/${encodeURIComponent(btn.dataset.file)}`, {
        method: "DELETE",
      });
      pollJob(btn.dataset.del);
    });
  });
  const prev = selectedSpace();
  const opts = list.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("");
  document.getElementById("upload-space").innerHTML = opts;
  document.getElementById("member-space").innerHTML = opts;
  if (prev) document.getElementById("upload-space").value = prev;
  const space = selectedSpace();
  document.getElementById("inbox-hint").textContent = space
    ? `Watch folder: drop files into data/spaces/${space}/inbox/ on this server.`
    : "";
  await loadMembers(document.getElementById("member-space").value);
}

document.getElementById("upload-space").addEventListener("change", () => {
  const space = selectedSpace();
  document.getElementById("inbox-hint").textContent = space
    ? `Watch folder: drop files into data/spaces/${space}/inbox/ on this server.`
    : "";
});
document.getElementById("member-space").addEventListener("change", () => {
  loadMembers(document.getElementById("member-space").value);
});

document.getElementById("model-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  await api("/api/admin/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      display_name: f.display_name.value,
      provider: f.provider.value,
      model_id: f.model_id.value,
      tier: f.tier.value,
      api_base: f.api_base.value || null,
      api_key: f.api_key.value || null,
    }),
  });
  f.reset();
  load();
});

document.getElementById("user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  await api("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: f.name.value,
      email: f.email.value,
      password: f.password.value,
      tier: f.tier.value,
    }),
  });
  f.reset();
  load();
});

document.getElementById("space-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/spaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: e.target.name.value }),
  });
  e.target.reset();
  load();
});

document.getElementById("member-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const space = document.getElementById("member-space").value;
  await api(`/api/spaces/${space}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: e.target.email.value, role: e.target.role.value }),
  });
  e.target.reset();
  loadMembers(space);
});

async function uploadFiles(files) {
  const space = selectedSpace();
  if (!space || !files.length) return;
  const body = new FormData();
  for (const file of files) body.append("files", file);
  const headers = {};
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  const res = await fetch(`/api/spaces/${space}/upload`, { method: "POST", headers, body });
  const data = await res.json();
  document.getElementById("job-status").textContent = data.job_id
    ? `Ingest queued (${data.job_id})`
    : data.detail || "Uploaded";
  if (data.job_id) pollJob(space);
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const files = document.getElementById("file-input").files;
  await uploadFiles(files);
});

const dropzone = document.getElementById("dropzone");
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("over");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("over"));
dropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  dropzone.classList.remove("over");
  await uploadFiles(e.dataTransfer.files);
});

document.getElementById("demo-btn").addEventListener("click", async () => {
  const space = selectedSpace();
  if (!space) return;
  await api(`/api/spaces/${space}/demo`, { method: "POST" });
  pollJob(space);
});

document.getElementById("reindex-btn").addEventListener("click", async () => {
  const space = selectedSpace();
  if (!space) return;
  await api(`/api/spaces/${space}/ingest`, { method: "POST" });
  pollJob(space);
});

load();
