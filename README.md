# StudyPartner

All-in-one study companion: **shared focus rooms** (with anti-distraction
enforcement), a **NotebookLM-style AI notebook**, **centralized notes**, and
**gamification** (points, streaks, levels, leaderboard).

## Features

| Area | What it does |
|------|--------------|
| 🛋 Study rooms | Host-controlled Pomodoro timer synced over WebSocket. Leave the tab / minimize while it runs → violation counted, red block-screen + browser notification on return. Session end awards points to everyone present (violators get docked). Room chat + presence. |
| 🤖 AI notebook | Add text or `.txt/.md/.pdf` sources; summarize, ask questions, generate multiple-choice quizzes via any OpenAI-compatible API. Agent outputs are stored in **browser localStorage** (export/import as JSON). Quizzes are graded server-side — answers never reach the client before submission. |
| 🗒 Notes | Your own notes live centrally in Postgres: CRUD + search, markdown-ish rendering. |
| 🏆 Gamification | Points for focus sessions/quizzes/notes, daily streaks with bonuses (+50 every 7th day), levels `isqrt(points/250)+1`, global leaderboard. |

## Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, WebSocket rooms
- **DB:** PostgreSQL (`psycopg` 3) — auto-falls back to SQLite if unset
- **Auth:** Firebase Authentication (email/password + Google); `DEV_AUTH=1` bypass for local development
- **LLM:** any OpenAI-compatible API (OpenAI, Groq, Ollama-with-OpenAI-route...); built-in mock mode when no key is set
- **Frontend:** Jinja2 single page + vanilla ES modules, no build step
- Context handling: see [CONTEXT_WINDOW_MANAGER.md](CONTEXT_WINDOW_MANAGER.md)

## Quick start (local dev, zero external accounts)

```bash
cd studypartner
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env                               # defaults work out of the box
uvicorn app.main:app --reload
```

Open http://localhost:8000 → enter any username (dev mode) → create a room,
open a second browser profile to join it.

With no `LLM_API_KEY`, the agent answers in deterministic mock mode so the full
flow works offline. With no `DATABASE_URL`, data lands in `./dev.db` (SQLite).

## Production setup

1. **Firebase**: create a project → add a Web app → copy the config JSON into
   `FIREBASE_CONFIG_JSON`; generate a service-account key and provide it via
   `FIREBASE_SERVICE_ACCOUNT_JSON` (or `GOOGLE_APPLICATION_CREDENTIALS`). Set
   `DEV_AUTH=0`.
2. **Postgres**: point `DATABASE_URL` at your instance
   (`postgresql+psycopg://user:pass@host/db`). Tables are created on startup.
3. **LLM**: set `LLM_API_KEY` (+ optional `LLM_BASE_URL`, `LLM_MODEL`).
4. Run via Docker Compose:

```bash
cp .env.example .env   # fill in real values
docker compose up --build -d
```

## API sketch

```
POST /api/rooms                      create room → {code}
GET  /api/rooms/public              listed rooms w/ online counts
WS   /api/rooms/ws/{code}?token=…    join room (or ?uid=&name= in dev)
     ↕ start/pause/resume/reset/finish_early/violation/chat/ping
GET  /api/notebooks                  list · POST create · GET/{id} detail
POST /api/notebooks/{id}/sources     text source (upload endpoint for files)
POST /api/notebooks/{id}/summarize|chat|quiz
POST /api/notebooks/quizzes/{id}/submit
GET/POST/PUT/DELETE /api/notes       (+ ?q= search)
GET  /api/gamify/profile|leaderboard
GET  /api/admin/overview             platform stats (admin role required)
GET/PATCH/POST/DELETE /api/admin/users[...]   user management
GET  /api/admin/rooms · POST .../end · DELETE .../{code}  room management
GET  /healthz
```

**Admin access:** set `ADMIN_UIDS` (comma-separated, promoted on login) or flip a user's
role via the dashboard; in Firebase mode you can also set an `admin: true` custom claim.

## Project layout

```
studypartner/
├── app/
│   ├── main.py               FastAPI app wiring
│   ├── config.py             env-driven settings
│   ├── db.py                 engine/session/init
│   ├── models.py             ORM models (rooms, sessions, notebooks, notes…)
│   ├── auth.py               Firebase verify + dev bypass
│   ├── llm.py                OpenAI-compatible client + mock mode
│   ├── context_manager.py    token-budget prompt packing
│   ├── gamification.py       levels, points, streaks
│   ├── routers/              rooms · notebooks · notes · gamify
│   ├── templates/index.html  single-page UI
│   └── static/               css + es-module js
├── tests/test_smoke.py       end-to-end smoke tests
├── CONTEXT_WINDOW_MANAGER.md context-packing design doc
├── Dockerfile / docker-compose.yml
└── requirements.txt / .env.example
```
