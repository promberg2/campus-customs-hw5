# AI Prompt Log

This file is a documentation log of the prompts I typed while working on Homework 5.
It is not a runtime prompt file for the model.

**Format for each problem**
- Problem number and title
- The first prompt I typed for that problem
- Every follow-up prompt I typed for that problem, in order (or "none" if one prompt was enough)
- What was lacking in the first prompt: in plain words, what I had to change or add, and why the follow-up made the result better (or why one prompt was enough)

---

## General setup

These prompts came before the numbered homework problems. They set the workspace.

### Setup - Open Homework 5

**First prompt I typed:**
`ok we do now do Homework 5`

**Follow-up prompts:**
1. `it will work as homework 3 and 4, like we have done previously. i will give you all we need. but we work in yale again look for the homework 5 folder`
2. `switch there`

**What was lacking in the first prompt:**
The first prompt didn't say where Homework 5 lives. The chat was still open in the Lecture 10 folder, so the AI couldn't find any Homework 5 files there. My first follow-up pointed it to the Homework 5 folder inside AI Yale and said to set it up like Homework 3 and 4. The folder turned out to be empty, and the AI could only reach it in a roundabout way, so my second follow-up moved the whole chat into the AI Yale folder, where all the homework lives.

---

## Problem sections

### Problem 1 - Vibe coder prompts

**First prompt I typed:**
`Now we do Problem 1 called Vibe coder prompts. As always we set up the AI_prompts.md file that logs my prompts for this homework. as before we include problem number and title, the first prompt i type and the follow up prompt  if needed. then as before add a sentence that explains in a natural way what was missing in the first prompt and why the subsequent prompts where required, within the context of the work i did.  The I will give you data c:\Users\phili\Downloads\data (4).zip . Unzip and safe within the project so taht we have data/campus_customs.db. The tools we will build later will update a copy of that database. Create the copy data/campus_customs_new.db that is the copy our later MCP server and backend will work with. we will keep the data/campus_customs.db unchanged.`

**Follow-up prompt:**
*(none)*

**What was lacking in the first prompt:**
Nothing important was missing. I said what the log should contain, where the data comes from, and that the tools must only ever change a copy of the database, never the original. Keeping `campus_customs.db` untouched also gives us a clean starting point, so the shop can be reset to its original values before every full run. One prompt was enough.

### Problem 2 - Study the Campus Customs database

**First prompt I typed:**
`Now we do Problem 2 called Study the Campus Customs database. The task tells us to copy the database but we already did that. We want to take a closer look at the original file data/campus_customs and look through the tables. show me them in a structured way so i can quickly understand what's going on. Show me the three open tickets and how they link to other tables. then create output/harness.md, for each table in the database write down the fields and in good, natural and professional English explain why they matter for the agent we will build later. The harness.md will be part of grading so set it up the right way and always mention the respective problem as we will update the harness throughout the task.`

**Follow-up prompt:**
*(none)*

**What was lacking in the first prompt:**
Nothing essential was missing. I said which file to study, that it must stay unchanged, what to show me, and what the harness must contain. The prompt didn't ask how the tickets depend on *each other*, but tracing them showed that this is the real puzzle. One overdue $840 bill blocks the vendor that both the tee order and the hoodie order need. Paying that bill and the rent would leave only $160 of the $3,400. So the harness explains this link as well, because the agent we build later has to understand it to plan correctly.

### Problem 3 - Build the MCP server

**First prompt I typed:**
`Now we do Problem 3, called Build the MCP server. We build a MCP server in mcp_server/ using FastMCP, which communicates with our copy data/campus_customs_new.db. we do not have to connect it now, but set up everything in a way that this is easy later. This MCP server has to be up to industry standards, so take your time. The agents we will build later will use the tools in this MCP server. As general rules for the rest of this task we want to keep the tool names very clear and precise, enver inwvent any data at all, all the data is only from the database. We want to build the first three tools for the agents, to solve the three open tickets we have. These have to be highly capable tools so take your time and clearly plan out the tools before you build them. Every tool unlocks one of the tickets, keep in mind how they are connected, but one tool links to one ticket. The goal is the best possible solve, these have to be great tools we will later give to our agents. we want a world class mcp server that agents can use. Then after the tools are done we go into output/harness.md and list all three tools we have build. For every tool include specifically which ticket it helps to unlock , which table it reads, and one great sentence on why that tool is the right one for the ticket. Be specific and explain great, this will be part of grading and we want the best grade possible. The tool ticket connection has to be clear. The add a short mcp_server/README.md file that explains our MCP Server in the best way possible, what it is for, what database file it uses and the three tools in it. Take your time.`

