"""命令行入口。

用法
----
    # 离线演示（不需要 Token，评审者直接就能跑）
    python main.py --mock

    # 真实账户
    export MCD_MCP_TOKEN=你的Token
    python main.py --live

    # 同时导出 HTML 报告
    python main.py --mock --html out/report.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict

from .domain import McSnapshot
from .mcp_client import McpError
from .report import render_html, render_terminal
from .source import build_source
from .valuation import build_plan


def _plan_to_dict(plan, snapshot: McSnapshot) -> Dict[str, Any]:
    """导出结构化结果，方便二次开发或被别的 Skill 调用。"""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "is_mock": plan.is_mock,
        "account": {
            "available_points": plan.account_total,
            "nominal_rate_per_point": round(plan.rate.nominal, 6),
            "rate_basis": plan.rate.basis,
            "expiring": [
                {"points": b.points, "expire_date": b.expire_date.isoformat() if b.expire_date else None,
                 "days_left": b.days_left()}
                for b in snapshot.account.expiring
            ],
        },
        "free_value_cny": round(plan.free_value, 2),
        "lottery": {
            "available": plan.lottery.available,
            "name": plan.lottery.name,
            "cost_points": plan.lottery.cost_points,
            "expected_per_draw_cny": round(plan.lottery.per_draw_cny, 4),
            "rate_per_point": round(plan.lottery.rate_per_point, 6),
            "stdev_cny": round(plan.lottery.stdev_cny, 4),
            "lose_probability": round(plan.lottery.lose_prob, 4),
        },
        "routes": [
            {
                "key": r.key,
                "title": r.title,
                "description": r.desc,
                "draws": r.draws,
                "draw_points": r.draw_points,
                "redeem_points": r.redeem.spent_points,
                "redeem_items": [
                    {"name": i.product.name, "points": i.points, "value_cny": round(i.value_cny, 2)}
                    for i in r.redeem.items
                ],
                "expected_cny": round(r.expected_cny, 2),
                "worst_case_cny": round(r.worst_cny, 2),
                "all_lose_probability": round(r.all_lose_prob, 4),
                "steps": r.steps,
            }
            for r in plan.routes
        ],
        "recommended": plan.recommended.key if plan.recommended else None,
        "expiry_alerts": [
            {"kind": a.kind, "label": a.label, "points": a.points,
             "value_cny": round(a.value_cny, 2), "days_left": a.days_left, "action": a.action}
            for a in plan.expiry_alerts
        ],
        "free_actions": plan.free_actions,
        "notes": plan.notes,
    }


def main(argv: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcd-points-steward",
        description="麦麦积分资产管家 —— 扫描你的麦当劳积分账户，算清最优兑换路线",
    )
    parser.add_argument("--mode", choices=["auto", "live", "mock"], default="auto",
                        help="auto=有 Token 就走真实接口（默认），live=强制真实，mock=强制离线演示")
    parser.add_argument("--mock", action="store_true", help="等价于 --mode mock（离线演示，无需 Token）")
    parser.add_argument("--live", action="store_true", help="等价于 --mode live（连接真实 MCP）")
    parser.add_argument("--token", default=None, help="MCP Token（默认读环境变量 MCD_MCP_TOKEN）")
    parser.add_argument("--html", default=None, help="把 HTML 报告写到指定路径")
    parser.add_argument("--json", dest="json_out", default=None, help="把结构化结果写到指定路径")
    parser.add_argument("--quiet", action="store_true", help="不打印终端报告")
    parser.add_argument("--horizon", type=int, default=30, help="到期高危窗口天数，默认 30")
    parser.add_argument("--city", default="", help="所在城市（用于解析门店菜单价格），也可用环境变量 MCD_CITY")
    parser.add_argument("--keyword", default="麦当劳", help="门店搜索关键词，默认「麦当劳」")
    args = parser.parse_args(argv)

    mode = args.mode
    if args.mock:
        mode = "mock"
    elif args.live:
        mode = "live"

    try:
        source = build_source(mode, args.token, city=args.city, keyword=args.keyword)
        snapshot = source.collect()
    except McpError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        print("提示：可先用 --mock 以离线演示数据跑通全流程。", file=sys.stderr)
        return 2

    plan = build_plan(snapshot, horizon_days=args.horizon)

    if not args.quiet:
        print(render_terminal(plan, snapshot))

    if args.html:
        os.makedirs(os.path.dirname(os.path.abspath(args.html)) or ".", exist_ok=True)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(plan, snapshot))
        if not args.quiet:
            print(f"[已写出] HTML 报告 → {args.html}")

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(_plan_to_dict(plan, snapshot), fh, ensure_ascii=False, indent=2)
        if not args.quiet:
            print(f"[已写出] 结构化结果 → {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
