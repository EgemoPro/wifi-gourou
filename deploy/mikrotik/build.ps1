# Construit les 2 images (agent + tailscale) au format tar importable par RouterOS.
# Prérequis : Docker Desktop (avec buildx).
#
# Usage :  .\deploy\mikrotik\build.ps1 [-Platform linux/arm64|linux/amd64] [-TsVersion v1.104.1]
#   linux/arm64 : hAP ax2/ax3, RB5009, L009...   (défaut)
#   linux/amd64 : CHR / x86
#
# Résultat : deploy\mikrotik\dist\<plateforme>\wz-agent.tar et wz-tailscale.tar
param(
    [string]$Platform  = "linux/arm64",
    [string]$TsVersion = "v1.104.1"
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

$arch = $Platform -replace "/", "-"
$out  = "deploy/mikrotik/dist/$arch"
New-Item -ItemType Directory -Force $out | Out-Null

Write-Host "==> Agent ($Platform)"
docker buildx build --platform $Platform `
    -f deploy/mikrotik/Dockerfile `
    -t wifizone/agent:local `
    --output "type=docker,dest=$out/wz-agent.tar" .
if ($LASTEXITCODE -ne 0) { throw "Build agent échoué" }

Write-Host "==> Tailscale $TsVersion ($Platform)"
docker buildx build --platform $Platform `
    -f deploy/mikrotik/tailscale/Dockerfile `
    --build-arg "TS_VERSION=$TsVersion" `
    -t wifizone/tailscale:local `
    --output "type=docker,dest=$out/wz-tailscale.tar" `
    deploy/mikrotik/tailscale
if ($LASTEXITCODE -ne 0) { throw "Build tailscale échoué" }

Get-ChildItem $out | Format-Table Name, Length
Write-Host "Copier ces 2 fichiers dans <clé USB>/wifizone/ sur le routeur."
