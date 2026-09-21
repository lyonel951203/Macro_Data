# Historical configuration

These source folders contain frozen manifests from completed discovery,
backfill, validation and probe work. They are retained so historical commands
and reports remain reproducible.

None of these files is referenced by the four active daily/weekly YAML files.
Supported production and offline configuration remains directly under
`config/`. Historical scripts that still use a manifest point to its new path
under this directory.
