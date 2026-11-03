<#
.SYNOPSIS
    Build a folder that can be pushed to a Hugging Face Docker Space.

.DESCRIPTION
    The Space repository must contain README.md with sdk: docker and app_port: 7860
    at its root, plus the Dockerfile. This script copies only runtime files and
    excludes .env, node_modules, web/dist and local caches.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\prepare_hf_space.ps1
    powershell -ExecutionPolicy Bypass -File deploy\prepare_hf_space.ps1 -OutDir E:\duohereshui-hf -Force
#>
param(
    [string]$OutDir = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $OutDir) {
    $OutDir = Join-Path (Split-Path $Root -Parent) "duohereshui-hf"
}

if (Test-Path $OutDir) {
    if (-not $Force) {
        throw "Output directory already exists: $OutDir. Use -Force to overwrite."
    }
    Remove-Item $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

foreach ($file in @("Dockerfile", "entrypoint.sh", ".dockerignore", ".gitattributes")) {
    $source = Join-Path $Root $file
    if (-not (Test-Path $source)) {
        throw "Missing file: $source"
    }
    Copy-Item $source (Join-Path $OutDir $file) -Force
}

function Copy-Tree {
    param(
        [string]$Name,
        [string[]]$ExcludeDirs
    )
    $source = Join-Path $Root $Name
    $target = Join-Path $OutDir $Name
    $robocopyArgs = @($source, $target, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($ExcludeDirs.Count -gt 0) {
        $robocopyArgs += "/XD"
        $robocopyArgs += $ExcludeDirs
    }
    $robocopyArgs += @("/XF", ".env", "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db")
    & robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Copy failed for $Name, robocopy exit=$LASTEXITCODE"
    }
}

Copy-Tree -Name "backend" -ExcludeDirs @("__pycache__", ".pytest_cache")
Copy-Tree -Name "database" -ExcludeDirs @("__pycache__")
Copy-Tree -Name "web" -ExcludeDirs @("node_modules", "dist", ".vite-temp", ".esbuild-tmp")

Copy-Item (Join-Path $PSScriptRoot "hf-space\README.md") (Join-Path $OutDir "README.md") -Force

# Remove any .env accidentally copied from the local workspace.
Get-ChildItem $OutDir -Recurse -Force -Filter ".env" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

Set-Content -Path (Join-Path $OutDir ".gitignore") -Encoding utf8 -Value @"
.env
__pycache__/
*.pyc
.venv/
web/dist/
node_modules/
.pytest_cache/
"@

Write-Host ""
Write-Host "Hugging Face Space folder created:" -ForegroundColor Green
Write-Host "  $OutDir"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Create a Docker Space at https://huggingface.co/new-space"
Write-Host "     (name example: duohereshui, SDK: Docker, template: Blank)"
Write-Host "  2. Run:"
Write-Host "       cd `"$OutDir`""
Write-Host "       git init"
Write-Host "       git add ."
Write-Host "       git commit -m `"HF Space deploy`""
Write-Host "       git branch -M main"
Write-Host "       git remote add space https://huggingface.co/spaces/<username>/<space>"
Write-Host "       git push --force space main"
Write-Host ""
Write-Host "Use your Hugging Face username and an Access Token as the git password."
Write-Host "Alternative with huggingface_hub:"
Write-Host "  huggingface-cli login"
Write-Host "  huggingface-cli upload <username>/<space> `"$OutDir`" . --repo-type space"
Write-Host ""
Write-Host "Configure Space variables and secrets as described in docs/DEPLOY_HF_SPACES.md." -ForegroundColor Yellow
