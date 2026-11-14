from __future__ import annotations

from core.services.conversations import ConversationStore


def test_snapshot_flattens_turns_and_provenance():
    now = [1_000.0]
    store = ConversationStore(60, clock=lambda: now[0], max_turns=4)

    store.append("conversation", ("m1",), {("bass2", "bass2/BASS-II_clean.csv")})
    store.append("conversation", ("m2",), {("flex2", "flex2/FLEX2_clean.csv")})

    snapshot = store.snapshot("conversation")

    assert snapshot.messages == ("m1", "m2")
    assert snapshot.provenance == {
        ("bass2", "bass2/BASS-II_clean.csv"),
        ("flex2", "flex2/FLEX2_clean.csv"),
    }


def test_conversation_expires_after_idle_ttl():
    now = [1_000.0]
    store = ConversationStore(60, clock=lambda: now[0])

    store.append("conversation", ("m1",), set())
    now[0] += 61

    assert store.snapshot("conversation").messages == ()


def test_snapshot_keeps_only_recent_turns():
    now = [1_000.0]
    store = ConversationStore(60, clock=lambda: now[0], max_turns=2)

    store.append("conversation", ("m1",), {("bass2", "one.csv")})
    store.append("conversation", ("m2",), {("flex2", "two.csv")})
    store.append("conversation", ("m3",), {("cfig", "three.csv")})

    snapshot = store.snapshot("conversation")

    assert snapshot.messages == ("m2", "m3")
    assert snapshot.provenance == {("flex2", "two.csv"), ("cfig", "three.csv")}


def test_new_conversation_evicts_oldest_when_full():
    now = [1_000.0]
    store = ConversationStore(60, clock=lambda: now[0], max_entries=2)

    store.append("first", ("m1",), set())
    store.append("second", ("m2",), set())
    store.append("third", ("m3",), set())

    assert store.snapshot("first").messages == ()
    assert store.snapshot("second").messages == ("m2",)
    assert store.snapshot("third").messages == ("m3",)
