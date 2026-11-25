[CmdletBinding()]
param(
    [switch]$SkipArchive
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SpecPath = Join-Path $RepoRoot "packaging\windows\document-intelligence-navigator.spec"
$DistDir = Join-Path $RepoRoot "dist\DocumentIntelligenceNavigator"
$ArchivePath = Join-Path $RepoRoot "dist\DocumentIntelligenceNavigator-windows-x64.zip"

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python not found at $VenvPython. Create .venv and install '.[dev,build]' first."
}

Push-Location $RepoRoot
try {
    Write-Host "Building standalone Windows package with PyInstaller..."
    & $VenvPython -m PyInstaller --clean --noconfirm $SpecPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }

    $ExePath = Join-Path $DistDir "DocumentIntelligenceNavigator.exe"
    if (-not (Test-Path $ExePath)) {
        throw "Expected executable not found at $ExePath."
    }

    Write-Host "Built executable: $ExePath"

    if (-not $SkipArchive) {
        if (Test-Path $ArchivePath) {
            Remove-Item $ArchivePath -Force
        }
        Compress-Archive -Path $DistDir -DestinationPath $ArchivePath -CompressionLevel Optimal
        $Hash = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash
        $ChecksumPath = "$ArchivePath.sha256"
        $ArchiveName = Split-Path -Leaf $ArchivePath
        [System.IO.File]::WriteAllText(
            $ChecksumPath,
            "$Hash  $ArchiveName`n",
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Built zip archive: $ArchivePath"
        Write-Host "Built checksum file: $ChecksumPath"
        Write-Host "SHA-256: $Hash"
    }
}
finally {
    Pop-Location
}
