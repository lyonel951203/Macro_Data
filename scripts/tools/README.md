# Operator tools

These scripts generate inventories, estimate availability, ingest reviewed
Wind files, inspect registered series, run DeepSeek audits, and send audit
mail. They are not part of the unattended network execution path.

Batch-specific manual contract checks and export spot checks were removed on
2026-09-21. Use the maintained pytest contracts for verification.

Run them from the repository root so relative database, configuration and
report paths resolve consistently.
