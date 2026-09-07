"""Tests for the HTTP skeleton.

These run the REAL graph over the REAL SqliteSaver with the five agents stubbed,
which is the only arrangement that answers the question the skeleton was built
to answer: does the checkpoint store behave when the caller is a web handler on
a worker thread rather than a person at a terminal?

A fake store would have proved nothing about that, and a live run would have
cost a day's quota to find out. Everything below is deterministic, offline, and
uses the temporary database `isolated_checkpoints` points every test at.

WHAT THESE DELIBERATELY DO NOT TEST

Frame TIMING. ``httpx.ASGITransport`` collects the whole response body before
handing it back, so every event appears to arrive at once no matter what the
server does - which is exactly what happened the first time this was measured,
and reading it as a defect in the app would have been wrong. Timing was settled
against a real uvicorn server over a socket (``started`` at +0.3s, one stage per
second after it) and cannot be settled here. A test that cannot fail is not
evidence, so rather than assert timing weakly, these assert content only.
"""

import asyncio
import time
import json

import httpx
import pytest

import checkpoints
import workflow
from models.companies import CompanyFindings
from models.decision import Decision
from models.profile import InvestorProfile
from models.research import ResearchFindings
from models.risk import RiskFindings
import render
from web.app import app


# --- Driving the endpoint ----------------------------------------------------


