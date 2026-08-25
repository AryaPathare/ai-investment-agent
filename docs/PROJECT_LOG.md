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
`937e16c`. The pipeline worked and could not be shown to anyone: it ran only
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
graph without being added to that list.** They shipped that way in `937e16c`.

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
- The serializer defect from `937e16c` is fixed and has a regression test.

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
| `5d2b322` (before this session) | 11.1s | 7.0–8.1s |
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

---

## Session 7 — 2026-08-23

### Starting point

The last item of the hardening pass, and the only one needing no quota. Agent
1's eval scored 18/18, which the handoff described as "catches regressions but
cannot show improvement".

### 35. Why it scored 18/18

Reading the set before adding to it was the whole job. **Every conflict case
named the same word twice:**

```
sectors_of_interest = ["technology"]
restrictions        = ["Do not invest in technology companies"]
```

`renewable energy` vs "renewable energy or energy companies". `pharmaceuticals`
vs "pharmaceutical companies". And every valid case was lexically disjoint —
`technology` against tobacco and gambling.

The prompt gives that exact pattern as its worked example. So a model could
score full marks by checking whether a restriction repeats a sector word, and
never judge anything. Worse, 13 of the 18 expected `valid`, so answering
"valid" every time — reading nothing at all — scored **72%**.

That is not a hard set with a high score. It is an easy set, and the number was
measuring the wrong thing.

### 36. Building an instrument that can tell the difference

Twelve cases that break the correlation between "shares a word" and "is a
conflict", from three directions:

- **Conflicts with no shared vocabulary.** `coal mining` against "nothing that
  damages the environment". `defence primes` against "no companies that profit
  from war". `SPACs and pre-revenue biotech` against low risk tolerance — the
  easy version says "extremely speculative" outright; this one requires knowing
  what a SPAC is.
- **A non-conflict that DOES repeat the sector word.** `technology` against "no
  financial technology companies". Fintech is one corner of technology; the
  rest remains. This is the exact inverse of the pattern the prompt teaches,
  and the sharpest single case in the set.
- **Non-conflicts where the restriction is merely adjacent.** `energy` against
  "no fossil fuel companies"; `semiconductors` against "no companies
  headquartered in China". These narrow the search without emptying it, and
  narrow is not contradictory. The trap for a model that reasons semantically
  rather than lexically.

Plus one that is neither: **risk tolerance is a ceiling, not a quota.** High
tolerance with treasury bonds is coherent — being willing to take risk does not
oblige anyone to take it. Its mirror, low tolerance with speculative sectors,
IS a conflict, and telling those two apart is the judgment being measured.

The hard set is **balanced 6/6** between the two verdicts, so answering
everything the same way scores exactly 50% rather than 72%. A test enforces the
balance, because it is the property that makes the number mean anything.

### 37. Validating the instrument without spending any quota

The obvious risk in writing twelve cases from scratch is that they are not
actually harder, and there was no budget to find out by running the model.

So the runner was pointed at a **deliberately naive stand-in**: a fake that
flags a conflict only when a restriction repeats a sector word — precisely the
strategy the old set could not distinguish from judgment.

| | string-matching fake |
|---|---|
| original false-positive cases | **12/12 (100%)** |
| hard set | **4/12 (33%)** |
| clarification cases | **0/6** |

That is the separation the set exists to produce, measured for free. It also
corrected two things mid-flight:

- The first draft's comment claimed the false-positive half had "high lexical
  overlap". The fake passed all five, which proved otherwise: they are
  *semantic* near-misses with no shared words. The comment was wrong and was
  fixed rather than left to mislead whoever adds the next case.
- That gap is what prompted the fintech case, the one genuine lexical-overlap
  non-conflict. Adding it dropped the fake from 5/12 to 4/12 and from 100% to
  94% on false-positives, which is the case doing exactly its job.

### 38. Scoring the verdict was not enough

`clarification_resolves_conflict` passed if the model returned `valid`. It
would have passed just as happily if the model returned `valid` while leaving
the contradictory restriction in place — which is not a cosmetic failure. It is
a contradictory profile reaching Agent 2, the one thing Agent 1 exists to
prevent.

Cases can now assert what the clarification actually DID:

```python
expected_status="valid",
expect_restrictions_exclude=("technology",),
expect_sectors_include=("technology", "sports"),
```

Split by field on purpose: dropping the interest and dropping the restriction
are opposite, equally legitimate resolutions of the same conflict, and a check
over the combined text could not tell them apart. The fake fails all six
clarification cases on exactly this.

Matching uses **word boundaries, not substrings** — "technology" is a substring
of "biotechnology", and a naive check would mark a correct answer wrong. The
project already shipped one naive-substring bug in the exclusion check; putting
the same flaw inside the instrument that measures it would generate false
failures and send someone off fixing a prompt that was fine.

### 39. Testing the eval

An eval is an instrument and an instrument can be wrong, so the case set now
has its own tests: unique names, every case tagged and explained, expectations
only on cases that send a clarification, no expectation naming a term the input
never contained, regressions never relabelled `hard`, and the 6/6 balance.

One of those tests caught a wrong number in its own docstring — the claim that
the original set was "12 valid to 6, worth 67%". Computing it gave 13 to 5 and
72%. A number written from memory into a comment, in a session about an
instrument that measures things.

### Where it stands

- **578 tests**, no network.
- 30 eval cases: the original 18, plus 12 tagged `hard`.
- `--tag hard` runs 12 calls instead of 30, which is the cheap way to iterate on
  a prompt change.

### NOT yet verified

**The hard cases have never been run against the real model.** They are
validated against a fake, which proves they separate string matching from
judgment — it does not prove the labels are right. The first real run is as
much a test of the labels as of the agent:

- ~8-10 of 12 would be a good result and a usable baseline.
- **12/12 would mean they are still too easy**, not that the agent is perfect.
- Below ~5, suspect the labels before the prompt, and check the `why` on each
  failure — it is written to make that argument checkable.

### Next

1. **Run the CLI against the live pipeline** — still never done end to end.
2. **`--tag hard`** to get the first real baseline (12 calls).
3. **Agent 3's exposure grade** — the one weakness putting a wrong-looking
   company in front of a person.

---

## Session 8 — 2026-08-23

### 40. The author identity was rewritten, so every SHA changed

Before publishing anything, the repository was audited: `.env` was never
committed, no key-shaped strings appear anywhere in history, and `.cache/` and
`evals/results/` were never tracked. Clean.

The one thing that did need changing was the commit identity. All 38 commits
were authored by `Nilesh <nileshp@fucient.com>`; publishing would have put a
work email into public commit metadata permanently. Two `filter-branch` passes
rewrote author AND committer to `Arya Pathare <patharearya@gmail.com>`, and
`refs/original`, the reflog and unreachable objects were purged so the old
identity survives nowhere.

Verified before purging the backup: identical tree hashes, identical commit
messages, 578 tests still passing. Only metadata moved.

**Consequence worth recording: every commit SHA before this point changed.**
Any SHA written down elsewhere - in notes, in an issue, in an earlier draft of
this log - no longer resolves. The two references inside this file were updated
in place:

| old | new | commit |
|---|---|---|
| `c930892` | `937e16c` | Complete the pipeline: Agents 4 and 5 |
| `1dd95e0` | `5d2b322` | Add the CLI, and fix the checkpointer types |

