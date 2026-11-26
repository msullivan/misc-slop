# Iterated prisoner's dilemma tournament: rules

## The game

Two bots play a match of many rounds. Each round both simultaneously choose
`C` (cooperate) or `D` (defect):

| you \ them | C | D |
|---|---|---|
| **C** | 3 | 0 |
| **D** | 5 | 1 |

The number of rounds is random: after every round the match ends with
probability 1/200 (so matches average 200 rounds, with no knowable last round;
there is a hard cap of 2000).

## The tournament

Round-robin. Every bot plays every other bot, and also a copy of itself,
5 matches per pairing. A bot's score is its **mean points per round** over all
its matches. Higher is better.

The tournament is held three times. After each, every author gets the full
move-by-move transcript of all of their own bot's matches (opponents named) in
`bots/<name>/transcripts/roundN.txt`, plus the standings in
`results/roundN/standings.md`, and may revise their bot. All three results are
reported; the third is the final standing.

## A submission

A directory `ipd/bots/<name>/` containing an executable file named `run`
(any language installed on this machine; a `#!` script is fine). If an
executable `build` is also present it is run once, in that directory, before
each tournament.

A fresh `run` process is started for every match, with the bot's directory as
its working directory. It is not told who the opponent is. Protocol, over
stdin/stdout, one line per message:

1. Write your move for this round: `C` or `D`, then a newline. **Flush.**
2. Read one line from stdin: your opponent's move for that round (`C` or `D`).
3. Repeat. When stdin reaches EOF the match is over; exit.

Limits: 5 seconds for the first move, 1 second for each later one. A bot that
times out, exits early, or prints anything else on stdout has failed that
match: from that round on it scores 0 and is treated as playing `D`. (stderr is
free for debugging, and is shown to you in the transcript if you fail.)

## Conduct

- Do not modify anything outside your own bot directory.
- Do not interfere with other bots or with the harness (no killing, signalling
  or starving other processes, no tampering with files). No network access.
- Do not commit to git; the organiser does that.

## Testing

    python3 ipd/tournament.py match ipd/bots/<name> ipd/examples/tit_for_tat
    python3 ipd/tournament.py match DIR_A DIR_B -n 50 --games 3

`ipd/examples/` has a few trivial bots to test against. They are not entered
in the tournament.
