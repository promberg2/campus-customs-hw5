# Campus Customs Desk — Design Notes (Problem 8)

This document explains how the Campus Customs desk in `frontend/` was designed: the ideas we started from, the research that shaped them, the structure of the screens, and the design language that holds everything together. It closes with two questions that matter most for a dashboard that sits between AI agents and people: how agents and humans read the same information differently, and what makes the desk something people actually enjoy using.

---

## 1. What the desk is for

The desk is the screen the people at Campus Customs use to run the back office together with the agent team. Real business decisions are made here, so the design started from one sentence: **the agents do the work, the human makes the calls, and the screen makes both visible.**

Our brief asked for six things, and each became a part of the product:

| Our idea | Where it lives |
|---|---|
| List all three tickets and let the user choose which one the team works on | Ticket list on the left of the Desk, with a clear **Run team** button and keys `1`–`3` and `R` |
| Show each agent and what it is saying and doing during a run | The **Agent team** graph and the **Team conversation** feed |
| Show the connections between agents and animate every time they communicate | Edges that color in with the sender's color, a traveling pulse, and speech bubbles |
| Mark a ticket resolved when the run finishes, and summarize what the team did | The ticket's state pill turns green, and the inspector shows **What the team did** |
| Let the human approve the necessary human calls | The **Approvals** inbox and the review dialog |
| Show the checking balance and help us understand the company's finances | The balance in the top bar, and the **Finance** view |

We added a few things the brief did not ask for but a real tool needs: a banner that says when a decision is waiting, a full audit trail with export, a replay of past runs, a stop button for live runs, a database reset with confirmation, toasts when cash moves, and an offline notice when the backend is down.

---

## 2. What we learned from others

Before drawing anything we looked at how leading products handle the same jobs.

- **Agent observability tools** (Langfuse, AgentOps, orq.ai) draw multi-agent runs as graphs of nodes and edges with counters on each node. They separate the *trace* (every raw step) from the *story* (what happened). We kept both: the Desk tells the story, and the Activity view holds the trace.
- **Spend-approval inboxes** (Ramp, BILL, Clearflow) put the decision first. Every request shows the amount, who asked, why, and what it does to the budget. Approving is one deliberate click, denying asks for a reason, and nothing is approved blind. Our Approvals view follows this pattern almost exactly.
- **Human-in-the-loop guidance** for AI agents says the human should see the plan, the current step, the time spent, and a visible way to stop. That became the stage tracker, the run clock and the **Stop** button.
- **Good business dashboards** lead with a verdict in plain words before any chart, and keep evidence one click away. That shaped the green or red verdict at the top of Finance and the "evidence" toggles inside each agent report.

The common lesson: **show decisions first, explain them in sentences, and keep the raw data close but out of the way.**

---

## 3. Structure

The desk has four views, always reachable from the left sidebar. The top bar stays the same everywhere and holds the three facts people check most often: the shop's date, the checking balance (with what is left after known bills), and a bell for pending decisions.

**Desk** is the home screen, built in three columns that read from left to right like a sentence: *what needs doing → who is doing it → what came out of it.*

