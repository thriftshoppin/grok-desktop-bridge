#Requires -Version 5.1
<#
.SYNOPSIS
  ON starts the Grok guardian, loopback MCP on port 8790, and a cloudflared tunnel.
  OFF stops only this install's owned processes, after PID creation-time checks.

.DESCRIPTION
  Double-click GrokBridge-LightSwitch.cmd. The window stays open. Tokens are never printed.
  UAC Cancel (error 1223) rolls back anything this switch started and does not use the scheduled task.
#>
[CmdletBinding()]
param(
    [ValidateSet("Toggle", "On", "Off", "Status")]
    [string]$Action = "Toggle",
    [string]$BridgeRoot = "",
    [int]$Port = 8790,
    [switch]$FromCmd
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "scripts\GrokBridgeLib.ps1")

$script:TranscriptOn = $false
$script:GrokExit = 1

function Stop-GrokTranscript {
    if ($script:TranscriptOn) {
        try { Stop-Transcript | Out-Null } catch { }
        $script:TranscriptOn = $false
    }
}

function Exit-Grok {
    param([int]$Code)
    $script:GrokExit = $Code
    Write-Host ("FINAL EXIT CODE: " + $Code)
    Stop-GrokTranscript
    if (-not $FromCmd) {
        Write-Host "Press Enter to close this window."
        try { [void](Read-Host) } catch { }
    }
    exit $Code
}

function Convert-CreationStamp {
    param($Value)
    if ($null -eq $Value -or $Value -eq "") { return "" }
    if ($Value -is [datetime]) { return [string]$Value.ToUniversalTime().Ticks }
    return [string]$Value
}

function Get-ProcessIdentity {
    param([int]$ProcessId)
    $proc = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId=" + $ProcessId) -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    return [pscustomobject]@{
        Pid = [int]$proc.ProcessId
        Creation = (Convert-CreationStamp $proc.CreationDate)
        Image = [string]$proc.ExecutablePath
        CommandLine = [string]$proc.CommandLine
    }
}

function Get-OwnedGrokProcesses {
    param([string]$Root, [int]$ListenPort)
    $out = @()
    $titles = @{}
    foreach ($gp in @(Get-Process -ErrorAction SilentlyContinue)) {
        if ($gp.MainWindowTitle) { $titles[[int]$gp.Id] = [string]$gp.MainWindowTitle }
    }
    $procs = @(Get-CimInstance -ClassName Win32_Process -ErrorAction SilentlyContinue)
    foreach ($proc in $procs) {
        $cl = [string]$proc.CommandLine
        $img = [string]$proc.ExecutablePath
        $title = [string]$titles[[int]$proc.ProcessId]
        $owned = Test-OwnedGrokProcess -CommandLine $cl -Executable $img -BridgeRoot $Root -Port $ListenPort
        if ((-not $owned) -and $title.StartsWith("Grok Desktop Bridge - live action feed") -and (Test-PathUnder $img $Root)) {
            # Elevated guardian command lines are often unreadable. The feed title plus our venv image is still this install.
            $owned = $true
        }
        if ($owned) {
            $out += [pscustomobject]@{
                Pid = [int]$proc.ProcessId
                Creation = (Convert-CreationStamp $proc.CreationDate)
                Image = $img
                CommandLine = $cl
            }
        }
    }
    return $out
}

function Stop-IfSameProcess {
    param($Recorded)
    if (-not $Recorded) { return "nothing-recorded" }
    $current = Get-ProcessIdentity -ProcessId ([int]$Recorded.Pid)
    $cur = $null
    if ($current) {
        $cur = @{ Pid = $current.Pid; Creation = $current.Creation; Image = $current.Image }
    }
    $rec = @{ Pid = $Recorded.Pid; Creation = $Recorded.Creation; Image = $Recorded.Image }
    $check = Test-SafeToStop $rec $cur
    if (-not $check.Ok) {
        Write-Host ("skip PID " + $Recorded.Pid + ": " + $check.Why)
        return $check.Why
    }
    Write-Host ("stopping PID " + $Recorded.Pid + " " + $Recorded.Image)
    Stop-Process -Id ([int]$Recorded.Pid) -Force -ErrorAction Stop
    return "stopped"
}

function Get-LoopbackStatus {
    param([int]$ListenPort)
    $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:" + $ListenPort + "/mcp")
    $req.Method = "GET"
    $req.Timeout = 2500
    $req.UserAgent = "grok-bot"
    $req.Headers.Add("X-Grok-Bridge-Client", "grok-bot")
    try {
        $resp = $req.GetResponse()
        try { return [int]$resp.StatusCode } finally { $resp.Close() }
    } catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($response) {
            try { return [int]$response.StatusCode } finally { $response.Close() }
        }
        return 0
    }
}

