# Target sheet: draw "final" before building it

One page that shows what the finished character looks like in the game's style, approved by the owner before any body work. The concept settles shape and mood. The target sheet settles everything a builder would otherwise guess: colours, where lines go, the face, what glows, what moves, what the surface is made of. Every later picture is judged beside it.

It exists because of the pilot. Its concept fixed the silhouette, and "final" was then found by building and reacting: a dark core asked for and then judged too intense, a return to an earlier version's blues, a snow layer, lines redone four times, eyes built in a place the owner did not expect. Each of those was one sentence and one sketch on a sheet, and each cost days as finished art.

## What is on it

One image the owner can read on a phone, with short labels:

- **Three views and a close crop.** Front, side and back at the usual player distance, and one crop at the closest view (`art_pipeline.critic.closest_view`), painted in the game's style, not the concept's. If the game draws flat colour with ink lines, the sheet is flat colour with ink lines.
- **Palette.** Five to eight swatches with what each is for (body, shadow side, accent, glow, eyes), and the darkest and lightest value the body may reach. Team or state colours that override part of the palette are shown overriding it.
- **Lines.** Where lines are drawn and where they are not: silhouette only, silhouette plus part borders, or interior creases too. Mark two or three places on the close crop. Say where the lines come from when it matters (the shape's own edges, or drawn marks), because the two look different in motion.
- **Face.** Where the eyes are, their shape and size, whether they glow, and what the mouth does. Mark them on the front view; a sentence is not enough. The pilot's eyes were described, never drawn, and came back as a slit under the brow.
- **Glow and light.** What emits light, what colour, and whether it changes with a state.
- **What moves.** Hanging parts (mane, chains, cape, tail) and how they move: stiff, swaying, flowing. These are built as their own parts.
- **Effects.** What particles or trails belong to the character at rest and per ability, as rough marks, with the count kept small.
- **Surface and paint method.** Flat paint, flat paint plus shader detail, or painted texture ([skill](../SKILL.md#paint-method)), and one sentence on the material: wet ice, dry rock, bark.
- **New techniques.** Anything the game's shaders cannot do today, named in plain words. This list is what stage 7 builds. An empty list is the cheapest character.
- **Must not.** What it must not look like, carried from the concept brief.

## How to make it

Work in two dimensions. Paint over the approved concept or over a grey render of a stand-in body, with the image route the game allows (`art_pipeline.concept_route`). Do not build a model, a shader or a material to make the sheet. A sheet round should take minutes; if it takes hours it has turned into stage 6.

Take the palette, line weight and light step from the game's art contract when it has one ([studio-art-direction](../../studio-art-direction/SKILL.md)). When the game has none, the first character's approved sheet is the start of it: say so to the owner, because later characters will be held to it.

## When the owner does not know yet

That is the usual case. Do not ask for a description. Put two or three contrasting answers to each open question on the page (dark core, pale core, no core; lines on every crease, on part borders, on the silhouette only) and let the owner point. Keep each answer to one difference so a pick means something. Questions the owner has no view on are settled by the builder from the art contract and listed under "decided for you" so they can be overruled in one word.

## Rounds

Three rounds. Each round shows the whole sheet again with what changed marked. Count them in the run record's `gates.target.rounds`. If the third round has no yes, stop and ask the one question the rounds kept circling, with the options drawn.

## After approval

- Record the sheet in `gates.target` with its hash, approver and date, and keep it as a project reference with an ID and version.
- Put it in every later brief, bench page and review page for this character, beside the candidate.
- A change to the sheet after approval is a new version. Say which stages it reopens: a palette change reopens the look bench; a change to shape, stance or hanging parts reopens the body.
- Three rounds without a yes at a later stage send the work back here ([rule 7](../SKILL.md#rules)).

## Checklist

- [ ] Three views and a close crop, in the game's style
- [ ] Palette swatches with roles and value limits
- [ ] Lines marked on the close crop
- [ ] Eyes and mouth drawn on the front view
- [ ] Glow, moving parts and effects marked
- [ ] Paint method and material named
- [ ] New techniques listed, or the list is empty
- [ ] Made in two dimensions, no model or shader work
- [ ] Owner approved; hash, approver and round count in the run record