The lesson is small but general: **a commit hash is a reference to something
mutable.** Prose that cites one is making a promise the repository can break,
and rewriting history breaks every such promise at once. Citing the commit
SUBJECT alongside the hash, as the table above does, is what made these two
recoverable at all.

### 41. Auditing the source filter instead of guessing at it

Agent 4's `LOW_QUALITY_SOURCES` was seven domains "from one afternoon of
searches", carried as a known weakness for three sessions. The obvious fix was
to spend another afternoon and add more names.

There was a better option sitting on disk: **224 cached news responses** from
every run this project has ever made. Real retrieved articles, no API calls.

The first pass counted 433 articles and got the ranking wrong. The cache stores
one file per query and the same article comes back from many queries, so it was
counting RETRIEVALS. `globalrenewablenews.com` looked like the third-biggest
source at 31; deduplicated by uuid it is 7. The corrected corpus is **272
distinct articles from 130 sources**, and every number below is from that.

**What the audit found:**

- The seven-name list removed **2.6%** of the corpus. Nearly inert.
- **86 of 130 sources contributed exactly one article.** This is the finding
  that matters, and it is not "the list is too short". A list of names cannot
  cover a distribution where two thirds of sources appear once. Extending it
  helps with recurring offenders and cannot make the filter complete.
- Three different problems were being conflated under "low quality":

  | | example | right instrument |
  |---|---|---|
  | not publishers | `airedale.futurecdn.net` (a CDN hostname), `api.foxsports.com` | a structural rule |
  | off-topic | `dealigg.com` - *"Best Deal: 6-Pack Lithium Battery"* against a battery-storage query | nothing here; a relevance failure |
  | editorial tail | `insidermonkey.com`, `financefeeds.com` | naming - what the list is for |

- **6% of the corpus is press releases**, concentrated in `manilatimes.net`:
  nine of its twenty-three articles, and it is the second-largest source
  overall. *"CervoMed Reports Second Quarter Financial Results."* A press
  release is the company's own framing, which makes it close to worthless to a
  RISK critic specifically - the one agent whose job is the bear case.

**What was changed:** sixteen names, every one of them observed in the corpus
rather than imagined. 2.6% to 15.1%. The header comment records the honest
limits alongside the improvement, because 15.1% reads like progress and the
long tail is still wide open.

**What was deliberately not changed.** The press-release problem needs a filter
on the SHAPE of the article, not on who carried it: this content arrives
through ordinary newspapers that also do real reporting, so blocking the
newspaper is wrong. And no source list fixes relevance.

### 42. Two things the audit turned up on the way

**The filter had no tests at all** - not one - despite deciding which evidence a
published risk claim is allowed to rest on. It has ten now. The list itself is
an editorial judgement and cannot be asserted on, but everything around it can:
that entries are written in a form the matcher can actually match (matching
lowercases the source, so an entry with a capital letter would never fire and
nothing would reveal it), that dropping is reported rather than silent, and
that matching is exact so `news.ycombinator.com` does not take `medcitynews.com`
with it. Verified by breaking an entry's casing on purpose and watching two
tests fail.

**The caller discards what the filter withheld.** `drop_low_quality` returns the
dropped sources, and its docstring argues the case: "a filter that silently
removes evidence is its own kind of unreliable narrator." `risk_agent.py` then
assigns them to `_dropped` and throws them away. Nothing in `RiskFindings`
records that anything was withheld. Left as-is - it needs a field threaded
through the assembly, which is more than this change - but it is exactly the
failure the docstring warns about, sitting one line below the warning.

**And the cache cannot answer the question it was used to ask.** Cached
responses store the provider's reply and not the query that produced it, so
these articles cannot be attributed to Agent 2's theme search versus Agent 4's
bear-case search. The claim "press releases are reaching the risk critic" is
therefore *unproven* - it is in the corpus, and which agent retrieved it is not
recoverable. Recording the query alongside the response is a few lines and
would make every future audit of this kind possible for free.

### 43. Making the filter answerable, in both directions

Session 8's audit ended with two things it could not do, both for the same
underlying reason: the system removed and retrieved evidence without recording
enough about either to be questioned afterwards. Both are now fixed, and
neither is a behaviour change - no different article reaches any agent. They
change what can be ASKED.

**The cache did not record its own questions.** Cached responses stored the
provider's reply and nothing else, so 272 cached articles could be measured for
press-release content and could not be attributed to Agent 2 versus Agent 4 -
the only question that mattered, since a press release is ordinary input for
theme research and close to worthless to a risk critic. The finding had to be
written down as unproven.

`_write_cache` now takes a provenance block: the query, the asking agent, the
date window, and when it was fetched. Namespaced under `_provenance` so it can
never collide with a provider field, copied rather than mutated onto the
payload so caching stays free of side effects, and deliberately without the API
token - the cache key already excludes it, and writing it into the value
instead would put a live credential in the one file designed to be kept and
inspected.

The two call sites tag themselves in one word each, `asked_by="research"` and
`asked_by="risk_critic"`, which is the whole point: a query string can be
guessed at, an explicit label cannot.

**Timing matters here and nearly went wrong.** The 224 existing entries keep no
provenance and stay readable, which is accurate - they genuinely have none. But
that means the payoff is entirely in FUTURE runs, and the next live run is the
most valuable corpus this project will generate. Doing this after that run
would have produced one more unattributable cache and wasted the one chance.

**The filter discarded what it withheld.** `drop_low_quality` returns the
dropped sources and its docstring argues the case - "a filter that silently
removes evidence is its own kind of unreliable narrator" - and `risk_agent`
assigned them to `_dropped` and threw them away, one line below the warning.
Three sessions of that.

`CandidateCritique.sources_withheld` now carries them, and the CLI prints them:

```
  WAAREE: survives (1 risk(s) from 6 article(s))
    withheld 3 article(s) from: revolver.news, zerohedge.com
```

It matters the same way `articles_reviewed` does. "No risks found" means
something different when twelve articles were reviewed than when eight were
reviewed and four withheld - and different again when all four came from one
publisher, which is the shape of a filter that is too aggressive rather than a
company that is sound.

Recording it in state and not printing it would have moved the silence rather
than ended it, so the chain is tested end to end: filter, to critique, to
screen. Verified by putting the discard back and watching a test fail.

### 44. The pattern in both of these

Neither was a bug. Both were places where the system did something defensible
and kept no record of having done it, which is indistinguishable from not
having done it at all - and in one case had already cost a real finding, which
had to be published as unproven.

The tell was the same both times: **a function returned information nobody
consumed.** `drop_low_quality` returned dropped sources into `_dropped`.
`_write_cache` received a payload whose query it never saw. Neither shows up as
a failing test, a wrong number, or a bad output. They show up much later, as a
question that cannot be answered.

### 45. Filtering the company's own voice out of the bear case

The audit's largest finding was that 6% of the retrieved corpus is press
releases, concentrated in a single source. A press release is the company
describing itself, which makes it the most confirmatory input available to the
one agent whose entire job is to argue the other side.

It could not be fixed by blocking the publisher. This content arrives through
ordinary newspapers that also do real reporting - blocking `manilatimes.net`
would throw away its journalism to remove its syndicated wire copy. The article
had to be judged, not the source.

**The dangerous version of this rule is the obvious one.** "Announces" is the
word that marks a press release, and it is also the word in:

    Apple announces changes for apps in the European Union
    Canadian Solar Announces Resolution of Maxeon U.S. Patent Litigation
    SK Hynix Announces $38.5 Billion DRAM and NAND Manufacturing Expansion
    Regulator announces probe into ...

