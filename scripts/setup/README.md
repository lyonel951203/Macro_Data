# Setup scripts

These PowerShell scripts install the four Windows scheduled tasks or save the
DeepSeek credential used by them. They are operator-invoked and are not called
during a normal scheduled run.

Run them from the repository root, for example:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup\install_daily_web_update_task.ps1
```
