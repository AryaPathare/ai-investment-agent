# Design notes

The reasoning behind the build, and an honest account of what it still gets
wrong. [`PROJECT_LOG.md`](PROJECT_LOG.md) is the narrative version — 72 entries
of what broke and why the first diagnosis was usually wrong.

---

## Design decisions worth knowing

**LLMs judge; Python computes.** Anything calculable or checkable in code stays
in code. A negative investment amount is rejected by Pydantic, not reasoned
about by a model. Models are used only where genuine ambiguity requires
judgment.

**The model returns a verdict, not your data.** Agent 1 emits a
`ProfileAssessment` — a status, a reason, and a narrow whitelist of fields a
clarification may revise. Python assembles the final `InvestorProfile` by
copying everything else from the user's own validated input. The model has no
channel through which to alter an age or an amount.

**LLM output is untrusted input.** It steers control flow, so it is validated as
strictly as anything arriving from outside. `ProfileAssessment` rejects
incoherent combinations, such as "needs clarification" with no reason given.

**Every loop is bounded by code, never by the model.** The clarification cycle
stops after a configured number of attempts and records why it gave up. A model
is never trusted to decide when to stop looping.

**Failures end the workflow cleanly.** When a model call fails after its
retries, the graph records a readable `error` in state instead of raising. If
`error` is set, `investor_profile` must not be used downstream.

**One retry layer, not two.** The Groq client already retries with exponential
backoff, so LangGraph's node-level `retry_policy` is deliberately unused —
stacking them would multiply attempts against an API that is rate-limiting you.

**Search first, then synthesise.** Agent 2 never asks the model what trends
matter and then hunts for support — that is confirmation bias with a training
cutoff attached. It retrieves real articles first and asks the model to read
them. Every theme must cite at least one retrieved article, and `Evidence` has
no field for a title or URL, so fabricating a source is impossible rather than
discouraged. Citations use short labels the model can copy reliably; Python maps
them back to real ids and discards any that do not exist.

**Token budgets are per call, not global.** Groq charges `max_tokens` against
the tokens-per-minute quota whether or not it is used, so one value big enough
for the largest call makes every small call expensive. `gpt-oss-20b` is also a
reasoning model, spending tokens before the visible answer, so budgets must be
larger than the output length suggests.

**The model never writes a ticker.** Agent 3 extracts company *names* as
articles write them; tickers come from a market database and are verified.
`NVDA`, `NVDA.NE` and `NVD.DE` are all real symbols for Nvidia, so a guessed one
does not look wrong — it silently returns a different company's financials.
Resolution scores candidates rather than taking the first result, because search
relevance is not ours: "Pfizer" returns Germany first and Argentina second.

**Ranking is arithmetic, not a model's opinion.** Screening and scoring run in
pure Python over provider figures. The model supplies exactly one input — whether
a company is `direct`, `partial` or `incidental` to a theme. A model asked to
score a company 0-100 returns 72 with nothing behind it: not reproducible, not
comparable, not explainable.

**Comparable ratios and currency amounts are separate types.** Fundamentals
arrive in local currency, and GBp is *pence*. Ranking touches `ComparableMetrics`
(all unitless); `CurrencyAmounts` is display only. Reaching the wrong one means
crossing a type boundary rather than ignoring a comment.

**What gets filtered out is reported, not silently dropped.** Two filters sit in
front of the risk critic: one removes publishers that do no original reporting,
the other removes press releases, which are the company describing itself and
the most confirmatory input an agent arguing the bear case could be handed. Both
report what they withheld, because "no risks found" means something different
when four of twelve articles never reached the model. Both are also deliberately
cautious in the same direction — a press release slipping through costs a
mediocre input, while removing "Regulator announces probe" defeats the agent, so
anything ambiguous is kept.

**An exit condition must be checkable, or it does not ship.** Every condition
Agent 5 writes has to cite an article it was actually shown or name a measured
metric; anything grounded in neither is discarded, and the discards are counted.
The counting matters more than the discarding — "monitor the competitive
landscape" reads like prudence and means nothing, and a brief full of metric
thresholds reads identically for any company in any sector. The count is what
makes that visible.

**Rejections are recorded, never discarded.** `drop_summary` says where every
examined company went. "3 candidates from 30 mentions" is either good filtering
or a broken resolver, and those look identical without it — it caught three real
bugs on its first live run.

---

---

## Known limitations

Ordered by how much each would change an answer a reader actually sees. Every
one of these was measured rather than guessed at; where something was fixed,
`docs/PROJECT_LOG.md` records what the fix cost and what it revealed.

- **Agent 3 only reads the articles Agent 2 chose to cite.**
  `ResearchFindings.articles` keeps the articles a *theme* cited, and company
  extraction reads that list — so retrieval feeds the residue of a decision made
  one stage earlier for a different purpose. Two live runs on 2026-08-26: 9
  retrieved became 3, and 17 became 5. Most themes cite exactly one article and
  there is a five-theme cap, so the pool reaching Agent 3 is capped near five
  however many were retrieved. In a rich sector this costs nothing; in a thin
  one it empties the brief. **The one open defect**, and it needs a design
  decision rather than an edit.
