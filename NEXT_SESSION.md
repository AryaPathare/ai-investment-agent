# Start here

**Written against `6512a09`, 2026-09-08, at the end of session 20.** Before
trusting a word of this:

```powershell
git log --oneline 6512a09..HEAD
```

Thirty seconds, and it is here because of entry 92: session 15 opened this file,
believed it, and spent a stretch working on a project four sessions out of date -
planning tasks that were already done and nearly reverting a prompt section that
four sessions of evals had since been run against. Two signals were available and
neither was used. A handoff is a CLAIM about the repository, not the repository,
and it is written by somebody who is about to stop working and cannot describe
what happens next.

**Session 19's four commits are PUSHED and CI is green on all of them.** That
was the first thing session 20 did; there is nothing outstanding from it.

Session 20 spent no news requests and shipped no behaviour change. It answered
entry 112, and the answer was no - see below. Session 21 then began the deploy
work and added the first tests the deployment config has ever had. The suite is
**1040 passed, 1 skipped**.

- Repo: <https://github.com/AryaPathare/ai-investment-agent> (public, MIT)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- `docs/PROJECT_LOG.md` is current through entry **118**, 20 sessions
- Tagged **`v1.0.0`** at `48f9c08`, which the case study quotes

---

## The task list, agreed at the end of session 20

Eight items, grouped by what BLOCKS each one rather than by how interesting it
is. Everything below was checked against the repository on 2026-09-08, not
carried forward from a previous handoff - which is the mistake the section
"What is not written down" further down records this file making twice.

### A. Quota-bound - need a day's headroom

**A1. The Basic Materials gallery run.** ~28k tokens and ~13 news requests, and
the gallery is complete at eleven of eleven sectors plus the run that recommends
nothing. The profile is written and validated under "Where the gallery got to"
below; audit before recording.
Watch this one specifically: Basic Materials is the lithium-shaped sector, entry
112 is measured and UNFIXED, so a project vehicle can still be recommended as a
company. Steering the narrowing to copper is deliberate.

**A2. `python -m evals.company_runner` against the buyer ceiling (entry 106).**
~28k tokens. Owed since session 19 and the honest gap - the ceiling is measured
on one frozen state plus five live runs that it graded defensibly. It guards
BOTH directions: a ceiling that is too aggressive empties briefs, which is
exactly how entry 69 played out.

### B. Free - no model calls at all

**B3. The public-documents refresh - HALF DONE in session 21.** The four stale
numbers are FIXED (README twice, README's entry count, DESIGN's entry count),
because session 21 added tests and so moved the count itself. **What remains is
the limitations list**, which stops at entry 91 and therefore omits entry 112 -
the one that can put a project vehicle in front of a reader - plus entries 116
and 118. Free, and still the file a stranger reads first.

**B4. Entry 116 - `<Country>'s <Company>` does not resolve.** The cheapest open
item to VERIFY and the easiest to get wrong. Verifiable end to end offline,
because resolution is Python plus a cached search - but it touches
`resolve_company`, which `AMD`, `IBM`, `BP`, `GE`, `RWE` and `SMIC` all depend
on, and entry 53's retry does not reach it: the possessive has to be normalised
out BEFORE scoring, not merely before searching. Decide the approach first, the
way entry 112 was decided.

### C. Decisions before any work

**C5. Retrying entry 112.** Optional. Only worth starting with n of at least 6
per arm, and the rule has to remove PPG WITHOUT increasing verbatim copying,
which is what defeated the last attempt.

**C6. Failed-run resumability, 2.10's second half.** Re-entering a completed
thread, which changes what `--resume` and `--list` mean for every run.

**C7. Agent 1's hard eval set is exhausted.** 12/12 across `--repeat 3`, which by
the rubric written with those cases means it confirms rather than measures.
Writing harder cases is free; running them is 12 calls.

**C8. `disqualified_by_risk` has still never fired on real data.** Deliberately
not forced - a fabricated critique proves only that the code runs on a
fabrication. It waits on a live run where a critic genuinely finds something
critical.

