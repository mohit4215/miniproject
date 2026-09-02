import { initAuth } from "./auth.js";
import { getUser } from "./api.js";
import { initRooms, loadPublic } from "./rooms.js";
import { initNotebook, setUid } from "./notebook.js";
import { initNotes } from "./notes.js";
import { initStats } from "./gamify.js";
import { initAdmin } from "./admin.js";

const $ = (s) => document.querySelector(s);

window.addEventListener("error", (e) => {
  const box = document.getElementById("toasts");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast bad";
  el.textContent = `Script error: ${e.message}`;
  box.appendChild(el);
  setTimeout(() => el.remove(), 6000);
});

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#panel-${btn.dataset.tab}`).classList.add("active");
  };
});

function boot() {
  const uidWatch = setInterval(() => {
    const u = getUser();
    if (u) { setUid(u.uid); clearInterval(uidWatch); }
  }, 200);
  initRooms();
  initNotebook();
  initNotes();
  initStats();
  initAdmin();
  loadPublic();
}

initAuth(() => {});
document.addEventListener("sp-ready", () => {
  if (!document.getElementById("app-view").dataset.booted) {
    document.getElementById("app-view").dataset.booted = "1";
    boot();
  }
});
