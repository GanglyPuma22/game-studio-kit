# The avoid ledger

A sheet's avoid-list (D7) names the failures to watch for in one subject. The ledger is where those failures are kept for the whole game, with their context, so the next move or shot starts from what was already learned instead of rediscovering it.

The ledger **documents, it does not forbid.** An entry says what was tried, why it failed then and what it cost. Trying it again is allowed. When a retry works (a new rig, a new model, a different context), mark the old entry `superseded` and point to what changed. Nothing is deleted.

## Where it lives

One file per game, in the game's own repository, never in this kit. One JSON object per line, so a merge adds lines and a `grep` still works. Either a `.jsonl` file, or a `.md` file whose entry lines start with `{` inside a code fence, with a heading and notes around them (useful when the game's checks treat Markdown as documentation). The script keeps the prose and the fence when it adds or updates entries.

## An entry

```json
{"id": "giant-walk-rigid-pieces", "date": "2026-11-05", "lane": "in-engine", "decision": "D3", "tags": ["giant", "walk", "rig"], "tried": "walk cycle on a body cut into rigid pieces", "failed": "pieces opened gaps at every bend; feet slid", "impact": "two days of retakes; the body was re-skinned as one mesh", "lesson": "skin one mesh before keying locomotion", "evidence": "review page or PR link", "status": "active"}
```

| Field | Required | Holds |
|---|---|---|
| `id` | yes | Short, unique, readable (`<subject>-<what>`) |
| `date` | yes | When it was seen, `YYYY-MM-DD` |
| `tags` | yes | Lowercase words: the character or class, the move type, the system (rig, particles, shader, camera, network, model) |
| `tried` | yes | What was done, concretely |
| `failed` | yes | What went wrong and why, as far as it is known |
| `impact` | yes | What it cost: rounds, days, a revert, a player-facing bug |
| `lesson` | no | What to do instead, if known |
| `decision` | no | Which sheet decision it belongs to: `D1` to `D7`, or `limits` |
| `lane` | no | `in-engine`, `video` or `both` |
| `evidence` | no | A link or path to the take, capture or review |
| `status` | no | `active` (default), `superseded`, `retired` |
| `superseded_by`, `note` | no | What changed, when an entry no longer holds |

## Use

The script is standard-library Python: [scripts/avoid_ledger.py](../scripts/avoid_ledger.py).

```text
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py query design/avoid-ledger.jsonl --tag giant --tag walk
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py query design/avoid-ledger.jsonl --tag giant --tag particles --any --limit 15
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py add design/avoid-ledger.jsonl --json '{...}'
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py set-status design/avoid-ledger.jsonl giant-walk-rigid-pieces superseded --superseded-by "one-skin rig"
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py tags design/avoid-ledger.jsonl
python <KIT>/skills/studio-direction-sheet/scripts/avoid_ledger.py check design/avoid-ledger.jsonl
```

`query` prints one line per active entry, newest first: what was tried, why it failed, what it cost and the lesson. That line is what goes into a sheet or a brief, so the whole file is never pasted. `--full` prints the JSON; `--all-status` includes superseded entries, useful when deciding whether to retry something.

## When to read it

- **Filling a sheet:** query by the subject's tags (character or class, move type, the systems it touches). Copy the entries that apply into D7 by id, and say in a word why each applies. Entries that do not apply are left out; a long D7 is a sign of a too-broad query.
- **Briefing a builder:** the brief links the sheet and lists the ledger ids it used. A builder may query further for its own system.
- **Before a retry of something the ledger records:** read the entry with `--full`, say what is different this time, and go ahead.

## When to write it

- **Every killed take** adds a noun to the sheet's D7 and, when the failure would bite another subject, one ledger entry.
- **A revert, a reworked look, or a round the owner rejected** is an entry with its cost.
- **Seeding:** when a game adopts the ledger, write entries from its existing review notes and decision logs, one per failure that cost a round or more. Mark guesses about cause as such in `failed`.

Keep entries to a line each. When the file passes a few hundred active entries, retire the ones a changed system has made moot rather than splitting the file. A database is not needed at this size; the query is a filter over lines.
