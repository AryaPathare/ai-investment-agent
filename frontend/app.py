"""A walking skeleton: one endpoint that runs the pipeline and streams it.

WHAT THIS IS FOR

Not a feature. It exists to answer three questions about runtime behaviour that
no amount of reading settles, before any HTML is written:

1. Does the graph run inside an async web handler at all?
2. Does the existing ``stream(stream_mode="updates")`` loop give usable events?
3. Does the SQLite checkpoint store behave when the process is not a terminal?

Everything here is deliberately thin. Nothing in this file decides what a reader
is TOLD: the stage counts and the finished brief both come from ``render.py``,
which the CLI reads too, so the two front ends cannot end up describing the same
run differently. Writing the brief's layout twice is the defect category this
project has recorded most often (entries 48, 49, 92, 94).

THE ONE STRUCTURAL DECISION

``graph.stream`` is synchronous and takes two to four minutes. Awaiting it on
the event loop would block every other request AND - the part that matters -
stop the SSE frames flushing, so the browser would receive the whole run in one
burst at the end. That is precisely the failure streaming exists to prevent, and
it is the same argument entry 26 made for ``stream`` over ``invoke`` in the CLI:
a channel that goes silent for three minutes is indistinguishable from a hang.

So the graph runs in a worker thread and pushes events into an ``asyncio.Queue``
that the response generator drains. The thread is where the blocking work
belongs; the queue is the only thing crossing between them.

WHAT IS NOT HERE YET, ON PURPOSE

* The clarification interrupt is REPORTED and not resolved. A paused run is
  saved and resumable by id, so nothing is lost - but resuming it over HTTP
  needs a session model, which is the next piece of work and constrains it.
* No queue, no quota counter, no rate limit. Two concurrent runs would mean two
  writers on one SQLite file; until the queue exists this is single-user.
"""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from langgraph.types import Command
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from backend import checkpoints
from backend import recordings
from backend import render
from backend.models.user_input import UserInput
from frontend import quota, runqueue, session

app = FastAPI(
    title="AI Investment Research Agent",
    description="Runs the five-agent pipeline and streams each stage as it lands.",
)


# --- Driving the graph off the event loop ------------------------------------


_SENTINEL = object()
"""Put on the queue by the worker thread when it has nothing left to send.

A sentinel rather than closing the queue, because the reader has to be able to
tell "the run ended" from "nothing has happened for ninety seconds", and the
second is normal here - Agent 3 can spend minutes inside one node.
"""


