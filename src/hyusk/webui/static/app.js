// Hyusk web UI — chat client + state machine.

const $ = (sel) => document.querySelector(sel);

const state = {
  connected: false,
  activity: "idle", // idle | listening | thinking | speaking | error
  tasks: new Map(), // task_id -> { name, args, status, error }
  currentTaskId: null,
  // Accumulated text per task_id, for streaming rendering.
  partial: new Map(),
  // Recognized browser audio input for mic mode.
  mediaRecorder: null,
  micStream: null,
  micChunks: [],
};

const messagesEl = $("#messages");
const inputEl = $("#input");
const formEl = $("#form");
const sendBtn = $("#send");
const micBtn = $("#mic-btn");
const toolsEl = $("#tools");
const versionEl = $("#version");

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]
  ));
}

function appendMessage(role, text, meta) {
  const div = document.createElement("div");
  div.className = "message " + role;
  div.innerHTML = escapeHtml(text);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function setActivity(next) {
  if (state.activity === next) return;
  state.activity = next;
  if (window.__hyuskScene && window.__hyuskScene.setState) {
    window.__hyuskScene.setState(next);
  }
}

function renderTools() {
  const items = [...state.tasks.values()];
  if (items.length === 0) {
    toolsEl.innerHTML = '<p class="empty">No tools running.</p>';
    return;
  }
  toolsEl.innerHTML = items
    .map((t) => {
      const cls = t.status === "error" ? "tool error" :
                 t.status === "done" ? "tool done" : "tool";
      const meta = t.error ? `error: ${escapeHtml(t.error)}` :
        Object.keys(t.args || {}).length
          ? Object.entries(t.args)
              .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
              .join("\n")
          : "";
      return `<div class="${cls}">
        <div class="name">${escapeHtml(t.name || "?")}</div>
        ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}
      </div>`;
    })
    .join("");
}

let ws = null;
function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/direct`);
  ws.addEventListener("open", () => {
    state.connected = true;
    $("#status").classList.add("connected");
    $("#status-text").textContent = "connected";
    setActivity("idle");
  });
  ws.addEventListener("close", () => {
    state.connected = false;
    $("#status").classList.remove("connected");
    $("#status-text").textContent = "disconnected — retrying…";
    setActivity("error");
    setTimeout(connect, 2000);
  });
  ws.addEventListener("error", () => {
    /* the close handler will run */
  });
  ws.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleServerEvent(msg);
  });
}

function handleServerEvent(msg) {
  const mtype = msg.type;
  if (mtype === "submitted") {
    state.currentTaskId = msg.task_id;
    state.partial.set(msg.task_id, "");
    setActivity("thinking");
  } else if (mtype === "event") {
    const ev = msg.event;
    const data = msg.data || {};
    const tid = msg.task_id;
    if (ev === "agent.text") {
      // Stream into the current message bubble.
      if (!state.partial.has(tid)) state.partial.set(tid, "");
      if (data.delta) {
        state.partial.set(tid, state.partial.get(tid) + (data.text || ""));
        setActivity("speaking");
      }
      renderPartial(tid);
    } else if (ev === "tool.started") {
      state.tasks.set(tid, {
        name: data.name,
        args: data.arguments || {},
        status: "running",
        startedAt: Date.now(),
      });
      renderTools();
    } else if (ev === "tool.completed") {
      const t = state.tasks.get(tid) || {};
      t.status = data.error ? "error" : "done";
      t.error = data.error || null;
      t.duration = data.duration_ms;
      state.tasks.set(tid, t);
      renderTools();
    } else if (ev === "agent.completed") {
      setActivity("idle");
      state.currentTaskId = null;
    }
  } else if (mtype === "task_done") {
    setActivity("idle");
    state.currentTaskId = null;
    const t = msg.task;
    appendMessage(
      "system",
      `[task ${t.task_id.slice(0, 8)} done — ${t.state || "done"} — ` +
      `${t.iterations} iter — ${t.cancelled ? "cancelled" : "ok"}` +
      `${t.error ? " — error: " + t.error : ""}]`
    );
  } else if (mtype === "error") {
    appendMessage("system", "error: " + (msg.message || "unknown"));
    setActivity("error");
  }
}

let partialBubbles = new Map();
function renderPartial(taskId) {
  let bubble = partialBubbles.get(taskId);
  if (!bubble) {
    bubble = document.createElement("div");
    bubble.className = "message assistant";
    messagesEl.appendChild(bubble);
    partialBubbles.set(taskId, bubble);
  }
  bubble.textContent = state.partial.get(taskId) || "";
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || !state.connected) return;
  inputEl.value = "";
  appendMessage("user", text);
  if (ws.readyState === WebSocket.OPEN) {
    setActivity("thinking");
    ws.send(JSON.stringify({ type: "submit", text }));
  }
});

// Mic button: browser microphone → raw audio → base64 over WS.
// Server is responsible for STT. (Optional; server may not support
// this in all configurations; we silently fall back.)
micBtn.addEventListener("click", async () => {
  if (state.micStream) {
    // stop
    state.mediaRecorder.stop();
    state.micStream.getTracks().forEach((t) => t.stop());
    state.micStream = null;
    state.mediaRecorder = null;
    micBtn.classList.remove("recording");
    setActivity("idle");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.micStream = stream;
    const rec = new MediaRecorder(stream, { mimeType: "audio/webm" });
    state.micChunks = [];
    rec.addEventListener("dataavailable", (ev) => {
      if (ev.data && ev.data.size > 0) state.micChunks.push(ev.data);
    });
    rec.addEventListener("stop", async () => {
      const blob = new Blob(state.micChunks, { type: "audio/webm" });
      state.micChunks = [];
      const buf = await blob.arrayBuffer();
      const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "submit_audio", mime: "audio/webm", b64 }));
      }
    });
    rec.start();
    state.mediaRecorder = rec;
    micBtn.classList.add("recording");
    setActivity("listening");
  } catch (err) {
    appendMessage("system", "mic error: " + err.message);
  }
});

connect();