### Order

**B3 first** - free, and it is the reader-facing one. **A1 the moment news
headroom returns**, because the gallery slot is the only item with a deadline of
sorts: every day it is missing is a day the site shows ten of eleven sectors.
Then **A2**. B4 is the interesting engineering and wants a decision before code.

---

## Where the gallery got to

**Eleven recordings: ten of the eleven sectors, plus the run that recommends
nothing.** Was five.

```
  technology              semiconductors, chip manufacturing equipment
  healthcare              Healthcare                      (triage, zero quota)
  financial-services      cryptocurrency, banking
  energy                  Energy, oil services and refining
  utilities               renewable energy, wind power
  industrials             Industrials
  consumer-cyclical       Consumer Cyclical, carmakers
  consumer-defensive      Consumer Defensive, food producers
  communication-services  Communication Services, streaming and telecoms
  real-estate             Real Estate                     (triage, zero quota)
  nothing-recommended     renewable energy                (recommends nothing)
```

**Basic Materials is the only sector still missing.** It was attempted and the
daily ceiling landed first:

    Limit 200000, Used 196148, Requested 5411

One run, ~28k tokens and ~13 news requests, and the slot is complete. **Still
outstanding after session 20**, which had 8 news requests left and did not
attempt it: a token ceiling refuses for free and states the numbers, but a news
shortfall lets the run start and die partway with Agents 1 and 2 already paid
for. This is the first item to spend on.

**A lithium-shaped Basic Materials profile is the one that produced entry 112.**
That is now measured and unfixed, so a run down that theme can still put a
project vehicle in front of a reader. Note that `render.SECTORS` offers
`lithium mining, chemicals` as this sector's narrowing, and steering to copper
is a DELIBERATE departure from the menu wording for that reason; audit the
mentions before recording whatever lands.

**The profile is written and validated through `UserInput`** - demographics
varied against the eleven already in the gallery, no restrictions, so nothing
in it needs deciding before it is spent:

```json
{
  "age": 52,
  "investment_experience": "advanced",
  "risk_tolerance": "moderate",
  "investment_amount": 60000.0,
  "investment_currency": "USD",
  "holding_period": "5-7 years",
  "sectors_of_interest": ["Basic Materials", "copper and specialty chemicals"],
  "restrictions": []
}
```

**The profile shape that works, and it is not the plain sector name alone.** Lead
with the plain sector name so a visitor can see which sector a run is, then add
the menu's OWN narrowing from `render.SECTORS`:

```json
"sectors_of_interest": ["Basic Materials", "copper and specialty chemicals"]
```

Plain "Energy" had produced EV-charging and solar themes and nothing about oil.
`["Energy", "oil services and refining"]` produced ONGC, Indian Oil and BPCL on
refinery-capacity themes, first attempt. That is entry 83 working as designed -
the menu teaches the narrowing at the moment of choice - and it is the single
most useful thing to know before spending a run.

Vary age, experience, risk, currency and amount; `scripts/` has no profile
fixtures, so write the JSON and validate it through `UserInput` before spending
anything on it. Record each run AS IT LANDS:

```powershell
python -m scripts.record_run <id> --to demo/gallery/basic-materials.json
```

**Audit a run before recording it.** Every check is free, and all of them come
out of the checkpoint - industry versus theme sector for entry 106, name length
for entry 110, restriction terms for entry 104, `holding_period` for entry 105.
Session 19 refused four runs on that evidence without a single model call.

**Do NOT record:** `web-4d0d8c07`, `web-6ec0f651`, `web-9f7f85af` (superseded by
session 18), `cli-008657ee` (Amazon graded `partial` in a healthcare brief),
`cli-37e6602b` (ALCO, farm products, in a technology brief), `cli-db89f371` (the
good-looking Energy run, refused over entry 110), `cli-66c74b37` (the PPG run -
see below).

---

## The two defects session 19 found, and what is owed on each

