# Game Studio Kit

The entrypoints live in `skills/` (the list is `studio-kit.json`); shared contracts in `references/`.
Read the relevant entrypoint. Resolve the toolkit from that file's location.
Run helpers through an absolute path to `scripts/studio.py`; give an explicit
project/output root. Installed package sources are read-only during production.
Credentials belong in environment variables, host paths in ignored host config.

Validation: `python -m unittest discover -s tests -v` and
`python -m studio_tools check-package --root .`.
Native/perceptual and paid-provider results are separate from helper tests.

## Changing the kit

- This repository is public. Name no game, person, machine or account. Write
  "one game" and keep the date. `tests/test_public_names.py` holds the list.
- A lesson goes in the reference file of the skill that owns it, dated. A game's
  own values stay in that game's repository.
- A release bumps every version declaration together: both plugin manifests,
  `studio-kit.json`, `pyproject.toml` and `studio_tools.__version__`.
  `check-package` compares them.
- Do not write the number of skills in prose. `studio-kit.json` is the list.
