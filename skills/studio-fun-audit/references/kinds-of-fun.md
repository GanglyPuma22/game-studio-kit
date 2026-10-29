# Kinds of fun: the vocabulary and its limits

Two vocabularies, one method. The audit uses the eight kinds as the shared words, the four keys as a cross-check, and the one-word method as the discipline that keeps a target honest.

## The eight kinds (MDA aesthetics)

From Hunicke, LeBlanc and Zubek, "MDA: A Formal Approach to Game Design and Game Research" (2004); the taxonomy is Marc LeBlanc's. The one-line glosses are the paper's own; the test question is this skill's, to be answered with a mechanic the player meets.

| Kind | Gloss | Test question |
|---|---|---|
| `sensation` | Game as sense-pleasure | What does the body feel: motion, music as feedback, the look? Name the input-to-feedback loop |
| `fantasy` | Game as make-believe | Who does the player become, and which rule makes the efficient behaviour feel like being that? |
| `narrative` | Game as drama | What unfolds, and does the player drive it? |
| `challenge` | Game as obstacle course | What is mastered, and what shows progress toward mastering it, including in a loss? |
| `fellowship` | Game as social framework | Which mechanic requires another person, rather than allows one? |
| `discovery` | Game as uncharted territory | What does noticing change about what the player tries next? (See [actionable discovery](../../../references/actionable-discovery.md).) |
| `expression` | Game as self-discovery | What choice is visible to others as this player's, not the optimal one? |
| `submission` | Game as pastime | What lets the player keep going at low mental cost? |

The paper itself uses `competition` as a further kind in an example; accept it where a role's primary is beating another person and no other word fits.

**The model.** Mechanics (rules, components, algorithms) produce dynamics (emergent run-time behaviour such as bluffing, camping, staggering in one at a time), which evoke aesthetics (the feelings above). The designer builds mechanics, dynamics, aesthetics in that order and controls only the first; the player experiences the chain in reverse and feels first. Consequence for the audit: a target feeling is a hypothesis until a playtest shows the dynamic and a person reports the feeling.

**Known limits, so the tool is not over-trusted.** The list is not exhaustive by the authors' own admission. "Aesthetics" is widely misread as visuals; it means feelings. The framework gives no reliable method for deriving rules from a target feeling, which is why step 6 of the skill writes experiments. A successor framework (DDE, Walk, Görlich and Barrett, 2017) folds authored narrative and art into design for cases where the eight feel too coarse. Use the eight as a shared vocabulary and audit tool, not as a complete theory of fun.

## The four keys (Lazzaro)

Nicole Lazzaro's player research (XEODesign, "4 Keys 2 Fun") names four keys:

- **Hard fun.** Challenge; frustration that resolves into fiero, the personal triumph.
- **Easy fun.** Novelty, curiosity, awe; exploring and fooling around.
- **People fun.** Social amusement; competition and cooperation with others.
- **Serious fun.** Meaning and real-world value; changing how the player feels.

Her finding was that best-sellers tend to touch three of the four. The audit records the count per role as a fragility check: a candidate that scores only on hard fun has one point of failure.

## The one-word method

Wyatt Cheng's short series on why specific games are fun opens every episode with the same challenge: give one word for why it is fun, without using the word fun. His premise is that telling a teammate a game is fun describes nothing, because everybody pictures something different, and that naming the specific kind in design documents gets everybody on the same page. The method, applied in every episode:

1. Exactly one primary kind per game.
2. Secondaries named briefly.
3. The verdict grounded in one or two concrete mechanics, never in a genre label.

His six verdicts, as worked examples of grounding a kind in a mechanic:

| Game | Primary | Secondary | The mechanic the verdict rests on |
|---|---|---|---|
| Cuphead | `challenge` | `sensation` | The death screen shows a progress bar with the boss phase reached: manufactured micro-victories that spur the retry |
| It Takes Two | `fellowship` | `narrative` | No solo mode, no artificial partner; asymmetric abilities force interdependence |
| Beat Saber | `sensation` | `fantasy` | The music is the feedback: miss and it goes flat, the combo dies |
| Vampire Survivors | `submission` | `discovery`, `sensation` | Movement-only control, constant power growth, low mental effort |
| Dispatch | `narrative` | none | The player is the one unfolding the story |
| Cyberpunk 2077 | `fantasy` | `narrative` | Embodiment: the player does not play as the character but becomes them |

The series has no episode on a team or hero shooter, a co-operative shooter, or a competitive arena game. Applying the vocabulary to those genres is the auditor's synthesis and is recorded as `hypothesis` until a playtest says otherwise.

## Three principles that travel with the vocabulary

From Cheng's talk on refining Diablo III's systems and his later retrospectives:

- **Death readability.** Full health to death was tuned to roughly three to five seconds so the player could recognize, assess and react; faster deaths read as random and feel unfair. The skill's step 4 generalizes this into a per-project window on a slider.
- **Mechanics induce behaviour, and behaviour must fulfil the fantasy.** Shooter-style health regeneration failed in the action role-playing game because running in circles to heal broke the battle fantasy; health globes shipped because healing by advancing made the efficient thing the fun thing. The forum version: make the most efficient thing to do also the most fun thing to do.
- **Fun to play as and fun to play against.** Prototyped arena, lane and asymmetric boss-versus-heroes modes were cut because reconciling every ability for both sides was a monumental task. Asymmetric audits score every ability twice.

Riot's teaching of the same vocabulary (URF Academy, "Game Feeling & 8 Kinds of Fun") adds the lesson that the same game evokes different feelings in different players, which is the reason a shared vocabulary in design documents matters; and its player-dynamics discipline treats the social structure of a mode (what teammates can do for each other, what a dead player can still contribute) as a design surface from the first prototype, not a moderation problem later.