**Entry 110, a name cut one character below the field width - FIXED in `015fe91`.**
`"BHARAT PETROLEUM CORPORATION L"` is thirty characters and cut mid-word, so
entry 103's `>= 31` test let it through, its bear case reviewed zero articles, and
the brief said "we argued against this one and it held up" about its own third
recommendation. Lowering the constant was wrong - four complete cached names sit
at exactly thirty. There is now a SECOND signal, `_cut_mid_word`, which asks
whether the short name is the long name stopped in the middle of a word. Zero
false positives over all 125 cached names, and both halves broken on purpose
before being trusted. Verified live: a 33-character name now arrives whole.

**Entry 112 was ANSWERED in session 20, and the answer was to revert. Do not
re-open it without reading entries 115-117 first.** The approach chosen was the
narrow one - the missing member of the extraction prompt's own
`WHAT IS NOT A COMPANY MENTION` list, since a named project or joint venture had
no entry in it. Measured against the frozen research of `cli-66c74b37`, no news
requests, control and treatment in the same session:

    control (n=6)   PPG extracted 3/6   "China's Ganfeng" as the NAME 0/6
    treated (n=4)   PPG extracted 0/4   "China's Ganfeng" as the NAME 2/4

It removed PPG and, in half its runs, removed **Ganfeng** - the company that
actually signed the deals, and a legitimate `direct` grade in the recorded run.
`resolve_company("China's Ganfeng")` returns `None`. The criterion had been
written before the first call and it said revert, so it was reverted.

**Two things a next attempt must carry.** Entry 112's defect is INTERMITTENT -
3 of 6, not 2 of 2 - so a pair of runs is not a baseline and any future
measurement needs n of at least 6 per arm. And the treated prompt worked by
making the model copy the article's phrasing verbatim, which is what dragged the
possessive into the name; a rule that gets PPG out without increasing verbatim
copying is the thing to look for.

The triage that preceded it, all free and worth not repeating: an acronym
modifying an asset noun appears **6 times in 841 cached articles**, and across
**all 82 candidates this project has ever produced** PPG is the only one that is
not a real company for its theme. Two other non-company acronyms were extracted
and cost nothing - `TENER` (a Siemens Energy product) and `SEMI` (a trade body)
both died downstream. The harm needs extracted AND resolvable AND unrelated, all
at once.

**Entry 116, `<Country>'s <Company>` does not resolve - OPEN, NEW, and a
decision rather than a fix.** Found by the measurement above and NOT created by
it. The extraction prompt says to write the name as the article writes it, and
prose writes `China's Alibaba`, `China's Niutech`, `Canada's Fairfax` - **134
hits across 122 distinct phrases in the same 841 articles.** A name in that
shape resolves to `None`.

Entry 53's trailing-legal-form retry does NOT reach it, and the reason is the
whole decision: that fix is safe because the words it strips are already in
`_NOISE_WORDS`, so scoring is unaffected. `resolve_company` scores hits against
the ORIGINAL name at `NAME_MATCH_THRESHOLD = 0.6`, and `China's Ganfeng` against
`Ganfeng Lithium Group Co. Ltd.` scores **0.33**. Retrying the SEARCH alone
changes nothing; the possessive has to be normalised out before scoring, in a
function `AMD`, `IBM`, `BP`, `GE`, `RWE` and `SMIC` all ride on. Verifiable
entirely offline at zero model cost - resolution is Python plus a cached search.

**Entry 112's original write-up, kept because the reasoning still holds:**
A Basic Materials run recommended PPG Industries, a coatings company, for a
lithium theme. The cited article says *"three Salta lithium projects into the PPG
joint venture"* - `PPG` is Pozuelos-Pastos Grandes, the project vehicle. The
extractor read it as a company, `resolve_company("PPG")` returned a real and
correctly matched security, and every check passed because every check was right:
real citation, real reporting, industry genuinely Basic Materials so entry 106's
ceiling saw no mismatch.

