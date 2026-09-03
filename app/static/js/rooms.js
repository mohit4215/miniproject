import { api, wsUrl } from "./api.js";
import { fmtClock, toast } from "./ui.js";

const $ = (s) => document.querySelector(s);
let ws = null;
let room = null;
let tickHandle = null;
let phase = "idle";
let endsAt = null;
let remaining = null;
let durSec = 0;
let me = null;
let totalDurSec = 0; // for ring progress

export function initRooms() {
  $("#create-room").onclick = createRoom;
  $("#join-code-btn").onclick = () => joinRoom($("#join-code").value.trim().toUpperCase());
  $("#join-code").addEventListener("keydown", e => { if (e.key === "Enter") joinRoom($("#join-code").value.trim().toUpperCase()); });
  $("#leave-room").onclick = leaveRoom;
  $("#btn-start").onclick = () => send({ type: "start", duration_min: +$("#sess-min").value || 25 });
  $("#btn-pause").onclick = () => send({ type: "pause" });
  $("#btn-resume").onclick = () => send({ type: "resume" });
  $("#btn-finish").onclick = () => send({ type: "finish_early" });
  $("#btn-reset").onclick = () => send({ type: "reset" });
  $("#chat-send").onclick = sendChat;
  $("#chat-input").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

  const refreshBtn = $("#public-refresh");
  if (refreshBtn) refreshBtn.onclick = loadPublic;

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && phase === "running") send({ type: "violation" }, true);
    if (!document.hidden && $("#focus-overlay").classList.contains("show")) {
      fireNotification();
    }
  });
  window.addEventListener("blur", () => {
    if (phase === "running") setTimeout(() => {
      if (document.hidden || !document.hasFocus()) send({ type: "violation" }, true);
    }, 800);
  });
  $("#overlay-back").onclick = () => $("#focus-overlay").classList.remove("show");
}

function sendChat() {
  const t = $("#chat-input").value.trim();
  if (!t) return;
  send({ type: "chat", text: t });
  $("#chat-input").value = "";
}

