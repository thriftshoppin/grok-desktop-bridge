# Shared helpers for Install-GrokBridge.ps1 and GrokBridge-LightSwitch.ps1.
# Windows PowerShell 5.1 compatible. Dot-source only; this file has no param block.
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $Global:PSNativeCommandUseErrorActionPreference = $false
}

$script:ConfirmGrok = "REMOVE LISTED GROK INSTALLS"
$script:ConfirmOther = "REMOVE LISTED GROK INSTALLS AND SELECTED OTHER CLIENT PATHS"
$script:KnownFolderGuids = @{
    Desktop   = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
    Downloads = "374DE290-123F-4565-9164-39C4925E467B"
}
$script:FolderRe = '(?i)^(grok-desktop-bridge|desktop-mcp-bridge)(-main)?([ ._-]*(\(\d+\)|\d+))?$'
$script:MaxWalkDepth = 6
$script:RemotePort = 8790

function Write-GrokStep {
    param([string]$Message)
    Write-Host $Message
}

function Get-PythonCommand {
    foreach ($name in @("python3", "python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Invoke-Native {
    param(
        [scriptblock]$Command,
        [string]$Label
    )
    Write-GrokStep ("STEP: " + $Label)
    & $Command
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    Write-GrokStep ("NATIVE EXIT " + $Label + ": " + $code)
    if ([int]$code -ne 0) {
        throw ("Command failed (" + $Label + ") exit code " + $code)
    }
    return [int]$code
}

function Test-ReparsePoint {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return $false }
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Remove-TreeNoReparse {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw ("refusing to delete reparse point " + $Path)
    }
    if (-not $item.PSIsContainer) {
        Remove-Item -LiteralPath $Path -Force
        return
    }
    foreach ($child in @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)) {
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-GrokStep ("SKIP reparse (not deleted, not entered): " + $child.FullName)
            continue
        }
        if ($child.PSIsContainer) {
            Remove-TreeNoReparse -Path $child.FullName
        } else {
            Remove-Item -LiteralPath $child.FullName -Force
        }
    }
    $left = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
    if ($left.Count -eq 0) {
        Remove-Item -LiteralPath $Path -Force
    } else {
        Write-GrokStep ("LEFT IN PLACE (reparse children remain): " + $Path)
    }
}

function Copy-TreeNoReparse {
    param([string]$Source, [string]$Destination)
    if (Test-ReparsePoint -Path $Source) {
        throw ("refusing to copy through reparse point " + $Source)
    }
    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Path $Destination | Out-Null
    }
    foreach ($child in @(Get-ChildItem -LiteralPath $Source -Force)) {
        if ($child.Name -in @(".venv", ".git", "__pycache__")) { continue }
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-GrokStep ("SKIP reparse (not copied, not entered): " + $child.FullName)
            continue
        }
        $target = Join-Path $Destination $child.Name
        if ($child.PSIsContainer) {
            Copy-TreeNoReparse -Source $child.FullName -Destination $target
        } else {
            Copy-Item -LiteralPath $child.FullName -Destination $target -Force
        }
    }
}

