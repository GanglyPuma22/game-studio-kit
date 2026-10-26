---
name: studio-assets
description: Find and pull free, openly licensed textures, materials, HDRIs, base meshes and modular kits (Poly Haven, ambientCG, Kenney, Quaternius, The Base Mesh and more) with `studio assets`, keeping every file's source, licence, author and hash in one ledger so a library can be rebuilt, credited and reused across games.
---

# Studio Assets

Use this before modelling or texturing something from scratch, and whenever a scene needs surfaces, sky light or props that a public CC0 library already has. It is the free-base step of [art direction](../studio-art-direction/references/concept-and-bases.md) made concrete: which sites to look at, how to download from each without a browser, and how to keep the rights trail.

Inputs: what the asset or surface must be (and the approved concept when the game requires one), the game's style and texture budget, an explicit project or library root, and the host's network reach.

## 1. Pick sources

`studio assets sources [--kind textures|models|hdris|base-meshes|modular-kits]` prints the catalogue in [sources.json](references/sources.json): licence, licence page, how downloads work (`route`) and whether a cloud container behind a proxy could reach it when last checked. [Sources and recipes](references/sources.md) explains each site and the steps for the ones without an API.

| Need | Start with |
|---|---|
| Tiling surface (brick, plaster, roof, wood, ground) | ambientCG, Poly Haven, TextureCan, Share Textures, cgbookcase |
| Sky light and reflections | Poly Haven HDRIs |
| Low-poly or stylized props and modular buildings | Kenney, Quaternius, then itch.io and OpenGameArt |
| A clean starting shape to reshape in Blender | The Base Mesh, then Poly Haven models |

Every site-wide source above is CC0. OpenGameArt, itch.io, Poly Pizza, Blend Swap and Sketchfab set a licence per asset: read it on the asset page.

## 2. Search and fetch

```text
python <KIT>/scripts/studio.py assets search --source polyhaven --query "plaster wall" --kind textures
python <KIT>/scripts/studio.py assets search --source ambientcg --query "roof tiles" --kind textures
python <KIT>/scripts/studio.py assets search --source ambientcg --query "leaf" --kind atlases
python <KIT>/scripts/studio.py assets fetch --project <ROOT> --source polyhaven --id plastered_wall_05 --resolution 1k
python <KIT>/scripts/studio.py assets fetch --project <ROOT> --source ambientcg --id RoofingTiles013A --resolution 1K
python <KIT>/scripts/studio.py assets fetch --project <ROOT> --source kenney --url <zip> --page <asset page> --author Kenney --extract
```

- `search` covers the two sites with public APIs (Poly Haven, ambientCG) and is read-only. ambientCG keeps cut-out sheets (leaf sets, foliage, grass strands) apart from tiling materials: search them with `--kind atlases`; `--kind textures` never returns them. For the rest, open the asset page, find the file link as [sources.md](references/sources.md) describes, and pass it as `--url` with `--source <site id>`.
- Poly Haven textures default to the maps a game shader uses (`Diffuse,nor_gl,Rough,AO,Displacement,arm`); `--maps` narrows them. Models come as glTF with their textures; HDRIs as `.hdr`. The helper checks Poly Haven's md5 for each file.
- A site-wide CC0 source fills in the licence. A per-asset source needs `--licence` copied from the page, `--author`, and for CC-BY the exact `--attribution` text.
- The helper refuses NonCommercial, NoDerivatives, ShareAlike, GPL and unknown licences, the same rule `validate-record` applies. When the page and the download disagree, skip the asset.
- `--extract` unpacks a zip into `extracted/` beside the untouched original. Never edit the original; reshape or repaint in a new source file.
- A site that answers with a web page instead of a file (login wall, challenge) is refused with that reason. Ask the person to download it, put it under the library folder, and record it with `studio assets add --file <path> --page <page> --licence <licence> --author <name>`.

Files land under `<ROOT>/assets/third_party/<source>/<id>/` (`--library` moves this) and every fetch rewrites `ledger.json` there. Each fetch prints a `provenance` block ready for an asset record's `provenance.base` (a mesh) or `provenance.texture_bases` (a texture or material).

## 3. Keep the library

- The ledger is the lock file. Commit it. Large third-party binaries do not need to live in git: `studio assets verify --project <ROOT>` re-hashes every file, and `--restore` re-downloads missing ones from their recorded URLs and accepts them only when the hash matches. Entries marked `refetchable: false` (itch.io's expiring links, files a person added) must keep their original somewhere durable, such as Git LFS or a storage bucket.
- `studio assets credits --project <ROOT> --output CREDITS-third-party.md` writes the credits: CC-BY entries with their required text, CC0 entries as a courtesy. Carry it into the game's credits.
- One library can serve several games. Point `--project` at a dedicated library checkout (its own repository), and have each game record which library revision and entries it uses. A game that copies a file into its own tree copies the ledger entry with it.

## 4. Make it fit the game

A found asset is a starting point, not the look. Photoreal scans rarely suit a stylized game as they are: take the normal and roughness maps for shape, then repaint, posterize or replace the base colour to the approved palette, and compare against the concept. Fetch at the size the game ships (1K, sometimes 2K, for most props and tiling surfaces on PC and browser builds); a larger download is not a better asset. Then follow the game's texture path (tiling, colour space, compression, target-renderer preview) and qualify any mesh with `studio blender inspect` as for a provider mesh ([Blender](../studio-blender/SKILL.md)). A modular kit piece used many times in a scene should be one shared mesh and material so the engine can batch or instance it.

## 5. Network

Hosts differ. On 2026-10-22, from a Claude Code cloud container behind its HTTPS proxy, every site except Poly Pizza (Cloudflare challenge, keyed API) downloaded without a person; Blend Swap and Sketchfab need an account for downloads. `cloud_reachable` in the catalogue records that check. If a host cannot reach a site, fetch from one that can and say which host fetched it; the ledger's `retrieved_on` records it.

Return the ledger path, the entries added, any assets skipped and why (licence, reach, style), and the next step for each kept asset.
