$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PartsDirectory = Join-Path $Root "package_parts"
$OutputZip = Join-Path $Root "艾尔登法环_第一大陆实际数据_V1_20260820.zip"
$ExpectedSha256 = "f43d31ecd745baae91f7c7693bdf7f146a18764d32c8f3dbba68a2ac4a0081b8"

$Parts = Get-ChildItem -LiteralPath $PartsDirectory -Filter "eld_c01_v1_20260820.zip.part-*" | Sort-Object Name
if ($Parts.Count -ne 29) {
    throw "压缩包分片数量错误：应为29，实际为$($Parts.Count)。"
}

$Output = [System.IO.File]::Create($OutputZip)
try {
    foreach ($Part in $Parts) {
        $Bytes = [System.IO.File]::ReadAllBytes($Part.FullName)
        $Output.Write($Bytes, 0, $Bytes.Length)
    }
}
finally {
    $Output.Dispose()
}

$ActualSha256 = (Get-FileHash -LiteralPath $OutputZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "SHA-256校验失败：$ActualSha256"
}

Write-Host "压缩包已还原并通过SHA-256校验：$OutputZip"
