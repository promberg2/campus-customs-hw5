# Campus Customs — back-office agent team (Homework 5)

A team of five AI agents (Boss, Inventory, Accounting, Facilities, Customer service) runs the back office of
Campus Customs, a Yale apparel shop. The agents work only through the tools of a FastMCP server on a SQLite
database. A FastAPI backend runs the team, and a React board (the "desk") shows the agents at work and lets a
human approve every payment. All agents use `gpt-6-luna` through Portkey.

```
hw5/
├── AI_prompts.md            my prompt log, problem by problem
├── requirements.txt         Python dependencies
├── .env.example             template for the Portkey key (copy to .env)
├── .mcp.json                MCP connection for Cursor (paths are for my machine, see below)
├── data/
│   ├── campus_customs.db        the original database, never changed
│   └── campus_customs_new.db    the working copy the tools change
├── mcp_server/              FastMCP server (23 tools) and its README
├── backend/                 FastAPI routes, agents, prompts/ (one file per agent)
├── frontend/                React + Vite + TypeScript board
├── tests/                   77 automated tests
└── output/                  harness.md, mcp_smoke.json, desk_tickets.html, design.md,
                             resolved_tickets.json, resolved_board.html, audit_trail.json,
                             Problem10_Reflection.md, board screenshots, github_url.txt
```

The working database in this repository is the state after the three tickets were resolved (cash $152.00).
Start with a reset (step 1) if you want to run the tickets yourself.

## Setup

Python 3.12 or newer and Node.js 22 or newer.

```powershell
# Windows (PowerShell), from the hw5 folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then put your PORTKEY_API_KEY into .env
```

```bash
# macOS / Linux, from the hw5 folder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then put your PORTKEY_API_KEY into .env
```

The real `.env` is not in the repository.

## 1. Clean run: copy the original database to the working copy

`data/campus_customs.db` is never changed. All tools work on `data/campus_customs_new.db`. To start from the
original values, copy the original over the working copy:

```powershell
copy data\campus_customs.db data\campus_customs_new.db      # Windows
```

```bash
cp data/campus_customs.db data/campus_customs_new.db        # macOS / Linux
```

The same reset is built into the app (see step 5), and it also clears the approval board.

## 2. Start the MCP server

The backend starts the MCP server on its own, as a subprocess over stdio, whenever the agents need it. You do
not have to start it by hand to use the app.

To run it on its own, for example to try the tools:

```bash
python -m mcp_server                                  # stdio (what the backend and Cursor use)
python -m mcp_server --transport http --port 8765     # or over HTTP at http://127.0.0.1:8765/mcp
```

It reads the database named in `CAMPUS_CUSTOMS_DB`, and defaults to `data/campus_customs_new.db`. To use it
from Cursor, change the three paths in `.mcp.json` to your own clone. The tools are described in
[`mcp_server/README.md`](mcp_server/README.md).

## 3. Start the FastAPI backend

With the virtual environment active:

```bash
cd backend
uvicorn main:app --port 8000
```

The interactive API docs are at http://127.0.0.1:8000/docs. `--reload` also works, but avoid editing code
during a run: a reload restarts the server and interrupts a run that is waiting for an approval.

## 4. Start the React board

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The board calls the backend at `http://localhost:8000`. If your backend runs on
another port, start the board with `VITE_API_URL`, for example `VITE_API_URL=http://localhost:8001 npm run dev`
(PowerShell: `$env:VITE_API_URL="http://localhost:8001"; npm run dev`).

## 5. Reset the database before a full three-ticket run

Always reset before running all three tickets, so the run starts from the original values (cash $3,400.00).
Any of these does the same thing: it copies the original database over the working copy and clears the board.

- the **Reset** button in the board's top bar;
- `POST http://localhost:8000/api/reset` (for example `curl -X POST http://localhost:8000/api/reset`);
- `python -m backend.run_team --reset` from the hw5 folder.

Then run tickets 101, 102 and 103 one by one from the board. When an agent prepares a payment or purchase
order, the run waits and the board shows "decision needs you". Approve it in **Approvals** under your own name,
and the same run continues. Nothing is paid without a named human, and nothing is sent to customers or
vendors: drafts and purchase orders stay on the board.

From the command line instead of the board:

```bash
python -m backend.run_team --reset --all --approval interactive --approver-name "Your name"
```

## Tests

```bash
python -m pytest -q          # 77 tests
cd frontend && npx tsc -b --noEmit
```

## Where to read more

- [`output/harness.md`](output/harness.md): the full documentation, problem by problem.
- [`output/desk_tickets.html`](output/desk_tickets.html): expected vs. actual per ticket, the cash tab and the
  reflection essay (open it in a browser).
- [`output/resolved_board.html`](output/resolved_board.html): screenshots of the board for each ticket.
- [`output/design.md`](output/design.md): the design of the board.
