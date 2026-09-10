# Start here — FRONTEND

The website: the page, the HTTP layer, the gallery and the deploy.
For the pipeline see [the backend handoff](../../backend/handoff/NEXT_SESSION.md).

**Written against `4aefc46`, 2026-09-10, during session 27.** Before
trusting a word of this:

```powershell
git log --oneline 4aefc46..HEAD
```

Thirty seconds, and it is here because of entry 92: session 15 opened a handoff,
believed it, and spent a stretch working on a project four sessions out of date.
**A handoff is a CLAIM about the repository, not the repository**, written by
somebody about to stop working who cannot describe what happens next.

- Repo: <https://github.com/patharearya/ai-investment-agent> (public, MIT)
- Live: <https://ai-investment-agent-gdjr.onrender.com> (Render free plan, ONE worker)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- Suite: **1089 passed, 1 skipped** — 1090 collected, and the distinction matters
- `docs/PROJECT_LOG.md` is current through entry **140**, 27 sessions

**The repository was restructured in session 22 into `backend/` and
`frontend/`.** Entry 123 records the old-to-new mapping. Every command changed:
`python -m backend.cli`, `python -m backend.evals.runner`,
`python -m uvicorn frontend.app:app`. Log entries written before that session
cite the OLD paths and are accurate as history.

## THE SITE IS LIVE

**https://ai-investment-agent-gdjr.onrender.com**

Deployed 2026-09-08 from `render.yaml` as a Render blueprint at `1320108`, on
the `patharearya` account. Verified against the real deployment: health, the
page, the quota estimate, all 11 gallery recordings, a full brief, the 8-field
form with its sector menu, and the traversal guard. Entry 122 has the numbers.

**The one thing NOT verified there is a real live run** - it costs ~28k tokens
and ~13 news requests, and Basic Materials has first claim on the next headroom.
The run path in production rests on 1062 local tests plus session 18's live runs
against the same code. That is good evidence and it is not the same thing. **It
is now the last genuinely unverified thing in this project.**

Session 20 spent no news requests and shipped no behaviour change; it answered
entry 112, and the answer was no. Session 21 deployed, moved the repository to
the professional account, and gave the deployment config the first tests it has
ever had. The suite is **1062 passed, 1 skipped**.

- Repo: <https://github.com/patharearya/ai-investment-agent> (public, MIT)
- Live: <https://ai-investment-agent-gdjr.onrender.com> (Render free plan, one worker)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- `docs/PROJECT_LOG.md` is current through entry **122**, 21 sessions
- Tagged **`v1.0.0`** at `48f9c08`, which the case study quotes

---

## DONE AND DEPLOYED — W1-W5, F1, F2 (2026-09-09)

Seven items across three commits, all live. Entries 127 and 128 have the
reasoning.

    W1  the CLI instruction is gone from what a browser visitor is told
    W2  the gallery one-way door is fixed - it has its OWN result area
    W3  three tabs on the location hash: Run it / Past runs / About
    W4  h1 scales up to 2.9rem, h2 bold rather than timid uppercase
    W5  copy saying switching tabs is fine, because it is
    F1  deep links - #gallery/technology opens that brief, Back closes it,
        and a link to a recording that no longer exists says so
    F2  four narrow-screen fixes: clamped headline, overflow-wrap, a grid
        that can shrink below its track, wrapping tabs

**The backend is PARKED by decision.** `backend/handoff/NEXT_SESSION.md`
carries its list; nothing there is a live defect a visitor meets. Do not start
on it unprompted.

---

## DONE IN SESSION 23 — F4 and F6 (2026-09-08)

Entry 130 has the reasoning. Both were free; neither spent a news request.

    F4  the in-run copy no longer overclaims - it says "keep this tab open"
        rather than "closing this tab loses nothing", which was true of the
        run and false for the reader
    F6  the design pass, all five asks: palette and frame, a banner with the
        title top-left and the tabs top-right, "Consumer Defensive" on one
        line, and a 72rem shell with the reading column still at 46rem

**Two corrections to what this file used to say**, both worth reading before
trusting the rest of it:

- **The browser is NOT without a resume path.** `GET /api/runs/{thread_id}`
  already returns the finished brief, gated on the session cookie. F4's third
  option - "give the page an actual resume-by-id path" - is a control that calls
  an endpoint that exists, not new server work. It is still undone, and it is
  cheaper than this file claimed.
- **The wide shell did not cost the briefs anything.** The trap was real but
  avoidable: only the PROSE containers keep 46rem, while the form and the
  gallery take the full 72rem. Prose and layout are different things, which is
  the line `render.py` already draws one level up.

