"""One run at a time, and everybody else told where they are.

WHY SERIALISE AT ALL

Two runs at once means two writers on one SQLite checkpoint file, and
``checkpoints.py`` was written for a person at a terminal - one process, one
run. The offline test that drives two concurrent requests passes today, so this
is not repairing an observed corruption; it is refusing to rely on a property
nothing guarantees, on the one file that holds work a person has already paid
for.

There is a second reason, and on this project it is the bigger one. A full run
is 25-30k tokens and a rolling daily ceiling of 200k. Two visitors arriving
together do not merely risk the database - they spend the day's budget twice as
fast, and both get a slower run because the provider rate-limits per minute.

WHY A POSITION AND NOT AN ERROR

Refusing the second visitor with "busy, try later" is the blank screen this
project refuses everywhere else. "You are second in line" is a stated reason
with something to wait for, and it is the same argument as recommending nothing:
an honest empty answer beats an error code.

FAIRNESS IS FIRST COME, FIRST SERVED

Including resumed runs, which wait their turn like anything else. A case can be
made for letting someone answering a clarification jump ahead - they are
mid-conversation and their run already holds work that was paid for - and it was
considered and not built, because a queue whose order cannot be predicted from
the outside is one nobody can be told the truth about. If a person waits behind
a resume they were told about, that is a queue. If they can be overtaken by
runs they never see, the position is a guess.

WHAT THIS IS NOT

Not durable and not shared. It lives in one process, so two server processes
would have two queues and the SQLite argument above comes straight back. That is
a deployment constraint - run ONE worker - rather than something this module can
fix, and it is written down here because the failure would be silent.
"""

import asyncio
from contextlib import asynccontextmanager


class Ticket:
    """One caller's place in line.

    ``changed`` is set whenever this ticket's position moves or its turn
    arrives, so a caller can report progress without polling: waiting on an
    event costs nothing, and a timer would either lag or spin.
    """

    __slots__ = ("position", "granted", "changed")

    def __init__(self, position: int) -> None:
        self.position = position
        self.granted = position == 0
        self.changed = asyncio.Event()
        if self.granted:
            self.changed.set()

    @property
    def waiting(self) -> bool:
        return not self.granted


class RunQueue:
    """A one-at-a-time gate that can say how long the line is.

    Deliberately not an ``asyncio.Semaphore``. A semaphore grants entry in an
    order nobody can observe, so there is no position to report - and the
    position is the whole point of queueing rather than refusing.
    """

    def __init__(self) -> None:
        self._line: list[Ticket] = []

    @property
    def depth(self) -> int:
        """How many runs are in the system, including the one in progress."""
        return len(self._line)

    @asynccontextmanager
    async def place(self):
        """Take a place in line, yielding the ticket immediately.

        The ticket is yielded BEFORE the turn arrives, so a caller can tell the
        visitor where they are while they wait. Awaiting ``wait_for_turn`` is
        what actually blocks.

        Always a context manager: a client that closes the tab while queued must
        leave the line, or everybody behind them waits on somebody who is gone.
        """
        ticket = Ticket(position=len(self._line))
        self._line.append(ticket)
        try:
            yield ticket
        finally:
            self._line.remove(ticket)
            self._renumber()

    async def wait_for_turn(self, ticket: Ticket) -> None:
        while not ticket.granted:
            ticket.changed.clear()
            await ticket.changed.wait()

    def _renumber(self) -> None:
        """Tell everybody still waiting where they now are."""
        for position, ticket in enumerate(self._line):
            if ticket.position != position or (position == 0 and not ticket.granted):
                ticket.position = position
                if position == 0:
                    ticket.granted = True
                ticket.changed.set()


queue = RunQueue()
"""The process-wide queue.

A module-level instance rather than something built per request, because the
whole point is that unrelated requests meet in it. It holds no resources - an
empty list until somebody queues - so importing this module still touches
nothing, which is the rule ``workflow.py`` and ``checkpoints.py`` both follow.
"""