All real, all from the corpus, and all things the risk critic needs. A rule
keyed on that word would blind the agent to precisely what it exists to find.
**Letting a press release through costs a mediocre input; removing real bad
news defeats the agent.** The asymmetry decides every judgement call here: when
the signals are unclear, keep the article.

**Two independent signals, both narrow:**

1. *The wire dateline.* An article carrying "(GLOBE NEWSWIRE)" or "/PRNewswire/"
   was published BY the company through a paid service. Close to definitional,
   and it reaches releases no title rule could - "Purple Appoints Jimmy Serrano
   as Growth Director", "Pontiac Bancorp has agreed to acquire Ottawa Bancorp".
2. *Issuer document types in the title.* "Announces ... Financial Results",
   "Provides Corporate Update", "Declares Dividend", "To Present At ...
   Conference". Each names a KIND OF DOCUMENT rather than a verb, which is what
   keeps "Regulator announces probe" out. It exists as a second signal because
   aggregators strip the dateline and keep the headline.

Measured against the 272 cached articles: **15 matched, 5.5%, and every one is
an issuer document.** An earlier looser draft matched 6% and took the Apple and
Canadian Solar stories with it. The missing half a percent is deliberate.

Deliberately NOT filtered: **earnings call transcripts.** The company's own
event, but the analyst Q&A is the one part of an earnings cycle where hard
questions get asked out loud.

**Applied by the risk critic and not by Agent 2.** The same article is ordinary
evidence for theme research - a company announcing a 1.2GW order genuinely is a
signal the theme is real. The filter is not "this article is bad"; it is "this
article cannot serve THIS purpose". A test asserts research does not import it.

`CandidateCritique.press_releases_withheld` carries the count and the CLI prints
it, for the reason established one entry earlier: eight articles reviewed with
four withheld as announcements is a finding about the SEARCH, not evidence that
the company is sound.

Verified by loosening the rule back to a bare "announces" and watching seven
tests fail - the seven that name real headlines it would have destroyed.

### 46. Measuring the off-topic problem instead of describing it

Off-topic retrieval had been carried for two entries as "a real failure, no
instrument identified" - `dealigg.com` returning *"Best Deal: 6-Pack Lithium
Battery"* for a battery-storage query. Asked what could actually be done about
it, the honest first step was to stop characterising it and measure it.

**Two candidate instruments, both checked against real data, both dead:**

*Provider categories.* TheNewsAPI tags articles `business`, `tech`, `general`
and so on, and the "Best Deal" articles carry none - which looks like a clean
signal until you read the other twenty-four articles that also carry none:
"Francisco Partners to acquire Weave for $650m", "US lawmaker wants gov't to
enforce regulation to ensure chipmakers...", "Samsung's fab roadmaps examined".
Category absence is not a junk signal, it is a metadata gap.

*Query-term matching.* An article that matches none of the query terms is
off-topic - except "Best Deal: 6-Pack Lithium **Battery**" legitimately matches
a query about battery storage. The junk is topically adjacent, which is exactly
why it was retrieved.

**Then the question that should have been asked first: does it reach the
output at all?** The saved research evals answer it:

| retrieved | cited | on-topic themes |
|---|---|---|
| 11 | 7 | 4 of 4 |
| 18 | 8 | 5 of 5 |
| 17 | 5 | 5 of 5 |
| 12 | 5 | 4 of 4 |
| 10 | 7 | 4 of **5** |

The model cites 40-70% of what is retrieved, and in **eight of nine recorded
cases every theme it produced was on topic**. One off-topic theme, in one run,
ever. The junk is retrieved and then discarded by the model.

So the cost is not corrupted output. It is wasted retrieval budget - 100
requests a day at three articles each - and wasted prompt tokens on a tight
daily ceiling. Both real, both efficiency rather than correctness.

**Accepted, on the same terms as the two scoring limits: measured, documented,
judged not worth the cost.** It was mischaracterised in entries 41 and 43 as a
failure sitting in the output; it is not, and the correction matters because
those entries would have justified spending on it.

One thing does change the picture cheaply. The provenance block added in entry
43 records which query produced each article, so the next live run will show
whether specific queries are responsible rather than junk arriving diffusely.
If a fix is ever worth building, that is what would make it well-targeted - and
it costs nothing extra, because the run has to happen anyway.

### 47. The shape of this whole session

Four items were carried into today as known weaknesses. Two turned out to be
smaller than their description, and one turned out to be a different problem
than its description:

- *"The source filter is seven domains"* - the count was not the problem. 86 of
  130 sources appear exactly once, so no list of names can ever cover it.
- *"Press releases are 6% of the corpus"* - accurate, and the obvious fix would
  have destroyed the litigation and regulatory news the risk critic exists to
  find. The shipped rule catches 5.5% and the missing half a percent is the
  point.
- *"Off-topic retrieval is a real failure"* - the model already discards it.

In each case the description had been written once, carried forward across
sessions, and cited as justification without being re-examined. **A weakness
recorded in prose is a claim, and it decays like any other claim.** The measured
version was different every time, and twice it argued for doing less work
rather than more.

### 48. Reviewing 4,754 lines written in one day

Everything above shipped in a single session, authored and tested by the same
process, with no independent pass. A review of the eight-commit range found
seven defects. Two were serious, and both were in code I had verified and
written confident prose about.

**The press-release filter removed the evidence it was built to protect.**

Entry 45 argued at length that the dangerous version of this rule is the
obvious one, listed the headlines it must never touch, and claimed the shipped
version had zero false positives. It did not:

    First Solar Reports Disappointing Second-Quarter Financial Results, Shares Plunge
    Third-quarter results reveal accounting irregularities at Acme
    Acme Q3 FY2025 results miss badly, shares tumble
    Board declares special dividend amid activist pressure

All four were dropped. Reporting on a bad quarter, accounting irregularities and
activist pressure are the most useful things the risk critic could possibly
retrieve, and the filter ate them while its docstring explained why that must
never happen.

**Why neither check caught it.** The corpus contained no headline of that shape,
so the 15/272 measurement was clean. And the seven tests written alongside the
rule used invented headlines that happened to avoid the "quarter ... results"
construction, because they were written by the same person, at the same time,
from the same mental model of what the rule was for. **A test written to
demonstrate a rule tests the rule's intent, not its behaviour.**

The fix is a veto: any title containing evaluative or market-reaction language
is kept, whatever else matches. An issuer does not call its own results
disappointing, does not mention its shares plunging, and does not report that
they revealed accounting irregularities. The veto runs FIRST and beats a genuine
wire dateline, because when the signals disagree the article is ambiguous and
the asymmetry says keep it.

**The wire marker had the same shape of error.** Matching the bare name dropped
"Judge rules against Acme in patent suit" because its body said "Acme said in a
PR Newswire release last month" - a journalist attributing a claim. Every real
dateline in the corpus has a structure the mention does not:

    DUBLIN, Ireland, Aug. 12, 2026 (GLOBE NEWSWIRE) -- Fusion Fuel today ...
    WARNERTOWN, Australia, Aug. 17, 2026 /PRNewswire/ -- As Southern ...

Wire wrapped in parentheses or slashes, followed by a double dash. Matching the
shape rather than the name fixes it and still catches all 15.