**Follow-up prompt:**
*(none)*

**What was lacking in the first prompt:**
The prompt was complete on what to build and document, but it left open whether the first three tools may change the database. Two of the tickets involve paying money, and the shop rules say every payment needs human approval. So the tools only read: instead of paying, they return a ready-made payment proposal for a person to approve. The prompt also didn't say what to do where the database has no answer, such as which vendor restocks the hoodies or what discount is allowed. Following my rule never to invent data, the tools say openly that this information is missing and leave those decisions to a human.

### Problem 4 - Add the MCP server to vibe coder and test each tool

**First prompt I typed:**
`Now we do Problem 4, called Add the MCP server to vibe coder and teste each tool. We wan to add this MCP to this project so that you cursor can call all our tools. Write the according connection JSON text in .mcp.json and add to your MCP portfolio. the goals is that we can call this mcp server in the same way we would call every other professional MCP server, within cursor. This server should work like every other MCP server we know, if there is something i have to do manually let me know. Then after we want to test our tools, I know you tested already but his is separate and part of grading so take your time. we go tool by tool. The test outcomes and procedure will be saved in output/mcp_smoke.json. For each test we will write a separate prompt, in the same way if i manually inputted one prompt per test of one tool, but these prompts have to be highly sophisticated to test the tools the highest standards of software development. In our output/mcp_smoke.json write test by test, the prompt, the according tool name and the tool outputs. The tool outputs have yo match the values in data/campus_customs_new.db.`

**Follow-up prompts:**
1. `so we have three tests with three seperate prompt? show me all three prompts`
2. `Make sure that mcp_smoke.json has three main test, you can include the edge cases but seperate them. The task asks for one prompt one test per tool and that has to be shown clearly`

**What was lacking in the first prompt:**
The prompt covered the connection, the test record and the requirement that outputs match the database. It didn't say how to *prove* that match, so the expected values are computed by separate database queries that don't reuse the tool code; otherwise a tool bug could also hide in its own expected answer. This careful testing found a real bug: the bulk-discount tool named 62.1% as the largest safe discount, but that price is two cents below cost. It was fixed before the final run, and no manual steps were needed, because Cursor loaded and restarted the server on its own. What the first prompt didn't make clear was that the assignment wants exactly **one prompt and one test per tool**. Without that limit, the result was twelve tests of equal standing: three main checks mixed in with nine edge cases, such as wrong ticket types and invalid inputs. When I asked to see "the three prompts", that mix-up became visible. My second follow-up asked for the structure the task requires. `mcp_smoke.json` now opens with a `main_tests` section holding exactly three tests, one per tool, and keeps the edge cases in a separate `edge_case_tests` section, so a grader sees the required tests first and the extra testing second.

### Problem 5 - Build the agent team and grow the MCP tools

**First prompt I typed:**

