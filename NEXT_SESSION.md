# Start here

Last worked: **2026-08-23** (session 5). **The pipeline is complete and now
demonstrable.** All five agents are built and verified against their own evals,
and `python -m cli` runs the whole thing end to end.

`docs/PROJECT_LOG.md` is current through Session 5.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **472 passed** in about 3 seconds.

Then see it work, without spending quota on a real run:

```powershell
python -m cli --help
```

---

## 2. THE TASK — finish the hardening pass

### 2a. A CLI — DONE this session

`cli.py`. Asks the eight profile questions, runs the graph, handles Agent 1's
clarification interrupt, prints the brief. `--profile FILE` replays a saved
profile (three in `examples/`, one deliberately contradictory so the interrupt
can be shown on demand); `--save-profile FILE` writes one out.

Two things worth knowing before changing it:

- It uses `stream(stream_mode="updates")`, not `invoke`, so each stage reports
  as it lands. A run is several minutes and a dozen model calls; a silent
  terminal is indistinguishable from a hang.
- `stream` never yields accumulated state, so the final state is read back with
  `get_state(config).values`. **That is what found the serializer bug below.**

### 2b. `SqliteSaver` — NEXT, and start here

`InMemorySaver` loses all state on restart, including a user stopped mid
clarification.

Now slightly larger than it looks, and better understood than it was:

- `--thread-id` already exists in the CLI and is **inert** until the
  checkpointer is durable. It is the seam this work plugs into.
- The serializer is now a named constant, `workflow.CHECKPOINTED_TYPES`, with a
  test walking `InvestmentState` to prove nothing reachable is missing from it.
  `SqliteSaver` takes the same `serde=`, so that guarantee carries over — but
  **resume across processes will exercise it far harder than anything has so
  far**, because every read comes back through the serializer rather than only
  the one interrupt in Agent 1.
- Worth an actual end-to-end check once it is in: start `python -m cli` with
  `examples/conflicted_crypto.json`, kill the process at the clarification
  prompt, and resume the same `--thread-id` in a fresh process.

### 2c. Harder Agent 1 eval cases

It scores 18/18, so it catches regressions but cannot show improvement.

---

## 3. Then the known weaknesses

All measured, all deliberately left. Work them in the order they would change an
answer a reader sees.

### Agent 3 grades data-centre operators as "direct" exposure to renewables

**Start here.** The `renewables_excluding_fossil_fuels` profile is recommended
**Google and Amazon**, because both buy battery storage for their data centres.
True, and a very loose link: a beginner asking about renewable energy gets two
mega-cap advertising and retail businesses.

This is the one weakness currently putting a wrong-LOOKING company in front of a
person — and now it is in front of them in a readable brief rather than a Python
repr, which raises the cost of leaving it. The cause is Agent 3's exposure
prompt; the cost is re-verifying Agent 3.

### Agent 5 barely reads the articles

1 of 8 exit conditions cites one; the rest are metric thresholds, which are the
cheap answer and read identically for any company in any sector. The prompt now
demands at least one article-cited condition, which moved it from 0/9 to 1/8 -
progress, not a solution.

The CLI makes this visible in a way the eval numbers did not: every condition
prints its grounds, so a brief where four of five say `grounds: metric X` looks
as thin on screen as it is.

### Agent 2 records almost no dissenting evidence

Structural, not a prompt problem: most themes cite one article and one article
cannot disagree with itself. Worked around by giving Agent 4 its own adversarial
retrieval. If that stops working, this comes back.

### Agent 4's source filter is seven domains

From one afternoon of searches. An unlisted low-quality outlet passes and
nothing notices.

### Two accepted scoring limits

Ranking saturates at the very top; financial companies cap at 0.50. Both distort
absolute scores without changing any ordering that gets consumed. Documented in
`agents/screening.py`. **Settled - do not reopen** without a reason that has
actually changed.

### The exclusion check matches naive substrings

"No crypto exposure" in a rationale would register as a violation. Not yet
observed. Narrow it in ONE place for both agents if it ever fires falsely.

---

## What is NOT verified

Worth knowing before trusting a clean eval run.

- **Agent 5's exclusion path has never run.** Every run produced three or fewer
  candidates and no disqualifications, so nothing has been excluded for real.
  Unit tests only.
- **One of two eval profiles keeps returning zero candidates.** Article variance
  means each run tests a different slice, so a run of clean results is weaker
  evidence than the count suggests. **Verifying a fix against its exact failing
  inputs has repeatedly proved stronger than another eval run.**
