#Requires -Version 5.1
<#
.SYNOPSIS
  Show every old Grok install target, confirm, remove only that list, then install fresh.

.DESCRIPTION
  Double-click Install-GrokBridge.cmd so the window stays open on parse errors and on failure.
  Dry run:  powershell -File .\Install-GrokBridge.ps1 -DryRun
  Removes only paths it prints. Does not walk reparse points. Does not remove Claude/Codex
  desktop-mcp-bridge folders unless -IncludeOtherClientPath names that exact path and you type
  the longer confirmation phrase. Does not print token file contents.
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$FromCmd,
    [switch]$SelfTest,
    [string]$ConfirmPhrase = "",
    [string]$InstallDir = "",
    [string[]]$IncludeOtherClientPath = @(),
    [switch]$SkipCleanup
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "scripts\GrokBridgeLib.ps1")

$script:GrokExit = 1
$script:TranscriptOn = $false

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

function Start-GrokTranscript {
    $dir = Join-Path $env:USERPROFILE "GrokDesktopBridge-logs"
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:GrokLogPath = Join-Path $dir ("install-" + $stamp + ".log")
    Start-Transcript -LiteralPath $script:GrokLogPath -Force | Out-Null
    $script:TranscriptOn = $true
    Write-Host ("Log: " + $script:GrokLogPath)
}

function Get-LivePython {
    $launcher = ""
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $launcher = $py.Source }
    $extras = @()
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { $extras += $python.Source }
    $found = Find-SupportedPython -Launcher $launcher -LocalAppData $env:LOCALAPPDATA -UserProfile $env:USERPROFILE -ExtraExecutables $extras
    foreach ($note in $found.Notes) { Write-Host $note }
    Write-Host ("Using Python: " + $found.Path)
    return $found.Path
}

function Get-ExplicitTargets {
    param([string]$Destination, [string]$PackageRoot)
    $rows = @()
    $local = Join-Path $env:LOCALAPPDATA "GrokDesktopBridge"
    $program = Join-Path $env:ProgramData "GrokDesktopBridge"
    $tempDir = Join-Path $env:TEMP "GrokDesktopBridge"
    foreach ($pair in @(
            @{ Path = $local; Class = "token-store"; Reason = "TOKEN SCOPE under LocalAppData\GrokDesktopBridge (file contents are not printed)" },
            @{ Path = $program; Class = "state"; Reason = "Grok ProgramData state (not Claude DesktopBridge)" },
            @{ Path = $tempDir; Class = "temp"; Reason = "Grok temp logs" }
        )) {
        if ($pair.Path -and (Test-Path -LiteralPath $pair.Path)) {
            $rows += [pscustomobject]@{ Path = $pair.Path; Name = (Split-Path -Leaf $pair.Path); Class = $pair.Class; Action = "remove"; Reason = $pair.Reason }
        }
    }
    $task = $null
    try { $task = Get-ScheduledTask -TaskName "GrokDesktopBridgeWorker" -ErrorAction SilentlyContinue } catch { $task = $null }
    if ($task) {
        $rows += [pscustomobject]@{ Path = "GrokDesktopBridgeWorker"; Name = "GrokDesktopBridgeWorker"; Class = "scheduled-task"; Action = "remove"; Reason = "scheduled task GrokDesktopBridgeWorker only" }
    }
    if ($Destination -and (Test-Path -LiteralPath $Destination)) {
        if (-not (Test-PathUnder $Destination $PackageRoot)) {
            $rows += [pscustomobject]@{ Path = $Destination; Name = (Split-Path -Leaf $Destination); Class = "install-dir"; Action = "remove"; Reason = "existing canonical install directory will be replaced" }
        }
    }
    return $rows
}

