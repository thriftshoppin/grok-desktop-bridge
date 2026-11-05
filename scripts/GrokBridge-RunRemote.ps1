#Requires -Version 5.1
# Visible remote-launcher window. Started with powershell -NoExit so it stays open.
param(
    [string]$Python,
    [string]$Root,
    [int]$Port = 8790,
    [string]$LogPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GrokBridgeLib.ps1")
Set-Location -LiteralPath $Root
$env:DESKTOP_BRIDGE_INSTANCE = "grok"
Write-Host ("STEP: remote launcher in " + $Root)
Write-Host ("Python: " + $Python)
Write-Host ("Port: " + $Port)
Write-Host ("Log: " + $LogPath)
if (-not (Test-Path -LiteralPath $Python)) { throw "python not found: $Python" }
$ec = 0
& $Python -u (Join-Path $Root "launcher.py") --remote --port "$Port" 2>&1 | ForEach-Object {
    $safe = Protect-LogText "$_"
    Add-Content -LiteralPath $LogPath -Value $safe -Encoding UTF8
    Write-Host $safe
}
$ec = $LASTEXITCODE
if ($null -eq $ec) { $ec = 0 }
$line = "FINAL EXIT CODE: $ec"
Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
Write-Host $line
Write-Host "This window stays open. Closing it does not by itself stop an elevated guardian; use the light switch OFF."
