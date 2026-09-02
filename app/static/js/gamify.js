import { api } from "./api.js";
import { toast } from "./ui.js";

const $ = (s) => document.querySelector(s);

export function initStats() {
  document.addEventListener("sp-ready", refresh);
  document.addEventListener("sp-points", () => setTimeout(refresh, 500));
}

export function refresh() {
  loadProfile();
  loadLeaderboard();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function relativeTime(dateStr) {
  const d = new Date(dateStr);
  const diffMs = Date.now() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  return `${diffDays}d ago`;
}

async function loadProfile() {
  try {
    const p = await api("GET", "/api/gamify/profile");

    // Points
    $("#st-points").textContent = p.points.toLocaleString();
    // Level progress bar
    const lvl = p.level;
    const pct = Math.round(lvl.pct || 0);
    $("#st-lvlbar").style.width = `${pct}%`;
    $("#st-lvltxt").textContent = `Level ${lvl.level} — ${(p.points - lvl.floor).toLocaleString()} / ${(lvl.next - lvl.floor).toLocaleString()} XP to next`;

    // Sidebar badge
    const badge = $("#lvl-badge");
    if (badge) badge.textContent = `Lv ${lvl.level} · ${p.points.toLocaleString()} pts`;

    // Streak
    const streak = p.current_streak;
    const streakEmoji = streak >= 7 ? "🔥" : streak >= 3 ? "⚡" : "📅";
    $("#st-streak").textContent = `${streakEmoji} ${streak} day${streak !== 1 ? "s" : ""}`;
    const longest = p.longest_streak;
    $("#st-streakbest").textContent = `Best: ${longest} day${longest !== 1 ? "s" : ""}`;

    // Bonus notification
    if (p.streak_today && p.streak_today.bonus > 0) {
      toast(`🔥 ${streak}-day streak — +${p.streak_today.bonus} bonus pts!`, "good");
    }

    // Activity
    const t = p.totals;
    const totalActivity = t.focus_sessions + t.quizzes;
    $("#st-sessions").textContent = `${totalActivity}`;
    $("#st-totals").textContent = `${t.focus_sessions} sessions · ${t.quizzes} quizzes · ${t.notes} notes`;

    // Recent events
    const eventsHtml = p.recent_events.length
      ? p.recent_events.map(e => {
          const reasonLabels = {
            "note-created": "📝 Note created",
            "focus-session": "⏱ Focus session",
          };
          const label = Object.entries(reasonLabels).find(([k]) => e.reason.startsWith(k))?.[1]
            || escapeHtml(e.reason);
          return `
            <tr>
              <td>${label}</td>
              <td class="num ${e.delta >= 0 ? "pos" : "neg"}">${e.delta >= 0 ? "+" : ""}${e.delta}</td>
              <td class="muted">${relativeTime(e.at)}</td>
            </tr>`;
        }).join("")
      : '<tr><td colspan="3" class="muted" style="padding:16px;text-align:center">Nothing yet — start a session!</td></tr>';
    $("#events-tbl").innerHTML = `
      <thead><tr><th>Event</th><th>Pts</th><th>When</th></tr></thead>
      <tbody>${eventsHtml}</tbody>`;

    // Show admin tab if admin
    if (p.is_admin) {
      const adminTab = document.querySelector('[data-tab="admin"]');
      if (adminTab) adminTab.classList.remove("hidden");
    }
  } catch (e) {
    console.warn("Profile load failed:", e.message);
  }
}

async function loadLeaderboard() {
  try {
    const rows = await api("GET", "/api/gamify/leaderboard");
    const bodyHtml = rows.length
      ? rows.map(r => `
          <tr>
            <td><span class="rank r${r.rank}">${r.rank}</span></td>
            <td style="font-weight:600;color:var(--text)">${escapeHtml(r.display_name)}</td>
            <td><span class="badge">${r.level > 0 ? `Lv ${r.level}` : "—"}</span></td>
            <td class="num">${r.points.toLocaleString()}</td>
            <td class="num">${r.current_streak > 0 ? `🔥 ${r.current_streak}` : "—"}</td>
          </tr>`).join("")
      : '<tr><td colspan="5" class="muted" style="padding:16px;text-align:center">Be the first on the board.</td></tr>';
    $("#lb-tbl").innerHTML = `
      <thead><tr><th>#</th><th>Studier</th><th>Level</th><th>Points</th><th>Streak</th></tr></thead>
      <tbody>${bodyHtml}</tbody>`;
  } catch {}
}
