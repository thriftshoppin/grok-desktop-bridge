#Requires -Version 5.1
# Visible cloudflared window. Started with powershell -NoExit so it stays open.
param(
    [string]$Cloudflared,
    [int]$Port = 8790,
    [string]$LogPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GrokBridgeLib.ps1")
Write-Host ("STEP: cloudflared tunnel to 127.0.0.1:" + $Port)
Write-Host ("cloudflared: " + $Cloudflared)
Write-Host ("Log: " + $LogPath)
$ec = 0
& $Cloudflared tunnel --url ("http://127.0.0.1:" + $Port) 2>&1 | ForEach-Object {
    $safe = Protect-LogText "$_"
    Add-Content -LiteralPath $LogPath -Value $safe -Encoding UTF8
    Write-Host $safe
}
$ec = $LASTEXITCODE
if ($null -eq $ec) { $ec = 0 }
$line = "FINAL EXIT CODE: $ec"
Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
Write-Host $line
Write-Host "This window stays open."
