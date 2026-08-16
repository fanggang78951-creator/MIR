param(
    [string]$SourceMmap = 'D:\XuanYuanDevPlatform\玄渊界面施工台\workspace\star-xx371-382-minimap-native-20260812\candidate\143.mmap',
    [string]$TargetMmap = 'D:\11周年\Data\minimap\301.mmap',
    [string]$MiniMapConfig = 'D:\MirServer\Mir200\Envir\MiniMap.txt',
    [string]$ReportPath = 'D:\XuanYuanDevPlatform\玄渊界面施工台\reports\star-xx371-native-minimap-9901-gate-20260812.json'
)

$ErrorActionPreference = 'Stop'
$encoding = [System.Text.Encoding]::GetEncoding(936)
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupRoot = "D:\codex交班记录\备份\${stamp}_XX371原生雷达9901门禁"

foreach ($path in @($SourceMmap, $TargetMmap, $MiniMapConfig)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file is missing: $path"
    }
}

$clientProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith('D:\11周年', [System.StringComparison]::OrdinalIgnoreCase)
}
if ($clientProcesses) {
    $names = ($clientProcesses | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ', '
    throw "Target client is running: $names"
}

$configBytesBefore = [System.IO.File]::ReadAllBytes($MiniMapConfig)
$configTextBefore = $encoding.GetString($configBytesBefore)
$matches = [regex]::Matches($configTextBefore, '(?m)^XX371\s+\d+\s*$')
if ($matches.Count -ne 1) {
    throw "Expected exactly one XX371 MiniMap row, found $($matches.Count)"
}

$other9901 = [regex]::Matches($configTextBefore, '(?m)^(?!XX371\s)\S+\s+9901\s*$')
if ($other9901.Count -ne 0) {
    throw 'MiniMap code 9901 is already used by another map.'
}

New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
Copy-Item -LiteralPath $TargetMmap -Destination (Join-Path $backupRoot '301.mmap.before') -Force
Copy-Item -LiteralPath $MiniMapConfig -Destination (Join-Path $backupRoot 'MiniMap.txt.before') -Force

$before = [ordered]@{
    targetMmapSha256 = (Get-FileHash -LiteralPath $TargetMmap -Algorithm SHA256).Hash
    miniMapConfigSha256 = (Get-FileHash -LiteralPath $MiniMapConfig -Algorithm SHA256).Hash
    miniMapRow = $matches[0].Value
}

$mmapTemp = "$TargetMmap.xy_tmp"
$configTemp = "$MiniMapConfig.xy_tmp"
try {
    Copy-Item -LiteralPath $SourceMmap -Destination $mmapTemp -Force
    Move-Item -LiteralPath $mmapTemp -Destination $TargetMmap -Force

    $configTextAfter = [regex]::Replace(
        $configTextBefore,
        '(?m)^XX371\s+\d+\s*$',
        'XX371 9901'
    )
    [System.IO.File]::WriteAllBytes($configTemp, $encoding.GetBytes($configTextAfter))
    Move-Item -LiteralPath $configTemp -Destination $MiniMapConfig -Force
} catch {
    if (Test-Path -LiteralPath $mmapTemp) { Remove-Item -LiteralPath $mmapTemp -Force }
    if (Test-Path -LiteralPath $configTemp) { Remove-Item -LiteralPath $configTemp -Force }
    Copy-Item -LiteralPath (Join-Path $backupRoot '301.mmap.before') -Destination $TargetMmap -Force
    Copy-Item -LiteralPath (Join-Path $backupRoot 'MiniMap.txt.before') -Destination $MiniMapConfig -Force
    throw
}

$sourceHash = (Get-FileHash -LiteralPath $SourceMmap -Algorithm SHA256).Hash
$targetHash = (Get-FileHash -LiteralPath $TargetMmap -Algorithm SHA256).Hash
$configTextReadback = $encoding.GetString([System.IO.File]::ReadAllBytes($MiniMapConfig))
$rowReadback = [regex]::Match($configTextReadback, '(?m)^XX371\s+\d+\s*$').Value

if ($sourceHash -ne $targetHash -or $rowReadback -ne 'XX371 9901') {
    Copy-Item -LiteralPath (Join-Path $backupRoot '301.mmap.before') -Destination $TargetMmap -Force
    Copy-Item -LiteralPath (Join-Path $backupRoot 'MiniMap.txt.before') -Destination $MiniMapConfig -Force
    throw 'Readback verification failed; original files were restored.'
}

$receipt = [ordered]@{
    schemaVersion = 1
    status = 'deployed-awaiting-game-verification'
    mapId = 'XX371'
    officialNativeFile = $TargetMmap
    officialNativeCode = 9901
    sourceCandidate = $SourceMmap
    sourceSha256 = $sourceHash
    targetSha256 = $targetHash
    configSha256 = (Get-FileHash -LiteralPath $MiniMapConfig -Algorithm SHA256).Hash
    before = $before
    afterMiniMapRow = $rowReadback
    backupRoot = $backupRoot
    engineTouched = $false
    clientLoginRegenerationRequired = $false
    nextStep = 'Close only the current M2 and wait for the engine to restart it, then enter XX371 and verify radar identity.'
}

New-Item -ItemType Directory -Path (Split-Path -Parent $ReportPath) -Force | Out-Null
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 6
