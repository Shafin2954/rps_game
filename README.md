# rps-game-cli

Rock Paper Scissors for your terminal, turned into a game of reading minds.

- **The Gauntlet** - a ten-floor climb. Every foe has hit points, a personality and a *tell*;
  you have Focus to spend on techniques and a relic to choose after every fight. The Oracle
  waits at the top, and it has been watching you the whole way up.
- **The Oracle** - a computer opponent that runs a council of predictors against you and
  cannot be out-guessed, only out-randomised.
- **The mind reader** - after a game, see how predictable you were and which habits gave
  you away.
- **Dual Player** - play a friend online with passkey-protected, cheat-proof rounds, chat
  while you play, and keep a head-to-head record.
- **ASCII theatre** - hands lunge and collide: rock crushes, paper wraps, scissors slice.
  Beaten foes crumble to dust, big wins set off fireworks, and your opponents talk back.
- Rank, experience and achievements across every mode, and a screen-reader friendly plain
  mode for all of it.

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
        > Single Player        -> difficulty (Easy / Normal / Hard / Oracle)
          Dual Player (online) -> Create game / Join game
          Gauntlet             -> New run / Daily Run / Enter a seed
          Multiplayer (coming soon)
```

Use the arrow keys and Enter (Esc goes back one level). In `--plain` mode the menus
are numbered lists you answer by typing.

Skip the menu with flags:

```bash
rps --gauntlet         # climb the Gauntlet (a new random tower)
rps --daily            # today's Daily Run: the same tower for everyone
rps --seed CAT42       # the tower built from a seed (share it to race a friend)
rps -d hard            # straight into an unlimited game (easy | normal | hard | oracle)
rps -d easy -r 10      # exactly 10 rounds, highest score wins (ties are possible)
rps -f 3               # first to 3 wins takes the game (draws don't count)
rps -b 5               # same as -f 3, phrased as best of 5
rps --plain            # no art, colour or animation; type words and press Enter
rps --no-animation     # keep the art, skip the countdown, clashes, splash and fireworks
rps --stats            # lifetime statistics (saved between sessions)
rps --profile          # your rank, Gauntlet records and achievements
rps --no-save          # play without recording the session
rps --reset-stats      # delete saved statistics, rank and achievements
rps --update           # upgrade from GitHub
python -m rps_game     # same as `rps`
```

The screen is redrawn every round: fists, a countdown, the reveal and the clash (the
losing hand is crushed, wrapped or cut in two), then the scoreboard updates and the
hands are wiped for the next round. Winning a game sets off fireworks; any key skips
them, and the opening splash. Stats are stored in
`~/.local/share/rps-game-cli/stats.json` (platform equivalent elsewhere; override
with `RPS_STATS_FILE`); your rank, achievements and records sit next to it in
`profile.json` (`RPS_PROFILE_FILE`).

### The Gauntlet

Ten floors, ten foes, one life. Classic rules decide who wins each round; the Gauntlet
decides what a win is worth.

- **Hit points.** You start with 14. Win a round and the foe takes damage (2, before
  relics); lose one and you take theirs. A fight ends when someone reaches 0. You heal
  3 HP after each fight you win, and that is all the healing there is unless you rest.
- **Tells.** Every foe is introduced with a line that hints at how it thinks ("Never throws
  the same thing twice in a row", "Certain you are about to repeat yourself"). Early foes
  can be solved outright. Later ones add noise, armour, thorns and real pattern reading.
  The strip of recent throws under the hands is there for you to study.
- **Focus and techniques.** Losing or drawing a round earns 1 Focus (you hold up to 4).
  Spend it before you throw, one technique per round:

  | Key | Technique | Focus | Effect |
  |-----|-----------|-------|--------|
  | `f` | Foresight | 2 | Rules out one throw the foe will not make this round |
  | `g` | Guard     | 1 | You take no damage this round |
  | `c` | Charge    | 2 | If you win this round, you deal double damage |

- **Relics.** After each fight choose one of three relics, or rest for 5 HP instead.
  There are 22: *Granite Knuckles* (rock wins +2), *Momentum* (each win in a row hits
  harder), *Second Wind* (survive a killing blow once per fight), *Third Eye* (cheaper
  Foresight), *Static Charge* (draws hurt the foe)... A relic that rewards one throw also
  tempts you into throwing it, and the foes on the upper floors notice.
- **The ladder.** Two rookies, two scrappers, **the Warden** on floor 5 (it has watched
  every throw of your climb and counters your favourite), two veterans, two masters, and
  **the Oracle** on floor 10. Sixteen regular foes are shuffled into each run.
- **Seeds.** The same seed always builds the same tower with the same relics on offer, so
  a seed is a challenge you can hand to a friend. The **Daily Run** uses today's date.
- **Score.** Each floor cleared is worth 100 points times its number, a fight won without
  taking damage adds 100, and conquering the tower pays a bonus that grows with the health
  you have left.

In a fight: `r` / `p` / `s` throw, `f` / `g` / `c` arm a technique (press again to cancel
Guard or Charge), `i` shows the foe's traits and your relics, `q` abandons the run. Plain
mode takes the same letters, or the words, one per line.

The foes talk. Each has its own lines for winning a round, losing one, falling and
finishing you off, and they stay in character, so listen: Echo's "You repeated yourself.
They always do." is a tell too. The Oracle only speaks when it is sure, and then it tells
you exactly how it read you ("After a loss you always make the same step. I was already
there."). It does the same in single player with `-d oracle`.

### The mind reader, rank and achievements

Any single-player game of eight rounds or more ends with a reading: how often a pattern
reader would have beaten you (33% is pure chance), a verdict from *Unreadable* to *An open
book*, and your strongest habits in words ("After a loss you switch to the one throw
neither of you used"). Lifetime habits appear on the statistics screen.

Every mode earns experience toward a rank (Novice to Legend) and there are 17 achievements
to unlock. `Stats` in the main menu shows your profile, achievements and head-to-head
record; `rps --profile` prints the first two.

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
- **Chat.** Press `t` on the round screen (or while waiting for the other player) and type;
  Enter sends, Esc cancels. The latest lines sit under the scoreboard on both screens, and
  the game-over menu has *Send a message* for the "gg". In `--plain` mode type
  `say your message` instead of a move. Messages are one short line of ordinary characters:
  anything that could garble a terminal is refused on both ends. Chat needs both games on
  4.1 or newer; against an older game it is simply switched off and everything else works.
- **Leaving is a forfeit.** Quitting (you are asked to confirm), closing the program, losing your
  connection for 30 seconds or taking more than two minutes to choose counts as a win for the other
  player.
- **Head-to-head.** Every online game is added to your record against that player (it
  follows their installation, not their name, so a renamed friend keeps their history and
  two different Alices stay separate). See it under `Stats > Head-to-head`.

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
- Everything received from the other side is validated strictly (size, types, names, chat
  text). A flood of chat messages is dropped rather than shown.
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

`Stats` in the main menu shows your lifetime results, your **Profile** (rank and Gauntlet
records), your **Achievements** and your **Head-to-head** record against other players. It
also holds two preferences: **Show stats after each game** (off by default: the results
screen then shows only the game you just played) and **Reset statistics**, which wipes your
results, rank and achievements.

Game keys: `r` / `p` / `s` (or `1` / `2` / `3`), `q` to quit, `t` to talk in an online game. In `--plain` mode you can
also type the full word. Set `NO_COLOR=1` to disable colour.

## Difficulty

- **easy**: pure random.
- **normal**: counters your most frequent recent move most of the time.
- **hard**: reads sequences in your play (e.g. "after paper you usually throw
  scissors", or R-P-S cycles) and counters the prediction, with a little randomness.
- **oracle**: eleven small models of you (your favourite throw, what you do after your own
  last throws, how you answer the computer's, how you react to winning and losing, the
  longest stretch of earlier play that looks like right now), each second-guessed three
  levels deep. It follows whichever has been right lately and plays pure chance when none
  has. A truly random player holds it to a draw; a cycle, one repeated throw or a
  win-stay-lose-shift habit loses nine rounds in ten, and even a mild bias toward one
  throw gives it a steady edge.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

`pip install -e ".[dev]"` also installs a local mailbox server, which the network
integration tests start on a random local port (they never touch the public one).

Layout: `gauntlet/` (`rules.py` the duel, `foes.py`, `banter.py`, `relics.py`, `run.py` one climb, `screens.py`, `play.py`) ·
`oracle.py` (the Oracle) · `insight.py` (the mind reader) · `profile.py` (rank, achievements, head-to-head) ·
`fx.py` (the ASCII effects, as pure frame data) · `chat.py` (message rules and the conversation log) ·
`net/` (protocol, session handshake, transport, connection screens) · `engine.py` (pure rules) · `strategies.py` (computer players) ·
`ui.py` (menus, screens, input) · `menu.py` (menu flow) · `stats.py` (saved stats) · `art.py` · `terminal.py` (keyboard) · `cli.py` (entry point).

The Gauntlet's rules are pure and seeded: `tests/test_gauntlet_run.py` plays whole runs
without a screen, and includes a balance guard (blind luck must rarely reach the top).
