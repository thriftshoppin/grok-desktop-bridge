# Feature: shared guardian

One elevated worker per Windows session serves every MCP client (Grok / Local Computer Assistant primary, Claude desktop/Code for compatibility, others), like a primary/relay bridge: no repeated dialogs, one feed window, one input lock, one kill switch. See [../ARCHITECTURE.md](../ARCHITECTURE.md). Client approval is a one-time typed answer in the feed window, remembered in `%ProgramData%\DesktopBridge\state`. Tests: `tests/test_guardian.py`, `tests/test_primary.py`, `tests/test_ctlguard.py`, `selftest.py`, `tests/security-e2e.py`.