def _run_graph(store, thread_id: str, start, emit) -> None:
    """Drive the graph to completion or to its first interrupt. Blocking.

    Runs in a worker thread. ``emit`` is the only thing that crosses back to the
    event loop, and it is called with plain dicts - nothing holding a database
    handle or a Pydantic object escapes this function.

    An interrupt STOPS this loop rather than asking. Over HTTP the answer
    arrives in a later request, and the graph has already saved itself, so the
    run is left paused under its own id and reported as such.
    """
    config = {"configurable": {"thread_id": thread_id}}

    for chunk in store.graph.stream(start, config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            emit({"event": "interrupt", "data": chunk["__interrupt__"][0].value})
            return

        for node, update in chunk.items():
            if update.get("error"):
                # A node that caught its own exception recorded it and let the
                # graph end cleanly, deliberately, so no traceback reaches a
                # user. That makes it indistinguishable from success by shape
                # alone (entry 88), which is why the error is read explicitly.
                emit({
                    "event": "failed",
                    "data": {
                        "message": update["error"],
                        # The same hint render.describe() attaches when this run
                        # is read back later. Without it the LIVE view of a
                        # failure said less than the reloaded view of the same
                        # failure - and on a public site, where the shared daily
                        # ceiling is what usually ends a run, the live view is
                        # the one nearly every visitor sees.
                        "hint": render.RATE_LIMIT_HINT,
                    },
                })
                continue

            stage, label = render.STAGE_LABELS.get(node, (0, node))
            emit(
                {
                    "event": "stage",
                    "data": {
                        "node": node,
                        "stage": stage,
                        "label": label,
                        "detail": render.stage_detail(node, update),
                    },
                }
            )

    # stream() yields per-node updates and never the accumulated state, so the
    # thing a reader actually wants is read back from the checkpointer - and
    # described through render.py rather than dumped.
    #
    # A raw model_dump was what this sent during the skeleton, and it silently
    # drops every computed PROPERTY: recommended_nothing, verdict, found_nothing,
    # drop_summary, in_major_units. A browser handed that would have to
    # re-derive "is this a recommendation of nothing?" from the length of a
    # list, which is a rule from the model living in a second home that nothing
    # tests. describe_run states all of them.
    emit(
        {
            "event": "done",
            "data": {
                "thread_id": thread_id,
                "brief": render.describe_run(store.graph.get_state(config).values),
            },
        }
    )


async def _stream(thread_id: str, start):
    """Bridge the worker thread to the response, one event at a time.

    ``start`` is the only difference between a new run and a resumed one, the
    same three shapes the CLI drives with: a profile to begin, a Command
    carrying an answer, or None to pick up a run that stopped mid-stage.
    """
    events: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event: dict) -> None:
        # call_soon_threadsafe is the whole bridge: put_nowait from another
        # thread is not safe, and awaiting from one is not possible.
        loop.call_soon_threadsafe(events.put_nowait, event)

    def work() -> None:
        try:
            # The store is opened INSIDE the thread that uses it. The connection
            # is created with check_same_thread=False, but keeping the whole
            # lifetime in one thread means this is not also exercising SQLite's
            # cross-thread behaviour while it exercises everything else.
            with checkpoints.open_store() as store:
                _run_graph(store, thread_id, start, emit)
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            # Anything reaching here escaped every node's own handler. It still
            # must not be silence: the browser is holding an open connection and
            # a stream that simply stops is the blank screen this project
            # refuses everywhere else.
            emit({
                "event": "failed",
                "data": {
                    "message": f"{type(exc).__name__}: {exc}",
                    "hint": render.RATE_LIMIT_HINT,
                },
            })
        finally:
            loop.call_soon_threadsafe(events.put_nowait, _SENTINEL)

    # The run id goes out FIRST, before any model call is paid for. A client
    # that drops mid-run can then resume by id; one that learned the id only at
    # the end would lose exactly the runs worth recovering.
    yield {"event": "started", "data": json.dumps({"thread_id": thread_id})}

    # One run at a time. A context manager because a visitor who closes the tab
    # while queued has to leave the line, or everybody behind them waits on
    # somebody who is gone.
    async with runqueue.queue.place() as ticket:
        while not ticket.granted:
            yield {
                "event": "queued",
                "data": json.dumps(
                    {"position": ticket.position, "ahead": ticket.position}
                ),
            }
            ticket.changed.clear()
            # Re-checked AFTER the clear. A grant landing in between would
            # otherwise be cleared and waited on forever; a POSITION change
            # landing there is only ever reported late, which costs a stale
            # number on screen and nothing else.
            if ticket.granted:
                break
            await ticket.changed.wait()

        task = asyncio.create_task(asyncio.to_thread(work))

        while True:
            item = await events.get()
            if item is _SENTINEL:
                break
            yield {"event": item["event"], "data": json.dumps(item["data"])}

        await task


# --- Sessions ----------------------------------------------------------------


_NO_SUCH_RUN = {"error": "no such run"}
"""One reply for both "never existed" and "not yours".

Telling them apart would let anybody enumerate other people's runs by watching
which ids come back 403 rather than 404.
"""