def _events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs.

    Written here rather than pulled from a library on purpose: the point of
    these tests is what this endpoint actually puts on the wire.
    """
    out: list[tuple[str, dict]] = []
    name = None
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:") and name is not None:
            out.append((name, json.loads(line.removeprefix("data:").strip())))
            name = None
    return out


def post(profile: dict) -> list[tuple[str, dict]]:
    """POST a profile and return the events the server sent."""

    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            response = await c.post("/api/runs", json=profile, timeout=30)
            return response.text

    return _events(asyncio.run(_go()))


@pytest.fixture
def whole_pipeline(monkeypatch):
    """Stub all five agents so the real graph runs offline and deterministically.

    Every one of these is patched on ``workflow``, which is where the node
    functions look them up. The autouse guard in conftest already makes reaching
    the real Agents 2 and 3 an immediate failure; this replaces that with
    something that returns.
    """

    def _install(*, clarify=False, fail_at=None, dwell=0.0, spans=None,
                 clarifications_seen=None):
        def profile_agent(user_input, clarifications=None):
            if clarifications_seen is not None:
                # What Agent 1 was actually handed, per call. The point of
                # the round trip is that the person's words arrive here.
                clarifications_seen.append(list(clarifications or []))
            if clarify and not clarifications:
                return InvestorProfile(
                    **user_input.model_dump(),
                    status="needs_clarification",
                    clarification_reason="You asked for technology and forbade it.",
                )
            return InvestorProfile(**user_input.model_dump(), status="valid")

        def research(profile, **kwargs):
            if fail_at == "research":
                raise ConnectionError("news API unreachable")
            if fail_at == "killed":
                # BaseException, so research_node's `except Exception` does not
                # turn it into a recorded error the way a real failure would.
                # This is a worker being killed, not a stage failing.
                raise KeyboardInterrupt("the process went away")
            if dwell:
                # Hold the node open long enough that two runs genuinely
                # overlap. Without it the stubbed pipeline finishes in under a
                # millisecond and a concurrency test proves nothing.
                started = time.monotonic()
                time.sleep(dwell)
                if spans is not None:
                    spans.append((started, time.monotonic()))
            return ResearchFindings(articles_retrieved=12, notes="ok")

        def companies(research_findings, **kwargs):
            return CompanyFindings(mentions_extracted=9, companies_examined=8)

        def risk(company_findings, **kwargs):
            return RiskFindings()

        def decide(*args, **kwargs):
            return Decision(no_recommendation_reason="Nothing cleared the bar.")

        monkeypatch.setattr(workflow, "create_investor_profile", profile_agent)
        monkeypatch.setattr(workflow, "research_themes", research)
        monkeypatch.setattr(workflow, "analyse_companies", companies)
        monkeypatch.setattr(workflow, "critique_companies", risk)
        monkeypatch.setattr(workflow, "decide", decide)

    return _install


@pytest.fixture
def profile(clean_user) -> dict:
    return clean_user.model_dump()


# --- What reaches the client -------------------------------------------------


def test_the_run_id_arrives_before_any_model_call_is_paid_for(whole_pipeline, profile):
    """A client that drops mid-run can only resume if it already knows the id.

    Learning the id from the final event would lose exactly the runs worth
    recovering - the ones that did not reach a final event.
    """
    whole_pipeline()
    events = post(profile)

    assert events[0][0] == "started"
    assert events[0][1]["thread_id"].startswith("web-")


def test_every_stage_reaches_the_client_in_order(whole_pipeline, profile):
    whole_pipeline()
    names = [name for name, _ in post(profile)]

    assert names == ["started", "stage", "stage", "stage", "stage", "stage", "done"]


def test_each_stage_carries_the_counts_the_evals_score(whole_pipeline, profile):
    """The per-stage numbers, not decoration.

    A run that examines eight companies and produces no candidates looks
    identical to a broken one until the counts are on screen. These are the same
    fields the eval runners read.
    """
    whole_pipeline()
    stages = {
        data["node"]: data["detail"] for name, data in post(profile) if name == "stage"
    }

    assert stages["research"]["articles_retrieved"] == 12
    assert stages["companies"]["companies_examined"] == 8
    assert stages["companies"]["candidates"] == []
    assert stages["decide"]["recommended_nothing"] is True


def test_recommending_nothing_is_reported_as_a_result_not_a_failure(
    whole_pipeline, profile
):
    """The outcome the whole design exists to make possible.

    It must reach the client as a completed run carrying a reason, never as an
    error and never as a stream that simply stops.
    """
    whole_pipeline()
    events = post(profile)
    names = [name for name, _ in events]
    done = [data for name, data in events if name == "done"][0]
    decide = [d for n, d in events if n == "stage" and d["node"] == "decide"][0]

    assert "failed" not in names
    assert names[-1] == "done"
    assert decide["detail"]["recommended_nothing"] is True
    assert done["brief"]["decision"]["no_recommendation_reason"]


def test_the_brief_carries_the_properties_a_raw_dump_would_lose(
    whole_pipeline, profile
):
    """The reason the final event sends a described brief and not model_dump().

    ``recommended_nothing``, ``verdict``, ``found_nothing``, ``drop_summary``
    and eleven more are computed properties rather than fields, so a dumped
    model does not contain a single one of them - and they are precisely the
    judgments a reader needs. During the skeleton this test asserted their
    ABSENCE, because that was the truth then and worth recording rather than
    papering over. render.describe_run states them.

    Entry 27 is the ancestor: an unregistered type crossed the checkpointer,
    came back as a dict, and the failure surfaced far away on the first property
    access. The boundary here is JSON and the loss was silent the same way -
    the payload looked complete.
    """
    whole_pipeline()
    brief = [data for name, data in post(profile) if name == "done"][0]["brief"]

    assert brief["status"] == "ok"
    assert brief["decision"]["recommended_nothing"] is True
    assert brief["decision"]["no_recommendation_reason"]
    assert brief["profile"]["headline"].startswith("age 35")


def test_the_brief_says_the_same_thing_the_cli_would_print(whole_pipeline, profile):
    """One description, two front ends.

    Not a comparison of the rendered text - the CLI wraps to 78 columns and a
    browser does not. What must match is the CONTENT decision underneath both,
    which is exactly what render.describe_run holds.
    """
    whole_pipeline()
    brief = [data for name, data in post(profile) if name == "done"][0]["brief"]

    assert brief["disclaimer"] == render.DISCLAIMER
    assert brief["decision"]["nothing_explanation"] == render.NOTHING_RECOMMENDED


def test_a_node_failure_is_reported_rather_than_silence(whole_pipeline, profile):
    """A node catches its own exception and records it, so the graph ends
    cleanly. The client is holding an open connection, and a stream that stops
    without saying why is the blank screen this project refuses everywhere."""
    whole_pipeline(fail_at="research")
    events = post(profile)

    failures = [data for name, data in events if name == "failed"]
    assert len(failures) == 1
    assert "Research failed" in failures[0]["message"]


def test_a_clarification_pauses_the_run_and_sends_the_question(
    whole_pipeline, profile
):
    """The interrupt is reported, not answered. Resuming needs a second request,
    which is the next piece of work - but nothing may be lost in the meantime."""
    whole_pipeline(clarify=True)
    events = post(profile)

    interrupts = [data for name, data in events if name == "interrupt"]
    assert len(interrupts) == 1
    assert "technology" in interrupts[0]["reason"]
    assert interrupts[0]["attempt"] == 1
    assert "done" not in [name for name, _ in events]


def test_an_invalid_profile_is_refused_by_the_model_not_by_this_layer(profile):
    """Ranges live in UserInput. Restating them here would give the bound two
    homes and one of them no test."""
    profile["age"] = 200
    result = asyncio.run(_post_raw(profile))

    assert result["error"] == "invalid profile"
    assert any(d["loc"] == ["age"] for d in result["detail"])


async def _post_raw(profile: dict) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return (await c.post("/api/runs", json=profile, timeout=10)).json()


# --- The question the skeleton exists to answer ------------------------------


def test_the_run_is_saved_and_readable_after_the_response_ends(
    whole_pipeline, profile
):
    """The checkpoint store, driven from a worker thread inside a web handler.

    This is the third of the three questions the skeleton was built for, and the
    one predicted to bite: ``checkpoints.py`` was written assuming one process
    at a time with a person in front of it. Reopening the store afterwards and
    finding the run is what proves the writes actually landed - the response
    completing proves only that nothing raised.
    """
    whole_pipeline()
    thread_id = post(profile)[0][1]["thread_id"]

    with checkpoints.open_store() as store:
        saved = store.run(thread_id)

    assert saved is not None, "the run reached the client but was never written"
    assert saved.status == "finished"
    assert saved.sectors == ["renewable energy"]


def test_a_paused_run_is_left_resumable_under_its_own_id(whole_pipeline, profile):
    """An interrupt over HTTP has nobody to answer it in that request. The run
    must therefore survive as something a later request can pick up."""
    whole_pipeline(clarify=True)
    thread_id = post(profile)[0][1]["thread_id"]

    with checkpoints.open_store() as store:
        saved = store.run(thread_id)

    assert saved.status == "paused"
    assert saved.can_resume
    assert saved.question["reason"]


def test_two_runs_at_once_are_queued_rather_than_refused(whole_pipeline, profile):
    """Two visitors arriving together.

    This test used to assert the opposite - that the two runs OVERLAPPED - and
    said in its own docstring that if it ever failed, the queue would stop being
    a nicety about quota and become a correctness fix. The queue now exists, so
    it fails, and the subject changes deliberately rather than quietly: what
    must hold is that both runs complete, neither is refused, and they do not
    write to the checkpoint database at the same time.

    The second visitor is told where they are. "Busy, try later" is the blank
    screen this project refuses everywhere else.
    """
    spans: list[tuple[float, float]] = []
    whole_pipeline(dwell=0.4, spans=spans)

    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            first, second = await asyncio.gather(
                c.post("/api/runs", json=profile, timeout=30),
                c.post("/api/runs", json=profile, timeout=30),
            )
            return _events(first.text), _events(second.text)

    left, right = asyncio.run(_go())
    ids = {left[0][1]["thread_id"], right[0][1]["thread_id"]}

    assert len(spans) == 2, "both runs must have reached the held-open node"
    (a_start, a_end), (b_start, b_end) = sorted(spans)
    assert b_start >= a_end, "the two runs overlapped; the queue did not hold"

    assert len(ids) == 2, "two runs shared a thread id"
    assert [n for n, _ in left][-1] == "done"
    assert [n for n, _ in right][-1] == "done"

    # Exactly one of them waited, and was told so rather than being turned away.
    queued = [d for events in (left, right) for n, d in events if n == "queued"]
    assert queued, "the second visitor was never told they were in a queue"
    assert queued[0]["position"] == 1

    with checkpoints.open_store() as store:
        assert all(store.run(tid).status == "finished" for tid in ids)


# --- Serialising the result --------------------------------------------------


def test_a_described_brief_survives_json(clean_user):
    """The state carries datetimes - article dates, a price's as_of - and the
    default model dump leaves them as objects that json then refuses.

    The failure would land AFTER a paid run had completed, which is where this
    project has lost work twice (entry 72). So the description is JSON-safe by
    construction, and this drives the path where a date really appears: an exit
    condition citing a retrieved article.
    """
    from datetime import datetime, timezone

    from models.decision import Decision, ExitCondition, Recommendation
    from models.research import Article

    article = Article(
        uuid="u1",
        title="A headline",
        description="d",
        snippet="s",
        url="https://example.com/u1",
        source="example.com",
        published_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    state = {
        "user_input": clean_user,
        "research_findings": ResearchFindings(articles_retrieved=1, articles=[article]),
        "decision": Decision(
            recommendations=[
                Recommendation(
                    ticker="ACME",
                    name="Acme",
                    thesis="It makes things.",
                    screen_score=0.5,
                    verdict="survives",
                    exposure="direct",
                    exit_conditions=[
                        ExitCondition(condition="It stops.", article_ids=["u1"])
                    ],
                )
            ]
        ),
    }

    blob = json.dumps(render.describe_run(state))
    assert "2026-08-18" in blob
    assert "18 Aug 2026" in blob


# --- The clarification, across three requests --------------------------------
#
# The interesting thing this system does, and the reason the HTTP layer needed a
# session at all: the graph stops mid-run to ask a question, and the answer
# arrives in a later request that has to find the same thread.


def visit(steps):
    """Run several requests as ONE browser, so the cookie survives between them."""

    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await steps(c)

    return asyncio.run(_go())


def test_a_paused_run_is_answered_in_a_later_request_and_then_finishes(
    whole_pipeline, profile
):
    """The whole point of step 3, end to end."""
    whole_pipeline(clarify=True)

    async def steps(client):
        first = _events((await client.post("/api/runs", json=profile)).text)
        thread_id = first[0][1]["thread_id"]
        second = _events(
            (
                await client.post(
                    f"/api/runs/{thread_id}/answer",
                    json={"answer": "drop the technology restriction"},
                )
            ).text
        )
        return thread_id, first, second

    thread_id, first, second = visit(steps)

    assert [name for name, _ in first] == ["started", "stage", "interrupt"]
    # The second request picks the SAME run up rather than starting a new one.
    assert second[0][1]["thread_id"] == thread_id
    assert [name for name, _ in second][-1] == "done"

    with checkpoints.open_store() as store:
        assert store.run(thread_id).status == "finished"


def test_the_answer_reaches_the_agent(whole_pipeline, profile):
    """Not merely that the run continued - that what the person typed is what
    Agent 1 was given the second time."""
    seen: list[list[str]] = []
    whole_pipeline(clarify=True, clarifications_seen=seen)

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        await client.post(
            f"/api/runs/{thread_id}/answer", json={"answer": "keep sports, drop tech"}
        )

    visit(steps)

    assert seen[0] == [], "the first pass has no clarification yet"
    assert seen[-1] == ["keep sports, drop tech"]


def test_the_question_can_be_read_again_after_the_page_is_lost(
    whole_pipeline, profile
):
    """Somebody coming back tomorrow needs to see what CONFLICTED, not just a
    prompt saying "please clarify" - the argument the CLI's --resume settled."""
    whole_pipeline(clarify=True)

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        return (await client.get(f"/api/runs/{thread_id}")).json()

    body = visit(steps)

    assert body["status"] == "paused"
    assert body["can_resume"] is True
    assert body["question"]["intro"] == render.CLARIFICATION_INTRO
    assert "technology" in body["question"]["reason"]
    assert body["question"]["attempt"] == 1
    assert body["question"]["max_attempts"] == 3
    assert body["brief"] is None


