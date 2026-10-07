# Synthetic revision record example

All candidate content and observations here are invented text fixtures. There are no real images, models, reviewer inspections or human acceptance. The record illustrates a structurally complete content-defect revision, not successful art.

Run without native apps or providers:

```sh
python /path/to/kit/scripts/studio.py review revision --project /path/to/kit/examples/review-revision --evidence review.json
```

Expected: `closure_supported_by_record: true` for the one synthetic defect, while `human_acceptance` remains `not_established`. This command reads the example and prints a report; it does not write a receipt or change the project.

See [the record guide](../../docs/review-revisions.md). Change a retained file without updating its record and its evidence becomes unusable. Omit the critic recheck, use the builder as critic, or omit a required view and the closed claim becomes unsupported. Unit tests cover those cases; they do not demonstrate a real visual review cycle.
