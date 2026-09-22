$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PlatformRoot = [System.IO.Path]::GetFullPath((Join-Path $Root '..\..'))
$Stage = Join-Path $Root '.build_current'
$ExpectedStage = [System.IO.Path]::GetFullPath($Stage)
$ExpectedPrefix = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
if (-not $ExpectedStage.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Build path escaped tool root: $ExpectedStage"
}

if (Test-Path -LiteralPath $ExpectedStage) {
    Remove-Item -LiteralPath $ExpectedStage -Recurse -Force
}
New-Item -ItemType Directory -Path $ExpectedStage -Force | Out-Null

$Dist = Join-Path $ExpectedStage 'dist'
$Work = Join-Path $ExpectedStage 'work'
$Spec = Join-Path $ExpectedStage 'spec'
$env:PYTHONPATH = $Root

python -m unittest discover -s (Join-Path $Root 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Cleaner tests failed' }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name XuanYuanTempCleaner `
    --paths $Root `
    --distpath $Dist `
    --workpath $Work `
    --specpath $Spec `
    (Join-Path $Root 'run_cleaner.py')
if ($LASTEXITCODE -ne 0) { throw 'Cleaner build failed' }

$Built = Join-Path $Dist 'XuanYuanTempCleaner.exe'
if (-not (Test-Path -LiteralPath $Built -PathType Leaf)) { throw 'Built EXE missing' }
$Target = Join-Path $PlatformRoot 'bin\XuanYuanTempCleaner.exe'
Copy-Item -LiteralPath $Built -Destination $Target -Force
$SourceHash = (Get-FileHash -LiteralPath $Built -Algorithm SHA256).Hash
$TargetHash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
if ($SourceHash -ne $TargetHash) { throw 'Published EXE hash mismatch' }

# This path is created by this script and was verified to be under the tool
# directory above. Removing it avoids adding another persistent build cache.
Remove-Item -LiteralPath $ExpectedStage -Recurse -Force
[pscustomobject]@{
    target = $Target
    sha256 = $TargetHash
    bytes = (Get-Item -LiteralPath $Target).Length
} | ConvertTo-Json -Compress
