#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_prompt_builder.py: standardized review prompt with scenario matrix.

2026-08-10 评审流程优化（9 个提交后问题回顾）：
A. 材料缺陷（主场景外退化场景未暴露）→ 场景矩阵强制
B. 测试盲区（无反例）→ 反例清单强制
C. 发布链门禁 → pytest 强制（已落地）
D. 环境差异 → 标注"本地已验证/runner 差异风险"
E. diff stat 未展示 → stat 强制

用法：python scripts/review_prompt_builder.py <diff_path> [--extra "补充背景"]
输出标准评审 prompt（stdout）。
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def build_prompt(diff_path: str, extra: str = "", gate_hash: str = "") -> str:
    diff = Path(diff_path).read_text(encoding="utf-8")
    sha = gate_hash or hashlib.sha256(diff.encode("utf-8")).hexdigest()
    lines = diff.splitlines()
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    files = set()
    for l in lines:
        if l.startswith("+++ b/"):
            files.add(l[6:])
    stat = f"文件数={len(files)} 新增行={added} 删除行={removed} 文件: {', '.join(sorted(files))}"

    return f"""请对 crawl_phones 手机数据仓库以下 unified diff 做严格代码评审。
diff SHA-256: {sha}

【diff stat（必须审查——异常大/噪音 diff 应质疑）】
{stat}

【评审纪律（2026-08-10 流程优化，必须遵守）】
1. 必须严格基于 diff 中的实际代码评审——不要假设 diff 之外存在的表/函数/结构，
   不要脑补实现细节（此前评审曾幻觉不存在的 phone_spu_mapping 等概念）。
2. 必须逐项检查以下边界场景矩阵（缺场景=评审不完整）：
   - 空输入 / 数据缺失（输入缺某型号/某字段时行为）
   - 单侧缺失（信息缺失 vs 信息冲突的边界）
   - 单位变体（GB/TB/亿像素/英寸/色深——含口语形式如"1T"=1TB）
   - 格式差异（全角/半角括号、多值容量"256|512"、描述详略）
   - 源数退化（候选源数 < 基线源数时的覆盖/保留）
   - 同键多行（同 SPU/同型号级多行并存时的归并/去重）
3. 必须检查"测试断言与行为变更的一致性"：diff 改了行为，相关字段的既有测试断言
   是否同步（此前 Agent 改屏幕缺失侧语义不同步 3 个断言导致 CI 红）。
4. 必须列出遗漏的测试用例（反例缺失清单）——指出哪些边界场景没有测试覆盖。
5. 环境差异标注：本地已验证通过但 runner 可能不同的部分（Python/PyYAML 版本、
   网络端点可用性、import 路径）——评估降级/回退路径安全性。

【背景】
{extra}

【评审输出要求】
1. 第一行输出：DIFF_SHA256: {sha}
2. 必须包含一行独立的：结论：PASS（不要加粗/前缀/后缀）；正文避免独立成行的"结论：xxx"（用"判定："代替）
3. 输出结构：边界场景矩阵逐项判定 / 测试一致性检查 / 反例缺失清单 / 结论

【完整 diff】
{diff}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("diff_path")
    ap.add_argument("--extra", default="")
    ap.add_argument("--gate-hash", default="")
    args = ap.parse_args()
    print(build_prompt(args.diff_path, args.extra, args.gate_hash))
    return 0


if __name__ == "__main__":
    sys.exit(main())
