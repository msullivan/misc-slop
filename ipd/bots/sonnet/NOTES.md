# sonnet

Generous tit-for-tat with a one-shot exploitation probe.

- Open with C; copy the opponent's last move.
- After an opponent D, forgive with small probability (8%, 15% in mutual defection). This breaks echo loops against other retaliators and noisy bots.
- Give up (always D) against opponents who have defected on all of the first 12 rounds, or on at least 27 of the last 30.
- After 25+ rounds in which the opponent never defected, probe once with a D. If they don't answer it with D, they are an unconditional cooperator, so keep defecting. Stop if they ever defect back. The probe costs about 1 point against retaliators.
