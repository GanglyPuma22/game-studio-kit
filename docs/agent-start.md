# Agent startup: clone, integrate, verify, work

Use this guide when a user asks a Windows ChatGPT/Codex agent to set up the studio and then perform a game task. It is an agent-executed setup workflow, not a universal installer. The host provides filesystem/command access, native computer use and installation permissions.

## 1. Keep one complete checkout

Clone `https://github.com/GanglyPuma22/game-studio-kit.git` into a new user-owned tools directory, outside the game project. For example:

```powershell
$Kit = Join-Path $env:USERPROFILE "Documents\AgentTools\game-studio-kit"
git clone https://github.com/GanglyPuma22/game-studio-kit.git "$Kit"
git -C "$Kit" rev-parse HEAD
```

Create the parent directory first if needed. If the destination exists, inspect its origin, revision and working tree. Reuse a suitable checkout; preserve local changes and use a fresh directory when necessary. Do not reset a user's checkout. When a task packet pins a revision, use that revision in the fresh checkout and record it. Avoid updating tools during a production run.

Read [studio-director](../skills/studio-director/SKILL.md), [Windows setup](setup-windows.md) and [portability](../references/portability.md). Keep all ten skills, shared references, templates and helpers together. Copying individual skill folders loses required shared resources.

## 2. Integrate through the active host

When the session authorizes studio installation, perform these ordinary setup actions without asking for the same authorization again. Do not modify unrelated skills or overwrite an existing marketplace.

**Registered plugin:** use the active host's supported local plugin flow with the existing `.codex-plugin/plugin.json`. ChatGPT's built-in `@plugin-creator`, or Codex's `$plugin-creator`, can help add an existing plugin to a personal marketplace. Ask it to register the complete existing package, preserving its contents. The standalone GitHub repository is not itself a plugin marketplace or a universal-directory listing. Follow [the marketplace layout and CLI commands](setup-windows.md) if using Codex CLI; check that host's actual help rather than assuming another product's configuration is shared.

After refresh/install, test invocation in a new host conversation from the game directory: ChatGPT supports selecting a registered skill with `@`; Codex supports `/skills` or `$`. Invoke `studio-director`, then resolve a sibling skill and `scripts/studio.py` from its actual installed location. Verify the active copy matches the intended workflow revision. Listing a plugin does not prove invocation.

**Direct-file route:** if registration is unavailable, deferred, or requires a user restart that would block the authorized task, explicitly read the checkout's coordinator and the sibling skills it names. Use the absolute helper path. Record `direct_file` as the integration mode and leave registered discovery unverified. This preserves task execution without claiming installation.

For future project sessions, add a small studio section to the new game's `AGENTS.md` when the host uses that file, preserving any existing instructions. State the actual KIT location and revision, coordinator path, project work-card location and external host-config path. This is a project pointer, not a replacement for the skill catalog. Do not paste the ten skills into global instructions. On other hosts, keep the same pointer in an explicit project setup note and include it when resuming.

Official host behavior: [build/install plugins](https://learn.chatgpt.com/docs/build-plugins), [skill discovery and invocation](https://learn.chatgpt.com/docs/build-skills). A Git clone cannot provide computer-use tools or sign into an app.

## 3. Verify before production

From a separate game working directory, run the absolute helper's `check-package --root <KIT>` and `doctor --config <HOST>`. Discover actual application paths; follow [Windows setup](setup-windows.md) and [native smoke](windows-smoke.md). Keep host configuration outside the toolkit. Setup inspection does not silently install applications or call paid providers.

Record under the game project's `artifacts/studio-bootstrap.json`: source checkout/revision, active KIT location, integration mode, host/application versions, resolved coordinator/sibling/helper paths, host-config path, actual capability checks and outstanding steps. Never include credentials. A host restart or absent native tools is a real remaining step, not an implied pass.

## 4. Continue with the work card

Once the task's required checks pass, the coordinator routes into the relevant internal skills as needed. Follow existing session scope and budgets; no additional approval is implied for already authorized modeling, testing or corrections. Keep source, runtime exports and evidence in the game project. Report missing checks and preserve the user's final artistic decision.
