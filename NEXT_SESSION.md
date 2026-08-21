# Start here

Last worked: **2026-08-20**. Agents 1, 2 and 3 are built. Agent 3 is **not yet
verified** — that is the first job.

---

## 1. Check the environment still works

```powershell
python -m scripts.check_setup
```

Confirms `.env`, settings, and a live call to Groq. If anything is broken, this
tells you whether it is your config, the provider, or your code — before you
start debugging the wrong layer.

```powershell
python -m pytest
```

Should be **267 passed** in about 5 seconds. If not, something changed
underneath; fix that before anything else.

---

## 2. Run the Agent 3 eval baseline — THE ACTUAL TASK

```powershell
python -m evals.company_runner
```

This never completed. Groq's 200,000 tokens-per-day ceiling was hit after one
profile, so we have one data point and not a baseline. It takes a few minutes
(profiles are paced apart on purpose) and costs roughly 20-25k tokens.

**Unit tests prove the code is right. Only the evals show whether the behaviour
is.** That is why this comes before Agent 4.

### What to look for

`HARD FAILURES` must be **0**. Anything there is a bug, not an opinion:
traceability, incidental survivors, ranking order, the candidate cap,
debt/equity landing in ratio range, drop accounting, funds among candidates.

Then look at the soft signals. Four specific suspicions, none confirmed:

| Watch for | Why it matters |
|---|---|
| Scores saturated at 1.0 | If several candidates tie at the top, the ranking cannot order them |
| Exposure mostly `direct` | Grade inflation would make the field decorative |
| `sources` mostly `yfinance` | Then FMP is barely earning its integration |
| Drop profile dominated by one reason | Mostly `no_ticker_found` means the resolver is broken; mostly `incidental_mention` means extraction is too eager |

Compare against the one profile that did complete:

```
semiconductors_high_risk
  3 themes / 4 articles -> 4 mentions -> 3 companies -> 2 candidates
    0.600  NVDA   direct
    0.290  INTC   partial
  dropped: {'incidental_mention': 1}
  HARD FAILURES: 0
```

---

## 3. Then decide what, if anything, to fix

Act on what the numbers show, not on guesses. If nothing needs fixing, Agent 3
is genuinely done and Agent 4 can start.

---

## After that: Agent 4 — Risk Critic

Consumes Agent 3's `CompanyFindings` and attacks the thesis: assume the previous
agents are wrong and find reasons each company could fail. **Needs no new API
key** — it reasons over data we already have.

Two things to settle before building it:

1. **Agent 2 almost never records dissenting evidence** — 0 of 5 profiles
   produced a single `weakens` or `complicates` stance. The risk critic depends
   on exactly that evidence, so feeding it a one-sided base undercuts the point
   of having it. Worth fixing first.
2. **Ranking saturates** at 1.0, so exceptional companies are not currently
   distinguishable from each other.

---

## At the END of every session

Ask for `docs/PROJECT_LOG.md` to be updated with what happened. It is the
running record the final write-up will be built from — decisions, what went
wrong, how it was found. Recording it while it is fresh beats reconstructing it
from a 4 MB transcript later.

---

## Commands

```powershell
python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 267 tests, ~5s, no network

python -m evals.runner                  # Agent 1: 18 labelled cases
python -m evals.research_runner         # Agent 2: process quality, 5 profiles
python -m evals.company_runner          # Agent 3: process quality, runs 2 -> 3
```

---

## Known limits that will bite

- **Groq free tier**: 8,000 tokens/minute and **200,000 tokens/day**. One full
  profile through Agents 1-3 costs about 6,000 tokens, so roughly 30 runs a day.
  The daily ceiling is a rolling 24-hour window, not a midnight reset.
- **FMP free tier**: 250 requests/day, and it covers only a *subset* of US
  symbols. Non-US companies and refused US symbols fall back to `yfinance`.
- **TheNewsAPI free tier**: 100 requests/day, 3 articles per request.

Caching is on by default everywhere, which is what makes development affordable.

---

## Still deferred (not blocking)

- **No CLI.** There is no way for a person to run this pipeline — only Python
  snippets. Worth building; it is also what makes the project demonstrable.
- **`InMemorySaver`** loses all state on restart, including a user mid
  clarification. Needs `SqliteSaver` before any real use.
- **Agent 1's eval set scores 100%**, so it catches regressions but cannot show
  improvement. Add harder cases as failures are found.