**Reusing `--thread-id` silently accepted a contradictory profile.**

LangGraph merges new input into an existing thread, so a second run under the
same id inherits the first run's `clarification_responses`. Reproduced across
four runs: run 1 asked the clarification, and runs 2, 3 and 4 returned "profile
valid" **without asking at all** - Agent 1 was handed a stale answer and
believed the conflict resolved. A contradictory profile through the one gate
built to stop it.

Worth recording that the review described this differently, predicting escalating
attempt counters. Running it showed something worse. **Reproducing a reported
defect is not a formality**; the mechanism was right and the symptom was not,
and the fix follows the symptom.

Starting a new run on an existing thread is now refused, pointing at `--resume`.
That is the design decision from entry 31 finally enforced rather than assumed.

### 49. The other five, and what they have in common

- **Ctrl-C during `graph.stream` printed a traceback.** `_read` converts Ctrl-C
  at a prompt into `Cancelled`, but the three-minute research call never passes
  through `_read` - the window where interruption is most likely was the one not
  covered, while the docstring and README both promised it was safe.
- **`_grounds` wrapped URLs.** `textwrap` broke long links mid-token, so the one
  thing in the output a reader is meant to go and check could not be copied.
- **`--repeat` merged results from run 1 only**, so a later run's failure printed
  a FAIL header with no reason under it.
- **Cache provenance recorded only the first asker.** Both agents share a cache
  key deliberately - splitting it would double requests against a 100/day
  ceiling - so a shared article was attributed to whoever asked first. That is
  precisely the question the block was added to answer, and entry 43 claimed it
  answered it.

Four of the seven are the same failure: **a promise made in prose that the code
did not keep.** The docstring said stopping was survivable; Ctrl-C tracebacked.
The comment said the grounds block gives the reader something to check; the URL
was unusable. Entry 43 said provenance makes attribution possible; it recorded
one agent. Entry 45 said the filter had no false positives; it had a class of
them.

Every one of those sentences was written in the same session as the code, by
someone who had just finished convincing themselves. That is the condition under
which prose and behaviour drift apart, and no amount of care inside the session
substitutes for a pass from outside it.

### 50. A bug introduced by the fix for a bug

Asked whether the review fixes had left anything behind, two checks were worth
running. One found a defect created by the review fixes themselves.

`_record_asker` was added so a cache HIT records the second agent that asked,
since both agents share a key deliberately. It works by rewriting the entry -
and `_read_cache` measures staleness from the file's **mtime**. So recording
the second asker reset the TTL clock to zero.

The consequence: a query BOTH agents ask is refreshed on every run and can
never expire. Stale news, served indefinitely, to the one agent whose job is
finding out what has recently gone wrong. Proved by ageing an entry to ten
hours, calling `_record_asker`, and watching it come back zero.

Fixed by restoring the original mtime after the write. Two tests hold it,
including one that ages an entry past the TTL and asserts it stays expired.

The pattern is worth naming: **the fix was to an observability feature, and it
broke a correctness property in a different module.** Provenance is about being
able to ask questions later; the TTL is about not lying to the reader now. They
met at the filesystem, through a field neither piece of code mentions.

### 51. The other check: a trade-off, not a defect

The journalism veto from entry 48 is broad, so an issuer release written in
upbeat language slips through - "Beats Guidance", "Revenue Jumps 40%". Checked
rather than assumed, and accepted:

- On the real corpus it costs **nothing**: all 15 press releases are still
  caught. The leaks are constructed headlines, not observed ones.
- The leaks are POSITIVE news, which a bear-case agent has little use for
  anyway.
- Narrowing the veto to reclaim them would risk re-introducing the false
  positives that made it necessary, one commit after they were removed.

Recorded as a test asserting the leak, so a future narrowing shows up as a
deliberate change rather than a silent one. **Tuning a filter immediately after
being burned by tuning it is how you get burned twice.**

## Session 9 — 2026-08-24

The session the live run was finally affordable. Everything below came out of
two commands.

### 52. The first live end-to-end run

`python -m cli --profile examples/beginner_renewables.json`, 255 seconds, exit
0, run id `cli-163fffe8`. Every path through this CLI had been covered by tests
with stubbed agents; none had ever been walked by the real pipeline.

It worked. The brief rendered, the checkpoint saved, and `--resume` now replays
the whole thing at zero quota. Three defects came out of it anyway, which is now
the fourth consecutive time that running existing code under a new condition
found something no test did.

Worth recording precisely because it is the boring outcome nobody writes down:
**the pipeline ran end to end on the first attempt.** The prediction that it
would break on contact was wrong. What it did instead was make things visible.

### 53. A real company lost to the word "Ltd."

The run examined 10 companies and dropped 6 as `no_ticker_found` — the reason
whose docstring says "extraction is producing names that are not companies".
The extraction was fine. Five of the six are genuinely private: Waaree
Transpower, Proton New Energy, DC Handal, JomCharge, ChargeEV, all correctly
dropped.

The sixth was **Waaree Energies Ltd.**, India's largest solar module
manufacturer, listed on both the NSE and the BSE. Searching for it returned
nothing. Searching for "Waaree Energies" returned both listings immediately.

The search passed the name to the provider verbatim, so a legal suffix that a
news article always writes could stop a real company being found at all. The
sharp part: `_NOISE_WORDS` already contained "ltd" and "limited" and already
declared they carry no identifying information — but that knowledge was only
ever applied to SCORING the candidates that came back, never to asking for
them. **The fix was a constant the file already had, used one step earlier.**

Retries only on an empty result, and only strips a TRAILING run of legal form,
so nothing that already resolved can move and "Technology Select Sector" keeps
every word.

This also corrects a diagnosis. The renewables brief recommending Google and
Amazon was recorded as an Agent 3 exposure-prompt problem. It is mostly that —
but the pool Agent 3 chooses from is 3 investable companies out of 10 examined,
because renewable-energy news is dominated by private and foreign firms.
**A stricter exposure grade alone would have emptied the brief rather than
improved it.**

### 54. The press release no source filter could ever catch

The provenance block earned its keep on its first run. Eleven cache entries
carry one, and they answer the question recorded as unproven: **press releases
do reach the risk critic.** Three of the sixteen articles it received were
PowerBank announcing a permit, a 4 MW project and a portfolio acquisition. It
reported no risk from any of them, which is the correct response to a company
announcing its own good news, and the reason it should never have seen them.

`is_press_release` missed all three because the existing document types cover
only the financial calendar — results, dividends, offerings, conferences — and
these are operational announcements. The wire dateline was stripped by the
aggregator, as the code already predicted aggregators do.

The obvious instrument was the source: every one came from
globalrenewablenews.com. **The corpus ruled it out.** All seven cached articles
from that domain were audited. Six are issuer announcements. The seventh is
"Canadian Solar Announces Resolution of Maxeon U.S. Patent Litigation" — the
single headline this project has twice named as the thing that must never be
filtered. An industry wire carries the issuer's good news and the litigation
the critic needs, side by side.

So the rule stayed where it was, extended with four document types that each
name the OBJECT of the announcement: a permit, a megawatt figure, a portfolio,
project financing. That object is what keeps the litigation headline out, along
with "Apple announces changes for apps in the EU" and "SK Hynix Announces $38.5
Billion Manufacturing Expansion". Measured over 283 cached articles: 13 matched
before, 18 after, all five additions genuine issuer documents.

