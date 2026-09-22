param(
    [string]$Root = 'D:\XuanYuanDevPlatform',
    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
$rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) {
    throw "Platform root not found: $rootPath"
}
if ([string]::IsNullOrWhiteSpace($Output)) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $Output = Join-Path $rootPath "evidence\TempInventory_$stamp.json"
}

$protectedTop = @(
    'assets', 'backups', 'catalog', 'evidence', 'knowledge', 'library',
    'map-replication-projects', 'migration', 'packages', 'templates',
    '所需材料表格汇总', '怪物库', '接口', '非常驻脚本', 'NPC脚本'
)
$safeGeneratedTop = @('build', 'tmp', '__pycache__')
$reviewTop = @('outputs', 'logs', 'testbeds')

# Legacy inventory entry point now delegates to the bounded Python scanner.
# The old implementation loaded every file in the whole platform into memory,
# which was slow and could terminate before writing its report.  The new scan
# only walks defined candidate locations and hard-skips assets/evidence/packages.
$python = Get-Command python -ErrorAction Stop
$runner = Join-Path $rootPath 'tools\temp-cleaner\run_cleaner.py'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Cleaner runner not found: $runner"
}
& $python.Source $runner scan --root $rootPath --days 14 --output $Output
if ($LASTEXITCODE -ne 0) {
    throw "Cleaner scan failed with exit code $LASTEXITCODE"
}
exit 0

function Measure-Candidate([object[]]$Items) {
    $sum = ($Items | Measure-Object Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    return [ordered]@{
        files = $Items.Count
        bytes = [int64]$sum
        gib = [math]::Round(([double]$sum / 1GB), 3)
    }
}
