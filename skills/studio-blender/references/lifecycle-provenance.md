# Supervised lifecycle provenance

The six files under `../scripts/lifecycle/` were migrated on September 9, 2026 from the deployment-specific supervised helper set reviewed in the Coastal Amphitheater lifecycle verification. They retain the proven endpoint-wide startup lock, lease, process-start, executable, working-scene, loopback-listener, conflict-refusal and receipt-bound graceful-cleanup design. The package adaptation removes host/user defaults, requires one explicit host JSON and external run root, takes receipt ownership identity from host configuration, and strengthens native protocol-status validation.

Original source SHA-256 values:

| File | SHA-256 |
|---|---|
| `Ensure-SupervisedBlenderMCP.ps1` | `756b86beaa276bd3fc6e9364438de0dcb22b799618318c5ea9045486655749b3` |
| `Test-SupervisedBlenderMCP.ps1` | `d19fd24065602ba4b17ee6caacf5848eb4147c2e2a8efde76c0d2abec5ca821e` |
| `Stop-SupervisedBlenderMCP.ps1` | `c61680020c08c07a586c26a3f83396641cb2da7992ec325eb39fca93c6eda9fd` |
| `supervised_bootstrap.py` | `be42ffb68d1b45384768001839134c3427840ef50614c04c4266f329a261b417` |
| `probe_mcp.py` | `44014086312cff4d7591bab0f6f52ca5a94fd71713209b5afbcbbb440735517e` |
| `Test-LifecycleContracts.ps1` | `676b58003391e3139029c8c484436f9d87c6ad39935b0bbae236d25512405ea3` |

The PowerShell contract script performs parsing and static source assertions only. Python policy tests execute configuration, current-status and bounded-retry behavior with fakes. Neither qualifies the packaged files on native Windows; use the separate lifecycle qualification card and record exact package revision and file hashes there.
