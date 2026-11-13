# AGY-Launcher Local Rules

These local rules apply to all maintenance, feature development, and configuration updates inside `AGY-Launcher/`.

## 1. Semantic Versioning Specification

`AGY-Launcher` follows **Semantic Versioning (`MAJOR.MINOR.PATCH`)**, with the canonical runtime version anchored in `AGY-Launcher/server.mjs` (`const VERSION = 'X.Y.Z';`) and recorded in `AGY-Launcher/MAINTENANCE_LOG.md`.

### Bump Criteria
- **`MAJOR` (`X+1.0.0`, reset `MINOR` and `PATCH` to `0`)** — Bump when introducing breaking changes:
  - Incompatible changes to the `plugins.json` root or plugin entry schema.
  - Breaking changes to CLI arguments (`cli.mjs`, `desktop_app.py`), daemon HTTP endpoints, or plugin lifecycle contracts (`PLUGIN_INTEGRATION.md`).
  - Removing support for a previously documented plugin `type` or placeholder token.
- **`MINOR` (`X.Y+1.0`, reset `PATCH` to `0`)** — Bump when adding backward-compatible functionality:
  - New desktop views, Marketplace capabilities, navigation modules, or visual system upgrades.
  - New optional configuration keys in `plugins.json`, new CLI flags, or enhanced plugin health/metadata inspection.
  - New standardized plugin integration capabilities that do not break existing plugins.
- **`PATCH` (`X.Y.Z+1`)** — Bump for backward-compatible maintenance:
  - Bug fixes, UI alignment/font/rendering fixes, performance improvements, and crash/race prevention.
  - Automated test additions, refactoring without contract changes, and documentation updates (`AGENTS.md`, `PLUGIN_INTEGRATION.md`).

### Version Synchronization Rule
1. Whenever a maintenance task modifies `AGY-Launcher` code or shipped manifests, determine the appropriate `MAJOR` / `MINOR` / `PATCH` increment before concluding the task.
2. Keep `const VERSION = 'X.Y.Z';` in `AGY-Launcher/server.mjs` synchronized with the version logged in `AGY-Launcher/MAINTENANCE_LOG.md`.
3. Every entry in `MAINTENANCE_LOG.md` must explicitly state the target version (`vX.Y.Z`).

---

## 2. Mandatory Maintenance Log Policy

**Every maintenance session affecting the Plugin Manager (`AGY-Launcher`) MUST record an entry in `AGY-Launcher/MAINTENANCE_LOG.md`.** Work is not complete until the log has been updated and verified.

### Required Entry Format
Append new entries at the **top** of the history section (reverse chronological order) using this structure:

```markdown
## [vX.Y.Z] - YYYY-MM-DD HH:MM

### Summary
- Concise bullet points describing what changed and why.

### Files Changed
- `path/to/file` — brief purpose of edit.

### Verification
- Exact command(s) executed after the final edit and observed outcome (e.g., `python -m unittest discover -s tests -v` -> 5 passed).
```

### Enforcement Rules
- **No silent patches**: Even small bug fixes, styling tweaks, or rule updates must be logged with the exact files touched and post-edit verification output.
- **No fabricated verification**: Only record commands and test counts that were actually executed after the last code modification.

---

## 3. AGY Plugin Development & Onboarding Requirement

When developing, updating, or onboarding any AGY external plugin under `AGY-Launcher/plugins/` or registering it in `AGY-Launcher/plugins.json`, you MUST adhere strictly to the specification in `AGY-Launcher/PLUGIN_INTEGRATION.md`, including:
- Valid plugin directory structure and ID format (`^[a-z0-9][a-z0-9-_]{1,63}$`).
- Complete `plugins.json` entry contract (`launchArgs`, `attachArgs`, `stopArgs`, `processMatch`, optional `healthUrl`).
- Headless detached startup, idempotent singleton attach locking, safe process matching (never relying on bare generic runtimes), graceful `--stop` handling, and standardized stdout/stderr logging.
