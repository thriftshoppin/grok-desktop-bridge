"""Parse the Windows scripts and run the PowerShell self-test when pwsh is available."""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = [
    "Install-GrokBridge.ps1",
    "GrokBridge-LightSwitch.ps1",
    "scripts/GrokBridgeLib.ps1",
    "scripts/GrokBridge-RunRemote.ps1",
    "scripts/GrokBridge-RunTunnel.ps1",
]
CMDS = [
    "Install-GrokBridge.cmd",
    "GrokBridge-LightSwitch.cmd",
]


def find_pwsh():
    for candidate in ("/tmp/pwsh/pwsh", shutil.which("pwsh") or "", shutil.which("powershell") or ""):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


PWSH = find_pwsh()


@unittest.skipUnless(PWSH, "PowerShell is not installed on this machine")
class Parser(unittest.TestCase):
    def test_scripts_parse(self):
        for rel in SCRIPTS:
            path = os.path.join(ROOT, rel)
            literal = path.replace("'", "''")
            command = (
                "$e=$null; $t=$null; "
                f"[void][System.Management.Automation.Language.Parser]::ParseFile('{literal}', [ref]$t, [ref]$e); "
                "if ($e -and @($e).Count) { $e | ForEach-Object { Write-Output $_.ToString() }; exit 1 }; exit 0"
            )
            proc = subprocess.run(
                [PWSH, "-NoProfile", "-Command", command],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, rel + "\n" + proc.stdout + proc.stderr)

    def test_selftest_cleanup_and_exit_codes(self):
        proc = subprocess.run(
            [PWSH, "-NoProfile", "-File", os.path.join(ROOT, "Install-GrokBridge.ps1"), "-SelfTest"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("SELFTEST ok", proc.stdout)
        self.assertIn("FINAL EXIT CODE: 0", proc.stdout)


class StaticContract(unittest.TestCase):
    def text(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
            return handle.read()

    def test_no_recursive_delete_and_reparse_guard_exists(self):
        blob = "\n".join(self.text(rel) for rel in SCRIPTS)
        self.assertNotIn("Remove-Item -Recurse", blob)
        self.assertNotIn("-Recurse", blob)
        self.assertIn("ReparsePoint", blob)
        self.assertIn("refusing to delete reparse point", blob)

    def test_cmds_stay_open_and_print_exit_codes(self):
        for rel in CMDS:
            text = self.text(rel)
            self.assertIn("pause", text)
            self.assertIn("FINAL EXIT CODE:", text)
            self.assertIn("ParseFile", text)
            self.assertNotIn("exit /b 0\r\n", text)

    def test_phrases_guids_and_secret_rules(self):
        lib = self.text("scripts/GrokBridgeLib.ps1")
        self.assertIn("REMOVE LISTED GROK INSTALLS", lib)
        self.assertIn("B4BFCC3A-DB2C-424C-B029-7FE99A87C641", lib)
        self.assertIn("374DE290-123F-4565-9164-39C4925E467B", lib)
        switch = self.text("GrokBridge-LightSwitch.ps1")
        install = self.text("Install-GrokBridge.ps1")
        for line in switch.splitlines():
            if "--add-bot" in line:
                self.assertIn("Write-Host", line, "light switch may mention --add-bot only as a manual command")
        self.assertNotIn("remote_bots.json", switch + install + lib)
        self.assertIn("--only-binary=:all:", install)
        self.assertIn("LASTEXITCODE", lib)
        self.assertIn("1223", lib)

    def test_light_switch_checks_identity_before_stop(self):
        switch = self.text("GrokBridge-LightSwitch.ps1")
        self.assertIn("Test-SafeToStop", switch)
        self.assertIn("Creation", switch)
        self.assertNotIn("taskkill", switch.lower())
        self.assertNotIn("Get-Process | Stop-Process", switch)


if __name__ == "__main__":
    unittest.main()
