# AI Investment Research Agent

[![tests](https://github.com/AryaPathare/ai-investment-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/AryaPathare/ai-investment-agent/actions/workflows/tests.yml)

Five LLM agents that research stocks for someone who doesn't know where to
start. You say which sectors interest you, how much risk you can take and what
you want to avoid; it finds what's happening in those sectors, finds real public
companies exposed to it, **attacks its own conclusions**, and recommends up to
three — or recommends **nothing**, which is a first-class outcome rather than a
blank screen.

Every claim cites a retrieved article or a measured number. Nothing else ships.

> **Not investment advice.** A personal learning project, not licensed or
> qualified to advise anyone. Its output should not be acted on.

MIT licensed — see [LICENSE](LICENSE).

---

## What it produces

Each recommendation states a thesis, then the conditions that would break it —
and what grounds each one:

```
     WHAT WOULD MEAN THIS HAS STOPPED BEING A GOOD IDEA
       - The Italian 1.2GW order is cancelled or materially reduced.
         grounds: "Waaree wins 1.2GW module order from Italian developer"
                  ft.com, 2026-08-17
       - debt_to_equity rises above 2.0.
         grounds: metric debt_to_equity
```

A condition grounded in neither is discarded, and the discards are counted.

---

## Run it

```powershell
python -m cli                                              # answer eight questions
python -m cli --profile examples/beginner_renewables.json  # skip the questions
python -m cli --list                                       # saved runs
python -m cli --resume <id>                                # continue a stopped one
python -m cli --save-profile mine.json                     # keep the answers
```

A run takes a few minutes and about a dozen model calls, printing each stage as
it lands. Every step is checkpointed to SQLite, so closing the terminal at a
clarification prompt — or Ctrl-C during the three-minute research call — loses
nothing, and resuming does **not** repeat the stages that finished.

`examples/conflicted_crypto.json` shows the other path: the pipeline stops
mid-run, asks you to resolve a contradiction, and continues from where it
paused.

---

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env      # then add your Groq API key
python -m scripts.check_setup    # verifies config, settings and the model
```

A free [Groq](https://console.groq.com/keys) key is required.
[TheNewsAPI](https://www.thenewsapi.com) and
[FMP](https://site.financialmodelingprep.com) are optional but needed for
Agents 2–4; non-US companies fall back to `yfinance`, which needs no key.

Run `check_setup` first whenever something breaks — it tells you whether the
problem is your config, the provider or your code, before you debug the wrong
layer.

---

## Commands

```powershell
python -m pytest                        # 752 unit tests, seconds, no network
python -m evals.runner                  # Agent 1: 30 labelled cases
python -m evals.runner --tag hard --repeat 3
python -m evals.research_runner         # Agent 2
python -m evals.company_runner          # Agent 3  (runs 2 -> 3)
python -m evals.risk_runner             # Agent 4  (runs 2 -> 3 -> 4)
python -m evals.decision_runner         # Agent 5  (the full chain)
```

**Tests and evals answer different questions.** `pytest` proves the code does
what it says — deterministic, no network, always green. The evals make real API
calls against known-correct answers and measure the model's *judgment*, which is
probabilistic and so is a measurement to compare across prompt changes, not a
pass/fail gate.

That distinction is the whole project. Every significant defect came from an
eval, never from the test suite — and the suite was green throughout. The
sharpest case: an agent shipped with **351 passing tests and a model that was
never called at all**, because every test stubbed the news client and the
provider silently returned nothing for every live query.

---

## How it works

Five agents on a LangGraph state machine — profile, research, companies, risk
critic, decide — with a few rules holding it together:

- **LLMs judge; Python computes.** Every score, screen and ranking is
  deterministic code. A model asked to score a company 0–100 returns 72 with
  nothing behind it.
- **The model never writes a ticker.** It extracts company *names*; tickers come
  from a market database and are verified. A guessed symbol doesn't look wrong —
  it silently returns a different company's financials.
- **Search first, then synthesise.** Agent 2 retrieves real articles and asks
  the model to read them, rather than asking what matters and hunting for
  support afterwards.
- **What gets filtered out is reported.** "No risks found" means something
  different when four of twelve articles never reached the model.

**[`docs/DESIGN.md`](docs/DESIGN.md)** has the full reasoning and the honest
list of what still goes wrong.

---

## Layout

```
cli.py             The command line front end. The only way a person runs this.
checkpoints.py     Durable run state, so a stopped run can be resumed.
config.py          All external configuration. The only place secrets are read.
workflow.py        The LangGraph graph: nodes, edges, routing.
models/            Pydantic schemas — the contracts between stages.
agents/            One module per agent. Prompt + orchestration.
evals/             Labelled cases and the scoring runners, one per agent.
tests/             Unit tests.
docs/              Design notes and the project log.
```

---

## Known limitations

The short version — [`docs/DESIGN.md`](docs/DESIGN.md) has all of them with
their evidence.

- **Agent 3 only reads the articles Agent 2 chose to cite.** The one open
  defect. Retrieval is throttled by a filter one stage earlier — 17 articles
  retrieved became 5 examined — which costs nothing in a rich sector and empties
  the brief in a thin one.
- **Briefs can be thin.** Roughly three of ten examined companies are
  investable on a renewables theme — most of that news is about private and
  foreign firms. A one-company brief is the honest output, not a broken one.
- **Agent 2 rarely records dissenting evidence**, and **the source filter can't
  cover its long tail** (86 of 130 observed sources contributed exactly one
  article). Both structural, both measured, both accepted deliberately.
- **Two of the four exclusion reasons have never fired** against real data —
  `restriction_violation` and `disqualified_by_risk`. The other two now have.

---

## The log

**[`docs/PROJECT_LOG.md`](docs/PROJECT_LOG.md) is the interesting half of this
repository.** 72 entries recording what broke, what the first diagnosis was, and
why it was usually wrong — an operating margin of 168 that corrupted two
verified agents, a citation rate blamed on the model that turned out to be
plumbing, and the tests-passing-model-never-called story above.

The code shows what was built. The log shows how it was found out.