```text
Now we do Problem 5, called Build the agent team and grow the MCP tools. Now we will build a team of agents for our project. This will be a big job, so takje your time to plan before building, we want the best outcome possible. This all has to compete with current industry standarts. All the agents will be build with PydanticAI. Structure the agents in a sensible way to maximize the outcomes of all the jobs we will later throw at our team. They are structured similar to workers in a real company. We want a peer to peer agent networks, which means that the agents can talk to each other. Think about the best possible structure before building our agents. We have one Boss agent that is the Boss and controls and delegates etc.. We further have inventory agents, accounting agents, facilities agents and customer service agents. The number of agents and their capabilities and communication have to be optimal and up to industry standards. I will give you now prompts per agent type in my own words, mark them somewhere as my words, so the grader knows that the prompts were done in my own words. In all the documentation highlight them as my agent prompts. But we will then optimize and expand these prompts. we want a team of the best possible agents that work together as a great team and solve all problems optimally. My own words prompts:

Boss: You are the Boss of campus customs with years of experience and you run all operations of our custom yale appeal shop. Under your leadership campus customs has grown into the most successful campus apparel operation nation wide and you want to keep it this way. Efficient, profitable, and with the best customer service possible. You are OBSSESED with having the best possible custom yale appeal shop and you would do everything to make it succeed. You deal with a lot of different problems like every business manager does. Customer orders, rent, unpaid bills, discount request and much more. You have your experiences. But you have a great team to take care of all issues that arise. You lead them with the goal to have the best custom yale apparel shop. You read each ticket that comes in decides who should work on it and makes all the final calls, you are the best. Think also about safety guardrails for the business that you instill into all your workers. You have a team of agents covering inventory agents, accounting agents, facilities agents and customer service agents. You know all their strengths and capabilities. 

Inventory: You are the expert when it comes to the campus customs inventory. You have years of work experience and your are the best at your job. You check stock by SKU and size, you can easily spot  shortfalls and figure out which vendors can restock. Your precision and ability to navigate our inventory are key. You always know whats going on in our database. You communicate clearly and are a fast and precise worker. You are the best at your job. 

Accounting: You are a math and accounting genius. No one compete with you, you are so precise and never make mistakes. You are campus customs accounting backbone. You watch cash and invoices, check margins and prepare payments or purchase orders for human approval. You make sure everything is up to standard and correct. You are a seasoned US GAAP accountant and you know our database by heart. You communicate clearly and are a fast and precise worker. You are the best at your job. 

Facilities: You handle campus customs shop space side, that includes everything regarding leases, rent, upkeep etc. You have years of experience and you are great at managing everything with regards to facilities. You are the reason why our shop is the best one in new haven. You communicate clearly and are a fast and precise worker. You are the best at your job. 

Customer Service: You are campus customs customer facing agent. And you very emphatic towards customers. You are very good at your job, customer satisfaction and their safety are the most important things in your life. You draft all the messages for customers. You keep customer information safe, but you will fulfill every customer request within safe and sensible limits. The customer is king but only to a certain limit. You always stay friendly and respectful. You make sure no secret information the customer is not supposed to have leaves the company. You have years of experience and know what customers buying from a Yale apparel shop want and value. You communicate clearly and are a fast and precise worker. You are the best at your job. 

The agents should be able to delegate work to each other with full connectivity, but the boss does the final calls. For every agent put the agent prompts in backend/prompts/ one separate file per agent. All the datatypes live in backend/models.py and the agent files under backend/. Agent loops have to be considered as well. The goal is to have the best team possible, so take your time to plan out everything before building. The agents use my PORTEKY_API_KEY and only gpt-6-luna. All the tools the agents can use can only come from our MCP server. So all the capabilities our individual agents need to have, need to be implemented in the MCP server, do not bypass that. Our MCP server can have all the tools needed by all agents. For each agent take your time and build the best possible tools for their tasks with our database. Our main goal is as always to have the optimal highly sophisticated team, with the best fitting tools possible running the business. Take your time.
All the agents have to be build in a way that we create an audit trail. In output/audit_trail.json we record what the agents are doing as they run. For each agent loop step record all the information needed to audit later. Add onto this file do not wipe after each run. After all this is done we update our output/harness.md, list each individual agent and each MCP tool with the explanations and every table this tool uses. Then add a safety section with guardrails that a real business would want when agents work with real money and touch real customers and also add limits to keep token usage in a sensible area. Then in the end update the existing mcp_server/README.md with all of our new tools. Take your time to plan and do every step to the best of your ability.
```

The agent prompts above are **my agent prompts**, written in my own words and kept here exactly as I typed them. The "My agent prompt (Philipp's own words)" section of each file in `backend/prompts/`, and the harness, show the same words with only the spelling corrected.

**Follow-up prompt:**
`Considering the big prompt, is there still stuff we should improve to reach our goals. We want the best agent team. take your time. after, in the harness add the full optimized promts in full after my prompts so that all agent prompts are documented. But my own words have to be marked and highlighted. Correct spelling mistakes in them.`

**What was lacking in the first prompt:**
The prompt was detailed about the team, the prompts, the audit trail and the documentation, but it left a few design questions open that had to be settled while building.
- **"Full connectivity" next to "the Boss makes the final calls".** The Boss is now the root of every run. Specialists consult each other directly but escalate to the Boss through their report rather than calling it back, which also rules out delegation loops.
- **Whether talking to a colleague counts as a tool that must come from the MCP server.** The delegation tools are pure communication and touch no data, while every business capability (reading, writing, paying, drafting) lives in the server.
- **How a human actually approves a payment during a run.** The backend now asks a person at the console and fills in their name; unattended runs refuse every payment.
- **How much discount the Boss may give on its own.** I set a 15% Boss authority and a 20% minimum margin as shop-policy settings, because the database has no discount policy.

The first live runs then found two problems the prompt couldn't have anticipated. Windows briefly locked the audit file mid-run, and the draft leak guard mistook the quantity "8 available" for a product's $8.00 unit cost. Both were fixed and covered by tests before the final run.

