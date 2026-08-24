$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $PSScriptRoot
$assetDir = Join-Path $repoRoot 'tests\assets'
New-Item -ItemType Directory -Force -Path $assetDir | Out-Null

function New-DrawingSurface {
    $bitmap = [System.Drawing.Bitmap]::new(1200, 800)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::White)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::None
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::SingleBitPerPixelGridFit
    return @($bitmap, $graphics)
}

function Save-TopFixture {
    param([string]$Path)

    $surface = New-DrawingSurface
    $bitmap = $surface[0]
    $graphics = $surface[1]
    $outlinePen = [System.Drawing.Pen]::new([System.Drawing.Color]::Black, 6)
    $dimensionPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(70, 70, 70), 2)
    $titleFont = [System.Drawing.Font]::new('Arial', 28, [System.Drawing.FontStyle]::Bold)
    $labelFont = [System.Drawing.Font]::new('Arial', 20, [System.Drawing.FontStyle]::Regular)
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::Black)
    try {
        $graphics.DrawString('L PROFILE - TOP (XY)', $titleFont, $brush, 40, 28)
        $points = [System.Drawing.Point[]]@(
            [System.Drawing.Point]::new(250, 610),
            [System.Drawing.Point]::new(950, 610),
            [System.Drawing.Point]::new(950, 190),
            [System.Drawing.Point]::new(670, 190),
            [System.Drawing.Point]::new(670, 400),
            [System.Drawing.Point]::new(250, 400)
        )
        $graphics.DrawPolygon($outlinePen, $points)

        $graphics.DrawLine($dimensionPen, 250, 660, 950, 660)
        $graphics.DrawLine($dimensionPen, 250, 642, 250, 678)
        $graphics.DrawLine($dimensionPen, 950, 642, 950, 678)
        $graphics.DrawString('100 mm', $labelFont, $brush, 545, 670)

        $graphics.DrawLine($dimensionPen, 190, 190, 190, 610)
        $graphics.DrawLine($dimensionPen, 172, 190, 208, 190)
        $graphics.DrawLine($dimensionPen, 172, 610, 208, 610)
        $graphics.DrawString('60 mm', $labelFont, $brush, 75, 385)

        $graphics.DrawLine($dimensionPen, 670, 135, 950, 135)
        $graphics.DrawLine($dimensionPen, 670, 118, 670, 152)
        $graphics.DrawLine($dimensionPen, 950, 118, 950, 152)
        $graphics.DrawString('40 mm', $labelFont, $brush, 765, 92)

        $graphics.DrawLine($dimensionPen, 720, 190, 720, 400)
        $graphics.DrawLine($dimensionPen, 702, 190, 738, 190)
        $graphics.DrawLine($dimensionPen, 702, 400, 738, 400)
        $graphics.DrawString('30 mm', $labelFont, $brush, 742, 278)
        $graphics.DrawString('All dimensions exact', $labelFont, $brush, 850, 735)

        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $brush.Dispose()
        $labelFont.Dispose()
        $titleFont.Dispose()
        $dimensionPen.Dispose()
        $outlinePen.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Save-FrontFixture {
    param([string]$Path)

    $surface = New-DrawingSurface
    $bitmap = $surface[0]
    $graphics = $surface[1]
    $outlinePen = [System.Drawing.Pen]::new([System.Drawing.Color]::Black, 6)
    $dimensionPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(70, 70, 70), 2)
    $titleFont = [System.Drawing.Font]::new('Arial', 28, [System.Drawing.FontStyle]::Bold)
    $labelFont = [System.Drawing.Font]::new('Arial', 20, [System.Drawing.FontStyle]::Regular)
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::Black)
    try {
        $graphics.DrawString('L PROFILE - FRONT (XZ)', $titleFont, $brush, 40, 28)
        $graphics.DrawRectangle($outlinePen, 250, 320, 700, 120)

        $graphics.DrawLine($dimensionPen, 250, 510, 950, 510)
        $graphics.DrawLine($dimensionPen, 250, 492, 250, 528)
        $graphics.DrawLine($dimensionPen, 950, 492, 950, 528)
        $graphics.DrawString('100 mm', $labelFont, $brush, 545, 525)

        $graphics.DrawLine($dimensionPen, 1010, 320, 1010, 440)
        $graphics.DrawLine($dimensionPen, 992, 320, 1028, 320)
        $graphics.DrawLine($dimensionPen, 992, 440, 1028, 440)
        $graphics.DrawString('8 mm', $labelFont, $brush, 1038, 365)
        $graphics.DrawString('Extrude +Z', $labelFont, $brush, 250, 270)
        $graphics.DrawString('All dimensions exact', $labelFont, $brush, 850, 735)

        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $brush.Dispose()
        $labelFont.Dispose()
        $titleFont.Dispose()
        $dimensionPen.Dispose()
        $outlinePen.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

Save-TopFixture -Path (Join-Path $assetDir 'profile-l-top.png')
Save-FrontFixture -Path (Join-Path $assetDir 'profile-l-front.png')