**Do not reach for the obvious rule.** Refusing bare acronyms would reject `AMD`,
and making `AMD` resolve was a deliberate session-1 fix - resolution accepts a
symbol match precisely so acronyms work, and `IBM`, `BP`, `GE`, `RWE` and `SMIC`
ride on it. What separates them is grammatical, not lexical: `AMD announced` has
the acronym as an actor, `the PPG joint venture` has it modifying a noun. That is
a judgement about prose, so it belongs to the extraction prompt - and a prompt
change here is a hypothesis until measured. **Decide the approach before writing
anything**, and measure it against the frozen research of `cli-66c74b37`, which
is the exact input that produced it.

**Entry 111, two fixes that were measured and NOT made.** Do not re-discover
these and "fix" them:

- `strip_legal_suffix` leaves a trailing comma, so 13 of 52 candidate names ever
  critiqued were searched as `"Tesla,"`, `"Amazon.com,"`, `"Applied Materials,"`.
  It costs nothing: 13% zero-article against 16% for clean phrases, and `"Tesla,"`
  returned six articles. The provider does not require the comma.
- `Massive` is chosen as a theme keyword for `Maruti Suzuki Massive Capex
  Expansion`. One theme in 126.

Both are real observations and neither changes an outcome. Entry 110 is different
because it is a mechanism rather than a correlation - `CORPORATION L` cannot
appear in prose.

---

## Still open, and needing a decision rather than a fix

**`evals.company_runner` against the buyer ceiling is still owed.** Unchanged
from the last handoff and still the honest gap: entry 106 is measured on one
frozen state, plus session 19's five live runs, which it graded defensibly in
every case. It also guards the other direction - a ceiling that is too aggressive
empties briefs, which is how entry 69 played out. ~28k tokens.

**A sub-penny share reached a low-risk brief - DECIDED in session 20, entry 118.
Recorded, nothing changed. Do not add a price floor.** Measured across every
recommendation the project has made: 54 of 67 carry a price and exactly two are
under one currency unit - the EUR 0.05 Energy holding, and **PowerBank at USD
0.38**, which entry 69 left as the single honest candidate of a renewables brief.
A floor would have deleted it. On this pipeline's data a price floor is not a
quality screen, it is a screen against small and foreign listings, which is the
class entries 53 and 60 were both about recovering.

What a reader would actually want is size or liquidity, and **the pipeline has no
volume or market-cap field anywhere**, on either provider path. That is a design
change with a threshold nobody can defend yet, not a fix. The absence is now
written down rather than closed.

**Entry 116, the possessive prefix.** Written up with the two defects above,
because that is where it was found. It is the cheapest open item to settle -
verifiable offline at zero model cost - and the riskiest to get wrong, because
it touches the resolution function every acronym in the project depends on.

**2.10's second half: making a failed run resumable.** Unchanged. It means
re-entering a completed thread, which changes what `--resume` and `--list` mean
for every run.

**Broad sector names research badly.** Settled in practice by the profile shape
above: plain name first, menu narrowing second.

---

## Quota, measured rather than estimated

Session 19's runs were **14:06-14:35 UTC on 2026-09-08** and the ceiling landed
at `Used 196148`. The window is a ROLLING 24 hours, so headroom returns across
that same span rather than at midnight. Six full runs plus the free audits was
that day.

**Session 20 spent 12 extraction calls and no news requests at all**, because
every measurement it made came out of the checkpoint. That is the pattern worth
copying: entry 69's replay costs one stage instead of twelve, removes retrieval
variance from a measurement that has nothing to do with retrieval, and compares
against a recorded result rather than a remembered one. The Basic Materials run
was NOT attempted - it needs ~13 news requests against 8 remaining, and unlike
the Groq ceiling a news shortfall is not free: the run would start, spend its
tokens on Agents 1 and 2, and die partway.

- **Do NOT probe for headroom.** Attempt the run; the 429 is free and states
  Limit, Used and Requested exactly. Entry 66 is the probe that could not fail.
