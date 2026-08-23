# Start here

Last worked: **2026-08-23**. **The pipeline is complete, demonstrable, durable,
and published.** All five agents are built and verified against their own evals,
`python -m cli` runs the whole thing end to end, a run that stops can be resumed,
and CI proves the suite passes on machines that have never seen the project.

**Everything that does not need Groq quota is finished.** All seven remaining
tasks need it — see section 2.

- Repo: <https://github.com/AryaPathare/ai-investment-agent> (public, MIT)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- `docs/PROJECT_LOG.md` is current through entry 51

**The git history was rewritten on 2026-08-23** to change the commit author to
`Arya Pathare <patharearya@gmail.com>`. Every SHA before that point changed, so
any commit hash written down elsewhere no longer resolves.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **707 passed** in a few seconds.

Then see it work, without spending quota on a real run:

```powershell
python -m cli --help
```

---

## 2. THE TASK — seven items, all needing quota

**Check the Groq console before planning around these.** The ceiling is a rolling
24-hour window, not a midnight reset, and it was at 196,521 / 200,000 on
2026-08-23. A new calendar day does not reset it.

Do them in this order. The first two are cheap and tell you whether anything
else is even needed.

### 2.1 Run the CLI live, end to end — ~12 calls

```powershell
python -m cli --profile examples/beginner_renewables.json
```

The last unverified thing about the CLI, and the highest-value single run:

- It exercises all five agents at once, so it doubles as a pipeline smoke test.
- It produces the first **attributable cache**. The `_provenance` block records
  which agent asked for each article, so afterwards you can finally answer
  whether press releases reach the risk critic — a claim currently recorded as
  unproven.
- Afterwards `python -m cli --resume <id>` replays the real result forever, at
  zero quota. That is the demo.

**Expect it to find something.** Three times on 2026-08-23, running existing
code under new conditions surfaced a real defect: reading state back exposed two
unregistered types, a review found the press-release filter eating litigation
news, and a clean clone found five tests silently reading `.env`. This run is
the newest condition of all.

### 2.2 Agent 1 hard-set baseline — 12 calls

```powershell
python -m evals.runner --tag hard
```

**Read this as a test of the LABELS as much as of the agent.** The 12 hard cases
have never been scored by a real model. They are validated only against a naive
string-matching stand-in, which proves they separate string matching from
judgment — not that the expected answers are right.

- ~8-10 of 12 is a good result and a usable baseline.
- **12/12 means they are still too easy**, not that the agent is perfect.
- Below ~5, suspect the labels before the prompt. Every case carries a `why`
  written specifically so that argument can be checked.

### 2.3 Agent 3's eval — ~25-30k tokens

```powershell
python -m evals.company_runner --limit 1
```

Owed since the operating-margin fix. The effect was verified offline across
eleven companies — only PowerBank changed, nothing fell below the completeness
floor, no screening decision moved — but the eval itself has never run. Confirms
the drop accounting still balances.

### 2.4 The zero-candidate eval profile — 2-3 runs

One of two research profiles keeps returning zero candidates. Article variance
means each run tests a different slice, so a run of clean results is weaker
evidence than the count suggests. **Verifying against the exact failing inputs
has repeatedly proved stronger than another eval run.**

### 2.5 Agent 3's exposure grade — several runs, OPEN-ENDED

**The only remaining defect a reader meets in the output.** The
`renewables_excluding_fossil_fuels` profile is recommended **Google and Amazon**,
because both buy battery storage for their data centres. True, and a very loose
link: a beginner asking about renewable energy gets two mega-cap advertising and
retail businesses.

The cause is Agent 3's exposure prompt. The cost is re-verifying Agent 3, and
the prompt change is free while knowing whether it worked is not — this has no
fixed size.

Possible side effect worth watching: a stricter exposure grade should start
disqualifying candidates, which would finally exercise **Agent 5's exclusion
path** — code that has unit tests only because no live run has ever produced a
disqualification.

### 2.6 Agent 5 barely cites articles — several runs, OPEN-ENDED

1 of 8 exit conditions cites one; the rest are metric thresholds, which are the
cheap answer and read identically for any company in any sector. The prompt
already demands at least one article-cited condition, which moved it from 0/9 to
1/8 — so one round of prompt work has already been spent here and was not
enough.