function Get-LeafName {
    param([string]$Path)
    if (-not $Path) { return "" }
    $normed = $Path.Replace("/", "\")
    $idx = $normed.LastIndexOf("\")
    if ($idx -lt 0) { return $normed.ToLowerInvariant() }
    return $normed.Substring($idx + 1).ToLowerInvariant()
}

function ConvertTo-PathKey {
    param([string]$Path)
    if (-not $Path) { return "" }
    return ($Path.Replace("/", "\").Trim().TrimEnd("\").ToLowerInvariant())
}

function Test-PathUnder {
    param([string]$Path, [string]$Root)
    $p = ConvertTo-PathKey $Path
    $r = ConvertTo-PathKey $Root
    if (-not $r -or -not $p) { return $false }
    return (($p -eq $r) -or $p.StartsWith($r + "\"))
}

function Test-FolderName {
    param([string]$Name)
    return [bool]($Name -match $script:FolderRe)
}

function Get-BrandMarkers {
    param([string]$BrandText)
    $text = ""
    if ($BrandText) { $text = $BrandText }
    $grok = ($text -match 'PRODUCT\s*=\s*[''"]GrokDesktopBridge[''"]') -or ($text -match 'SERVER_NAME\s*=\s*[''"]grok-desktop-bridge[''"]')
    $other = ($text -match 'SERVER_NAME\s*=\s*[''"]desktop-mcp-bridge[''"]')
    return @($grok, $other)
}

function Get-DirClass {
    param([string]$Name, [string]$BrandText)
    if (-not (Test-FolderName $Name)) { return "ignore" }
    $stemOther = $Name.ToLowerInvariant().StartsWith("desktop-mcp-bridge")
    $marks = Get-BrandMarkers $BrandText
    $grok = [bool]$marks[0]
    $other = [bool]$marks[1]
    if ($grok -and $other) { return "ambiguous" }
    if ($other -and -not $grok) { return "other-client" }
    if ($grok) { return "grok" }
    if ($stemOther) { return "other-client" }
    return "grok"
}

function Get-ScriptClass {
    param([string]$Name)
    switch ($Name.ToLowerInvariant()) {
        "apply-escfix.ps1" { return "grok-script" }
        "grokbridge-lightswitch.ps1" { return "grok-script" }
        "grokbridge-lightswitch.cmd" { return "grok-script" }
        "update-grokbridgeinplace.ps1" { return "grok-script" }
        default { return "ignore" }
    }
}

function Get-ShortcutClass {
    param([string]$Name, [string]$TargetPath)
    if ($Name.ToLowerInvariant() -ne "grok desktop bridge light switch.lnk") { return "ignore" }
    $target = ""
    if ($TargetPath) { $target = $TargetPath.Replace("/", "\").ToLowerInvariant() }
    if (($target.Contains("desktop-mcp-bridge")) -and (-not $target.Contains("grok-desktop-bridge"))) {
        return "ambiguous"
    }
    return "grok-shortcut"
}

function Read-ShortcutTarget {
    param([string]$Path)
    if (-not $Path) { return "" }
    if (-not $Path.ToLowerInvariant().EndsWith(".lnk")) { return "" }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($Path)
        return [string]$lnk.TargetPath
    } catch {
        return ""
    }
}

function Read-BrandText {
    param([string]$Dir)
    $brand = Join-Path (Join-Path $Dir "desktop_bridge") "brand.py"
    if (-not (Test-Path -LiteralPath $brand)) { return "" }
    return [IO.File]::ReadAllText($brand)
}

function Test-PlanNeedsOtherPhrase {
    param($Plan)
    foreach ($row in $Plan) {
        if (($row.Action -eq "remove") -and (($row.Class -eq "other-client") -or ($row.Class -eq "ambiguous"))) {
            return $true
        }
    }
    return $false
}

function Test-ConfirmationPhrase {
    param([string]$Phrase, $Plan)
    if (Test-PlanNeedsOtherPhrase $Plan) { return ($Phrase -eq $script:ConfirmOther) }
    $anyRemove = $false
    foreach ($row in $Plan) { if ($row.Action -eq "remove") { $anyRemove = $true } }
    if ($anyRemove) { return ($Phrase -eq $script:ConfirmGrok) }
    return $true
}

function Test-PythonSupported {
    param([int]$Major, [int]$Minor, [int]$Bits, [string]$Implementation)
    $impl = ""
    if ($Implementation) { $impl = $Implementation.Trim() }
    if ($impl.ToLowerInvariant() -ne "cpython") {
        return @{ Ok = $false; Reason = "Need CPython, found $impl. Install 64-bit CPython 3.14, 3.13, or 3.12 from python.org. dxcam and numpy ship CPython wheels only." }
    }
    if ($Bits -ne 64) {
        return @{ Ok = $false; Reason = "This interpreter is $Bits-bit. dxcam==0.3.0 publishes win_amd64 wheels only (no 32-bit wheel). Install 64-bit CPython 3.14, 3.13, or 3.12." }
    }
    if (($Major -lt 3) -or (($Major -eq 3) -and ($Minor -lt 12))) {
        return @{ Ok = $false; Reason = "Python $Major.$Minor is too old. numpy==2.5.4 requires Python >=3.12 and Pillow==13.0.0 requires >=3.11. Install 64-bit CPython 3.14, 3.13, or 3.12. The installer will not build from source." }
    }
    if (-not (($Major -eq 3) -and ($Minor -ge 12) -and ($Minor -le 14))) {
        return @{ Ok = $false; Reason = "Python $Major.$Minor has no usable wheel set. dxcam==0.3.0 has Windows wheels for CPython 3.10-3.14 only (no 3.15+), and numpy==2.5.4 requires >=3.12. Supported: 64-bit CPython 3.12, 3.13, and 3.14. pip --only-binary=:all: will not compile dxcam." }
    }
    return @{ Ok = $true; Reason = "64-bit CPython $Major.$Minor is supported (3.12, 3.13, 3.14) with win_amd64 wheels." }
}

function Get-RunAsFailureAction {
    param([int]$WinError)
    if ($WinError -eq 1223) { return "abort" }
    return "try-scheduled-task"
}

function Protect-LogText {
    param([string]$Text)
    if (-not $Text) { return "" }
    $text = [regex]::Replace($Text, '(?i)(\btoken\b\s*[:=]\s*)(\S+)', '$1[redacted]')
    $text = [regex]::Replace($text, '(?i)(bearer\s+)([A-Za-z0-9._~+/-]{8,})', '$1[redacted]')
    return $text
}

function Test-OwnedGrokProcess {
    param([string]$CommandLine, [string]$Executable, [string]$BridgeRoot, [int]$Port)
    $cl = ""
    if ($CommandLine) { $cl = $CommandLine }
    $exe = ""
    if ($Executable) { $exe = $Executable }
    $clKey = $cl.Replace("/", "\").ToLowerInvariant()
    $exeKey = ConvertTo-PathKey $exe
    $rootKey = ConvertTo-PathKey $BridgeRoot
    $base = Get-LeafName $exeKey
    $under = $false
    if ($rootKey) {
        if ($clKey.Contains($rootKey) -or ($exeKey -eq $rootKey) -or $exeKey.StartsWith($rootKey + "\")) { $under = $true }
    }
    if (($base -eq "cloudflared.exe") -or ($base -eq "cloudflared")) {
        return (($cl.Contains("127.0.0.1:" + $Port)) -and ($clKey.Contains("--url")) -and ($clKey.Contains("tunnel")))
    }
    if ($clKey.Contains("grokbridge-runremote.ps1") -or $clKey.Contains("grokbridge-runtunnel.ps1")) {
        return ($under -or $clKey.Contains($rootKey))
    }
    if (-not $under) { return $false }
    if (($base -ne "python.exe") -and ($base -ne "pythonw.exe") -and ($base -ne "python") -and ($base -ne "py.exe")) {
        return $false
    }
    $worker = ($clKey.Contains("desktop_bridge.worker") -and $clKey.Contains("--guardian") -and ($clKey -match '--instance(\s+|=)grok\b'))
    $launcher = ($clKey.Contains("launcher.py") -and $clKey.Contains("--remote"))
    return ($worker -or $launcher)
}

function Test-SafeToStop {
    param($Recorded, $Current)
    if (-not $Recorded) { return @{ Ok = $false; Why = "nothing-recorded" } }
    if (-not $Current) { return @{ Ok = $false; Why = "already-exited" } }
    if ([int]$Recorded.Pid -ne [int]$Current.Pid) { return @{ Ok = $false; Why = "pid-mismatch" } }
    if ([string]$Recorded.Creation -ne [string]$Current.Creation) { return @{ Ok = $false; Why = "pid-reused" } }
    if ((ConvertTo-PathKey $Recorded.Image) -ne (ConvertTo-PathKey $Current.Image)) { return @{ Ok = $false; Why = "image-changed" } }
    return @{ Ok = $true; Why = "ok" }
}

function Get-StartupClass {
    param($LauncherExit, [string]$LogText, $HttpStatus, [bool]$GuardianOwned, [string]$TunnelUrl, [bool]$TimedOut)
    $text = ""
    if ($LogText) { $text = $LogText.ToLowerInvariant() }
    $uac = ($text.Contains("error 1223") -or $text.Contains("uac was cancelled") -or ($LauncherExit -eq 1223))
    if ($uac) {
        return @{ State = "uac_cancelled"; Rollback = $true; Reason = "UAC was cancelled (error 1223). Partial startup is rolled back. The scheduled task is not used after Cancel." }
    }
    $httpOk = ($HttpStatus -eq 401)
    $url = ""
    if ($TunnelUrl) { $url = $TunnelUrl.Trim() }
    $running = ($null -eq $LauncherExit)
    if ($httpOk -and $GuardianOwned -and $url -and $running) {
        return @{ State = "ready"; Rollback = $false; Reason = "guardian, loopback HTTP (401 without a token), and tunnel URL are up" }
    }
    if ($null -ne $LauncherExit) {
        return @{ State = "failed"; Rollback = $true; Reason = ("launcher exited " + $LauncherExit + " before guardian, HTTP, and tunnel were all ready") }
    }
    if ($TimedOut) {
        return @{ State = "failed"; Rollback = $true; Reason = "timed out waiting for the guardian process, HTTP 401 on 127.0.0.1, and a trycloudflare URL" }
    }
    return @{ State = "wait"; Rollback = $false; Reason = "still starting" }
}

function Get-TunnelUrlFromText {
    param([string]$Text)
    if (-not $Text) { return "" }
    $m = [regex]::Match($Text, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { return $m.Value }
    return ""
}

function Read-SharedText {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $fs = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $sr = New-Object System.IO.StreamReader($fs)
        return $sr.ReadToEnd()
    } finally {
        $fs.Close()
    }
}

function Add-PlanRow {
    param($Plan, [string]$Path, [string]$Name, [string]$Class, [string]$Action, [string]$Reason)
    $Plan.Add([pscustomobject]@{
        Path = $Path; Name = $Name; Class = $Class; Action = $Action; Reason = $Reason
    }) | Out-Null
}

function Test-CoveredByRemovedParent {
    param($Plan, [string]$Path)
    foreach ($row in $Plan) {
        if (($row.Action -eq "remove") -and (Test-PathUnder $Path $row.Path) -and ((ConvertTo-PathKey $Path) -ne (ConvertTo-PathKey $row.Path))) {
            return $true
        }
    }
    return $false
}

function Get-PlanAction {
    param([string]$Class, [string]$Path, [string[]]$IncludeOther)
    $removable = @("grok", "grok-script", "grok-shortcut", "token-store", "state", "temp", "scheduled-task", "install-dir")
    if ($removable -contains $Class) { return "remove" }
    if (($Class -eq "other-client") -or ($Class -eq "ambiguous")) {
        $key = ConvertTo-PathKey $Path
        foreach ($extra in @($IncludeOther)) {
            if ((ConvertTo-PathKey $extra) -eq $key) { return "remove" }
        }
    }
    return "skip"
}

function Add-WalkPlan {
    param($Plan, [string]$Dir, [int]$Depth, [string[]]$Protected, [string[]]$IncludeOther)
    if ($Depth -gt $script:MaxWalkDepth) { return }
    foreach ($item in @(Get-ChildItem -LiteralPath $Dir -Force -ErrorAction SilentlyContinue)) {
        $path = $item.FullName
        $name = $item.Name
        $isReparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
        $underProtected = $false
        foreach ($root in @($Protected)) {
            if ($root -and (Test-PathUnder $path $root)) { $underProtected = $true }
        }
        if ($underProtected) {
            $scriptClass = Get-ScriptClass $name
            if ((Test-FolderName $name) -or ($scriptClass -ne "ignore")) {
                Add-PlanRow $Plan $path $name "protected" "skip" "inside the installer package that is running"
            }
            continue
        }
        if (Test-CoveredByRemovedParent $Plan $path) { continue }
        if ($isReparse) {
            $scriptClass = Get-ScriptClass $name
            if ((Test-FolderName $name) -or ($scriptClass -ne "ignore")) {
                Add-PlanRow $Plan $path $name "skip-reparse" "skip" "reparse point (junction/symlink); not entered and not deleted"
            }
            continue
        }
        if ($item.PSIsContainer) {
            $cls = Get-DirClass -Name $name -BrandText (Read-BrandText $path)
            if ($cls -ne "ignore") {
                $action = Get-PlanAction -Class $cls -Path $path -IncludeOther $IncludeOther
                $reason = $cls
                if ($cls -eq "other-client") { $reason = "folder looks like another client's install (Claude/Codex desktop-mcp-bridge); not removed unless selected" }
                if ($cls -eq "ambiguous") { $reason = "folder contains both Grok and another client; not removed unless selected" }
                Add-PlanRow $Plan $path $name $cls $action $reason
                if ($action -eq "remove") { continue }
            }
            Add-WalkPlan -Plan $Plan -Dir $path -Depth ($Depth + 1) -Protected $Protected -IncludeOther $IncludeOther
        } else {
            $cls = Get-ScriptClass $name
            $target = ""
            if ($cls -eq "ignore") {
                $target = Read-ShortcutTarget $path
                $cls = Get-ShortcutClass -Name $name -TargetPath $target
            }
            if ($cls -eq "ignore") { continue }
            $action = Get-PlanAction -Class $cls -Path $path -IncludeOther $IncludeOther
            Add-PlanRow $Plan $path $name $cls $action $cls
        }
    }
}

function Get-KnownFolderPath {
    param([string]$Which)
    if (-not ("KnownFolderNative" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class KnownFolderNative {
  [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
  public static extern int SHGetKnownFolderPath(
    [MarshalAs(UnmanagedType.LPStruct)] Guid rfid,
    uint dwFlags,
    IntPtr hToken,
    out IntPtr ppszPath);
}
"@
    }
    $guidText = [string]$script:KnownFolderGuids[$Which]
    if (-not $guidText) { throw "unknown known folder $Which" }
    $guid = [Guid]$guidText
    $ptr = [IntPtr]::Zero
    $hr = [KnownFolderNative]::SHGetKnownFolderPath($guid, [uint32]0, [IntPtr]::Zero, [ref]$ptr)
    if ($hr -ne 0) { throw "SHGetKnownFolderPath $Which failed hr=$hr" }
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringUni($ptr)
    } finally {
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::FreeCoTaskMem($ptr) }
    }
}

function Get-DiscoveryRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($which in @("Desktop", "Downloads")) {
        $path = $null
        try { $path = Get-KnownFolderPath $which } catch {
            Write-GrokStep ("Known folder " + $which + " unavailable: " + $_.Exception.Message)
        }
        if ($path) { $roots.Add($path) }
    }
    $desktopFallback = [Environment]::GetFolderPath("Desktop")
    $candidates = @($desktopFallback, (Join-Path $env:USERPROFILE "Desktop"), (Join-Path $env:USERPROFILE "Downloads"))
    foreach ($extra in $candidates) {
        if (-not $extra) { continue }
        if (-not (Test-Path -LiteralPath $extra)) { continue }
        if (Test-ReparsePoint $extra) {
            Write-GrokStep ("SKIP reparse discovery root (not entered): " + $extra)
            continue
        }
        $already = $false
        foreach ($have in $roots) {
            if ((ConvertTo-PathKey $have) -eq (ConvertTo-PathKey $extra)) { $already = $true }
        }
        if (-not $already) { $roots.Add($extra) }
    }
    return $roots
}

function Show-CleanupPlan {
    param($Plan)
    Write-GrokStep "---- targets ----"
    if ($null -eq $Plan -or $Plan.Count -eq 0) {
        Write-GrokStep "(no removable targets)"
        return
    }
    foreach ($row in $Plan) {
        $tag = $row.Action.ToUpperInvariant()
        Write-GrokStep ("[" + $tag + "] [" + $row.Class + "] " + $row.Path)
        Write-GrokStep ("    " + $row.Reason)
    }
    Write-GrokStep "Token files are not printed. Other clients (Claude/Codex), unrelated Python, node, and cloudflared are not in the remove list unless a path was explicitly selected."
}

function Assert-SelfTest {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ("SELFTEST FAIL: " + $Message) }
}

function Invoke-GrokBridgeSelfTest {
    Write-GrokStep "SELFTEST start"
    Assert-SelfTest (Test-FolderName "grok-desktop-bridge-main (1)") "numbered grok name"
    Assert-SelfTest (Test-FolderName "desktop-mcp-bridge-main") "desktop-mcp-bridge-main"
    Assert-SelfTest (-not (Test-FolderName "grok-desktop-bridge-backup")) "backup name must not match"
    Assert-SelfTest ((Get-DirClass "desktop-mcp-bridge" "") -eq "other-client") "unnamed desktop-mcp is other-client"
    Assert-SelfTest ((Get-DirClass "grok-desktop-bridge" 'PRODUCT = "GrokDesktopBridge"') -eq "grok") "grok product"
    $both = 'PRODUCT = "GrokDesktopBridge"' + "`n" + 'SERVER_NAME = "desktop-mcp-bridge"'
    Assert-SelfTest ((Get-DirClass "grok-desktop-bridge" $both) -eq "ambiguous") "both products ambiguous"
    Assert-SelfTest ((Get-ScriptClass "Apply-EscFix.ps1") -eq "grok-script") "Apply-EscFix"
    $pyOk = Test-PythonSupported -Major 3 -Minor 14 -Bits 64 -Implementation "CPython"
    Assert-SelfTest $pyOk.Ok "3.14 x64"
    $pyOld = Test-PythonSupported -Major 3 -Minor 11 -Bits 64 -Implementation "CPython"
    Assert-SelfTest (-not $pyOld.Ok) "3.11 rejected"
    $pyNew = Test-PythonSupported -Major 3 -Minor 15 -Bits 64 -Implementation "CPython"
    Assert-SelfTest (-not $pyNew.Ok) "3.15 rejected"
    $py32 = Test-PythonSupported -Major 3 -Minor 14 -Bits 32 -Implementation "CPython"
    Assert-SelfTest (-not $py32.Ok) "32-bit rejected"
    Assert-SelfTest ((Get-RunAsFailureAction 1223) -eq "abort") "UAC cancel aborts"
    Assert-SelfTest ((Get-RunAsFailureAction 5) -eq "try-scheduled-task") "other runas errors may try the task"
    $redacted = Protect-LogText "token: super-secret-token-value`nAuthorization: Bearer abcdefghijklmnop`nhttps://lucky-river.trycloudflare.com"
    Assert-SelfTest ($redacted.Contains("https://lucky-river.trycloudflare.com")) "tunnel url kept"
    Assert-SelfTest (-not $redacted.Contains("super-secret-token-value")) "token redacted"
    Assert-SelfTest (-not $redacted.Contains("abcdefghijklmnop")) "bearer redacted"
    $root = "C:\Users\SysAdmin\grok-desktop-bridge"
    $py = $root + "\.venv\Scripts\python.exe"
    Assert-SelfTest (Test-OwnedGrokProcess -CommandLine ($py + " launcher.py --remote --port 8790") -Executable $py -BridgeRoot $root -Port 8790) "owned launcher"
    Assert-SelfTest (Test-OwnedGrokProcess -CommandLine ($py + " -m desktop_bridge.worker --guardian --instance grok") -Executable $py -BridgeRoot $root -Port 8790) "owned guardian"
    Assert-SelfTest (-not (Test-OwnedGrokProcess -CommandLine ($py + " -m desktop_bridge.worker --guardian --instance main") -Executable $py -BridgeRoot $root -Port 8790)) "other instance"
    Assert-SelfTest (Test-OwnedGrokProcess -CommandLine "cloudflared tunnel --url http://127.0.0.1:8790" -Executable "C:\Tools\cloudflared.exe" -BridgeRoot $root -Port 8790) "our tunnel"
    Assert-SelfTest (-not (Test-OwnedGrokProcess -CommandLine "cloudflared tunnel --url http://127.0.0.1:8080" -Executable "C:\Tools\cloudflared.exe" -BridgeRoot $root -Port 8790)) "other tunnel"
    Assert-SelfTest (-not (Test-OwnedGrokProcess -CommandLine "node server.js" -Executable ($root + "\node.exe") -BridgeRoot $root -Port 8790)) "node not owned"
    $safe = Test-SafeToStop @{ Pid = 42; Creation = "100"; Image = "C:\py.exe" } @{ Pid = 42; Creation = "999"; Image = "C:\py.exe" }
    Assert-SelfTest ((-not $safe.Ok) -and ($safe.Why -eq "pid-reused")) "pid reuse"
    $same = Test-SafeToStop @{ Pid = 42; Creation = "100"; Image = "C:\py.exe" } @{ Pid = 42; Creation = "100"; Image = "C:\py.exe" }
    Assert-SelfTest $same.Ok "same process"
    $ready = Get-StartupClass -LauncherExit $null -LogText "up" -HttpStatus 401 -GuardianOwned $true -TunnelUrl "https://lucky-river.trycloudflare.com" -TimedOut $false
    Assert-SelfTest (($ready.State -eq "ready") -and (-not $ready.Rollback)) "ready"
    $uac = Get-StartupClass -LauncherExit 1 -LogText "UAC was cancelled (error 1223)" -HttpStatus $null -GuardianOwned $false -TunnelUrl "" -TimedOut $false
    Assert-SelfTest (($uac.State -eq "uac_cancelled") -and $uac.Rollback) "uac rollback"
    $wait = Get-StartupClass -LauncherExit $null -LogText "" -HttpStatus $null -GuardianOwned $false -TunnelUrl "" -TimedOut $false
    Assert-SelfTest ($wait.State -eq "wait") "spawn is not ready"
    $failed = Get-StartupClass -LauncherExit $null -LogText "" -HttpStatus 401 -GuardianOwned $true -TunnelUrl "" -TimedOut $true
    Assert-SelfTest (($failed.State -eq "failed") -and $failed.Rollback) "timeout rollback"

    $temp = Join-Path ([IO.Path]::GetTempPath()) ("grok-selftest-" + [guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Path $temp | Out-Null
    try {
        $downloads = Join-Path $temp "Downloads"
        New-Item -ItemType Directory -Path $downloads | Out-Null
        $nestedParent = Join-Path $downloads "grok-desktop-bridge-main"
        $nestedChild = Join-Path $nestedParent "grok-desktop-bridge-main"
        New-Item -ItemType Directory -Path $nestedChild | Out-Null
        $brandDir = Join-Path $nestedParent "desktop_bridge"
        New-Item -ItemType Directory -Path $brandDir | Out-Null
        [IO.File]::WriteAllText((Join-Path $brandDir "brand.py"), "PRODUCT = `"GrokDesktopBridge`"`nSERVER_NAME = `"grok-desktop-bridge`"`n")
        [IO.File]::WriteAllText((Join-Path $nestedChild "launcher.py"), "# launcher`n")
        $numbered = Join-Path $downloads "grok-desktop-bridge-main (1)"
        New-Item -ItemType Directory -Path $numbered | Out-Null
        [IO.File]::WriteAllText((Join-Path $downloads "Apply-EscFix.ps1"), "# draft`n")
        $other = Join-Path $downloads "desktop-mcp-bridge"
        New-Item -ItemType Directory -Path $other | Out-Null
        $otherBrand = Join-Path $other "desktop_bridge"
        New-Item -ItemType Directory -Path $otherBrand | Out-Null
        [IO.File]::WriteAllText((Join-Path $otherBrand "brand.py"), "SERVER_NAME = `"desktop-mcp-bridge`"`n")
        [IO.File]::WriteAllText((Join-Path $other "keep-claude.txt"), "keep")
        $secret = Join-Path $temp "secret-target"
        New-Item -ItemType Directory -Path $secret | Out-Null
        [IO.File]::WriteAllText((Join-Path $secret "keep.txt"), "keep-me")
        $link = Join-Path $downloads "grok-desktop-bridge"
        New-Item -ItemType SymbolicLink -Path $link -Target $secret | Out-Null
        $package = Join-Path $temp "package"
        $packageCopy = Join-Path $package "grok-desktop-bridge-main"
        New-Item -ItemType Directory -Path $packageCopy | Out-Null
        [IO.File]::WriteAllText((Join-Path $package "Install-GrokBridge.ps1"), "# running`n")
        $insideReparseParent = Join-Path $downloads "grok-desktop-bridge-main-9"
        New-Item -ItemType Directory -Path $insideReparseParent | Out-Null
        $brand2 = Join-Path $insideReparseParent "desktop_bridge"
        New-Item -ItemType Directory -Path $brand2 | Out-Null
        [IO.File]::WriteAllText((Join-Path $brand2 "brand.py"), "PRODUCT = `"GrokDesktopBridge`"`n")
        [IO.File]::WriteAllText((Join-Path $insideReparseParent "note.txt"), "note")
        $innerSecret = Join-Path $temp "inner-secret"
        New-Item -ItemType Directory -Path $innerSecret | Out-Null
        [IO.File]::WriteAllText((Join-Path $innerSecret "keep.txt"), "inner")
        New-Item -ItemType SymbolicLink -Path (Join-Path $insideReparseParent "jump") -Target $innerSecret | Out-Null

        $deep = $downloads
        for ($i = 1; $i -le 7; $i++) {
            $deep = Join-Path $deep ("level" + $i)
            New-Item -ItemType Directory -Path $deep | Out-Null
        }
        $tooDeep = Join-Path $deep "grok-desktop-bridge"
        New-Item -ItemType Directory -Path $tooDeep | Out-Null

        $plan = New-Object System.Collections.Generic.List[object]
        Add-WalkPlan -Plan $plan -Dir $downloads -Depth 1 -Protected @($package) -IncludeOther @()
        $removePaths = @()
        foreach ($row in $plan) { if ($row.Action -eq "remove") { $removePaths += (ConvertTo-PathKey $row.Path) } }
        Assert-SelfTest ($removePaths -contains (ConvertTo-PathKey $nestedParent)) "nested parent removed"
        Assert-SelfTest (-not ($removePaths -contains (ConvertTo-PathKey $nestedChild))) "child not listed separately"
        Assert-SelfTest ($removePaths -contains (ConvertTo-PathKey $numbered)) "numbered copy"
        Assert-SelfTest ($removePaths -contains (ConvertTo-PathKey (Join-Path $downloads "Apply-EscFix.ps1"))) "draft script"
        Assert-SelfTest (-not ($removePaths -contains (ConvertTo-PathKey $other))) "other client not removed"
        Assert-SelfTest (-not ($removePaths -contains (ConvertTo-PathKey $link))) "reparse root not removed"
        Assert-SelfTest (-not ($removePaths -contains (ConvertTo-PathKey $tooDeep))) "depth limit"
        Assert-SelfTest (-not (Test-ConfirmationPhrase "yes" $plan)) "bad phrase"
        Assert-SelfTest (Test-ConfirmationPhrase $script:ConfirmGrok $plan) "grok phrase"

        foreach ($row in $plan) {
            if ($row.Action -eq "remove") { Remove-TreeNoReparse -Path $row.Path }
        }
        Assert-SelfTest (-not (Test-Path -LiteralPath $nestedParent)) "nested parent deleted"
        Assert-SelfTest (-not (Test-Path -LiteralPath $numbered)) "numbered deleted"
        Assert-SelfTest (Test-Path -LiteralPath (Join-Path $other "keep-claude.txt")) "claude file kept"
        Assert-SelfTest (Test-Path -LiteralPath (Join-Path $secret "keep.txt")) "symlink target kept"
        Assert-SelfTest (Test-Path -LiteralPath $link) "symlink itself kept"
        Assert-SelfTest (Test-Path -LiteralPath (Join-Path $innerSecret "keep.txt")) "inner symlink target kept"
        Assert-SelfTest (Test-Path -LiteralPath (Join-Path $insideReparseParent "jump")) "inner symlink kept"
        Assert-SelfTest (Test-Path -LiteralPath $tooDeep) "deep copy kept"
        Assert-SelfTest (Test-Path -LiteralPath (Join-Path $package "Install-GrokBridge.ps1")) "package kept"
    } finally {
        try {
            if (Test-Path -LiteralPath $temp) {
                foreach ($item in @(Get-ChildItem -LiteralPath $temp -Force -ErrorAction SilentlyContinue)) {
                    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        try { [System.IO.Directory]::Delete($item.FullName) } catch { }
                    }
                }
                foreach ($item in @(Get-ChildItem -LiteralPath $temp -Force -ErrorAction SilentlyContinue)) {
                    if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                        try { Remove-TreeNoReparse -Path $item.FullName } catch { }
                    }
                }
                foreach ($item in @(Get-ChildItem -LiteralPath $temp -Force -ErrorAction SilentlyContinue)) {
                    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        try { [System.IO.Directory]::Delete($item.FullName) } catch { }
                    }
                }
                $left = @(Get-ChildItem -LiteralPath $temp -Force -ErrorAction SilentlyContinue)
                if ($left.Count -eq 0) {
                    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
                }
            }
        } catch { }
    }

    $pyCmd = Get-PythonCommand
    Assert-SelfTest ([bool]$pyCmd) "python is available for exit-code check"
    & $pyCmd -c "import sys; sys.exit(7)"
    Assert-SelfTest ($LASTEXITCODE -eq 7) ("LASTEXITCODE expected 7, got " + $LASTEXITCODE)
    $script:SelfTestPython = $pyCmd
    $threw = $false
    $caught = ""
    try {
        Invoke-Native -Label "pyfail" -Command { & $script:SelfTestPython -c "import sys; sys.exit(9)" } | Out-Null
    } catch {
        $threw = $true
        $caught = $_.Exception.Message
    }
    Assert-SelfTest $threw "Invoke-Native must stop on native failure"
    Assert-SelfTest ($caught -match "exit code 9") ("message should carry exit code 9: " + $caught)
    Write-GrokStep "SELFTEST ok"
    return 0
}
