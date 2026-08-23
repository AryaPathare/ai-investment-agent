# Start here

Last worked: **2026-08-23**. **The pipeline is complete.** All five agents are
built and verified against their own evals, and every stage is connected end to
end.

`docs/PROJECT_LOG.md` is current through Session 4.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **433 passed** in about 4 seconds.

---

## 2. THE TASK — the hardening pass

Decided 2026-08-22: finish the pipeline first, harden once. This is it. **None
of it needs Groq quota**, which makes it a good use of a session whatever the
daily budget looks like.

### 2a. A CLI — the most valuable item here

There is still no way for a person to run this pipeline. Everything so far has
been driven from Python snippets and eval runners, which means the project
cannot be DEMONSTRATED - for a portfolio piece, the difference between a system
that works and one anybody believes works.

It waited deliberately: its shape depends on the finished pipeline, and building
it earlier would have meant building it twice.

What it has to do:

- ask the profile questions: age, experience, risk tolerance, amount, window,
  holding period, **sectors of interest**, restrictions
- run the graph and handle the **clarification interrupt** - Agent 1 can come
  back asking a question, and the CLI must carry the answer in and resume
- print the `Decision` readably: each thesis, the exit conditions with what
  grounds each one, and the exclusions with their reasons
- print `no_recommendation_reason` prominently when nothing is recommended.
  Recommending nothing is a first-class outcome and must not look like a failure
  or an empty screen

### 2b. `SqliteSaver`

`InMemorySaver` loses all state on restart, including a user stopped mid
clarification. Needed before anyone could really use this.

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
person. The cause is Agent 3's exposure prompt; the cost is re-verifying Agent 3.

### Agent 5 barely reads the articles

1 of 8 exit conditions cites one; the rest are metric thresholds, which are the
cheap answer and read identically for any company in any sector. The prompt now
demands at least one article-cited condition, which moved it from 0/9 to 1/8 -
progress, not a solution.

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
- **Agent 3's own eval has not run since the margin fix** (2026-08-23) - the
  daily quota ran out first. The effect WAS checked offline across eleven
  companies spanning tech, semiconductors, pharma, banks and small caps: only
  PowerBank changed, nothing was pushed below the completeness floor, and no
  screening decision moved. Worth one `python -m evals.company_runner --limit 1`
  next session to confirm the drop accounting still balances.

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

---

## Commands

```powershell
python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 433 tests, ~4s, no network

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
  at about 12 model calls per profile. **Measure, do not extrapolate** - trusting
  a documented figure once cost a whole verification run. The ceiling is a
  rolling 24-hour window, not a midnight reset.
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
