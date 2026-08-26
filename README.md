# AI Investment Research Agent

[![tests](https://github.com/AryaPathare/ai-investment-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/AryaPathare/ai-investment-agent/actions/workflows/tests.yml)

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

MIT licensed — see [LICENSE](LICENSE).

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

**[`docs/PROJECT_LOG.md`](docs/PROJECT_LOG.md) is the interesting half of this
repository.** 72 entries recording what broke, what the first diagnosis was, and
why it was usually wrong — including an agent that shipped with 351 passing
tests and a model that was never called at all. The code shows what was built;
the log shows how it was found out.

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
python -m pytest                        # unit tests (702, a few seconds, no network)

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

**What gets filtered out is reported, not silently dropped.** Two filters sit in
front of the risk critic: one removes publishers that do no original reporting,
the other removes press releases, which are the company describing itself and
the most confirmatory input an agent arguing the bear case could be handed. Both
report what they withheld, because "no risks found" means something different
when four of twelve articles never reached the model. Both are also deliberately
cautious in the same direction — a press release slipping through costs a
mediocre input, while removing "Regulator announces probe" defeats the agent, so
anything ambiguous is kept.

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

Ordered by how much each would change an answer a reader actually sees. Every
one of these was measured rather than guessed at; where something was fixed,
`docs/PROJECT_LOG.md` records what the fix cost and what it revealed.

- **Agent 2 writes search queries too specific to return anything.** Observed
  2026-08-25: five queries, each naming a company and then ANDing four or five
  more terms onto it, four of which returned zero articles.

      SunPower solar panel manufacturing expansion            found 0
      Vestas wind turbine supply chain expansion              found 1
      NextEra Energy renewable portfolio expansion contracts  found 0
      Enphase Energy battery storage contracts                found 0

  TheNewsAPI is space-separated AND with no `OR`, so every added term narrows
  the search. This is an earlier fix overshooting — teaching the agent that a
  useful article names a company was read as "name companies in the query" —
  and it is the one open defect in the project. **A live run on the renewables
  profile can currently come back with an empty brief because of it.**
- **The renewables brief is thin, and honestly so.** Of roughly ten companies
  examined for that profile, about three are investable — renewable-energy news
  is dominated by private and foreign firms. Now that loose exposure is graded
  out (below), a reader can get a one-company brief. That is the correct
  output, but it is a thin one, and no prompt fixes it.
- **Agent 2 rarely records dissenting evidence.** Across the baseline, 0 of 5
  profiles produced a single `weakens` or `complicates` stance. Structural
  rather than a prompt problem — most themes cite one article, and one article
  cannot disagree with itself. Worked around by giving Agent 4 its own
  adversarial retrieval, which makes that workaround load-bearing: if those
  bear queries stop returning anything, this comes back with nothing behind it.
  **Accepted deliberately.**
- **The source filter cannot cover its long tail.** Audited against 272 cached
  articles from 130 sources: 86 of those sources contributed exactly one
  article. A list of publisher names cannot cover a distribution whose mode is
  one, and both alternatives were tried and failed on real data — provider
  categories put a private-equity acquisition in the same bucket as everything
  uncategorised, and query-term matching cannot tell a lithium battery deal
  from a battery-storage company. What carries the weight instead is a filter
  on article *shape* rather than publisher. **Accepted deliberately.**
- **Most Agent 2 themes cite one source** (13 of 18 in the baseline), and it
  reaches the five-theme cap on well-covered sectors.
- **Ranking saturates, and financial companies are capped.** A company beyond
  every cap scores a flat 1.000, so exceptional companies are not distinguishable
  from each other; banks have no cost of goods, so their completeness caps at
  0.50. Both are measured and accepted — they distort absolute scores without
  changing any ordering that gets consumed. See `agents/screening.py`.
- **Ticker resolution can be flaky between runs.** Provider search results vary
  over time for short ambiguous names. The system degrades safely — it records a
  drop reason rather than picking the wrong company.
- **`openai/gpt-oss-20b` is unevaluated against alternatives.** Now that the
  eval set exists, comparing a larger model is a measurable question.

### Not yet verified

Distinct from the above: these are not known to be wrong, they are simply
untested against the live pipeline.

- **Agent 5's exclusion path has never run.** No live run has yet produced a
  disqualification, so the code that handles one has unit tests only. This is
  the last untested path in the pipeline.
- **The 12 hard Agent 1 cases no longer discriminate.** They score 12/12, and
  the rubric written alongside them says 8–10 is a good hard set and 12 means
  it is too easy. Fixing the defect the set was built to catch spent its
  margin. The score is no longer evidence about Agent 1 until harder cases
  exist.

### Fixed, and how it was found

Three things that were on this list are not any more. Each is worth reading in
`docs/PROJECT_LOG.md`, because in every case the first diagnosis was wrong:

- **Agent 3 grading data-centre operators as *direct* exposure** — Google and
  Amazon were recommended for a renewables profile because both buy battery
  storage. Now graded `incidental_mention` and dropped, on the test of which
  way the money flows.
- **Agent 5 barely reading the articles** — 1 of 8 exit conditions cited one,
  which was read for weeks as the model taking the cheap option. It was not: it
  had never been given the articles. Cited equalled citable on every candidate.
  On identical inputs the rate is now 3 of 7, and what the new conditions
  displaced was boilerplate.
- **A live end-to-end CLI run, and the Agent 1 and Agent 3 evals** — all three
  were owed and all three have now run against the real model.