**A test was rewritten, deliberately.** `test_the_disclaimer_sits_outside_the_tabs`
anchored on `<nav class="tabs">`; the banner moved the nav above the disclaimer
and the test failed while the disclaimer had not moved. It now anchors on the
tab panels - the thing that actually hides content - and asserts there is
exactly one disclaimer in the file. Stronger than what it replaced. Entry 130
explains why this is entry 125 in different clothes.

**A real browser drove the page for the first time** (Playwright, already in the
venv, against a local uvicorn). It found two things reading could not: the left
gutter spine was off the bottom of the screen, because the individual `rotate`
property composes BEFORE `transform`; and widening the panel let a 15rem sector
track fit four columns, which re-broke the examples. It also answered the
question the suite structurally cannot - 8 widths x 3 tabs, no horizontal
overflow anywhere.

Suite: 1062 passed to **1065**.

---

## THE AGENDA — what the website still owes

**THE LIST IS EMPTY.** Session 27 fixed the queue defect (entry 139) and built
resume-in-the-browser (entry 140), both from his ask rather than from a list,
and opened nothing. **What is left is not code:** two visitors in PRODUCTION,
which needs one real run's quota and a second person, and the paper's cover,
which only he can change.

F13 and F14 arrived and were closed the same session;
they are recorded at the bottom of this file rather than here, because a list
of done things is not an agenda. Session 24 closed F3 and F7-F12; he closed F5 himself on
2026-09-09 by opening the live site on his phone, which is the only instrument
that could answer it. **W1-W5 and F1-F12 are all done.** Nothing the website
owes is written down anywhere, so the next person to work on it is starting from
his next ask, not from this file.

    F3   DONE - one live run in production, five stages in 2m21s (entry 131)
    F7   DONE - stat tiles beside the intro, numbered 01-05 band (entry 132)
    F8   DONE - menus start blank, "Currency of that amount" -> "Currency"
    F9   DONE - the banner eyebrow is gone
    F10  DONE - blue and black, from the three sites he gave
    F11  DONE - the lede was DELETED, not moved; see below
    F12  DONE - the Consumer Defensive example shortened, all 11 rows one line
    F5   DONE - checked on his phone, it reads well (entry 133)
    F13  DONE - "How a run works" was on the page twice; About lost its copy
    F14  DONE - the About right column now shows the paper (entry 134)
    F15  DONE - the guard a rename had switched off (entry 135)
    F16  DONE - THE PAGE IS DARK NOW. Full redesign, entry 136

**Three things from session 24 worth carrying forward:**

- **A real browser is now part of how this project is checked.** Playwright is
  in the venv; `python -m uvicorn frontend.app:app --port 8321` plus a
  screenshot found two defects reading the CSS could not, and measured the
  sector rows rather than guessing at them. Reach for it before arguing about
  layout.
- **F11 was already done before anybody started it.** He asked for the
  narrowing advice to move closer to the sector question; it was already
  rendered directly under that question by `SECTOR_GUIDANCE`, so the fix was to
  delete the page's duplicate. Check what exists before moving anything.
- **`form_fields()` had no test at all** until F8 changed its contract. It has
  three now. Worth assuming other seams are equally bare.

**The site now has nothing unverified in production except two visitors at
once.** The queue was present during the live run and never stressed - depth 0
throughout - so concurrency is the one remaining gap, and the site has never
had two visitors.

**Session 27 found and fixed a real defect in exactly that gap (entry 139),
without needing two visitors to do it.** A visitor who closed the tab mid-run
released their place in line while the run carried on writing to the checkpoint
file, so the next arrival was let straight in on top of it - the two concurrent
writers `runqueue.py` exists to prevent. The place in line now belongs to the
RUN and not to the reader. It was found by measuring against a real uvicorn
server with the agents stubbed, which costs nothing, and that method is
available for the rest of the concurrency gap too. **Two visitors in
PRODUCTION is still unverified**, and one real run's quota is the floor for
checking it, because the second visitor has to have something to queue behind.

**F3. DONE in session 24 (2026-09-09) - it passed.** Five stages in 2m21s,
inside the 2-4 minutes the page promises; the brief rendered with citations two
days old and prices from the day of the run. The three keys work server-side,
the stream survived Render's proxy, the ledger incremented 1 to 2, and Agent 4's
source filter fired on live data for the first time (a press release withheld,
and a zerohedge.com article). Entry 131 has the timings and the run that was
thrown away before it. ~~The last genuinely unverified thing in the whole
project.~~ Everything else about the
website has now been checked in production - health, gallery, form, tabs, deep
links, the new page - and this has not. It is also the only path that spends a
visitor's share of the quota, so it is the one where a failure costs something.

