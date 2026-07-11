# NetHack runs — buttsquid (NAO, NetHack 5.0.0)

## GAME 1 POST-MORTEM (died T:259, Dlvl:1, 73 pts — small mimic + fox)
Sequence: opened a door into a room with a fox + disguised mimic at XL1/18HP,
fought both in the doorway, went 18→0 HP in ~3 exchanges without ever noticing.
Contributing: luck penalty from killing own kitten (missed a lot).
Carried but never used: potion of extra healing (!), ring of invisibility, +4 flail.

### RULES FOR NEXT GAME (discipline!)
1. **Read the HP field on the status line after EVERY combat exchange.** Not just the message line.
2. HP < 1/2: disengage. HP < 1/3: quaff unknown potions / PRAY (one early prayer is safe).
3. Never blind-loop attack commands — one swing, one screen read.
4. Don't melee two unknowns at XL1; retreat into a real corridor, not a doorway square.
5. Remember **Elbereth** (E then write in dust) scares most melee monsters incl. mimics/foxes.
6. Farlook (`;dir.` as ONE key burst) anything unfamiliar before engaging.
7. XP matters: kill safe stuff early; don't wander at XL1 forever.


## Character
- Lawful female **dwarven Valkyrie**, St:14 Dx:16 Co:17 In:8 Wi:8 Ch:12
- Start: HP 18, AC 6

## Inventory (start)
- a: blessed +1 dwarvish spear (wielded)
- b: +0 dagger (alt)
- c: uncursed +3 small shield (worn)
- d: food ration
- e: oil lamp

## Strategy
- Melee everything early (valk is strong), keep kitten fed/alive if convenient
- Dip for Excalibur at XL5+ if a fortune presents; main goal: dive sensibly, find Sokoban after Dlvl 2-4 branch
- Pray to Tyr when HP critical (once early is safe)
- Watch for: floating eyes (NEVER melee), water moccasins, dwarves with picks

## GAME 2 (current) — dwarven Valkyrie #2
- St:13 Dx:13 Co:20, HP18, kitten. Turn ~250: **AC 0** (found splint mail T:4!)
- Inventory highlights: **h = wand of digging** (engrave-IDed), g = white gem (kitten found),
  i = brown potion, flail... no wait that was game 1. b = blessed dagger, a = +1 dwarvish spear.
- Dlvl:1 map: fountain in START room (NE-ish) — Excalibur at XL5. VAULT on level (coin sounds).
  Dead-end corridor N of big W room searched 18× — nothing. `>` in far-E room.
- T:250 descending to Dlvl:2. Kitten in tow.
- Dlvl:2: rolling boulder trap (dead tourist +2 food rations, 3 total). `>` room NE via corridor door.
- T:330 Dlvl:3: fell down stairs (boots!). **k = CURSED -1 snow boots = likely FUMBLE BOOTS, welded on.**
  Wear-test lesson: check curse BEFORE wearing footwear. Prayed T:372: "Tyr is pleased" but boots still cursed.
  Need: scroll of remove curse / altar / next prayer window (~T:1300+).
- Dlvl:3 start room: green mold (avoided), empty large box #3, statue of newt. $35.
- Dlvl:4: XL2 (goblin kill). Violet + orange gems. Dropped ring mail. Door-to-rock dead end (27 searches, nada).
- Dlvl:5 (T~1000): **SHOP on level** (heard shopkeeper) — not found yet. Fountain room mid-map.
  Got: scare monster scroll (s! panic button — stand on it), redwood wand t (unid, boring engrave), towel u.
  Two stuck boulders blocking corridors E. $87. Kitten lost on Dlvl3 (left behind at stairs).
- travel.sh helper: ./nethack/travel.sh X Y — steers travel cursor from actual cursor pos (it does NOT start at @!)
- Dlvl:6 (T~1650): hidden corridor+locked door W of start (found by searching dead end!), paper golem inside
  (dropped 2 blank scrolls v,w). Hidden room has `>` + chest (2 emerald potions x). Floating eye in NW room —
  daggers thrown, recovered. Fog cloud: missed it 15× (?!), just walked away. Rotten ration eaten, 1 ration left.
  Prayers at T372 + T1450 both "pleased" but boots STAY cursed — prayer won't fix them, need remove curse.
  Wand t (redwood) zapped at eye: NO effect message — probably nothing/opening. 2 more stair-falls (5 total).
