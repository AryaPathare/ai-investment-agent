# Start here

Last worked: **2026-08-23** (session 7). **The pipeline is complete, demonstrable,
and durable, and the hardening pass is finished.** All five agents are built and verified against their own evals,
`python -m cli` runs the whole thing end to end, and a run that stops can be
resumed.

`docs/PROJECT_LOG.md` is current through Session 8.

**The git history was rewritten on 2026-08-23** to change the commit author from
`Nilesh <nileshp@fucient.com>` to `Arya Pathare <patharearya@gmail.com>`. Every
SHA before that point changed, so any commit hash written down elsewhere no longer
resolves. Nothing is pushed and there is still no remote configured.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **699 passed** in a few seconds.

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

### 2b. `SqliteSaver` — DONE this session

`checkpoints.py`. Every step is written to `.state/checkpoints.sqlite`, so
closing the terminal at a clarification prompt loses nothing.

```powershell
python -m cli --list                 # saved runs and which can be resumed
python -m cli --resume nilesh-1      # continue one
python -m cli --db other.sqlite      # point at a different database
```

Three things worth knowing before changing it:

- **A run has three states, not two.** `paused` (interrupted to ask a question,
  resume with `Command(resume=...)`), `stopped` (process died mid-stage, resume
  with `None`), `finished`. The `stopped` case resumes at the unfinished stage
  and does NOT repeat completed ones — a test proves Agent 1 is not called
  twice. On this project's quota that is the whole value.
- **`allowed_msgpack_modules` opts into a STRICT allow-list.** Passing it means
  unregistered types come back as dicts; passing no serializer at all falls back
  to a permissive default that reconstructs everything and merely warns it will
  stop. So dropping `serde=` looks harmless today and fails everywhere later.
  A round-trip test cannot catch that, so the test asserts the serializer's
  identity. Do not "simplify" it back to a round trip.
- **The database is not under `.cache/`** and must not move there. `.cache/` is
  documented as safe to delete; a paused clarification is not.

### 2c. Harder Agent 1 eval cases — DONE this session

12 new cases tagged `hard`, bringing the set to 30. `python -m evals.runner
--tag hard` runs just those, 12 calls instead of 30.

Why the old set scored 18/18: **every conflict case named the same word twice**
(`technology` vs "Do not invest in technology companies"), and every valid case
was lexically disjoint. The prompt gives that pattern as its worked example, so
string matching alone scored full marks. 13 of 18 also expected `valid`, so
answering "valid" every time was worth 72%.

The hard set is balanced 6/6 between the two verdicts — a test enforces it — so
a degenerate strategy scores 50%.

Cases can now also assert what a clarification CHANGED, not just the verdict:

```python
expected_status="valid",
expect_restrictions_exclude=("technology",),
expect_sectors_include=("technology", "sports"),
```

`valid` alone would also be returned by a model that left the contradictory
restriction in place, which is a contradictory profile reaching Agent 2.

**THE IMPORTANT CAVEAT — read before running it.** These have never been run
against the real model. They are validated against a deliberately naive
string-matching fake (12/12 on the old false-positive cases, 4/12 on the hard
set), which proves they separate string matching from judgment. **It does not
prove the labels are right.** The first real run is as much a test of the
labels as of the agent:

- ~8-10 of 12 is a good result and a usable baseline.
- **12/12 means they are still too easy**, not that the agent is perfect.
- Below ~5, suspect the labels first. Every case carries a `why` written
  specifically so that argument can be checked.

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
python -m pytest                        # 699 tests, a few seconds, no network

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
