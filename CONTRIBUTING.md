# Contributing to AGY Dock

Quick Links: [Plugin Integration Spec](PLUGIN_INTEGRATION.md) · [Changelog](CHANGELOG.md) · [README](README.md)

---

## Submitting a Plugin to the Marketplace

If you want to distribute an external plugin through **AGY Dock**, start by reading the full specification in [`PLUGIN_INTEGRATION.md`](PLUGIN_INTEGRATION.md).

### Submission Checklist

1. Create a root `agy-plugin.json` manifest (`schemaVersion: 1`) inside your plugin archive.
2. Choose a valid plugin ID matching `<owner>.<slug>` (e.g., `alice.my-helper`) for community/third-party submissions.
3. Verify your archive passes the built-in static security scanner before submitting:
   ```powershell
   node scripts/scan-plugin.mjs path/to/your-plugin.zip
   ```
4. Submit your plugin via GitHub Issues:
   - **Third-Party Marketplace** (links to your own GitHub repository & release assets): use [Submit Third-Party Plugin](.github/ISSUE_TEMPLATE/submit-third-party-plugin.yml).
   - **Official Marketplace** (maintained or reviewed inside this repository): use [Submit Official Plugin](.github/ISSUE_TEMPLATE/submit-official-plugin.yml).

---

## Contributing Core Changes

1. Run frontend type-checking and build:
   ```powershell
   npx tsc --noEmit
   npm run build
   ```
2. Run backend Rust tests:
   ```powershell
   cargo test --manifest-path src-tauri/Cargo.toml
   ```
3. Run launcher runtime tests:
   ```powershell
   node --test AGY-Launcher/tests/process-manager.test.mjs
   ```
4. Document user-facing changes in [`CHANGELOG.md`](CHANGELOG.md).