- **A failure in the LAST agent cannot be resumed.** The graph records the
  error in state and finishes cleanly, by design, so a traceback never reaches a
  reader - but `--resume` then sees a completed run, and the four stages already
  paid for cannot be continued from the CLI. Recoverable by replaying `decide()`
  over the checkpoint by hand. Ending cleanly and being recoverable turn out to
  be different properties.
- **No forecast, and that is deliberate.** Nothing here predicts a price, names
  a sell date or says how much to invest. There is no valuation model, no price
  target and no expected-return estimate, so any of those would be the only
  figure in the output citing nothing. The exit conditions are the sell signal,
  and they are event-based rather than dated.
- **The share count is often absent.** It needs a price, a stated investor
  currency, and a match between that and the share's. No exchange rate is
  invented, and 39 of 48 cached companies trade in USD - so a reader who says
  GBP will usually see a price and no count. A missing line was preferred to a
  figure that is quietly wrong by a quarter.
- **The renewables brief is thin, and honestly so.** Of roughly ten companies
  examined for that profile, about three are investable — renewable-energy news
  is dominated by private and foreign firms. Now that loose exposure is graded
  out (below), a reader can get a one-company brief. That is the correct
  output, but it is a thin one, and no prompt fixes it.
- **Agent 2 rarely records dissenting evidence.** Across the baseline, 0 of 5
  profiles produced a single `weakens` or `complicates` stance. Structural
  rather than a prompt problem — most themes cite one article, and one article
  cannot disagree with itself. Worked around by giving Agent 4 its own
  adversarial retrieval, which makes that workaround load-bearing: if those
  bear queries stop returning anything, this comes back with nothing behind it.
  **Accepted deliberately.**
- **The source filter cannot cover its long tail.** Audited against 272 cached
  articles from 130 sources: 86 of those sources contributed exactly one
  article. A list of publisher names cannot cover a distribution whose mode is
  one, and both alternatives were tried and failed on real data — provider
  categories put a private-equity acquisition in the same bucket as everything
  uncategorised, and query-term matching cannot tell a lithium battery deal
  from a battery-storage company. What carries the weight instead is a filter
  on article *shape* rather than publisher. **Accepted deliberately.**
- **Most Agent 2 themes cite one source** (13 of 18 in the baseline), and it
  reaches the five-theme cap on well-covered sectors.
- **Ranking saturates, and financial companies are capped.** A company beyond
  every cap scores a flat 1.000, so exceptional companies are not distinguishable
  from each other; banks have no cost of goods, so their completeness caps at
  0.50. Both are measured and accepted — they distort absolute scores without
  changing any ordering that gets consumed. See `agents/screening.py`.
- **Ticker resolution can be flaky between runs.** Provider search results vary
  over time for short ambiguous names. The system degrades safely — it records a
  drop reason rather than picking the wrong company.
- **`openai/gpt-oss-20b` is unevaluated against alternatives.** Now that the
  eval set exists, comparing a larger model is a measurable question.

### Not yet verified

Distinct from the above: these are not known to be wrong, they are simply
untested against the live pipeline.

- **Two of the four exclusion reasons have never fired.** A live run on
  2026-08-26 populated `Decision.excluded` for the first time — six candidates,
  three recommended — but only with `outside_top_three` and `not_critiqued`.
  Nothing has yet been excluded for `restriction_violation` or
  `disqualified_by_risk`, which are the two that matter, and those still have
  unit tests only.
- **The 12 hard Agent 1 cases no longer discriminate.** They score 12/12, and
  the rubric written alongside them says 8–10 is a good hard set and 12 means
  it is too easy. Fixing the defect the set was built to catch spent its
  margin. The score is no longer evidence about Agent 1 until harder cases
  exist.

### Fixed, and how it was found

Three things that were on this list are not any more. Each is worth reading in
`docs/PROJECT_LOG.md`, because in every case the first diagnosis was wrong:

- **Agent 3 grading data-centre operators as *direct* exposure** — Google and
  Amazon were recommended for a renewables profile because both buy battery
  storage. Now graded `incidental_mention` and dropped, on the test of which
  way the money flows.
- **Agent 5 barely reading the articles** — 1 of 8 exit conditions cited one,
  which was read for weeks as the model taking the cheap option. It was not: it
  had never been given the articles. Cited equalled citable on every candidate.
  On identical inputs the rate is now 3 of 7, and what the new conditions
  displaced was boilerplate.
- **A live end-to-end CLI run, and the Agent 1 and Agent 3 evals** — all three
  were owed and all three have now run against the real model.

---

## Optional: tracing

Setting these in `.env` records every prompt, response, latency and token count
to a web UI, which is worth a lot once several agents are chained:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<from https://smith.langchain.com>
LANGSMITH_PROJECT=ai-investment-agent
```
