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

## How to use this

Five steps. The first two need no API key, so you can see what this produces
and run the whole test suite before deciding whether to sign up for anything.

### 1. Install

Python **3.14** is what CI runs on Linux and Windows, and every dependency is
pinned exactly. Older versions are untested rather than known-broken.

```bash
git clone https://github.com/AryaPathare/ai-investment-agent.git
cd ai-investment-agent
```

```powershell
# Windows / PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. See it work — no API key needed

```
python -m cli --demo
```

Prints a real recorded run: the same renderer, the same models, the same
grounded exit conditions, with no network call and nothing to sign up for. This
is the fastest way to see what the project actually produces.

```
python -m pytest
```

766 tests in a few seconds, no network and no credentials. If both of these work,
your install is good.

### 3. Add an API key

Only needed to run the pipeline for real.

```powershell
Copy-Item .env.example .env      # Windows
```
```bash
cp .env.example .env             # macOS / Linux
```

Then open `.env` and add:

| Key | Needed? | Free tier | Get one |
|-----|---------|-----------|---------|
| `GROQ_API_KEY` | **Required** | 200k tokens/day | [console.groq.com/keys](https://console.groq.com/keys) |
| `NEWS_API_KEY` | For Agents 2 and 4 | 100 requests/day | [thenewsapi.com](https://www.thenewsapi.com) |
| `FMP_API_KEY` | For Agent 3 | 250 requests/day | [financialmodelingprep.com](https://site.financialmodelingprep.com) |

Without the news key the pipeline cannot research anything, so it will not get
far. Without the FMP key it still works — non-US companies fall back to
`yfinance`, which needs no key at all.

Check everything is wired up:

```
python -m scripts.check_setup
```

It verifies `.env` exists, the settings validate, and the model actually
responds. **Run this first whenever something breaks** — it tells you whether
the problem is your config, the provider, or the code, before you debug the
wrong layer.

### 4. Run it

```
python -m cli --profile examples/semiconductors_high_risk.json
```

Or answer eight questions yourself:

```
python -m cli                             # then --save-profile mine.json to keep them
```

A run takes **two to three minutes** and about a dozen model calls, printing
each stage as it lands. One run costs roughly 25–30k of Groq's daily 200k, so
you get about six or seven a day on the free tier.

### 5. If it stops, resume it

Every step is checkpointed to SQLite, so closing the terminal at a prompt — or
Ctrl-C during the long research call — loses nothing.

```
python -m cli --list             # saved runs, and which can be resumed
python -m cli --resume <id>      # continue one
```

Resuming does **not** repeat the stages that already finished, which on a
free-tier quota is the difference between losing a minute and losing the day.

---

### What to expect

**It may recommend nothing, and that is a real answer.** The pipeline is never
forced to produce a pick. It prints a banner with the reason instead of a blank
screen.

**Sector choice matters more than it looks.** Semiconductors are covered densely
enough in the news to produce a full brief. Renewable energy is dominated by
private and foreign firms, so `examples/beginner_renewables.json` can
legitimately come back with nothing — that is the system working, not breaking.

**Try the interrupt.** `examples/conflicted_crypto.json` contains a
contradiction. The pipeline stops mid-run, asks you to resolve it, and continues
from exactly where it paused.

**Results vary between runs.** It reads the last two weeks of news, so the same
profile on a different day finds different companies.

---

## Tests and evals

```powershell
python -m pytest                        # 766 unit tests, seconds, no network, no key
```

The evals make **real API calls** and are how the agents were actually
developed. Start with `--tag hard`; a full `decision_runner` run costs most of a
free day's tokens.

```powershell
python -m evals.runner                  # Agent 1: 30 labelled cases
python -m evals.runner --tag hard --repeat 3
python -m evals.research_runner         # Agent 2
python -m evals.company_runner          # Agent 3  (runs 2 -> 3)
python -m evals.risk_runner             # Agent 4  (runs 2 -> 3 -> 4)
python -m evals.decision_runner         # Agent 5  (the full chain, most expensive)
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
demo/              A recorded run, so --demo works with no key.
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
