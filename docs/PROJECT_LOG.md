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
START → Profile → (valid) → Research → Companies → [Risk Critic] → [Decide] → END
              ↳ (conflict) → ask user → back to Profile
```

| Stage | Job | State |
|---|---|---|
| 1. Profile | Validate investor input; ask about genuine contradictions | Built |
| 2. Research | Identify themes, grounded in retrieved news | Built |
| 3. Companies | Extract, resolve, screen and rank companies | Built and verified |
| 4. Risk Critic | Adversarially attack each candidate | Planned |
| 5. Decide | Score, select, state exit conditions | Planned |

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
| yfinance | Its **search is better than FMP's** | FMP returned a cryptocurrency for "SMIC" and Canada for "Nvidia" |
| Both | Fundamentals arrive in local currency — USD, HKD, INR, **GBp** (pence) | Only the four unitless ratios are cross-comparable |
| Windows | Console is cp1252 and cannot encode model output | Killed a completed eval run mid-report |

---

## Where things stand

**Built and verified:** Agents 1, 2 and 3.

**276 unit tests**, ~2 seconds, no network and no API key required.

Agent 3's baseline finally ran on 2026-08-21 across all five profiles. It found
four defects, all of which are now fixed and covered by regression tests, and
every post-fix run has reported **0 hard failures**.

### Measured weaknesses, deliberately not guessed at

- **Agent 2 records almost no dissenting evidence** — one `weakens` stance across
  every run ever made. Diagnosed on 2026-08-22 and it is **not the prompt**: most
  themes cite exactly ONE article, and a theme with one citation cannot record
  dissent because there is no second article to disagree. Themes are also derived
  from their own evidence, so a contradicting article becomes a different theme
  rather than dissent within this one. Underneath both: TheNewsAPI's free tier
  returns 3 articles per request. **Decision: fix it in Agent 4, not Agent 2** —
  the risk critic retrieves its own counter-evidence rather than depending on the
  researcher to have been self-critical.
- **Ranking still saturates at the very top.** Raising the caps fixed the part
  that mattered — TSMC and SK hynix tied at 1.000 and could not be ordered — but a
  company far beyond every cap still scores exactly 1.000, because a ramp clips by
  construction. Accepted: one company at 1.000 is ranked first, which is correct.
- **Financial companies are capped at 0.50.** At most two of four metrics exist
  for a bank, and score multiplies by completeness. Verified across ten major
  banks: all sit at exactly 0.50 and are kept. Accepted, because profiles are
  sector-themed, so every bank carries the same handicap and relative order is
  unaffected.
- **13 of 18 Agent 2 themes cite a single source**, and it reaches the theme cap
  on well-covered sectors. This is the same root cause as the dissent gap.
- **Agent 1's eval set scores 100%**, so it catches regressions but has no
  headroom to show improvement.
- **Ticker resolution rate varies a lot between runs.** One banking run failed to
  resolve 4 of 7 mentions and returned zero candidates. Degrades safely — it
  records a drop reason rather than guessing — but worth watching.

### Deferred, not blocking

- **No CLI.** There is no way for a person to run the pipeline — only Python
  snippets. Also the thing that would make the project demonstrable.
- **`InMemorySaver`** loses all state on restart, including a user mid
  clarification. Needs `SqliteSaver` before any real use.
- **The exclusion check matches naive substrings**, so a rationale reading "no
  crypto exposure" would register as a violation. Consistent with how Agent 2
  already checks themes. Not yet observed.

### Next

Sequencing decided 2026-08-22: **finish the pipeline first, then harden once.**

1. **Agent 4 (Risk Critic).** Needs no new API key, but DOES need news-API
   budget: the decision above makes it retrieve its own bear-case evidence, then
   reason — so it is closer in size to Agent 2 than to a pure reasoning step.
2. **Agent 5 (Decide).**
3. **One hardening pass** — CLI, `SqliteSaver`, harder Agent 1 eval cases, plus
   whatever Agents 4 and 5 expose in the earlier agents.

The alternative was to clean up the known gaps in Agents 1-3 first. Rejected for
three reasons, recorded so the choice is not silently reversed:

- **Most of the gaps are already decided.** Agent 3's two limits were
  deliberately accepted; Agent 2's dissent gap is already routed into Agent 4.
  What genuinely remains is Agent 1 eval headroom, which is small and not urgent.
- **Agents 4 and 5 will show what actually needs fixing.** `CompanyFindings` has
  no real consumer yet. Whether the currency field, exposure grades and score
  semantics are right FOR A CONSUMER is unknowable until one exists. Fixing now
  optimises against an imagined caller.
- **The question this project exists to answer is unanswerable at 3 of 5
  agents** — does the system produce a defensible recommendation, or correctly
  refuse to? Every session spent polishing links postpones the only test that
  counts.

The CLI belongs in the hardening pass specifically because its shape depends on
the finished pipeline; building it now means building it against three agents and
revising it twice.

**Known risk in this plan:** "harden later" is where cleanup goes to die. The
mitigation is that the list is written down here and in the handoff, so it is a
tracked commitment rather than an intention.

**Watch from Agent 4's first eval:** it adds retrieval, so per-profile cost rises
above the current 25-30k. If one end-to-end profile costs 50k+, a full run stops
fitting inside a day's quota, and caching or a cheaper model for some calls stops
being optional. Deal with it then, not at Agent 5.
