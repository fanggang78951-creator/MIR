param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$PlatformRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
function Get-BoundPath([string]$RelativePath) {
    if ([IO.Path]::IsPathRooted($RelativePath)) { throw "Release path must be relative: $RelativePath" }
    $CandidatePath = [IO.Path]::GetFullPath((Join-Path $PlatformRoot $RelativePath))
    if (-not $CandidatePath.StartsWith($PlatformRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Release path escapes platform: $RelativePath" }
    $WalkPath = $PlatformRoot
    foreach ($Part in $RelativePath.Replace('/', '\').Split('\')) {
        $WalkPath = Join-Path $WalkPath $Part
        if ((Get-Item -LiteralPath $WalkPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Release path is a link: $RelativePath" }
    }
    return $CandidatePath
}
function Assert-Hash([string]$RelativePath, [string]$ExpectedHash) {
    if ($ExpectedHash -notmatch '^[A-Fa-f0-9]{64}$') { throw "Missing release fingerprint: $RelativePath" }
    $BoundPath = Get-BoundPath $RelativePath
    if ((Get-FileHash -LiteralPath $BoundPath -Algorithm SHA256).Hash -ne $ExpectedHash) { throw "Release file changed: $RelativePath" }
    return $BoundPath
}
$ReceiptPath = Join-Path $PlatformRoot 'catalog\current-release.json'
$Release = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Release.source_and_package_fingerprints) { throw 'Release has no source/package fingerprints.' }
$GuiPath = Assert-Hash $Release.gui.path $Release.gui.sha256
$null = Assert-Hash $Release.cli.path $Release.cli.sha256
foreach ($Property in $Release.source_and_package_fingerprints.PSObject.Properties) {
    $null = Assert-Hash $Property.Name $Property.Value
}
if ($VerifyOnly) {
    [PSCustomObject]@{ status='passed'; release_id=$Release.release_id; gui=$GuiPath } | ConvertTo-Json -Compress
} else {
    Start-Process -FilePath $GuiPath -WorkingDirectory $PlatformRoot -WindowStyle Normal
}
