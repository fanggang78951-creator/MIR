param(
    [Parameter(Mandatory = $true)]
    [string]$SourceImage,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [int]$CropX = 32,
    [int]$CropY = 125,
    [int]$Width = 296,
    [int]$Height = 302,
    [int]$Feather = 18,
    [double]$InteriorDarken = 0.22
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$source = [System.Drawing.Bitmap]::FromFile($SourceImage)
try {
    if ($CropX -lt 0 -or $CropY -lt 0 -or
        ($CropX + $Width) -gt $source.Width -or
        ($CropY + $Height) -gt $source.Height) {
        throw "Crop rectangle is outside source image bounds."
    }

    $crop = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($crop)
        try {
            $graphics.DrawImage(
                $source,
                (New-Object System.Drawing.Rectangle(0, 0, $Width, $Height)),
                (New-Object System.Drawing.Rectangle($CropX, $CropY, $Width, $Height)),
                [System.Drawing.GraphicsUnit]::Pixel
            )
        }
        finally {
            $graphics.Dispose()
        }

        # Keep the outer edge unchanged for pixel-perfect continuity. Darken only
        # the interior with a short feather so labels remain readable.
        for ($y = 0; $y -lt $Height; $y++) {
            for ($x = 0; $x -lt $Width; $x++) {
                $edgeDistance = [Math]::Min([Math]::Min($x, $Width - 1 - $x), [Math]::Min($y, $Height - 1 - $y))
                $weight = $InteriorDarken * [Math]::Min(1.0, $edgeDistance / [double]$Feather)
                if ($weight -le 0) {
                    continue
                }

                $color = $crop.GetPixel($x, $y)
                $scale = 1.0 - $weight
                $crop.SetPixel(
                    $x,
                    $y,
                    [System.Drawing.Color]::FromArgb(
                        [int][Math]::Round($color.R * $scale),
                        [int][Math]::Round($color.G * $scale),
                        [int][Math]::Round($color.B * $scale)
                    )
                )
            }
        }

        $previewDirectory = Join-Path $OutputDirectory 'preview'
        $productionDirectory = Join-Path $OutputDirectory 'production'
        New-Item -ItemType Directory -Path $previewDirectory -Force | Out-Null
        New-Item -ItemType Directory -Path $productionDirectory -Force | Out-Null

        $previewPath = Join-Path $previewDirectory 'XY_Character_SeamlessInner_296x302_preview.png'
        $compositePreviewPath = Join-Path $previewDirectory 'XY_Character_SeamlessInner_composite_preview.png'
        $productionPath = Join-Path $productionDirectory 'XY_Character_SeamlessInner_296x302_24bit.bmp'
        $crop.Save($previewPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $crop.Save($productionPath, [System.Drawing.Imaging.ImageFormat]::Bmp)

        $composite = New-Object System.Drawing.Bitmap($source.Width, $source.Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
        try {
            $compositeGraphics = [System.Drawing.Graphics]::FromImage($composite)
            try {
                $compositeGraphics.DrawImageUnscaled($source, 0, 0)
                $compositeGraphics.DrawImageUnscaled($crop, $CropX, $CropY)
            }
            finally {
                $compositeGraphics.Dispose()
            }
            $composite.Save($compositePreviewPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $composite.Dispose()
        }

        $hash = (Get-FileHash -LiteralPath $productionPath -Algorithm SHA256).Hash
        $manifest = [ordered]@{
            id = 'xy-character-seamless-inner-page-296x302'
            version = '0.1.0-candidate.1'
            status = 'awaiting-pak-import'
            source = $SourceImage
            crop = [ordered]@{ left = $CropX; top = $CropY; width = $Width; height = $Height }
            treatment = [ordered]@{ feather = $Feather; interiorDarken = $InteriorDarken }
            preview = 'preview/XY_Character_SeamlessInner_296x302_preview.png'
            compositePreview = 'preview/XY_Character_SeamlessInner_composite_preview.png'
            production = 'production/XY_Character_SeamlessInner_296x302_24bit.bmp'
            width = $Width
            height = $Height
            pixelFormat = '24bppRgb'
            productionSha256 = $hash
            target = [ordered]@{
                scene = '连击界面 / 人物相关 / 人物属性 / 基础属性分组'
                controls = @('DStateTabSheet2', 'DStateTabSheet3', 'DStateTabSheet4', 'DStateTabSheet5', 'DStateTabSheet6')
                controlType = 'TDxTabSheet'
                library = 'NewUI5_PAK'
                expectedTailIndex = 1913
                left = 23
                top = 0
                width = $Width
                height = $Height
                absoluteOuterPosition = [ordered]@{ x = $CropX; y = $CropY }
                before = [ordered]@{ library = 'NewopUI_Pak'; defaultImage = 464; mouseDownImage = 465 }
            }
            next = '尾部添加生产BMP并记录实际编号；五个TabSheet的默认图片和鼠标按下均绑定该编号。'
        }
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'manifest.json') -Encoding UTF8

        [pscustomobject]@{
            Preview = $previewPath
            CompositePreview = $compositePreviewPath
            Production = $productionPath
            Sha256 = $hash
        }
    }
    finally {
        $crop.Dispose()
    }
}
finally {
    $source.Dispose()
}