1. **Tickets.** Three cards, one per ticket, each with its type, requester, item, the original note, and a state: Open, Team working, or Resolved. Stock alerts sit underneath because two of the tickets depend on stock.
2. **The team at work.** The selected ticket's header with the Run or Stop button, the live agent graph, and the conversation feed below it.
3. **The inspector.** Run status with a stage tracker (read the desk, delegate, specialist reports, human approval, Boss's report), counters for agents, hand-offs, tool calls and tokens, the approvals waiting for this ticket, and, once the run is done, the summary.

**Approvals** is an inbox. On the left is a list of every request with its amount aligned; on the right is everything needed to decide: the action, the cash before and after, the Boss's authorization, accounting's reason, and the exact command that will be sent to the shop systems.

**Finance** answers "can we pay what we owe?" It opens with a one-line verdict, then four numbers (checking, bills due within 30 days, cash after bills, cash waiting for approval), then a waterfall that walks from today's balance through each bill to what is left. Tables below show bills, payments with the name of the person who approved them, purchase orders and stock that needs attention.

**Activity** is the complete audit trail with filters for type, run and agent, a search box, a detail drawer for any event, and a JSON export.

---

## 4. Design language

Everything shares one dark, cool look so the screen is calm for long sessions and color can carry meaning.

**Color always means the same thing.**

- Each agent owns one color everywhere it appears: the Boss is blue, Inventory green, Accounting violet, Facilities cyan, Customer Service pink, the shop systems slate gray. A message in the feed, a node in the graph, an avatar in the activity table and an edge lighting up all use the same color, so you learn who is who after one run.
- **Amber means "a human is needed."** The human node, the "Needs you" banner, the approval badge and the waiting stage are all amber.
- **Green means done or safe**, and **red means money risk or failure**: an overdue bill, an overdraft, a refused action.

**Type and numbers.** Inter for all text, tabular figures for money so amounts line up in columns, and short labels written as people talk ("Bills to pay", "What the team did") rather than database names.

**Motion has a job.** Nothing moves for decoration. An edge colors in when two agents talk, a pulse travels in the direction of the message, a node spins while its agent is working and glows amber while it waits for you, the balance counts down when cash leaves, and the running ticket card has a slowly flowing border. When a run ends, every animation settles. People who prefer reduced motion get the same information without the movement.

---

## 5. The agent graph

The graph is the heart of the desk. The Boss sits at the top, the four specialists in a row beneath, the shop systems (the MCP server with its 23 tools) at the bottom, and **You** at the top right, next to the Boss, because the human is part of the team rather than an outsider.

- **Before a run** every connection is a faint dotted line: these are the paths that *could* be used.
- **When an agent hands work to another**, the edge between them draws itself in the sender's color and a glowing pulse travels along it. The receiver's ring lights up and starts spinning.
- **When an agent calls a tool**, a smaller, quicker pulse runs down to the shop systems, whose counter goes up.
- **When something needs a human**, an amber pulse runs to **You** and your node glows until you decide.
- **A speech bubble** shows the latest thing an agent said, so you can follow the conversation without reading the feed.
- **After a run** the used edges stay colored, so the graph becomes a map of who actually worked with whom. Badges show how many messages and tool calls each agent made.

Past runs can be **replayed** at 1×, 2× or 4× speed. That turns a finished run into something you can show a colleague, and it is the easiest way to understand how the team approached a ticket.

---

## 6. Approvals: making real money decisions safe

Agents can only prepare payments. Cash moves only when a named person approves on this screen, and the design makes that moment deliberate:

- Every request shows its **cash impact**: checking now, checking after this payment, and checking after all known bills. A payment that would overdraw the account turns red before anyone clicks.
- The **chain of reasons** is shown in order: the Boss authorized it and why, accounting prepared it and why, and what your decision will do.
- Approving needs your **real name** (agent names are refused) and a tick in **"I checked the amount, the reason and the cash impact."**
- Denying needs a **reason**, which is saved with the decision.
- After the decision the item moves to **Decided** with who decided, when, and the receipt from the shop systems.

---

## 7. How agents and humans read differently

The same run is written down twice, once for each kind of reader.

**Agents read structure.** They receive typed JSON from tools, with exact fields, ids and sources. They do not need color, order or emphasis; they need completeness and precision, and they follow rules written in their prompts. For them an approval is a status field (`queued_for_human_approval`), not a feeling of urgency.

**Humans read meaning.** People scan for what changed, what is at risk and what they must do. They trust sentences more than fields, they notice color and motion before text, and they want the evidence available but not in their face.

So the desk translates. Every audit event is turned into a one-line sentence that says who did what, for example that accounting's payment is now on your approval board and nothing has been paid. Agent reports appear as chat messages with a summary first and the facts table folded away under "evidence". Tool calls are compact rows that expand into raw JSON on demand. The approval status becomes an amber glow and a banner. Nothing is invented in the translation: every sentence and number on the screen comes from the shop database or the audit trail, and the Activity view always shows the original record.

---

## 8. What makes people enjoy the desk

A back-office tool is enjoyable when it removes worry and makes progress feel visible. These are the choices we made for that:

- **You always know what needs you.** One banner, one badge, one amber color. When nothing needs you, nothing nags.
- **Watching the team work is satisfying.** Seeing edges color in and pulses travel turns a black box into a team you can follow, and the replay makes it fun to show others.
- **Finishing feels like finishing.** The ticket turns green, a toast says it is resolved, and the summary tells you in plain words what happened and what comes next.
- **Money feels safe.** You see the effect of every payment before you approve it, and the balance visibly counts down when cash leaves, so nothing happens behind your back.
- **It respects your time.** Keyboard shortcuts, one-click navigation from an approval to its ticket, and evidence that is one click away instead of always on screen.
- **It is honest.** It never shows a number the database does not contain, it says plainly that income is not modeled, and it keeps the database's own ticket status visible next to the board's "resolved". Normally the run waits for your decision and continues by itself. Only if you decided an approval while no run was waiting (for example after a server restart) does the ticket card say a **follow-up run** is needed, so the Boss can confirm the payment and close it.

---

## 9. Running it

1. Start the backend from `backend/` with `uvicorn main:app --reload --port 8000`. It allows the Vite page at `http://localhost:5173` to call it.
2. Start the desk from `frontend/` with `npm install` (first time only) and then `npm run dev`.
3. Open `http://localhost:5173`. To use a different backend address, set `VITE_API_URL` before `npm run dev`.