What it proves that no local test can: the three keys work server-side, a 2-4
minute SSE stream survives Render's proxy (sse-starlette pings every 15s by
default, so it should), the queue behaves in a real process, and the runs-served
ledger increments. Open the site, fill the form, watch five stages land, read
the brief.

Costs a normal run: ~28k tokens and ~13 news requests. **Needs headroom** -
session 19's usage ages out of the rolling 24h window from about 14:00 UTC.

**F4. DONE in session 23.** ~~Two pieces of in-run copy that disagree with each other.~~ Found while
finishing F1 and not fixed, because it needs a decision rather than an edit:

    index.html:126   "Keep the page open to see the result."
    index.html:549   "saved as it goes, so closing this tab loses nothing."

Both are defensible and together they are confusing. The run genuinely IS
checkpointed, so nothing is lost from the SERVER's point of view - but **the
browser has no way to resume one.** `--resume <id>` exists in the CLI and
nothing in the page offers it, so a visitor who closes the tab has in fact lost
their brief. The second sentence overclaims for the reader it is shown to.

Three ways out, in increasing order of work: narrow the sentence to what is true
in a browser; show the run id as something a person could bring back; or give
the page an actual resume-by-id path, which the API already supports since the
id is emitted before the first model call is paid for. Free either way.

**F5. DONE 2026-09-09 - he checked it on his phone and it reads well.** (And
entry 138 proves the point harder than intended: he later found a broken
About layout on the same phone that every automated width check had called
fine. A person with the device is still the instrument.)
~~Open the live site on a phone.~~ It was never a coding task, and it was the
reason F2 was only half-checked: no browser runs in the test suite, so every F2
assertion says a CSS property is PRESENT, never that the result looks right. A
screenshot would have been a fifth assertion of that same kind. **The suite is
unchanged at 1070 - a human check produces no test**, which is the honest
outcome and not a gap to fill with one.

    https://ai-investment-agent-gdjr.onrender.com
**F6. DONE in session 23.** ~~A DESIGN PASS. His words after reviewing the live site: the tabs work and
the information is good, but "the website's design itself looks quite boring"
and it lacks enthusiasm.** Five specific asks, and two traps in delivering them.

*What he asked for:*

1. **More colour, and a border.** The palette is deliberately restrained -
   `--paper #faf8f5`, `--ink #1a1a1a`, one dark-green `--accent #1f4d3d`, serif
   throughout. It reads as a newspaper, which is defensible for a document and
   is not what he wants. Every colour is already a CSS custom property in one
   `:root` block, so a repalette is one edit rather than a hunt.
2. **A banner across the top**, with the title top-left in a big, good-looking
   font.
3. **The tabs moved into that banner, top-right**, smaller than the title but
   still styled - not the plain underlined row they are now.
4. **"Consumer Defensive" must sit on one line** like every other sector. See
   the diagnosis below; it is not a width problem in the way it looks.
5. **Use more of the screen.** `main { max-width: 46rem }` is 736px, so on a
   1920px display the content occupies about a third of it and the rest is
   background.

*The Consumer Defensive wrap, diagnosed rather than guessed:*

`.sectors label` is a flex row of three children - the checkbox, a bare `<span>`
with the sector name, and `<span class="eg">` with the example. **The name span
has no `flex` or `white-space` rule**, so when the row runs short of space the
name is what gives. "Consumer Defensive" is both the longest name AND has the
longest example ("food producers, household goods"), so that one cell is the
tightest in the grid and it is the only one that breaks. The fix is on the name
span - `flex: none; white-space: nowrap` - letting `.eg` absorb the pressure
instead. Widening the page would hide it without fixing it, and it would come
back on the next narrow viewport.

*Trap one: widening the page makes the BRIEFS worse if done bluntly.* 46rem is
roughly 90 characters, which is near the top of the comfortable range for
reading prose - and a brief is prose: a thesis, exit conditions, an explanation
of why nothing was recommended. Setting `main` to 1400px would make every one of
those lines materially harder to read while solving the complaint. **What he is
describing is a wide SHELL, not wide prose**: banner, tabs, the gallery cards
and the sector grid can all use the full width, while the reading column stays
constrained. Expect to widen `main` and add a narrower wrapper around the text,
rather than one number.