def test_a_blank_answer_is_refused_rather_than_spending_an_attempt(
    whole_pipeline, profile
):
    """The loop is bounded and gives up with a stated outcome, so an empty reply
    would cost one of three attempts and tell the agent nothing."""
    whole_pipeline(clarify=True)

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        refused = await client.post(
            f"/api/runs/{thread_id}/answer", json={"answer": "   "}
        )
        after = (await client.get(f"/api/runs/{thread_id}")).json()
        return refused, after

    refused, after = visit(steps)

    assert refused.status_code == 422
    assert refused.json()["hint"] == render.BLANK_CLARIFICATION
    assert refused.json()["question"]["attempt"] == 1
    assert after["status"] == "paused", "the run must be exactly where it was"


def test_another_visitor_cannot_answer_your_clarification(whole_pipeline, profile):
    """A thread id is not a secret - it travels in the stream and the CLI prints
    it - so ownership is what stops a stranger's words being fed to an agent
    deciding what to research on somebody else's behalf."""
    whole_pipeline(clarify=True)

    async def owner(client):
        return _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]

    thread_id = visit(owner)

    async def stranger(client):  # a different client: no cookie
        return (
            await client.get(f"/api/runs/{thread_id}"),
            await client.post(
                f"/api/runs/{thread_id}/answer", json={"answer": "drop it"}
            ),
        )

    read, answer = visit(stranger)

    assert read.status_code == 404
    assert answer.status_code == 404
    # The same reply an id that never existed would get: confirming this one is
    # real but somebody else's would turn 404s into a way of enumerating runs.
    assert read.json() == {"error": "no such run"}

    with checkpoints.open_store() as store:
        assert store.run(thread_id).status == "paused", "still waiting on its owner"