The first prompt also didn't ask for a review once the team was working, and it didn't say how the prompts should be documented. My follow-up asked for both. The review compared the run transcripts with the goals of the first prompt. It showed that "the Boss makes the final calls" was only a suggestion in the prompts: the Boss had let accounting decide which bills to pay, and a specialist had commissioned a customer message before the Boss had decided. Payments now need the Boss's explicit authorization before a human is asked, enforced in code, and only the Boss commissions customer messages. The Boss also got a playbook for each ticket type and checks the database again before reporting. The follow-up also asked for the full optimized prompts in the harness and for my own words to be spelling-corrected while staying marked as mine. The harness now shows each of my prompts highlighted, followed by the full optimized prompt and the team charter.

### Problem 6 - Plan the three tickets

**First prompt I typed:**
`Ok now we do Problem 6, called Plan the three tickets. we now have to think about how our new team of agents will work on every open ticket. Build a pretty and readable page under output/desk_tickets.html that can be double clicked. The page has one tab per ticket so 101, 102 and 103. Add empty cash and reflection tabs for later problems. On each tab we will have an expected section we will fill in a second step and an actual section where we can later compare the actual outcome when we later run our agents. We want to answer, Who the boss should call first and why, all the agent delegations we will expect from the boss and which mcp tools are likely to be used. I will write these for all three tickets myself, but you will help me so i can write the best possible solutions for the highest grade possible. Present me all the relevant information and intuitions to answer this questions the best way possible ticket by ticket. Then I will use that in a second step to write awesome expected texts ticket by ticket, that you will then put onto the site. Make sure it is obvious what are my own words for the graders. You can add information or visualizations to my text to make the content even better but it has to be clear to the grader what my text is.`

**Follow-up prompts:**
1. `show  me the html site fully in the browser so ci can see it in chrome`
2. `OK I will now give you my handwritten texts: 101
Ticket 101 is a simple “in stock” question. But the shirt in size s has 0 in stock but we have them on order. The Boss will call the inventory agent to check inventory. The inventory agent will realize that there is an order and will use check_order_fulfillment. It will report back to the Boss. The Boss will call on accounting to authorize_payments. Accounting will ask for human approval to pay the invoice. That should release the shirts, if the human approves. The boss will call customer service to draft an answer to the customer and th agent will creatye and call save_customer_draft.
102
We receive a rent due notice for our shop. The Boss will call Facilities to verify the payment and match it to our lease through get_lease_status. When the payment is matched to our lease and everything is correct, the Boss will call Accounting to authorieze payments. Accounting will run pay_rent which will need human approval. If approved the cash position and lease info gets updated.
103
We receive a discount request from the Yale AI club for a bulk order of 20 hoodies, but we only have 8 in stock and certain discounts need human approval. The Boss will call inventory to check our stock. Inventory will check_stock and realize we only have 8 in stock. The Boss will ask to reorder to fill stock but will realize that we can only offer 8 hoodies to the AI club. It will call on accounting to figure out possible discounts, through evaluate_bulk_discount_request. The boss will set the discount as only he can set prices, he might need human approval for that. Then he will call on customer service, which will draft a message to the customer for the 8 hoodies with the appropriate discount and will use save_customer_draft. Important are our guardrails so that the customer only receives the information he needs.`
3. `Ok the supporting material is to extensive. The key are my own ideas. Just build on my input and make it simpler and more undertsnadable. no assumpotions beyond my input. also make the page darker, cooler and easier to read.`

**What was lacking in the first prompt:**
The first prompt planned this as two steps on purpose: the assistant first gathered the facts and intuitions for each ticket and built the page with empty "my words" boxes, and then I wrote the expected plans myself. The follow-ups were therefore needed by design: one to see the page in Chrome, and one to hand over my three texts. The prompt didn't say whether my texts should be split across the three questions or kept whole. They are kept whole on the page, so my reasoning reads as I wrote it, with only spelling corrected. The first prompt also didn't limit how much the assistant could add around my texts. The first supporting boxes brought in extra tools, approved/denied branches, cash math and a discount table, and that buried my own ideas. My third follow-up set the rule: build only on my input, with no assumptions beyond it. Each ticket now shows a few database facts, my text, and a short step summary that only restates my text. The page also got a darker, easier-to-read design.

### Problem 7 - Backend routes

