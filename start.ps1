$ErrorActionPreference = 'Stop'
$bundle = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $bundle) {
  & $bundle (Join-Path $PSScriptRoot 'server.py')
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 (Join-Path $PSScriptRoot 'server.py')
} else {
  & python (Join-Path $PSScriptRoot 'server.py')
}
exit $LASTEXITCODE