- Dlvl:7 (T~1980): ORACLE level (centaur statues + 4-fountain sanctum, Oracle visible). XL4 (spider kills).
  Killed: 2 grid bugs, 3 cave spiders, elf zombie, Mordor orc, Uruk-hai. 2nd rotten ration → temp BLIND. NO FOOD left.
  Uruk-hai dropped: **scroll THARR = REMOVE CURSE → BOOTS OFF!!** + orcish helm (worn) + iron shoes (worn) → **AC -2**
  Scroll IDs this game: THARR=remove curse, LOREM IPSUM=scare monster, NR 9=fire, STRC PRST=?nothing happened
  PLAN: grind to XL5 → Excalibur dips at Oracle fountains → dig down. $116.
- **XL5 reached** (housecat kill). Realization: NO LONG SWORD = no Excalibur dips (dwarf valk has spear!). Want: long sword.
- Ate housecat ("bad idea" = alignment ding) + iguana + banana. Food precarious — eat fresh kills.
- Spear skill Basic→**Skilled** (#enhance). Helm+iron shoes+cloak from orc drops → **AC -2**.
- Dlvl:8: acid blob stalked me (weirdly fast, tanked 4 thrown hits); speared it, no splashback. `>` behind locked door W.
- **Wand of digging EMPTY** (had 4 charges: engrave + boulder + W-dig + down-dig). Keep for recharge scroll.
- Dlvl:9 (T~2470): wererat+summoned rats+orc mummy fight — HP 21/54, used scare scroll, killed mummy. Green gem.
  Nymph asleep W of start room (AVOID/kill at range — theft). Gems: 2 white, violet, orange, green.
- **T:2470 ssh connection HUNG** — game frozen, monitor watching for recovery. Game state saved server-side by NAO.
- hit.sh helper: one attack + full report (msg/HP/local map). USER FEEDBACK: never blind-loop attacks; check map each swing.
- Reconnected after hang (password from user). Resumed same state.
- Dlvl:9 finds: 9 SILVER arrows (d), 2 tins (1 wasted via default-n prompt — always answer y to "Eat it?"),
  booby-trapped door (KABOOM, survived). **ALTAR TO TYR (lawful!) at ~(23,13)** — BUC-tested unknowns: ALL uncursed.
  Moonstone ring worn: no message (unknown type, removed — hunger tax). 
- **PLAN: altar-camp. Kill wanderers → #offer fresh corpses to Tyr → artifact gift chance.**

## GAME 2 POST-MORTEM (died T:2762, Dlvl:9, killed by owlbear while FAINTED from starvation)
Chain of death: sacrificed BOTH rothe corpses while already Hungry → went Weak → owlbear arrived →
fought it anyway (grabbed, can't flee) → FAINTED mid-fight → crushed at 0 HP. 288 xp (XL5, 32 short of 6).
Death-ID reveals: emerald=healing, moonstone ring=sustain ability, redwood wand=CANCELLATION(3), balsa=undead
turning(6), white gem G=OPAL (real!), green=glass. Yellow-light blindness + rothe swarm nearly killed me earlier.

## GAME 3 POST-MORTEM (died T:4266, Dlvl:10 Mine's End, 4954 pts — "killed by an ape, while praying")
**Best run yet** (G1: 73pts/T259, G2: T2762/Dlvl9, G3: 4954pts/T4266/Dlvl10/XL7/AC0/70maxHP).
Death spiral: 3-warg pack (burned prayer #4 + full-healing + 2 healing potions) → rested in an EXPOSED corner
next to unexplored territory → 4-ape troop trickled in → cornered vs 3 attackers, walls N/NE/E → burned last
4 healing potions → potion gamble = BLINDNESS → prayed 170 turns after last prayer (too soon) → ape finished
me mid-prayer. HP 70→5→70(pray)→...→3→0 across ~130 turns of grinding attrition.

**Death-screen ID reveals** (write these into item-guessing priors):
- curved wand = **CANCELLATION (0:5)** — engrave-test shows NOTHING and zapping most monsters shows nothing.
  "No effect" ≠ junk wand! (Also: cancellation destroys the Catacombs level-teleporters per wiki 3.7 note.)
- milky potion = **SPEED** (was in pack the whole fight!), dark = **PARALYSIS** (quaffing it = certain death),
  purple-red ×2 = blindness (the fatal gamble), pink = object detection.
- scrolls: JUYED AWK YACC ×2 = identify (2 copies of an unID scroll ≈ identify, it's the most common),
  HAPAX LEGOMENON = create monster (glad I didn't read it mid-fight), EIRIS SAZUN IDISI = REMOVE CURSE
  (the one scroll-read gamble that PAID — uncursed the fumbling gauntlets mid-apes-fight).
- rings: engagement = cursed HUNGER (never wore it — good), 2× shiny = cursed -1 increase accuracy,
  iron = searching (should have worn this all game!).
- 3 daggers from the falling-rock pile = blessed +2! K-slot daggers were the best throwables I had.
- cloth spellbook = FIREBALL (uncastable at In:7 — dwarf Valk problem).
- 2 gray stones = TOUCHSTONES (stack-inference was right: same type; guess of flint wrong).
- Gem haul (died with): **2 DIAMONDS, emerald, 2 amethysts**, jet/jasper/fluorite/citrine/amber + ~12 glass.

### LESSONS → RULES FOR GAME 4
13. **Curse-test armor before wearing** (drop-test on altar, or just don't wear unID'd armor). The -1 gauntlets
    of fumbling caused: constant trips (interrupted travel), a BOTCHED Elbereth ("Elnereth") at HP 22, and
    weapon-drop risk all game. USER TIP: **pets won't step on cursed items** — drop the item and watch whether
    the pet avoids the square = free curse detection (another reason to keep a pet alive!).
14. **Elbereth is an escape tool, not a fighting platform.** Melee attacks FROM the square (and monster traffic)
    smudge dust engravings — I burned 3 engravings this way and got surprise-attacked each time it silently died.
    Pattern: engrave → REST ONLY → leave when healed. Verify with `:` every few turns.
15. **Retreat has to happen at ~60% HP, not 30%.** Twice I kept fighting/resting in place at ~40/70 next to
    unexplored dark. The stairs `<` were ~15 squares away the whole time; climbing up = warg/ape packs don't follow.
16. **Don't quaff unknown potions as emergency heals** — 2/5 of my unknowns were instant-loss (paralysis) or
    fight-losing (blindness). Unknowns are for safe-time testing; emergencies need KNOWN healing only.
17. **Prayer cooldown is real**: ~1000+ turns. T4095 prayer worked (1330 elapsed); T4266 prayer (171 elapsed)
    got me killed mid-animation. Track "next safe prayer" in notes after every prayer.
18. **Clear every --More-- immediately.** A pending More silently ate ~80 rest keystrokes; I misdiagnosed it as
    a frozen game, stepped off Elbereth to "test movement", and took free hits. USER CORRECTION: resting (`.`)
    is ALSO refused while hostiles are visible, same as `s` search — you cannot rest-heal with monsters around,
    period. With hostiles present the options are: fight, flee, or hold on Elbereth without expecting regen.
19. Monster packs (3× warg, 4× ape) are the #1 killer of this build: 2+ adjacent attackers out-DPS spear+AC0.
    Fight packs only at true chokepoints (doorways/corridors, ONE exposed side) or ranged-kite them.
20. Blindfold + telepathy = free full-level monster scan. Do it on EVERY new level arrival (it found the mimics
    = gem chambers, and would have shown the ape den before I camped next to it).
21. **Domestic animals (large dog, kitten, pony) = recruits, not XP.** Throw food at them to tame. A pet
    fights alongside you, and won't step on cursed items (walking curse detector). Keep it alive (rule from
    Game 3's T:250 kitten disaster still stands: never blind-loop attacks near your pet).

## GAME 3 (finished) — Buttsquid III, dwarven Valkyrie, **St 18/02**
- T~404: XL3, AC5, HP 42/44, $20, Dlvl:4 of **THE GNOMISH MINES** (branch found on Dlvl:2 this time!)
- Route: D1 (fast, T108) → D2 (shop heard, not found; boulder-blocked corridor) → Mines entrance
- Mines 3: killed jackal"Slasher"(kitten's kill), rat, newts, hobbit (war hammer drop), gnome, gnome lord (4 daggers!)
  Retreated upstairs at 6HP once (rule 5 works). Lemni's GHOST (bones) unhittable — walked around it. Kitten left fighting it.
- Ruby potion = healing family (gnome lord drank one mid-fight, IDed by use)
- Inventory: +1 spear, 5+1 daggers, war hammer, crossbow+5 bolts, 7 arrows, lichen corpse (emergency food),
  pink/sky-blue potions (unid), 2 scrolls (unid), engagement ring (unid), red gem
- Mines 4: gnome pack ~5 converging in the dark. CAUTION: accidentally hit a PEACEFUL gnome (it "got angry") —
  farlook alignment before attacking in Mines as a dwarf!
- Mines 4 (T~650): killed FLOATING EYE with darts at range, ate corpse → **TELEPATHY intrinsic!**
  Found **ELVEN MITHRIL-COAT** in arrow-trap loot pile (dead adventurer) → **AC 0** at Dlvl 4. Dart traps, sleep-gas trap.
- Dlvl 5 = **ORC TOWN** (Minetown sacked variant!): named hill orc tribe "of Uulai" everywhere, NO shops/priest,
  iron bars + boulders sealing the plaza. Killed 5 orcs on the outskirts.
  **ORC-CAPTAIN with poisoned arrows nearly killed me**: 51→5 HP in 2 volleys, St 18/02→17, Co 18→17, maxHP 51→40.
  PRAYER SAVED ME: full heal + cured sickness. (Correction to rule 12: prayer DOES fix critical-HP/sickness troubles;
  it just ignores minor ones like cursed items.) Leprechaun stole ~$60 total (never melee-race a speed-15 thief).
  Loot: 11 candles (Izchak's looted stock!), 250 gold from orc "treasurer", scimitars.
- Dlvl 6: more Uulai orcs (10 killed total), imp, iguanas. Land mine (leg wound), pits everywhere. XL5.
- Dlvl 7 — ~~MINE'S END~~ **WRONG, it's just Mines 7!** (T:3229 found a `>` downstairs in dark SW area.)
  The "Mines levels 3 to 7" overview line only lists *visited* levels — rookie mistake, cost ~250 wasted searches.
  Peaceful gnome KING + lords + gnomes everywhere. Gem haul: 3 yellowish-brown, yellow, red, black, violet (7 total).
  Curved wand = boring engrave + no zap effect (nothing?). Fog cloud engulfed me → destroyed it → **XL6** (HP 61).
  USER CLARIFIED: the "on the ground" hint was about BONES loot, not the luckstone. Real Mine's End is deeper
  (wiki: 8th-9th branch level). Wiki variants: Mimic (gem piles w/ mimic fakes; glass-in-middle = luckstone pile),
  Wine Cellar (gem cache walled in NE — NEEDS DIGGING, get a pick-axe from a hostile dwarf),
  Catacombs (maze; luckstone at 1 of 3 fixed spots ON A LEVEL TELEPORTER — stepping on it TPs you up unless
  magic resistance; can also zap wand of tele at the stone). (Loadstone lookalike: kick-test before pickup.)
- T:3140-3150 WATER NYMPH stole my mithril-coat ("You gladly let her take your suit"), wore it, fled —
  chased and one-shot her, got it back + 9 darts + poisoned dart + 2nd engagement ring. Nymphs = kill-on-sight AT RANGE.
- Mines 7 NW dark warren explored: dart trap + falling-rock trap (3 daggers looted), hobgoblin, gecko, coyote killed.
- Dlvl 8 (Mines): big cavern rooms. Killed tanky "large dog" (5.0 dogs are BEEFY — Elbereth dance + 6 spear hits)
  — USER TIP: DON'T kill large dogs if you have any food: **throw food to TAME it** (it's a lost pet, and a
  large dog is a great early ally + curse-detector per rule 13). That fight should have been a recruitment.
  Also killed:
  giant bat, 3 elf zombies + rats + yellow light horde at a corridor mouth (blinded again — Elbereth+rest worked).
  Loot: FOOD RATION, 2 gray stones (kick-tested, stacked = same type = probably flint), towel, orcish pile w/
  cursed-later gloves + shiny ring + black gem. Falling-rock + pits + water squares ("flounder").
- Dlvl 9 (Mines): BLINDFOLD found — blindfold+telepathy = full-level monster scan (killer scouting trick!).
  Killed named orc Akh-ubaneu of Uulai → XL7 (HP 70). Peaceful gnomish wizard casting ambient buffs.
- **Dlvl 10 = MINE'S END, "Mimic of the Mines" variant** (4 m's on telepathy scan at level edges = gem-pile mimics!).
  Wiki: 7 hidden places (6 secret doors + 1 choke). REAL luckstone pile = ruby(bottom), red glass(mid), luckstone(top);
  loadstone pile = glass(bottom), ruby(mid). Mimic piles have diamond/emerald/amethyst + glass + mimic-as-gray-stone.
  ALL WALLS UNDIGGABLE. Found & looted 2 mimic chambers so far (secret doors ~5-25 searches, locked → kick):
  small mimic (violet+green+2white gems), large mimic (2violet+green+2white). Mimics = pushovers at a doorway.
  Killed hostile hobbit slingers (took sling), Uulai the orc chief (SILVER SABER + bag + gems + shiny ring #2!).
- **GLOVES OF FUMBLING (cursed)** — the "old gloves" from Dlvl 8. Constant trips/flounders, and they BOTCHED
  Elbereth mid-fight ("Elnereth")!! Nearly died to 3-warg pack: 70→5 HP. PRAYER #4 SAVED ME (Tyr, full heal,
  ~1300 turns since last). Killed all 3 wargs + homunculus. Pre-IDed full healing potion also burned mid-fight.
  TODO: remove curse for gloves; NEW RULE 13: curse-test unknown armor before wearing (drop-test or altar).
- Gem hoard: ~24 gems in Uulai's sack (4 white=diamond?, 2 green=emerald?, 6 violet=amethyst?, blue, reds, etc).
- Prayer log: T754, T2765, T4095 all successful (heal/cure). Next prayer safe ~T5200+.
- Learned: `travel.sh` / walking SWAPS places with peacefuls in 5.0 (no need to route around).
- Climbed out of Mines (T~1900-2150): recrossed orc town clean (captain switched to scimitar, never showed).
  Kitten STILL fighting Lemni's ghost on Mines 2 (~1700 turns!) — both unhittable, left them to it. Spear → Skilled.
  Killed 2nd floating eye with darts on Dungeons 3 (already have telepathy). Statue gallery room on D4 (ooze + zombie statues).
- Dungeons 4: hidden passage found E of chest room (searched dead-end corridor 25×). Locked door kicked open.
- Dungeons 5 (T~2555): 2 chests looted (3 scrolls: JUYED AWK YACC, PRIRUTSENIE, + old 2; dark/milky potions).
  **SKY BLUE = POTION OF HEALING** (quaff-IDed, 6 found — 5 left as emergency stash!). 2nd yellow gem (8 gems total).
  Fountain room W side. NO FOOD in pack — eating fresh corpses (newt, iguana OK).
- SOKOBAN: no second `<` found on D2/D3/D4 yet — must be in an unexplored corner; check when passing.
- GOAL: descend toward Oracle (D5-9), level up, find food + Sokoban. Kill-list: leprechaun (has ~$60 of mine).

### ADDITIONAL RULES FOR GAME 3
8. **FOOD > PIETY.** Never sacrifice an edible corpse when Hungry. Eat at "Hungry", never reach Weak.
9. Don't fight big melee bruisers (owlbear/rothe pack) while Weak/statused — flee first, they're slow.
10. Yellow lights: kill from range or just leave; blind + swarm = death spiral.
11. Answer item prompts ('Eat it?') explicitly — Enter takes the DEFAULT which may discard the item.
12. Prayer in NH5.0 seems to NOT fix troubles (boots, blindness twice) — treat prayer as alignment-only, not rescue.

## Progress log
- T:1 Dlvl:1 — started, small room, kitten adjacent
- T:100 Dlvl:1 — explored west half. Killed jackal + grid bug. **Fountain** in mid-west room (Excalibur later!).
  - Looted locked large box (forced w/ dagger): carrot, 2 scrolls (h: ABRA KA DABRA, i: VENZAR BORGAVVE), j: brilliant blue potion
  - Arrow trap in NW room killed a samurai: took 9 arrows (k), sling (l), iron ring (m, unid). HP 14/18
  - Boulder in corridor NW of first room (pushed once west, left it)
  - Unexplored: north doors in several rooms, south door `+` of NE room, SE corridor past first room
- T:250 — **KILLED MY OWN KITTEN** by blind-looping `F 8` after the lichen died and kitten stepped in. "Rumble of distant thunder" = luck penalty (~-5, decays over time). LESSON: check screen between attacks, never loop attacks blindly.
- `<` on Dlvl:1 is described as "branch staircase up" (NetHack 5.0 thing? investigate later)

## Helper
- `./nethack/nh.sh [-s sleep] [keys...]` — send keys + capture screen
  - tmux server socket: `tmux -L nethack`, pane target `0`

## Keybinding facts (verified via `?f` key lookup)
- number_pad is ON: move with 1-9 (4=W 6=E 8=N 2=S, 7/9/1/3 diagonals)
- `5` and `g` = rush prefix, `G` = run prefix (e.g. `G4` run west)
- Arrow keys DON'T work (raw ESC[x sequences get parsed as commands — Left = `ESC [ D` triggered Drop!)
- h/j/k/l are NOT movement (h = help menu)
- `_` = travel, `^P` = message history, `?f<key>` = what does key do
