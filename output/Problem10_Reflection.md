# Problem 10: Reflection on the Campus Customs agent team

This report evaluates the five-agent team (Boss, Inventory, Accounting, Facilities, Customer service) on the three desk tickets, using only what the code, the working database, the audit trail and the test suite show.

**Sources.** All metrics come from the three final Problem 9 runs in `output/audit_trail.json`, one run per ticket:
- **Ticket 101:** run `a58b38b75ec7`.
- **Ticket 102:** run `956009e61de4`.
- **Ticket 103:** run `7836ec6adbd6`.

These runs started from a fresh reset on 2026-10-10 (21:01 UTC). Philipp approved every payment himself in the board, entering the name "Phil". While he decided, the agent's tool call waited on the board, and the run continued with the result, so each ticket took a single run. Other runs in the audit trail are used only for the history of the 103 discount decision and for the development problems listed in `output/harness.md` section 9.4. The test suite passes with 77 tests (`.\.venv\Scripts\python.exe -m pytest -q`).

**Labels used throughout:**
- **[live]** happened in a logged run;
- **[tested]** is covered by an automated test but was not exercised in a live run;
- **[hypothesis]** is a reasoned expectation without a measurement.

---

## 1. Performance on each ticket

### 1.1 Summary table (final runs)

| | 101 · Bulldog tee | 102 · Rent due | 103 · Bulk hoodies |
|---|---|---|---|
| Final status | `waiting_on_vendor` | `resolved` | `waiting_on_customer` |
| Outcome | **Partially successful**: blocker removed, shirt ordered, customer told the date and offered other sizes; not delivered | **Successful** | **Successful for the team's part**: offer drafted, customer's answer pending |
| Team runs | 1 | 1 | 1 |
| Total tokens | 93,355 (49% of all three runs) | 46,432 | 50,665 |
| Boss share of tokens | 47,377 (51%) | 28,612 (62%) | 35,670 (70%) |
| Input tokens / output tokens (all three runs) | — | — | 181,253 / 9,199 (95% input) |
| Team time (wall time minus the wait for the human) | 82 s | 48 s | 46 s |
| Waiting for the human's decision | 4 min 0 s (233 s and 7 s) | 45 s | — |
| Model requests | 22 | 12 | 12 |
| Agent MCP tool calls | 16 | 9 | 9 |
| Delegations | 5 | 2 | 2 |
| Identical calls repeated within the run | 4 | 1 | 1 |
| Human approvals | 2 ($840.00, $8.00) | 1 ($2,400.00) | 0 (15% is exactly the Boss's authority) |
| Cash moved | −$848.00 | −$2,400.00 | $0.00 |
| Refused or failed tool calls | 0 | 0 | 0 |

The MCP tools themselves took 3.7 s in total across the three runs (sum of `duration_ms`, including the two payment executions by the board), against 175 s of team time. **About 98% of the team's time was spent waiting for model responses, not doing shop work.** Token use is dominated by input (95%): each model step re-reads the system prompt, the tool schemas and the growing conversation. That is the main cost of every extra agent and every extra step.

### 1.2 Ticket 101: correct, safe, expensive and unfinished

**Correctness.** Every fact the team acted on matches the database [live]:
- size S at 0 on hand;
- invoice 501 for $840.00, 3 days overdue, blocking Bulldog Print Co;
- arrival date 2026-08-31 + 5 lead days = 2026-09-05;
- PO 1 at 1 × $8.00.

The final ledger reconciles: $3,400.00 − $840.00 − $8.00 = $2,552.00 before the rent.

**Safety.**
- The Boss authorized the exact amount; `_boss_authorization` (`backend/mcp_tools.py:58`) would have refused any other figure.
- Accounting's `pay_invoice` call waited on the board; the board executed the payment once, under the human's name, and returned `approved_and_executed` to the waiting call. The same happened for the purchase order.
- The draft passed the leak guard (`_leaks`, `mcp_server/operations.py:695`) on its first attempt.

**Coordination.**
- **What worked:**
  - Inventory and Accounting ran in parallel (both agent runs start within 0.1 s, at 21:02:34). That is a real latency benefit of the team structure.
  - The run continued after each approval: payment, then the purchase order, then the status and the customer draft, all in one run.
- **What did not:** Accounting was invoked three times, and used 32,981 tokens:
  - the first time for analysis (`list_invoices`, `get_ticket`, `get_cash_position`);
  - the second time only to carry the Boss's payment authorization, when it re-read `get_cash_position`. This is a consequence of the design: in `delegate` (`backend/agents/base.py:165`) an authorization can only travel with a new delegation;
  - the third time to order the shirt, when it re-read `get_ticket` and read `get_vendor_status` (already read by Inventory) before `create_purchase_order`.

**Efficiency.**
- 101 used 49% of all tokens to handle a single $28.00 shirt that has not yet arrived.
- The run repeated 4 identical calls: Accounting's `get_cash_position` and `get_ticket`, and the Boss's `get_shop_snapshot` and `get_ticket`. `boss.md` (line 35) says to use `get_ticket` "only for a detail it does not show".

**Reliability.**
- Development on 101 surfaced four of the first six problems in `harness.md` section 9.4:
  - scope creep into ticket 102;
  - analysis without a decision;
  - a stale purchase-order status;
  - a Portkey cache replay.
- The final behaviour is the product of those fixes, not of the first design.

**Did every agent contribute?**
- Inventory: yes, with the only tool that combines stock, the vendor block and the arrival date.
- Accounting: yes; it holds the money tools.
- Customer service: yes; it wrote one draft giving Tauhid the expected date (2026-09-05, "not a promise of earlier delivery") and the sizes in stock (M, L, XL).
- Boss: yes; it made the restock decision and set `waiting_on_vendor`, because the next event is the vendor's delivery.

**Verdict.** Correct and safe, but only partially successful: the ticket cannot be closed by any existing tool, because nothing records the delivery or reads the customer's answer (see 5.2 and 5.3).

### 1.3 Ticket 102: the cleanest ticket

**Correctness and safety.** `review_rent_payment` (`mcp_server/tools.py:303`) verified the notice in a single call [live]:
- requester = landlord;
- $2,400.00 = monthly rent;
- due 2026-09-02, unpaid;
- $152.00 left after paying.

The Boss authorized the exact amount and the run waited while Philipp approved it. `pay_rent` then updated cash, payments and `leases.next_due` (2026-09-02 → 2026-10-02) in one transaction, and the same run set the ticket to `resolved`.

**Efficiency.**
- Facilities used only 6,751 tokens (`get_ticket`, `review_rent_payment`).
- The Boss used 62% of the run's tokens (28,612 of 46,432), mostly briefing Facilities and Accounting and reading their reports back.
- Accounting's role was mechanical: `get_cash_position` and `get_ticket`, then submitting the already-authorized `pay_rent`. It added 11,069 tokens.

**Reliability.**
- Two earlier problems were found on this ticket and fixed:
  - bug 4, where a paid rent notice was read as a conflict;
  - a development run in which the Boss sent Customer service to a landlord ticket (`get_customer_order_view` error, run `9140cdcedd0b`).
- **Verdict:** successful.

### 1.4 Ticket 103: efficient and safe, but not repeatable

**Correctness.** All the arithmetic is correct [live]:
- unit price $58.00 × 0.85 = $49.30;
- margin ($49.30 − $22.00) / $49.30 = 55.4%;
- offer 8 × $49.30 = $394.40;
- restock 12 × $22.00 = $264.00, more than the $152.00 in checking, so offering only the 8 in stock was correct.

**Efficiency.**
- One run, 9 MCP tool calls, 46 s.
- Accounting needed one call, because `evaluate_bulk_discount_request` (`mcp_server/tools.py:448`) returns stock, margin scenarios, the Boss's authority and the restock cost together.
- The Boss correctly skipped Inventory.
- The only repeated call was the final verification snapshot that `boss.md` step 7 requires.

**Safety.**
- The draft discloses only the quantity and the agreed price.
- `record_discount_decision` (`operations.py:294`) refuses anything below cost or below the minimum margin; above 15% the gate in `approval_reason` (`mcp_tools.py:41`) sends the decision to a human.

**Reliability, the real weakness.**
- The commercial decision is not stable. Across all eleven runs that recorded a discount for 103, the Boss chose **15% ten times and 10% once** (run `adeff37d6088`). The final run chose 15%.
- 15% is exactly the ceiling of its own authority (`BOSS_DISCOUNT_AUTHORITY_PCT`, `backend/config.py:73`).
- No discount policy exists in the database, so the price a customer receives depends on sampling. That is a governance problem, not a calculation error.
- `record_discount_decision` also refuses a second decision on the same ticket (`operations.py:301`). A poor price cannot be corrected later by any agent.

**Verdict.** Successful for the team's part: the decision was safe and the offer is drafted. The ticket is still open, waiting on the customer's reply.

---

## 2. Actual compared with Expected

### 2.1 Step-by-step comparison

| Ticket | Expected step (my plan) | Actual | Effect on the outcome |
|---|---|---|---|
| 101 | Boss calls Inventory first | Boss called Inventory **and** Accounting in parallel | Better: lower latency |
| 101 | Inventory uses `check_order_fulfillment` | Exactly as planned | — |
| 101 | Accounting authorizes and asks for human approval | The **Boss** authorized (maker-checker in code); Accounting only submitted | Better: separation of duties is enforced in code, not left to the prompt |
| 101 | Paying the invoice "releases the shirts" | Paying only unblocked the vendor. Nothing was on order, so a $8.00 PO and a second approval were needed | Necessary: my plan assumed an order existed. It did not (the tool confirmed it) |
| 101 | One pass | One run, which paused at both approvals and continued after each decision | As planned |
| 101 | Customer service drafts once | One draft, with the date and the sizes in stock | As planned |
| 102 | Facilities uses `get_lease_status` | Facilities used `review_rent_payment` | Better: one composite call covers lease, payments and cash |
| 102 | Accounting runs `pay_rent`, human approves, tables update | Exactly as planned, in one run | — |
| 103 | Inventory uses `check_stock` | Inventory was not called | Better: the stock was already in `get_ticket` and the discount tool |
| 103 | Boss "asks to reorder" | Not attempted, because the discount tool showed $264 > $152 | Better: avoided a refused or overdraft action |
| 103 | Accounting uses `evaluate_bulk_discount_request` | Exactly as planned | — |
| 103 | Boss sets the discount, "might need human approval" | Boss chose 15%, exactly its authority, so no human was involved | Neutral; the choice is not stable across runs (1.4) |
| 103 | Customer service drafts for 8 hoodies with guardrails | Exactly as planned; the draft passed the leak guard on its first attempt | — |

### 2.2 What the deviations reveal

1. **My plans got the order of agents right and the state of the world wrong.** The biggest deviation (101's missing order) came from an assumption about data, not about agents. A plan for a multi-agent workflow is only as good as its model of the database, so plans should start from the tool outputs, not from the ticket text.
2. **Composite tools changed who needs to be involved.** In 102 and 103 the specialist I expected to work in several steps finished in one call, and in 103 a whole agent (Inventory) was skipped. Tool design decided the workflow more than my plan did.
3. **A human approval pauses the work, it does not end it.** I planned each ticket as one pass, and that is what happened: the run waits at the board for the decision and continues with the result, so 101, with two approvals, still needed one run and nothing had to be worked out twice.
4. **Deviations made the outcome better or left it the same; none made it worse.** The cost is predictability: the same ticket can take a different path on another run (see section 6, point 4).

---

## 3. Would one agent with tools have been simpler?

**Measured findings [live]:**
- **The Boss used 58.6% of all tokens** (111,659 of 190,452). The specialists together used 41.4%.
- **Specialists usually needed only one or two tool calls:**
  - Facilities in 102 made 2 calls (6,751 tokens);
  - Accounting in 103 made 1 call (7,856 tokens);
  - Inventory in 101 made 1 call (5,823 tokens).
- **Every one of those delegations adds costs on the Boss's side:** a step to write the task, and a step that reads the full report back into its context.
- **6 of the 34 agent tool calls (18%) repeated an identical call already made in the same run** (`get_shop_snapshot` 3 extra, `get_ticket` 2 extra, `get_cash_position` 1 extra). Some are deliberate verification reads (`boss.md` step 7); the rest are not.
- **The tools ran in 2.1% of the team time;** the rest was model inference.

**Hypotheses** (no single-agent benchmark was run, so none of these is measured):
- **102 and 103 could very likely be handled by one agent.** Each needs one composite read tool, one write (`pay_rent` or `record_discount_decision`), one draft or status update, and the human gate.
- With fewer model steps per run, a single agent would probably use fewer tokens and less time. Because inference is 98% of team time, fewer steps is the lever that matters. **This must not be claimed as faster without running the comparison.**

**Where specialization helped, with evidence:**
- **Least privilege is enforced per agent** (`TOOLS_BY_AGENT`, `backend/config.py:39–55`):
  - only Accounting holds `pay_invoice`, `pay_rent` and `create_purchase_order`;
  - Customer service sees only `get_customer_order_view`, `save_customer_draft` and `list_drafts`, so internal cost and cash data never enters its context.
- **The maker-checker worked live.** In development run `5cbf8a169032`, Accounting tried `pay_invoice` without the Boss's authorization and was refused (`refused_not_authorized_by_boss`).
- **Parallel analysis in 101** shortened the run.

**The counter-evidence is just as important.** Most of the safety lives in the tools and the backend, not in the agent split:
- the leak guard in `save_customer_draft`;
- the overdraft check;
- `require_human_approver` (`operations.py:97`);
- the ticket-scope guard (`out_of_scope`, `mcp_tools.py:71`);
- the board, which executes an approved action exactly once under the human's name (`board._decide`, `backend/board.py:256`).

A single agent behind the same MCP server would inherit all of them. Every draft refusal in the trail came from the leak guard, not from the agent split, and all of them were false positives. In run `87ef604d841a` the guard refused a 103 draft written by the isolated Customer service agent because it read the quantity "8 available" as the tee's $8.00 unit cost. The agent rewrote it as "eight", and the guard was later fixed (`test_draft_guard_allows_quantities_and_the_agreed_price`).

**Trade-off:**

| Criterion | Multi-agent (as built) | One agent with the same tools [hypothesis] |
|---|---|---|
| Tokens and latency | Measured: high overhead on the Boss side | Likely lower; not measured |
| Security | Per-agent tool lists; Boss authorization plus the human gate | Same server guards; loses per-agent context isolation and the two-key payment |
| Maintainability | Five prompts plus a charter to keep consistent | One prompt; simpler to debug |
| Modularity | New capabilities can be added as a new agent | New tools still work, but one prompt grows |

**Judgement.** Specialization paid off for the money path (101, and the payment step of 102) and for customer communication. For read-and-decide tickets like 103 and the review part of 102, it mainly added overhead.

---

## 4. Three new problems the existing team could solve

All three use only implemented tools. **Shared prerequisite:** the backend has no ticket-intake route and no tool that creates tickets. A new problem must be entered as a row in `tickets` (and `invoices`) by a person before the team can run on it. The scenarios assume the state after Problem 9 (invoice 501 paid, Bulldog Print Co unblocked, $152.00 in checking). Specific products and figures below come from the database; the new tickets themselves are hypothetical.

### 4.1 Partial order fulfilment from stock
- **Problem.** A customer orders 5 Classic Bulldog Tees in size L; 3 are on hand.
- **Agents.** Boss, Inventory, Accounting, Customer service.
- **Tools.**
  - `check_order_fulfillment`: 3 on hand, short 2, vendor unblocked, arrival 2026-08-31 + 5 = 2026-09-05.
  - `ship_order_from_stock` for 3 units.
  - `create_purchase_order`: 2 × $8.00 = $16.00, pending approval.
  - The human approves it on the board while the run waits.
  - `get_customer_order_view` and `save_customer_draft`.
- **Collaboration.** The Boss decides to ship what exists and reorder the rest. Inventory ships; Accounting raises the purchase order; the human approves it (cash $152.00 → $136.00); Customer service confirms 3 shipped and 2 expected.
- **Why it works.** `ship_order_from_stock` (`operations.py:391`) supports partial shipping: it checks `qty ≤ remaining` and `qty ≤ on hand` and logs a `stock_movements` row.
- **Evidence.** [tested] in `test_ship_guards` and `test_ship_after_price_decision_moves_stock_once`; never exercised live.
- **Limit.** The 2 reordered shirts can never be received (5.2), so the ticket could never be closed, like 101.

### 4.2 A new supplier invoice blocks a restock
- **Problem.** An overdue invoice from Elm City Gifts (vendor 2, "mugs and small goods", 3 lead days) arrives while Crest Mugs are at 0.
- **Agents.** Boss, Accounting, Inventory.
- **Tools.**
  - `find_stock_shortfalls` flags `CC-MUG-CREST` as out of stock.
  - `get_vendor_status` shows vendor 2 blocked.
  - `list_invoices` and `get_cash_position`.
  - The Boss's authorization, then `pay_invoice` after human approval.
  - `create_purchase_order` at $3.50 per mug.
- **Collaboration.** The same path as 101, and the one the team has proven live.
- **Expected outcome.**
  - If the invoice is at most $152.00, it is paid with approval and the vendor is unblocked.
  - If it is larger, `pay_invoice` refuses the overdraft [tested: `test_pay_rent_advances_lease_and_refuses_overdraft` and the payment tests], and the Boss must report that it cannot be paid.
- **Caveat.** The database does not link products to vendors. `get_vendor_status` itself says to match by `vendors.specialty`, so the mug–Elm City link is an inference by the model.

### 4.3 A bulk discount above the Boss's authority
- **Problem.** A student group asks 25% off 10 hoodies in size L; 14 are on hand.
- **Agents.** Boss, Accounting, then Inventory and Customer service once the human has decided.
- **Tools.**
  - `evaluate_bulk_discount_request`: 25% gives $43.50, a margin of ($43.50 − $22.00) / $43.50 = 49.4%, which is above the 20% minimum; the most allowed is 52.5%.
  - `record_discount_decision` at 25%. `approval_reason` (`mcp_tools.py:41`) queues it on the board as a "discount" item (`approval_queue.describe`).
  - On approval, the board runs it with `approved_by` (`board._decide`, `backend/board.py:256`), and the waiting run continues.
  - `ship_order_from_stock` for 10 units.
  - A draft at $43.50 each, 10 × $43.50 = $435.00. The guard accepts the agreed price, because `_customer_safe_amounts` includes the override.
- **Evidence.** [tested] at the unit level only: `test_backend.py:121–122` (the 15% gate), `test_discount_decision_rules` (a named human is required above 15%). No live run and no API test cover the discount approval end to end.

---

## 5. Three problems the team cannot solve today

### 5.1 Paying October's rent: no revenue, no forecast
- **Scenario.** Rent of $2,400.00 is due 2026-10-02, and checking holds $152.00.
- **Limitation.**
  - No tool can increase cash: the only cash write is the debit in the payment functions, and shipping 8 hoodies at $49.30 records no sale.
  - No tool projects cash over time. `get_cash_position` only looks 30 days ahead at known obligations.
  - The team can only refuse the payment or report the problem.
  - (Revenue is excluded by the homework rules, but the gap would be fatal in a real shop.)
- **Needed.**
  - `record_sale` (on shipment);
  - `record_customer_payment`;
  - `forecast_cash(horizon)`, built from `leases.next_due`, open invoices, approved POs and expected receipts.
- **Agent design.**
  - Extend **Accounting** with read-only forecasting.
  - Add a separate **Sales/Receivables agent** for money coming in, so the agent that receives money is never the one that pays it out.
- **Extended flow.** The Boss sees a projected shortfall weeks ahead, prioritises collections, and only authorizes payments the forecast covers.

### 5.2 Receiving the shirt that was ordered for 101
- **Scenario.** PO 1 is approved with an arrival date of 2026-09-05. Ticket 101 is `waiting_on_vendor` and should be completed when the shirt arrives.
- **Limitation.**
  - No tool marks a purchase order as received or adds stock. `stock_movements` only ever records negative quantities, from `ship_order_from_stock`.
  - `desk.date_today` is a fixed row: nothing advances the shop's date or wakes a ticket on its expected date.
  - As a result, 101 can never move past the restock and Tauhid can never be shipped his size-S shirt.
- **Needed.**
  - `receive_purchase_order(po_id, qty_received)`: increase inventory, add a positive stock movement, set the PO to `received`, and handle short or damaged deliveries.
  - A scheduler, which is not an agent, that triggers a team run on tickets whose expected date has arrived.
- **Agent design.** Extend **Inventory**: receiving is a stock job and fits its existing least-privilege boundary. No new agent is needed.
- **Extended flow.** On 2026-09-05 the scheduler starts a run. Inventory receives PO 1 and ships the shirt; Customer service confirms; the Boss sets `resolved`.

### 5.3 Handling the customer's reply
- **Scenario.** The Yale AI Club answers "yes, send the 8", or Tauhid chooses size M instead of waiting.
- **Limitation.**
  - There is no inbound channel: `POST /api/tickets/{id}/run` takes no input, no API route or tool creates or updates tickets, and drafts are never sent.
  - The 103 offer cannot be accepted inside the system.
  - A changed request cannot be priced again, because the decision on 103 is final (`operations.py:301`).
- **Needed.**
  - `ingest_message` (store an inbound message, link it to a ticket or open one);
  - a `ticket_messages` table;
  - `send_message`, approved by a human like a payment;
  - an amendment path for price decisions, approved by a human.
- **Agent design.**
  - Classify and route new messages with a deterministic first step (sender plus ticket reference), escalating to a model only when that is ambiguous. A full LLM agent for routing would repeat the overhead measured in section 3.
  - Extend **Customer service** to send approved replies.
- **Extended flow.** The club's "yes" is attached to 103, which triggers a run. Inventory ships 8; a sale of $394.40 is recorded (5.1); Customer service sends the confirmation once a human has approved it.

---

## 6. Additional critical reflection

1. **Multi-agent overhead.**
   - **Measured cost:** the Boss's coordination used 59% of tokens; 18% of agent tool calls were repeats; inference was 98% of the team time.
   - **Measured benefit:** parallel analysis in 101; per-agent tool isolation; the maker-checker that refused an unauthorized payment.
   - The extra agents justified their cost on the money path (101, the payment in 102), and not on the read-and-decide parts (the review in 102, the discount in 103).

2. **Tool and backend design mattered more than the number of agents.**
   - Every efficiency gain in the final runs came from a composite tool: `check_order_fulfillment`, `review_rent_payment`, `evaluate_bulk_discount_request`.
   - At least three of the six bugs found during development were fixed in tools or backend code, not prompts: the stale PO status, the paid-rent conflict and the scope guard.
   - Prompt rules proved weaker. `boss.md` tells the Boss to avoid unnecessary `get_ticket` calls, and it still fetched ticket 101 twice in one run.
   - **Well-designed, guarded tools were the more valuable investment.**

3. **Human oversight.**
   - **Appropriate:**
     - all three payments are required by the shop rules, and each was approved by a named human before any money moved;
     - the deny path worked live: in the four early runs on all open tickets (`87ef604d841a`, `f7b736faf1f9`, `5470775905ec`, `81b5f82093b8`), both payments were denied and nothing executed (`denied_actions` in `team_run_end`).
   - **Built into the flow:** the run waits for the decision and continues with the result, so an approval pauses the work without splitting it into separate runs.
   - **Not measured:** approval waits of 233 s, 7 s and 45 s are logged in the final runs, but the first includes screenshot work, so **no representative human review time was measured**.
   - **Weak spots:**
     - the API requires a name but not a reason: all three final approvals, by "Phil", have empty comments;
     - the $8.00 purchase order needed the same approval process as the $2,400.00 rent. The rules require it, but it is a load that would grow with volume;
     - a waiting run holds the agent's call open, so if the human never decides, the run waits; after a server restart the board falls back to a follow-up run on approval.

4. **Consistency.**
   - **The guarded money outcome did not depend on the model:** the same three payments, each approved by a human, and an ending cash of $152.00.
   - **The choices left to the model did:**
     - the discount on 103 was 15% in 10 of 11 runs that recorded one, and 10% once;
     - the number of delegations, repeated reads and drafts differed between runs on the same ticket.
   - **The guarded actions were reproducible; the choices left to the model were not.**

5. **Scalability to 100 tickets.** All of the following are [hypothesis], derived from the code and the measured rates:
   - **Runs are sequential.** `start_run` refuses a second active run (`backend/board.py:163`, test `test_run_rejects_unknown_ticket_and_parallel_runs`). At the measured average of about 58 s of team time and 63,500 tokens per run, and one run per ticket, 100 tickets would take at least an hour and a half of agent time and six million tokens, plus the time a human needs for every approval, during which the run waits.
   - **The Boss's context grows.** `get_shop_snapshot` lists every open ticket, and input is already 95% of the tokens.
   - **Cash planning breaks down.** Each run is limited to one ticket by the scope guard, so cash allocation across 100 competing tickets has no global owner.
   - **The audit trail slows down.** `AuditTrail._append_sync` (`backend/audit.py:70`) re-reads and rewrites the whole JSON file on every event; it is already 4.5 MB after 58 runs, so total write cost grows quadratically.
   - **The approval board becomes the bottleneck,** with one human approving every payment while runs wait.

6. **Three improvements, ranked by importance.**
   1. **Turn discretionary policy into code (reliability).** Move the discount choice into a deterministic rule: a tool that returns the recommended discount for a quantity tier, inside the margin and authority limits. Let the model explain the rule rather than pick a percentage. This removes the 15%/10% variance and makes prices auditable.
   2. **Cut coordination overhead (efficiency).** Three changes:
      - give the Boss read-only access to the composite review tools, so single-call lookups need no delegation;
      - cache identical reads within a run, removing the 18% repeated calls;
      - let a payment authorization or a follow-up order be added to an existing delegation, which removes the extra Accounting invocations in 101 (three instead of one).

      Measure the result with the single-agent benchmark this report could not provide.
   3. **Require a reason on every approval (reliability and auditability).** The approve route requires a name (`require_human_approver`, `operations.py:97`) but not a comment, and all three final approvals by "Phil" have empty comments. Requiring a short note in the review dialog and the API would make every human decision explainable afterwards, and it would give any future learning from approvals (section 8) the reasons it needs. [hypothesis: not implemented]

---

## 7. Evidence gaps

- **No single-agent baseline** was run, so every efficiency claim for one agent is a hypothesis.
- **No representative human review time:** the approval waits include screenshot work, and the final approvals carry no review notes.
- **Few repeated trials:** one final run per ticket; other runs are used only for the discount history. That is not enough to put a statistical figure on how much the agents vary.
- **Never exercised live:** `ship_order_from_stock`, `find_stock_shortfalls`, a discount above 15% approved on the board, and a payment refused for lack of cash. They are covered only by tests (or, for the board discount path, not end to end).
- **Ticket 101 cannot be verified to the end,** because delivery is not modelled.
- **The documented state is the database state.** The three final runs were made last, so the working database holds exactly what is documented here: cash $152.00, payments 1–3 approved by "Phil", 101 `waiting_on_vendor`, 102 `resolved`, 103 at 15% and `waiting_on_customer`, drafts 1 and 2.

---

## 8. Author's perspective (Philipp)

- **Scale changes the answer.** The three tickets were relatively isolated, individual tasks, so a single agent might perform comparably on them. A real shop would add many more tools and connected workflows. The evidence above is consistent with a team advantage there:
  - input is 95% of every model call;
  - a specialist carries 3–9 MCP tools (`TOOLS_BY_AGENT`), against all 23 for a single agent;
  - independent work runs in parallel (101).

  This is a reasoned expectation [hypothesis] that should be tested with a larger, mixed benchmark.
- **Learning.** Agents should improve from their own history. The audit trail already records tool calls, decisions, approvals and reviewer comments. Learning may improve choices within the guardrails but must never relax them, and learned patterns should be reviewed by a human before becoming code [hypothetical extension].
- **Expansion.** Next steps:
  - integration with the online shop, which would also fix ticket intake;
  - revenue tasks (5.1);
  - more automated processes, such as receiving, low-stock reordering and returns.
- **Overall.** A strong starting point. The agents coordinated well (four agents and a human in a single run on 101 without a wrong payment). A real campus store could benefit from a system like this.

## 9. Conclusion

The project shows that **the value of this team came from boundaries, not from the number of agents talking to each other.** Splitting the work into five agents earned its cost where it created real separation:
- the Boss authorizes, Accounting submits and a human approves before money moves;
- Customer service writes to customers without ever seeing costs or cash.

Where a ticket was "read one composite tool, make one decision, write one record", as in 103 and the review part of 102, the specialists did one or two calls. The Boss then spent most of the tokens briefing them and reading their reports back. The most reliable behaviour (exact amounts, no overdrafts, no duplicate payments, no leaks, no writes outside the ticket a run was working on) was enforced in tools and backend code and held in every final run. The least reliable behaviour (the discount percentage, which and how many tools were called, the number of drafts) was exactly what was left to the models.

The practical lesson: **start with one agent and strong, guarded tools; add an agent only when it needs a different permission boundary, can work in parallel, or needs separation of duties; and move every repeatable business decision into code.** Multi-agent architecture is worth it for controls and for parallel work. For everything else, a simpler agent with good tools is the better default, and the next step for Campus Customs should be to prove that claim with a benchmark rather than assume it.