**The domain was the third instrument tried and rejected here on evidence**,
after provider categories and query-term matching. The pattern is consistent:
every cheap signal for "is this article any good" has failed the same way, by
being right about the aggregate and wrong about the one article that mattered.

One test moved to make room. "PowerBank Announces 4 MW Solar Project" had been
listed as must-keep since the bare-"announces" draft was rejected — but it sat
there because that instrument caught it along with everything else, not because
anyone had found the headline to be reporting. The live run is new evidence
that it is not.

### 55. Eleven of twelve, and the one that failed is the one that matters

`python -m evals.runner --tag hard`, the first time the 12 hard Agent 1 cases
have been scored by a real model rather than a string-matching stand-in.
**11/12, 91.7%.** Against the rubric written when they were built — 8 to 10 is
good, 12 means they are too easy — this says the labels are one case away from
not being hard enough.

The failure is `hard_clarification_defers_the_choice_back`. The user asks for
sports and technology while also saying "Do not invest in technology companies",
and clarifies with "Either way is fine, you choose." Expected
`needs_clarification`; got `valid`.

The label predicted that picking for the user "would silently override
something they stated". What the agent actually returned:

    sectors_of_interest: ["sports", "technology"]
    restrictions:        []
    problems: []   reason: null

It did not defer and it did not ask. It resolved the conflict by **deleting the
user's restriction**, recorded no problem, and gave no reason. Of the two
available resolutions — drop the interest or drop the prohibition — it chose
the prohibition, and every downstream agent then researches technology for
someone who said not to.

The prompt exposes `revised_restrictions` and forbids using it to tidy wording,
but says nothing about which side of a conflict may be resolved away. **A field
that can delete a user's stated constraint needs a rule about direction, not
just a rule about tidiness** — and an eval whose expected answer is a status
string could not have seen this, because the status was only the symptom. It
was visible because the runner records the returned profile alongside the
verdict.

Not fixed this session. It is Agent 1 work, the hard set is 12 calls, and this
is the cheapest agent in the project to iterate on.

### 56. A documented number that was never right

`python -m pytest` reports **706 passed, 1 skipped**, not the "707 passed" every
handoff has claimed. 707 is the COLLECTED count. Nobody noticed because
`pytest.ini` already sets `-q` in addopts, so the habit of adding `-q` produces
`-qq`, which suppresses the summary line entirely — the number was being read
off a progress bar of dots. Ends the session at 721 passed, 1 skipped.

### 57. Agent 3's eval, finally run, and the oil major it let through

`python -m evals.company_runner --limit 1`. **0 hard failures.** The drop
accounting balances - 7 examined, 3 candidates, 2 no_ticker_found, 2
incidental_mention - and that was the whole debt outstanding since the
operating-margin fix. 0 scores saturated at 1.0, average completeness 83%, no
growth-sanity breaches. The offline check across eleven companies held up.

The interesting part is what passed. For a profile named
`renewables_excluding_fossil_fuels`, carrying the restrictions "No fossil fuel
companies" and "No coal, oil or gas", the candidates were:

    0.316  TTE      TotalEnergies
    0.304  RWE.DE   RWE
    0.060  PBK      PowerBank

TotalEnergies is an oil and gas major. RWE still burns lignite. And the eval's
own restriction check reported `restriction_violations: []`, because it is:

    term in f"{c.name} {c.exposure_rationale} {' '.join(c.themes)}".lower()

with `forbidden_terms = ("fossil fuel", "coal", "crude oil", "natural gas",
"petroleum")`. "TotalEnergies SE" contains none of them, and the rationale is
about solar and wind. **The check tests the words used to describe a company,
not what the company is.**

The known weakness was recorded in the false-positive direction - "No crypto
exposure" in a rationale registering as a breach. This is the false-negative
direction and it is worse, because the eval reports a clean run on a case a
reader spots in one second. The instrument that would work is already on the
object: `ResolvedCompany` carries `sector` and `industry` from the provider,
and "Oil & Gas Integrated" is a fact Python controls rather than a sentence the
model wrote.

### 58. The zero-candidate profile is not article variance. It is QUERY variance.

Running the decision eval on that same profile twenty minutes later returned
**0 candidates** - the failure recorded since session 5 as "one of two research
profiles keeps returning nothing", attributed to article variance.

Two runs of one profile, one day, both caches on disk, is the comparison that
was never available before. The provider was not exhausted: the failing run
retrieved 8 articles across 4 queries. What differed was the queries themselves.

    company_runner 00:17          decision_runner 00:20
    solar panel manufacturing     offshore wind lease auction announcements
      capacity expansion          green hydrogen export agreements
    grid scale battery storage    utility-scale solar project financing
      contracts                   battery recycling facility approvals
    offshore wind lease
      agreements
    utility-scale solar farm
      construction permits

**Same profile, temperature 0.0, entirely different search queries.** Agent 2
regenerates them each run and they do not repeat.

The failing set asks about PROCESSES AND ASSETS - lease auctions, export
agreements, facility approvals - and those return articles about governments,
banks and projects. One query returned nothing at all. Of the eight articles
retrieved, exactly three named an investable company, and all three came from
the single query phrased around financing rather than approval.

The passing set asks about MANUFACTURING AND CONTRACTS, and those name
companies, because a company is who manufactures and who signs.

So the variance that matters is one stage earlier than recorded, and it is
controllable: a query is generated text, not a fact about the world. **"The
results vary" was true and stopped one step short of the cause.**

Checked and cleared: the corporate-development patterns from entry 54 are not
implicated. `drop_press_releases` is called only in `agents/risk_agent.py`, and
the graph runs 2 to 3 to 4, so Agent 3 saw all three articles whatever the
filter would later have done with them.

### 59. The restriction guard, and what repeating the eval revealed

Fixed entry 55 in two halves, deliberately split by what each half can be
trusted with.

**Python holds the invariant.** `build_profile` now refuses to drop a
restriction unless the user's OWN replies mention what it is about. Additions
are ungated; removal is the only direction that can hurt anybody. The check
reads the user's words and never the model's, which is the part that matters:
a guard that accepted the model's explanation would be one fluent sentence away
from useless. "Either way is fine, you choose" shares no subject word with "Do
not invest in technology companies" and authorises nothing; "actually I don't
mind technology" shares "technology" and is honoured, so a real change of mind
still works.

**The prompt holds the judgment.** Two rules: handing the decision back is not
a resolution, and where a clarification does not say which side to keep, narrow
the SECTORS and leave the restriction standing.

The invariant went in Python because this project has been taught the lesson
four times. A prohibition disappearing is not a language judgment, and entry 55
existed precisely because fluent, confident, wrong output had nothing checking
it.

Verified live: `--tag hard` moved clarification from 2/3 to **3/3**.

**Then the score did not move, and that was the interesting part.** Still 11/12
- but a different case failed: `hard_restriction_excludes_one_kind_of_bank`,
expected valid, got needs_clarification. The obvious reading was that the new
direction rule had over-corrected, teaching the model that a restriction which
NARROWS a sector blocks it.

`--repeat 3` says otherwise. That case returns
`['needs_clarification', 'valid']` on identical input, and the other eleven -
including the newly fixed one - agree with themselves every time. It is a
boundary case that fell the right way in the morning run and the wrong way in
the afternoon one.

Two things follow.

