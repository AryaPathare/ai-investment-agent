# Project Log

A running record of what was built, what went wrong, and why each decision was
made. Written as it happens rather than reconstructed afterwards, because the
reasoning behind a decision is the first thing lost once the code works.

**Append a new session section at the end of every working session.**

---

## The project

A multi-agent investment research system. It takes an investor's profile,
researches current market themes from real news, finds public companies
genuinely exposed to those themes, attacks the thesis, and recommends up to
three stocks — or explicitly recommends **nothing** when nothing clears the bar.

**Stack:** Python 3.14, LangGraph, Pydantic 2, Groq (`openai/gpt-oss-20b`),
TheNewsAPI, Financial Modeling Prep, yfinance.

**Purpose:** a portfolio and interview project. That goal shapes what "done"
means — the system has to be defensible under questioning, not merely running.

### Pipeline

```
START → Profile → (valid) → Research → Companies → [Risk Critic] → [Decide] → END
              ↳ (conflict) → ask user → back to Profile
```

| Stage | Job | State |
|---|---|---|
| 1. Profile | Validate investor input; ask about genuine contradictions | Built |
| 2. Research | Identify themes, grounded in retrieved news | Built |
| 3. Companies | Extract, resolve, screen and rank companies | Built, eval pending |
| 4. Risk Critic | Adversarially attack each candidate | Planned |
| 5. Decide | Score, select, state exit conditions | Planned |

---

## Principles that shaped every stage

These emerged early and were applied consistently. Most of the interesting work
follows from them.

**LLMs judge; Python computes.** Anything calculable or checkable stays in code.
A negative investment amount is rejected by Pydantic, not reasoned about. Models
are used only where genuine ambiguity requires judgement — and in Agent 3, only
two of nine pipeline steps need one.

**The model returns a verdict, never the data.** Applied three times in three
different disguises:

- Agent 1: the model cannot emit the user's age or investment amount, so it
  cannot corrupt them.
- Agent 2: `Evidence` has no `url` or `title` field, so a fabricated source is
  impossible rather than discouraged — it can only cite an article Python
  already retrieved.
- Agent 3: `CompanyMention` has no ticker field. `NVDA`, `NVDA.NE` and `NVD.DE`
  are all real symbols for Nvidia, so a guessed one does not *look* wrong; it
  silently returns a different company's financials.

**Encode rules in types, not comments.** A comment saying "never compare these
across currencies" gets ignored eventually. Splitting `ComparableMetrics` from
`CurrencyAmounts` means reaching the wrong one requires crossing a type
boundary.

**Every loop is bounded by code, never by the model.** A model is never trusted
to decide when to stop.

**Rejections are recorded, not discarded.** `drop_summary` is what distinguishes
"3 candidates from 30 mentions" as good filtering from the identical numbers
produced by a broken resolver.

**Coarse judgements over invented precision.** `high/medium/low` and
`direct/partial/incidental` instead of 0-100 scores. A model asked to score
something 0-100 returns 72 with nothing behind it.

**Returning nothing is a designed outcome.** At every stage — no themes, no
companies, no recommendation — "nothing cleared the bar" is a legitimate answer
rather than a failure.

---

## Session 1 — 2026-08-19 → 2026-08-20

### Starting point

A working prototype built in a previous tool: Agent 1 validated investor
profiles and paused for clarification via a LangGraph `interrupt`. It ran. A
review found four structural problems, none of them visible from the output.

### What was done

Rebuilt Agent 1, then built Agents 2 and 3. 32 commits.

### Agent 1 — hardening

| Problem | Fix |
|---|---|
| Unbounded clarification loop | Bounded at 3 attempts with a defined give-up outcome |
| Each clarification overwrote the last | `Annotated[list[str], add]` accumulates them |
| The LLM could silently rewrite user data | Model returns a verdict; Python composes the profile |
| Tests were scripts that hung on `input()` | 58 real tests, no network, 0.3s |
| No config, no timeouts, globals at import | `config.py` with lazy, validated settings |

The schema change is the one worth remembering. `InvestorProfile` had been the
schema handed to `with_structured_output()`, so the model re-emitted the user's
age, amount, interests and restrictions on every call and could alter any of
them. It now returns `ProfileAssessment` — a verdict plus a narrow whitelist of
fields a clarification may legitimately revise.

**A prompt rule got deleted as a result.** Rule 1 had said "Preserve the user's
information. Do not invent new preferences." That existed only to compensate for
the schema flaw. Once the model structurally could not touch those fields, the
rule became dead weight. *When a prompt rule is patching a design problem, fix
the design.*

**Scope was cut, deliberately.** The original plan had 8 agents, 4 external
APIs, SQLite, a scheduler and backward routing. It became 5 agents, one or two
APIs, no database, no separate supervisor:

