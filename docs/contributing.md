# Contributing and local release preparation

Keep ten discriminating entrypoints and shared contracts; avoid importing an agent framework or making generic installed skills a runtime dependency. Use Python 3.11 standard library for core helpers. New provider fields need schema evidence and contract/failure tests before expanding the allowlist. Preserve original editable assets and honest native/perceptual statuses.

Run helper tests and package validation, then the affected real app route. A formatting edit does not need an expensive rendering rerun; a rig/export/material change does. Do not treat mock service tests as live provider validation. Update [compatibility](compatibility.md) only with actual evidence.

For upstream adaptations, retain exact repository revision, source/local file hashes, license/NOTICE and local-change/reference-closure description in `upstream-lock.json`. Never dynamically download main during production. Audit all copied material and output rights; new source changes may require updating the adapted-file hashes.

Before publishing, complete the native Windows registration/ordinary-input/listening smoke and the real project pilot, resolve defects, repeat clean-profile reproduction, review provenance/private paths and obtain the owner's publication decision. This repository has no automatic publishing workflow.

Create a complete **local** archive from committed files:

```text
git status --short
git archive --format=zip --prefix=game-studio-kit/ --output=/path/outside/repo/game-studio-kit.zip HEAD
```

This retains `.codex-plugin`, shared helpers, references, licenses, tests and example assets. It excludes ignored host config, `.godot`, task artifacts and untracked private inputs. Extract into a path with spaces and rerun check-package from a different working directory. A Python wheel alone does not carry the complete plugin/skills tree; use this source archive for distribution.