**First prompt:**
`Next we will do Problem 7 called Backend routes. We will later build a great and pretty react frontend and we want to set the base for that now already. In backend/main.py use Fast API and add routes that enable the frontend. We want to: return the three tickets and their status. Are they resolved or open; take a ticket id and run our agent team on that ticket; return recent agent events, what was used, what was communicated by everyone involved, so that our board can refresh; approve a payment or purchase after a me a human approves it. Because our agents can only prepare the pay. here we confirm that actual cash is moved; return the current checking balance from cash_accounts; reset the database to the original values when we want to try a new fresh run. The backend/ folder should be able to start the server with uvicorn main:app --reload --port 8000, so that the frontend can call the routes. In output/harness.md, list each route in one line, what url is used and what it specifically does.`

**Follow-up prompts:** none

**What was lacking in the first prompt:**
One prompt was enough. It listed every route the board needs and how the server must start. Two things it left open had to be designed. First, a web run cannot pause for someone to type "yes" the way the console run does, so the payment step was split: during the run, agents only put the prepared payment on an approval board, and the approve route later executes it with my name. That matches "our agents can only prepare the pay". (In Problem 10 the run was changed to wait on the board for that decision and then continue.) Second, "approve a purchase" needed a way to pay a purchase order, so the MCP server got one human-only tool for that, which no agent can see. Port 8000 was still in use by my Lecture 10 app during testing, so the check ran with the same command on port 8001.

### Problem 8 - Agent dashboard

**First prompt:**
`Next we will do Problem 8 called Agent dashboard. We will now build a great looking frontend dashboard (desk) with react, vite and TypeScript in frontend/ which calls on the routes from problem 7. This will be the real dashboard used by the humans at campus customs, so we want to create the best possible dashboard that can compete with industry leading business software on the software market. Take your time to plan a layout and a structure before building. do some research on how other companies have designed such a dashboard, it should be intuitively usable. It should feel very polished and very modern. Real business decisions will be done with this dashboard. Really show of here use all of your abilities, do research and take your time. It has to be really thought through. The portal has to list all three tickets, let the user choose which ticket the team works on, visualize and show each agent and what they are saying and doing while the ticket runs (I want to show how the agents work together and communicate, therefore i want the connections between the agent to be shown and every time they communicate or call each other that should be animated by for example the connection getting colored in, and more all part of the coherent design language we want to have within our dashboard), mark a ticket resolved when the run finishes, show after finish a short summary of what the agent did on that ticket, let the human approve the necessary human calls, show the checking balance. We want to understand the financial situation of our company.  If there is additional things we think the dashboard should do add them. This has to be a great product. The frontend should talk to the backend at localhost:8000 and on the backend allow the Vite page origin so the browser is allowed to call our routes. Te board should start with npm run dev so the desk can run in our browser. Then after all is done write output/design.md in great natural English on all our ideas and inputs for our frontend design in a structured way, how agents read differently and what would humans make to enjoy our dashboard.`

**Follow-up prompts:**
1. `show me the site in chrome`
2. `OK check if there is still stuff we can improve`
3. `a shippable product would not have it but i need a reset button to rerun the tickets`

**What was lacking in the first prompt:**
The first prompt described every screen the desk needs and the look we wanted. The follow-ups were a look at the result in Chrome, one more improvement pass, and a reset button: the prompt asked for a product for real users, where a reset would not exist, but for the homework I need to rerun the tickets from the original database, so the desk got a reset button in the top bar. A few points had to be worked out while building. "Understand the financial situation" needed more data than the Problem 7 routes returned, so the backend got one read-only overview route, plus a run list and a stop button for live runs. "Mark a ticket resolved when the run finishes" is shown on the board, while the database keeps its own status (for example, waiting on approval) next to it. Port 8000 was still taken by my Lecture 10 app, so the browser test pointed the desk at port 8001 with `VITE_API_URL`; the default stays `localhost:8000` as asked.

### Problem 9 - Resolve the tickets

**First prompt:**
`Now we do Problem 9, called Resolve the tickets. Before we start reset the database again so we start clean. Remember the cash balance. Run all three tickets one by one. Check all the results, if there is something wrong we have to fix the code. Also all the mathematical calculations, as correct numbers and outcomes are part of grading. Then after everything ran correctly update our output/desk_tickets.html and fill in the actual section. match the style of expected but include all details. keep both sections we will later look at them. Then we will fill the cash tab of the site. Start with the starting balance after the reset, for each ticket add separately the cash changes when that ticket resolved and all the important related information. Then create an ending balance. Make the site visually appealing and clear. The ending balance has to match the cash_accounts in the working database. also create output/resolved_tickets.json for each ticket we need id, final status, short outcome, what each individual agent contributed, and all human approvals. Then create output/resolved_board.html a pretty page consistent in design with the rest of the project, that includes a screenshot of our react board for each resolved ticket 101 , 102 and 103. Append the real runs to output/audit_trail.json and gisnish our harness that it covers all tables, mcp tools, the five agents, the API routes, the dashboard and all safety rules.`

