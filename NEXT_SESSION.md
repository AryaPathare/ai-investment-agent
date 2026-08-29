# Start here

**THIS PROJECT IS CLOSED.** Finished 2026-08-28, session 14, entry 89.
Session 15 re-recorded the demo from a live run (entry 90), fired the
restriction gate (91), and recorded how the handoff itself went stale (92)
and what the closing sessions rejected (93). Session 16 corrected the public
documents, which had drifted the same way (94), and a second reading against
the code found five more (95).

Sixteen sessions, 95 log entries, 816 passed and 1 skipped, CI green on Ubuntu
and Windows. The pipeline runs end to end, resumes when it stops, prices what it
recommends and says plainly when the answer is nothing.

**Nothing is owed except the v1.0.1 batch below, and nothing is unverified.**
Section 2 below is a record of
what was done, kept because the arguments in it are the useful part. Section 3
lists what was ACCEPTED rather than fixed, each with the evidence and the
instrument that failed.

**One decision stands**: 2.10's second half, making a failed run resumable. It
changes what `--resume` and `--list` mean for every run, so it needs deciding
before it is built. It is not a repair - the failure it recovers from is rare,
its immediate cause is fixed, and the run now reports itself honestly.

If you come back to this, read entry 89 first, then entry 87 - the second is the
clearest example of the habit the whole log is about.

- Repo: <https://github.com/AryaPathare/ai-investment-agent> (public, MIT)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- `docs/PROJECT_LOG.md` is current through entry **95**
- Tagged **`v1.0.0`** at `48f9c08` - the fixed point the case study cites

---

## v1.0.1: batched, deliberately not cut yet

Five known-wrong statements, all in code and example files rather than the four
documents `v1.0.0` covers, and none affecting anything the case study quotes.
Held as a batch because drafting the "what it does" section means checking every
behavioural claim against the code, which will probably find more. **Cut it once,
after the paper is drafted and before the post goes out.**

| Where | Says | Should say |
|---|---|---|
| `cli.py:294` | "Ask the eight questions" | nine |
| `cli.py:970` | "eight prompts between each attempt" | see below - the unit is wrong too |
| `tests/test_cli.py:660` | "Asking eight questions again" | nine |
| `examples/README.md:4` | "without retyping eight questions" | nine |
| `demo/recorded_run.json` | omits the optional `recorded_on` | so `--demo` prints no recording date |

`investment_currency` (entry 80, 2026-08-26) took the count from eight to nine;
entry 83 rebuilt the sector question without changing it. Verified twice:
`len(QUESTIONS)` is 9 and `ask_profile` asks all nine unconditionally, and
driving the CLI with nine piped answers consumed exactly nine and saved nine
fields.

**`cli.py:970` is wrong on the unit, not just the digit.** It counts PROMPTS
while everything else counts QUESTIONS, and those came apart the moment the
`ValidationError` re-ask loop existed: a rejected answer re-prompts without
adding a question, and Agent 1's clarification adds a tenth prompt only when it
finds a contradiction. Fix the vocabulary or the next person reintroduces the
ambiguity from the other side. **Same disease as 816 versus 817.**

