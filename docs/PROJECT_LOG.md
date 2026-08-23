# Project Log

A running record of what was built, what went wrong, and why each decision was
made. Written as it happens rather than reconstructed afterwards, because the
reasoning behind a decision is the first thing lost once the code works.

**Append a new session section at the end of every working session.**

---

## The project

A multi-agent investment research system. It takes an investor's profile,
researches current market themes from real news, finds public companies
genuinely exposed to those themes, attacks the thesis, and recommends up to
three stocks — or explicitly recommends **nothing** when nothing clears the bar.

**Stack:** Python 3.14, LangGraph, Pydantic 2, Groq (`openai/gpt-oss-20b`),
TheNewsAPI, Financial Modeling Prep, yfinance.

**Purpose:** a portfolio and interview project. That goal shapes what "done"
means — the system has to be defensible under questioning, not merely running.

### Pipeline

```
START → Profile → (valid) → Research → Companies → Risk Critic → Decide → END
              ↳ (conflict) → ask user → back to Profile
```

| Stage | Job | State |
|---|---|---|
| 1. Profile | Validate investor input; ask about genuine contradictions | Built |
| 2. Research | Identify themes, grounded in retrieved news | Built |
| 3. Companies | Extract, resolve, screen and rank companies | Built and verified |
| 4. Risk Critic | Retrieve the bear case and attack each candidate | Built and verified |
| 5. Decide | Select, write the case, state exit conditions | Built and verified |

---

## Principles that shaped every stage

These emerged early and were applied consistently. Most of the interesting work
follows from them.

**LLMs judge; Python computes.** Anything calculable or checkable stays in code.
A negative investment amount is rejected by Pydantic, not reasoned about. Models
are used only where genuine ambiguity requires judgement — and in Agent 3, only
two of nine pipeline steps need one.

**The model returns a verdict, never the data.** Applied three times in three
different disguises:

- Agent 1: the model cannot emit the user's age or investment amount, so it
  cannot corrupt them.
- Agent 2: `Evidence` has no `url` or `title` field, so a fabricated source is
  impossible rather than discouraged — it can only cite an article Python
  already retrieved.
- Agent 3: `CompanyMention` has no ticker field. `NVDA`, `NVDA.NE` and `NVD.DE`
  are all real symbols for Nvidia, so a guessed one does not *look* wrong; it
  silently returns a different company's financials.

**Encode rules in types, not comments.** A comment saying "never compare these
across currencies" gets ignored eventually. Splitting `ComparableMetrics` from
`CurrencyAmounts` means reaching the wrong one requires crossing a type
boundary.

**Every loop is bounded by code, never by the model.** A model is never trusted
to decide when to stop.

**Rejections are recorded, not discarded.** `drop_summary` is what distinguishes
"3 candidates from 30 mentions" as good filtering from the identical numbers
produced by a broken resolver.

**Coarse judgements over invented precision.** `high/medium/low` and
`direct/partial/incidental` instead of 0-100 scores. A model asked to score
something 0-100 returns 72 with nothing behind it.

**Returning nothing is a designed outcome.** At every stage — no themes, no
companies, no recommendation — "nothing cleared the bar" is a legitimate answer
rather than a failure.

---

## Session 1 — 2026-08-19 → 2026-08-20

### Starting point

A working prototype built in a previous tool: Agent 1 validated investor
profiles and paused for clarification via a LangGraph `interrupt`. It ran. A
review found four structural problems, none of them visible from the output.

### What was done

Rebuilt Agent 1, then built Agents 2 and 3. 32 commits.

### Agent 1 — hardening

| Problem | Fix |
|---|---|
| Unbounded clarification loop | Bounded at 3 attempts with a defined give-up outcome |
| Each clarification overwrote the last | `Annotated[list[str], add]` accumulates them |
| The LLM could silently rewrite user data | Model returns a verdict; Python composes the profile |
| Tests were scripts that hung on `input()` | 58 real tests, no network, 0.3s |
| No config, no timeouts, globals at import | `config.py` with lazy, validated settings |

The schema change is the one worth remembering. `InvestorProfile` had been the
schema handed to `with_structured_output()`, so the model re-emitted the user's
age, amount, interests and restrictions on every call and could alter any of
them. It now returns `ProfileAssessment` — a verdict plus a narrow whitelist of
fields a clarification may legitimately revise.

**A prompt rule got deleted as a result.** Rule 1 had said "Preserve the user's
information. Do not invent new preferences." That existed only to compensate for
the schema flaw. Once the model structurally could not touch those fields, the
rule became dead weight. *When a prompt rule is patching a design problem, fix
the design.*

**Scope was cut, deliberately.** The original plan had 8 agents, 4 external
APIs, SQLite, a scheduler and backward routing. It became 5 agents, one or two
APIs, no database, no separate supervisor:

- **Agent 8 (monthly monitoring)** — a long-running service, not a pipeline
  stage. Needed a scheduler, position tracking and stored baselines. Substitute:
  re-run the pipeline.
- **GDELT** — an event database for geopolitical analysis, not a
  trend-identification tool. Old Agents 2 and 3 merged into one Research agent.
- **SEC EDGAR** — duplicates FMP and requires XBRL parsing.
- **The Supervisor** — everything left of its job is a LangGraph feature: edges
  for routing, `retry_policy` for retries, `interrupt` for clarification,
  Pydantic for validation. An LLM router would be *less* reliable than edges.

### Agent 2 — Research

Search first, *then* synthesise. Asking a model what trends matter and then
hunting for support is confirmation bias with a training cutoff attached. It
retrieves real articles, then asks the model to read them.

Citations use short labels (`[A3]`) because a model copies two characters
reliably and a 36-character uuid unreliably. Python maps them back and discards
any that do not exist.

### Agent 3 — Companies

Nine steps, two of which need a model: spotting which companies an article
names, and judging whether a company is genuinely exposed to a theme or merely
appeared in the same paragraph.

Exposure is graded per **company-theme pair**, not per company. The test that
proved it mattered:

```
Northern Trust vs AI data centre buildout  → incidental
Northern Trust vs bank share buybacks      → direct
Nvidia         vs AI data centre buildout  → direct
Nvidia         vs bank share buybacks      → incidental
```

Ranking is pure arithmetic over provider figures. The model contributes exactly
one input — the exposure level. Screening rejects only what is genuinely
disqualifying, and notably **not** high leverage on its own: a blanket
debt-to-equity threshold would silently exclude every bank, insurer and utility
from a system meant to research banking themes.

