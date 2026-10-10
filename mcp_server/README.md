# Campus Customs MCP Server

An [MCP](https://modelcontextprotocol.io) server, built with **FastMCP**, that gives AI agents safe, structured access to the Campus Customs back office. It is the **only** source of tools for the agent team in `backend/` (Problem 5): every read, status change, payment and draft goes through one of the 23 tools below (22 for the agents, 1 for the human approval routes). Every value comes from the database or is calculated from it; nothing is guessed.

## Database

| File | Used by the server? |
|---|---|
| `data/campus_customs_new.db` | **Yes.** The working copy, and the default. |
| `data/campus_customs.db` | **Never.** The original, kept unchanged as the reset source. The server refuses to open it. |

Set `CAMPUS_CUSTOMS_DB` to point the server at another copy (the tests use this). Reads use SQLite `mode=ro`. Each write runs in one `BEGIN IMMEDIATE` transaction that rolls back completely if any check fails. The first write creates four operational tables in the working copy only: `drafts`, `purchase_orders`, `stock_movements` and `price_overrides`.

To reset the working copy before a full run, use either command:

```powershell
.\.venv\Scripts\python.exe -m backend.run_team --reset
Copy-Item data\campus_customs.db data\campus_customs_new.db -Force
```

## Tools (23)

**Type:**
- **read**: `readOnlyHint` and `idempotentHint`; changes nothing.
- **write**: changes data but moves no money.
- **money**: `destructiveHint`, tagged `requires_human_approval`.

Write tools take `acting_agent`, and approval tools take `approved_by`. The agent backend fills both in and hides them from the model. Every tool also reads `desk` for "today".

### Shared and Boss

| Tool | Type | What it does | Tables read → written |
|---|---|---|---|
| `get_shop_snapshot` | read | One-call overview: cash, open tickets, open and overdue invoices, rent due in 30 days, cash after obligations, stock problems, pending purchase orders, drafts | `cash_accounts`, `tickets`, `invoices`, `vendors`, `leases`, `payments`, `inventory`, `purchase_orders`, `drafts` |
| `list_tickets` | read | Tickets, optionally filtered by status | `tickets` |
| `get_ticket` | read | One ticket with its linked invoice and vendor, lease, product stock, drafts, price decision and the analysis tool that handles it | `tickets`, `invoices`, `vendors`, `leases`, `inventory`, `drafts`, `price_overrides` |
| `update_ticket_status` | write | New status plus a dated, signed note appended to the ticket's notes | `tickets` → `tickets` |
| `record_discount_decision` | write | Records the price on a `price_override` ticket. Never below cost or the 20% minimum margin; above the Boss's 15% authority it needs a named human approver; one decision per ticket | `tickets`, `pricing`, `price_overrides` → `price_overrides` |

### Ticket analysis (one per ticket type)

Each takes a `ticket_id`, checks the ticket type (and names the correct tool if it is wrong), and returns an `outcome`, a `summary` and `next_steps`.

| Tool | Ticket | What it answers | Tables read |
|---|---|---|---|
| `check_order_fulfillment` | 101, customer order | Can the order ship? If not, which unpaid invoice blocks the supplier, what unblocking costs, and the earliest honest arrival date | `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, `cash_accounts` |
| `review_rent_payment` | 102, rent notice | Is the notice genuine (requester = landlord), unpaid this period and affordable? Shows cash after all open bills | `tickets`, `leases`, `payments`, `cash_accounts`, `invoices`, `vendors` |
| `evaluate_bulk_discount_request` | 103, price override | Units fillable now, cost floor, margin per discount, which discounts are `allowed` and `within_boss_authority`, blocked restock vendors, restock cost vs. cash | `tickets`, `inventory`, `pricing`, `vendors`, `invoices`, `leases`, `cash_accounts` |

### Inventory

| Tool | Type | What it does | Tables read → written |
|---|---|---|---|
| `check_stock` | read | Every size of one SKU with quantity, location and stock status | `inventory`, `pricing` |
| `find_stock_shortfalls` | read | Rows that are out of stock, low (≤ 3) or short for open customer tickets | `inventory`, `tickets` |
| `get_vendor_status` | read | Lead time, open invoices, blocked yes/no, earliest arrival, pending purchase orders | `vendors`, `invoices`, `purchase_orders` |
| `ship_order_from_stock` | write | Ships units to a customer ticket; refuses more than is on hand or than the ticket still needs, and refuses a discount ticket without a price decision | `tickets`, `inventory`, `stock_movements`, `price_overrides` → `inventory`, `stock_movements` |

### Accounting

| Tool | Type | What it does | Tables read → written |
|---|---|---|---|
| `get_cash_position` | read | Cash, obligations, cash after obligations, pending purchase orders, payment history | `cash_accounts`, `invoices`, `vendors`, `leases`, `payments`, `purchase_orders` |
| `list_invoices` | read | Open or paid invoices with due status and days overdue | `invoices`, `vendors` |
| `analyze_margin` | read | Cost, price, margin, largest discount above cost and allowed by the margin floor, for any SKU, quantity and discounts | `pricing`, `inventory` |
| `pay_invoice` | **money** | Needs a named human `approved_by`; exact amount; no double pay; no overdraft. Debits cash, records the payment, marks the invoice paid, reports whether the vendor is unblocked | `invoices`, `vendors`, `cash_accounts` → `cash_accounts`, `payments`, `invoices` |
| `pay_rent` | **money** | Needs a named human `approved_by`; exact amount; not already paid this period; no overdraft. Debits cash, records the payment, moves `next_due` forward one month | `leases`, `payments`, `cash_accounts` → `cash_accounts`, `payments`, `leases` |
| `create_purchase_order` | write | Records a restock order as `pending_approval` with cost, arrival date and affordability. Refused for a vendor with an unpaid invoice; no money moves, nothing is sent | `vendors`, `inventory`, `tickets`, `invoices`, `pricing`, `cash_accounts`, `leases`, `payments` → `purchase_orders` |

### Human only (Problem 7)

Never given to an agent. Only the approval routes of the board API (`backend/main.py`) call it, with the human's name.

| Tool | Type | What it does | Tables read → written |
|---|---|---|---|
| `decide_purchase_order` | **money** | A named human approves or rejects a pending purchase order. Approving pays it: debits cash, records the payment, marks the order `approved`; refused if not pending, if the vendor still has an open invoice, or on overdraft. Rejecting marks it `rejected` and moves no money | `purchase_orders`, `vendors`, `invoices`, `cash_accounts` → `cash_accounts`, `payments`, `purchase_orders` |

### Facilities

| Tool | Type | What it does | Tables read |
|---|---|---|---|
| `get_lease_status` | read | Leases with rent, landlord, next due date, due status and whether this period is paid | `leases`, `payments` |

### Customer service

| Tool | Type | What it does | Tables read → written |
|---|---|---|---|
| `get_customer_order_view` | read | Customer-safe facts only: product, size, quantity, list price, availability, expected date, other sizes, agreed price, plus the sharing rules. No cost, cash, vendor or invoice fields | `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, `purchase_orders`, `price_overrides` |
| `save_customer_draft` | write | Saves a reply to the requester as a draft (never sent). On customer tickets it refuses internal terms, vendor names and money amounts equal to costs, cash or invoices; the ticket's own list and agreed price are allowed | `tickets`, `vendors`, `pricing`, `cash_accounts`, `invoices`, `price_overrides` → `drafts` |
| `list_drafts` | read | Drafts for one ticket or all | `drafts`, `tickets` |

## Rules the server enforces on its own

These rules hold even if the client that calls the server is buggy or hostile:
- "Today" is `desk.date_today`, and lead times come from `vendors`.
- A vendor with an open unpaid invoice gets no purchase order.
- Payments need a real human name; "boss", "agent", "ai", "system" and similar names are rejected. Payments also refuse overdrafts, double payments and wrong amounts.
- Discounts never go below cost or the minimum margin.
- Customer drafts are checked for leaks.
- Nothing is ever sent to a customer or vendor.
- Unexpected errors are masked, so no stack traces or paths reach a model.

## Run

From the `hw5/` folder, with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m mcp_server                                # stdio (agent starts it as a subprocess)
.\.venv\Scripts\python.exe -m mcp_server --transport http --port 8765   # HTTP at http://127.0.0.1:8765/mcp
.\.venv\Scripts\python.exe -m pytest tests                              # 77 tests (server, operations, agent backend, board API)
.\.venv\Scripts\python.exe tests\mcp_smoke.py                           # prompt-driven smoke test -> output/mcp_smoke.json
```

## Connecting a client

The connection is defined in [`../.mcp.json`](../.mcp.json), the standard `mcpServers` format that Cursor and other MCP clients read:

```json
{
  "mcpServers": {
    "campus-customs": {
      "type": "stdio",
      "command": "C:/Users/phili/OneDrive/Desktop/AI Yale/Homework 5/hw5/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "C:/Users/phili/OneDrive/Desktop/AI Yale/Homework 5/hw5",
        "PYTHONUNBUFFERED": "1",
        "CAMPUS_CUSTOMS_DB": "C:/Users/phili/OneDrive/Desktop/AI Yale/Homework 5/hw5/data/campus_customs_new.db"
      }
    }
  }
}
```

The paths are absolute and `PYTHONPATH` points at `hw5/`, so the server starts the same way whichever folder the client was opened in. In **Cursor** the same entry is registered in `~/.cursor/mcp.json`, where it shows up as `campus-customs` under *Settings → MCP*. Cursor restarts the server automatically when the config file changes. After a change to the server code, toggle the server off and on there, or edit the config, so the new code is loaded.

The agent backend (`backend/mcp_tools.py`) reads this same file and connects with PydanticAI's `MCPToolset` over stdio. Each agent gets a filtered view with only its own tools.

## Layout

```
mcp_server/
  server.py      FastMCP app: 23 tool registrations, descriptions, annotations, input validation, transports
  tools.py       the three ticket-analysis tools and the discount math
  operations.py  all other tools: snapshot, stock, vendors, cash, payments, purchase orders, leases, drafts
  models.py      Pydantic output models (become each tool's output schema)
  db.py          read-only connections, write transactions, operational tables, "today", money rounding
  config.py      database path, guard against the original file, business-rule constants
  __main__.py    enables `python -m mcp_server`
```