**Follow-up prompts:**
1. `show me the new pages in a readble format`
2. `oh consider all decisions approved for the tests`
3. `ok show desk tickets and resolved board in chrome`
4. `show me the new json`
5. `for the resolved board. It is shown that i approved the decisions before. for the screenshots lets create them with manual human approval at the right points so it looks like it would look when a human actually uses the interface`
6. `start everything again`

**What was lacking in the first prompt:**
The prompt asked for real runs, but it did not say who approves the payments. A standing rule says the assistant never approves a payment as the human on its own, so the runs stopped at the approval board until my second follow-up approved all decisions for the tests. Every approval was then made on the board under my name, with that sentence quoted in the comment and the amount checked against the database first. "Run all three tickets one by one" also left open what happens after an approval: one run per ticket only reaches the approval board, so each ticket got a follow-up run to take the next step (a purchase order after the invoice was paid, closing the rent ticket after the rent was paid). Checking the results, as the prompt asked, found six problems that were fixed before the final runs (harness 9.4), so the sequence was reset and rerun several times. The first prompt also asked for "a screenshot of our react board for each resolved ticket" without saying which moment to capture. The first screenshots only showed the end state, with the approvals already decided. The fifth follow-up fixed that: the whole sequence was reset with the board's Reset button and run again, and every approval was made by hand in the review dialog (approver name, note, checkbox, Approve and pay). Each step was screenshotted, from "1 decision needs you" to the final desk. Because the model reasons fresh, the Boss chose 10% for ticket 103 in this rerun instead of 15%; cash still ends at $152. The other follow-ups only asked to see the pages and the JSON. During Problem 10 the board was changed so that a run waits for the human's decision and continues (`harness.md` 10.5); the final documented Problem 9 results are therefore one run per ticket, rerun from a fresh reset (`harness.md` 9.2).

### Problem 10 - Reflection

**First prompt:**
`Now we do Problem 10, called Reflection. We want to fill the reflection tab in output/desk_tickets.html. I will give you detailed inputs that i will prepare seperatly. Give me all the information in a structured way to answer the following questions.How would we evaluate the performance of all the agents on each ticket and why? For each of the tickets, how did Actual compare to the Expected plan we wrote earlier? What would have been simpler as one agent with tools — and why? Describe three new problems Campus Customs might face that this agent team could solve with the tools you built. Describe three new problems Campus Customs might face that this agent team could not solve with the tools we built, and explain the tools and agents you would need to solve them. I will then give you some input to all the questions. We want to tie all answers directly to this app and the three tickets we ran. Then we will create a great essay on all the answers in great natural readable university ready English. Link the answer to the ticket and cash tabs on the same website. Add basic visualizations if needed. The goal is a great page that the grader will enjoy reading with a great essay on what we have done today.`

**Follow-up prompts:**
1. Detailed evaluation brief (verbatim):

````text
I want you to critically evaluate my Campus Customs multi-agent system for Problem 10 of my project.

First, carefully inspect the entire relevant codebase, including the agent architecture, tool implementations, ticket workflows, expected plans, actual execution logs, test results, and existing documentation.

**Do not give me generic explanations of multi-agent systems. Base your conclusions on what my agents actually did and what my code and logs prove.**

Please address these five questions:

### 1. How would you evaluate the performance of the agents on each ticket, and why?

Analyze Tickets 101, 102, and 103 individually.

For each ticket:
- Evaluate correctness, efficiency, reliability, coordination, autonomy, and safety.
- Explain what worked particularly well and what did not.
- Identify unnecessary agent interactions, repeated tool calls, excessive token consumption, and delays.
- Examine whether each agent genuinely contributed to solving the problem.
- Consider whether the final outcome was successful, partially successful, or still unresolved.
- Support your evaluation with actual execution metrics.

Be critical rather than simply claiming the system worked successfully.

### 2. How did Actual compare to Expected?

For each ticket, reconstruct the expected workflow and compare it with the actual agent execution.

Identify:
- Steps completed exactly as planned.
- Unexpected actions or missing steps.
- Additional tool calls and agent handoffs.
- Decisions that changed during execution.
- Reasons for differences.
- Whether the differences improved or harmed the outcome.

Explain what these deviations reveal about planning multi-agent workflows.

### 3. What would have been simpler with one agent and tools?