function Test-GuardianOwned {
    param($Procs)
    foreach ($proc in @($Procs)) {
        $cl = ""
        if ($proc.CommandLine) { $cl = $proc.CommandLine.ToLowerInvariant() }
        if ($cl.Contains("desktop_bridge.worker") -and $cl.Contains("--guardian") -and ($cl -match "--instance(\s+|=)grok\b")) {
            return $true
        }
    }
    return $false
}

function Read-FinalExit {
    param([string]$Text)
    if (-not $Text) { return $null }
    $m = [regex]::Match($Text, "FINAL EXIT CODE:\s*(-?\d+)")
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return $null
}

function Start-VisibleRunner {
    param([string]$ScriptPath, [string[]]$Arguments)
    $parts = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $ScriptPath) + @($Arguments)
    $quoted = @()
    foreach ($part in $parts) {
        $text = [string]$part
        if ($text.Contains(" ") -or $text.Contains('"')) {
            $quoted += ('"' + ($text.Replace('"', '\"')) + '"')
        } else {
            $quoted += $text
        }
    }
    $argLine = [string]::Join(" ", $quoted)
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argLine -WindowStyle Normal -PassThru
    $identity = $null
    for ($i = 0; $i -lt 20; $i++) {
        $identity = Get-ProcessIdentity -ProcessId $proc.Id
        if ($identity -and $identity.Creation) { break }
        Start-Sleep -Milliseconds 150
    }
    if (-not $identity) { throw "started process $($proc.Id) but could not read its identity" }
    Write-Host ("started PID " + $identity.Pid + " creation " + $identity.Creation)
    return $identity
}

function Invoke-RollbackStarted {
    param($Before, $Root, [int]$ListenPort, $Extra)
    Write-Host "STEP: rollback partial startup"
    $beforeIds = @{}
    foreach ($row in @($Before)) { $beforeIds[[int]$row.Pid] = $true }
    $now = @(Get-OwnedGrokProcesses -Root $Root -ListenPort $ListenPort)
    foreach ($proc in $now) {
        if ($beforeIds.ContainsKey([int]$proc.Pid)) {
            Write-Host ("leave pre-existing PID " + $proc.Pid)
            continue
        }
        Stop-IfSameProcess $proc
    }
    foreach ($extra in @($Extra)) {
        if ($extra) { Stop-IfSameProcess $extra }
    }
}

