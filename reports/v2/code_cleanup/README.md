# 废弃代码清理

执行日期：2026-09-16。

本次只清理活动代码树，未删除data、数据库、原稿、日志或既有审计报告。

- 从scripts移除：285个一次性历史、核查、修复或迁移脚本
- 移除旧根目录入口：monitor_progress.cmd
- 移除废弃脚本专属测试文件：10个
- 从混合测试文件移除废弃任务专属函数：1个
- 当前保留维护脚本：27个
- 删除文件中Git已跟踪：54个
- 删除文件中仅本地存在：242个
- 删除文件代码体积：836596字节

删除前已生成ZIP，并通过成员集合及CRC校验：

    data/backups/code_cleanup/deprecated_code_20260916.zip

当前ZIP SHA-256：

    027b436b19607e95d290a3d6077e1cbfc3b88c716b6b3f198a5eee2289c64f2d

逐文件路径、大小、原修改时间和SHA-256见removed_code_manifest.csv。
被部分修改的test_atomic_fileio.py清理前完整版本也保存在ZIP中。

保留原则：当前每日更新和计划任务入口、当前Wind导入与PIT导出工具、
发布滞后校准及质量审计工具，以及仍用于本地原稿解析并由测试覆盖的解析器。
MacroPIT-NBS-History-Daily仍引用的run_nbs_history_once.ps1明确保留。

清理后验证：

- 活动测试集：233项全部通过
- macro_pit CLI帮助：通过
- 中国每日更新配置干运行：DRY_RUN
- 全球每日更新配置干运行：DRY_RUN