*Trap two: F2 just fixed four narrow-screen hazards, and this touches all of
them.* A banner with a title left and tabs right is a horizontal layout on a
page that currently has none; `white-space: nowrap` on sector names removes a
break point; a wider `main` changes nothing on a phone but a wider GRID does.
Whatever lands here has to be re-checked at 360px, and F5 is still the only
check that settles it.

---

## F7-F12 — ALL DONE IN SESSION 24 (2026-09-09)

**Kept in full below rather than deleted, because the reasoning is the useful
part and three of these were not what they looked like.** Entry 132 has the
narrative. What actually shipped, against what he asked for:

    F7   two-column intro row (tiles beside the prose, on every tab) plus a
         full-width numbered band; the tiles state four things that CANNOT
         drift, deliberately - a count would have gone stale
    F8   blank menus; `required` derived from the model annotation and shipped
         in /api/form, so an unanswered required question is blocked natively
         and costs no quota, and an optional one sends null rather than ""
    F9   done as asked
    F10  one :root edit; the interface went sans and the BRIEF stayed serif,
         which is a judgement call he accepted and is one line to reverse
    F11  DELETED rather than moved - the advice already sat where he wanted it
    F12  the example shortened, not the track widened; widening would have cost
         a column and undone F7

---

## THE ORIGINAL ASK, 2026-09-09

**Written from his own message and four screenshots at the end of session 23.
Nothing here was started.** He looked at the live site after F6 deployed and
asked for six more things. They are recorded before any of them was touched, so
what follows is his ask plus what reading the code says about it - not a plan
anybody has committed to.

**F7. The blank space, in three places.** F6 widened the shell to 72rem and kept
prose at 46rem, which is what stopped the briefs getting harder to read. The
cost is emptiness he does not want, and he pointed at three instances:

    run tab      under the three form columns, right of the sector grid
    gallery      right of the cards where the row does not fill
    about tab    the ENTIRE right column, which is the worst of the three

**His instruction, verbatim: "if we are not going to do anything about the extra
space outside the reading column then add some design in the white space to make
up for it. I want it to look creative and inspiring."** His own ideas: something
relating to stocks or investing, or "some fun catch phrases to make it more user
friendly", and he explicitly left the choice open.

The two gutter spines F6 added are the same instinct at a smaller scale and are
not what he means - they are outside `main`, in the viewport margins, and he is
pointing INSIDE the content shell. **Whatever lands here must not widen the
prose**, which is the constraint that produced the empty space in the first
place; the About tab is the hard case, because that column is empty precisely
because the tab is nothing but prose.

**F8. The dropdowns must not answer themselves, and one label is wrong.** A
`<select>` shows its first option, so the form arrives claiming the visitor is a
`beginner`, at `low` risk, holding `USD` - three answers nobody gave. He wants
them blank so the visitor has to open the menu and choose.

Two things to know before writing it, both checked in the code:

- **The options are DERIVED, not typed.** `backend/render.py` builds them with
  `get_args()` off the `Literal[...]` annotations in `models/user_input.py`, so a
  blank entry is an extra `<option>` the PAGE adds, never a model change. Do not
  add an empty string to the Literal.
- **Blank is not equally legal across the three.** `investment_currency` is
  annotated `Literal[...] | None` and is genuinely optional; experience and risk
  tolerance are not. `POST /api/runs` answers a `ValidationError` with **422**
  and `{"error": "invalid profile", "detail": ...}`, so an unanswered required
  menu has to be stopped at the form or land as a 422 the page renders usefully.
  **Which of those it is has not been decided, and the page's handling of that
  422 has not been read.**

He also wants **"Currency of that amount" renamed to just "Currency"**. That
string is at `backend/render.py:725`, not in the page - it is CONTENT by entry
98's test, and `render.py` is shared with the CLI, so **the rename changes what
the CLI prints too, and it crosses into the parked backend.** That is a small
edit with a decision attached, not a typo fix.

**F9. Delete the "FIVE AGENTS &middot; ONE BRIEF" eyebrow.** F6 added it above the
banner title; he does not want it. `.mark` in the stylesheet and the `<span>` in
the banner both go. Trivial, and no test asserts it.

**F10. Re-colour to BLUE AND BLACK.** F6's palette is deep green, rust and
amber, which he has now seen and does not want. Every colour is a custom
property in one `:root` block, which is what makes this one edit rather than a
hunt - but note that the amber and rust are load-bearing in more than the
background: the active tab underline, the `h2::after` rules, the `.lede` bar,
the `.card` left border and the disclaimer's top rule all read as accents. A
straight hue swap will flatten those unless the new scheme keeps a third colour
doing that job.

