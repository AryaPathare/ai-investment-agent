# AI Investment Research Agent

Built for someone who wants to start investing and does not know where to begin.
They say which **sectors or fields** they are interested in — technology,
healthcare, energy — along with how much, for how long, how much risk they can
take, and anything they want to avoid. From there a multi-agent system researches
what is currently happening in those sectors, finds real public companies exposed
to it, attacks its own conclusions, and recommends up to three stocks — or
explicitly recommends **nothing** when no opportunity is good enough.

That last part is deliberate. The system is never forced to produce a
recommendation just because recommending is its job.

> **Not investment advice.** This is a personal learning project. It is not
> licensed or qualified to advise anyone, and its output should not be acted on.

---

## Status

| Stage | What it does | State |
|-------|--------------|-------|
| 1. Profile | Validate investor input, ask the user about genuine contradictions | **Built** |
| 2. Research | Identify trends and gather supporting evidence | **Built** |
| 3. Companies | Extract, screen, and analyse fundamentals | **Built** |
| 4. Risk Critic | Retrieve the bear case and attack the thesis | **Built** |
| 5. Decide | Select, write the case, and state exit conditions | **Built** |
| CLI | Ask the questions, run the graph, print the brief | **Built** |
| Checkpoints | Save every step, so a stopped run can be resumed | **Built** |

---

## Run it

```powershell
python -m cli                                          # answer eight questions
python -m cli --profile examples/beginner_renewables.json    # skip the questions
python -m cli --save-profile mine.json                 # keep the answers for next time
```

A run takes a few minutes and roughly a dozen model calls, and prints each
stage as it lands so you can see it working:

```
[2/5] Researching current themes in your sectors ...
        2 theme(s), 3 cited article(s) from 23 retrieved
          - Grid-scale storage buildout (high confidence)
[3/5] Finding companies genuinely exposed to those themes ...
        3 candidate(s) from 11 companies examined
          dropped: 1 failed_screen, 1 no_ticker_found
```

Each recommendation prints its thesis, the exit conditions that would break it,
and **what grounds each condition** — a headline and a link you can open, or a
named metric:

```
     WHAT WOULD MEAN THIS HAS STOPPED BEING A GOOD IDEA
       - The Italian 1.2GW order is cancelled or materially reduced.
         grounds: "Waaree wins 1.2GW module order from Italian developer"
                  ft.com, 2026-08-17
                  https://ft.com/story/a2
       - debt_to_equity rises above 2.0.
         grounds: metric debt_to_equity
```

Recommending nothing is a first-class outcome and gets its own banner with the
reason, not a blank screen. `examples/conflicted_crypto.json` demonstrates the
other path: Agent 1 stops mid-run, asks you to resolve the contradiction, and
the graph resumes from exactly where it paused.

See [examples/](examples/) for the saved profiles.

### Stopping is safe

Every step is checkpointed to SQLite, so closing the terminal at a clarification
prompt — or Ctrl-C during the three-minute research call — loses nothing:

```powershell
python -m cli --list
#   nilesh-1  paused, waiting on your answer  cryptocurrency, banking

python -m cli --resume nilesh-1
#   Resuming 'nilesh-1' - paused, waiting on your answer.
#     researching: cryptocurrency, banking
#   (the original question is shown again, then the run continues)
```

A run stopped partway through a stage resumes at that stage and **does not
repeat the ones that finished**, which on a free-tier quota is the difference
between losing a minute and losing the day's budget. Runs live in `.state/`,
deliberately not under `.cache/` — a paused session is not re-fetchable, and
`.cache/` is documented as safe to delete.

---

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env      # then add your Groq API key
```

Two more keys are optional but needed for Agents 2, 3 and 4:

- **TheNewsAPI** (<https://www.thenewsapi.com>) — news search
- **Financial Modeling Prep** (<https://site.financialmodelingprep.com>) — US
  company fundamentals. Non-US companies use `yfinance`, which needs no key.

Get a free Groq key at <https://console.groq.com/keys>.

Verify everything works:

```powershell
python -m scripts.check_setup
```

This checks `.env` exists, settings validate, and the model actually responds.
**Run it first whenever something breaks** — it tells you whether the problem is
your config, the provider, or your code, before you start debugging the wrong
layer.

---

## Commands

```powershell
python -m cli                           # run the pipeline and print the brief
python -m cli --list                    # saved runs, and which can be resumed
python -m cli --resume <id>             # continue a run that stopped
python -m scripts.check_setup           # environment health check
python -m pytest                        # unit tests (699, a few seconds, no network)

python -m evals.runner                  # Agent 1: accuracy on 30 labelled cases
python -m evals.runner --tag hard       # only the 12 hard cases (cheaper to iterate)
python -m evals.runner --tag regression # only the must-never-break cases

python -m evals.research_runner         # Agent 2: process quality on 5 profiles
python -m evals.company_runner          # Agent 3: process quality, runs 2 -> 3
python -m evals.company_runner --limit 1

