"use strict";

// Required on state-changing requests; see web/security.py. A cross-origin
// form POST cannot set it, which is what makes it a CSRF guard.
const CSRF_HEADER = "X-Meshgate";
const POLL_MS = 2000;

const state = {
  selectedNode: null,
  logCursor: 0,
  pluginsEtag: null,
  transcriptsEnabled: false,
};

function el(id) {
  return document.getElementById(id);
}

function text(value) {
  // Everything from the API is rendered as text, never HTML: message content
  // and node names come from the mesh and are not trusted.
  return document.createTextNode(String(value));
}

function showError(message) {
  const banner = el("error-banner");
  if (message) {
    banner.textContent = message;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

async function api(path, options = {}) {
  const opts = { headers: {}, ...options };
  if (opts.method && opts.method !== "GET") {
    opts.headers[CSRF_HEADER] = "1";
    opts.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, opts);
  if (response.status === 304) return null;
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch (e) {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return response.json();
}

function pill(id, label, good) {
  const node = el(id);
  node.textContent = label;
  node.classList.toggle("ok", good === true);
  node.classList.toggle("bad", good === false);
}

async function refreshStatus() {
  const s = await api("/api/status");
  state.transcriptsEnabled = s.transcripts_enabled;

  pill("pill-running", s.running ? "running" : "stopped", s.running);
  pill(
    "pill-transport",
    s.transport_connected ? "radio connected" : "radio offline",
    s.transport_connected
  );
  pill("pill-sessions", `${s.active_sessions} sessions`);
  pill(
    "pill-plugins",
    s.disabled_plugins
      ? `${s.enabled_plugins} plugins (${s.disabled_plugins} off)`
      : `${s.enabled_plugins} plugins`
  );
}

async function togglePlugin(name, enable) {
  const action = enable ? "enable" : "disable";
  try {
    await api(`/api/plugins/${encodeURIComponent(name)}/${action}`, { method: "POST" });
    state.pluginsEtag = null; // force a re-render
    await refreshPlugins();
    await refreshStatus();
    showError("");
  } catch (err) {
    showError(`Could not ${action} ${name}: ${err.message}`);
  }
}

async function refreshPlugins() {
  const headers = {};
  if (state.pluginsEtag) headers["If-None-Match"] = state.pluginsEtag;

  const response = await fetch("/api/plugins", { headers });
  if (response.status === 304) return;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  state.pluginsEtag = response.headers.get("ETag");
  const plugins = await response.json();

  const body = el("plugins-body");
  body.replaceChildren();

  if (!plugins.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text("No plugins registered."));
    body.appendChild(p);
    return;
  }

  const table = document.createElement("table");
  const head = table.insertRow();
  ["#", "Name", "State", ""].forEach((label) => {
    const th = document.createElement("th");
    th.appendChild(text(label));
    head.appendChild(th);
  });

  for (const plugin of plugins) {
    const row = table.insertRow();
    row.insertCell().appendChild(text(plugin.menu_number));

    const nameCell = row.insertCell();
    nameCell.appendChild(text(plugin.name));

    const stateCell = row.insertCell();
    const badge = document.createElement("span");
    badge.className = `badge ${plugin.enabled ? "on" : "off"}`;
    badge.appendChild(text(plugin.enabled ? "enabled" : "disabled"));
    stateCell.appendChild(badge);

    const actionCell = row.insertCell();
    const button = document.createElement("button");
    button.appendChild(text(plugin.enabled ? "Disable" : "Enable"));
    if (!plugin.enabled) button.classList.add("danger");
    button.addEventListener("click", () => togglePlugin(plugin.name, !plugin.enabled));
    actionCell.appendChild(button);
  }

  body.appendChild(table);
}

async function endSession(nodeId) {
  try {
    await api(`/api/sessions/${encodeURIComponent(nodeId)}`, { method: "DELETE" });
    if (state.selectedNode === nodeId) state.selectedNode = null;
    await refreshSessions();
    await refreshDetail();
    await refreshStatus();
    showError("");
  } catch (err) {
    showError(`Could not end session: ${err.message}`);
  }
}

async function refreshSessions() {
  const sessions = await api("/api/sessions");
  const body = el("sessions-body");
  body.replaceChildren();

  if (!sessions.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text("No active sessions."));
    body.appendChild(p);
    return;
  }

  const table = document.createElement("table");
  const head = table.insertRow();
  ["Node", "Plugin", "Idle", ""].forEach((label) => {
    const th = document.createElement("th");
    th.appendChild(text(label));
    head.appendChild(th);
  });

  for (const session of sessions) {
    const row = table.insertRow();
    row.className = "clickable";
    if (session.node_id === state.selectedNode) row.classList.add("selected");
    row.addEventListener("click", (event) => {
      if (event.target.tagName === "BUTTON") return;
      state.selectedNode = session.node_id;
      refreshSessions().catch(() => {});
      refreshDetail().catch(() => {});
    });

    row.insertCell().appendChild(text(session.node_id));
    row.insertCell().appendChild(text(session.active_plugin || "— menu —"));
    row.insertCell().appendChild(text(`${session.idle_seconds}s`));

    const actionCell = row.insertCell();
    const button = document.createElement("button");
    button.className = "danger";
    button.appendChild(text("End"));
    button.addEventListener("click", () => endSession(session.node_id));
    actionCell.appendChild(button);
  }

  body.appendChild(table);
}

function renderTranscript(container, messages) {
  const heading = document.createElement("h2");
  heading.style.marginTop = "16px";
  heading.appendChild(text("Chat transcript"));
  container.appendChild(heading);

  if (!state.transcriptsEnabled) {
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(
      text("Recording is disabled. Set web.transcript_enabled to capture messages.")
    );
    container.appendChild(p);
    return;
  }

  if (!messages || !messages.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text("Nothing recorded for this node yet."));
    container.appendChild(p);
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "transcript";
  for (const message of messages) {
    const row = document.createElement("div");
    row.className = `msg-row ${message.direction}`;

    const who = document.createElement("span");
    who.className = "who";
    who.appendChild(text(message.direction === "inbound" ? "node →" : "← gateway"));
    row.appendChild(who);

    const bodyEl = document.createElement("div");
    bodyEl.className = "body";
    bodyEl.appendChild(text(message.text));
    row.appendChild(bodyEl);

    wrap.appendChild(row);
  }
  container.appendChild(wrap);
}

async function refreshDetail() {
  const body = el("detail-body");
  const label = el("detail-node");

  if (!state.selectedNode) {
    label.textContent = "";
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text("Select a session to see its state and transcript."));
    body.appendChild(p);
    return;
  }

  label.textContent = state.selectedNode;

  let detail;
  try {
    detail = await api(`/api/sessions/${encodeURIComponent(state.selectedNode)}`);
  } catch (err) {
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text(`Session no longer available (${err.message}).`));
    body.appendChild(p);
    return;
  }

  let messages = [];
  if (state.transcriptsEnabled) {
    try {
      const transcript = await api(
        `/api/sessions/${encodeURIComponent(state.selectedNode)}/transcript`
      );
      messages = transcript.messages;
    } catch (err) {
      messages = [];
    }
  }

  body.replaceChildren();

  const meta = document.createElement("p");
  meta.className = "muted";
  meta.appendChild(
    text(
      `${detail.active_plugin || "at menu"} · idle ${detail.idle_seconds}s · ` +
        `last active ${new Date(detail.last_activity).toLocaleTimeString()}`
    )
  );
  body.appendChild(meta);

  const stateHeading = document.createElement("h2");
  stateHeading.appendChild(text("Plugin state"));
  body.appendChild(stateHeading);

  const pre = document.createElement("pre");
  const keys = Object.keys(detail.plugin_state || {});
  pre.appendChild(text(keys.length ? JSON.stringify(detail.plugin_state, null, 2) : "{}"));
  body.appendChild(pre);

  renderTranscript(body, messages);
}

