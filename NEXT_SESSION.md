# Start here

Last worked: **2026-08-22**. **Agents 1, 2 and 3 are built and verified.**
Agent 3 was finished this session: its eval baseline ran, found four defects, all
four were fixed, and every post-fix run reported **0 hard failures**.

`docs/PROJECT_LOG.md` is up to date through Session 2.

Nothing is committed. `git status` shows the changeset.

---

## 1. Check the environment

```powershell
python -m scripts.check_setup
python -m pytest
```

Expect **276 passed** in about 2 seconds.

---

## 2. THE TASK — Agent 4, the Risk Critic

Consumes Agent 3's `CompanyFindings` and attacks the thesis: assume the earlier
agents are wrong and find the reasons each company could fail.

**Needs no new API key**, but it DOES need news-API budget. See the scope note.

Do the **planning and groundwork first**, the way Agents 2 and 3 were built. No
code until the shape is agreed.

### The decision already made — do not re-litigate

Agent 2 has recorded a dissenting stance (`weakens` / `complicates`) exactly
**once, ever**. The obvious move is to go and fix Agent 2. **That was
investigated on 2026-08-22 and rejected**, because the cause is not the prompt,
which is already explicit and well argued. It is structural:

| Profile (2026-08-20 run) | Themes | Single-source | Avg citations/theme | Dissent |
|---|---|---|---|---|
| renewables | 4 | 3 | 1.25 | 0 |
| healthcare | 2 | 2 | 1.00 | 0 |
| sports | 2 | 1 | 2.00 | 0 |
| semiconductors | 5 | 2 | 1.60 | 0 |
| banking | 5 | 5 | 1.00 | 0 |

1. **A theme with one citation cannot record dissent** — there is no second
   article to disagree. Most themes have exactly one, so the dissent rate is not
   low, it is arithmetically unavailable. The single time dissent ever appeared
   was in the profile with the highest average citations (1.75).
2. **Themes are derived from their own evidence.** Agent 2 reads articles and
   names the pattern it sees; a contradicting article becomes a DIFFERENT theme
   rather than dissent within this one.

Underneath both: TheNewsAPI's free tier returns **3 articles per request**, so the
corpus is only 2-5 articles per profile.

**So: Agent 4 retrieves its own counter-evidence.** For each candidate, query
specifically for the bear case (`"<theme> delay"`, `"<theme> falls"`,
`"<company> regulatory"`, `"<company> lawsuit"`), then reason over what comes
back. A risk critic that depends on the researcher having already been
self-critical is not much of a critic — finding counter-evidence IS the job.

This reuses the news client, caching and citation-grounding that already exist
and are tested.

### Scope note

This makes Agent 4 **retrieve, then reason** — closer in size to Agent 2 than to
a pure reasoning step. Budget news-API requests accordingly (100/day, 3 articles
per request).

### Worth settling before writing code

- What does Agent 4 OUTPUT? A risk per candidate, a revised score, or a veto?
  Agent 5 (Decide) consumes it, so the contract matters.
- Does a candidate that survives criticism get promoted, or only demoted? A critic
  that can only subtract will drive every score toward zero over time.
- How is a risk that is real but already priced in handled? "This stock could
  fall" is not a finding.
- Same grounding rule as Agent 2: every risk must cite a retrieved article, or it
  is the model inventing a bear case from training data.

---

## 3. Then Agent 5 — Decide

Score, select up to three, state exit conditions, or recommend **nothing**.
Recommending nothing must remain a first-class outcome.

---

## What was done in Session 2 (2026-08-21 → 22)

Full detail is in `docs/PROJECT_LOG.md` sections 8-15. Summary:

Agent 3's eval baseline reported **0 hard failures** and four real defects were
found anyway — all of them in the soft signals, none caught by the 267 unit tests
that were passing throughout. **The unit tests prove the code does what it says;
only the evals show whether what it says is right.**