- News is as tight as tokens: ~13 requests/run against 100/day, 25-30k tokens
  against 200k. Neither binds first; it flips with candidate count.
- Set `PYTHONIOENCODING=utf-8` before printing any run state on Windows.
- Persist before formatting: write the result to disk, then render it.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **1040 passed, 1 skipped** - 1041 collected, and the distinction matters
(entry 56). Counted at each session end: 760 after session 11, 797 after 12, 811
after 13, 816 after 14, 814 then 856 after 17, 1008 after 18, 1032 after
session 19, and 1040 after session 21, which added 12 tests for the truncation fix and its two mutations.

Suite time swung between 9s and 22s across runs today on an unchanged tree. Entry
34 is the reason not to chase that: six seconds of work once went into
investigating a regression that was one cold run against one warm one.

Do not add `-q`: pytest.ini already sets it, and `-qq` suppresses the summary
line, which is how a wrong count once survived for two sessions.

See the whole thing without spending quota:

```powershell
python -m cli --demo
python -m uvicorn web.app:app --port 8000     # ONE worker only
```

---

## What exists now that did not at v1.0.0

A web front end, built in the order the risk sat rather than the order it reads.

```
  web/app.py         one FastAPI app: run, resume, gallery, quota
  web/session.py     a signed cookie: which runs are yours to answer
  web/runqueue.py    one run at a time, with a position to report
  web/quota.py       how many runs are probably left today, said as an estimate
  web/static/        one page, no build step, no framework
  render.py          what a reader is TOLD, shared by the CLI and the web
  recordings.py      real runs the repository can carry
  scripts/record_run.py   writes one
  demo/gallery/      eleven of them
```

**`render.py` is the piece to understand first.** The CLI used to walk the models
and print in the same breath; a second front end would have been a second set of
decisions about what a reader is told. Content lives in `render.py`, layout stays
in the front end, and the test of the line is: if changing it would tell a reader
something DIFFERENT it is content, and if it only moves the words on the page it
is layout.

**Deploy with ONE worker.** The queue that stops two runs writing to one SQLite
file lives in a single process; two workers means two queues and the argument for
having one comes straight back. Set `WEB_SESSION_SECRET` (see `.env.example`) or
a restart stops visitors resuming a paused run.

---

## What is not written down

**The claim that used to sit here was itself stale, and session 20 checked it
rather than acting on it.** It said `README.md` and `docs/DESIGN.md` describe a
system with no web layer, that the README still calls the CLI "the only way a
person runs this", and that neither mentions the gallery. **All three are false
now** - `156fa87` and `2047762` fixed them at the end of session 18, and the
handoff carried the pre-fix description forward anyway. Entry 92 happening to
this file again, which is why line 1 says to run `git log` before trusting a
word of it.

What the public documents actually had wrong was smaller, and **all four are
FIXED in session 21**:

    README.md:109    "1008 passed, 1 skipped"   ->  1040   FIXED
    README.md:206    "1008 passed, 1 skipped"   ->  1040   FIXED, the check line
    README.md:346    "97 entries"               ->  118    FIXED
    docs/DESIGN.md:4 "97 entries"               ->  118    FIXED

**Line 206 was the one that mattered**, and it was entry 94 verbatim: a stale
number in the VERIFICATION INSTRUCTION, the line telling a returning reader what
a healthy suite looks like. Anybody following it would have run pytest, seen a
different number, and gone looking for what they broke. A stale number in a
check does not merely fail to inform; it manufactures a discrepancy in a system
that is fine. They were fixed in the same commit that moved the count, which is
the only discipline that keeps them true.

**And the README's limitations list is missing the three newest ones.** That
list is good and current through entry 91, which is what makes the gap easy to
miss. It does not carry entry 112 (a project vehicle can be recommended as a
company - the one that actually reaches a reader), entry 116, or entry 118 (no
size or liquidity notion anywhere in the pipeline). Entry 94's finding was that
a limitations list goes stale by things getting BETTER and nobody re-reading it;
this is the other direction.

