# Game Studio Kit

The ten entrypoints live in `skills/`; shared contracts in `references/`.
Read the relevant entrypoint. Resolve the toolkit from that file's location.
Run helpers through an absolute path to `scripts/studio.py`; give an explicit
project/output root. Installed package sources are read-only during production.
Credentials belong in environment variables, host paths in ignored host config.

Validation: `python -m unittest discover -s tests -v` and
`python -m studio_tools check-package --root .`.
Native/perceptual and paid-provider results are separate from helper tests.