try {
    $dir = Join-Path $env:USERPROFILE "GrokDesktopBridge-logs"
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:GrokLogPath = Join-Path $dir ("lightswitch-" + $stamp + ".log")
    Start-Transcript -LiteralPath $script:GrokLogPath -Force | Out-Null
    $script:TranscriptOn = $true
    Write-Host ("Log: " + $script:GrokLogPath)

    if (-not $BridgeRoot) { $BridgeRoot = Join-Path $env:USERPROFILE "grok-desktop-bridge" }
    $BridgeRoot = (Resolve-Path -LiteralPath $BridgeRoot).Path
    $launcher = Join-Path $BridgeRoot "launcher.py"
    $venvPy = Join-Path (Join-Path (Join-Path $BridgeRoot ".venv") "Scripts") "python.exe"
    if (-not (Test-Path -LiteralPath $launcher)) { throw "launcher.py not found under $BridgeRoot" }
    if (-not (Test-Path -LiteralPath $venvPy)) { throw "isolated venv python not found at $venvPy. Run Install-GrokBridge.cmd first." }
    $env:DESKTOP_BRIDGE_INSTANCE = "grok"
    Write-Host ("Bridge root: " + $BridgeRoot)
    Write-Host ("Instance: grok  Port: " + $Port)

    $owned = @(Get-OwnedGrokProcesses -Root $BridgeRoot -ListenPort $Port)
    Write-Host ("Owned Grok processes: " + @($owned).Count)
    foreach ($proc in $owned) {
        Write-Host ("  PID " + $proc.Pid + " " + $proc.Image)
    }

    $listening = $false
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) { $listening = $true }
    } catch { }
    if (-not $listening) {
        $net = netstat -ano | Select-String -Pattern (":" + $Port + "\s+.*LISTENING")
        if ($net) { $listening = $true }
    }
    Write-Host ("Port " + $Port + " listening: " + $listening)

    if ($Action -eq "Status") {
        if ($owned.Count -gt 0 -or $listening) { Write-Host "Status: ON" } else { Write-Host "Status: OFF" }
        Exit-Grok 0
    }

    $foreign = $false
    if ($listening -and $owned.Count -eq 0) { $foreign = $true }
    if ($foreign -and ($Action -eq "On" -or $Action -eq "Toggle")) {
        throw "Port $Port is already in use by a process this switch does not own. It was not stopped."
    }

    $doOff = $false
    if ($Action -eq "Off") { $doOff = $true }
    elseif ($Action -eq "Toggle" -and ($owned.Count -gt 0)) { $doOff = $true }

    if (($Action -eq "On") -and ($owned.Count -gt 0)) {
        Write-Host "Already ON. Not starting a second copy."
        Exit-Grok 0
    }

    if ($doOff) {
        Write-Host "STEP: OFF"
        foreach ($proc in $owned) { Stop-IfSameProcess $proc }
        Start-Sleep -Seconds 1
        $left = @(Get-OwnedGrokProcesses -Root $BridgeRoot -ListenPort $Port)
        if ($left.Count -gt 0) {
            Write-Host "Some owned processes are still running:"
            foreach ($proc in $left) { Write-Host ("  PID " + $proc.Pid) }
            Exit-Grok 1
        }
        Write-Host "Owned Grok processes are stopped."
        Exit-Grok 0
    }

    Write-Host "STEP: ON preflight"
    $cloud = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloud) {
        throw "cloudflared is not on PATH. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ and run this switch again. Nothing was started."
    }
    $before = @(Get-OwnedGrokProcesses -Root $BridgeRoot -ListenPort $Port)
    $script:LightSwitchBefore = @($before)
    $script:LightSwitchStarted = @()
    $remoteLog = Join-Path $dir ("remote-" + $stamp + ".log")
    $tunnelLog = Join-Path $dir ("tunnel-" + $stamp + ".log")
    New-Item -ItemType File -Path $remoteLog -Force | Out-Null
    New-Item -ItemType File -Path $tunnelLog -Force | Out-Null
    $started = @()
    Write-Host "STEP: start guardian and loopback HTTP (approve the UAC prompt; Cancel rolls this back)"
    $remoteRunner = Join-Path (Join-Path $BridgeRoot "scripts") "GrokBridge-RunRemote.ps1"
    $tunnelRunner = Join-Path (Join-Path $BridgeRoot "scripts") "GrokBridge-RunTunnel.ps1"
    $remoteProc = Start-VisibleRunner -ScriptPath $remoteRunner -Arguments @($venvPy, $BridgeRoot, "$Port", $remoteLog)
    $started += $remoteProc
    $script:LightSwitchStarted = @($started)
    $tunnelProc = $null
    $deadline = (Get-Date).AddSeconds(180)
    $result = $null
    while ($true) {
        $logText = Protect-LogText (Read-SharedText $remoteLog)
        $exitCode = Read-FinalExit $logText
        $http = 0
        try { $http = Get-LoopbackStatus -ListenPort $Port } catch { $http = 0 }
        $nowOwned = @(Get-OwnedGrokProcesses -Root $BridgeRoot -ListenPort $Port)
        $guardian = Test-GuardianOwned $nowOwned
        $url = Get-TunnelUrlFromText (Read-SharedText $tunnelLog)
        $timedOut = (Get-Date) -gt $deadline
        if (($null -eq $tunnelProc) -and ($http -eq 401) -and $guardian -and ($null -eq $exitCode)) {
            Write-Host "STEP: HTTP 401 and guardian are up. Starting cloudflared."
            $tunnelProc = Start-VisibleRunner -ScriptPath $tunnelRunner -Arguments @($cloud.Source, "$Port", $tunnelLog)
            $started += $tunnelProc
            $script:LightSwitchStarted = @($started)
            $deadline = (Get-Date).AddSeconds(60)
        }
        $result = Get-StartupClass -LauncherExit $exitCode -LogText $logText -HttpStatus $http -GuardianOwned $guardian -TunnelUrl $url -TimedOut $timedOut
        Write-Host ("state=" + $result.State + " http=" + $http + " guardian=" + $guardian + " " + $result.Reason)
        if ($result.State -eq "ready") { break }
        if ($result.Rollback) { break }
        Start-Sleep -Seconds 1
    }
    if ($result.State -ne "ready") {
        Invoke-RollbackStarted -Before $before -Root $BridgeRoot -ListenPort $Port -Extra $started
        if ($result.State -eq "uac_cancelled") { Exit-Grok 1223 }
        Exit-Grok 1
    }
    $url = Get-TunnelUrlFromText (Read-SharedText $tunnelLog)
    Write-Host ("Tunnel URL: " + $url)
    Write-Host ("Remote log: " + $remoteLog)
    Write-Host ("Tunnel log: " + $tunnelLog)
    Write-Host "Bearer tokens are not printed. Create one, if you have not, with:"
    Write-Host ("  " + $venvPy + " launcher.py --add-bot work")
    Write-Host "Grok header: X-Grok-Bridge-Client: grok-bot"
    Write-Host "Esc stays global while Grok is in control. The feed window stays visible without taking focus."
    Exit-Grok 0
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    Write-Host $_.ScriptStackTrace
    if ($script:LightSwitchStarted -and $BridgeRoot) {
        try {
            Invoke-RollbackStarted -Before $script:LightSwitchBefore -Root $BridgeRoot -ListenPort $Port -Extra $script:LightSwitchStarted
        } catch {
            Write-Host ("rollback error: " + $_.Exception.Message)
        }
    }
    $code = 1
    if ($_.Exception.Message -match "exit code (\d+)") { $code = [int]$Matches[1] }
    Exit-Grok $code
}
