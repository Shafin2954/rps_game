# Magic Wormhole feasibility spike

Throwaway code that checks whether Magic Wormhole's mailbox can carry Dual Player.
It is **not** part of the installed package.

```bash
python3 -m venv .venv-spike && . .venv-spike/bin/activate
pip install magic-wormhole            # add magic-wormhole-mailbox-server to run one locally
```

## Run every scenario against a local mailbox
```bash
pip install magic-wormhole-mailbox-server
twist wormhole-mailbox --port tcp:4000:interface=127.0.0.1 &
python spike/run_spike.py
```

## Measure real latency to the public mailbox (what matters for players)
One machine, round trip through the mailbox:
```bash
python spike/run_spike.py --relay ws://relay.magic-wormhole.io:4000/v1 latency
```
Two machines in different places (the realistic test). Pick any 8-10 digit number:
```bash
# machine A
python spike/run_spike.py --relay ws://relay.magic-wormhole.io:4000/v1 pingpong host 55501234-testpass
# machine B (start within ~60 seconds)
python spike/run_spike.py --relay ws://relay.magic-wormhole.io:4000/v1 pingpong join 55501234-testpass
```
Machine A prints median / p90 / max round-trip time. Anything under ~500 ms is comfortable
for a turn-based game.
