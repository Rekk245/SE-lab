$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m unittest discover -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m tools.build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m tools.measure
exit $LASTEXITCODE
