"""Which runs this visitor started, carried in a signed cookie.

WHAT THIS IS FOR

The clarification interrupt splits one run across two requests: the graph pauses
mid-run to ask a question, and the answer arrives later. Something has to say
which thread that answer belongs to, and - the part that is not obvious - which
threads this particular visitor is allowed to answer at all.

Without the second half, a thread id is a bearer token that anybody can guess or
copy. Answering somebody else's clarification is not a dramatic attack, but it
does mean feeding a stranger's words into an agent that is deciding what to
research on their behalf, and the answer would be indistinguishable from theirs.

SIGNED, NOT ENCRYPTED, AND NOT STORED

The cookie carries the thread ids in the clear with an HMAC over them. Three
consequences, all deliberate:

* Ids are not secret - they already travel in the stream, and the CLI prints
  them - so hiding them buys nothing. Being unable to FORGE one is the property
  that matters.
* There is no server-side session table. Nothing to grow without bound, nothing
  to clean up, and a restart does not strand a visitor mid-clarification as long
  as the secret is configured.
* A tampered or stale cookie is treated as "no session", never as an error. The
  visitor loses the ability to resume, which is recoverable; the alternative is
  a page that refuses to load because of a cookie they cannot see or clear.

Set ``WEB_SESSION_SECRET`` for any deployment. Unset, the server generates one
per process: fine for local work, and it means a restart stops visitors resuming
a paused run. The RUNS are unaffected either way - they are in the checkpoint
database, and `python -m cli --resume <id>` still picks any of them up.
"""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from config import get_settings

COOKIE_NAME = "investment_runs"

RUNS_PER_VISITOR_PER_DAY = 1
"""How many runs one visitor may start in a rolling day.

A full run is 25-30k tokens against a 200k daily ceiling shared by everybody, so
one bored person clicking repeatedly is the whole budget in a quarter of an hour
- and every later visitor then meets an empty site.

This is a speed bump and not a security control. A cookie can be cleared, and
clearing it buys another run. That is accepted: the honest gates are the queue,
which stops runs happening at once, and the provider's own refusal, which costs
nothing. This one exists to make casual repetition inconvenient rather than to
make it impossible, and pretending otherwise would be the kind of claim this
project keeps having to walk back.
"""

VISITOR_WINDOW = timedelta(hours=24)
"""Rolling, to match the provider's own window rather than a calendar day."""

MAX_THREADS = 20
"""How many run ids a cookie will carry.

A cookie is capped at about 4KB by every browser, and a visitor with an
unbounded history would eventually hit that and lose the whole session rather
than the oldest part of it. Oldest are dropped first.
"""

_FALLBACK_SECRET = secrets.token_bytes(32)
"""Used when nothing is configured. Regenerated every process, on purpose.

A hard-coded default would be worse than useless: it would look like a secret
while being public, and every deployment that forgot to set one would share it.
"""


def _secret() -> bytes:
    configured = get_settings().web_session_secret
    if configured is None:
        return _FALLBACK_SECRET
    return configured.get_secret_value().encode("utf-8")


def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_secret(), payload, hashlib.sha256).digest()
    ).decode("ascii")


def _verified(cookie: str | None):
    """The payload this cookie carries, or None if it is not ours.

    Every failure - absent, malformed, wrong signature, wrong shape - returns
    the same None. Distinguishing them would tell an attacker which part of a
    forgery was wrong, and would tell an honest visitor nothing they could act
    on.
    """
    if not cookie:
        return None

    payload, _, signature = cookie.rpartition(".")
    if not payload or not signature:
        return None

    # compare_digest rather than ==, so the comparison does not leak where the
    # first differing byte is.
    if not hmac.compare_digest(_sign(payload.encode("ascii")), signature):
        return None

    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _decode(cookie: str | None) -> dict:
    """The whole session: which runs are this visitor's, and when they started.

    Tolerates a bare list, which is what the cookie carried before it needed to
    remember start times. An old cookie keeps working and simply has no run
    history - which reads as "no runs today" and costs its holder nothing.
    """
    raw = _verified(cookie)
    if isinstance(raw, list):
        return {"threads": [t for t in raw if isinstance(t, str)], "runs": []}
    if isinstance(raw, dict):
        threads = raw.get("threads")
        runs = raw.get("runs")
        return {
            "threads": [t for t in threads if isinstance(t, str)]
            if isinstance(threads, list)
            else [],
            "runs": [r for r in runs if isinstance(r, str)]
            if isinstance(runs, list)
            else [],
        }
    return {"threads": [], "runs": []}


def _encode(session: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "threads": session["threads"][-MAX_THREADS:],
                "runs": session["runs"][-MAX_THREADS:],
            },
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")
    return f"{payload}.{_sign(payload.encode('ascii'))}"


def read(cookie: str | None) -> list[str]:
    """The thread ids this visitor started, or an empty list."""
    return _decode(cookie)["threads"][-MAX_THREADS:]


def write(threads: list[str]) -> str:
    """The cookie value for these thread ids and no run history.

    Used by tests and by anything that needs a session from nothing; the normal
    path is ``add``, which keeps whatever history is already there.
    """
    return _encode({"threads": list(threads), "runs": []})


def add(cookie: str | None, thread_id: str, now: datetime | None = None) -> str:
    """The cookie for this visitor once they have started one more run.

    The start time is recorded HERE rather than on completion, for the same
    reason the server-wide ledger records at the start: a run that fails halfway
    has already spent what it spent.
    """
    session = _decode(cookie)
    threads = [t for t in session["threads"] if t != thread_id]
    threads.append(thread_id)
    runs = session["runs"] + [(now or datetime.now(timezone.utc)).isoformat()]
    return _encode({"threads": threads, "runs": runs})


def owns(cookie: str | None, thread_id: str) -> bool:
    return thread_id in read(cookie)


def runs_in_window(cookie: str | None, now: datetime | None = None) -> int:
    """How many runs this visitor has started in the last rolling day."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - VISITOR_WINDOW
    count = 0
    for stamp in _decode(cookie)["runs"]:
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            # A timestamp we cannot read is not evidence that a run happened.
            # Erring towards letting somebody run is the right direction: the
            # queue and the provider's refusal are the gates that matter.
            continue
        if when > cutoff:
            count += 1
    return count


def may_start(cookie: str | None, now: datetime | None = None) -> bool:
    return runs_in_window(cookie, now) < RUNS_PER_VISITOR_PER_DAY
