# Agent Roadmap

Future AI agent layer for the VC Tracker. Each agent runs as a background job (see architecture notes at the bottom).

---

## Planned Agents

### 1. Patent Intelligence Agent
Pulls and summarizes patent filings for a given portfolio company.

**What it does:**
- Searches USPTO, Google Patents, and/or Espacenet for patents assigned to the company
- Identifies filing trends (volume over time, technology categories, IPC classifications)
- Flags competitive patent activity from known rivals
- Produces a structured summary: total patents, key claims, moat assessment, active litigation if any

**Inputs:** Company name, optional ticker or domain
**Output:** Structured JSON + markdown summary stored in `agent_runs`, attached to the private position

**Data sources to evaluate:** USPTO PatentsView API (free), Google Patents Public Data (BigQuery), Lens.org API, SerpAPI Google Patents

---

### 2. Valuation Builder Agent (DCF / Multiples)
An interactive agent that walks the user through building a company valuation from scratch.

**What it does:**
- Prompts the user through the key assumptions needed for a chosen methodology
- DCF track: revenue growth, EBITDA margin, terminal growth rate, WACC, discount rate, forecast period
- Multiples track: selects appropriate comp set, pulls or accepts EV/Revenue or EV/EBITDA multiples, applies to current or forward metrics
- Shows sensitivity tables (e.g., what the valuation looks like across a range of growth rates × discount rates)
- Saves the final model as a structured artifact attached to the thesis or position
- Can re-run with updated assumptions and show what changed

**Inputs:** Company name, stage (early/growth/late), methodology choice (DCF, revenue multiple, EBITDA multiple, ARR multiple)
**Output:** Valuation model JSON with assumption log, sensitivity table, and implied range — stored in `agent_runs` and surfaced in the UI next to the position

**Notes:**
- For private companies, the user provides metrics manually (no market data)
- For later-stage companies, the agent can attempt to pull comparable public multiples via yfinance or a financial data API
- Should save each version so assumptions can be tracked over time (version history)

---

### 3. VC Scorecard Agent
Learns established VC evaluation frameworks and applies them to a company the user is analyzing.

**What it does:**
- Ingests one or more VC scorecard methodologies (Berkus Method, Risk Factor Summation, Scorecard Valuation Method, First Chicago, SAFE/cap table analysis)
- Prompts the user for the inputs each method requires (team quality, market size, product stage, competition, traction, etc.)
- Scores the company across each dimension and produces a composite score with written rationale
- Compares the score to the user's existing portfolio companies to calibrate relative attractiveness
- Surfaces which scorecard inputs are weakest (risks) and strongest (conviction drivers)

**Inputs:** Company name, user-supplied qualitative and quantitative inputs, optional attachment of pitch deck or memo for the agent to extract signals from
**Output:** Scorecard JSON with per-dimension scores and rationale, overall ranking vs. portfolio, stored in `agent_runs`

**Notes:**
- The agent should support uploading a custom scorecard template (PDF or CSV) so users can teach it firm-specific criteria
- Scorecard results should be comparable side-by-side across portfolio companies

---

### 4. Summary Agent
On-demand or scheduled summaries of a thesis, company, or entire portfolio.

**What it does:**
- **Position summary**: given a private position, synthesizes all attached notes, files, agent outputs (patent report, scorecard, DCF), and performance data into a 1-page investment memo
- **Thesis summary**: rolls up all companies within a thesis — current performance, key risks, overall thesis health
- **Portfolio digest**: weekly or on-demand email/notification summarizing portfolio performance, notable changes, upcoming liquidity events, and agent findings from the week
- Can also produce a "what has changed since last summary" delta view

**Inputs:** Entity to summarize (position, thesis, or full portfolio), optional time window
**Output:** Markdown memo stored in `agent_runs`, optionally emailed

---

### 5. Orchestrator Agent
Oversees all other agents and decides when to run them.

**What it does:**
- Monitors the portfolio for trigger conditions (new position added, liquidity date approaching, significant valuation change, user request)
- Routes to the appropriate agent(s) based on trigger type
- Chains agents when appropriate (e.g., after a new company is added: run Patent → Scorecard → Summary in sequence)
- Manages retries and error recovery across agent runs
- Surfaces a feed of recent agent activity in the UI ("Patent report ready for Stripe", "Valuation model updated for AI thesis")
- Tracks which agents have run on which entities and when, so it can prompt the user to refresh stale analyses

**Inputs:** Internal event stream (DB changes, user actions, scheduled triggers)
**Output:** Dispatches jobs to worker queue, updates `agent_runs` table, sends notifications

---

## Architecture Notes

These agents should NOT run in the FastAPI request cycle. They need a background worker layer.

### Recommended Stack

```
Railway Web Service (FastAPI)     — handles HTTP, auth, serves UI
Railway Worker Service (RQ)       — runs agent jobs from queue
Redis (Railway add-on)            — job queue between web and worker
Postgres (Railway add-on)         — replace SQLite when multi-service needed
```

### Database Tables to Add

```sql
-- Tracks every agent job
CREATE TABLE agent_runs (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    entity_type   TEXT,          -- 'thesis', 'position', 'private_position'
    entity_id     INTEGER,
    agent_type    TEXT,          -- 'patents', 'dcf', 'scorecard', 'summary', 'orchestrator'
    status        TEXT,          -- 'pending', 'running', 'done', 'error'
    inputs        TEXT,          -- JSON of what was passed in
    result        TEXT,          -- JSON or markdown output
    error_detail  TEXT,
    model_used    TEXT,          -- which LLM version was used
    created_at    TEXT,
    completed_at  TEXT
);

-- Versioned valuation models saved by the DCF agent
CREATE TABLE valuations (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    entity_id     INTEGER,       -- private_position id
    methodology   TEXT,          -- 'dcf', 'revenue_multiple', 'ebitda_multiple'
    version       INTEGER,
    assumptions   TEXT,          -- JSON
    result_low    REAL,
    result_base   REAL,
    result_high   REAL,
    notes         TEXT,
    created_at    TEXT
);

-- Scorecard results
CREATE TABLE scorecard_results (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    entity_id     INTEGER,
    methodology   TEXT,          -- 'berkus', 'risk_factor', 'scorecard', 'custom'
    scores        TEXT,          -- JSON: {dimension: {score, rationale}}
    composite     REAL,
    created_at    TEXT
);
```

### LLM Integration

Use the Anthropic SDK with `claude-sonnet-4-6` as the default. Agents that need structured output (scorecard scores, DCF assumptions) should use tool use / structured output mode. Agents producing narrative (summaries, patent memos) can use standard completions.

```python
# Pattern for each agent
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

def run_patent_agent(company: str, user_id: int, run_id: int):
    # 1. Fetch raw patent data from API
    # 2. Pass to Claude with a structured prompt
    # 3. Parse response into JSON
    # 4. Update agent_runs row with result and status='done'
```

### API Keys Needed (Railway env vars)

| Key | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | All agents (LLM calls) |
| `USPTO_API_KEY` | Patent agent |
| `SERPAPI_KEY` | Patent agent (Google Patents fallback) |
| `REDIS_URL` | Job queue (auto-set by Railway Redis add-on) |

---

## Implementation Order

1. Add `agent_runs` table and worker infrastructure (Redis + RQ on Railway)
2. Build Patent Intelligence Agent — most self-contained, no user input loop needed
3. Build Summary Agent — depends only on existing data, good test of the output format
4. Build Valuation Builder Agent — requires interactive multi-turn UI flow
5. Build Scorecard Agent — requires custom template ingestion
6. Build Orchestrator — connects everything, add last once agents are stable