**A single-shot 12-case score has an error bar nobody had measured**, and all of
it sits in one case. The two 11/12 results recorded today are not the same
result: the first failed the clarification case and passed the bank case, the
second did the reverse. **"Unchanged" was the wrong word for it.**

**And the tempting next move is the wrong one.** Entry 51 ends "tuning a filter
immediately after being burned by tuning it is how you get burned twice", and
this is that situation exactly - a prompt changed an hour ago, a neighbouring
case wobbling, and an obvious sentence to add. Recorded instead, so that
clarifying the narrows-versus-blocks distinction is a decision somebody makes
on purpose rather than a reflex while the last change is still warm.

### 60. The zero-candidate profile, fixed one stage upstream

Entry 58 found that the zero-candidate runs differ from the good ones by their
QUERIES, not their articles. The query prompt was thorough about specificity,
dates, restrictions and variety, and silent on the one thing that decides
whether a retrieved article is usable at all: **whether a company is in it.**

Its own list of what to search for - "regulation, capacity changes, supply
chains, major contracts, technology shifts, policy decisions" - contains the
failure. Regulation and policy are real industry news written with a government
as the subject.

Added a section saying so, with the observed contrast: manufacturing, contracts,
acquisitions, orders and financing are written with a company as the subject,
because a company is who builds and who signs; auctions, permits, approvals and
bilateral agreements are not. Policy is capped at one query in six.

Verified live on the profile that had been failing:

    before   0 candidates    (8 articles about ministries and projects)
    after    3 candidates    SUZLON.BO 0.486, GOOG 0.450, AMZN 0.286
             completeness 83% -> 100%, 0 hard failures

**The top candidate is now a wind turbine manufacturer** rather than a data
centre operator, and it is an Indian listing in INR - the same class of company
that entry 53 found being dropped over a legal suffix. Two fixes from opposite
ends of the session pointing at the same gap: the pipeline was systematically
losing the pure-plays and keeping the megacaps that happened to be nearby.

### 61. Grade a buyer as a buyer

Agent 3's exposure prompt already said a company "mentioned only as a customer"
is incidental, and Alphabet and Amazon were still graded against a battery
storage theme, because both buy battery storage for data centres.

The prompt stated the principle without a ceiling. Added one: where the
company's industry sits outside the theme's sector, the highest grade available
is incidental unless the article shows it producing, supplying or building
rather than using - and size does not change that, because a very large buyer is
still a buyer. The test offered is which way the money flows. If the theme
playing out means the company SPENDS more, it is a customer.

**Written but NOT verified.** Quota ran out before Agent 3 could be re-run, and
on this project a prompt change nobody has measured is a hypothesis.

### 62. Agent 5 was never given anything to cite

The recorded defect was that Agent 5 barely cites articles - 1 of 8 exit
conditions - and one round of prompt work had already moved it from 0/9 to 1/8.
Read as the model taking the cheap option, since metric thresholds are identical
for every company in every sector.

The live run says otherwise. Which company produced the one citation is the
clue:

    GOOG   0 risks                          0 articles reached Agent 5
    AMZN   1 risk, 1 article_id             1 article  -> the ONE cited condition
    PBK    2 risks, both article_ids=[]     0 articles reached Agent 5

`RiskFindings.articles` deliberately keeps only the articles a risk actually
CITED, and `risk_rules` produces metric-derived risks - leverage, negative free
cash flow - which cite nothing. So for two of the three companies Agent 5 was
handed no articles at all, and the prompt's rule is explicitly conditional:
"when articles are supplied below, at least one of your conditions must be
about what those articles describe."

**It complied every time it could.** 1 of 1, not 1 of 8.

The candidates were carrying evidence the whole way: `evidence_article_ids` has
1, 1 and 2 entries for the three companies. Those Article objects live in
`ResearchFindings`, which `decide()` is never passed.

So the fix is to plumb research findings into `decide()` and widen
`_evidence_for`. **Deliberately not done today.** It changes what the last agent
in the graph is fed, and a theme article is bullish where a bear-case article is
not - it could as easily produce worse conditions as better ones. There was not
enough quota left to run the decision eval, and shipping an unmeasured change to
Agent 5 is the exact move this project's first lesson warns against.

**Three times today the recorded diagnosis was one stage upstream of the cause**
- the exposure prompt (a query problem), the zero candidates (a query problem),
and now the citation rate (a supply problem). The common shape: each was
described by looking at the output of the last stage that touched it.

### 63. The rendered log went stale in four minutes

`docs/project_log.html` was committed so the document is available without
running anything. Three entries were appended to the markdown immediately
afterwards, and the committed HTML still described the previous state - caught
by chance while writing the summary, not by anything in the repo.

A copy nobody regenerates is a copy that lies, and this one lies in the document
handed to a person. It is the same failure as prose drifting from behaviour, so
it gets the same instrument: a test that rebuilds from the markdown and fails if
the committed file is not what comes out. Broken on purpose first - append an
entry, do not rebuild, watch it go red.

The assertion reduces to a bool before comparing. Asserting the strings directly
made pytest dump both sides, a hundred kilobytes of HTML, and the only useful
line - the command to run - scrolled off the top. **A guard whose failure
message cannot be read is most of the way to no guard at all.**

Four tests, not one: the drift check, an entry count so a converter that
silently drops a section is caught on the day it happens rather than the next
time somebody looks, a check that no raw markdown reaches the reader, and
idempotence, without which the drift check would fail at random.

### 64. The build that never returned

Checking whether the new render guard would survive a Windows checkout - git
converts line endings, and the committed HTML would then be compared against
output built from CRLF source - hung. Not failed. Hung, with no timeout and no
output, and had to be killed.

Every branch of the converter tests the START of a line. One does not: the table
rule tests whether the NEXT line is all dashes and colons, and a trailing
carriage return is neither. So under CRLF no table was recognised, the row fell
through to the paragraph branch, and that branch **refuses lines beginning with
a pipe**. It appended nothing and advanced nothing.

Two fixes, because they answer different questions.

Normalising line endings at the top removes the trigger. But the hazard is
structural: every branch either consumes a line or falls through to a paragraph
loop that rejects some of the lines which can arrive there, and reasoning about
which ones is exactly the reasoning that was already wrong once. The paragraph
branch now consumes a line unconditionally when it would otherwise take none.
**Guarantee progress rather than proving it unnecessary.**

A third thing fell out while testing the shapes: `set(rule) <= {"-", ":"}` is
true for the empty string, so a pipe line followed by a BLANK one was read as a
one-row table. The rule now has to contain a dash.

Worth noting how this was found. Nothing in the session's own work touched
CRLF - the check was speculative, aimed at a CI platform this machine is not,
and it found a defect that had nothing to do with CI. **The guard written in
entry 63 was itself unverified on one of the two platforms it runs on**, one
commit after being described as a mechanism.

The regression test asserts almost nothing about the output. It feeds nine
malformed inputs and passes if the function RETURNS. A hang is the one failure
a test suite cannot report.

### 65. Narrowing a sector is not contradicting it

Entry 59 left `hard_restriction_excludes_one_kind_of_bank` sitting on the
model's decision boundary - "banking" with "No investment banks" returning
`valid` on one run and `needs_clarification` on the next - and deliberately did
not chase it, because the prompt had been changed an hour earlier.