def _remember(response, request: Request, thread_id: str) -> None:
    """Record on the visitor that this run is theirs to answer."""
    response.set_cookie(
        session.COOKIE_NAME,
        session.add(request.cookies.get(session.COOKIE_NAME), thread_id),
        # The browser never needs to read this, so JavaScript must not either.
        httponly=True,
        samesite="lax",
        # Only over TLS when the request itself came over TLS - hard-coding it
        # true would silently drop the cookie in local development, and
        # hard-coding it false would leak it in production.
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


# --- The endpoints -----------------------------------------------------------
#
# A run that pauses is spread across three requests, and the shape below follows
# from that rather than from REST tidiness:
#
#   POST /api/runs                    start one, stream until it ends or pauses
#   GET  /api/runs/{id}               what happened to it, and what it is asking
#   POST /api/runs/{id}/answer        answer, and stream the rest of it
#
# The GET is not a convenience. A browser that reloads, or a person coming back
# tomorrow, has to be able to see the ORIGINAL question again - "please clarify"
# with no statement of what conflicted is useless to somebody who has lost the
# page, and this project already settled that argument for the CLI's --resume.


@app.post("/api/runs")
async def start_run(payload: dict, request: Request):
    """Run the pipeline for a profile and stream each stage as it completes.

    The profile is validated by ``UserInput`` and not by anything written here.
    Restating ``gt=0, le=120`` in a request model would give the bound two homes
    and one of them no test - the argument entry 29 already settled for the CLI.
    """
    try:
        user = UserInput(**payload)
    except ValidationError as exc:
        # The field errors, rather than a 500 with a traceback.
        return JSONResponse(
            status_code=422,
            content={"error": "invalid profile", "detail": json.loads(exc.json())},
        )

    cookie = request.cookies.get(session.COOKIE_NAME)
    if not session.may_start(cookie):
        # A stated reason and something else to look at, never a bare refusal.
        # One visitor clicking repeatedly is 25-30k tokens a time against a
        # ceiling everybody shares, and the next visitor would meet an empty
        # site rather than this message.
        return JSONResponse(
            status_code=429,
            content={
                "error": "one run per visitor per day",
                "reason": (
                    "You have already had a run today. A full run costs a "
                    "sizeable share of a daily budget that every visitor "
                    "shares, so there is one each."
                ),
                "quota": quota.describe(),
            },
        )

    thread_id = f"web-{uuid.uuid4().hex[:8]}"
    # Recorded before the first model call, not after the last one: a run that
    # fails halfway has already spent what it spent.
    quota.record()
    response = EventSourceResponse(_stream(thread_id, {"user_input": user}))
    # Set BEFORE the run, not after it: the visitor has to own this thread while
    # it is still running, or a clarification arriving two minutes from now
    # would be refused as somebody else's.
    _remember(response, request, thread_id)
    return response


@app.get("/api/quota")
async def read_quota(request: Request) -> dict:
    """What is probably left today, and whether this visitor may have one.

    Advisory, and it says so. Nothing here refuses a run on the strength of the
    server-wide estimate - the provider's own refusal is the gate, it costs
    nothing, and it states the numbers exactly. The per-VISITOR limit below is a
    different thing and is enforced.
    """
    cookie = request.cookies.get(session.COOKIE_NAME)
    return {
        **quota.describe(),
        "you_may_start": session.may_start(cookie),
        "your_runs_today": session.runs_in_window(cookie),
        "runs_per_visitor_per_day": session.RUNS_PER_VISITOR_PER_DAY,
        "queue_depth": runqueue.queue.depth,
    }


@app.get("/api/runs/{thread_id}")
async def read_run(thread_id: str, request: Request):
    """What happened to one run, and what it is waiting on.

    Four answers, matching the four a saved run can have, because they need
    different things from a reader: an answer, patience, or nothing at all.
    """
    if not session.owns(request.cookies.get(session.COOKIE_NAME), thread_id):
        # Deliberately the same reply as a genuinely unknown id. Confirming that
        # a run exists but belongs to somebody else would turn this into a way
        # of enumerating other people's runs.
        return JSONResponse(status_code=404, content=_NO_SUCH_RUN)

    with checkpoints.open_store() as store:
        saved = store.run(thread_id)
        if saved is None:
            return JSONResponse(status_code=404, content=_NO_SUCH_RUN)

        body = {
            "thread_id": thread_id,
            "status": saved.status,
            "can_resume": saved.can_resume,
            "sectors": saved.sectors,
            "updated_at": saved.updated_at,
            "question": (
                render.describe_question(saved.question) if saved.question else None
            ),
            # A finished OR failed run has something to read. `describe_run`
            # tells those apart itself, and a failed one carries its reason -
            # which is the whole of entry 88: nothing pending looks identical to
            # success from outside, so the error has to be read explicitly.
            "brief": (
                render.describe_run(store.graph.get_state(store.config(thread_id)).values)
                if not saved.can_resume
                else None
            ),
        }
    return body


@app.post("/api/runs/{thread_id}/answer")
async def answer_run(thread_id: str, payload: dict, request: Request):
    """Resume a paused run with the visitor's clarification.

    Resuming is an explicit endpoint rather than something inferred from a
    second POST, for the reason entry 48 recorded the hard way: LangGraph merges
    new input into an existing thread, so a fresh run on an id that already
    exists silently inherits the earlier run's clarification answers and Agent 1
    then reports a conflict resolved that nobody resolved. Starting and
    continuing must not be the same request.
    """
    cookie = request.cookies.get(session.COOKIE_NAME)
    if not session.owns(cookie, thread_id):
        return JSONResponse(status_code=404, content=_NO_SUCH_RUN)

    answer = (payload.get("answer") or "").strip()

    with checkpoints.open_store() as store:
        saved = store.run(thread_id)

        if saved is None:
            return JSONResponse(status_code=404, content=_NO_SUCH_RUN)

        if not saved.can_resume:
            # Not an error the caller can fix by retrying, and worth telling
            # apart: "it already finished" and "it failed" are different facts,
            # and `read_run` above will hand over the brief for either.
            return JSONResponse(
                status_code=409,
                content={
                    "error": f"this run is {saved.status}",
                    "status": saved.status,
                    "thread_id": thread_id,
                },
            )

        if saved.question is not None and not answer:
            # A blank answer would spend one of a small number of attempts and
            # tell the agent nothing. Refused in both front ends, with the same
            # sentence saying what would help.
            return JSONResponse(
                status_code=422,
                content={
                    "error": "an answer is needed",
                    "hint": render.BLANK_CLARIFICATION,
                    "question": render.describe_question(saved.question),
                },
            )

        # A run that stopped mid-stage rather than at a question resumes with
        # NOTHING, and the graph picks up at the unfinished node without
        # repeating the ones that completed. On this project's quota that is the
        # difference between losing a minute and losing the day's budget.
        start = Command(resume=answer) if saved.question is not None else None

    return EventSourceResponse(_stream(thread_id, start))


@app.get("/api/form")
async def read_form() -> dict:
    """The questions, their allowed answers, and their bounds.

    Served rather than written into the HTML so the page cannot offer a risk
    level the model would reject, or leave off a currency that was added. The
    CLI reads the same definitions - see render.form_fields.
    """
    return {"fields": render.form_fields(), "disclaimer": render.DISCLAIMER}


@app.get("/api/gallery")
async def read_gallery() -> dict:
    """Recorded runs, listed.

    This is what the site has when the day's quota is gone, and it is not a
    consolation prize: every one is a real run through the real pipeline, with
    the same renderer and the same grounded exit conditions. Only the API calls
    are absent.

    The profile is listed beside each one deliberately. "Narrower researches
    better" is the most useful thing this system knows about how to ask it -
    'semiconductors' produced its best brief and 'renewable energy' an empty one
    - and a gallery that shows only answers teaches none of that.
    """
    return {
        "runs": [recordings.summarise(path) for path in recordings.available()],
        "note": (
            "Real runs, replayed from recordings that ship with the code. No "
            "API key, no network call and no quota were used to show them."
        ),
    }


@app.get("/api/gallery/{name}")
async def read_recording(name: str):
    """One recorded run, described exactly as a live one is.

    Through render.describe_run, so a recording and a fresh run cannot render
    differently - which is the whole reason the description was split out.
    """
    # Resolved against the gallery directory rather than joined to it: `name`
    # comes from a URL, and "../../.env" is a path too.
    match = next((p for p in recordings.available() if p.stem == name), None)
    if match is None:
        return JSONResponse(status_code=404, content={"error": "no such recording"})

    state = recordings.load(match)
    return {
        "name": name,
        "recorded_on": state.get("recorded_on"),
        "brief": render.describe_run(state),
    }


@app.get("/api/health")
async def health() -> dict:
    """Cheap liveness check that touches neither the database nor a provider."""
    return {"ok": True}


# --- The page ----------------------------------------------------------------


STATIC = Path(__file__).parent / "static"


@app.get("/")
async def index() -> FileResponse:
    """One page, no build step.

    Served from a file rather than a template because nothing about it is
    computed on the server: the questions come from ``/api/form`` and the brief
    comes from the run's own stream, so there is nothing to interpolate and
    nothing that can drift from what the CLI shows.
    """
    return FileResponse(STATIC / "index.html")


@app.get("/paper.pdf")
async def paper() -> FileResponse:
    """The write-up the About tab shows, served as the file it is.

    A file rather than a render: this is a document that was written and
    exported, not a view of anything the server holds, so what a visitor
    downloads is the same artefact rather than a second rendering of it that
    could disagree.

    Served by an explicit route because this app mounts no static directory -
    the page and these two assets are the only files it serves - which is also
    why no path from a request ever reaches the filesystem here.
    """
    return FileResponse(
        STATIC / "paper.pdf",
        media_type="application/pdf",
        # Named for the download, not for the URL. Without this a saved copy is
        # called paper.pdf, with no hint of what it is a paper about.
        filename="building-and-verifying-a-multi-agent-llm-pipeline.pdf",
        content_disposition_type="inline",
    )


@app.get("/paper-p1.png")
async def paper_preview() -> FileResponse:
    """Page one of that PDF, as the picture on the card.

    A route rather than a data: URI in the page. Inlining 44KB of base64 would
    put it in front of every visitor including the ones who never open About,
    and it would be re-sent on every page load; a file is fetched once, only
    when the tab is opened, and then cached.
    """
    return FileResponse(STATIC / "paper-p1.png", media_type="image/png")
