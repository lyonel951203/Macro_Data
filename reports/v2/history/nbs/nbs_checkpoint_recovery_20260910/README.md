# NBS 断点保存修复（2026-09-10）

## 故障与恢复依据

NBS 在 18:06 完成 2026 年采购经理指数窗口后，替换主断点文件时遇到 `PermissionError / WinError 5`。异常收尾阶段再次保存成功，正式断点保留了全部 148 个完成窗口及 318 条入库计数，未遗留旧锁或未提交临时断点，因此本次不需要覆盖或迁移生产断点。

具体哪个进程占用文件无法从错误日志确定。已复现 Windows 读句柄未允许删除共享时，原子替换会失败的行为，并验证释放句柄后重试可以成功。

## 修改

- 新增 `src/macro_pit/fileio.py`：独立临时文件、flush/fsync，再进行原子替换。
- 对 Windows 错误 5、32、33 最多尝试 8 次，等待从 50 毫秒逐步增加至 1 秒，总等待上限 3.55 秒。
- 重试耗尽保留旧正式文件和完整临时恢复文件；其他 I/O 错误立即抛出。
- NBS 主断点、入库回执、检索断点及 STATUS 文档都使用此写入函数。
- 退出时即使关闭客户端、导出或保存失败，也执行进程锁清理。
- 未修改解析与 PIT 规则、请求限速、原始数据或已完成窗口。

## 验证

- `pytest tests/test_atomic_fileio.py tests/test_nbs_search.py tests/test_pit_autorun_validation.py tests/test_http_safety.py -q`：**41 passed**。
- 测试覆盖暂时失败后的恢复、持续失败的有界退出、独立恢复文件保留、检索和主断点集成，以及真实 Windows 文件共享冲突。
- `checkpoint_verification.json`：148 个完成窗口与顺序一致；318 条入库回执在主库各匹配 1 条；52 份相应原稿的 SHA-256 一致；正式断点未改变。
- 剩余窗口为 `2026_1` 至 `2026_6`。另有 5 个重复分页窗口仍待后续缩小时间范围复查。
- 启动前重新运行离线原稿回放；校验与恢复后的实际抓取结果记录在 `resume.json`。

备份文件 `worker_before.py`、`search_before.py`、`state_before.json`、`preflight_before.json` 仅用于追溯。实时状态以 [多来源监控](../source_monitor/latest.md) 为准。