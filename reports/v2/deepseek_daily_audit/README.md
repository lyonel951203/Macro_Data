# DeepSeek daily semantic audit

The 22:00 China update and 00:00 global update run this audit after deterministic
ingestion. It reviews only records written during that run plus reported source
errors. When neither exists, it makes no API request.

The model checks indicator identity, period alignment, transformation basis,
unit and percent scaling, revision consistency, and PIT timing. It receives
bounded text excerpts from public source archives. It cannot write to the
database. `REVIEW` and `REJECT` decisions are evidence for parser or human
review; they do not silently alter stored values.

The configured model is `deepseek-flash`, currently served by
DeepSeek-V4.1-Flash. To use V4 Pro instead, change `model` to
`deepseek-v4-pro` in both daily YAML files.

Reports are written to:

- `reports/v2/deepseek_daily_audit/china/latest.md`
- `reports/v2/deepseek_daily_audit/global/latest.md`
- each directory's `runs/<run_id>.json`

## Credential setup

Do not put the API key in YAML, command arguments, logs, or source control. The
runner looks for `DEEPSEEK_API_KEY` first. For unattended Windows Task Scheduler
runs it also reads this private file by default:

`%USERPROFILE%\.macro_pit\deepseek_api_key.txt`

The file must contain only the API key. Limit its Windows file permissions to
the task's user account. A missing key produces `SKIPPED_NO_KEY`; it does not
make source ingestion fail.

The interactive helper hides keyboard input, writes that file, and removes
inherited ACL entries:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\set_deepseek_api_key.ps1
```

## Manual audit or connectivity test

After configuring the credential, rerun the audit for the latest China report
without downloading source data again:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts\run_deepseek_daily_audit.py
```

For the global report:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts\run_deepseek_daily_audit.py `
  --config config\daily_global_update.yml
```

The client sends credentials only to `https://api.deepseek.com`. API errors and
malformed JSON are retried once and then written as `API_ERROR`; completed
deterministic ingestion remains intact.
