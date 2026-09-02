import { api } from "./api.js";
import { mdLite, toast } from "./ui.js";

const $ = (s) => document.querySelector(s);

export function initNotes() {
  $("#note-save").onclick = saveNote;
  $("#note-cancel").onclick = resetForm;
  $("#note-delete").onclick = deleteNote;
  let t;
  $("#note-search").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadNotes, 300); });
  loadNotes();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

async function loadNotes() {
  const el = $("#notes-list");
  el.innerHTML = '<span class="muted"><span class="spinner"></span> Loading…</span>';
  try {
    const q = encodeURIComponent($("#note-search").value.trim());
    const notes = await api("GET", `/api/notes${q ? `?q=${q}` : ""}`);
    if (!notes.length) {
      el.innerHTML = '<span class="muted">No notes yet — create your first one!</span>';
      return;
    }
    el.innerHTML = notes.map(n => {
      const tags = n.tags ? n.tags.split(",").map(t => t.trim()).filter(Boolean) : [];
      const date = n.updated_at ? n.updated_at.slice(0, 10) : "";
      return `
        <div class="note-item" data-id="${n.id}">
          <div class="note-title">${escapeHtml(n.title)}</div>
          <div class="note-meta">
            ${tags.map(t => `<span class="note-tag">${escapeHtml(t)}</span>`).join("")}
            ${date ? `<span class="note-date">${date}</span>` : ""}
          </div>
        </div>`;
    }).join("");
    el.querySelectorAll(".note-item").forEach(li => li.onclick = () => openNote(li.dataset.id));
  } catch (e) {
    toast(e.message, "bad");
    el.innerHTML = '<span class="muted">Could not load notes.</span>';
  }
}

async function openNote(id) {
  try {
    const n = await api("GET", `/api/notes/${id}`);
    $("#note-id").value = n.id;
    $("#note-title").value = n.title;
    $("#note-tags").value = n.tags;
    $("#note-content").value = n.content;
    $("#note-form-title").innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      Editing note`;
    $("#note-cancel").classList.remove("hidden");
    $("#note-delete").classList.remove("hidden");
    // Highlight active note
    document.querySelectorAll(".note-item").forEach(el => {
      el.classList.toggle("sel", el.dataset.id === id);
    });
    // Scroll editor into view on mobile
    $("#note-title").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    toast(e.message, "bad");
  }
}

function resetForm() {
  ["#note-id", "#note-title", "#note-tags", "#note-content"].forEach(s => ($(s).value = ""));
  $("#note-form-title").innerHTML = `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
    New note`;
  $("#note-cancel").classList.add("hidden");
  $("#note-delete").classList.add("hidden");
  document.querySelectorAll(".note-item").forEach(el => el.classList.remove("sel"));
}

async function saveNote() {
  const btn = $("#note-save");
  const body = {
    title: $("#note-title").value,
    content: $("#note-content").value,
    tags: $("#note-tags").value,
  };
  if (!body.title.trim()) { toast("Title is required", "bad"); return; }
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving…';
  try {
    const id = $("#note-id").value;
    if (id) {
      await api("PUT", `/api/notes/${id}`, body);
      toast("Note updated ✓", "good");
    } else {
      const r = await api("POST", "/api/notes", body);
      toast(`Note saved — +${r.points.delta} pts${r.streak?.bonus ? `, +${r.streak.bonus} streak bonus` : ""} 🗒`, "good");
      document.dispatchEvent(new CustomEvent("sp-points"));
    }
    resetForm();
    loadNotes();
  } catch (e) {
    toast(e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Save note`;
  }
}

async function deleteNote() {
  const id = $("#note-id").value;
  if (!id) return;
  if (!confirm("Delete this note?")) return;
  try {
    await api("DELETE", `/api/notes/${id}`);
    resetForm();
    loadNotes();
    toast("Note deleted", "");
  } catch (e) {
    toast(e.message, "bad");
  }
}
