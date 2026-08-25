# Start here

Last worked: **2026-08-24**. **The pipeline is complete, demonstrable, durable,
and published.** All five agents are built and verified against their own evals,
`python -m cli` runs the whole thing end to end, a run that stops can be resumed,
and CI proves the suite passes on machines that have never seen the project.

**The live CLI run and the Agent 1 hard set are now done** (2026-08-24). Five
tasks remain plus one new defect - see section 2. Everything verifiable today is
done. **Start with 2.6**: the fix is specified and needs one measured session.

- Repo: <https://github.com/AryaPathare/ai-investment-agent> (public, MIT)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- `docs/PROJECT_LOG.md` is current through entry 62

**The git history was rewritten on 2026-08-23** to change the commit author to
`Arya Pathare <patharearya@gmail.com>`. Every SHA before that point changed, so
any commit hash written down elsewhere no longer resolves.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **732 passed, 1 skipped** in a few seconds. (Not 707 - that was the
COLLECTED count. Do not add `-q`: pytest.ini already sets it, and `-qq`
suppresses the summary line, which is how the wrong number survived.)

Then see it work, without spending quota on a real run:

```powershell
python -m cli --help
```

---

## 2. THE TASK

**Check the Groq console before planning around these.** On 2026-08-24 the
console showed 113 tokens used for the day and a full CLI run went through
without a 429, so the rolling window HAD aged out overnight - the ceiling is
less binding than session 8 assumed. Read the console, not this paragraph.

### 2.1 Run the CLI live, end to end - **DONE 2026-08-24**

Ran in 255s, exit 0, run id **`cli-163fffe8`**. `python -m cli --resume
cli-163fffe8` replays the whole thing at zero quota. **That is the demo, and it
now exists.** Found three defects; see entries 52-54 of the log. Two are fixed.

### 2.2 Agent 1 hard-set baseline - **DONE 2026-08-24**

**11/12, 91.7%.** Against the rubric written with the cases (8-10 good, 12 means
too easy) the labels are one case away from not being hard enough. Worth
hardening when Agent 1 is next touched.

The single failure is not a label problem. It is 2.2b.

### 2.2b Agent 1 DELETES a user's restriction - **FIXED 2026-08-24**

Two halves. **Python**: `build_profile` refuses to drop a restriction unless the
USER's own replies mention what it is about - additions ungated, and the check
never reads the model's account of itself. **Prompt**: handing the decision back
is not a resolution, and an unresolved conflict narrows the sectors rather than
the restriction.

Verified live: clarification category 2/3 -> **3/3**, stable across `--repeat 3`.

### 2.2c The hard set has an error bar of one case - **NEW, measured**

`--repeat 3` on the hard set: eleven cases agree with themselves every time.
`hard_restriction_excludes_one_kind_of_bank` returns
`['needs_clarification', 'valid']` on identical input at temperature 0.

So **a single-shot 12-case score carries about +/-1 of noise, all of it in that
one case.** The two 11/12 scores recorded on 2026-08-24 are different results,
not a flat line: the first failed the clarification case, the second the bank
case. Use `--repeat` before concluding anything from a one-point move.

The case sits on the decision boundary between a restriction that NARROWS a
sector (banking, minus investment banks - valid) and one that BLOCKS it. A
prompt sentence would probably settle it. **Deliberately not done**: the Agent 1
prompt was changed an hour earlier, and entry 51 of the log is about exactly
this - tuning immediately after being burned by tuning. Make it a decision, not
a reflex.

### 2.3 Agent 3's eval - **DONE 2026-08-24**

**0 hard failures.** Drop accounting balances (7 examined = 3 candidates + 2
no_ticker_found + 2 incidental_mention), 0 scores saturated at 1.0, average
completeness 83%, no growth breaches. The debt from the operating-margin fix is
paid.

It surfaced 2.3b.

### 2.3b The restriction check tests words, not companies - **NEW**

That run recommended **TotalEnergies (TTE)** and **RWE** for a profile whose
restrictions are "No fossil fuel companies" and "No coal, oil or gas". The
eval's own check reported `restriction_violations: []`, because it is a
substring match over `name + exposure_rationale + themes`, and "TotalEnergies
SE" contains none of the forbidden terms while its rationale is about solar and
wind.

The recorded weakness was the FALSE-POSITIVE direction ("No crypto exposure" in
a rationale reading as a breach). This is the false-negative direction and it is
worse: the eval reports a clean run on a case a reader spots instantly.