Chased it now, with the reason it wobbled. Three of the twelve hard cases test
the same distinction: a restriction naming PART of a sector leaves the rest to
research, and a restriction naming the WHOLE sector leaves nothing. The prompt
never said so. Its conflict rule gave only the emptying example - technology
minus technology companies - and its list of things that do NOT need
clarification was about timeframes and experience levels.

Worse, entry 59's own fix pushed against it: "a restriction and an interest are
not equal, narrow the sectors and leave the restriction standing" is correct for
a genuine conflict and reads, to a model, like a reason to treat any
restriction-versus-sector pair as one.

Added the missing rule with the test stated as a question - is anything LEFT to
research - and the three real cases as worked examples. Narrow is not the same
as contradictory, and only the investor can decide their own interest has been
narrowed too far.

**Written, NOT verified.** See the next entry.

### 66. A probe that answered the wrong question

The narrows-versus-blocks rule from entry 65 was written and then verified with
`--tag hard --repeat 3`. The run returned **0/12**, every case a
`RateLimitError`, and the error carried the number this project has spent nine
sessions guessing at:

    Limit 200000, Used 199921, Requested 3430

Nothing was wrong with the prompt. The day was simply over.

What is worth recording is the check that preceded it. Groq does not report the
DAILY budget in its response headers - only the per-minute one - so remaining
quota was tested by making one deliberately tiny call and seeing whether it came
back 200. It did, and that was read as permission to start a 36-call run.

**It was a true answer to a question nobody needed.** 79 tokens remained. A
one-token probe fits in 79 tokens, so the probe could not have failed, and its
success carried no information about whether 25,000 more would fit. A test that
cannot fail is not evidence - session 6 learned exactly this about a mutation
test and it was recorded as entry 51 - and here the same mistake was made about
a quota check, one day later, by someone who had just re-read that entry.

The instrument that does work is the failure itself: the 429 states Limit, Used
and Requested exactly. There is no way to ask for that number without being
refused, so the honest options are to read the console, or to accept that a long
run may stop partway and be resumable. **Do not probe for headroom with a call
too small to be refused.**

Cost: a verification that has to be run again. **Not the budget** - that was
already gone, spent by the CLI run and three evals, and the refused requests
consumed nothing. Corrected the same night after the console appeared to
disagree: it buckets by CALENDAR DAY and the limit is a rolling 24 hours, so a
session running past midnight is split across two rows that neither of them is
the number being enforced.

The three 429s show it directly, seconds apart:

    Used 199921
    Used 199916
    Used 199912

**Used goes DOWN while requests are refused.** The window drains continuously as
old calls pass the 24-hour mark, and a rejected call adds nothing to it. Which
also means the refusal is not merely the honest instrument, it is a FREE one:
starting the real run costs nothing when there is no room for it, and the error
states Limit, Used and Requested exactly. There was never a reason to probe.

## Session 10 — 2026-08-25

The closing session. Three verifications were owed; two came back clean, the
third is built and half-measured. The session's own instrument turned out to be
the finding twice - a provenance block written for a future run, and a
checkpoint database built for resuming one.

### 67. Narrows versus blocks, verified - and the set is now too easy

`--repeat 3`, 36 calls, **12/12 with every case agreeing with itself three
times.** `hard_restriction_excludes_one_kind_of_bank` - the case that returned
`valid` on one run and `needs_clarification` on the next, which is what sent
entry 65 looking for a missing rule - now lands the same way three times
running. Clarification held at 3/3. Nothing else started wobbling, which was the
actual risk: the rule was added to a prompt that four other cases depend on.

The rubric written with these cases says 8-10 correct is a good hard set and 12
means it is too easy. It scored 11 yesterday and the note then was "one case
away from not being hard enough". **That case was the defect, and fixing it
spent the margin.** The set is no longer measuring anything; it is confirming.
Whoever next touches Agent 1 has to write harder cases before the run means
anything, and the honest reading of 12/12 is not "Agent 1 is finished" but "this
instrument has run out of range".

Worth keeping: `--repeat 3` is what made this readable. A single pass returning
12/12 would have been the same number with none of the confidence, because one
non-deterministic case puts about +/-1 of noise on a single-shot score.

### 68. The queries got longer and the news ran out

Verifying entry 61 needed one `company_runner` case. It returned **1 theme, 1
article, 0 mentions, 0 candidates** - and 0 candidates for a reason that had
nothing to do with the exposure rule being verified. Agent 3 was never given
anything to grade.

The provenance block from entry 49 - added because a future run would need it,
and with no way to prove that at the time - answered it immediately:

    SunPower solar panel manufacturing expansion            found 0
    Vestas wind turbine supply chain expansion              found 1
    Orsted green hydrogen production facility investment    found 0
    NextEra Energy renewable portfolio expansion contracts  found 0
    Enphase Energy battery storage contracts                found 0

Every query names a specific company and then ANDs four or five more terms onto
it. TheNewsAPI is plain space-separated AND with no `OR`, and three ANDed terms
usually returns nothing - which is documented, in this repo, as a known limit.
Five returns nothing at all. The single article that came back is an off-topic
climate-policy long-read that names no company.

**This is entry 58's defect wearing the opposite coat.** That fix taught Agent 2
that a useful article contains a COMPANY, because its queries had been returning
ministries and policy announcements. The model appears to have read that as
"name companies in the query", which is the one place naming them cannot help:
the company name is a term the article must also match, so each name makes the
query narrower rather than better targeted.

Not fixed here, because fixing a prompt and measuring an unrelated prompt in the
same run leaves neither one measured. Recorded as the next defect with its
evidence attached.

**The instrument is the finding.** Six sessions of retrieval failures were
diagnosed by inference - article variance, query variance, provider quirks - and
this one was diagnosed by reading what was actually asked. The provenance block
cost an afternoon and paid for itself the first time a run came back empty.

### 69. Grade a buyer as a buyer, verified - against the exact inputs that failed

The exposure ceiling from entry 61 could not be verified by the eval, for the
reason above. It was verified instead by replaying Agent 3 over the
ResearchFindings frozen in the `cli-163fffe8` checkpoint - the exact 8 articles
that produced the grades being complained about.

    before                       after
    GOOG   partial               incidental_mention  "buys storage, not producing"
    AMZN   partial               incidental_mention  "finances storage, buyer"
    META   -                     incidental_mention  "buys solar electricity, not storage"
    PBK    direct                direct              "acquires solar assets"

The rationales quote the rule's own test back - which way the money flows -
rather than reaching the right answer by some other route. PBK survives, and it
is a renewable utility by the sector the provider reports, not by the model's
opinion of it.

**The brief emptied, exactly as predicted: 3 candidates to 1.** That was written
down in advance as the real risk, and it happened, and it is still the right
outcome. Two of the three candidates were a mega-cap advertising business and a
mega-cap retailer, in front of a beginner who asked about renewable energy. One
honest candidate is a thinner brief than three and a better one. The thinness
has a separate and known cause - only about 3 of 10 examined companies are
investable, because renewable news is dominated by private and foreign firms -
and it is not repairable in Agent 3's prompt.

**Replaying against frozen inputs beat re-running the eval, for the third time.**
It cost one stage instead of two, it removed retrieval variance from a
measurement that had nothing to do with retrieval, and it compared against a
recorded result rather than a remembered one. The checkpoint database was built
so a person could resume an interrupted run; it turns out to be the best
regression instrument in the project, because it is the only place a real run's
intermediate state is kept.

### 70. Agent 5 cited everything it was ever given

