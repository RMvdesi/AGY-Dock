param(
  [ValidateSet("launch", "attach", "status", "stop", "shortcut", "daemon", "open-ui")]
  [string]$Action = "launch"
)

$ErrorActionPreference = "Stop"
$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliPath = Join-Path $BaseDir "cli.mjs"

if (-not (Test-Path $CliPath)) {
  throw "CLI entrypoint not found: $CliPath"
}

& node.exe $CliPath $Action
exit $LASTEXITCODE