python -m evals.risk_runner            # Agent 4: process quality, runs 2 -> 3 -> 4
python -m evals.decision_runner        # Agent 5: process quality, runs 2 -> 3 -> 4 -> 5
```

Agent 2's evals are paced ~60s apart on purpose: one research run costs about
6,100 of Groq's free-tier 8,000 tokens-per-minute, so back-to-back runs fail.

### Tests vs evals

These answer different questions and are kept strictly separate.

**`pytest` tests the code.** No network, no API key, fully deterministic. It
proves routing is correct, the clarification loop terminates, and the model
cannot corrupt user data. These must always pass.

**`evals.runner` tests the model's judgment.** Real API calls against profiles
with known-correct answers. Model output is probabilistic, so accuracy is a
*measurement* to compare across prompt changes, not a pass/fail gate. The
exception is cases tagged `regression` — those are bugs already fixed once, and
the runner exits non-zero if any of them come back.

---

## Layout

```
cli.py             The command line front end. The only way a person runs this.
checkpoints.py     Durable run state, so a stopped run can be resumed.
config.py          All external configuration. The only place secrets are read.
workflow.py        The LangGraph graph: nodes, edges, routing.
models/            Pydantic schemas — the contracts between stages.
agents/            One module per agent. Prompt + orchestration.
evals/             Labelled cases and the scoring runner.
examples/          Saved profiles for `--profile`.
scripts/           Operational helpers (health check).
tests/             Unit tests.
```

---

## Design decisions worth knowing

**LLMs judge; Python computes.** Anything calculable or checkable in code stays
in code. A negative investment amount is rejected by Pydantic, not reasoned
about by a model. Models are used only where genuine ambiguity requires
judgment.

**The model returns a verdict, not your data.** Agent 1 emits a
`ProfileAssessment` — a status, a reason, and a narrow whitelist of fields a
clarification may revise. Python assembles the final `InvestorProfile` by
copying everything else from the user's own validated input. The model has no
channel through which to alter an age or an amount.

**LLM output is untrusted input.** It steers control flow, so it is validated as
strictly as anything arriving from outside. `ProfileAssessment` rejects
incoherent combinations, such as "needs clarification" with no reason given.

**Every loop is bounded by code, never by the model.** The clarification cycle
stops after a configured number of attempts and records why it gave up. A model
is never trusted to decide when to stop looping.

**Failures end the workflow cleanly.** When a model call fails after its
retries, the graph records a readable `error` in state instead of raising. If
`error` is set, `investor_profile` must not be used downstream.

**One retry layer, not two.** The Groq client already retries with exponential
backoff, so LangGraph's node-level `retry_policy` is deliberately unused —
stacking them would multiply attempts against an API that is rate-limiting you.

**Search first, then synthesise.** Agent 2 never asks the model what trends
matter and then hunts for support — that is confirmation bias with a training
cutoff attached. It retrieves real articles first and asks the model to read
them. Every theme must cite at least one retrieved article, and `Evidence` has
no field for a title or URL, so fabricating a source is impossible rather than
discouraged. Citations use short labels the model can copy reliably; Python maps
them back to real ids and discards any that do not exist.

**Token budgets are per call, not global.** Groq charges `max_tokens` against
the tokens-per-minute quota whether or not it is used, so one value big enough
for the largest call makes every small call expensive. `gpt-oss-20b` is also a
reasoning model, spending tokens before the visible answer, so budgets must be
larger than the output length suggests.

**The model never writes a ticker.** Agent 3 extracts company *names* as
articles write them; tickers come from a market database and are verified.
`NVDA`, `NVDA.NE` and `NVD.DE` are all real symbols for Nvidia, so a guessed one
does not look wrong — it silently returns a different company's financials.
Resolution scores candidates rather than taking the first result, because search
relevance is not ours: "Pfizer" returns Germany first and Argentina second.

**Ranking is arithmetic, not a model's opinion.** Screening and scoring run in
pure Python over provider figures. The model supplies exactly one input — whether
a company is `direct`, `partial` or `incidental` to a theme. A model asked to
score a company 0-100 returns 72 with nothing behind it: not reproducible, not
comparable, not explainable.

**Comparable ratios and currency amounts are separate types.** Fundamentals
arrive in local currency, and GBp is *pence*. Ranking touches `ComparableMetrics`
(all unitless); `CurrencyAmounts` is display only. Reaching the wrong one means
crossing a type boundary rather than ignoring a comment.

**Rejections are recorded, never discarded.** `drop_summary` says where every
examined company went. "3 candidates from 30 mentions" is either good filtering
or a broken resolver, and those look identical without it — it caught three real
bugs on its first live run.

---

## Optional: tracing

Setting these in `.env` records every prompt, response, latency and token count
to a web UI, which is worth a lot once several agents are chained:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<from https://smith.langchain.com>
LANGSMITH_PROJECT=ai-investment-agent
```

`python -m scripts.check_setup` reports whether it is on.

---

## Known limitations

- **State is in memory.** `InMemorySaver` loses everything when the process
  exits. Needs `SqliteSaver` before any real use.
- **Agent 1's eval set scores 100%.** Good for catching regressions, but it has
  no headroom to detect improvement. It needs harder cases, added as found.
- **Agent 2 rarely records dissenting evidence.** Across the baseline, 0 of 5
  profiles produced a single `weakens` or `complicates` stance, despite the
  prompt asking for honest labelling. That is confirmation bias, and it is the
  clearest thing to work on next.
- **Most Agent 2 themes cite one source** (13 of 18 in the baseline), and it
  reaches the five-theme cap on well-covered sectors.
- **`openai/gpt-oss-20b` is unevaluated against alternatives.** Now that the
  eval set exists, comparing a larger model is a measurable question.
- **Agent 3's eval baseline is incomplete.** The account hit Groq's 200k
  tokens-per-day ceiling partway through. One profile completed cleanly with no
  hard failures; the rest need re-running once quota resets.
- **Ticker resolution can be flaky between runs.** Provider search results vary
  over time for short ambiguous names. The system degrades safely — it records a
  drop reason rather than picking the wrong company.
- **Ranking saturates.** A company maxing every metric scores a flat 1.0, so
  exceptional companies are not currently distinguishable from each other.