- **Agent 8 (monthly monitoring)** — a long-running service, not a pipeline
  stage. Needed a scheduler, position tracking and stored baselines. Substitute:
  re-run the pipeline.
- **GDELT** — an event database for geopolitical analysis, not a
  trend-identification tool. Old Agents 2 and 3 merged into one Research agent.
- **SEC EDGAR** — duplicates FMP and requires XBRL parsing.
- **The Supervisor** — everything left of its job is a LangGraph feature: edges
  for routing, `retry_policy` for retries, `interrupt` for clarification,
  Pydantic for validation. An LLM router would be *less* reliable than edges.

### Agent 2 — Research

Search first, *then* synthesise. Asking a model what trends matter and then
hunting for support is confirmation bias with a training cutoff attached. It
retrieves real articles, then asks the model to read them.

Citations use short labels (`[A3]`) because a model copies two characters
reliably and a 36-character uuid unreliably. Python maps them back and discards
any that do not exist.

### Agent 3 — Companies

Nine steps, two of which need a model: spotting which companies an article
names, and judging whether a company is genuinely exposed to a theme or merely
appeared in the same paragraph.

Exposure is graded per **company-theme pair**, not per company. The test that
proved it mattered:

```
Northern Trust vs AI data centre buildout  → incidental
Northern Trust vs bank share buybacks      → direct
Nvidia         vs AI data centre buildout  → direct
Nvidia         vs bank share buybacks      → incidental
```

Ranking is pure arithmetic over provider figures. The model contributes exactly
one input — the exposure level. Screening rejects only what is genuinely
disqualifying, and notably **not** high leverage on its own: a blanket
debt-to-equity threshold would silently exclude every bank, insurer and utility
from a system meant to research banking themes.

---

## Bugs found — the interesting part

Every one of these produced *plausible output*. None would have been caught by
looking at the results.

### 1. The search year that quietly degraded relevance

The model appended its training-cutoff year to every query:
`"solar farm approvals 2024"`. First assumption was that this would fight the
date filter and return nothing. **Measuring it proved that wrong** — article
counts were identical. But the *articles* were worse:

| Query | Top results |
|---|---|
| `solar farm approvals` | a solar farm upgrade, solar-powered farming |
| `solar farm approvals 2024` | an asset acquisition in Poland, diesel generators |

The year pulls in articles that merely *mention* it. **"It returned results" is
not "it worked."** The fix went into the prompt with the measurement attached,
so nobody deletes the rule later wondering if it matters.

### 2. Deduplication that merged different stories

Title-similarity dedup scored these at ~0.97:

```
"Tesla Q2 earnings beat expectations"
"Tesla Q3 earnings beat expectations"
```

Financial headlines are formulaic and differ in exactly the token that carries
the meaning — a quarter, an amount, a capacity. Merging them destroys evidence,
which is the failure dedup existed to *prevent*. Numbers in both headlines must
now match before similarity is considered. Found by writing an adversarial test,
not by observation.

### 3. A config edit that silently disarmed Agent 1

An index-based slice while editing `config.py` swallowed the section between two
anchors, deleting `max_clarification_attempts` — the setting bounding Agent 1's
loop. Seven tests failed instantly, all of them the loop-bound tests written the
day before.

**This is what tests are actually for.** Not proving code works when you write
it — proving it still works after you touch something unrelated. Without them,
a config edit made while building Agent 2 would have removed Agent 1's
termination guarantee, and nothing would have complained until it ran forever in
front of a user.

### 4. Three resolution bugs, all caught by `drop_summary`

The first real Agent 3 run produced four candidates and looked like success. The
rejection list did not:

```
AMD        not_an_operating_company     ← AMD is obviously a real company
Google     not_an_operating_company
Synopsys   no_fundamentals
Marvell    no_fundamentals
```

- **Word matching rejected correct answers.** "AMD" shares no word with
  "Advanced Micro Devices, Inc."; "Google" none with "Alphabet Inc." The guard
  that saved us from a cryptocurrency matching "SMIC" created a new failure.
  Fixed by accepting *either* a name match or a symbol match.
- **FMP's free tier covers only a subset of US symbols**, not merely US-only.
  AMD and NVDA work; SNPS and MRVL, both major Nasdaq companies, return 402.
  Now falls back to yfinance.
- **A tie was broken by luck.** "SMIC" matched the Hong Kong primary listing and
  a Singapore depositary receipt equally, so the winner depended on search
  ordering — which changed between runs. *Nondeterminism producing a plausible
  answer is the worst kind: it does not look like a bug.*

**Without `drop_summary`, this would have shipped.**

### 5. A fund filter defeated by changing metadata

`SPCF` ("ProShares Ultra SpaceX") was rejected correctly using `quoteType=ETF` —
then an hour later the same ticker reported `quoteType=EQUITY, legalType=None`.
Same code, same ticker; the upstream data changed.