async function createRoom() {
  const btn = $("#create-room");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Creating…';
  try {
    const r = await api("POST", "/api/rooms", {
      name: $("#room-name").value.trim() || `Study room`,
      duration_default: +$("#room-dur").value || 25,
      is_public: $("#room-public").checked,
    });
    toast(`Room created — code ${r.code}`, "good");
    await joinRoom(r.code);
    loadPublic();
  } catch (e) {
    toast(e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg> Create room`;
  }
}

export async function joinRoom(code) {
  if (!code) return;
  leaveRoom(true);
  try {
    const meta = await api("GET", `/api/rooms/${code}`);
    room = meta;
    const url = await wsUrl(code);
    ws = new WebSocket(url);
    ws.onmessage = (ev) => handle(JSON.parse(ev.data));
    ws.onclose = (ev) => {
      if (room && ev.code !== 1000) toast("Disconnected from room", "bad");
    };
    $("#rooms-lobby").classList.add("hidden");
    $("#room-active").classList.remove("hidden");
    $("#room-code-label").textContent = `Room ${meta.code}`;
    $("#room-title").textContent = meta.name;
    $("#sess-min").value = meta.duration_default || 25;
    totalDurSec = (meta.duration_default || 25) * 60;
    setTimerIdle(totalDurSec);
    $("#host-controls-note").textContent = "";
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  } catch (e) {
    toast(`Could not join room: ${e.message}`, "bad");
  }
}

function leaveRoom(silent) {
  try {
    if (ws) {
      const sock = ws;
      ws = null;
      sock.onclose = null;
      try { if (sock.readyState <= 1) sock.close(1000); } catch {}
    }
  } finally {
    room = null; phase = "idle";
    clearInterval(tickHandle);
    $("#focus-overlay").classList.remove("show");
    if (!silent) {
      $("#rooms-lobby").classList.remove("hidden");
      $("#room-active").classList.add("hidden");
      setStatus("Ready", "idle");
    }
    loadPublic();
  }
}

function send(obj, quietFail) {
  if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; }
  if (!quietFail) toast("Not connected to a room", "bad");
  return false;
}

function renderMembers(members, violations = {}) {
  const ul = $("#member-list");
  ul.innerHTML = "";
  members.forEach(m => {
    const v = violations[m.user_id] || 0;
    const isHost = m.user_id === room?.host_id;
    const isMe = me && m.user_id === me.user_id;
    const li = document.createElement("li");
    li.innerHTML = `
      <span>
        <span style="font-weight:${isMe ? '700' : '500'};color:${isMe ? 'var(--text)' : 'var(--text-dim)'}">
          ${escapeHtml(m.display_name)}${isMe ? ' <span style="color:var(--primary-light);font-size:10px">(you)</span>' : ''}
          ${isHost ? '<span class="tag-host">HOST</span>' : ''}
        </span>
      </span>
      <span class="pill ${v === 0 ? 'ok' : v < 3 ? 'warn' : 'bad'}">${v} slip${v !== 1 ? 's' : ''}</span>`;
    ul.appendChild(li);
  });
  const online = $("#online-count");
  if (online) online.textContent = `${members.length} online`;
}

function setStatus(text, cls) {
  const el = $("#timer-status");
  if (!el) return;
  el.className = `timer-status ${cls || ""}`;
  $("#timer-status-txt").textContent = text;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ─── Timer ring ───────────────────────────────────────────────────────────────
const RING_CIRCUMFERENCE = 2 * Math.PI * 45; // r=45

function setRingProgress(fraction, ph) {
  const ring = $("#timer-ring");
  if (!ring) return;
  ring.setAttribute("class", `timer-ring-fg ${ph}`);
  const offset = RING_CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, fraction)));
  ring.style.strokeDashoffset = offset;
}

function setTimerDisplay(secLeft, ph) {
  const el = $("#big-timer");
  el.textContent = fmtClock(secLeft);
  el.className = `timer ${ph}`;
  const frac = totalDurSec > 0 ? secLeft / totalDurSec : 0;
  setRingProgress(frac, ph);
}

function setTimerIdle(sec) {
  phase = "idle"; endsAt = null;
  clearInterval(tickHandle);
  const s = sec || (Number($("#sess-min").value) * 60 || 1500);
  setTimerDisplay(s, "idle");
  setStatus("Ready", "idle");
}

function startTicking(serverEndsAt, serverRemaining) {
  clearInterval(tickHandle);
  const end = serverRemaining != null
    ? Date.now() / 1000 + serverRemaining
    : serverEndsAt;
  endsAt = end;
  tickHandle = setInterval(() => {
    const left = Math.max(0, endsAt - Date.now() / 1000);
    setTimerDisplay(left, phase);
    if (left <= 0) clearInterval(tickHandle);
  }, 250);
}

function handle(msg) {
  switch (msg.type) {
    case "room_state": {
      me = msg.you;
      room.host_id = msg.host_id;
      renderMembers(msg.members, msg.violations);
      phase = msg.phase;
      if (msg.duration_sec) totalDurSec = msg.duration_sec;
      if (msg.phase === "running") {
        startTicking(msg.ends_at);
        setStatus("Focusing", "running");
        setHostControls();
      } else if (msg.phase === "paused") {
        setTimerDisplay(msg.remaining, "paused");
        setStatus("Paused", "paused");
      } else {
        setTimerIdle(msg.duration_sec || (Number($("#sess-min").value) * 60));
      }
      setHostControls();
      break;
    }

    case "presence":
      renderMembers(msg.members);
      break;

    case "timer_started":
      phase = "running";
      totalDurSec = msg.duration_sec;
      startTicking(msg.ends_at);
      setStatus("Focusing", "running");
      $("#results-box").classList.add("hidden");
      toast(`${msg.started_by} started a ${Math.round(msg.duration_sec / 60)}-min session. Stay here! 🎯`, "");
      setHostControls();
      break;

    case "timer_paused":
      phase = "paused";
      startTicking(null, msg.remaining);
      setStatus("Paused", "paused");
      break;

    case "timer_resumed":
      phase = "running";
      startTicking(msg.ends_at);
      setStatus("Focusing", "running");
      break;

    case "timer_reset":
      phase = "idle";
      setTimerIdle(Number($("#sess-min").value) * 60);
      renderMembers(lastMembers());
      break;

    case "violation": {
      renderMembers(lastMembers(), msg.violations);
      if (msg.user_id === me?.user_id) {
        $("#focus-overlay").classList.add("show");
        fireNotification();
        toast(`Focus broken — slip #${msg.count}. Points at risk ⚠️`, "bad");
      } else {
        const name = lastMembers().find(m => m.user_id === msg.user_id)?.display_name || "Someone";
        toast(`${name} slipped (${msg.violations[msg.user_id]} slip${msg.violations[msg.user_id] !== 1 ? 's' : ''})`, "");
      }
      break;
    }

    case "session_complete": {
      phase = "idle";
      const sessDur = totalDurSec;
      setTimerIdle(sessDur);
      const box = $("#results-box");
      box.classList.remove("hidden");
      const sorted = msg.results.sort((a, b) => b.points - a.points);
      box.innerHTML = `
        <h4>Session ${msg.reason === "time_up" ? "complete ✅" : "ended early"}</h4>
        ${sorted.map((r, i) => `
          <div class="results-row">
            <span>
              <span class="rank r${i + 1}">${i + 1}</span>
              &nbsp;${escapeHtml(r.display_name)}
              &nbsp;<span class="pill ${r.violations ? "warn" : "ok"}">${r.violations} slip${r.violations !== 1 ? 's' : ''}</span>
              ${r.level_up ? '&nbsp;<span class="pill ok">Level up! 🎉</span>' : ""}
            </span>
            <span class="results-pts">+${r.points} pts</span>
          </div>`).join("")}`;
      toast("Session complete — points awarded! 🏅", "good");
      document.dispatchEvent(new CustomEvent("sp-points"));
      break;
    }

    case "chat": {
      const log = $("#chatlog");
      const div = document.createElement("div");
      div.className = "chat-msg";
      div.innerHTML = `<span class="chat-from">${escapeHtml(msg.from)}</span> <span class="chat-text">${escapeHtml(msg.text)}</span>`;
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
      break;
    }

    case "room_closed":
      toast(msg.detail ? `Room closed: ${msg.detail}` : "Room closed by admin", "bad");
      leaveRoom();
      break;

    case "error":
      toast(msg.detail, "bad");
      break;
  }
}

