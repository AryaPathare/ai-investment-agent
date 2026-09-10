# Start here

The handoff is split in two, because it had grown to 1,130 lines covering a
research pipeline and a website that share almost no decisions.

| | |
|---|---|
| **[backend/handoff/NEXT_SESSION.md](backend/handoff/NEXT_SESSION.md)** | The pipeline. Agents, models, evals, quota, the graph, and every task that costs an API call. |
| **[frontend/handoff/NEXT_SESSION.md](frontend/handoff/NEXT_SESSION.md)** | The website. The page, the HTTP layer, the gallery, the deploy, and the W1-W5 work list. |

**Before trusting a word of either:**

```powershell
git log --oneline 4aefc46..HEAD
```

Thirty seconds. It is here because of entry 92: session 15 opened a handoff,
believed it, and spent a stretch working on a project four sessions out of date -
planning work that was already done, and coming one command away from reverting
a prompt section that four sessions of evals had since been run against. Two
signals were available and neither was used.

**A handoff is a CLAIM about the repository, not the repository.** It is written
by somebody who is about to stop working and cannot describe what happens next.

---

## Where things stand, 2026-09-10

- Repo: <https://github.com/patharearya/ai-investment-agent> (public, MIT)
- **Live: <https://ai-investment-agent-gdjr.onrender.com>** — Render free plan, ONE worker
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- Suite: **1092 passed, 1 skipped**, 1093 collected
- `docs/PROJECT_LOG.md` current through entry **142**, 27 sessions
- Tagged `v1.0.0` at `48f9c08`, which the case study quotes

**The repository was restructured in session 22** into `backend/` and
`frontend/`. Entry 123 records the mapping, and why the saved-run database had
to be migrated rather than abandoned. Every command changed:

```powershell
python -m backend.cli --demo
python -m backend.evals.runner --tag hard
python -m uvicorn frontend.app:app --port 8000     # ONE worker only
python -m pytest
```

Log entries written before session 22 cite the OLD paths. They are accurate as
history and are deliberately not rewritten - the same decision entry 40 took
when a history rewrite changed every commit SHA.

---

## The one thing to do first

**The backend is PARKED** (decided 2026-09-09). It works, it is verified against
its own evals, and its list is kept in
[backend/handoff/NEXT_SESSION.md](backend/handoff/NEXT_SESSION.md) for if it is
ever picked up again. Nothing there is a live defect a visitor meets. Do not
start on it unprompted.

**The website's agenda is EMPTY too, and that is not the same as parked.**
W1-W5 and F1-F16 are all done and deployed. Sessions 23-26 closed the last of
them, and he closed F5 himself by opening the live site on his phone - still the
only instrument that could answer it. The list lives in
[frontend/handoff/NEXT_SESSION.md](frontend/handoff/NEXT_SESSION.md), which now
opens by saying it is empty. **The next website work starts from his next ask,
not from a file.** Do not go hunting for open items to fill the gap.

One thing is known to remain, and it is not code. Nothing here is an agenda:

| | | |
|---|---|---|
| **Two visitors at once** | STILL unverified. Tried on 2026-09-10 and it did not test the queue - the first run died after 29s, so the line was empty before the second started (entry 142). It did find a real defect. **Retry: fill the second device's form in advance and start within ~10s.** | one real run's quota is the floor |
| ~~The paper's cover~~ | **DONE, entry 141.** It credits `patharearya` now, and carries a new section on the four external services. v1.0.0/95 were correct all along and were left alone. | done |
| ~~Resume in the browser~~ | **DONE, entry 140.** `GET /api/runs` lists what the cookie already carried; a card above the form offers to read, answer or carry on. `_EXECUTING` stops a run that is merely busy being offered for resuming. | done |

**Two things are decided and should not be reopened.** The run counter reads
high because Render's free plan throws `.state/` away on every deploy and every
spin-down after 15 minutes idle - `quota.py` is correct, the only fix is a paid
disk, and he chose to make the sentence honest instead (entry 137). And the
Chrome dropdown flash is WON'T-FIX: three real causes were found and fixed and
it survived all three, because Chromium builds the popup as a separate native
window painted before its first paint, outside CSS reach (entry 136).
