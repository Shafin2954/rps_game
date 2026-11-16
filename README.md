# rps-game-cli

Rock Paper Scissors for your terminal, with ASCII hands, a countdown animation,
best-of-N matches, an adaptive computer opponent and a screen-reader friendly mode.

## Install

Requires Python 3.10 or newer.

```bash
pipx install git+https://github.com/SohanurRahmanSohan43/rps_game.git
# or, from a clone:
pip install -e ".[dev]"
```

## Play

Run `rps` to open the menu:

```
Main menu
> Start Game
  Stats
  Exit
        Start Game > Select a mode
        > Single Player        -> difficulty (Easy / Normal / Hard)
          Dual Player (online, in progress)   -> Create game / Join game
          Multiplayer (coming soon)
```

Use the arrow keys and Enter (Esc goes back one level). In `--plain` mode the menus
are numbered lists you answer by typing.

Skip the menu with flags:

```bash
rps -d hard            # straight into an unlimited game (easy | normal | hard)
rps -d easy -r 10      # exactly 10 rounds, highest score wins (ties are possible)
rps -f 3               # first to 3 wins takes the game (draws don't count)
rps -b 5               # same as -f 3, phrased as best of 5
rps --plain            # no art, colour or animation; type words and press Enter
rps --no-animation     # keep the art, skip the countdown
rps --stats            # lifetime statistics (saved between sessions)
rps --no-save          # play without recording the session
rps --reset-stats      # delete saved statistics
rps --update           # upgrade from GitHub
python -m rps_game     # same as `rps`
```

The screen is redrawn every round: fists, a countdown, the reveal, then the
scoreboard updates and the hands are wiped for the next round. Stats are stored in
`~/.local/share/rps-game-cli/stats.json` (platform equivalent elsewhere; override
with `RPS_STATS_FILE`).

### Dual Player

Two players on two devices, anywhere. Both of you need the game, an internet connection and a
way to share a room code and passkey (a chat message is fine).

- **Create game:** your name, a passkey (type your own twice, or let the game generate three
  random words), which side of *your* screen your hand appears on, and the game length
  (a set number of rounds, or first to N wins). You then get a room code to share. While you
  wait, `p` shows your passkey and `Esc` cancels.
- **Join game:** the room code, your name, the passkey, and your side. You are shown the host's
  game settings and can accept or decline.
- Names are required and must differ from your opponent's after normalisation (case, spacing and
  full-width letters are ignored). If yours clashes you are asked for another.
- **Playing:** both players pick a move, and both see "Bob has locked in" as soon as the other
  has chosen. Each round shows both hands on the sides you each chose, the verdict, and the
  scoreboard (your connection's round-trip time is shown in the title). When the game ends you can
  *Play again*, which needs both players to agree and reuses the connection, so there is no new
  passkey to enter, or return to the menu.
- **Leaving is a forfeit.** Quitting (you are asked to confirm), closing the program, losing your
  connection for 30 seconds or taking more than two minutes to choose counts as a win for the other
  player.
- Statistics for online games (head-to-head) are coming soon; they are not recorded yet.

**How it stays private and safe**

- Connections go through the community-run [Magic Wormhole](https://magic-wormhole.readthedocs.io)
  mailbox. Your passkey is never sent: it is only used for a password-authenticated key exchange,
  so the mailbox (and anyone watching the network) cannot read the game or guess the passkey
  offline.
- A wrong passkey fails on both sides. The host's room closes after three wrong attempts.
- **Fair rounds.** Each round both players first send a hash of their move plus a random value
  and only then reveal them, and each checks the other's reveal against the hash. A modified game
  therefore cannot wait to see your move before choosing its own, and cannot change its mind
  afterwards. A mismatch ends the game and you win. The two games also compare a running hash of
  all earlier rounds, so they can never silently disagree about the score.
- Everything received from the other side is validated strictly (size, types, names).
- What the mailbox *can* see: your IP address, the room code and message timing, not names or
  moves. The default mailbox address is plain `ws://`, so a network observer sees those too.
- No guarantee of uptime: the public mailbox is volunteer-run. Both players must use the same one.

**Self-hosting the mailbox** (optional, for a private or more reliable setup):

```bash
pip install magic-wormhole-mailbox-server
twist wormhole-mailbox --port tcp:4000          # on a machine both players can reach
rps --mailbox ws://YOUR-HOST:4000/v1            # both players, or set $RPS_MAILBOX
```

### Stats menu

`Stats` in the main menu shows your lifetime results and holds two preferences:
**Show stats after each game** (off by default: the results screen then shows only the game
you just played) and **Reset statistics**. Head-to-head results against other players will
arrive with Dual Player.

Game keys: `r` / `p` / `s` (or `1` / `2` / `3`), `q` to quit. In `--plain` mode you can
also type the full word. Set `NO_COLOR=1` to disable colour.

## Difficulty

- **easy**: pure random.
- **normal**: counters your most frequent recent move most of the time.
- **hard**: reads sequences in your play (e.g. "after paper you usually throw
  scissors", or R-P-S cycles) and counters the prediction, with a little randomness.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

`pip install -e ".[dev]"` also installs a local mailbox server, which the network
integration tests start on a random local port (they never touch the public one).

Layout: `net/` (protocol, session handshake, transport, connection screens) · `engine.py` (pure rules) · `strategies.py` (computer players) ·
`ui.py` (menus, screens, input) · `menu.py` (menu flow) · `stats.py` (saved stats) · `art.py` · `terminal.py` (keyboard) · `cli.py` (entry point).
