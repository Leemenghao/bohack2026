"""A real, replayable multi-candidate research session, visible in the workbench."""
import argparse
from uuid import uuid4

from research_agent.cli import run_research
from research_agent.paths import DATA_ROOT
from research_agent.runview import save_run, timestamp

QUESTION = """开展一项长程 CPU 算子研究：参考 KernelBench level 1 的 39_L2Norm_ 问题，
在当前 Mac 的 NumPy 契约下优化逐行 L2 归一化，重点研究连续与非连续数组布局会不会改变候选排名。我们的缩小输入和零行保护属于改编，不报告官方 KernelBench 分数。
先检查工作区，再搜索 NumPy einsum 与归一化相关的官方资料，读取一份来源作为方法依据。
先实测基线。委派 code 子 Agent 提出两种不同实现，给它完整数值契约和允许 API。
用 development 先筛选五种独立候选，包括广播归约、einsum 归约、分块处理、除法改乘倒数以及根据反馈提出的改进方案，说明临时数组与数值正确性的假设。
正确候选进入 layout_development，再选两个进入 layout_validation，覆盖连续、跨列切片与转置三种布局。最终两名候选的 layout_validation 都要各复测一次，检验进程间抖动是否改变结论。按输入规模和布局比较，不能只报告一个平均加速比。
如果不同输入规模的排名发生冲突，委派 review 子 Agent 读取对应的两份证据，明确指出冲突并申请复核。
不要把一次测量的胜负当作稳定规律，对关键结论做一次有理由的复测。无论是否出现冲突，最终请委派 review 子 Agent 做独立复核，常规任务用 routine，无依据不要申请升级。
由你决定是否保存可复用经验。最终报告列出来源、候选、正确性、分规模速度、费用和未解决的问题。
目标是约 4–5 分钟的真实研究，不要 sleep 或重复无意义工作来凑时长。预算不足时优先收尾，允许提前结束。"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-budget", type=float, default=2)
    args = parser.parse_args()
    folder = DATA_ROOT / "runs" / uuid4().hex[:12]
    run = {"question": QUESTION, "task": "kernel", "status": "running", "mode": "research",
           "created_at": timestamp(), "events": []}
    save_run(folder, run)
    print(f"run_id={folder.name}", flush=True)
    def event(value):
        if value["type"] == "resources":
            run["resources"] = value
        else:
            run["events"].append(value)
        save_run(folder, run)
        if value["type"] in ("progress", "started", "completed"):
            print(value["type"], value.get("stage", ""), str(value.get("summary", value.get("reason", "")))[:160], flush=True)
    try:
        result = run_research(QUESTION, folder, event, task="kernel", cloud_budget=40,
                              max_cost_cny=args.cost_budget, use_memory=False)
        run["status"] = result["status"]
        print({key: result[key] for key in ("status", "elapsed_seconds", "usage")}, flush=True)
    except BaseException:
        run["status"] = "failed"
        raise
    finally:
        save_run(folder, run)
        from research_agent.conversation_store import ConversationStore
        ConversationStore(folder.parent, recover=False).save(folder.name, run)


if __name__ == "__main__":
    main()
