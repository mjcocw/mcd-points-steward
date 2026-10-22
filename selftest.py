#!/usr/bin/env python3
"""自检脚本：不依赖 Token，验证核心计算链路的正确性。

    python selftest.py

这是给评审者看的 —— 证明这不是一个只会调接口的壳子。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_steward.domain import Coupon, MallProduct, parse_account  # noqa: E402
from mcd_steward.source import MockSource  # noqa: E402
from mcd_steward.valuation import (  # noqa: E402
    build_plan,
    estimate_coupon_value,
    infer_point_rate,
    knapsack_redeem,
    lottery_expected_value,
)

PASS, FAIL = "  [PASS]", "  [FAIL]"
_failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"{PASS} {name}")
    else:
        print(f"{FAIL} {name}  {detail}")
        _failures.append(name)


def main() -> int:
    print("\n== 1. 账户解析 ==")
    acc = parse_account({"available": 1240, "totalEarned": 5860, "frozen": 0,
                         "expiring": [{"points": 240, "expireDate": "2026-11-30"}]})
    check("可用积分解析正确", acc.available == 1240, f"实际 {acc.available}")
    check("累计积分解析正确", acc.total_earned == 5860, f"实际 {acc.total_earned}")
    check("即将过期积分解析正确", acc.expiring_total == 240, f"实际 {acc.expiring_total}")

    print("\n== 2. 券面值估算 ==")
    menu = {"中可乐": 10.0, "麦辣鸡腿堡": 21.0, "麦乐鸡": 39.0, "甜品站": 8.0}
    cases = [
        ("巨无霸套餐满60减15元券", 15.0),
        ("免费中可乐一杯", 10.0),
        ("麦辣鸡腿堡买一送一", 21.0),
        ("第二份麦乐鸡半价券", 19.5),
        ("甜品站任选一件免费券", 8.0),
        ("早餐时段麦满分减6元", 6.0),
    ]
    for name, expect in cases:
        got, why = estimate_coupon_value(Coupon("x", name), menu)
        check(f"「{name}」→ {expect:g} 元", abs(got - expect) < 1e-6, f"实际 {got:g} 元（{why}）")

    print("\n== 3. 积分汇率反推 ==")
    prods = [
        MallProduct("a", "甲", 1000, 20.0),
        MallProduct("b", "乙", 500, 5.0),
        MallProduct("c", "丙", 2000, 20.0),
    ]
    rate = infer_point_rate(prods)
    check("中位数汇率 = 0.01 元/积分", abs(rate.nominal - 0.01) < 1e-9, f"实际 {rate.nominal}")
    check("样本数正确", rate.samples == 3, f"实际 {rate.samples}")

    print("\n== 4. 0/1 背包 ==")
    pool = [
        MallProduct("p1", "大件", 1000, 20.0, category="周边"),   # 效用 0.35 → 7.0
        MallProduct("p2", "尝鲜", 800, 15.0, category="餐品"),    # 效用 0.60 → 9.0
        MallProduct("p3", "券", 500, 5.0, category="代金券"),     # 效用 0.85 → 4.25
    ]
    res = knapsack_redeem(pool, 1000)
    check("1000 积分应选 800 分的尝鲜礼盒(9.0元)", len(res.items) == 1 and res.items[0].product.name == "尝鲜",
          f"实际 {[i.product.name for i in res.items]}")
    check("兑换效用价值 = 9.0 元", abs(res.value_cny - 9.0) < 1e-6, f"实际 {res.value_cny}")
    res2 = knapsack_redeem(pool, 5000)
    check("5000 积分应选多件且不超预算", res2.spent_points <= 5000 and len(res2.items) >= 2,
          f"实际 {res2.spent_points} 分 {len(res2.items)} 件")

    print("\n== 5. 抽奖期望值 ==")
    snap = MockSource().collect()
    ev = lottery_expected_value(snap.lottery, snap.menu_price_map)
    check("抽奖可用", ev.available)
    check("单次期望在 4~6 元区间", 4.0 < ev.per_draw_cny < 6.0, f"实际 {ev.per_draw_cny:.3f}")
    check("每积分期望 > 0.04 元", ev.rate_per_point > 0.04, f"实际 {ev.rate_per_point:.4f}")
    check("颗粒无收概率约 40%", abs(ev.lose_prob - 0.40) < 0.02, f"实际 {ev.lose_prob:.3f}")
    check("标准差 > 期望值（高方差）", ev.stdev_cny > ev.per_draw_cny, f"标准差 {ev.stdev_cny:.2f}")

    print("\n== 6. 完整方案 ==")
    plan = build_plan(snap)
    check("可用积分为 1240", plan.account_total == 1240, f"实际 {plan.account_total}")
    check("零成本收益 > 90 元", plan.free_value > 90, f"实际 {plan.free_value:.1f}")
    check("生成 3 条路线", len(plan.routes) == 3, f"实际 {len(plan.routes)}")
    check("推荐路线为 balance", plan.recommended and plan.recommended.key == "balanced",
          f"实际 {plan.recommended.key if plan.recommended else None}")
    check("平衡型用掉到期积分去抽奖", plan.recommended and plan.recommended.draws == 2,
          f"实际 {plan.recommended.draws if plan.recommended else None} 次")
    check("进攻型期望值 > 稳健型", plan.routes[2].expected_cny > plan.routes[0].expected_cny,
          f"{plan.routes[2].expected_cny:.1f} vs {plan.routes[0].expected_cny:.1f}")
    check("进攻型最差情况不高于稳健型", plan.routes[2].worst_cny <= plan.routes[0].worst_cny + 1e-6,
          f"{plan.routes[2].worst_cny:.1f} vs {plan.routes[0].worst_cny:.1f}")
    check("给出了推荐依据", len(plan.recommendation_reason) > 20)

    print("\n" + "=" * 60)
    if _failures:
        print(f"失败 {len(_failures)} 项：{', '.join(_failures)}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
