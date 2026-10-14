# Game Studio Kit in Claude Code

This repository is one kit with two plugin manifests. Claude Code uses
`.claude-plugin/plugin.json`; Codex uses `.codex-plugin/plugin.json`. Both load
the same eleven skills, Python helper, references and examples. Keep the whole
package together. Do not duplicate or translate the production skills into a
second implementation.

## Test without changing your installed plugins

From an independent project directory, use an absolute path to this checkout:

```powershell
$Kit = 'C:/Tools/game-studio-kit'
claude plugin validate "$Kit/.claude-plugin/plugin.json" --strict
claude plugin validate "$Kit/.claude-plugin/marketplace.json" --strict
claude --plugin-dir "$Kit" plugin details game-studio-kit
claude --plugin-dir "$Kit"
```

In the last interactive session, invoke `/game-studio-kit:studio-director` and
give it the actual project/output root and host configuration. Ask it to resolve
the kit from the loaded skill's physical location and run `check-package` and
an engine-free check from an independent project directory. Record the resolved
path, version and actual operation. Manifest validation and component discovery
alone do not establish that an agent followed the workflow or inspected a game.

The two explicit manifest checks also work on Claude Code versions that do not
validate both files when passed their common directory. Session-only loading
does not register a marketplace or replace the Codex plugin.

## Install a reviewed version

Once the compatibility change is reviewed and published, add the repository's
marketplace and install at user scope:

```text
claude plugin marketplace add GanglyPuma22/game-studio-kit
claude plugin install game-studio-kit@game-studio-kit-marketplace --scope user
claude plugin list --json
```

Check the selected version and install path. Start a fresh Claude Code session
or use its supported plugin reload command when the installer requires it.
The shared source repository must actually contain this manifest; these commands
are not a claim that an unmerged branch is on main. For a preview, register the
reviewed checkout's local absolute path instead. Keep its source until the
marketplace points at a published source. Do not hand-edit either agent's cache.

If an older Game Studio Kit from another marketplace is registered, preserve
that install/marketplace identity first. Verify the new one, then use Claude's
normal `plugin disable <old-name@marketplace> --scope user` for the exact old ID
when migrating. Do not delete its cache or leave two active copies of the same
skill namespace without checking which one the session loads. This setup guide
does not itself change global plugin settings.

## Capabilities and policy are host-specific

- Python 3.11+ and the explicitly configured Blender/Godot installations remain
  dependencies. Use `doctor --config <host>` before assuming an app route works.
- This plugin defines no MCP servers, hooks, agent model presets, auto-installs,
  remote runner or desktop-control capability. Configure a compatible Blender
  connector or desktop tool separately when needed. The listener in Blender and
  the agent's connector are separate; verify/reconnect the actual connector.
- Follow the user's current policies, approved scope, provider budget and exact
  cutoff. Do not impose a Codex-specific model family on Claude workers.
  The foreground orchestrator owns native/perceptual review and sign-off;
  headless workers' findings are inputs. Human acceptance remains separate.
- Codex `functions.exec` yield directives and tool names in the execution
  references are host examples, not Claude Code APIs. In Claude Code, use its
  actual synchronous shell tool with a timeout covering the kit command's
  bound. If a command is still running, use the runtime's supported single
  completion retrieval; do not repeatedly query progress or start another
  engine. Tool availability must be checked on that runtime.
- Read the overnight procedure and the user's policy override before an
  unattended run. A performance miss does not terminate development; retained
  engine identity, host readiness and ownership safeguards still apply.

No keys are bundled. Pass ignored host configurations explicitly; provider
credentials come from the configured environment or declared private credential
file, never a committed secret or a marketplace field. Installing a plugin does
not grant provider credits or GPU availability.

## Release and acceptance

For a normal published release, all five version declarations (both agent
manifests, `studio-kit.json`, Python package metadata and
`studio_tools.__version__`) advance together. The explicitly documented
[local staging exception](plugin-staging.md) updates the staged plugin and kit
manifests while preserving the canonical Python release metadata; it is a
preview procedure, not a published release. Building for
Claude does not change the asset provider or game's sources. Keep generated
work/evidence outside the installed kit and preserve originals.

Validate one real operation after discovery: import an existing asset into a
declared review project, inspect it at player scale, make one bounded correction
and recheck the defect on the revised content. Blender inspection, ordinary
runtime input, temporal evidence and a human verdict establish different claims;
neither an installed manifest nor passing helper tests supplies them.

Format and commands: [Claude plugin creation](https://code.claude.com/docs/en/plugins/create),
[manifest reference](https://code.claude.com/docs/en/plugins-reference),
[marketplace setup](https://code.claude.com/docs/en/plugin-marketplaces).