let membersCache = [];
const origRender = renderMembers;
// eslint-disable-next-line no-global-assign
window._renderMembers = function (...a) { membersCache = a[0] || membersCache; return origRender(...a); };
function lastMembers() { return membersCache; }

// Monkey-patch so violation / reset handlers work
(function () {
  const orig = renderMembers;
  window.__origRender = orig;
})();

function setHostControls() {
  const isHost = me && room && me.user_id === room.host_id;
  ["#btn-start", "#btn-pause", "#btn-resume", "#btn-finish", "#btn-reset"].forEach(id => {
    const el = $(id);
    if (el) el.disabled = !isHost;
  });
  const note = $("#host-controls-note");
  if (note) note.textContent = isHost ? "🎮 You are the host" : "Host controls the timer";
}

export function loadPublic() {
  const container = $("#public-rooms");
  if (!container) return;
  container.innerHTML = '<span class="muted"><span class="spinner"></span> Loading…</span>';

  api("GET", "/api/rooms/public")
    .then(rs => {
      if (!rs.length) {
        container.innerHTML = '<span class="muted">No public rooms yet — create one!</span>';
        return;
      }
      container.innerHTML = rs.map(r => `
        <div class="room-card-public" data-code="${r.code}">
          <div>
            <div class="room-card-name">${escapeHtml(r.name)}</div>
            <div class="room-card-code">${r.code}</div>
          </div>
          <div class="room-card-online">${r.online} online</div>
        </div>`).join("");
      container.querySelectorAll(".room-card-public").forEach(el =>
        el.onclick = () => joinRoom(el.dataset.code));
    })
    .catch(() => {
      container.innerHTML = '<span class="muted">Could not load rooms.</span>';
    });
}

function fireNotification() {
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification("Focus broken!", {
      body: "Return to StudyPartner to keep your streak alive.",
      icon: "/static/favicon.ico",
    });
  }
}