---

## Bugs found — the interesting part

Every one of these produced *plausible output*. None would have been caught by
looking at the results.

### 1. The search year that quietly degraded relevance

The model appended its training-cutoff year to every query:
`"solar farm approvals 2024"`. First assumption was that this would fight the
date filter and return nothing. **Measuring it proved that wrong** — article
counts were identical. But the *articles* were worse:

| Query | Top results |
|---|---|
| `solar farm approvals` | a solar farm upgrade, solar-powered farming |
| `solar farm approvals 2024` | an asset acquisition in Poland, diesel generators |

The year pulls in articles that merely *mention* it. **"It returned results" is
not "it worked."** The fix went into the prompt with the measurement attached,
so nobody deletes the rule later wondering if it matters.

### 2. Deduplication that merged different stories

Title-similarity dedup scored these at ~0.97:

```
"Tesla Q2 earnings beat expectations"
"Tesla Q3 earnings beat expectations"
```

Financial headlines are formulaic and differ in exactly the token that carries
the meaning — a quarter, an amount, a capacity. Merging them destroys evidence,
which is the failure dedup existed to *prevent*. Numbers in both headlines must
now match before similarity is considered. Found by writing an adversarial test,
not by observation.

### 3. A config edit that silently disarmed Agent 1

An index-based slice while editing `config.py` swallowed the section between two
anchors, deleting `max_clarification_attempts` — the setting bounding Agent 1's
loop. Seven tests failed instantly, all of them the loop-bound tests written the
day before.

**This is what tests are actually for.** Not proving code works when you write
it — proving it still works after you touch something unrelated. Without them,
a config edit made while building Agent 2 would have removed Agent 1's
termination guarantee, and nothing would have complained until it ran forever in
front of a user.

### 4. Three resolution bugs, all caught by `drop_summary`

The first real Agent 3 run produced four candidates and looked like success. The
rejection list did not:

```
AMD        not_an_operating_company     ← AMD is obviously a real company
Google     not_an_operating_company
Synopsys   no_fundamentals
Marvell    no_fundamentals
```

- **Word matching rejected correct answers.** "AMD" shares no word with
  "Advanced Micro Devices, Inc."; "Google" none with "Alphabet Inc." The guard
  that saved us from a cryptocurrency matching "SMIC" created a new failure.
  Fixed by accepting *either* a name match or a symbol match.
- **FMP's free tier covers only a subset of US symbols**, not merely US-only.
  AMD and NVDA work; SNPS and MRVL, both major Nasdaq companies, return 402.
  Now falls back to yfinance.
- **A tie was broken by luck.** "SMIC" matched the Hong Kong primary listing and
  a Singapore depositary receipt equally, so the winner depended on search
  ordering — which changed between runs. *Nondeterminism producing a plausible
  answer is the worst kind: it does not look like a bug.*

**Without `drop_summary`, this would have shipped.**

### 5. A fund filter defeated by changing metadata

`SPCF` ("ProShares Ultra SpaceX") was rejected correctly using `quoteType=ETF` —
then an hour later the same ticker reported `quoteType=EQUITY, legalType=None`.
Same code, same ticker; the upstream data changed.

Not a bug in the implementation. **The lesson: when a check guards something
important and rests on one external signal, get a second signal that fails
differently.** Fund *names* (sponsors, leverage markers) are marketing terms and
effectively stable. The blocklist deliberately excludes generic words like
"trust" and "fund" — verified that Northern Trust and Ultra Clean Holdings still
resolve.

### 6. Structured output: right data, wrong envelope

