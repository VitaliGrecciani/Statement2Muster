# Packaging Script for Statement2Muster Extensions (Chrome & Firefox)
# Generates reproducible, clean ZIP archives in dist/

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

$projectRoot = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $projectRoot "dist"
$tempBase = Join-Path $env:TEMP ("s2m_pkg_" + [System.Guid]::NewGuid().ToString("N"))

if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}

function Package-Extension {
    param (
        [string]$SourceDir,
        [string]$BrowserType
    )

    $manifestPath = Join-Path $SourceDir "manifest.json"
    if (-not (Test-Path $manifestPath)) {
        throw "manifest.json not found in $SourceDir"
    }

    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $version = $manifest.version
    $outputName = "statement2muster-$BrowserType-v$version.zip"
    $zipPath = Join-Path $distDir $outputName

    Write-Host "Packaging $BrowserType extension v$version from $SourceDir..."

    $stageDir = Join-Path $tempBase $BrowserType
    if (Test-Path $stageDir) { Remove-Item -Recurse -Force $stageDir }
    New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

    # Copy extension runtime files, excluding store_assets and raw screenshots
    Get-ChildItem -Path $SourceDir | ForEach-Object {
        $name = $_.Name
        if ($name -in @("store_assets", ".git", ".DS_Store", "Thumbs.db") -or $name.EndsWith(".zip")) {
            return
        }
        Copy-Item -Path $_.FullName -Destination (Join-Path $stageDir $name) -Recurse -Force
    }

    # Remove existing target zip if present
    if (Test-Path $zipPath) {
        Remove-Item -Force $zipPath
    }

    # Compress staging folder contents into target zip
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stageDir, $zipPath)

    $fileInfo = Get-Item $zipPath
    $hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash

    Write-Host "Created: $outputName"
    Write-Host "Size: $([math]::Round($fileInfo.Length / 1KB, 2)) KB ($($fileInfo.Length) bytes)"
    Write-Host "SHA256: $hash"
    Write-Host "--------------------------------------------------"
}

try {
    Write-Host "=== Statement2Muster Extension Packaging ==="
    Package-Extension -SourceDir (Join-Path $projectRoot "extension") -BrowserType "chrome"
    Package-Extension -SourceDir (Join-Path $projectRoot "extension_firefox_build") -BrowserType "firefox"
    Write-Host "Packaging completed successfully. Output in $distDir"
} finally {
    if (Test-Path $tempBase) {
        Remove-Item -Recurse -Force $tempBase -ErrorAction SilentlyContinue
    }
}
