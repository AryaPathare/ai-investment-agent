# AI Investment Research Agent

A multi-agent system that takes an investor's profile, researches current trends
and real public companies, weighs the risks, and recommends up to three stocks —
or explicitly recommends **nothing** when no opportunity is good enough.

That last part is deliberate. The system is never forced to produce a
recommendation just because recommending is its job.

> **Not investment advice.** This is a personal learning project. It is not
> licensed or qualified to advise anyone, and its output should not be acted on.

---

## Status

| Stage | What it does | State |
|-------|--------------|-------|
| 1. Profile | Validate investor input, ask the user about genuine contradictions | **Built** |
| 2. Research | Identify trends and gather supporting evidence | Planned |
| 3. Companies | Extract, screen, and analyse fundamentals | Planned |
| 4. Risk Critic | Adversarially attack the investment thesis | Planned |
| 5. Decide | Score, select, and state exit conditions | Planned |

---

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env      # then add your Groq API key
```

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
python -m scripts.check_setup      # environment health check
python -m pytest                   # unit tests (58, ~0.5s, no network)
python -m evals.runner             # model accuracy against 18 labelled cases
python -m evals.runner --tag regression   # only the must-never-break cases
python -m evals.runner --repeat 3         # consistency check
```

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
config.py          All external configuration. The only place secrets are read.
workflow.py        The LangGraph graph: nodes, edges, routing.
models/            Pydantic schemas — the contracts between stages.
agents/            One module per agent. Prompt + orchestration.
evals/             Labelled cases and the scoring runner.
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
- **The eval set scores 100%.** Good for catching regressions, but it has no
  headroom to detect improvement. It needs harder cases, added as failures are
  found.
- **`openai/gpt-oss-20b` is unevaluated against alternatives.** Now that the
  eval set exists, comparing a larger model is a measurable question.