def test_answering_a_run_that_already_finished_is_refused_with_its_status(
    whole_pipeline, profile
):
    whole_pipeline()

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        return await client.post(
            f"/api/runs/{thread_id}/answer", json={"answer": "too late"}
        )

    refused = visit(steps)

    assert refused.status_code == 409
    assert refused.json()["status"] == "finished"


def test_a_finished_run_hands_back_its_brief(whole_pipeline, profile):
    whole_pipeline()

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        return (await client.get(f"/api/runs/{thread_id}")).json()

    body = visit(steps)

    assert body["status"] == "finished"
    assert body["question"] is None
    assert body["brief"]["decision"]["recommended_nothing"] is True


def test_a_failed_run_says_why_rather_than_looking_finished(whole_pipeline, profile):
    """Entry 88: a node that catches its own exception leaves nothing pending,
    so a failed run is shaped exactly like a successful one from outside."""
    whole_pipeline(fail_at="research")

    async def steps(client):
        thread_id = _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]
        return (await client.get(f"/api/runs/{thread_id}")).json()

    body = visit(steps)

    assert body["status"] == "failed"
    assert body["can_resume"] is False
    assert body["brief"]["status"] == "failed"
    assert "Research failed" in body["brief"]["error"]


def test_an_unknown_run_is_not_found_rather_than_started(whole_pipeline, profile):
    """Starting a fresh run under an id somebody typed is the failure entry 48
    recorded: LangGraph merges into an existing thread, so continuing and
    starting must never be the same request."""

    async def steps(client):
        return await client.get("/api/runs/web-does-not-exist")

    assert visit(steps).status_code == 404


