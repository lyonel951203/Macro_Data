# Windows 计划任务盘点（2026-09-17）

> 2026-09-21更新：`MacroPIT-MOF-History-Daily` 与
> `MacroPIT-NBS-History-Daily` 当前均已不存在；对应一次性脚本也已清理。
> 下文保留为2026-09-17时点的审计快照，当前生产任务只有四个每日/每周任务。

本报告只做读取和分类，没有删除、禁用或修改任何计划任务。原始清单见 `scheduled_tasks_inventory.json`，包含机器上的 216 个任务及其动作、触发器、最近结果和下次运行时间。

## 结论

- 与 Macro_Data 相关的任务共 6 个：4 个日常/修订任务属于当前方案，2 个是已经完成的历史回填任务。
- 当前方案的每日任务是：中国源 22:00、全球源 00:00；每周修订是周日 02:00 和 04:00。
- `MacroPIT-MOF-History-Daily` 和 `MacroPIT-NBS-History-Daily` 每天 10:00 运行，但两者状态文件都已是 `COMPLETE`、`pending=0`。它们现在每天只重复确认“已完成”，可以作为待停用的旧任务。
- NBS 历史状态中仍记有 49 个 `parse_error`，但当前历史任务不会再重试这些项目；若要修复，应单独建立解析失败修复流程，而不是继续保留这个每天空跑的任务。
- 任务计划程序显示的两个 `9009` 是 2026-09-17 08:27 的旧启动失败。启动脚本在 10:08 修复，随后绝对 Python 路径自检返回 0；正式计划仍要等 22:00 和次日 00:00 才能验证新的计划运行结果。

## Macro_Data 的 6 个任务

| 任务 | 频率 | 用途 | 最近结果 | 下次运行 | 判断 |
|---|---:|---|---:|---|---|
| `Macro_Data_Daily_Web_Update` | 每日 22:00 | 中国官方源及备用源轻量更新 | `9009`（修复前旧结果） | 2026-09-17 22:00 | 当前任务，保留 |
| `Macro_Data_Daily_Global_Update` | 每日 00:00 | OECD、RTDSM、ChinaBond、IMF 轻量更新 | `9009`（修复前旧结果） | 2026-09-18 00:00 | 当前任务，保留 |
| `Macro_Data_Weekly_Web_Revision` | 周日 02:00 | 中国源最近页面、OECD 中国修订及 PBOC 周探测 | 尚未首次运行（`0x41303`） | 2026-09-20 02:00 | 当前任务，保留 |
| `Macro_Data_Weekly_Global_Revision` | 周日 04:00 | OECD、RTDSM 历史修订核查 | 尚未首次运行（`0x41303`） | 2026-09-20 04:00 | 当前任务，保留 |
| `MacroPIT-MOF-History-Daily` | 每日 10:00 | 2005 年以来 MOF 历史回填 | 0 | 2026-09-18 10:00 | 已完成，待停用 |
| `MacroPIT-NBS-History-Daily` | 每日 10:00 | 2005 年以来 NBS 历史回填 | 0 | 2026-09-18 10:00 | 已完成，待停用 |

历史回填状态：

| 来源 | 队列 | 成功 | 解析失败 | 待处理 | 状态 |
|---|---:|---:|---:|---:|---|
| MOF | 195 | 195 | 0 | 0 | `COMPLETE` |
| NBS | 298 | 249 | 49 | 0 | `COMPLETE` |

## 为什么任务计划程序里看起来很多

机器上共有 216 个任务，其中 188 个位于 `\Microsoft\...`，主要由 Windows、Office、Edge 和系统组件安装。根目录及厂商目录共有 28 个任务。按“每天运行或每 24 小时重复”的规则筛出 40 个，构成如下：

| 类别 | 数量 | 常见任务 | 用途/判断 |
|---|---:|---|---|
| Macro_Data | 4 | Daily Web、Daily Global、MOF/NBS History | 2 个当前更新，2 个已完成旧回填 |
| NVIDIA | 6 | DriverUpdateCheck、NvTmRep 1—4、NvNodeLauncher | 驱动更新和崩溃报告；与项目无关 |
| MSI | 1 | `OneDC_Updater` | MSI Dragon Center 更新器；与项目无关 |
| OneDrive | 2 | Reporting、Standalone Update | OneDrive 维护；与项目无关 |
| Edge | 2 | PlatformExperiencesHelper Daily/Metrics | Edge 平台体验及指标维护 |
| Office | 4 | ClickToRun、Feature Updates、Startup Maintenance | Office 更新和维护 |
| Windows | 20 | 更新扫描、数据完整性、设备信息、语言、打印、安全等 | Windows 内置维护；部分任务用 COM Handler，所以“操作”栏可能看起来为空 |
| SoftLanding | 1 | CreativeManagementTask | Windows 推荐内容/体验管理；与项目无关 |

## 根目录中容易看不懂的任务

| 名称/前缀 | 来源 | 说明 |
|---|---|---|
| `iGoAudioTaskSession` | Intelligo | 音频驱动会话服务；显示 `Running/0x41301` 表示任务仍在运行 |
| `NahimicTask32/64` | A-Volute/Nahimic | MSI 机器常见的音效服务 |
| `OmApSvcBroker` | MSI | MSI NBFoundation/设备控制服务 |
| `Nv*`、`NVIDIA*` | NVIDIA | 显卡驱动、Broadcast、更新及遥测/崩溃报告 |
| `OneDC_Updater` | MSI | One Dragon Center 更新器，当前动作位于 `C:\Users\71871\Documents\temp\OneDC_Updater`；路径较特殊，但任务作者和参数均指向 MSI，最近结果为 0 |
| `OneDrive*` | Microsoft | OneDrive 启动、更新和报告 |
| `PlatformExperiencesHelper*` | Microsoft Edge | Edge 平台体验组件 |
| `SoftLanding*` | Windows | Windows 推荐内容/首次体验相关任务，动作通过 COM Handler 执行 |

## 非项目任务中的非零结果

这些结果不影响 Macro_Data：

| 任务 | 结果 | 备注 |
|---|---:|---|
| `NvNodeLauncher_*` | `0x80004005` | NVIDIA 组件通用失败，可在不用 GeForce Experience 时忽略或后续单独修复 |
| `OneDrive Standalone Update Task-*` | `0x8004EE04` | OneDrive 更新器错误；仅在使用 OneDrive 且更新异常时需要处理 |
| `Office Startup Maintenance` | `0xFFFFFFF8` | Office 启动维护返回非零；不影响项目 |
| `IntelligentPwdlessTask` | `0x80040154` | Windows 无密码功能组件未注册；不影响项目 |

## 建议的项目任务集合

保留以下 4 个当前任务：

1. `Macro_Data_Daily_Web_Update`
2. `Macro_Data_Daily_Global_Update`
3. `Macro_Data_Weekly_Web_Revision`
4. `Macro_Data_Weekly_Global_Revision`

`MacroPIT-MOF-History-Daily` 与 `MacroPIT-NBS-History-Daily` 已完成且持续空跑，适合停用。停用不会删除任务、脚本、日志、原始文件或数据库记录，之后仍可手动重新启用。

## 2026-09-18 全球任务范围更新

`Macro_Data_Daily_Global_Update` 仍在每日00:00运行，现包含 OECD、RTDSM、USTREASURY、ChinaBond 和 IMF。`Macro_Data_Weekly_Global_Revision` 仍在周日04:00运行，并增加 USTREASURY 最近400天修订核查；没有新增Windows计划任务。
