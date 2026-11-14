"""Magic Wormhole feasibility spike. Run against a local mailbox (default) or,
to measure real-world latency, against the public one:

    python spike/run_spike.py --relay ws://relay.magic-wormhole.io:4000/v1 latency

Two-machine latency test (round trip between two real computers):
    machine A:  python spike/run_spike.py --relay <url> pingpong host  12345678-testpass
    machine B:  python spike/run_spike.py --relay <url> pingpong join  12345678-testpass
"""
from __future__ import annotations

import argparse
import random
import statistics
import threading
import time

from ww_bridge import Closed, Link

LOCAL = "ws://127.0.0.1:4000/v1"


def room() -> str:
    return str(random.randrange(10**9, 10**10))          # numeric nameplate (required)


def timed(label, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        status = "ok"
    except Exception as exc:                              # noqa: BLE001
        out, status = exc, f"{type(exc).__name__}"
    dt = (time.perf_counter() - t0) * 1000
    print(f"  {label:<52} {status:<22} {dt:7.0f} ms")
    return out


def pair(relay, code_a, code_b=None):
    a, b = Link(relay), Link(relay)
    a.open(code_a)
    b.open(code_b or code_a)
    return a, b


def exchange(a, b):
    a.send(b"hello from host")
    b.send(b"hello from guest")
    return a.recv(10), b.recv(10)


def s1_custom_passkey(relay):
    print("\n[1] user-chosen passkey as the code (numeric room + free-text passkey)")
    code = f"{room()}-purple tiger!42".replace(" ", "_")   # spaces not allowed
    a, b = pair(relay, code)
    got = timed("exchange messages with custom passkey", lambda: exchange(a, b))
    assert got == (b"hello from guest", b"hello from host"), got
    a.close(); b.close()


def s2_wrong_passkey(relay):
    print("\n[2] wrong passkey")
    n = room()
    a, b = pair(relay, f"{n}-correct-horse", f"{n}-wrong-horse")
    ra = timed("host sees", lambda: a.recv(10))
    rb = timed("guest sees", lambda: b.recv(10))
    for r in (ra, rb):
        assert isinstance(r, Closed) or "WrongPassword" in type(r).__name__ or isinstance(r, Exception), r
    print("     host error :", getattr(getattr(ra, 'reason', ra), '__class__', type(ra)).__name__)
    print("     guest error:", getattr(getattr(rb, 'reason', rb), '__class__', type(rb)).__name__)
    a.close(); b.close()


def s3_retry_after_failure(relay):
    print("\n[3] host re-listens on the SAME code after a bad attempt; friend retries correctly")
    n = room(); good = f"{n}-lamp-river"
    host = Link(relay); host.open(good)
    bad = Link(relay); bad.open(f"{n}-lamp-rivr")           # typo
    timed("bad attempt rejected on host", lambda: host.recv(10))
    host.close(); bad.close()
    host2 = Link(relay); host2.open(good)                    # host restarts listening
    friend = Link(relay); friend.open(good)
    got = timed("friend connects with right passkey", lambda: exchange(host2, friend))
    assert got == (b"hello from guest", b"hello from host"), got
    host2.close(); friend.close()


def s4_third_party_crowding(relay):
    print("\n[4] a third party tries to join a live, authenticated room")
    n = room(); code = f"{n}-secret-words"
    a, b = pair(relay, code)
    exchange(a, b)
    intruder = Link(relay); intruder.open(f"{n}-guess-guess")
    timed("intruder is turned away", lambda: intruder.recv(8))
    a.send(b"still alive?")
    got = timed("original pair still works afterwards", lambda: b.recv(8))
    assert got == b"still alive?", got
    a.close(); b.close(); intruder.close()


def s5_room_reuse(relay):
    print("\n[5] the same room number can be reused right after closing")
    n = room()
    for i in (1, 2):
        a, b = pair(relay, f"{n}-pass{i}")
        timed(f"round {i}: exchange", lambda: exchange(a, b))
        a.close(); b.close()


def s6_latency(relay, rounds=30):
    print(f"\n[6] round-trip latency, {rounds} ping-pongs on one machine (via the mailbox)")
    a, b = pair(relay, f"{room()}-latency-test")
    exchange(a, b)
    stop = threading.Event()

    def echo():
        while not stop.is_set():
            try:
                m = b.recv(1)
            except Closed:
                return
            if m:
                b.send(m)
    threading.Thread(target=echo, daemon=True).start()
    samples = []
    for i in range(rounds):
        t0 = time.perf_counter()
        a.send(b"ping%d" % i)
        assert a.recv(10) == b"ping%d" % i
        samples.append((time.perf_counter() - t0) * 1000)
    stop.set()
    s = sorted(samples)
    print(f"     median {statistics.median(s):.0f} ms | p90 {s[int(len(s)*.9)-1]:.0f} ms | max {s[-1]:.0f} ms")
    a.close(); b.close()


def pingpong(relay, role, code):
    link = Link(relay); link.open(code)
    print("connecting... (waiting for the other side)")
    if role == "host":
        link.send(b"hi"); link.recv(60)
        samples = []
        for i in range(20):
            t0 = time.perf_counter(); link.send(b"p%d" % i); link.recv(10)
            samples.append((time.perf_counter() - t0) * 1000)
        s = sorted(samples)
        print(f"round trip: median {statistics.median(s):.0f} ms, p90 {s[17]:.0f} ms, max {s[-1]:.0f} ms")
    else:
        link.recv(60); link.send(b"hi")
        try:
            while True:
                m = link.recv(30)
                if m is None:
                    break
                link.send(m)
        except Closed:
            pass
    link.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--relay", default=LOCAL)
    p.add_argument("scenario", nargs="?", default="all",
                   choices=["all", "passkey", "wrong", "retry", "crowd", "reuse", "latency", "pingpong"])
    p.add_argument("role", nargs="?", choices=["host", "join"])
    p.add_argument("code", nargs="?")
    a = p.parse_args()
    print(f"relay: {a.relay}")
    if a.scenario == "pingpong":
        return pingpong(a.relay, a.role, a.code)
    table = {"passkey": s1_custom_passkey, "wrong": s2_wrong_passkey, "retry": s3_retry_after_failure,
             "crowd": s4_third_party_crowding, "reuse": s5_room_reuse, "latency": s6_latency}
    for name, fn in table.items():
        if a.scenario in ("all", name):
            fn(a.relay)
    print("\nspike finished")


if __name__ == "__main__":
    main()
