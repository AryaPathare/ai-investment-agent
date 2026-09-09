# Start here

The handoff is split in two, because it had grown to 1,130 lines covering a
research pipeline and a website that share almost no decisions.

| | |
|---|---|
| **[backend/handoff/NEXT_SESSION.md](backend/handoff/NEXT_SESSION.md)** | The pipeline. Agents, models, evals, quota, the graph, and every task that costs an API call. |
| **[frontend/handoff/NEXT_SESSION.md](frontend/handoff/NEXT_SESSION.md)** | The website. The page, the HTTP layer, the gallery, the deploy, and the W1-W5 work list. |

**Before trusting a word of either:**

```powershell
git log --oneline 4c1e052..HEAD
```

Thirty seconds. It is here because of entry 92: session 15 opened a handoff,
believed it, and spent a stretch working on a project four sessions out of date -
planning work that was already done, and coming one command away from reverting
a prompt section that four sessions of evals had since been run against. Two
signals were available and neither was used.

**A handoff is a CLAIM about the repository, not the repository.** It is written
by somebody who is about to stop working and cannot describe what happens next.

---

## Where things stand, 2026-09-09

- Repo: <https://github.com/patharearya/ai-investment-agent> (public, MIT)
- **Live: <https://ai-investment-agent-gdjr.onrender.com>** — Render free plan, ONE worker
- CI: green on ubuntu-latest and windows-latest, Python 3.14, no secrets
- Suite: **1062 passed, 1 skipped**, 1063 collected
- `docs/PROJECT_LOG.md` current through entry **129**, 22 sessions
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

**The website is the focus, and its agenda is F3-F5** in
[frontend/handoff/NEXT_SESSION.md](frontend/handoff/NEXT_SESSION.md):

| | | |
|---|---|---|
| **F3** | One live run against the deployed site | needs quota, ~14:00 UTC |
| **F4** | Two pieces of in-run copy that contradict each other | free, needs a decision |
| **F5** | Open the live site on a phone | ten seconds, and the only thing that settles F2 |
| **F6** | A design pass — banner, colour, wider layout | free, and the biggest visible change |

W1-W5, F1 and F2 are done and deployed. Entries 127 and 128 have the reasoning.