**Three sites he gave as inspiration, for the colour scheme and the layout:**

    https://racescout.ai/
    https://atonwebsites.com/
    https://561roofers.com/

**These were NOT opened in session 23.** They are his stated references,
recorded verbatim; nobody has characterised what is actually on them, so treat
the list as a starting point to look at rather than a description to build from.

**F11. The lede is in the wrong place - and it may not need moving so much as
deleting.** He does not like where *"Narrower questions research better. 'Grid
storage' produces a sharper answer than 'Utilities'..."* sits, and asked for it
"closer to that actual question".

**Read the sector field before moving it.** `SECTOR_GUIDANCE` at
`backend/render.py:662` is already *"Narrower researches better - 'grid storage'
beats 'utilities'."*, and it is already rendered as the help text directly under
"Which parts of the market interest you?" **The thing he is asking for largely
exists**, one line below where he wants it, and moving the lede down would put
two near-identical sentences next to each other.

So the honest options are: delete the lede and let the server-owned help text do
the job alone; or delete the help text and move the longer lede into its place,
which moves content OUT of `render.py` and away from the CLI. **Entry 83 is the
reason to be careful either way** - the sector examples and the narrowing advice
are the one piece of teaching this interface does, and it exists because a bare
menu of eleven broad sectors measurably made runs worse. Whatever happens here,
the advice has to survive it.

**F12. "Consumer Defensive" fits on one line now, and its EXAMPLE does not.**
He saw `Consumer Defensive  e.g. food producers, household goods` wrapping to
two lines and wants it on one.

**Read this before treating it as a regression: it is the F6 fix working as
designed.** That cell has always been the tightest in the grid. F6 decided WHICH
of the two halves gives - the handoff's own diagnosis was that the name had no
flex rule of its own, so the name was the child that broke - and pinned the name
with `flex: none; white-space: nowrap` so the example absorbs the pressure
instead. He is now asking for neither to give. **Reverting the F6 rule is not
the answer; that just moves the wrap back onto the name he asked to fix**, and
`test_the_sector_name_cannot_be_the_thing_that_gives` guards against exactly
that.

**Why it is only this one cell, measured rather than guessed.** Name plus
example, in characters, across all eleven sectors:

    49  Consumer Defensive      food producers, household goods
    42  Financial Services      regional banks, payments
    42  Industrials             aerospace, electrical equipment
    41  Consumer Cyclical       carmakers, online retail

**Consumer Defensive is seven characters clear of the field.** Everything else
already fits a 21rem track. This is one outlier, not a grid that is generally
too tight - which is what makes the cheapest fix a real option.

Four ways out, and they are not equally cheap:

- **Shorten that one example.** Seven characters brings it level with the pack -
  `food producers, household goods` to `food producers, toiletries`, say. It
  lives at `backend/render.py:641` in the `SECTORS` table, so it is CONTENT
  shared with the CLI and inside the parked backend, same crossing as F8's
  currency rename. **Read the `SECTORS` docstring first** - entry 83 is there,
  and it says the examples are the teaching this interface does, not decoration.
  Shorter must not mean vaguer.
- **Widen the sector track past 21rem.** Fixes it and costs a column - 3 columns
  becomes 2 - which puts width back into the blank space F7 exists to remove.
  These two items pull against each other; do not settle this one without
  looking at that one.
- **Give the example its own line for EVERY sector.** Ten cells on one line and
  one on two reads as broken; eleven cells on two lines reads as a pattern. Turns
  the raggedness into a layout decision instead of chasing a string length.
- **Shrink `.eg` below .8rem, or truncate with a title attribute.** Cheapest in
  CSS, worst for the thing the examples are for - a truncated example teaches
  nothing, and an unreadable one is not much better.

**It also may not survive F7 and F10 unchanged.** Both touch the panel this grid
sits in; a layout that changes the available width changes which cells fit.
Worth sequencing this after them rather than fixing it twice.

---

## RESUME IN THE BROWSER — BUILT in session 27 (entry 140)

**DONE.** A visitor who closes the page finds their run again when they come
back. `GET /api/runs` lists the runs the cookie already carried; the page shows
a card above the form offering to read a finished brief, answer a pending
question, or carry on a stopped run. `_EXECUTING` holds the thread ids running
in this process, so a run that is merely BUSY is reported `running` and is
never offered for resuming - and `/answer` refuses one with 409. `resumes_at`
comes from the graph's own `next`, so stages already paid for show as done
rather than as waiting. **"Keep this tab open" is gone**, which was the half of
F4 that stayed wrong.

