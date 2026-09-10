"""Build and validate the frozen 34-field task list. No requests or observations."""
import hashlib
import json
from pathlib import Path
import shutil
from collections import Counter
import pandas as pd

OUT = Path("reports/v2/pit_34_backfill")


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path("config/pit34_backfill_plan.json").read_text(encoding="utf-8"))
    baseline = OUT / "baseline_first_points.csv"
    if not baseline.exists():
        shutil.copyfile("reports/v2/pit_csv_inspection/first_points.csv", baseline)
    first = pd.read_csv(baseline).set_index("indicator")
    target = set(first[first.first_nonnull_as_of.ge("2021-01-01")].index)
    assert len(first) == 47 and len(target) == 34
    rows = []
    for group in plan["groups"]:
        for indicator in group["fields"]:
            current = first.loc[indicator]
            rows.append(dict(task_id=f"PIT34-{len(rows)+1:02d}", indicator=indicator, name=current['name'],
                source=current.source, frequency=current.frequency, group_id=group['id'], batch=group['batch'],
                status="PLANNED", current_first_as_of=current.first_nonnull_as_of,
                current_first_data_period=current.strict_first_data_period,
                current_strict_periods=int(current.strict_original_period_count),
                classification=group['classification'], target_data_period=group['target_data_period'],
                target_as_of=group['target_as_of'], evidence_status=group['evidence_status'],
                source_route=group['source_route'], parser_work=group['parser_work'],
                scope_check=group['scope_check'], first_action=group['first_action']))
    tasks = pd.DataFrame(rows).sort_values(['batch','task_id'])
    assert len(tasks) == 34 and not tasks.indicator.duplicated().any()
    assert set(tasks.indicator) == target
    assert Counter(tasks.source) == {'NBS':17, 'PBOC':10, 'SAFE':7}
    assert Counter(tasks.classification) == {'seek_2005':18, 'later_or_scope_review':16}
    tasks.to_csv(OUT / "tasks.csv", index=False, encoding="utf-8-sig")
    # A generated specification is not a progress tracker; execution writes its
    # own state so regenerating this plan never resets completed work.
    (OUT / "task_specifications.json").write_text(json.dumps(tasks.to_dict('records'),ensure_ascii=False,indent=2),encoding="utf-8")
    detail = ["# 34 字段逐项任务", "", "本表为冻结基线与任务规格，PLANNED 是规划时状态。实际执行进度见 [execution_progress.csv](execution_progress.csv) 和 execution_state.json；重生成规格不重置执行状态。", "",
              "| 任务 | 字段 | 当前首次有值 | 当前真实期数 | 批次 | 回溯目标数据期 |", "|---|---|---|---:|---|---|"]
    for r in tasks.itertuples():
        detail.append(f"| {r.task_id} | {r.name} | {r.current_first_as_of} | {r.current_strict_periods} | {r.batch} | {r.target_data_period} |")
    detail += ["", "每项的来源路径、解析改动、口径限制、首个动作及目标可用时间见 [tasks.csv](tasks.csv)。月份与季度分别计数，不能把覆盖期数相加当作同一频率样本数。"]
    (OUT / "TASKS.md").write_text('\n'.join(detail)+'\n',encoding='utf-8')
    report = dict(status="PASS",fields=34,unique_task_ids=tasks.task_id.nunique(),groups=len(plan['groups']),
                  source_counts=dict(Counter(tasks.source)),class_counts=dict(Counter(tasks.classification)),
                  batch_counts=tasks.groupby('batch').size().to_dict(),baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
                  database_modified=False,wide_export_modified=False,download_started=False)
    (OUT / "plan_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    build()
