# Build the Windows bundle: dist\Folio\Folio.exe and dist\folio-<version>-windows-x64.zip
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .venv)) { python -m venv .venv }
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -e ".[dev]"
.venv\Scripts\python -m pytest -q tests
if ($LASTEXITCODE) { throw "tests failed" }
.venv\Scripts\pyinstaller folio.spec --noconfirm --log-level WARN
if ($LASTEXITCODE) { throw "pyinstaller failed" }
dist\Folio\Folio.exe --selftest | Out-Host
if ($LASTEXITCODE) { throw "selftest failed" }
$version = .venv\Scripts\python -c "import folio; print(folio.__version__)"
$zip = "dist\folio-$version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\Folio -DestinationPath $zip
Write-Host "Built $zip"