Entry 62 re-diagnosed the 1-of-8 citation rate as a plumbing fault rather than a
lazy model. The fix is now built: `decide()` takes `ResearchFindings`, and
`_evidence_for` returns the articles a risk cited PLUS the candidate's own
`evidence_article_ids`, deduplicated, bear case first. Four tests, two of which
go red when the widening is reverted - broken on purpose first, per entry 51.

What the frozen `cli-163fffe8` state says, at zero quota:

    GOOG   citable 0 -> 1     recorded run cited 0 of 3 conditions
    AMZN   citable 1 -> 2     recorded run cited 1 of 2 conditions
    PBK    citable 0 -> 2     recorded run cited 0 of 3 conditions
                              total citable articles 1 -> 5

**The recorded citation count equals the citable count on every row.** Agent 5
cited every article it was ever handed, three times out of three. The 1-of-8
figure was never a measurement of the model's behaviour; it was a measurement of
what reached it. This is now shown from the run's own data rather than argued
from the code.

**Built, and measured a few hours later - see entry 72.** The live half first
hit the ceiling mid-run at `Limit 200000, Used 197710, Requested 3985`. Starting
the run was still the right move: the refusal cost nothing and stated the number
exactly, which is entry 66's lesson applied. The window then drained enough to
finish the same day.

And the free half surfaced the thing the live run has to check. PBK's two new
articles are *"PowerBank Acquires New York Solar Portfolio"* and *"PowerBank
Receives Final Environmental Permit"* - both issuer announcements, and both
exactly what the press-release filter of entry 47 was extended to keep AWAY from
the risk critic, because it found no risk in any of them. They are legitimate
theme evidence, which is why that filter was scoped to the critic alone. But an
exit condition asks what would mean the case has BROKEN, and a permit being
granted is not that. **The hazard is now specific rather than theoretical: the
citation rate can rise while the conditions get worse.** Count the rate, then
READ the conditions. If they read as thesis restatements wearing a citation, the
answer is a prompt rule about what a theme article can and cannot ground - not
removing the plumbing, which is correct.

### 71. Closing entry: what is being accepted, and why that is not ignoring it

The project is being called done. Two structural weaknesses stay open, on the
same terms as the scoring limits in `agents/screening.py` and the off-topic
matches of entry 47: **measured, understood, and left deliberately.**

**Agent 2 records almost no dissenting evidence.** Most themes cite one article,
and one article cannot disagree with itself. This is not a prompt fault and no
prompt fixes it - it is the shape of a three-article-per-request news budget. It
is worked around rather than solved: Agent 4 does its own adversarial retrieval,
so the dissent enters the pipeline one stage later than it should. The
workaround is load-bearing. If Agent 4's bear queries ever stop returning
anything, this comes back immediately and there is nothing behind it.

**Agent 4's source filter cannot cover its long tail.** Audited against 224
cached responses: 272 articles, 130 sources, and **86 of those 130 contributed
exactly one article.** Widening the list from 2.6% to 15.1% coverage was worth
doing because every name added was actually observed. Going further is not, and
the reason is arithmetic rather than effort: a list of names cannot cover a
distribution whose mode is one. The two instruments that would work on the tail
were both tried and both failed on real data - provider categories put a private
equity acquisition in the same bucket as everything uncategorised, and
query-term matching cannot tell a lithium battery deal from a battery storage
company. What replaced the list is not a better list: it is the press-release
filter, which tests article SHAPE rather than publisher, and the journalism veto
that protects real bad news from it.

Both of these share a property worth naming at the end of a project. **They are
the two weaknesses a prompt cannot reach.** Every other defect in this log - the
operating margin of 168, the queries that named ministries, the buyer graded as
a producer, the citations that were never supplied - was ultimately a sentence
someone could write or a value Python could check. These two are properties of
the data available, and the honest response to those is to state them where a
reader will find them, rather than keep adding names to a list and calling it
progress.

The lesson the whole log keeps returning to, stated once more because it applies
to the closing decision as much as to any fix in it: **unit tests prove the code
does what it says; only the evals show whether what it says is right.** 752
tests pass. That was never the question.

### 72. The measurement that arrived after the closing entry

Entry 71 closed the project with 2.6 built and unmeasured, because the quota
ceiling landed mid-run. The window drains continuously, and a few hours later
there was room. **The measurement is done, and it is the last one this project
owed.**

Replayed over the frozen `cli-163fffe8` state, so the only variable is whether
`decide()` was handed `ResearchFindings`:

    recorded run, months of argument about it     1 of 8 conditions cited
    same inputs, research WITHHELD, re-run now    1 of 7
    same inputs, research SUPPLIED                3 of 7

The middle row is the one that makes this readable. Re-running the baseline in
the same session, against the same frozen state, reproduces 1-of-N - so the jump
to 3 is the plumbing and not the weather.

**But the rate was never the interesting half.** Entry 70 predicted a specific
way this could go wrong: two of the newly citable articles are *"PowerBank
Acquires New York Solar Portfolio"* and *"PowerBank Receives Final Environmental
Permit"* - bullish issuer announcements, exactly what the press-release filter
keeps away from the risk critic. An exit condition asks what would mean the case
has BROKEN, and a permit being granted is not that. The fear was that the
citation count would rise while the conditions got worse.

It did not happen. The model INVERTED the bullish articles rather than restating
them:

    GOOG  "Google announces it will no longer finance battery storage projects"
    PBK   "PowerBank's acquisition of the New York solar portfolio is delayed
           or canceled"
    AMZN  "found liable in the Twitch AI training lawsuit and fined more than
           $100 million"                                      [the bear article]

All three are checkable in six months with a yes or no, and each is the negation
of the thesis it belongs to rather than an echo of it. The AMZN condition also
gained a threshold it did not have before - the recorded run said only "is found
liable".

**What got displaced is the better part of the result.** PBK went from three
conditions to two, and the three it had were `revenue_growth turns negative`,
`operating_margin turns negative`, `gross_margin falls below 0.20` - the generic
answer, written without reading anything, identical for any company in any
sector. GOOG's were the same shape. Giving the model something real to cite did
not merely add a citation; it **pushed out boilerplate**. Seven conditions
carrying three real ones beats eight carrying one.

Two things worth keeping from how this was measured.

**The prediction was worth writing down even though it was wrong.** Entry 70
named the failure mode in advance and said to read the conditions rather than
trust the count. That is what turned a number into a result: 3-of-7 alone would
not have distinguished "cites real evidence" from "cites a permit approval as a
reason to sell". The check was cheap because the question was already written.

**Two runs were lost to output handling, not to the model.** A print statement
reached for a field name that did not exist, and a console encoding failed on a
non-ASCII character - both AFTER the model calls had been paid for. The first
cost a full Agent 3 replay and was plausibly the difference between finishing at
the first attempt and hitting the ceiling. The second cost nothing, because by
then the result was being written to disk before anything tried to print it.
**On a metered API, persist the result before formatting it.** Formatting is
free to retry and the call is not.

A footnote on the candidates themselves: GOOG and AMZN would no longer reach
Agent 5 at all, because entry 69's ceiling now grades them `incidental_mention`.
The frozen state is deliberately stale - holding the inputs constant is what
makes this a measurement of Agent 5 rather than of the pipeline. Read together,
the two fixes agree: Agent 3 stops the data-centre buyers from arriving, and
Agent 5 does better with whatever does.
