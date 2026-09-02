import { api } from "./api.js";
import { toast } from "./ui.js";

const $ = (s) => document.querySelector(s);
let wired = false;

export function initAdmin() {
  document.addEventListener("sp-ready", async () => {
    try {
      const p = await api("GET", "/api/gamify/profile");
      if (!p.is_admin) return;
    } catch { return; }
    const tab = document.querySelector('[data-tab="admin"]');
    if (tab) tab.classList.remove("hidden");
    wire();
    refreshAll();
  });
  document.addEventListener("sp-points", () => {
    if (wired && document.getElementById("panel-admin").classList.contains("active")) refreshAll();
  });
}

function wire() {
  if (wired) return;
  wired = true;

  let t;
  $("#u-search").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadUsers, 300); });
  $("#r-refresh").onclick = loadRooms;

  $("#u-body").onclick = onUserAction;
  $("#r-body").onclick = onRoomAction;
}

async function refreshAll() {
  await Promise.all([loadOverview(), loadUsers(), loadRooms()]);
}

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

async function loadOverview() {
  try {
    const o = await api("GET", "/api/admin/overview");
    $("#ov-users").textContent = o.users;
    $("#ov-rooms").textContent = o.rooms;
    $("#ov-online").textContent = o.online_now;
    $("#ov-live").textContent = o.sessions_running;
    $("#ov-s24").textContent = o.sessions_completed_24h;
  } catch {}
}

async function loadUsers() {
  try {
    const q = encodeURIComponent($("#u-search").value.trim());
    const users = await api("GET", `/api/admin/users${q ? `?q=${q}` : ""}`);
    const body = $("#u-body");
    body.innerHTML = users.length
      ? users.map(u => `
        <tr>
          <td><b>${esc(u.display_name)}</b><br><small class="muted">${esc(u.id)}</small></td>
          <td class="muted">${esc(u.email || "—")}</td>
          <td class="num">${u.points}</td>
          <td class="num">${u.current_streak}</td>
          <td class="num">${u.notes}</td>
          <td>${u.is_admin ? '<span class="pill ok">admin</span>' : '<span class="muted">member</span>'}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn sm ghost" data-act="addp" data-id="${esc(u.id)}" title="Award points">+ pts</button>
            <button class="btn sm ghost" data-act="subp" data-id="${esc(u.id)}" title="Deduct points">&minus; pts</button>
            <button class="btn sm ghost" data-act="${u.is_admin ? "demote" : "promote"}" data-id="${esc(u.id)}">${u.is_admin ? "Demote" : "Make admin"}</button>
            <button class="btn sm danger" data-act="del" data-id="${esc(u.id)}">Delete</button>
          </td>
        </tr>`).join("")
      : '<tr><td colspan="7" class="muted">No users match.</td></tr>';
  } catch (e) { /* non-admin or offline */ }
}

async function onUserAction(e) {
  const b = e.target.closest("button");
  if (!b) return;
  const { act, id } = b.dataset;
  try {
    if (act === "addp" || act === "subp") {
      const d = prompt(act === "addp" ? "Points to award:" : "Points to deduct:", act === "addp" ? "10" : "5");
      if (!d) return;
      const delta = Math.abs(parseInt(d, 10) || 0) * (act === "addp" ? 1 : -1);
      if (!delta) return;
      await api("POST", `/api/admin/users/${id}/points`, { delta, reason: "dashboard adjustment" });
      toast(`${delta > 0 ? "+" : ""}${delta} pts applied`, "good");
    } else if (act === "promote") {
      await api("PATCH", `/api/admin/users/${id}`, { is_admin: true });
      toast("Admin role granted", "good");
    } else if (act === "demote") {
      await api("PATCH", `/api/admin/users/${id}`, { is_admin: false });
      toast("Admin role revoked", "");
    } else if (act === "del") {
      if (!confirm("Delete this user and ALL their content? This cannot be undone.")) return;
      await api("DELETE", `/api/admin/users/${id}`);
      toast("User deleted", "");
    }
    refreshAll();
  } catch (err) { toast(err.message, "bad"); }
}

async function loadRooms() {
  try {
    const rooms = await api("GET", "/api/admin/rooms");
    const body = $("#r-body");
    body.innerHTML = rooms.length
      ? rooms.map(r => `
        <tr>
          <td><b>${esc(r.code)}</b></td>
          <td>${esc(r.name)}</td>
          <td>${esc(r.host_name)}${r.is_public ? "" : ' <span class="badge">private</span>'}</td>
          <td class="num">${r.members_db} db · ${r.online} online</td>
          <td>${r.phase === "running"
              ? '<span class="pill ok">running</span>'
              : r.phase === "paused"
                ? '<span class="pill warn">paused</span>'
                : '<span class="muted">idle</span>'}</td>
          <td class="muted">${r.created_at.slice(0, 16).replace("T", " ")}</td>
          <td style="text-align:right;white-space:nowrap">
            ${r.phase !== "idle"
              ? `<button class="btn sm" data-act="end" data-code="${esc(r.code)}">End session</button>` : ""}
            <button class="btn sm danger" data-act="delroom" data-code="${esc(r.code)}">Delete</button>
          </td>
        </tr>`).join("")
      : '<tr><td colspan="7" class="muted">No rooms yet.</td></tr>';
  } catch {}
}

async function onRoomAction(e) {
  const b = e.target.closest("button");
  if (!b) return;
  const { act, code } = b.dataset;
  try {
    if (act === "end") {
      if (!confirm(`Force-end the running session in ${code}? Members present will be awarded points.`)) return;
      await api("POST", `/api/admin/rooms/${code}/end`);
      toast("Session ended", "good");
    } else if (act === "delroom") {
      if (!confirm(`Delete room ${code}? Connected members will be disconnected.`)) return;
      await api("DELETE", `/api/admin/rooms/${code}`);
      toast("Room deleted", "");
    }
    refreshAll();
  } catch (err) { toast(err.message, "bad"); }
}