Checked in a browser both ways (finish-and-read, and pause-answer-finish), on
WebKit at 390px with no overflow, and with zero elements at opacity 0 under
reduced motion. What follows is what was measured before building it, kept
because it is why the shape is what it is.

**Measured against a real uvicorn server over a real socket, with
the agents stubbed, for no quota:**

- A visitor who closes the tab leaves a run that **carries on to completion**
  and saves a full brief.
- `GET /api/runs/{id}` hands that brief back **with their cookie** (200) and
  404s without it. Ownership already works and needs nothing new.
- The page keeps the id in a plain JS variable and persists it nowhere, so the
  brief is reachable by the server and unreachable by the browser.

**The shape that fits: `GET /api/runs`, listing the visitor's own runs.** The
cookie already carries the ids (`session.read`), so nobody has to type or keep
one. Return status, sectors and time - not the brief. On load, offer a card:
finished -> read it, paused -> answer the question, stopped -> pick it up. The
click paths reuse `GET /api/runs/{id}` and `POST /api/runs/{id}/answer`
unchanged.

**A "paste your run id" box is strictly worse and was rejected on a
measurement.** Ownership is cookie-based, so an id pasted into another browser
404s. It only works when the cookie is there too - the case the listing handles
without asking anyone to copy a hex string.

**THE WRINKLE THAT WAS THE ACTUAL WORK, now handled.** A run still executing
reads as `('stopped', can_resume=True)` - *identical* to one that genuinely
died mid-stage. Offering "pick it up" on a live run would start a second
execution of the same thread. `_EXECUTING` in `frontend/app.py` is the
in-process set that answers it. **Do not remove it on the grounds that the
checkpoint file already says `can_resume`** - it does, and it is wrong about
exactly this case.

**And know what it buys before spending a session.** Render's free plan wipes
`.state/` - both `checkpoints.sqlite` and the ledger - on every redeploy and
every spin-down after 15 minutes idle. Recovery therefore covers "I closed the
tab / hit reload / my phone locked" inside one container lifetime, which is the
common case, and NOT "I came back tomorrow". Same ephemerality as the run
counter.

## PHONE LAYOUT IS CHECKED ON WEBKIT NOW (entry 138)

**An iPhone found a rule that had never applied.** `@media (max-width: 62rem)`
sat above `.about` and `.logcard` in the stylesheet, so at equal specificity the
wide-screen rule won and those two phone overrides were dead from the day they
were written. About kept a two-column grid on a 390px screen and hung the paper
card off the edge.

**Every responsive override now lives at the BOTTOM of the stylesheet**, after
the rules it overrides. `test_narrow_screen_rules_come_after_the_rules_they
_override` fails if a selector overridden in a `max-width` block is declared
again later. Keep new media rules down there.

**AND STOP MEASURING OVERFLOW ON CHROMIUM MOBILE EMULATION.** Session 26's "no
horizontal overflow at five widths" was green on a page that was visibly broken
on the device: Chromium widens its own viewport to swallow overflow, so
`scrollWidth > innerWidth` compared 414 to 414. WebKit kept the viewport at 390
and reported it. Both engines had the identical broken grid.

    python -m playwright install webkit     # installed 2026-09-09
    p.webkit.launch() + p.devices["iPhone 13"]

An iPhone is Safari. Check phone layout on WebKit, and compare against the
DEVICE width rather than `innerWidth`.

---

## THE RUN COUNTER READS HIGH, ON PURPOSE (entry 137)

**Do not "fix" the quota counter by rewriting quota.py.** It is correct.
`record()` is called at run start and `describe()` counts the ledger; what does
not survive is the FILE. Render's free plan replaces the container on every
deploy and on every spin-up after 15 minutes idle, so `.state/runs_served.json`
is thrown away - which is why the site read "About 7 runs left" after three
people had run it.

**The real fix costs money and is already written down.** `render.yaml` names
it: a persistent disk mounted at the `.state` path. Render allows disks only on
PAID instance types. He was offered it at $7/mo and chose instead to make the
sentence honest, on the argument that this number gates nobody - the 429 does,
exactly and for free - so a count that reads high is a labelling problem rather
than a spending one.

A disk would also make a paused clarification survive a redeploy, and keep the
checkpoints. **It is the first thing to buy if this ever gets real traffic.**

---

## THE DESIGN, AS IT STANDS AFTER SESSION 26 (entry 136)

