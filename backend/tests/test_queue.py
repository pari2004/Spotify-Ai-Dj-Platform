"""Queue state-machine tests (PRD §6.1).

Covers vote-driven reordering determinism, concurrent votes never diverging, Soundclash
submit/vote/resolve/splice, and host-disconnect promotion/freeze.
"""
import asyncio

from app.realtime.room_state import RoomState


def _room():
    r = RoomState("lg_test", host_user_id=1, now_playing="t_2001")
    for tid in ("t_2002", "t_2003", "t_2004"):
        r.add_to_queue(tid)
    return r


def test_vote_reorders_deterministically():
    r = _room()
    assert [q.track_id for q in r.next_up] == ["t_2002", "t_2003", "t_2004"]
    r.vote("t_2004", user_id=10)
    r.vote("t_2004", user_id=11)
    assert r.next_up[0].track_id == "t_2004"  # most-voted floats to top


def test_one_vote_per_user_is_idempotent():
    r = _room()
    assert r.vote("t_2002", 10) is True
    assert r.vote("t_2002", 10) is False  # same user can't double-vote
    item = next(q for q in r.next_up if q.track_id == "t_2002")
    assert item.votes == 1


def test_concurrent_votes_converge():
    """Two simultaneous votes on different tracks must leave server state consistent and
    order fully determined (PRD §6.1: no divergence)."""
    r = _room()

    async def drive():
        async def cast(track, uid):
            async with r.lock:
                r.vote(track, uid)
        await asyncio.gather(
            cast("t_2003", 20), cast("t_2004", 21), cast("t_2004", 22), cast("t_2003", 23),
        )

    asyncio.run(drive())
    votes = {q.track_id: q.votes for q in r.next_up}
    assert votes["t_2003"] == 2 and votes["t_2004"] == 2
    # Deterministic tie-break by original position: t_2003 was added before t_2004.
    top_two = [q.track_id for q in r.next_up[:2]]
    assert top_two == ["t_2003", "t_2004"]


def test_soundclash_submit_vote_resolve_splice():
    r = _room()
    battle = r.open_battle(["t_2005", "t_clash"], duration_seconds=30)
    assert battle.status == "open"
    r.vote_battle("t_2005", 30)
    r.vote_battle("t_2005", 31)
    r.vote_battle("t_clash", 32)
    winner = r.resolve_battle()
    assert winner == "t_2005"
    assert r.soundclash.status == "resolved"
    # winner spliced to the FRONT of the queue
    assert r.next_up[0].track_id == "t_2005"


def test_soundclash_tie_breaks_to_earliest_candidate():
    r = _room()
    r.open_battle(["t_2005", "t_clash"])
    r.vote_battle("t_2005", 1)
    r.vote_battle("t_clash", 2)  # 1-1 tie
    assert r.resolve_battle() == "t_2005"  # earliest-submitted wins


def test_advance_tracks_recently_played():
    r = _room()
    r.advance()
    assert r.now_playing == "t_2002"
    assert r.recently_played[0] == "t_2001"


def test_host_disconnect_promotes_co_dj():
    r = RoomState("lg2", host_user_id=1, now_playing="t_2001")
    r.join(1, "Host", "host")
    r.join(2, "Co", "co_dj")
    r.host_connected = True
    # host leaves
    r.leave(1)
    assert r.host_connected is False
    promoted = r.promote_first_co_dj_to_host()
    assert promoted == 2
    assert r.host_user_id == 2


def test_host_disconnect_with_no_co_dj_freezes():
    r = RoomState("lg3", host_user_id=1, now_playing="t_2001")
    r.join(1, "Host", "host")
    r.join(2, "Listener", "listener")
    r.host_connected = True
    r.leave(1)
    assert r.promote_first_co_dj_to_host() is None  # nobody to promote -> caller freezes room
