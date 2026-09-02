import { api } from "./api.js";
import { download, mdLite, toast } from "./ui.js";

const $ = (s) => document.querySelector(s);
let currentNb = null;
let activeQuiz = null;

const store = {
  key: () => `sp.nb.${getUserUid()}.${currentNb}`,
  all() { try { return JSON.parse(localStorage.getItem(this.key()) || "[]"); } catch { return []; } },
  save(items) { localStorage.setItem(this.key(), JSON.stringify(items)); },
  add(type, content, title) {
    const items = this.all();
    items.unshift({ id: `a${Date.now()}${Math.floor(Math.random() * 999)}`, type, content, title: title || "", created_at: new Date().toISOString() });
    this.save(items);
    return items[0];
  },
  update(id, patch) {
    const items = this.all();
    const it = items.find(x => x.id === id);
    if (it) Object.assign(it, patch);
    this.save(items);
  },
};

function getUserUid() {
  return window.__sp_uid || "anon";
}

export function setUid(uid) {
  window.__sp_uid = uid;
  if (currentNb) renderArtifacts();
}

export function initNotebook() {
  $("#nb-create").onclick = createNb;
  $("#src-add").onclick = addTextSource;
  $("#src-file-btn").onclick = () => $("#src-file").click();
  $("#src-file").onchange = uploadFile;
  $("#sum-btn").onclick = doSummarize;
  $("#ask-btn").onclick = doAsk;
  $("#quiz-btn").onclick = doQuiz;
  $("#art-export").onclick = exportAll;
  $("#art-import").onclick = () => $("#art-import-file").click();
  $("#art-import-file").onchange = importAll;
  loadList();
}