- **Agent 3's own eval has still not run since the margin fix** (2026-08-23).
  Attempted again at the end of session 5 and blocked by the daily ceiling:
  `196,521 of 200,000` tokens already used, one case needs ~25-30k. The effect
  WAS checked offline across eleven companies spanning tech, semiconductors,
  pharma, banks and small caps: only PowerBank changed, nothing was pushed below
  the completeness floor, and no screening decision moved. Still worth one
  `python -m evals.company_runner --limit 1` to confirm the drop accounting
  balances. **Check the ceiling before planning a session around evals** — it is
  a rolling 24-hour window, so a new calendar day does not reset it.
- **The CLI has never been run against the live pipeline end to end.** Every
  path is covered by tests with stubbed agents, and the rendering was checked
  against realistic fixtures, but no real profile has gone through it. One
  `python -m cli --profile examples/beginner_renewables.json` when quota allows.
  Do this FIRST next session, before the eval — it exercises all five agents and
  is the last unverified thing about the CLI.

---

## The lesson this project kept re-teaching

**Unit tests prove the code does what it says; only the evals show whether what
it says is right.** Every significant defect in Agents 3, 4 and 5 came from an
eval, never from the suite, and the suite was green throughout.

The sharpest instance: Agent 4 shipped with **351 passing tests and a model that
was never called at all** - every test stubbed the news client, and the provider
does not support `OR` as query syntax, so every search silently returned nothing.

The most instructive: an operating margin of **168.38** corrupted scores through
two verified agents. The ranking clips at 0.40, so garbage and excellence scored
identically; Agent 4's rules only look for negative margins, so they were silent
too. It was caught when Agent 5 wrote "operating_margin falls below 150" into a
brief and a human read it. **A metric that clips cannot serve as its own
data-quality alarm** - and a number that looks fine in a field can look absurd in
a sentence, which is the argument for the last stage existing at all.

**Session 5 added a third kind, which neither tests nor evals could catch.**
Agents 4 and 5 were added to the graph without being added to the
checkpointer's type allow-list. An unregistered Pydantic type is not an error:
it round-trips as a plain dict with all the right keys and fails later,
elsewhere, on the first property access. The eval runners hold the objects they
build and never read one back out of the checkpointer, so 433 tests and five
eval suites stayed green. The CLI was the first caller to read state back, and
it broke immediately. There is now a test that walks `InvestmentState` and fails
if a reachable type is missing from `CHECKPOINTED_TYPES` — **adding a stage
means adding its types.**

---

## Commands

```powershell
python -m cli                           # run the pipeline for a person
python -m cli --profile examples/beginner_renewables.json
python -m cli --profile examples/conflicted_crypto.json   # shows the interrupt
python -m cli --save-profile mine.json

python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 472 tests, ~3s, no network

python -m evals.runner                  # Agent 1: 18 labelled cases
python -m evals.research_runner         # Agent 2: process quality, 5 profiles
python -m evals.company_runner          # Agent 3: runs 2 -> 3
python -m evals.risk_runner             # Agent 4: runs 2 -> 3 -> 4
python -m evals.decision_runner         # Agent 5: runs 2 -> 3 -> 4 -> 5
python -m evals.decision_runner --case <name>   # one profile, to conserve quota
```

---

## Known limits that will bite

- **Groq's daily ceiling is the binding constraint.** A profile through Agents
  2-3 is roughly **25-30k tokens**; the decision eval adds Agents 4 and 5 on top,
  at about 12 model calls per profile. A full `python -m cli` run costs the same
  as one decision-eval case. **Measure, do not extrapolate** - trusting a
  documented figure once cost a whole verification run. The ceiling is a rolling
  24-hour window, not a midnight reset.
- **TheNewsAPI**: 100 requests/day, 3 articles per request. Query syntax is
  plain space-separated AND only - **no `OR`, no `|`** - and three ANDed terms
  usually returns nothing.
- **FMP**: 250 requests/day, only a subset of US symbols. The yfinance fallback
  does real work, so a low `fmp` count is not a bug.
- **yfinance returns impossible values, and always has**: `debtToEquity` as a
  percentage, a literal `0.0` for margins that do not apply, and an operating
  margin of 168. Every one was caught late and by accident. **Treat a new metric
  as suspect until something checks its range.**

Caching is on by default everywhere, which is what makes development affordable.
