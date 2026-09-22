param(
    [string]$ReleaseId = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [switch]$Publish
)
$ErrorActionPreference = 'Stop'
$PlatformRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildTemp = Join-Path $PlatformRoot 'runtime\build-bootstrap'
$PyInstallerConfig = Join-Path $PlatformRoot 'runtime\pyinstaller-config'
New-Item -ItemType Directory -Path $BuildTemp -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerConfig -Force | Out-Null
$env:TEMP = $BuildTemp
$env:TMP = $BuildTemp
$env:PYINSTALLER_CONFIG_DIR = $PyInstallerConfig
$PythonCommand = if ($env:XYDP_PYTHON) { $env:XYDP_PYTHON } else { 'python' }
$BuildArguments = @('-X', 'utf8', (Join-Path $PlatformRoot 'tools\build_platform_release.py'), '--root', $PlatformRoot, '--release-id', $ReleaseId)
if ($Publish) { $BuildArguments += '--publish' }
& $PythonCommand @BuildArguments
if ($LASTEXITCODE -ne 0) { throw 'Matched platform release failed; current release was not changed.' }
