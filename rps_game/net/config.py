"""Network constants and where to find the mailbox server."""
from __future__ import annotations

import os

# Community-run public mailbox of the Magic Wormhole project (no account needed).
# Both players must use the same one. Override with --mailbox or RPS_MAILBOX to
# self-host (see the README).
DEFAULT_MAILBOX = "ws://relay.magic-wormhole.io:4000/v1"

# Namespaces our rooms away from other Wormhole apps; the suffix is the wire version.
APPID = "github.com/SohanurRahmanSohan43/rps_game/dual/v1"
PROTOCOL_VERSION = 1

MAX_MESSAGE_BYTES = 4096        # nothing legitimate is anywhere near this
MAX_WRONG_PASSKEYS = 3          # live guesses before the host burns the room
MAX_NAME_TRIES = 5              # name re-prompts during one handshake
MAX_RECONNECTS = 3              # host re-dials if the mailbox connection drops

HOST_LOBBY_TIMEOUT = 15 * 60    # how long a host waits for a friend
JOIN_TIMEOUT = 90               # how long a joiner waits for the host to answer
STEP_TIMEOUT = 60               # any single handshake reply
HUMAN_TIMEOUT = 180             # replies that wait on a person (new name, accept/decline)
POLL_SLICE = 0.2                # how often waits check for Esc / redraw

COMMIT_TIMEOUT = 120            # how long we wait for the other player to lock in a move
REVEAL_TIMEOUT = 20             # once both have locked in, the reveal is just network time
REMATCH_TIMEOUT = 120           # how long we wait for an answer to "play again?"
PING_INTERVAL = 5.0             # heartbeat; also measures round-trip time
LIVENESS_TIMEOUT = 30.0         # silence this long and the other player is considered gone


def mailbox_url(cli_value: str | None = None) -> str:
    """--mailbox beats $RPS_MAILBOX beats the public default."""
    return cli_value or os.environ.get("RPS_MAILBOX") or DEFAULT_MAILBOX
