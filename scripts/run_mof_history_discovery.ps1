$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\Macro_Data'
$env:PYTHONPATH = 'D:\Macro_Data\src'
py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb discover-index `
  --source MOF `
  --url-manifest config\mof_index_pages4_20.txt `
  --allow-network