---

## What session 18 found, in the pipeline rather than the web

Four defects, all found by running the thing rather than by any test, and each
one a shape this log already knew:

**A name the provider cut off.** yfinance's `shortName` is a fixed-width field at
31 characters. Agent 4 wraps the name in quotes to search, so a phrase ending
mid-word asks for something no article contains. Zero articles is zero risks is
`survives`, which reads as "we argued against this one and it held up" - and
selection PREFERS that verdict. **Session 19 found this again at THIRTY
characters; see entry 110 above.**

**A restriction matched by its words separately.** "No cryptocurrency or digital
asset companies" became `['cryptocurrency', 'digital', 'asset']`, and 'digital'
excluded a regional bank whose rationale said "digital transformation". Terms are
phrases now. The first draft of the fix was worse than the bug: putting
"investment" in the noise list turned "No investment banks" into "no banks".

**A timeframe that is only a number.** "8" could be months or years and nothing
downstream can tell. Refused now, while every real answer passes untouched.

**The verb in the article deciding who is a buyer.** Entry 69's ceiling said a
company qualifies if it is "producing, supplying or BUILDING", and its example of
a participant ended "or BUILDING the automation" - so "Walmart builds charging
stations" matched, and Walmart was recommended for Energy.
---

## 2. What the closing sessions did, kept for the arguments

Everything below is DONE and is here because the reasoning is the useful part.
It is not a task list; the current one is above.

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

### The exclusion check matches naive substrings - **OBSERVED AND FIXED**

Carried here for three sessions as "not yet observed". It was observed on
2026-09-07 (entry 104): "No cryptocurrency or digital asset companies" became
three separate terms, and 'digital' excluded a regional bank whose rationale said
"digital transformation". Terms are phrases now, split on commas, "or" and "and",
so "No coal, oil or gas" stays three prohibitions. Given up knowingly: a "digital
currency exchange" no longer matches a restriction written as "digital asset".

**This bullet is why entries 94 and 95 exist.** It sat in this file describing a
defect as hypothetical for a day after it had fired on a live run, been
diagnosed and been fixed - because nobody re-reads a limitation after fixing it.
The "What is NOT verified" section below had the correct account the whole time,
thirty lines away, and the two disagreed.

---

## What is NOT verified

Worth knowing before trusting a clean eval run.

- **`restriction_violation` fires, and fired WRONGLY the first time it did so
  unprompted.** Entry 91 verified it by substituting a restriction against real
  candidates: NVDA and 0981.HK excluded on industry "Semiconductors", Samsung
  and Alibaba kept. That was sound. Then on 2026-09-07 it fired on a live run
  nobody had arranged and excluded a regional bank, because "No cryptocurrency
  or digital asset companies" had become the single term 'digital'. Fixed, and
  re-verified in both directions against real candidates - but the lesson is
  that a gate verified by substitution had never met an unarranged input. It is
  rarely REACHED, because Agent 2 honours restrictions at query time, so it gets
  very little exercise per run.
- **The buyer ceiling is measured on one frozen state.** Walmart and Tesla move
  to `incidental_mention` and a genuine renewable utility does not, which is the
  right shape from one input. `evals.company_runner` is the fuller instrument
  and has not been run against it.
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
python -m cli --demo                    # a recorded run; no key, no network

python -m uvicorn web.app:app --port 8000    # the site; ONE worker only
python -m scripts.record_run --list          # runs that could join the gallery
python -m scripts.record_run <id> --to demo/gallery/<sector>.json

python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 1040 passed, 1 skipped; no network

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
- **News is as tight as tokens, which was not expected.** Counted from the
  provenance block across 16 full runs: 7 requests at the low end, ~13 typical,
  24 at the top. Against 100/day that is 7.7 runs; 25-30k tokens against 200k is
  7.4. NEITHER binds first - they land within one run of each other, and which
  one bites depends on how many candidates a run produces, because each costs
  two bear-case searches. `web/quota.py` carries the sums.
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