1. **`currency` meant two different things** — FMP set it from the statements,
   yfinance from the share price. SK hynix's 162 trillion won of net income was
   labelled USD. Corrupted nothing (all screening metrics are ratios, which are
   currency-invariant) but Agent 4 consumes the field.
2. **The ranking could not separate its top two** — TSMC and SK hynix both maxed
   every component and tied at 1.000 despite an eight-fold growth difference.
   Caps raised to 50% / 40% / 75%; the tie broke, order preserved exactly.
3. **A provider `0.0` was read as "terrible"** — banks have no cost of goods,
   pre-revenue biotechs no revenue. A healthcare run recommended two biotechs
   scoring **0.000** to a 66-year-old with low risk tolerance.
4. **The disqualifying screen was defeated by missing data** — it rejected on
   *shrinking AND unprofitable*, and a conjunction cannot fire when one side is
   missing. CervoMed passed while losing 94x its revenue.

Two eval checks were added: exclusion compliance (hard) and a growth sanity
ceiling (soft). **267 tests became 276.**

### Two known limits — SETTLED as documented, do not reopen

Written up in the module docstring of `agents/screening.py`. Both distort
absolute scores; neither distorts an ordering anyone consumes.

- **SK hynix still scores exactly 1.000.** Saturation mattered because it caused a
  TIE; raising the caps fixed that. One company at 1.000 is ranked first, correctly.
- **Financial companies cap at 0.50.** At most 2 of 4 metrics exist for a bank and
  score multiplies by completeness. Verified across ten major banks: all sit at
  exactly 0.50 and are KEPT, so this is a ceiling, not a rejection.

---

## Commands

```powershell
python -m scripts.check_setup           # health check - run this first when stuck
python -m pytest                        # 276 tests, ~2s, no network

python -m evals.runner                  # Agent 1: 18 labelled cases
python -m evals.research_runner         # Agent 2: process quality, 5 profiles
python -m evals.company_runner          # Agent 3: process quality, runs 2 -> 3
python -m evals.company_runner --case <name>   # one profile, to conserve quota
```

---

## Known limits that will bite

- **Groq's daily ceiling is the binding constraint, and a profile costs far more
  than it looks.** A full profile through Agents 2-3 costs roughly **25-30k
  tokens**, NOT the ~6k previously documented. Trusting that wrong figure caused a
  bad estimate: the budget was thought 30% spent when it was 99% spent, and a
  five-profile run died after one case. **Budget ~6-7 profiles per day, total**,
  and expect Agent 4 to raise the per-profile cost. Measure, do not extrapolate.
  The ceiling is a rolling 24-hour window, not a midnight reset.
- **FMP free tier**: 250 requests/day, covers only a *subset* of US symbols. Of 5
  US-listed candidates measured, FMP served 2 and refused 3 — the yfinance
  fallback is doing real work, so a low `fmp` count is not a bug.
- **TheNewsAPI free tier**: 100 requests/day, 3 articles per request. This is the
  constraint that shapes Agent 4.
- **Run-to-run variance is large.** Agent 2 retrieves different articles each run,
  so candidate SETS differ and aggregate counts are not comparable between runs.
  Compare companies appearing in both. One banking run resolved only 3 of 7
  mentions and returned zero candidates — legitimate, but it means a single run
  proves less than it appears to.

Caching is on by default everywhere, which is what makes development affordable.

---

## Still deferred (not blocking)

- **No CLI.** There is no way for a person to run this pipeline — only Python
  snippets. Worth building; it is also what makes the project demonstrable.
- **`InMemorySaver`** loses all state on restart, including a user mid
  clarification. Needs `SqliteSaver` before any real use.
- **Agent 1's eval set scores 100%**, so it catches regressions but cannot show
  improvement.
- **The exclusion check matches naive substrings**, so a rationale reading "no
  crypto exposure" would register as a violation. Consistent with how Agent 2
  already checks themes. Not yet observed; narrow it in one place for both agents
  if it fires falsely.