Not a bug in the implementation. **The lesson: when a check guards something
important and rests on one external signal, get a second signal that fails
differently.** Fund *names* (sponsors, leverage markers) are marketing terms and
effectively stable. The blocklist deliberately excludes generic words like
"trust" and "fund" — verified that Northern Trust and Ultra Clean Holdings still
resolve.

### 6. Structured output: right data, wrong envelope

Every schema wraps a single list, and the model regularly returns the bare list
instead of `{"mentions": [...]}`, sometimes inside a ```json fence. The provider
rejects it and the call fails — discarding *correct* extracted data.

Two things made this worth a real fix:

- It survived **three identical retries**. Deterministic, so retrying only
  spends another call to be told the same thing.
- It happens under **both** structured-output methods, merely on different
  schemas: `function_calling` failed on `MentionExtraction`, `json_schema` on
  `ThemeProposal`. Switching methods trades one failure for another.

`agents/structured.py` now recovers the rejected generation, strips the fence,
wraps a bare list, and **re-validates against the schema exactly like a normal
response**. Verified that valid JSON violating the schema is still refused: this
loosens the transport, never the contract.

### 7. An eval that measured the wrong thing

The Agent 3 eval reported "1 mention vanished without a drop reason." It was
balancing candidates and drops against *mention rows* — but a company named in
three articles is three mentions and one company. The check was right; its
denominator was not. `companies_examined` was added so the balance is
meaningful.

---

## Provider facts learned by probing, not from documentation

| Provider | Fact | Why it matters |
|---|---|---|
| Groq | `max_tokens` counts against the tokens-per-minute quota **even when unused** | One global value big enough for the largest call makes every small call expensive; budgets are per call |
| Groq | `gpt-oss-20b` is a **reasoning** model — it spends tokens before the visible answer | Budgets must be far larger than output length suggests; 512 truncated a six-item list |
| Groq | Limits are 8,000 tokens/min **and 200,000/day**, a rolling window | ~30 full pipeline runs per day on the free tier |
| TheNewsAPI | Cloudflare rejects urllib's default user-agent with `403 error 1010` | Must use `requests` plus an explicit UA |
| TheNewsAPI | Default search covers **all history** sorted by relevance | Returned 2023 articles for a current-events agent; `published_after` is mandatory |
| TheNewsAPI | Free tier: 100 req/day, **3 articles per request** | Design uses several narrow queries rather than one broad one |
| FMP | `/api/v3/*` endpoints are **dead** (403, legacy-only since Aug 2025) | Nearly every tutorial online shows v3; `/stable/*` works |
| FMP | Free tier is 250 req/day and covers only a **subset of US symbols** | Search returns foreign symbols happily, then data requests 402 |
| yfinance | Reports `debtToEquity` as a **percentage**; FMP as a **ratio** | Exactly 100× apart — unnormalised, every yfinance company screens as distressed |
| yfinance | Its **search is better than FMP's** | FMP returned a cryptocurrency for "SMIC" and Canada for "Nvidia" |
| Both | Fundamentals arrive in local currency — USD, HKD, INR, **GBp** (pence) | Only the four unitless ratios are cross-comparable |
| Windows | Console is cp1252 and cannot encode model output | Killed a completed eval run mid-report |

---

## Where things stand

**Built and verified:** Agents 1 and 2.
**Built, not yet verified:** Agent 3 — its eval baseline never completed because
the account hit Groq's daily token ceiling after one profile.

**267 unit tests**, ~5 seconds, no network and no API key required.

### Measured weaknesses, deliberately not guessed at

- **Agent 2 records almost no dissenting evidence** — 0 of 5 profiles produced a
  single `weakens` or `complicates` stance, despite the prompt asking and the
  schema supporting it. This matters because Agent 4 is the risk critic and
  contradicting evidence is exactly what it consumes.
- **Ranking saturates.** A company maxing every metric scores a flat 1.0, so
  exceptional companies are not currently distinguishable from each other.
- **13 of 18 Agent 2 themes cite a single source**, and it reaches the theme cap
  on well-covered sectors.
- **Agent 1's eval set scores 100%**, so it catches regressions but has no
  headroom to show improvement.

### Deferred, not blocking

- **No CLI.** There is no way for a person to run the pipeline — only Python
  snippets. Also the thing that would make the project demonstrable.
- **`InMemorySaver`** loses all state on restart, including a user mid
  clarification. Needs `SqliteSaver` before any real use.
- **Ticker resolution can be flaky between runs**, because provider search
  results vary for short ambiguous names. Degrades safely: it records a drop
  reason rather than picking the wrong company.

### Next

1. Run `python -m evals.company_runner` — the Agent 3 baseline.
2. Act on what it shows.
3. Then Agent 4 (Risk Critic), which needs no new API key.
