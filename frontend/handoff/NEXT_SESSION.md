# Start here — FRONTEND

The website: the page, the HTTP layer, the gallery and the deploy.
For the pipeline see [the backend handoff](../../backend/handoff/NEXT_SESSION.md).

**Written against `4c1e052`, 2026-09-09, at the end of session 22.** Before
trusting a word of this:

```powershell
git log --oneline 4c1e052..HEAD
```

Thirty seconds, and it is here because of entry 92: session 15 opened a handoff,
believed it, and spent a stretch working on a project four sessions out of date.
**A handoff is a CLAIM about the repository, not the repository**, written by
somebody about to stop working who cannot describe what happens next.

- Repo: <https://github.com/patharearya/ai-investment-agent> (public, MIT)
- Live: <https://ai-investment-agent-gdjr.onrender.com> (Render free plan, ONE worker)
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- Suite: **1062 passed, 1 skipped** — 1063 collected, and the distinction matters
- `docs/PROJECT_LOG.md` is current through entry **129**, 22 sessions

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

## THE AGENDA — what the website still owes

**F3. One live run against the DEPLOYED site, start to finish.** The last
genuinely unverified thing in the whole project. Everything else about the
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

**F4. Two pieces of in-run copy that disagree with each other.** Found while
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

**F5. Open the live site on a phone.** Not a coding task and the reason F2 is
only half-checked. No browser runs in the test suite, so every F2 assertion says
a CSS property is PRESENT, never that the result looks right. The four known
hazards are guarded and the layout is fluid; whether it actually reads well on a
360px screen is unknown and takes ten seconds to find out.

    https://ai-investment-agent-gdjr.onrender.com
**F6. A DESIGN PASS. His words after reviewing the live site: the tabs work and
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