async function loadList() {
  const listEl = $("#nb-list");
  try {
    const nbs = await api("GET", "/api/notebooks");
    if (!nbs.length) {
      listEl.innerHTML = '<span class="muted">No notebooks yet — create one!</span>';
      return;
    }
    listEl.innerHTML = nbs.map(n =>
      `<div class="list-item ${n.id === currentNb ? "sel" : ""}" data-id="${n.id}">
         <div>
           <div style="font-weight:600;font-size:13px;color:var(--text)">${escapeHtml(n.title)}</div>
           <div class="muted" style="font-size:11px;margin-top:2px">${n.sources} source${n.sources !== 1 ? 's' : ''}</div>
         </div>
         <button class="btn xs danger" data-del="${n.id}" title="Delete notebook">✕</button>
       </div>`).join("");
    listEl.querySelectorAll(".list-item").forEach(el => {
      el.onclick = (e) => {
        if (e.target.dataset.del) return deleteNb(e.target.dataset.del);
        selectNb(el.dataset.id);
      };
    });
  } catch (e) {
    listEl.innerHTML = `<span class="muted">${e.message}</span>`;
  }
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

async function createNb() {
  const title = $("#nb-title").value.trim();
  if (!title) return toast("Give the notebook a title", "bad");
  const nb = await api("POST", "/api/notebooks", { title });
  $("#nb-title").value = "";
  await loadList();
  selectNb(nb.id);
}

async function deleteNb(id) {
  await api("DELETE", `/api/notebooks/${id}`);
  if (id === currentNb) { currentNb = null; $("#src-list").textContent = "Select a notebook."; }
  loadList();
  renderArtifacts();
}

async function selectNb(id) {
  currentNb = id;
  await loadList();
  const srcEl = $("#src-list");
  srcEl.innerHTML = '<span class="muted"><span class="spinner"></span> Loading sources…</span>';
  try {
    const detail = await api("GET", `/api/notebooks/${id}`);
    $("#nb-current-name").textContent = `· ${detail.title}`;
    if (!detail.sources.length) {
      srcEl.innerHTML = '<span class="muted">No sources yet — paste text or upload a file below.</span>';
    } else {
      srcEl.innerHTML = detail.sources.map(s =>
        `<div class="src-item">
           <span class="src-item-name">
             <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:5px;opacity:0.5"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
             ${escapeHtml(s.title)}
           </span>
           <span class="src-item-chars">${(s.chars / 1000).toFixed(1)}k ch</span>
         </div>`).join("");
    }
  } catch (e) {
    toast(e.message, "bad");
    srcEl.innerHTML = `<span class="muted">${e.message}</span>`;
  }
  renderArtifacts();
}

async function addTextSource() {
  if (!currentNb) return toast("Select a notebook first", "bad");
  const title = $("#src-title").value.trim();
  const text = $("#src-text").value;
  if (!text.trim()) return toast("Paste some material first", "bad");
  await api("POST", `/api/notebooks/${currentNb}/sources`, { title: title || "Pasted source", text });
  $("#src-title").value = ""; $("#src-text").value = "";
  toast("Source added", "good");
  selectNb(currentNb);
}

async function uploadFile() {
  const f = $("#src-file").files[0];
  if (!f || !currentNb) return;
  const fd = new FormData();
  fd.append("file", f);
  fd.append("title", f.name);
  try {
    await api("POST", `/api/notebooks/${currentNb}/sources/upload`, fd);
    toast("File uploaded & parsed", "good");
    selectNb(currentNb);
  } catch (e) { toast(e.message, "bad"); }
  $("#src-file").value = "";
}

function showAgent(text) {
  const el = $("#agent-out");
  el.innerHTML = mdLite(text);
  el.classList.remove("muted");
}

async function doSummarize() {
  if (!currentNb) return toast("Select a notebook first", "bad");
  busy($("#sum-btn"), true);
  try {
    const r = await api("POST", `/api/notebooks/${currentNb}/summarize`);
    showAgent(r.summary);
    store.add("summary", r.summary, "Summary");
    renderArtifacts();
    toast(`Summary saved locally (${r.stats.used_context_tokens} ctx tokens, ${r.stats.fidelity})`, "good");
  } catch (e) { toast(e.message, "bad"); }
  busy($("#sum-btn"), false);
}

async function doAsk() {
  if (!currentNb) return toast("Select a notebook first", "bad");
  const message = $("#ask-input").value.trim();
  if (!message) return;
  busy($("#ask-btn"), true);
  try {
    const r = await api("POST", `/api/notebooks/${currentNb}/chat`, { message });
    showAgent(r.answer);
    store.add("qa", { q: message, a: r.answer }, message.slice(0, 60));
    renderArtifacts();
  } catch (e) { toast(e.message, "bad"); }
  busy($("#ask-btn"), false);
}

async function doQuiz() {
  if (!currentNb) return toast("Select a notebook first", "bad");
  busy($("#quiz-btn"), true);
  try {
    const n = +$("#quiz-n").value || 5;
    const r = await api("POST", `/api/notebooks/${currentNb}/quiz?num_questions=${n}`, {});
    activeQuiz = { quiz_id: r.quiz_id, questions: r.questions, answers: {} };
    store.add("quiz", { quiz_id: r.quiz_id, questions: r.questions }, `Quiz (${r.questions.length}q)`);
    renderArtifacts();
    renderQuiz(activeQuiz);
    $("#quiz-area").scrollIntoView({ behavior: "smooth" });
  } catch (e) { toast(e.message, "bad"); }
  busy($("#quiz-btn"), false);
}

function renderQuiz(quiz) {
  const area = $("#quiz-area");
  area.classList.remove("hidden");
  area.innerHTML = `
    <h3>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01"/></svg>
      Quiz
      <small>${quiz.questions.length} questions — select your answers, then submit</small>
    </h3>` +
    quiz.questions.map((q, i) => `
      <div class="quiz-q" data-i="${i}">
        <p>${i + 1}. ${escapeHtml(q.question)}</p>
        ${q.options.map((o, oi) => `<div class="opt" data-oi="${oi}">${String.fromCharCode(65 + oi)}. ${escapeHtml(o)}</div>`).join("")}
      </div>`).join("") +
    `<button class="btn primary" id="quiz-submit" style="margin-top:8px">
       <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
       Submit quiz
     </button>`;
  area.querySelectorAll(".quiz-q").forEach(qEl => {
    qEl.querySelectorAll(".opt").forEach(opt => {
      opt.onclick = () => {
        qEl.querySelectorAll(".opt").forEach(o => o.classList.remove("sel"));
        opt.classList.add("sel");
        quiz.answers[qEl.dataset.i] = +opt.dataset.oi;
      };
    });
  });
  $("#quiz-submit").onclick = submitQuiz;
}

async function submitQuiz() {
  if (!activeQuiz) return;
  const total = activeQuiz.questions.length;
  if (Object.keys(activeQuiz.answers).length < total)
    return toast(`Answer all ${total} questions`, "bad");
  busy($("#quiz-submit"), true);
  try {
    const ordered = [];
    for (let i = 0; i < total; i++) ordered.push(activeQuiz.answers[i]);
    const r = await api("POST", `/api/notebooks/quizzes/${activeQuiz.quiz_id}/submit`,
      { answers: ordered });
    $("#quiz-area").querySelectorAll(".quiz-q").forEach(qEl => {
      const i = +qEl.dataset.i;
      const right = r.review[i].answer_index;
      qEl.querySelectorAll(".opt")[right]?.classList.add("right");
      if (!r.review[i].correct && ordered[i] >= 0)
        qEl.querySelectorAll(".opt")[ordered[i]]?.classList.add("wrong");
      const exp = document.createElement("p");
      exp.className = "muted";
      exp.innerHTML = `${r.review[i].correct ? "Correct" : "Incorrect"} — ${escapeHtml(r.review[i].explanation)}`;
      qEl.appendChild(exp);
    });
    $("#quiz-submit").remove();
    store.update?.call?.(); // no-op guard
    const items = store.all();
    const it = items.find(x => x.type === "quiz" && x.content.quiz_id === activeQuiz.quiz_id);
    if (it) { it.content.result = { score: r.score, max: r.max }; store.save(items); }
    toast(`Scored ${r.score}/${r.max} — +${r.points.delta} pts${r.streak.bonus ? ` (streak bonus +${r.streak.bonus})` : ""}`, r.score / r.max >= .6 ? "good" : "");
    document.dispatchEvent(new CustomEvent("sp-points"));
  } catch (e) { toast(e.message, "bad"); }
}

function busy(btn, on) {
  btn.disabled = on;
  if (on) { btn.dataset.txt = btn.textContent; btn.innerHTML = '<span class="spinner"></span>'; }
  else btn.textContent = btn.dataset.txt || btn.textContent;
}

function artifactLabel(t) { return { summary: "Summary", qa: "Q&A", quiz: "Quiz" }[t] || "Artifact"; }

function renderArtifacts() {
  const listEl = $("#artifact-list");
  if (!currentNb) { listEl.textContent = "Select a notebook to see its local artifacts."; return; }
  const items = store.all();
  if (!items.length) { listEl.textContent = "No artifacts yet for this notebook."; return; }
  listEl.innerHTML = "";
  items.forEach(it => {
    const div = document.createElement("div");
    div.className = "artifact";
    let body = "";
    if (it.type === "summary") body = mdLite(String(it.content).slice(0, 700));
    else if (it.type === "qa") body = `<b>Q:</b> ${mdLite(it.content.q)}<br><b>A:</b> ${mdLite(String(it.content.a).slice(0, 500))}`;
    else if (it.type === "quiz") body = `Quiz · ${it.content.questions.length} questions` +
      (it.content.result ? ` · scored ${it.content.result.score}/${it.content.result.max}` : " · not attempted yet");
    div.innerHTML = `<div class="meta-row">
        <div class="row">
          <h4>${artifactLabel(it.type)}</h4>
          <span class="muted" style="font-size:12px">${escapeHtml(it.title || "")}</span>
        </div>
        <span class="row">
          <small class="muted">${new Date(it.created_at).toLocaleString()}</small>
          ${it.type === "note-candidate" ? "" : `<button class="btn sm ghost" data-note="${it.id}" title="Save as server note">To note</button>`}
          <button class="btn sm ghost" data-view="${it.id}">View</button>
          <button class="btn sm ghost" data-del="${it.id}" title="Delete artifact">Delete</button>
        </span>
      </div><div class="md-body">${body}</div>`;
    div.querySelector("[data-del]").onclick = () => { store.save(store.all().filter(x => x.id !== it.id)); renderArtifacts(); };
    div.querySelector("[data-note]").onclick = async () => {
      const content = it.type === "summary" || it.type === "qa"
        ? (typeof it.content === "string" ? it.content : JSON.stringify(it.content))
        : JSON.stringify(it.content);
      await api("POST", "/api/notes", { title: `[${it.type}] ${it.title}`, content, tags: "ai-artifact" });
      toast("Saved to central notes (+5 pts)", "good");
      document.dispatchEvent(new CustomEvent("sp-points"));
    };
    listEl.appendChild(div);
  });
}

function exportAll() {
  const dump = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k.startsWith(`sp.nb.${getUserUid()}.`)) dump[k] = localStorage.getItem(k);
  }
  download(`studypartner-artifacts-${getUserUid()}.json`, JSON.stringify(dump, null, 2));
}

function importAll(ev) {
  const f = ev.target.files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const dump = JSON.parse(reader.result);
      Object.entries(dump).forEach(([k, v]) => localStorage.setItem(k, v));
      toast("Artifacts imported", "good");
      renderArtifacts();
    } catch { toast("Invalid file", "bad"); }
  };
  reader.readAsText(f);
}
