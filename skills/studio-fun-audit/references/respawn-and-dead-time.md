# Respawn and dead time: the four legs, with the shipped designs behind them

The published record on one-life shooters that work converges on four things a no-respawn format needs. When a one-life format feels bad in a playtest, the question is not whether no-respawn is wrong; it is which legs are missing. The same four legs score every dead state in a respawning format too.

## Leg 1: cap the dead time

Shipped one-life rounds run short. Rainbow Six Siege ranked rounds are three minutes plus a forty-five-second preparation phase; Counter-Strike rounds under two minutes (1:55 plus a short freeze); Valorant rounds one hundred seconds. Nobody ships five-minute spectate sentences. Measure both the length of one dead stretch and the share of a whole match a player spends unable to act, because short rounds in a long first-to-N match still add up, and record both from the structured playtest report rather than from a design value.

## Leg 2: give the dead a job

Ubisoft's design post on Siege's one-life rule names the failure mode directly: the no-respawn rule had faded out of the genre because once a player is dead they do not have much to do. Siege's answer is Support Mode: dead players operate drones and cameras and become the team's information source, so they are actively involved the whole time. The designers' fear had been that only hardcore players would accept one life; instead, skills beyond twitch aim (communication, planning, leadership) became decisive, and trash talk turned into coordination.

Valorant gives the dead the same job informally (pinging the full map, calling damage, watching gaps) and a second job through its economy: spectating doubles as next-round buy planning, credits, loss bonuses and save decisions. Counter-Strike spectating works the same way.

The job has to use a verb that survives death. A spectating player whose primary kind rested on positioning and aim reading still exercises it while watching; a spectating player whose primary kind rested on a movement verb has lost the game's main source of sensation and challenge entirely, and no amount of camera is a substitute. That difference decides whether a format can keep waiting at all.

## Leg 3: make deaths readable

High lethality is accepted when a death reads as the player's own readable mistake. Cheng's three-to-five-second rule (full health to death, time to recognize, assess and react) is the same principle from the tuning side. Deaths that feel sudden or random, such as a blow the player never saw coming in a fight with a lot of vertical movement, spend patience instead of building tension. The skill's step 4 sets a per-project window on a slider and measures the share of recorded deaths that met it.

## Leg 4: let stakes convert spectating into drama

One life plus high lethality makes the one-against-many clutch the emotional peak of the genre, and the dead teammates are its audience. Riot chose this deliberately for Valorant: lethality is high and you do not respawn, with Counter-Strike, Call of Duty 4 and Siege cited as the inspirations and the respawning hero shooters pointedly not.

## Why the respawning hero shooter went the other way

Overwatch's continuous objectives (escort, control, push) make death a tempo cost rather than an elimination: the fight continues without you and the cost is the respawn timer plus the walk back. Its recurring enemy is trickling, players staggering back in one by one, answered first with Group Respawn (October 2023) and then Wave Respawns (Season 12). Its original director later said the team had put all its eggs in the player noticing whether the team won or lost and had downplayed individual contribution, and that he would surface individual contribution more. Lesson for any mode: check that each role's contribution is visible to its own player, not only to the team.

## Hybrids that keep one-life stakes but soften the wait

- **Carry-back revival (Apex Legends banners).** A dead teammate's banner can be carried to a respawn beacon. The dead player stays because return is possible, and the rescue becomes an emergent mission for the living.
- **Earned return (Warzone's Gulag).** First death becomes a one-on-one duel for redeployment, and waiting players spectate the pit. Dead time becomes a spectator sport with a skill-based exit.
- **Revive tokens and shared pools.** A shoot-em-up's designer postmortem credits a revive-token rule, with team credit lost only on a full wipe, with a night-and-day transformation. A shared team pool of respawns is the same pattern: respawns exist, but each one spends a team resource, so kills keep their stakes. This is the one respawn design that fixes leg 4 as well as leg 1.
- **Mode ladders (Valorant).** The no-respawn core is protected by giving players other doors in: a short first-to-five mode, a quick spike mode, respawning deathmatch and team deathmatch.

## Diagnosis template

Per format and per role, mark each leg `present`, `weak` or `absent`, from playtest reports rather than intuition:

| Leg | Format A, role 1 | Format A, role 2 | Format B, role 1 | Format B, role 2 |
|---|---|---|---|---|
| 1 Cap | | | | |
| 2 Job | | | | |
| 3 Readability | | | | |
| 4 Stakes | | | | |

Name the weakest leg per format. Then write the prototype that separates "the rule is wrong" from "the wait was empty and the deaths unreadable": for a one-life format, that is usually a branch that gives the dead an information job (free camera plus team pings on enemy position and objective state) and a telegraph pass, A/B tested against plain spectating, with the measurements fixed before the build: dead time per death and per match, what dead players did while dead, share of readable deaths, and the owner's own report.