**The page is dark, and it is not the blue-and-black of entry 132.** Ground
`#101423`, a blue-cyan-violet gradient as the single accent, and FOUR type
voices where there was one:

    Cormorant Garamond  headings only, 300, italic on the title's last word
                        and on every h2. Lifted from cielhomes.in exactly.
    Inter               anything read as a sentence
    JetBrains Mono      anything read as a token - labels, counts, ids, 01-05
    Georgia             the brief only

**The rule that came out of it: words are set in the fancy face, tokens are
not.** Cormorant draws its numeral 1 with no foot serif, so "15 pages" rendered
as "I5 pages" until every figure moved to the mono. Do not move them back.

**Motion is all decoration except the stage pulse**, and all of it dies under
`prefers-reduced-motion` - the check is that NO element is left at opacity 0
with the flag set. The cursor light and the card highlight are additionally
gated on `(hover: hover) and (pointer: fine)` and are never created on a touch
device.

**THE DROPDOWN FLASH IS KNOWN AND DELIBERATELY UNFIXED.** Selects flash white
for a frame when opened in Chrome. Three real causes were found and fixed
(no `color-scheme`, translucent controls, an animated focus background) and the
flash survived all three, because Chromium creates the popup as a separate
native window with a white surface before its first paint. **Do not spend a
session on this.** The only cure is a custom listbox, which costs free keyboard
and screen-reader behaviour and replaces the native picker on a phone with
something worse. He was shown the trade and chose to live with it.

**The lede and the stat tiles are on the RUN TAB ONLY.** They used to be on all
three and restated About's own first paragraph. The disclaimer stays outside
the tabs - `test_the_disclaimer_sits_outside_the_tabs` explains why, and it is
right.

---

## THE ABOUT TAB, AND THE TWO GUARDS IT ADDED (entry 134)

`/paper.pdf` and `/paper-p1.png` are two explicit routes, because this app
mounts no static directory - the page and those two assets are every file it
serves, which is also why no request path reaches the filesystem.

**If the paper is ever replaced, two things must be re-done or the suite
fails, by design:**

```powershell
python -m frontend.scripts.build_paper_preview   # re-renders page one + hash
# then update the page count in index.html, id="paper-pages"
```

The card's "15 pages" and the preview image are both hand-made COPIES of that
file - the failure mode `docs/project_log.html` and entry 132's rejected stat
tile are both about. The page-count test reads the PDF back; the preview test
compares a stored sha256. **The renderer (`pypdfium2`, Pillow) is deliberately
NOT in `requirements.txt`** - nothing at runtime rasterises anything, the same
standing Playwright has - so the hash guard is pure `hashlib` and still runs in
CI.

**The paper's own cover is a v1.0.0 document.** It cites
`github.com/AryaPathare/ai-investment-agent` and a 95-entry log; the repository
moved to `patharearya` in session 21 and the log is past 130. Nothing in the
site is wrong - the PDF says what it said when it was written - but it is the
first thing a visitor reads, and only he can change it.

**A dead test found on the way past, deliberately not fixed:**
`test_every_start_command_names_an_importable_app` filters for modules starting
with `web`, which session 22 renamed to `frontend`. It matches nothing now and
passes without asserting anything. One word to fix; it was not this session's
job.

---

## THE WEBSITE WORK LIST — agreed 2026-09-08, for session 22

Written down from his own list after the site went live. These are ordered by
what BLOCKS a visitor, not by how interesting they are. **All of it is free** -
no model calls, no news requests - so none of it competes with A0 or A1 for
quota. It can be done on a day with no headroom at all.

**W1. Drop the CLI instruction from the hint web visitors see.** `RATE_LIMIT_HINT`
in `render.py` ends *"Run `python -m backend.scripts.check_setup` to tell a configuration
problem from an outage."* That is useful in a terminal and useless in a browser -
it tells a stranger with no shell to run a command. It is also about to be the
most-read sentence on the site, because hitting the shared daily ceiling is what
usually ends a run and there is deliberately no global gate stopping anyone
starting one. Keep it for the CLI, drop it for the web. Needs a second constant
rather than a rewording, because both front ends read the same one today.

**W2. The gallery is a ONE-WAY DOOR - the first defect a user found on the
deployed site.** Click a recorded run and the live-run form disappears with no
way back; only a page reload escapes. The mechanism, confirmed in
`web/static/index.html` around line 517:

    const body = await (await fetch("/api/gallery/" + name)).json();
    $("intro").hidden = true;      // hides the live-run form
    $("progress").hidden = true;
    showBrief(body.brief);