Every schema wraps a single list, and the model regularly returns the bare list
instead of `{"mentions": [...]}`, sometimes inside a ```json fence. The provider
rejects it and the call fails — discarding *correct* extracted data.

Two things made this worth a real fix:

- It survived **three identical retries**. Deterministic, so retrying only
  spends another call to be told the same thing.
- It happens under **both** structured-output methods, merely on different
  schemas: `function_calling` failed on `MentionExtraction`, `json_schema` on
  `ThemeProposal`. Switching methods trades one failure for another.

`agents/structured.py` now recovers the rejected generation, strips the fence,
wraps a bare list, and **re-validates against the schema exactly like a normal
response**. Verified that valid JSON violating the schema is still refused: this
loosens the transport, never the contract.

### 7. An eval that measured the wrong thing

The Agent 3 eval reported "1 mention vanished without a drop reason." It was
balancing candidates and drops against *mention rows* — but a company named in
three articles is three mentions and one company. The check was right; its
denominator was not. `companies_examined` was added so the balance is
meaningful.

---

## Session 2 — 2026-08-21 → 2026-08-22

### Starting point

Agent 3 was built and wired in, but unverified: its eval baseline had never
completed, because the account hit Groq's daily token ceiling after one profile.
Unit tests all passed. That distinction turned out to be the theme of the whole
session — **the unit tests prove the code does what it says; only the evals show
whether what it says is right.**

### What was done

The baseline ran across all five profiles. It reported **0 hard failures** — and
then four real defects were found anyway, every one of them in the soft signals
or in behaviour no hard check was looking at. All four are fixed, each with a
regression test that names the company that exposed it. **267 tests became 276.**

Two new eval checks were added, and both immediately earned their place.

### 8. One field, two meanings, depending on who answered

The baseline showed TSMC labelled `TWD`. That looked wrong — TSM is a New York
ADR that trades in dollars — and it was, but not in the way it first appeared.

`CurrencyAmounts.currency` was being set from `reportedCurrency` on the FMP path
and from `currency` on the yfinance path. Those are different things: the first
is what the STATEMENTS are reported in, the second is what the SHARE trades in.
So the field meant one thing for a US company and another for a foreign one.

The visible damage: SK hynix's net income of **162 trillion won** was labelled
USD. Read as dollars, that is more than global GDP.

It had corrupted **nothing**, because all four screening metrics are ratios and
ratios are currency-invariant. It was found by inspection, not by failure — and
fixed before Agent 4, which consumes this field, could ever act on it. PowerBank
turned out to be mislabelled the same way and had not been noticed at all.

This is the same failure as the `debtToEquity` percentage-vs-ratio bug from
session 1: two providers, one field name, two conventions. Worth stating as a
rule — **when two providers populate one field, the field needs one definition
written down, not two implementations that happen to agree on the common case.**

### 9. A ranking that could not rank

Two candidates came back at exactly **1.000**: TSMC and SK hynix. Every one of
the four metric ramps had clipped at its cap for both of them.

They are not equivalent companies. SK hynix was growing revenue at 256% and TSMC
at 33% — an eight-fold difference, rendered as an identical score. A ranking
whose top two cannot be ordered is not ranking.

The thresholds were the problem: full marks sat at 30% growth, a 25% operating
margin and a 60% gross margin, which is where a *strong* company lives, not an
exceptional one. They were raised to 50% / 40% / 75%.

The tie broke — TSMC fell to 0.877 — and **rank order was preserved exactly**,
with no inversions anywhere, which was the stated success criterion decided
before the change rather than after.

**What this deliberately does not fix:** SK hynix still scores 1.000, because a
ramp clips by construction. That was accepted rather than fixed. Saturation
mattered because it produced a TIE; one company at 1.000 is ranked first, which
is correct. Removing the number entirely needs a soft-saturating curve, which
would re-calibrate every company in the system to change one number that changes
no ordering.

### 10. Clipping hides bad data, so the check has to sit upstream of it

SK hynix's 256% revenue growth is almost certainly a provider artifact — its real
figure is closer to 100%. Nothing caught it, and nothing could have, because
every value above the cap renders as 1.0: an implausible 256% and a healthy 55%
are indistinguishable by the time scoring has finished.

A `GROWTH_SANITY_CEILING` was added to the eval as a SOFT signal, deliberately
not a hard failure — extraordinary growth genuinely happens in a memory upcycle
or after an acquisition, so a breach means "look at this", not "this is a bug".

The general lesson is worth more than the check: **a metric that clips cannot
also serve as a data-quality alarm.** The alarm has to sit before the clipping.

### 11. A meaningless zero, read as a terrible one

A banking run produced one candidate scoring 0.309, and its gross margin was
`0.0`. Banks have no cost of goods, so gross margin is meaningless for them —
but yfinance returns a literal `0.0` rather than nothing, the code accepted it as
a real observation, and it scored at the very bottom of the ramp.

That inverts the rule the scoring is explicitly built on: *a missing metric is
unknown, not bad.* Here a NOT-APPLICABLE metric was being scored as bad.

Then a healthcare run made it much worse. It returned two pre-revenue biotechs,
CervoMed and ProMIS, **both scoring exactly 0.000** — to a 66-year-old investor
with low risk tolerance. Same placeholder `0.0`, different sector.

Three companies across two unrelated sectors made it clear this is a provider
convention, not a quirk. Handled at the provider boundary in
`clients/companies.py`, for BOTH providers, so the field means one thing whoever
served it — the rule learned in bug 8, applied straight away.

### 12. A conjunction cannot fire when one side is missing

CervoMed reported an operating margin of **-94.07**. It loses ninety-four times
its revenue. It passed screening.

`screen()` rejected on *shrinking AND unprofitable* — deliberately, so that a
profitable company having a flat year, or a fast-growing one investing ahead of
profit, would not be discarded. But CervoMed's revenue growth was unreported, so
`shrinking` was False, so the conjunction could never fire. A perfectly sound
rule was defeated by a missing input.

Losing more than all of your revenue is now disqualifying on its own, checked
BEFORE the conjunction so it cannot depend on a second metric being present. And
a candidate scoring zero is dropped rather than ranked last, because ranking it
last still means recommending it.

### 13. The estimate that was wrong by a factor of four

Midway through, the token budget was reported as roughly 30% spent. It was
actually **99%** spent, and the final five-profile verification run died after
one profile.

The cause was trusting a documented figure instead of measuring: the handoff note
said a profile costs ~6,000 tokens. The real cost is **25-30k** — the reasoning
model spends far more before the visible answer than that number assumed. Seven
profiles consumed essentially the entire daily ceiling.

Recorded here because it cost a full verification run, and because the wrong
number had been sitting in the handoff note being believed for two sessions. It
is now corrected in both the handoff and the memory.

### 14. What "verified" honestly means here

The re-runs could not confirm everything, and it is worth being precise about
what was actually established rather than implying more.

Agent 2 retrieves different articles on every run, so candidate SETS differ
between runs. CervoMed and ProMIS never reappeared, and one banking run resolved
only 3 of 7 mentions and returned zero candidates — so the exclusion check had no
candidates to iterate over and was not exercised there.

Each fix was therefore verified at the layer where the evidence is strongest:

| Fix | Confirmed how |
|---|---|
| Currency | Live — PowerBank read `CAD` |
| Recalibration | Live — scores matched offline predictions to three decimals |
| Growth sanity | Live — fired on SK hynix at 2.568 |
| Exclusion check | Live on renewables, no false positives |
| Placeholder zero | Directly, across ten major banks plus both biotechs |
| Score floor, catastrophic margin | Unit test through the real `analyse_companies` |

**0 hard failures on every post-fix run.** The remaining gap is not a code path —
it is which companies a given article draw happens to surface.

### 15. Deciding what NOT to fix

Two known limits were found, measured, and deliberately left in place: SK hynix
still scoring 1.000, and financial companies capped at 0.50.

Both distort absolute scores. Neither distorts an ordering anyone consumes — the
tie is gone, and profiles are sector-themed so every bank carries the same
handicap. Both are documented in the module docstring of `agents/screening.py`
with the reasoning, so they are not rediscovered and re-litigated later.

The alternative for each was a real design change — a soft-saturating curve, or
completeness measured against what is obtainable per sector — spent on making a
number look better without changing a decision. Recording *why* something was
left alone is worth as much as recording what was fixed.

---

## Session 3 — 2026-08-22

### Starting point

Agents 1-3 verified. Agent 4 not started. The open question was what to do about
Agent 2 recording dissenting evidence essentially never, since a risk critic
built on a one-sided corpus would confirm whatever it was handed.

### 16. Diagnosing the dissent gap instead of fixing the prompt

The obvious move was to rewrite Agent 2's prompt, which already asks explicitly
for `weakens` and `complicates` stances and explains why they matter. Reading
the saved research evals first showed the prompt was not the problem:

| Profile | Themes | Single-source | Avg citations/theme | Dissent |
|---|---|---|---|---|
| renewables | 4 | 3 | 1.25 | 0 |
| healthcare | 2 | 2 | 1.00 | 0 |
| sports | 2 | 1 | 2.00 | 0 |
| semiconductors | 5 | 2 | 1.60 | 0 |
| banking | 5 | 5 | 1.00 | 0 |

Two structural causes, neither reachable by wording:

1. **A theme citing one article cannot record dissent** — there is no second
   article to disagree with the first. Most themes cite exactly one, so the
   dissent rate is not low, it is arithmetically unavailable. The one time
   dissent ever appeared was in the profile with the highest average (1.75).
2. **Themes are derived from their own evidence.** Agent 2 reads articles and
   names the pattern it sees; an article contradicting the pattern becomes a
   DIFFERENT theme rather than dissent within this one.

Underneath both: TheNewsAPI's free tier returns 3 articles per request.

**Decision: do not rework Agent 2. Give Agent 4 its own adversarial retrieval.**
A risk critic that depends on the researcher having already been self-critical
is not much of a critic - finding counter-evidence IS the job. This also avoided
a second calibration cycle on an agent already verified.

### 17. The division of labour, applied again

Agent 4 reuses the split that Agents 2 and 3 settled on. Per candidate:

    Python   builds bear-case queries          deterministic
    Python   retrieves articles                news client, cached
    LLM      reads articles, returns risks     judgement about prose
    Python   discards risks citing nothing retrieved
    Python   adds risks derived from fundamentals
    Python   computes the verdict from severities

Two consequences worth stating. **Agent 4 produces no score** - Agent 3's
ranking is Python arithmetic precisely so it is reproducible, and a
model-invented number competing with it would destroy that. And **fundamental
risks are computed in Python and never shown to the model**, because a model
handed a balance sheet and asked what could go wrong writes fluent sentences
whose relationship to the numbers cannot be checked. Those rules also give the
agent a FLOOR: a quiet week retrieves no bear-case articles, and without them
the critic would report nothing, which reads as reassurance.

The schema does the rest of the work. A `Risk` must cite either a retrieved
article or a named metric, and a validator refuses to construct one that cites
neither. Not discouraged - refused, because there is no way to check it.

### 18. A green suite and a dead agent

351 unit tests passed. Every one of them stubbed the news client, so all of them
passed while **the model was never being called at all**.

The eval reported `HARD FAILURES 0` on a run that measured nothing: zero
bear-case articles retrieved, so the agent returned early every time and only
the fundamental rules ever fired. The soft signals that were supposed to catch
manufactured criticism read `generic claims 0`, which was true and worthless.

The cause was one word. TheNewsAPI does not support `OR` as query syntax:

    "Pfizer" lawsuit OR investigation OR probe   ->  0 articles

**The obvious fix was worse than the bug.** The provider does support `|`, but
it ORs across the WHOLE query, so the company name stops being required:

    "Pfizer" lawsuit | investigation | probe     ->  3 articles, two about an
                                                    Israeli army probe and an
                                                    Air India incident

That would have handed the model an off-topic article and asked what risk it
poses to Pfizer - an invitation to invent one, in the agent built to prevent
exactly that. It was only caught by printing the headlines instead of trusting
the count. Plain space-separated AND keeps the company mandatory and is what
shipped, at the cost of one angle per query.

A third variant of the same mistake: `"Pfizer" Vaccine Demand Shifts` is four
ANDed terms and returns nothing, so theme queries now contribute a single
most-distinctive keyword with filler words like "demand" and "growth" removed.

### 19. Three ways to lose an answer that was already correct

With retrieval fixed the model finally ran, and failed twice more - both in the
envelope rather than the answer, which is the failure `agents/structured.py`
exists for.

**Truncation.** `RISK_MAX_TOKENS` was 1600, the smallest budget in the project,
for a call comparable to the theme call's 3000. The generation was cut off
mid-sentence - `"Pfizer's non-"` - leaving no valid JSON to salvage. This is the
reasoning-model trap already recorded here: the budget must cover the thinking,
not just the output.

**A tool named `functions.NewsRiskAssessment`.** The client rejects the whole
response with "Unknown tool type", and that error carries no `failed_generation`
to salvage from, so a correct answer is discarded over a naming convention.
Fixed by asking for `json_schema` output instead, which removes the tool
envelope and with it the chance to misname it.

**A wrapper that validated as an empty answer.** The model sometimes returns the
whole tool call, `{"name": ..., "arguments": {...}}`, rather than its arguments.
Salvage was extended to unwrap it - and the new tests immediately showed the
first attempt made things worse. Every schema in this project gives its fields
defaults, so the OUTER dict validates perfectly well as an EMPTY result:
pydantic ignores the unknown keys and fills the rest in. Checking the wrapper
first therefore "succeeds", returning **zero risks while the real ones sit one
level down** - silent data loss that looks like a clean answer, in the one agent
where "no risks found" must never be a lie. Fixed by trying the arguments first,
with a test asserting the ORDER rather than the outcome.

`agents/structured.py` had no tests at all despite being load-bearing for four
agents. It now has 15, each naming the real failure it came from.

### 20. Grounded, specific, and resting on a blog

With everything working the eval reported 0 hard failures, 0 generic claims and
0 discarded risks. Reading the actual claims told a different story:

| Severity | Claim | Source |
|---|---|---|
| material | Trump admin vaccine-splitting could raise production costs | arstechnica.com |
| minor | $44M Chantix settlement increases costs | fastcompany.com |
| **material** | Misinformation could erode vaccine demand | **joemygod.com** |
| **material** | Litigation over vaccine-induced miscarriages could raise costs | **joemygod.com** |

The last two derive from coverage of a **debunked** claim - one article
explicitly calls it a lie, the other is an advocacy group's fundraising appeal
premised on it. The model treated a donation solicitation as evidence of
litigation risk and graded it material. Both risks were specific, correctly
cited, and passed every check.

**Grounding in a retrieved article is necessary and not sufficient.** The
citation was real; the article was worthless.

Worse, they compounded. The verdict threshold is two material risks, so a single
dubious news cycle - counted twice - tipped Pfizer from `survives` to
`weakened`. The arithmetic is only sound if the risks it counts are independent,
and nothing enforced that.

Two fixes:

- **A source filter** in `clients/news.py`, applied before the model sees
  anything. This is an editorial judgement and an uncomfortable one, so it is
  kept short and visible in code rather than buried in a prompt - the same
  reasoning as the screening thresholds. The test applied is not political
  slant but whether the outlet does original REPORTING a business decision could
  rest on. An opinion blog may be entirely right and still not be evidence that
  a company faces litigation.
- **De-duplication** before the verdict: risks sharing an article collapse to
  one, keeping the most severe. Stated honestly, this would NOT have caught the
  Pfizer case - those two risks cited two different articles - but it fixes the
  related problem of one story counted twice crossing the threshold alone.

Verified against the exact failing case: 6 articles retrieved, 2 dropped, both
fabricated-litigation risks gone, the legitimate Chantix finding kept and
correctly downgraded to minor, verdict corrected to `survives`.

### 21. The measurement that could not measure

Every soft signal in the risk eval counts something, and none of them could see
the problem above. `generic_claims: 0` was accurate: the claims WERE specific.
They were specific and wrong.

The runner now prints every claim with the source behind it -
`[material] regulatory (joemygod.com)` - so provenance sits next to the finding.
It is the only check in the file that does not produce a number, and it is the
one that found the defect that mattered.

### What was NOT verified, and why it matters

Agent 3 retrieves different articles every run, so each eval run tests a
different slice. Across the last three runs one profile produced zero candidates
and another produced only fundamental risks, so "0 hard failures three times" is
weaker evidence than it sounds. The Pfizer check above - run directly against the
exact failing inputs - is stronger evidence than any of the eval runs.

The source list is seven domains drawn from one afternoon of searches. A
low-quality outlet not on the list simply passes, and there is no mechanism to
notice when it should have been added.

---

## Session 4 — 2026-08-22 → 2026-08-23

### Starting point

Agents 1-4 verified. Agent 5 not started. **The pipeline was finished this
session** - Agent 5 built, verified, and every stage now connected end to end.

### 22. Changing the question the project asks

Before any of Agent 5, the premise was reconsidered. The system asked for the
investor's *interests*, and the honest objection was that almost nobody picks
stocks because of their hobbies. The project reads better, and is more useful,
as a tool for someone who wants to start investing and does not know where to
begin: they say which SECTORS interest them.

**A fixed list of sectors was considered and rejected.** It is the obvious
implementation and it would have been worse:

* Standard sector labels classify BUSINESS MODELS while people think in THEMES,
  and the two do not line up. A solar manufacturer is classified Technology; a
  solar operator is Utilities. Every renewable-energy answer would be spread
  across three "wrong" sectors.
* The idea that made a fixed list attractive - matching the user's sector
  against the provider's `sector` field as a hard check - collapses for the same
  reason. It would fire constantly on correct answers.
* "renewable energy" and "semiconductor equipment" carry far more signal for
  Agent 2's query generation than "Energy" and "Technology". Constraining the
  input would have made the RESEARCH worse.
* Several of Agent 1's 18 labelled cases depend on free-text values to create
  the conflicts they test, and its eval is that agent's only verification.

So the field was renamed `interests` -> `sectors_of_interest`, its description
rewritten ("Not hobbies: the question is what part of the market to research"),
and the prompts reworded. The pipeline's behaviour did not change at all: 422
tests passed before and after, and no eval case needed rewriting.

Worth noting WHY the rename mattered rather than just the description: the
profile is serialised into Agent 2's prompt with `model_dump_json()`, so the
FIELD NAME is something the model reads on every call.

### 23. Agent 5, and what it is not allowed to do

    Python   selects and orders the candidates
    for each selected company:
        LLM      writes the thesis and the exit conditions
        Python   discards any condition citing nothing checkable
        Python   supplies a fallback if none survived
    Python   assembles the Decision, carrying scores and verdicts through

Seven decisions were agreed before any code was written. Three are load-bearing:

**Python selects; the LLM writes.** Selection is filtering and ordering over
facts that already exist. A model asked "which of these five" produces an
ordering it cannot justify and will not reproduce - and by this stage the
ordering IS the product.

**Verdict tiers, screen_score orders within a tier.** The two earlier numbers do
not combine. Multiplying a verdict by a weight would have meant inventing a
constant, and a company's position would then rest on a number nobody could
defend. Tiering states the preference plainly: prefer what withstood criticism,
and among equals prefer the stronger business.

**An uncritiqued candidate is not selectable.** This is the trap built into
Agent 4's own schema: a candidate skipped by the critique cap reports `survives`
identically to one that was attacked and held up, because the verdict is
arithmetic over a risk list and an empty list is an empty list either way.
Selecting on the verdict alone would promote exactly what the cap left out.

Two more are expressed as ABSENCES, which is the only way they hold:

* **There is nowhere to put a position size.** Dividing `investment_amount`
  three ways is two lines of code, and it is the point where research becomes
  advice. A schema with no field for it holds that line better than a prompt
  asking the model not to.
* **There is no new score.** `screen_score` and `verdict` are carried through,
  not recomputed, so Agent 5 structurally cannot disagree with the stages that
  produced them.

### 24. Four defects, one of them years old in a two-week project

Every one was found by the eval. 422 unit tests were green throughout.

**A correct answer thrown away over a null.** The model wrote
`{"condition": "debt_to_equity rises above 3.0", "article_ids": null,
"metric": "debt_to_equity"}` - exactly what the prompt asks for. `article_ids`
is typed `list[str]`, the model spelled the absence as `null` rather than
omitting the field, and the entire brief was discarded.

This one could NOT be salvaged by `agents/structured.py`: it arrives as a
client-side parse error carrying no rejected payload, unlike a provider 400 with
`failed_generation`. Fourth distinct variant of "right data, wrong envelope",
and the first with nothing to recover. Fixed in the schema, and in Agent 4's
`Risk` which has the identical shape and had simply not hit it yet.

**An exit condition that was already true.** PowerBank was recommended with
"free_cash_flow_is_negative" as the thing to watch for. Its free cash flow was
already -28,367,000.

The condition was specific, correctly grounded, and completely useless: true the
moment it was written. It is the mirror image of the unfalsifiable conditions
the prompt already bans, and INVISIBLE to the check that looks for them, because
this one IS falsifiable. Now rejected deterministically - a condition may not
name a metric Agent 4's rules already fired on - and a hard failure in the eval.

**An operating margin of 168.** The most interesting one.

Agent 5 wrote "operating_margin falls below 150" into PowerBank's brief. That
reads as nonsense - a margin cannot exceed 1.0 - so the model looked wrong. It
was not. yfinance reported PowerBank's operating margin as **168.38**, and 150
is a sensible threshold for that number.

The figure had been corrupting results through two VERIFIED agents:

* Agent 3's ramp maps anything above 0.40 to a perfect 1.0, so garbage and
  excellence produced identical scores. PowerBank scored full marks on a metric
  that did not exist, and its `screen_score` of 0.373 was built on it. With the
  figure rejected, that score is **0.060**.
* Agent 4's fundamental rules only look for NEGATIVE margins, so they were
  silent.
* The eval had a `GROWTH_SANITY_CEILING` and nothing equivalent for margins.

Third instance of a lesson this log already records twice: **a metric that clips
cannot also serve as its own data-quality alarm.** The alarm has to sit upstream
of the clipping.

And it is the argument for the last stage existing at all. The number looked
fine in a field and absurd in a sentence, and it was caught by a human reading
prose - not by any check.

**The model would not read the articles.** With everything else working, all
nine exit conditions in the first clean run were metric thresholds. Not one
cited an article, though Agent 4 had retrieved them. The result was boilerplate:
the same three conditions for all three companies, which would read identically
for any company in any sector.

Metric thresholds are the cheap answer - "revenue_growth turns negative" can be
written without reading anything. The prompt now requires at least one
article-cited condition when articles exist, and the eval tracks the ratio.
It moved 0/9 to 1/8, which is honest progress and not a solved problem.

### 25. What "finished" means here, precisely

The pipeline is complete and every stage is verified against its own eval. The
things that are NOT true are worth stating plainly, because a summary that
omits them would be the kind of confident, unchecked claim this whole project
is built to avoid:

* **Agent 5's exclusion path has never run.** Every run so far produced three or
  fewer candidates and no disqualifications, so nothing has ever been excluded
  for real. It is covered by unit tests only.
* **One of two profiles keeps returning zero candidates.** Article variance
  means each run tests a different slice, so "0 hard failures three times" is
  weaker evidence than it sounds.
* **1 of 8 exit conditions cites an article.** The prompt change landed, barely.
* **Google and Amazon are being recommended for a renewable-energy profile**,
  because they buy batteries for data centres. That is Agent 3's exposure
  grading, and it is logged rather than fixed - it means re-opening an agent
  that is currently verified.

---

## Provider facts learned by probing, not from documentation

| Provider | Fact | Why it matters |
|---|---|---|
| Groq | `max_tokens` counts against the tokens-per-minute quota **even when unused** | One global value big enough for the largest call makes every small call expensive; budgets are per call |
| Groq | `gpt-oss-20b` is a **reasoning** model — it spends tokens before the visible answer | Budgets must be far larger than output length suggests; 512 truncated a six-item list |
| Groq | Limits are 8,000 tokens/min **and 200,000/day**, a rolling window | ~30 full pipeline runs per day on the free tier |
| TheNewsAPI | Cloudflare rejects urllib's default user-agent with `403 error 1010` | Must use `requests` plus an explicit UA |
| TheNewsAPI | Default search covers **all history** sorted by relevance | Returned 2023 articles for a current-events agent; `published_after` is mandatory |
| TheNewsAPI | Free tier: 100 req/day, **3 articles per request** | Design uses several narrow queries rather than one broad one |
| FMP | `/api/v3/*` endpoints are **dead** (403, legacy-only since Aug 2025) | Nearly every tutorial online shows v3; `/stable/*` works |
| FMP | Free tier is 250 req/day and covers only a **subset of US symbols** | Search returns foreign symbols happily, then data requests 402 |
| yfinance | Reports `debtToEquity` as a **percentage**; FMP as a **ratio** | Exactly 100× apart — unnormalised, every yfinance company screens as distressed |
| yfinance | Carries **two** currencies: `currency` is the SHARE price, `financialCurrency` the STATEMENTS | Amounts are statement figures; the quote currency labelled SK hynix's 162tn won as dollars |
| Both | Return a literal **`0.0`** where a margin does not apply | Banks have no cost of goods, pre-revenue biotechs no revenue; taken at face value it scores as "terrible" rather than "not applicable" |
| TheNewsAPI | The word **`OR` is not query syntax** and matches nothing | `"Pfizer" lawsuit OR investigation` returns 0 articles; `"Pfizer" lawsuit` returns 3 |
| TheNewsAPI | **`\|` ORs across the WHOLE query**, so a required phrase stops being required | `"Pfizer" lawsuit \| probe` returned articles about an Israeli army probe and Air India, with no Pfizer in them |
| TheNewsAPI | Three ANDed terms is usually **zero results** | `"Pfizer" Vaccine Demand Shifts` returns nothing; `"Pfizer" vaccine` returns plenty |
| Groq | The model may name its tool **`functions.<Schema>`**, which the client rejects outright | "Unknown tool type"; the error carries no `failed_generation`, so a correct answer is unrecoverable. `json_schema` output avoids the tool envelope |
| yfinance | Can report a **margin above 1.0** — PowerBank's operating margin came back as `168.38` | Arithmetically impossible (profit > revenue). The ranking CLIPS at 0.40, so it scored as perfect; caught only when Agent 5 wrote "falls below 150" into a brief |
| yfinance | Its **search is better than FMP's** | FMP returned a cryptocurrency for "SMIC" and Canada for "Nvidia" |
| Both | Fundamentals arrive in local currency — USD, HKD, INR, **GBp** (pence) | Only the four unitless ratios are cross-comparable |
| Windows | Console is cp1252 and cannot encode model output | Killed a completed eval run mid-report |

---

## Where things stand

**The pipeline is complete.** All five agents are built and verified against
their own evals, and every stage is connected end to end.

**433 unit tests**, ~4 seconds, no network and no API key required.

### What is NOT verified, stated plainly

A summary that omitted these would be the kind of confident, unchecked claim the
whole project is built to avoid.

- **Agent 5's exclusion path has never run.** Every run produced three or fewer
  candidates and no disqualifications, so nothing has been excluded for real.
  Unit tests only.
- **One of two eval profiles keeps returning zero candidates.** Article variance
  means each run tests a different slice, so a run of clean results is weaker
  evidence than the count suggests. Verifying a fix against its exact failing
  inputs has repeatedly proved stronger than another eval run.
- **Nobody can run this pipeline except through Python snippets.** There is
  still no CLI.

### Known weaknesses, measured and deliberately not fixed

Each needs re-opening an agent that is currently verified, which is why they
wait rather than being unknown.

- **Agent 3 grades data-centre operators as `direct` exposure to renewables.**
  The renewables profile is recommended Google and Amazon because they buy
  battery storage. A real fact and a very loose link: a beginner asking about
  renewable energy gets two mega-cap advertising and retail businesses. The
  error surfaces at the last stage, where a human notices; the cause is Agent
  3's exposure prompt.
- **Agent 5 barely reads the articles.** 1 of 8 exit conditions cites one; the
  rest are metric thresholds, which are the cheap answer and read the same for
  any company in any sector. The prompt change moved it from 0/9, which is
  progress and not a solution.
- **Agent 2 records almost no dissenting evidence.** Structural, not a prompt
  problem - most themes cite one article, and one article cannot disagree with
  itself. Worked around by giving Agent 4 its own adversarial retrieval.
- **Agent 4's source filter is seven domains** from one afternoon of searches.
  An unlisted low-quality outlet passes and nothing notices.
- **Ranking saturates at the very top**, and **financial companies cap at 0.50**.
  Both measured, both accepted: they distort absolute scores without changing
  any ordering that gets consumed.
- **Agent 1's eval scores 100%**, so it catches regressions but cannot show
  improvement.
- **The exclusion check matches naive substrings.** "No crypto exposure" would
  register as a violation. Not yet observed.

### Deferred, not blocking

- **No CLI.** The thing that would make the project demonstrable.
- **`InMemorySaver`** loses all state on restart, including a user mid
  clarification. Needs `SqliteSaver` before any real use.

### Next

1. **The hardening pass** - CLI, `SqliteSaver`, harder Agent 1 eval cases. None
   of it needs quota.
2. **Then work through the known weaknesses above**, in the order they would
   change an answer a reader sees. The Agent 3 exposure grade is first: it is
   the one currently putting a wrong-looking company in front of a person.

---

## Session 5 — 2026-08-23

### Starting point

All five agents built and verified, 433 tests, everything committed at
`c930892`. The pipeline worked and could not be shown to anyone: it ran only
from Python snippets and eval runners. The hardening pass began here, with the
CLI as its most valuable item.

### 26. The CLI, and the interrupt that turned out to be the easy part

The handoff called the clarification interrupt "the awkward part". It was not.
`tests/test_workflow.py` already contained the exact loop the CLI needed —
invoke, check for `__interrupt__`, resume with `Command(resume=...)` — because
proving the clarification loop terminates required driving it the same way a
user would. The test written to bound a loop had incidentally specified the
front end.

The one real decision was `stream` over `invoke`. `invoke` returns only at the
end, and the end is several minutes and roughly a dozen model calls away; a
terminal that prints nothing for that long is indistinguishable from a hang.
`stream(stream_mode="updates")` yields `{node: update}` per completed node, so
each stage can report what it produced as it lands:

```
[3/5] Finding companies genuinely exposed to those themes ...
        3 candidate(s) from 11 companies examined
          dropped: 1 failed_screen, 1 no_ticker_found
```

Those counts are not decoration. They are the same numbers the evals score —
`companies_examined`, `drop_summary`, `articles_retrieved` — shown to whoever
is watching. A run that examines eleven companies and produces zero candidates
looks identical to a broken one until the drop reasons are on screen.

One consequence: `stream` yields updates, never the accumulated state, so the
final state has to be read back with `get_state(config).values`. That is what
found the next bug.

### 27. The types nobody registered, and why 433 tests could not see it

`get_state()` returned `decision` as a plain `dict`. The first property access
died:

```
AttributeError: 'dict' object has no attribute 'recommended_nothing'
```

`workflow.py` passes a `JsonPlusSerializer` an explicit allow-list of Pydantic
types. Agents 1, 2 and 3's types were all listed, with comments explaining that
an unlisted type could not be reconstructed. **Agents 4 and 5 were added to the
graph without being added to that list.** They shipped that way in `c930892`.

What makes this worth writing down is why nothing caught it:

- **It is not an error.** An unregistered model round-trips as a dict with all
  the right keys. It fails later, somewhere else, on the first property access —
  and `verdict`, `was_critiqued`, `recommended_nothing` and `exclusion_summary`
  are all properties.
- **Nothing read state back.** The eval runners construct the objects, hold
  them, and score the objects they are holding. They never take one out of the
  checkpointer. The CLI was the first caller to do so, which is the only reason
  it surfaced at all.
- **The one path that would have hit it does not exist.** The single interrupt
  sits in Agent 1, before Agents 4 and 5 ever run, so no resume had ever had to
  reconstruct their types.

The fix was four lines of imports. The interesting part was the comment in
`workflow.py` claiming this could not be caught generically — which was wrong,
and rewriting it produced the actual fix:

```python
def test_every_type_that_reaches_state_is_registered_with_the_checkpointer():
```

It walks `InvestmentState`'s annotations, recurses through `list[...]`, `X |
None` and nested model fields, and asserts every reachable `BaseModel` appears
in `CHECKPOINTED_TYPES` (extracted from an inline literal so a test can import
it). A second test checks the other direction, so a renamed model does not leave
a dead entry behind. Removing `Decision` from the list makes it fail with the
type named — checked, because a registry test that cannot fail is worse than no
test, being evidence of something it never verified.

This is the project's lesson arriving from a new direction. The usual form is
"only the evals show whether what it says is right." This one no eval could have
caught either: it is not a judgement about model output, it is a serialization
contract that only breaks when somebody reads state back. **Adding a stage means
adding its types**, and that is now a red test rather than a footnote.

### 28. Where the output had to be honest rather than pretty

Three choices in the printing, all the same argument:

- **Recommending nothing gets the loudest banner on the page** and prints
  `no_recommendation_reason` under a `WHY` heading. Everywhere upstream an empty
  result is a legitimate outcome; this is the one place a person sees it, and a
  blank screen reads as a crash. It also exits **0** — a non-zero code would tell
  every wrapping script the run had failed.
- **Exit conditions print what grounds them**, resolved to a headline, publisher,
  date and link. The citation was carried through three stages precisely so it
  could be followed, and a bare uuid is not a source. An id that resolves in
  neither `RiskFindings.articles` nor `ResearchFindings.articles` prints
  "source not retained" rather than nothing, because silence there looks
  identical to a citation that worked.
- **Every excluded candidate is named with its reason.** A company that vanished
  between the ranking and the output would be the one failure a reader could
  never detect.

### 29. Two places the CLI refused to duplicate a rule

The prompts validate shape only — is it a number, is it one of the allowed
words. Ranges stay in `UserInput`, and `ask_profile()` catches the
`ValidationError` and re-asks the offending field by name. The alternative was
restating `gt=0, le=120` in the CLI, giving the bound two homes and one of them
no test.

Likewise `EXPERIENCE` and `RISK` are read from `UserInput`'s own `Literal` types
with `get_args`, not retyped. Adding a risk level in the model cannot leave the
CLI offering the old three, and a test asserts the question list and the model's
fields are the same set.

### Where it stands

- **472 tests** (was 433), ~3s, no network.
- `python -m cli`, `--profile`, `--save-profile`; three example profiles, one of
  them deliberately contradictory so the interrupt can be demonstrated on
  demand.
- The serializer defect from `c930892` is fixed and has a regression test.

### Next

1. **`SqliteSaver`** (2b). Now more clearly worth doing: `--thread-id` exists in
   the CLI and is inert until the checkpointer is durable.
2. **Agent 3's exposure grade** — still the one weakness putting a
   wrong-looking company in front of a person.
3. Harder Agent 1 eval cases.

---

## Session 6 — 2026-08-23

### Starting point

The CLI shipped and `--thread-id` existed as an inert flag. `InMemorySaver` lost
everything on process exit, including a user stopped mid-clarification — which
is the one moment this pipeline is most likely to be stopped, because it is the
only moment it asks a person for something.

### 30. What the checkpointer's allow-list actually does

The session began by mutation-testing the fix from Session 5: remove
`serde=serializer` from the store and confirm the tests fail. **They passed.**

That was worth chasing rather than shrugging at, because it meant either the
guard was worthless or the Session 5 diagnosis was wrong. Testing the serializer
directly settled it:

| serializer | unregistered type comes back as |
|---|---|
| `JsonPlusSerializer()` — no allow-list | the real type, **plus a deprecation warning** |
| `JsonPlusSerializer(allowed_msgpack_modules=[...])` | **a plain dict**, blocked |

So passing `allowed_msgpack_modules` **opts into a strict allow-list**. That is
what made Session 5's bug real, and re-running that exact scenario reproduced it
exactly: with Agents 4 and 5 absent from the list, `decision` and `risk_findings`
both come back as `dict`. The Session 5 account was right.

But *omitting the serializer entirely* is a different failure, and a quieter
one. It falls back to LangGraph's permissive default, which reconstructs
everything and only warns:

> Deserializing unregistered type ... This will be blocked in a future version.

So dropping `serde=` looks completely fine today, silently discards the
guarantee `CHECKPOINTED_TYPES` exists to provide, and breaks everywhere at once
when that future version lands. **A round-trip test cannot catch it while the
default is still permissive.** The test asserts the serializer's IDENTITY
instead, which does fail on the mutation.

The general lesson: a test that cannot fail is not evidence, and the only way to
find out is to break the thing on purpose. Two mutation tests in two sessions;
one confirmed the guard, one exposed that it was pointed at nothing.

### 31. Three ways a run can be unfinished, not one

The obvious model was "paused at a clarification, or done". Probing found a
third, and it turned out to be the valuable one:

```
paused     interrupted to ask a question       -> resume with Command(resume=answer)
stopped    process died partway through a stage -> resume with None
finished   ran to the end                       -> nothing to resume
```

`stopped` is what happens on Ctrl-C during the three-minute research call, and
`invoke(None, config)` picks up at the unfinished node **without repeating the
ones that completed**. A test proves Agent 1 is not called a second time. On a
free-tier daily ceiling that is the difference between losing a minute and
losing the day's budget, and it would have been missed entirely by modelling
this as a two-state problem.

`get_state` on an unknown thread returns a snapshot with `created_at is None`
rather than raising, so that is the existence test — and `run()` returns `None`
for it, so a mistyped id can be reported instead of quietly starting a fresh run
under the typo. That is also why resuming is `--resume` rather than
`--thread-id` guessing.

### 32. A durable checkpoint nobody can find is not durable

`--list` exists because the alternative is asking people to write down a uuid.
It prints the status and **what each run was researching**, because a column of
thread ids is not something a person can recognise their own work in.

### 33. Two places this refused to be convenient

**The database is not in `.cache/`.** That directory is documented in
`.gitignore` as "re-fetchable; not source" and is safe to delete to force fresh
API data. A paused clarification is neither re-fetchable nor safe to delete.
Sooner or later somebody clears the cache; they should not lose a live session
by doing it. It lives in `.state/`, with the distinction written into the
ignore file.

**Importing a module still creates nothing.** `build_graph(checkpointer)` takes
the checkpointer as an argument rather than the module owning one, so
`import workflow` and `import checkpoints` touch no filesystem. A module-level
`SqliteSaver` would create a database because something imported it — including
every test run. Checked in a subprocess, and skipped when a real run has already
created the file, since then the question cannot be answered by looking.

### 34. A performance regression that was not one

The suite appeared to go from 3s to 13s. Before optimising anything, the
committed baseline was measured in a throwaway `git worktree`:

| | cold | warm |
|---|---|---|
| `1dd95e0` (before this session) | 11.1s | 7.0–8.1s |
| this session | 13.4s | 6.3–7.1s |

**There was no regression.** The "3.07s" figure quoted in Session 5's README was
a single warm outlier, and "13s" was a single cold one. Roughly six seconds of
work went into chasing a number that was noise — cheap, and cheaper than the
alternative of "optimising" a suite that was never slow. The README now says "a
few seconds" rather than a precise figure it cannot honestly promise.

The one real finding along the way: an autouse fixture requesting `tmp_path`
applies to every test in the suite, so it creates a temp directory per test.
Changed to one session-scoped directory with a file per test. It saved little
here, but it is the kind of thing that scales badly and silently.

### Where it stands

- **501 tests**, a few seconds, no network.
- `python -m cli --list` / `--resume <id>`; `--db` for pointing at another
  database, which is also what keeps the tests off the real one.
- An autouse fixture redirects `checkpoints.DB_PATH` for every test, so a test
  that forgets `--db` cannot write into a user's saved runs.
- Verified across three separate processes: start, kill at the prompt, list,
  resume, finish.

### Next

1. **Run the CLI against the live pipeline.** Still never done end to end.
2. **Agent 3's exposure grade** — the one weakness putting a wrong-looking
   company in front of a person.
3. Harder Agent 1 eval cases.