def test_a_run_killed_mid_stage_resumes_without_repeating_what_it_paid_for(
    whole_pipeline, profile
):
    """The other thing /answer has to handle, and the one with a price on it.

    A worker killed during the three-minute research call - a restart, a deploy,
    a crash - leaves a run STOPPED rather than paused: there is no question, so
    there is nothing to answer. Resuming sends nothing and the graph picks up at
    the unfinished node. On this project's quota, repeating the stages that
    already completed is the difference between losing a minute and losing the
    day's budget.
    """
    calls: list[list[str]] = []
    whole_pipeline(clarifications_seen=calls, fail_at="killed")

    async def start(client):
        return _events((await client.post("/api/runs", json=profile)).text)[0][1][
            "thread_id"
        ]

    thread_id = visit(start)
    assert len(calls) == 1, "Agent 1 ran once before the kill"

    with checkpoints.open_store() as store:
        assert store.run(thread_id).status == "stopped"
        assert store.run(thread_id).question is None, "nothing to answer"

    # The worker comes back and the visitor picks the run up. Same cookie is not
    # available across `visit` calls, so this asserts the store-level behaviour
    # the endpoint depends on rather than going through HTTP twice.
    whole_pipeline(clarifications_seen=calls)
    with checkpoints.open_store() as store:
        list(store.graph.stream(None, store.config(thread_id), stream_mode="updates"))
        assert store.run(thread_id).status == "finished"

    assert len(calls) == 1, "Agent 1 must NOT have been asked a second time"


