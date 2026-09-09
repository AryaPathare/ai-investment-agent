"""Tests for the one-at-a-time gate.

The queue exists so two visitors cannot write to one SQLite checkpoint file at
once, and so the second one is told where they are rather than refused. These
test the second half hardest: a position that is wrong is worse than no position
at all, because the visitor is being told something specific and false.
"""

import asyncio


from frontend.runqueue import RunQueue


def run(coro):
    return asyncio.run(coro)


def test_the_first_caller_goes_straight_through():
    async def go():
        queue = RunQueue()
        async with queue.place() as ticket:
            return ticket.granted, ticket.position

    assert run(go()) == (True, 0)


def test_the_second_caller_is_told_they_are_second():
    async def go():
        queue = RunQueue()
        async with queue.place() as first:
            async with queue.place() as second:
                return first.granted, second.granted, second.position

    granted_first, granted_second, position = run(go())
    assert granted_first is True
    assert granted_second is False
    assert position == 1


def test_a_waiting_caller_is_granted_when_the_one_ahead_finishes():
    async def go():
        queue = RunQueue()
        order = []

        async def waiter(name):
            async with queue.place() as ticket:
                await queue.wait_for_turn(ticket)
                order.append(name)
                await asyncio.sleep(0.02)

        await asyncio.gather(waiter("first"), waiter("second"))
        return order

    assert run(go()) == ["first", "second"]


def test_positions_move_up_as_the_line_shortens():
    """The number on a waiting visitor's screen has to keep being true.

    Entered and left explicitly rather than with nested ``async with`` blocks:
    nesting makes the LAST caller leave first, which is the opposite of a queue
    draining and quietly tests the wrong ticket.
    """

    async def go():
        queue = RunQueue()
        first, second, third = queue.place(), queue.place(), queue.place()
        a = await first.__aenter__()
        b = await second.__aenter__()
        c = await third.__aenter__()

        assert (a.granted, b.position, c.position) == (True, 1, 2)

        await second.__aexit__(None, None, None)
        assert c.position == 1, "the middle of the line left; everyone moves up"
        assert not c.granted

        await first.__aexit__(None, None, None)
        assert c.position == 0 and c.granted, "its turn arrived"
        assert c.changed.is_set(), "and it was told, rather than having to poll"

        await third.__aexit__(None, None, None)
        return queue.depth

    assert run(go()) == 0


def test_a_caller_who_leaves_while_waiting_does_not_block_the_line():
    """A closed tab must not strand everybody behind it."""

    async def go():
        queue = RunQueue()
        async with queue.place() as first:
            async with queue.place() as abandoned:
                assert abandoned.waiting
            # abandoned has left; the line is just `first` again
            assert queue.depth == 1
            async with queue.place() as third:
                return third.position, queue.depth

    assert run(go()) == (1, 2)


def test_the_line_empties_completely():
    async def go():
        queue = RunQueue()
        async with queue.place():
            pass
        async with queue.place() as second:
            return queue.depth, second.granted

    assert run(go()) == (1, True)


def test_order_is_first_come_first_served():
    """Including resumed runs. A queue whose order cannot be predicted from
    outside is one nobody can be told the truth about."""

    async def go():
        queue = RunQueue()
        finished = []

        async def caller(name, delay):
            await asyncio.sleep(delay)
            async with queue.place() as ticket:
                await queue.wait_for_turn(ticket)
                await asyncio.sleep(0.03)
                finished.append(name)

        await asyncio.gather(
            caller("a", 0.00), caller("b", 0.01), caller("c", 0.02)
        )
        return finished

    assert run(go()) == ["a", "b", "c"]
