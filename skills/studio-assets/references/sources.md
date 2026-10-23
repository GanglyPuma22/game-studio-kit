# Sources and recipes

The machine-readable catalogue is [sources.json](sources.json); `studio assets sources` prints it. This page says what each site is good for and how to get a file URL from it without a browser. Checked on 2026-10-22 from a Claude Code cloud container behind its HTTPS proxy; sites change their pages, so treat a recipe that stops working as a reason to look again, not to scrape harder.

Ground rules for every site:

- Download only what the current asset needs, at the size the game ships. Do not mirror a site.
- Prefer an official API or the stable file link the page itself offers. Never get around a login wall, a CAPTCHA or a Cloudflare challenge; hand that download to a person and record it with `studio assets add`.
- Read the licence on the asset page for per-asset sites, and copy it exactly. When it says only "free" or "free for personal use", skip it.

## Textures and materials

| Site | Licence | Route | How to get a file |
|---|---|---|---|
| Poly Haven `polyhaven` | CC0, site-wide | api | `assets search/fetch --source polyhaven`. The site terms forbid scraping: always use the API, which asks for a named User-Agent (the helper sends one). |
| ambientCG `ambientcg` | CC0, site-wide | api | `assets search/fetch --source ambientcg`. One-person site: fetch the variant you need (`1K-JPG`), not all of them. |
| Share Textures `sharetextures` | CC0, site-wide | direct | The asset page embeds `"downloadLinks"` JSON; the files are `https://files.sharetextures.com/file/Share-Textures/<name>-1K.zip` (also 2K, 4K). |
| cgbookcase `cgbookcase` | CC0, site-wide | direct | The page's download link is `/textures/thanks?t=<Name>_<1K|2K|4K>.zip`; the file itself is `https://cgbookcase-volume.b-cdn.net/t/<Name>_1K.zip` and needs `--referer https://www.cgbookcase.com/`. |
| TextureCan `texturecan` | CC0, site-wide | direct | Detail pages (`/details/<n>/`) link `/downloads/<id>/<id>_1k_<token>.zip`. Plain curl gets 406; the helper's headers work. |

## Models, base meshes and kits

| Site | Licence | Route | How to get a file |
|---|---|---|---|
| Kenney `kenney` | CC0, site-wide | direct | Each asset page links one versioned zip, `https://kenney.nl/media/pages/assets/<slug>/<hash>/kenney_<slug>_<version>.zip`. Packs ship GLB, FBX and OBJ. |
| Quaternius `quaternius` | CC0, site-wide | recipe | Free tiers download through the pack's itch.io page; use the itch.io recipe below with `--source quaternius`. Pro and Source tiers are paid. |
| The Base Mesh `thebasemesh` | CC0, site-wide | direct | `/model-library` lists every model with `https://www.thebasemesh.com/_files/archives/<hash>.zip?dn=<name>.zip`; the helper names the file from `dn`. |
| Poly Haven models `polyhaven` | CC0 | api | `assets fetch --source polyhaven --id <model>` brings the glTF and its textures. |
| OpenGameArt `opengameart` | per asset | direct | Licences are listed on the page (`license-name`); files are `https://opengameart.org/sites/default/files/<file>`. Choose CC0 or CC-BY; CC-BY-SA, GPL and OGA-BY are refused. |
| itch.io `itch` | per asset | recipe | See below. Signed links expire, so pass `--no-refetch` and keep the original. |
| Poly Pizza `polypizza` | per asset (CC0 or CC-BY 3.0) | blocked | Cloudflare challenge on the site, API key required. A person downloads; record with `assets add` and the author for CC-BY. |
| Blend Swap `blendswap` | per asset | login | Downloads need an account. Many blends are SA or NC. |
| Sketchfab `sketchfab` | per asset | login | `https://api.sketchfab.com/v3/search?type=models&downloadable=true&license=cc0&q=<words>` searches without a key; downloading needs the person's API token. |

## Recipe: a free itch.io download

For a pack whose page offers a free download (no payment prompt), with one cookie jar for all steps:

1. GET the pack page (`https://<creator>.itch.io/<pack>`) and read `csrf_token` from the page.
2. POST `csrf_token=<token>` to `<pack page>/download_url`. The JSON answer has `url`, a download page.
3. GET that page. Each file has a `data-upload_id` and a name.
4. POST `csrf_token=<token from that page>` to `<pack page>/file/<upload_id>?source=game_download`. The JSON answer has a signed `url`, valid for a short time.
5. `studio assets fetch --project <ROOT> --source <quaternius|itch> --url <signed url> --page <pack page> --licence <as the page states> --author <creator> --no-refetch`.

Do this only for packs offered for free; a "name your own price" page that shows a payment step first is the creator's choice to ask, so let the person decide.

## Recording a manual download

```text
python <KIT>/scripts/studio.py assets add --project <ROOT> --source blendswap --file assets/third_party/blendswap/well/well.blend --page <asset page> --licence CC-BY-4.0 --author <name> --attribution "<exact credit>"
```

The file must already sit under the library folder. It is hashed and recorded with `refetchable: false` unless `--url` names a stable link.