`$("intro").hidden = true` is never undone. There is no back control, no
routing, and no history entry. **This is a symptom of W3 rather than a separate
bug**: the page is one screen whose sections are toggled by `hidden`, with no
navigation model, so every "go somewhere" is a one-way hide. Fixing W3 properly
fixes this; patching it alone would add a second ad-hoc path to the same tangle.

**W3. Restructure into tabs, with the live run as the landing page.** His layout,
as stated:

    Tab 1 (default)  A short description of what this is and what it does,
                     and BELOW it the live-run form.
    Tab 2            The gallery of recorded runs, readable by anyone whether
                     or not they ever start a run.
    Tab 3            Licensing, GitHub, and his own information.

**Four decisions to take before writing any of it:**

- **Hash routing, or show/hide only?** Show/hide alone leaves the browser Back
  button still broken and makes the gallery unlinkable - somebody cannot send a
  friend a link to a specific recorded brief. `#gallery`, `#about` and
  `#gallery/technology` are cheap and fix both. Recommended.
- **What happens to a RUN IN PROGRESS when a tab changes?** A run is a 2-4 minute
  SSE stream. If a visitor starts one and clicks Gallery, the stream must keep
  running and the progress must still be there on return. If it is not designed
  for, this becomes W2 again in a new costume - and it is worse, because the
  visitor has spent a share of a budget everybody else is sharing.
- **The DISCLAIMER must not move off the brief.** It renders with every brief
  today. An About tab can carry a fuller version, but a reader must never be able
  to see a recommendation without it. Adding a tab is exactly the kind of change
  that quietly relocates it.
- **Where does the intro copy live?** Entry 98's test is: if changing it would
  tell a reader something DIFFERENT it is content and belongs in `render.py`; if
  it only moves words on the page it is layout. A description of what the system
  does is content by that test. Against that: the CLI has its own opening and may
  not want the same words. Decide deliberately rather than by default.

**W4. A visual pass - bolder headers, bigger titles, more character.** The page
is deliberately plain: one file, no build step, no framework, and that should
stay - it is part of what the project demonstrates. What can change freely is
type scale, weight and rhythm. Today `h2` is `1.05rem`, uppercase, letter-spaced;
titles are barely larger than body text. Worth pairing with W3 rather than doing
separately, since tabs change the page's structure and the type scale should be
designed against the structure it actually has.

**W5. Text telling a visitor what to do while a run is going. HIS REQUEST WAS
"say that viewing the gallery will interrupt the run" - and that turns out not
to be true, so the wording is a decision rather than a transcription.**

Checked in `web/static/index.html` before writing it down: the run stream is
read with `fetch` and a `ReadableStream` (line ~229), NOT `EventSource` - a
deliberate choice, because starting a run is a POST and EventSource can only
GET. The reader therefore lives in JavaScript and keeps reading no matter which
DOM section is visible. **If W3's tabs are show/hide within one page, switching
to the gallery and back does not touch a running stream.** The only things that
break it are leaving the page: a reload, a navigation away, or closing the tab.

So there are two candidate texts and they are not equivalent:

    "Stay on this tab while a run is going or it will be interrupted."
        Untrue under show/hide tabs, and it is a label compensating for an
        architecture problem instead of fixing it - the shape session 1 dealt
        with when it DELETED a prompt rule that only existed to patch a schema
        flaw. It also discourages the gallery, which is the thing most visitors
        should look at while the seven daily runs are gone.

    "This takes 2-4 minutes. Keep this page open - closing or reloading it
     stops the run."
        True regardless of how the tabs are built, useful on its own, and it
        does not warn anybody off the gallery.

**Recommended: build W3 so a run survives a tab switch (nearly free given the
architecture above), and ship the second text.** Fall back to the first ONLY if
the tab implementation turns out to tear the reader down, and if it does, that
is a bug to fix rather than a caveat to publish.

Worth adding either way: a run that DOES get dropped is resumable. The run id is
emitted before the first model call is paid for, specifically so a client that
drops mid-run can pick it up - `--resume <id>` in the CLI, and the same id over
HTTP. Nothing in the browser surfaces that today, which is a small gap worth
closing while the page is being rebuilt anyway.

**One thing NOT to lose in W3 and W4.** The sector menu's narrowing examples -
`Utilities — e.g. solar, grid storage` - are the single most useful thing this
system knows about how to ask it, and entry 83 exists because a bare menu of
eleven broad sectors would have quietly made every run worse. They are served
from `/api/form`. A redesign that tidies them away as clutter would remove the
one piece of teaching the interface does.

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
  shared/gallery/      eleven of them
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

