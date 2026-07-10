# Learnings: driving NetHack (nethack.alt.org) from an agent via tmux

Distilled from three lives of buttsquid the dwarven Valkyrie (NetHack 5.0.0 on NAO).
Game 1 died T:259 (Dlvl 1, mimic+fox). Game 2 died T:2762 (Dlvl 9, owlbear while
fainted from starvation). Game 3 in progress and outpacing both.

## Gameplay rules (each purchased with hit points)

1. **Read the HP field after every combat exchange.** The message line lies by
   omission; the status bar doesn't. Game 1 went 18→0 HP across three exchanges
   while I only read messages.
2. **Never blind-loop attack commands.** One swing, one full screen read.
   Blind-looping killed my own kitten (game 1) and punched a peaceful gnome
   (game 3). Monsters move between your keystrokes.
3. **Food > piety > loot.** Eat at "Hungry", never coast to "Weak" — Weak can
   become *fainting mid-fight*, which is how game 2 ended (owlbear, unconscious).
   Never sacrifice an edible corpse while hungry. Lichen corpses never rot; bank them.
4. **Farlook (`;`) anything you don't recognize before touching it.** Floating
   eye = paralysis on melee. Green mold = passive acid. Yellow light = blindness
   bomb. Acid blob = passive acid. Nymph = theft. Also: many scary glyphs are
   statues. `;<dir>.` as a single burst, one direction key per square.
5. **Retreat is a first-class move.** Stairs under your feet are an escape hatch;
   monsters don't follow instantly. Ghosts you can't hit (AC -5 vs low Dex) are
   walls, not fights — walk around them. Boulders that won't budge: reroute.
6. **Emergency toolkit, in order:** known healing potion → scare monster scroll
   (read it, everything flees) → stairs → *then* prayer. In this 5.0 build prayer
   never fixed a trouble (cursed boots ×2, blindness) despite "Tyr is pleased" —
   treat prayer as alignment maintenance only.
7. **Curse discipline.** Wear-testing boots got me cursed fumble boots: welded on,
   ~1600 turns of tripping, fell down literally every staircase (6×). BUC-test on
   altars (drop items; no flash = uncursed), price-ID in shops. Scroll of remove
   curse is the real fix ("You feel like someone is helping you").
8. **Answer prompts explicitly.** `Enter` takes the default, and the default for
   "Eat it? [yn] (n)" throws your opened tin on the floor.
9. **Identification on the cheap:** engrave-test wands (E, digging/fire/etc. give
   distinctive messages; silence = boring wand), watch monsters use items (gnome
   lord drinking a ruby potion = healing family), altar flashes, shop prices.
10. **Class notes (dwarven Valkyrie):** starts with *spear*, not long sword — no
    Excalibur without finding one. St 18/xx one-shots early orcs/gnomes. Dwarves
    get peaceful dwarves but *hostile gnomes* in the Mines — except some are
    peaceful anyway: farlook before stabbing. #enhance spear at XL3-4.

## tmux/TUI driving (the meta-game)

- **`--More--` prompts eat queued keystrokes.** This was the root cause of most
  "the game ignored my command" confusion. Before acting, clear prompts
  (`Enter`/`Escape`/`Space`); after acting, expect one.
- **The status line `T:` counter is ground truth for "did my input register".**
  Frozen `T:` across several keys = pending prompt, illegal move, or hung ssh.
  A hung ssh looks exactly like a stuck prompt; NAO restores the save on reconnect.
- **The travel (`_`) cursor does NOT start at @.** Read the real cursor with
  `tmux display -p '#{cursor_x} #{cursor_y}'`, steer with computed number-key
  bursts, verify, then `.`. Same trick locates @ authoritatively when the map
  drawing is ambiguous (screen rows shift as message lines come and go).
- **tmux `send-keys` interprets key names.** `F4` is a function key (opened the
  options menu), `Left` sends `ESC [ D` which NetHack read as `ESC` + `[` + `D`
  (= the Drop menu). Send literal chars as separate args: `send-keys F 4`.
- **number_pad is on for this account**: movement is 1-9, `5`/`g` rush, `G` run,
  `_` travel, `s` search, `o<dir>` open, `C-d <dir>` kick, `F <dir>` fight.
  h/j/k/l are NOT movement (h = help).
- **Doorways forbid diagonal moves/attacks** — a "dead" attack key often means
  you're standing in a door. Step orthogonally first. Doors also only open
  orthogonally (`o4`, never `o7`).
- **Dungeon feature sounds are worth reading**: "counting coins" = vault,
  "cash register" = shop, "water falling on coins" = fountain w/ gold nearby.
- Helpers built: `nh.sh` (send keys + capture), `travel.sh X Y` (cursor-steered
  travel), `hit.sh <dir>` (one attack, then message + HP + local map around @).