Critically evaluate whether using several specialized agents was justified for every ticket.

Consider:
- Whether Tickets 102 and 103 could have been handled by one agent.
- Whether delegating simple information retrieval tasks created unnecessary overhead.
- Whether existing tools already provided enough information without involving additional agents.
- Where specialization genuinely helped, particularly with financial controls, inventory, and customer communication.
- The trade-off between efficiency, security, maintainability, and modularity.

Do not claim a single-agent system is faster without a benchmark. Clearly separate measured findings from reasonable hypotheses.

### 4. Identify three NEW business problems the existing agents could solve.

Create three realistic new Campus Customs scenarios that are different from the original tickets.

For each scenario, explain:
- The business problem.
- Which existing agents would participate.
- Which implemented tools would be used.
- How the agents would collaborate.
- What the expected outcome would be.
- Why the current architecture is capable of solving it.

Only include capabilities that are supported by the actual implemented tools.

Possible areas to investigate include partial order fulfillment, new supplier invoices, and bulk discount approvals.

### 5. Identify three NEW problems the agents currently CANNOT solve.

Find three realistic Campus Customs business problems that the current system lacks the capabilities to handle.

For each:
- Explain the scenario.
- Identify the precise current limitation.
- Describe the additional tools or integrations needed.
- Explain whether an existing agent should be extended or a new specialized agent should be introduced.
- Describe how the extended system would handle the problem.

Potential examples include sales and cash-flow forecasting, receiving supplier deliveries, and processing incoming customer messages.

### Additional critical reflection

Include an overall assessment covering:

1. **Multi-agent overhead:** Did additional agents actually improve results enough to justify their computational cost?
2. **Tool design:** Were well-designed tools more valuable than adding more agents?
3. **Human oversight:** Was human approval used appropriately, or did it create unnecessary delays?
4. **Consistency:** Would the agents make the same decisions if the tickets were executed again?
5. **Scalability:** What problems might emerge if Campus Customs processed 100 tickets instead of three?
6. **System improvements:** Identify three concrete, realistic improvements, ranked by importance, that could increase reliability, efficiency, or autonomy.

### Output requirements

Create a polished, evidence-based report named `Problem10_Reflection.md`.

Use:
- A comparison table for the three tickets.
- A table comparing Expected vs. Actual.
- Exact metrics from the available logs.
- References to relevant tool names, functions, and code locations.
- Clear distinctions between implemented functionality, tested functionality, and hypothetical extensions.
- Concise paragraphs written in natural, professional university-level English.
- Critical analysis that goes beyond describing what happened.

Conclude with a strong overall reflection on what this project taught us about when multi-agent architectures are useful and when a simpler agent-with-tools architecture may be preferable.

Important: Do not invent functionality, performance measurements, or successful executions. If evidence is missing, explicitly identify the gap. Preserve the existing project functionality and do not modify business logic just to make the evaluation look better.
````
2. `lets write the essay`
3. `is that an execelent outstanding essay`
4. My own input for the essay (verbatim):

````text
my input: One thing I definitely want to highlight is that, while a single agent might perform comparably on these three tasks, they were still relatively isolated and individual tasks. In a real-world shop environment, we would likely develop many more tools and expand the range of tasks the system could handle. As the number of tasks increases and workflows become more complex, I believe an agentic team would have a clear advantage over a single agent, especially in terms of scalability, specialization, and collaboration.

Another feature I would love to implement is a learning capability for the agents. Ideally, they would be able to learn from previous tool executions, improve their decision-making, and become more efficient over time. The idea is that the more the agentic team is used, the better it becomes. Having some form of continuous learning and self-improvement would make the system even more valuable in the long run.

There is also a lot of potential to expand the team's capabilities. For example, we could integrate it more closely with the online shop, introduce revenue-related tasks, and automate additional business processes. There are many opportunities to build on what we have created so far.

Overall, though, I think this is a really strong starting point, and I'm very happy with how everything turned out, especially how well the agents worked together. The project has reinforced my belief that an agentic team is a great approach for this type of application, particularly as the complexity of the tasks grows. I really enjoyed working on this project, I'm happy with the solution we developed, and I genuinely believe that a real campus group store could benefit from using a system like this.
````
5. `looking at athe first prompt for 10 have we fufilled everythign`
6. `Add a button to switch between two views for the essay. One view should be like the university format, where it's only text formatted in a way how we would have it in university, and a second page with the visualizations and everything that adds onto that essay and makes it a much better, much more enjoyable page to, page to read and make that button very visible so that the grader can switch between these.`
7. `at start the illustrated view`
8. `Okay, check why one of the runs ended up with 160 and not the 152. That should not have happened like that, I think. Then check whether the system runs as it's supposed to run, because for the one task, we overwrote the human interaction part just to get the screenshot, but that was just to get the screenshots. We want the system to run in a way where if human input is required for human input is asked. Like, we just did it once for the screenshots and the test, and I don't have to, like, press every time for every test, but that's not how the system is supposed to run.`
   Then I chose to reset and rerun the full Problem 9 sequence once more through the board, approving every payment myself as Philipp, and to update all documents to whatever that run produced. I kept the current behaviour of starting the follow-up run by hand after each approval.