function Invoke-FreshInstall {
    Start-GrokTranscript
    Write-Host "Grok Desktop Bridge fresh install"
    Write-Host ("Package: " + $PSScriptRoot)
    $package = (Resolve-Path -LiteralPath $PSScriptRoot).Path
    if (-not $InstallDir) { $InstallDir = Join-Path $env:USERPROFILE "grok-desktop-bridge" }
    Write-Host ("Install directory: " + $InstallDir)
    Write-Host "STEP: preflight Python wheels (no files removed yet)"
    $python = Get-LivePython
    $cloud = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cloud) {
        Write-Host ("cloudflared: " + $cloud.Source)
    } else {
        Write-Host "WARNING: cloudflared is not on PATH. Install can finish, but the light-switch ON will stop until cloudflared is installed from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    }

    if ($SkipCleanup) {
        Write-Host "STEP: skip cleanup. No old installs are listed or removed."
        $plan = New-Object System.Collections.Generic.List[object]
    } else {
    $plan = New-Object System.Collections.Generic.List[object]
    Write-Host "STEP: discovery (Desktop and Downloads known folders, plus explicit Grok AppData). Reparse points are not entered."
    foreach ($root in @(Get-DiscoveryRoots)) {
        Write-Host ("Search root: " + $root)
        if (Test-ReparsePoint $root) {
            Write-Host ("SKIP reparse search root: " + $root)
            continue
        }
        Add-WalkPlan -Plan $plan -Dir $root -Depth 1 -Protected @($package) -IncludeOther $IncludeOtherClientPath
    }
    foreach ($extra in @(Get-ExplicitTargets -Destination $InstallDir -PackageRoot $package)) {
        $dup = $false
        foreach ($row in $plan) {
            if ((ConvertTo-PathKey $row.Path) -eq (ConvertTo-PathKey $extra.Path)) { $dup = $true }
        }
        if (-not $dup) { $plan.Add($extra) | Out-Null }
    }
    Show-CleanupPlan $plan
    if ($DryRun) {
        Write-Host "Dry run only. Nothing was removed and nothing was installed."
        Exit-Grok 0
    }
    $removable = @($plan | Where-Object { $_.Action -eq "remove" })
    if ($removable.Count -gt 0) {
        if (-not $ConfirmPhrase) {
            if (Test-PlanNeedsOtherPhrase $plan) {
                Write-Host ("Type this phrase to remove the Grok list AND the selected other-client paths: " + $script:ConfirmOther)
            } else {
                Write-Host ("Type this phrase to remove the listed Grok targets: " + $script:ConfirmGrok)
            }
            $ConfirmPhrase = Read-Host "Confirmation"
        }
        if (-not (Test-ConfirmationPhrase $ConfirmPhrase $plan)) {
            Write-Host "Confirmation did not match. Nothing was removed and nothing was installed."
            Exit-Grok 2
        }
        foreach ($row in $removable) {
            Write-Host ("REMOVE: " + $row.Path)
            if ($row.Class -eq "scheduled-task") {
                if ($row.Name -ne "GrokDesktopBridgeWorker") { throw "refusing to unregister task $($row.Name)" }
                Unregister-ScheduledTask -TaskName "GrokDesktopBridgeWorker" -Confirm:$false
                continue
            }
            if (Test-ReparsePoint $row.Path) { throw ("refusing to delete reparse point " + $row.Path) }
            Remove-TreeNoReparse -Path $row.Path
        }
    } else {
        Write-Host "No removable targets."
    }
    }

    $same = (ConvertTo-PathKey $package) -eq (ConvertTo-PathKey $InstallDir)
    if ($same) {
        Write-Host "Package is already the install directory. Files stay; the venv is recreated."
    } else {
        if ((Test-Path -LiteralPath $InstallDir) -and -not $SkipCleanup) {
            if (Test-ReparsePoint $InstallDir) { throw "install directory is a reparse point; refusing to replace it" }
            Remove-TreeNoReparse -Path $InstallDir
        }
        if ((Test-Path -LiteralPath $InstallDir) -and $SkipCleanup -and (Test-ReparsePoint $InstallDir)) {
            throw "install directory is a reparse point; refusing to copy into it"
        }
        Write-Host ("STEP: copy package to " + $InstallDir)
        Copy-TreeNoReparse -Source $package -Destination $InstallDir
    }

    $venvPy = Join-Path (Join-Path (Join-Path $InstallDir ".venv") "Scripts") "python.exe"
    $venvParent = Join-Path $InstallDir ".venv"
    if (Test-Path -LiteralPath $venvParent) {
        if (Test-ReparsePoint $venvParent) { throw ".venv is a reparse point; refusing to replace it" }
        Remove-TreeNoReparse -Path $venvParent
    }
    Write-Host "STEP: create isolated venv"
    $script:InstallPython = $python
    $script:VenvParent = $venvParent
    Invoke-Native -Label "venv" -Command { & $script:InstallPython -m venv $script:VenvParent } | Out-Null
    if (-not (Test-Path -LiteralPath $venvPy)) { throw "venv python was not created at $venvPy" }
    $req = Join-Path $InstallDir "requirements.txt"
    $script:VenvPy = $venvPy
    $script:ReqPath = $req
    Invoke-Native -Label "pip upgrade" -Command { & $script:VenvPy -m pip install --disable-pip-version-check --only-binary=:all: --upgrade pip } | Out-Null
    Invoke-Native -Label "pip install" -Command { & $script:VenvPy -m pip install --disable-pip-version-check --only-binary=:all: -r $script:ReqPath } | Out-Null
    Write-Host "STEP: import dxcam, mss, PIL, numpy, win32api, comtypes"
    Invoke-Native -Label "import check" -Command { & $script:VenvPy -c "import dxcam, mss, PIL, numpy, win32api, comtypes" } | Out-Null

    $desktop = $null
    try { $desktop = Get-KnownFolderPath "Desktop" } catch {
        $desktop = [Environment]::GetFolderPath("Desktop")
    }
    if (-not $desktop) { throw "Desktop known folder was not found. Shortcut was not created." }
    $cmdPath = Join-Path $InstallDir "GrokBridge-LightSwitch.cmd"
    $shell = New-Object -ComObject WScript.Shell
    $lnkPath = Join-Path $desktop "Grok Desktop Bridge Light Switch.lnk"
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $cmdPath
    $lnk.WorkingDirectory = $InstallDir
    $lnk.WindowStyle = 1
    $lnk.Description = "Start or stop the Grok Desktop Bridge"
    $lnk.Save()
    Write-Host ("Desktop shortcut: " + $lnkPath)
    Write-Host ("Light switch: " + $cmdPath)
    Write-Host "Token files were not copied and were not printed."
    Write-Host "To create a bot token once, in a window you are watching (it is not written to this log), run:"
    Write-Host ("  " + $venvPy + " launcher.py --add-bot work")
    Write-Host "Create that token now in THIS window? Type YES to show it here and keep it out of the log. Press Enter to skip."
    $answer = Read-Host "Create token"
    if ($answer -eq "YES") {
        Stop-GrokTranscript
        & $venvPy (Join-Path $InstallDir "launcher.py") --add-bot work
        $tokenCode = $LASTEXITCODE
        Start-Transcript -LiteralPath $script:GrokLogPath -Append | Out-Null
        $script:TranscriptOn = $true
        Write-Host ("add-bot exit code " + $tokenCode + " (token value was not written to this log)")
        if ($tokenCode -ne 0) { throw "Command failed (add-bot) exit code $tokenCode" }
    }
    Write-Host "Install finished. Turn the bridge on with the desktop shortcut or:"
    Write-Host ("  " + $cmdPath)
    Exit-Grok 0
}

if ($SelfTest) {
    $code = 1
    try {
        $code = Invoke-GrokBridgeSelfTest
    } catch {
        Write-Host ("SELFTEST ERROR: " + $_.Exception.Message)
        Write-Host $_.ScriptStackTrace
        $code = 1
    }
    Write-Host ("FINAL EXIT CODE: " + $code)
    exit $code
}

try {
    Invoke-FreshInstall
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    Write-Host $_.ScriptStackTrace
    $code = 1
    if ($_.Exception.Message -match "exit code (\d+)") { $code = [int]$Matches[1] }
    Exit-Grok $code
}