The CLI makes this visible in a way the numbers did not: every condition prints
its grounds, so a brief where four of five say `grounds: metric X` looks as thin
on screen as it is.

### 2.7 The PDF — no quota, deferred by choice

`docs/PROJECT_LOG.md` is the source material: 51 numbered entries through
Session 8, written as a narrative of what broke and why. Deliberately held back
until the rest is done.

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

### Agent 4's source filter cannot cover its long tail

**Widened 2026-08-23 from evidence, and the remaining problem is structural.**
Audited against the 224 cached news responses on disk: 272 distinct articles,
130 sources. Sixteen names added, all of them actually observed. Coverage went
from 2.6% to 15.1%.

The number that matters is the other one: **86 of 130 sources contributed
exactly one article.** A list of names cannot cover that, and extending it
further is not the fix. Two problems found in the same audit are still open and
need different instruments:

- **Press releases: DONE** (2026-08-23), then **hardened after review found it
  was dropping real bad news** - "First Solar Reports Disappointing
  Second-Quarter Financial Results, Shares Plunge" and "Third-quarter results
  reveal accounting irregularities" were both being removed. A journalism veto
  now runs first and beats every other signal. **Do not remove it**; nine tests
  exist to stop that. Filtered by article shape, not publisher, and only for the
  risk critic - the same article is ordinary
  evidence for Agent 2. Two signals: the wire dateline ("GLOBE NEWSWIRE",
  "/PRNewswire/") and issuer document types in the title. 15 of 272 cached
  articles match, all genuine. **Do not loosen it to a bare "announces" rule** -
  that catches "Regulator announces probe" and "Canadian Solar Announces
  Resolution of Patent Litigation", which is exactly the evidence the agent
  exists to find. Seven tests exist to stop that.
- **Off-topic matches: ACCEPTED, not open.** `dealigg.com` returned retail
  battery deals for a battery-storage query. Measured 2026-08-23 rather than
  assumed: **the model already discards it.** In eight of nine recorded research
  evals every theme produced was on topic, and only 40-70% of retrieved articles
  are cited at all. The cost is wasted retrieval budget and prompt tokens, not
  corrupted output.

  Two instruments were checked and both failed: provider categories (the
  no-category bucket also holds *"Francisco Partners to acquire Weave for
  $650m"*) and query-term matching (*"6-Pack Lithium **Battery**"* legitimately
  matches a battery query). **Settled on the same terms as the scoring limits.**
  If it is ever reopened, do it after a live run - the provenance block now
  records which query produced each article, which is the only thing that would
  make a fix well-targeted.

Both smaller items the audit surfaced are **DONE** (2026-08-23):

- **The cache now records its own questions.** `_provenance` block carrying the
  query, the asking agent (`research` / `risk_critic`), the date window and the
  fetch time. The 224 older entries have none and stay readable. **The payoff is
  entirely in future runs**, which is why this was done before the next live
  one - do not run the CLI live and then wish you had this.
- **The filter now reports what it withheld.** `CandidateCritique.sources_withheld`,
  printed by the CLI. Once the next live run exists, the press-release claim
  above becomes answerable rather than unproven.

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
- **The 12 hard Agent 1 cases have never been scored by the real model.**
  See the caveat in 2c above: the first run tests the labels as much as the
  agent. `python -m evals.runner --tag hard` is 12 calls.
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

**Session 6 added a fourth: a test that cannot fail is not evidence.** Mutation
-testing that same guard — removing `serde=` and expecting red — produced green,
because omitting the serializer falls back to a permissive default rather than
the strict allow-list. The guard was real but pointed at nothing, and only
breaking it on purpose revealed that. Two sessions, two mutation tests, one
confirmed and one exposed. **Break a new guard deliberately before trusting it.**

---

## Commands

```powershell
python -m cli                           # run the pipeline for a person
python -m cli --list                    # saved runs; --resume <id> continues one
python -m cli --profile examples/beginner_renewables.json
python -m cli --profile examples/conflicted_crypto.json   # shows the interrupt
python -m cli --save-profile mine.json

python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 707 tests, a few seconds, no network

python -m evals.runner                  # Agent 1: 30 labelled cases
python -m evals.runner --tag hard       # just the 12 hard ones (12 calls)
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
