param(
  [Parameter(Mandatory=$true)][string]$Version,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
  $releaseArguments = @((Join-Path $PSScriptRoot 'scripts\release.mjs'), $Version)
  if ($DryRun) { $releaseArguments += '--dry-run' }
  & node @releaseArguments
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