**The git history was rewritten on 2026-08-23** to change the commit author to
`Arya Pathare <patharearya@gmail.com>`. Every SHA before that point changed, so
any commit hash written down elsewhere no longer resolves.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **816 passed, 1 skipped** in a few seconds - 817 collected, and the
distinction matters (entry 56). Counted at each session end: 760 passed after
session 11, 797 after session 12 (demo, margin invariant, prices, salvage), 811
after session 13 (the sector menu and the FX and plain-language work), 816 after
session 14 (entry 88's failed-run status).

Do not add `-q`: pytest.ini already sets it, and `-qq` suppresses the summary
line, which is how a wrong count once survived for two sessions.

Then see it work, without spending quota on a real run:

```powershell
python -m cli --help
```

---

## 2. THE TASK

### The salvage fix (entry 82) - **VERIFIED LIVE 2026-08-27**

Replayed `analyse_companies` over `cli-9760c4a2`'s checkpointed research - the
exact input that raised `OutputParserException` the day before. It completed:
5 examined, 1 candidate (688032.SS, direct, CNY 73.3).

**Caveat worth keeping.** That proves the pipeline survives the stage; it does
NOT prove the salvage path fired, because a well-formed reply looks identical
from outside. The salvage itself is covered by tests built from the real
exception text. If this ever needs settling properly, the honest instrument is a
counter on `salvage()` rather than another live run.

---

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

### 2.2c Narrows versus blocks - **DONE 2026-08-25**

**12/12, every case agreeing with itself across `--repeat 3`.**
`hard_restriction_excludes_one_kind_of_bank` - the case that flipped between
`valid` and `needs_clarification` - now lands the same way three times running.
Clarification held 3/3, nothing else started wobbling. Entry 67.

**The hard set is now TOO EASY and should not be trusted as a score.** The
rubric written with these cases says 12/12 means exactly that. It scored 11
yesterday with one case away from the boundary, that case was the defect, and
fixing it spent the margin. **Write harder cases before running it again** -
until then the run confirms rather than measures.

### 2.3 Agent 3's eval - **DONE 2026-08-24**

**0 hard failures.** Drop accounting balances (7 examined = 3 candidates + 2
no_ticker_found + 2 incidental_mention), 0 scores saturated at 1.0, average
completeness 83%, no growth breaches. The debt from the operating-margin fix is
paid.

It surfaced 2.3b.

### 2.3b The restriction check tests words, not companies - **FIXED 2026-08-24**

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
*(Superseded 2026-08-28: `restriction_violation` has since fired — entry 91.)*

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

### 2.5 Agent 3's exposure grade - **DONE 2026-08-25**

The rule holds. Verified by replaying Agent 3 over the 8 articles frozen in the
`cli-163fffe8` checkpoint - the exact inputs that produced the bad grades -
because the eval could not be used (see 2.8):

    GOOG   partial -> incidental_mention   "buys storage, not producing"
    AMZN   partial -> incidental_mention   "finances storage, buyer"
    META   -       -> incidental_mention   "buys solar electricity, not storage"
    PBK    direct  -> direct               "acquires solar assets"

The rationales quote the rule's own test back - which way the money flows.

**The brief emptied as predicted: 3 candidates to 1.** That is the right outcome
- the two losses were a mega-cap advertiser and a mega-cap retailer - but the
thinness is real and its cause is separate and known: only about 3 of 10
examined companies are investable, because renewable news is dominated by
private and foreign firms. Not repairable in Agent 3's prompt. Entry 69.

### 2.6 Agent 5's citations - **DONE 2026-08-25**

Built AND measured. `decide()` takes `ResearchFindings`; `_evidence_for` returns
the articles a risk cited PLUS the candidate's own `evidence_article_ids`,
deduplicated, bear case first. Four tests, two of which go red when the widening
is reverted.

Measured by replaying the frozen `cli-163fffe8` state, so the only variable is
whether research was supplied:

    recorded run                          1 of 8 conditions cited
    same inputs, research WITHHELD        1 of 7      <- same-session control
    same inputs, research SUPPLIED        3 of 7

**And the conditions read correctly**, which was the real question. The bullish
theme articles were INVERTED, not restated - "PowerBank's acquisition of the New
York solar portfolio is delayed or canceled", "Google announces it will no
longer finance battery storage projects". The hazard entry 70 predicted did not
happen. What got displaced was boilerplate: PBK's three generic metric
thresholds became one real condition plus one metric. Entries 70 and 72.

### 2.7 The PDF - **DONE 2026-08-24**

`python -m scripts.build_log_html` renders `docs/PROJECT_LOG.md` to
`docs/project_log.html`. Open it and print to PDF: the stylesheet has page
rules, so sessions start on a new page and code does not split across one.

Written as a converter rather than a dependency because nothing in the
toolchain does markdown - no pandoc, no weasyprint - and installing one for a
file built twice a year is the worse trade.

### 2.8 Agent 2's over-long queries - **DONE 2026-08-26**

The prompt described good and bad queries and never said what the search
actually does. Added the mechanism - every added word is another word the
article must also contain, and a proper noun is a rare word - plus the better
argument, that naming a company presupposes the answer this stage exists to find
out.

    before   1 article retrieved, 1 theme, 0 candidates
    after    14 retrieved, 5 themes, all on topic, 0 hard failures
             avg query 4.8 words, none over five, none naming a company

Confirmed again on a different sector the same day: six queries, all four words.
The runner now reports the three signals itself, and has its first tests.
Entry 73.

### 2.9 Agent 3's pool - **RE-FRAMED 2026-08-28, entry 87. It is themes, not articles**

    renewables      9 retrieved -> 3 cited     6 discarded
    semiconductors  17 retrieved -> 5 cited   12 discarded

`ResearchFindings.articles` keeps only cited articles and `analyse_companies`
reads that list, so company extraction works from the residue of a decision made
one stage earlier for a different purpose. **The same shape as entry 62**, where
`RiskFindings.articles` starved Agent 5 of anything to cite.

It is throttled harder than it looks: most themes cite exactly one article (13
of 18 in the baseline, 5 of 5 on both live runs) and there is a five-theme cap,
so the pool reaching Agent 3 is capped near five however many were retrieved.
The known cost of single-source themes was "thin evidence"; the real cost is
that it caps the company pipeline.

**Both options in this section are aimed one level away from the constraint.**
Agent 3 grades (company, theme) PAIRS, so an uncited article maps to no theme
and there is nothing to grade its companies against. Widening the article list
does not widen the candidate list.

**Tried and rejected 2026-08-28** (entry 87): telling Agent 2 to cite every
supporting article. Measured against a same-session control on the same profile:

                        themes  cited  mentions  companies  candidates
        with the rule      3       5        5         5          1
        control            5       6       13        10          2

Worse on every axis, because the model CONSOLIDATED - three themes instead of
five - and theme count drives the pool harder than citations per theme.

**So the real ceiling is `research_max_themes` (5), with most runs producing
three to five.** That is the number that caps how many companies can ever be
examined. Anything done here should start there, and should use a control run -
the treated run alone looked like a success.

**It only bites when the pool is thin**, which is why two runs were needed to
see it - in semiconductors, discarding twelve articles cost nothing.

### 2.10 A failed last agent is not resumable - **HALF DONE 2026-08-28, entry 88**

Agent 5 died on an intermittent empty-generation 400 during a live run. The
retry that Agents 2 and 3 already had is now added, so the immediate cause is
fixed. The structural part is not.

`decide_node` catches the exception and records it in state, so the graph
FINISHES - cleanly, by design, because a traceback must never reach a user. But
`--resume` then sees a completed run rather than something to continue, and the
research, company analysis and risk critique already paid for (~30k) cannot be
picked up from the CLI.

**The labelling half is DONE** (entry 88). A failed run was reported as
`finished` by `--list` and `--resume` said "already finished, showing what it
produced" directly above THE RUN COULD NOT FINISH. `state["error"]` was already
there; nothing looked at it. There is now a fourth status, `failed`, and
`can_resume` lists what CAN resume rather than excluding what cannot.

**Resumability itself is still open, and still a decision.**

**Ending cleanly and being recoverable are different properties**, and this is
the first time the difference cost anything. It was recovered by replaying
`decide()` over the checkpoint by hand - one model call instead of twelve -
which is the fourth time the checkpoint database has been a recovery instrument
rather than a resume feature.

The decision: should a stage that failed be resumable, and if so, how does the
graph distinguish "finished with an error" from "finished"? That changes what
`--list` and `--resume` mean, so decide it before touching code.

### 2.11 The shipped demo - **RE-RECORDED 2026-08-28, entry 90**

`demo/recorded_run.json` holds `cli-0562c71f`: NVIDIA, Samsung and SMIC, all
graded `direct` against an AI chip-capacity theme, each with an article-cited
exit condition carrying a real headline and a working link, all three priced
across three currencies, plus a fourth company recorded as considered and not
chosen.

The widest brief this pipeline has produced, and the one `python -m cli --demo`
shows. It replaced the two-company Lam Research / Applied Materials recording
made a day earlier.

Saved runs, all replayable at zero quota:

    cli-0562c71f   technology + utilities, 3 recommendations  (the recording)
    cli-11a4243b   semiconductors, 2 recommendations, priced
    cli-9760c4a2   grid storage - the OutputParserException run, now fixed
    cli-f7bbd302   renewables, recommends NOTHING
    cli-008657ee   healthcare - the run that exposed the margin bug

To re-record after a better run, serialise its checkpoint: `recorded_on`,
`profile`, `decision`, `research_findings`, `risk_findings`. Costs no quota. The
tests deliberately pin neither the company nor the count.

**The current recording omits `recorded_on`**, so `--demo` prints no recording
date. Harmless - the field is optional - but include it next time.

## 3. Then the known weaknesses

All measured, all deliberately left. Work them in the order they would change an
answer a reader sees.

### Agent 3 grades data-centre operators as "direct" - **FIXED AND VERIFIED**

Resolved 2026-08-25, entry 69. Google and Amazon are now graded
`incidental_mention` and dropped; the ceiling rule holds against the exact
articles that produced the bad grades. See 2.5.

What remains is the consequence, and it is not a defect: the brief for
`renewables_excluding_fossil_fuels` is now ONE company. Only about 3 of 10
examined companies are investable on this theme. **A thin brief is the honest
output here** - the alternative was two mega-caps in front of a beginner asking
about renewable energy.

### Agent 5 barely reads the articles - **FIXED AND VERIFIED**

Not a lazy model. It was never given anything to cite: cited equalled citable on
every candidate of the last real run. Fixed and measured 2026-08-25 - 1 of 7 to
3 of 7 on identical inputs, and the new conditions displaced boilerplate rather
than adding to it. See 2.6, entries 70 and 72.

### Agent 2 records almost no dissenting evidence - **ACCEPTED**

Structural, not a prompt problem: most themes cite one article and one article
cannot disagree with itself. It is the shape of a three-article-per-request news
budget. Worked around by giving Agent 4 its own adversarial retrieval, which
means **the workaround is load-bearing** - if Agent 4's bear queries ever stop
returning anything, this comes back immediately and there is nothing behind it.

**Recorded as accepted in entry 71**, on the same terms as the scoring limits.
Do not reopen without a reason that has actually changed.

### Agent 4's source filter cannot cover its long tail - **ACCEPTED**

**Recorded as accepted in entry 71.** A list of names cannot cover a
distribution whose mode is one, and both instruments that would work on the tail
were tried and failed on real data. What replaced the list is the press-release
filter, which tests article SHAPE rather than publisher. The detail below stays
because the press-release rules under it are live and must not be loosened.

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

- **`restriction_violation` FIRES CORRECTLY** (2026-08-28, entry 91), replayed
  over the real candidates of `cli-0562c71f`: NVDA and 0981.HK excluded on
  industry "Semiconductors", Samsung and Alibaba kept. It had never fired live
  because Agent 2 honours restrictions at QUERY time, so nothing forbidden
  usually reaches selection at all - the gate is rarely reached, not broken.
  **`disqualified_by_risk` is still unverified**, and deliberately: firing it
  would mean inventing a critical risk, which substitutes agent output rather
  than user input.
- **A thin-sector brief can legitimately be empty**, and 2.9 makes that more
  likely than the pool alone would. Do not read an empty renewables run as a
  regression without checking retrieved-versus-cited first.
- **The 12 hard Agent 1 cases score 12/12 and are therefore too easy.** By the
  rubric written with them that is the definition. The number is no longer
  evidence about Agent 1.
- **Verifying a fix against its exact failing inputs keeps beating another eval
  run** - four of the last five verifications were done that way, including the
  2.6 measurement, where a same-session control run made the result readable in
  a way a single number could not have been.
- **Agent 3's ceiling and Agent 5's citations were measured on stale candidates
  on purpose.** GOOG and AMZN would no longer reach Agent 5 at all. Holding the
  inputs constant is what made it a measurement of Agent 5 rather than of the
  whole pipeline.

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
gh run list --limit 3                   # CI status; authenticated 2026-08-25
gh run view --log-failed                # just the failing output, not the whole log

python -m cli                           # run the pipeline for a person
python -m cli --list                    # saved runs; --resume <id> continues one
python -m cli --profile examples/beginner_renewables.json
python -m cli --profile examples/conflicted_crypto.json   # shows the interrupt
python -m cli --save-profile mine.json

python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 816 passed, 1 skipped; no network

python -m evals.runner                  # Agent 1: 32 labelled cases
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