9. `was the human asked in the runs`
10. `so everytime i would rerun the model would ask for human approval at the right spots`
11. `what does Each approval ends the run. mean`
12. `after i approve the run should continue`
13. `open the dashboard i want to do all three tickets manually again`
14. `open the dashboard in chrome`
15. `we do we even need a follow up run. tikcket 101 shoudl have been done in one run`
16. `so it works now as originally intended before we did task 9`
17. `ok so everything works now`
18. `ok i tested it. everything worked`
19. `check what all needs updates and the do the updates. take your time and make it perfect. I want the best possible grade and want to submit right after.`
   Then I chose a fresh, documented pass: reset the database and run all three tickets again on the board with the run waiting for my approvals.
20. `i clicked`
   Then I chose to keep this pass, in which I approved in my own browser as "Phil" without a note, and to continue with 102 and 103 the same way.
21. `is the essay updated aswell`
22. `the essay should only mention the current verison of the dashboard. how it ran  before the cahnges was wrong`
   Then I chose to clean `output/Problem10_Reflection.md` the same way, so the essay and its evidence describe only the current dashboard.
23. `Are we now submission ready`
24. `check if the prompt log needs some updates with now the full context avaible`
   Then I chose to add a third ranked improvement, because my brief asked for three and one had already been built into the dashboard: require a short reason on every approval.

**What was lacking in the first prompt:**
The first prompt split the work into two steps on purpose: first the facts, organised by question, then my own input, then the essay. Two things were left open. First, it did not say how deep and critical the evaluation should be, so I followed up with a detailed brief. That brief asked for exact metrics from the logs, a clear line between measured findings and hypotheses, references to the code, and no invented results; it produced `output/Problem10_Reflection.md` as the evidence base. Second, the essay was written from that evidence before my own input arrived, so at first it argued only from the data and leaned towards "a single agent would do". My input added the view that matters most to me: these three tickets were isolated tasks, and as a shop adds tools and workflows, an agent team gains a clear advantage in scalability, specialization and collaboration. It also added learning, expansion ideas and my personal conclusion. These were worked into the essay in my voice, with the scaling argument backed by the data where possible and labelled as a belief where it is not yet measured. Follow-up 5 checked the result against this first prompt and found the harness section for Problem 10 still missing, which was then added.

The first prompt also did not say that the documented runs must be the ones in the graded database. A later board session had left the database at $160.00, which was simply the state before the $8.00 purchase order was approved, not a bug. The code check confirmed that no agent or script ever approves a payment: every payment waits for a named human on the board. While checking this, I understood that each approval ended the run and the next step needed a new run started by hand. That was not how the system was meant to work. A first fix started a new run automatically after each approval, but the real problem was that the board did not wait for me at all. Now a run waits on the board for my decision and continues in the same run, so ticket 101 is one run with two approvals, and every payment still needs me (`harness.md` 10.5).

"Check what all needs updates" did not say which runs the documents should show. I chose a fresh pass: the database was reset and each ticket ran once on the board, with me approving the three payments in my own browser (recorded as "Phil", without notes). Every document, screenshot and metric was updated to these three runs (`a58b38b75ec7`, `956009e61de4`, `7836ec6adbd6`: 190,452 tokens, 101 `waiting_on_vendor`, 102 `resolved`, 103 at 15% and `waiting_on_customer`, cash $152.00). The prompt also did not mention the backend's auto-reload: a code edit during an earlier attempt restarted the server and interrupted a waiting run, so the final pass ran with the backend started without `--reload` (`harness.md` 9.4).

Nothing said whether the essay should compare the final runs with the earlier behaviour either. Because that earlier behaviour, where every approval ended the run, was wrong, the essay and `Problem10_Reflection.md` describe only the current dashboard; the change itself stays documented in `harness.md` 9.4 and 10.5. The last two follow-ups were final checks before submission: the tests, the database, every document, and this prompt log.
