param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $PSScriptRoot
$masterPath = Join-Path $repoRoot "assets\app-icon-square.png"
$windowsIconPath = Join-Path $repoRoot "packaging\windows\app_icon.ico"

function Save-ResizedPng {
    param(
        [System.Drawing.Image]$Source,
        [int]$Size,
        [string]$Destination
    )

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.DrawImage($Source, 0, 0, $Size, $Size)
        $bitmap.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function New-IcoFile {
    param(
        [System.Drawing.Image]$Source,
        [int[]]$Sizes,
        [string]$Destination
    )

    $payloads = @()
    foreach ($size in $Sizes) {
        $bitmap = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $stream = New-Object System.IO.MemoryStream
        try {
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.DrawImage($Source, 0, 0, $size, $size)
            $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            $payloads += [pscustomobject]@{ Size = $size; Bytes = $stream.ToArray() }
        } finally {
            $stream.Dispose()
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $fileStream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter($fileStream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$payloads.Count)
        $offset = 6 + (16 * $payloads.Count)
        foreach ($payload in $payloads) {
            $dimension = if ($payload.Size -eq 256) { 0 } else { $payload.Size }
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$payload.Bytes.Length)
            $writer.Write([uint32]$offset)
            $offset += $payload.Bytes.Length
        }
        foreach ($payload in $payloads) {
            $writer.Write($payload.Bytes)
        }
    } finally {
        $writer.Dispose()
        $fileStream.Dispose()
    }
}

$resolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
$source = [System.Drawing.Bitmap]::FromFile($resolvedSource)
try {
    $side = [Math]::Min($source.Width, $source.Height)
    $cropX = [int][Math]::Floor(($source.Width - $side) / 2)
    $cropY = [int][Math]::Floor(($source.Height - $side) / 2)
    $cropRectangle = New-Object System.Drawing.Rectangle($cropX, $cropY, $side, $side)
    $square = $source.Clone($cropRectangle, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        New-Item -ItemType Directory -Path (Split-Path -Parent $masterPath) -Force | Out-Null
        $square.Save($masterPath, [System.Drawing.Imaging.ImageFormat]::Png)

        $androidSizes = [ordered]@{
            "mipmap-mdpi" = 48
            "mipmap-hdpi" = 72
            "mipmap-xhdpi" = 96
            "mipmap-xxhdpi" = 144
            "mipmap-xxxhdpi" = 192
        }
        foreach ($entry in $androidSizes.GetEnumerator()) {
            $destination = Join-Path $repoRoot "android\app\src\main\res\$($entry.Key)\ic_launcher.png"
            Save-ResizedPng -Source $square -Size $entry.Value -Destination $destination
        }

        New-IcoFile -Source $square -Sizes @(16, 24, 32, 48, 64, 128, 256) -Destination $windowsIconPath
        [pscustomobject]@{
            Source = $resolvedSource
            Crop = "x=$cropX, y=$cropY, size=${side}x${side}"
            Master = $masterPath
            WindowsIcon = $windowsIconPath
        } | Format-List
    } finally {
        $square.Dispose()
    }
} finally {
    $source.Dispose()
}