# --- What is left, and who may have it ---------------------------------------


def test_a_second_run_from_the_same_visitor_is_refused_with_a_reason(
    whole_pipeline, profile
):
    """Not "busy, try later". A stated reason, and the numbers behind it.

    One person clicking repeatedly is 25-30k tokens a time against a ceiling
    every visitor shares - the next visitor would meet an empty site rather
    than this message.
    """
    whole_pipeline()

    async def steps(client):
        first = await client.post("/api/runs", json=profile, timeout=30)
        second = await client.post("/api/runs", json=profile, timeout=30)
        return first, second

    first, second = visit(steps)

    assert first.status_code == 200
    assert second.status_code == 429
    body = second.json()
    assert body["error"] == "one run per visitor per day"
    assert "shares" in body["reason"]
    assert body["quota"]["estimate"] is True


def test_the_quota_endpoint_says_what_is_left_and_that_it_is_a_guess(
    whole_pipeline, profile
):
    whole_pipeline()

    async def steps(client):
        before = (await client.get("/api/quota")).json()
        await client.post("/api/runs", json=profile, timeout=30)
        after = (await client.get("/api/quota")).json()
        return before, after

    before, after = visit(steps)

    assert before["you_may_start"] is True
    assert before["your_runs_today"] == 0
    assert after["you_may_start"] is False, "they have had their run"
    assert after["your_runs_today"] == 1
    assert after["runs_used"] == before["runs_used"] + 1
    assert after["estimate"] is True


def test_the_estimate_never_refuses_a_run_by_itself(whole_pipeline, profile, monkeypatch):
    """The server-wide number is advisory and must stay that way.

    Groq does not report the daily budget, so this figure is a guess. The
    refusal is the gate: it costs nothing, states Limit, Used and Requested
    exactly, and adds nothing to the window it reports on. Refusing on the
    strength of a guess would turn a bad estimate into a closed site.
    """
    from web import quota

    monkeypatch.setattr(quota, "RUNS_PER_DAY", 0)
    whole_pipeline()

    async def steps(client):
        assert (await client.get("/api/quota")).json()["runs_remaining"] == 0
        return await client.post("/api/runs", json=profile, timeout=30)

    assert visit(steps).status_code == 200, "the estimate must not be the gate"