`ResolvedCompany` already carries `sector` and `industry` from the provider.
"Oil & Gas Integrated" is a fact Python controls, which is the instrument this
project's own design rules point at. **Fix it in ONE place for both agents.**

Still true and now more interesting: Agent 5's exclusion path has never fired
on real data. TTE is the first candidate that should trigger it.

### 2.4 The zero-candidate profile - **FIXED 2026-08-24**

Not article variance: query variance. Agent 2's prompt was silent on whether a
retrieved article contains a COMPANY, and its own list of good subjects included
regulation and policy, which are written with a government as the subject.

Verified live on the profile that had been failing:

    before   0 candidates (8 articles about ministries and projects)
    after    3 candidates: SUZLON.BO 0.486, GOOG 0.450, AMZN 0.286
             completeness 83% -> 100%, 0 hard failures

The top candidate is now a wind turbine manufacturer, and an Indian listing -
the same class of company entry 53 found being dropped over a legal suffix.

### 2.5 Agent 3's exposure grade - **WRITTEN, NOT VERIFIED**

The prompt said a company "mentioned only as a customer" is incidental but gave
no ceiling, so Alphabet and Amazon were graded against a battery storage theme
for buying batteries. Added: where the industry sits outside the theme's sector
the highest grade is incidental unless the article shows the company producing
or supplying rather than using, and size does not change that. The test is which
way the money flows.

**Run `python -m evals.company_runner --limit 1` before believing any of it.**
Quota ran out first. Watch for GOOG and AMZN dropping out entirely, and for the
brief emptying instead of improving - see the pool-size warning above.

### 2.6 Agent 5's citations - **RE-DIAGNOSED, fix specified, NOT built**

**It was never given anything to cite.** The 1-of-8 rate was read as the model
taking the cheap option. Which company produced the one citation says otherwise:

    GOOG   0 risks                       0 articles reached Agent 5
    AMZN   1 risk, 1 article_id          1 article -> the ONE cited condition
    PBK    2 risks, both article_ids=[]  0 articles reached Agent 5

`RiskFindings.articles` keeps only articles a risk actually CITED, and
`risk_rules` produces metric-derived risks that cite nothing. The prompt's rule
is conditional on articles being supplied. **Agent 5 complied every time it
could: 1 of 1, not 1 of 8.**

The candidates carry `evidence_article_ids` (1, 1 and 2) the whole way, but
those Articles live in `ResearchFindings`, which `decide()` is never passed.

**The fix**: plumb `ResearchFindings` into `decide()` and widen `_evidence_for`
to include the candidate's own evidence articles. Not built today because it
changes what the last agent is fed - a theme article is bullish where a
bear-case article is not, so it could produce worse conditions as easily as
better ones - and there was no quota left to run `decision_runner`. **Build it
and measure it in the same session.**

### 2.7 The PDF - **DONE 2026-08-24**

`python -m scripts.build_log_html` renders `docs/PROJECT_LOG.md` to
`docs/project_log.html`. Open it and print to PDF: the stylesheet has page
rules, so sessions start on a new page and code does not split across one.

Written as a converter rather than a dependency because nothing in the
toolchain does markdown - no pandoc, no weasyprint - and installing one for a
file built twice a year is the worse trade.

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

**Re-diagnosed 2026-08-24 - read 2.5 before acting on this.** The live run
showed Agent 3 choosing from 3 investable companies out of 10 examined, because
renewable-energy news is dominated by private and foreign firms. Fixing the
prompt alone empties the brief instead of improving it.

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
  "/PRNewswire/") and issuer document types in the title. 18 of 283 cached
  articles match, all genuine. **Extended 2026-08-24** with four
  corporate-development document types - acquires an asset, receives a permit,
  announces a megawatt figure, secures project financing - after the live run
  sent three PowerBank announcements to the risk critic and it found no risk in
  any of them. **Filtering by SOURCE was tried and rejected on evidence**: six
  of the seven cached articles from globalrenewablenews.com are issuer
  announcements and the seventh is the Canadian Solar litigation headline, so
  the domain carries both and cannot be the signal. **Do not loosen it to a bare "announces" rule** -
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
- **The 12 hard Agent 1 cases are DONE** (2026-08-24): 11/12. The labels held
  up; the one failure is a real defect, now 2.2b. At 11/12 the set is close to
  being too easy - harden it when Agent 1 is next touched.
- **The CLI live run is DONE** (2026-08-24, run id `cli-163fffe8`, 255s). It
  worked on the first attempt. `--resume cli-163fffe8` replays it at zero quota.

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