async function refreshLogs() {
  const data = await api(`/api/logs?since=${state.logCursor}`);
  const body = el("logs-body");

  if (!data.available) {
    body.replaceChildren();
    const p = document.createElement("p");
    p.className = "muted";
    p.appendChild(text("Log retention is not enabled."));
    body.appendChild(p);
    return;
  }

  if (state.logCursor === 0) body.replaceChildren();

  for (const record of data.records) {
    const line = document.createElement("div");
    line.className = "log-line";

    const ts = document.createElement("span");
    ts.className = "ts";
    ts.appendChild(text(new Date(record.timestamp).toLocaleTimeString()));
    line.appendChild(ts);

    const lvl = document.createElement("span");
    lvl.className = `lvl lvl-${record.level}`;
    lvl.appendChild(text(record.level));
    line.appendChild(lvl);

    const msg = document.createElement("span");
    msg.className = "msg";
    msg.appendChild(text(record.message));
    line.appendChild(msg);

    body.appendChild(line);
  }

  state.logCursor = data.latest_seq;

  if (el("log-follow").checked && data.records.length) {
    body.scrollTop = body.scrollHeight;
  }
}

async function tick() {
  try {
    await refreshStatus();
    await Promise.all([refreshPlugins(), refreshSessions(), refreshLogs()]);
    await refreshDetail();
    showError("");
    el("last-update").textContent = `updated ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    showError(`Update failed: ${err.message}`);
  }
}

tick();
setInterval(tick, POLL_MS);
