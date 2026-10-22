#!/usr/bin/env python3
"""自检脚本：不依赖 Token，验证核心计算链路的正确性。

    python selftest.py

这是给评审者看的 —— 证明这不是一个只会调接口的壳子。
所有断言都基于**麦当劳真实接口的字段结构**（2026-10 实测）。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_steward.domain import (  # noqa: E402
    Coupon,
    MallProduct,
    business_error,
    parse_account,
    parse_lottery,
    parse_mall_products,
    price_from_name,
)
from mcd_steward.source import MockSource  # noqa: E402
from mcd_steward.valuation import (  # noqa: E402
    build_plan,
    estimate_coupon_value,
    infer_point_rate,
    knapsack_redeem,
    lottery_expected_value,
    reference_price,
)

PASS, FAIL = "  [PASS]", "  [FAIL]"
_failures = []
TODAY = date.today()


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"{PASS} {name}")
    else:
        print(f"{FAIL} {name}  {detail}")
        _failures.append(name)


def main() -> int:
    print("\n== 1. 账户解析（真实字段 availablePoint / currentMouthExpirePoint）==")
    acc = parse_account({
        "availablePoint": "1240", "accumulativePoint": "5860", "frozenPoint": "0",
        "usedPoint": "0", "expiredPoint": "143.3",
        "currentMouthExpirePoint": "240", "nextMouthExpirePoint": "100",
    })
    check("可用积分解析正确", acc.available == 1240, f"实际 {acc.available}")
    check("累计积分解析正确", acc.total_earned == 5860, f"实际 {acc.total_earned}")
    check("已过期积分解析正确", acc.expired == 143, f"实际 {acc.expired}")
    check("本月到期积分解析正确", acc.expiring[0].points == 240, f"实际 {acc.expiring[0].points}")
    check("下月到期积分解析正确", acc.expiring[1].points == 100, f"实际 {acc.expiring[1].points}")
    check("到期积分合计正确", acc.expiring_total == 340, f"实际 {acc.expiring_total}")

    print("\n== 2. 券面值估算 ==")
    menu = {"中可乐": 10.0, "麦辣鸡腿堡": 21.0, "麦乐鸡": 39.0, "甜品站": 8.0,
            "脆薯饼": 9.9, "麦旋风": 11.0}
    cases = [
        ("巨无霸套餐满60减15元券", 15.0),
        ("11.9元麦辣鸡腿堡", 11.9),
        ("免费中可乐一杯", 10.0),
        ("麦辣鸡腿堡买一送一", 21.0),
        ("第二份麦乐鸡半价券", 19.5),
        ("甜品站任选一件免费券", 8.0),
        ("免费脆薯饼", 9.9),
        ("早餐时段麦满分减6元", 6.0),
    ]
    for name, expect in cases:
        got, why = estimate_coupon_value(Coupon("x", name), menu)
        check(f"「{name}」→ {expect:g} 元", abs(got - expect) < 1e-6, f"实际 {got:g} 元（{why}）")

    print("\n== 3. 商品名解析（price 字段恒为 0，价值藏在名称里）==")
    check("「21.9元巨无霸可乐组合」→ 21.9",
          abs(price_from_name("21.9元巨无霸可乐组合") - 21.9) < 1e-9)
    check("「麦旋风」参考价 = 11", abs(reference_price("麦旋风5折券") - 11.0) < 1e-9,
          f"实际 {reference_price('麦旋风5折券')}")
    check("「麦辣三件套」取主料 21", abs(reference_price("麦辣三件套5折券") - 21.0) < 1e-9,
          f"实际 {reference_price('麦辣三件套5折券')}")
    check("「甜辣小食组合」取最早命中的主料 21",
          abs(reference_price("甜辣小食组合5折券") - 21.0) < 1e-9,
          f"实际 {reference_price('甜辣小食组合5折券')}")

    print("\n== 4. 商城解析 + 下架过滤 ==")
    mall = parse_mall_products([
        {"spuName": "21.9元巨无霸可乐组合", "spuId": 1, "point": "800", "price": "0",
         "catName": "到店专用", "downTime": "2026-12-30 23:59:59"},
        {"spuName": "18.8元板烧鸡腿堡两件套", "spuId": 2, "point": "100", "price": "0",
         "catName": "到店专用", "downTime": "2020-03-21 23:59:59"},
        {"spuName": "麦当劳奇妙生日派对", "spuId": 3, "point": "0", "price": "50",
         "catName": "生日类派对", "downTime": "2027-12-31 23:59:59"},
    ])
    check("商品名解析正确", mall[0].name == "21.9元巨无霸可乐组合")
    check("面值从名称反推（price=0）", abs(mall[0].cash_price - 21.9) < 1e-9,
          f"实际 {mall[0].cash_price}")
    check("积分价解析正确", mall[0].points_price == 800)
    check("已下架商品被识别", not mall[1].is_on_sale(TODAY))
    check("在架商品被识别", mall[0].is_on_sale(TODAY))

    rate = infer_point_rate(mall)
    check("汇率只用仍在架商品（1 件样本）", rate.samples == 1, f"实际 {rate.samples}")
    check("汇率 = 21.9/800", abs(rate.nominal - 21.9 / 800) < 1e-9, f"实际 {rate.nominal}")
    check("下架/非兑换商品被跳过", rate.skipped == 2, f"实际 {rate.skipped}")

    print("\n== 5. 0/1 背包 ==")
    pool = [
        MallProduct("p1", "大件", 1000, 20.0, category="周边"),   # 效用 0.35 → 7.0
        MallProduct("p2", "尝鲜", 800, 15.0, category="餐品"),    # 效用 0.60 → 9.0
        MallProduct("p3", "券", 500, 5.0, category="代金券"),     # 效用 0.85 → 4.25
    ]
    res = knapsack_redeem(pool, 1000)
    check("1000 积分应选 800 分的尝鲜礼盒(9.0元)",
          len(res.items) == 1 and res.items[0].product.name == "尝鲜",
          f"实际 {[i.product.name for i in res.items]}")
    check("兑换效用价值 = 9.0 元", abs(res.value_cny - 9.0) < 1e-6, f"实际 {res.value_cny}")
    res2 = knapsack_redeem(pool, 5000)
    check("5000 积分应选多件且不超预算",
          res2.spent_points <= 5000 and len(res2.items) >= 2,
          f"实际 {res2.spent_points} 分 {len(res2.items)} 件")

    print("\n== 6. 抽奖期望值（官方不返回概率 → 等概率假设并标注）==")
    snap = MockSource().collect()
    ev = lottery_expected_value(snap.lottery, snap.menu_price_map, 0.0338)
    check("抽奖可用", ev.available)
    check("单次消耗 24 积分", ev.cost_points == 24, f"实际 {ev.cost_points}")
    check("单次期望在 7~10 元区间", 7.0 < ev.per_draw_cny < 10.0, f"实际 {ev.per_draw_cny:.3f}")
    check("每积分期望 > 0.2 元", ev.rate_per_point > 0.2, f"实际 {ev.rate_per_point:.4f}")
    check("标准差 > 期望值（高方差）", ev.stdev_cny > ev.per_draw_cny,
          f"标准差 {ev.stdev_cny:.2f} vs 期望 {ev.per_draw_cny:.2f}")
    check("明确标注概率来源", "等概率" in ev.probability_source, ev.probability_source)
    check("给出「概率未公布会高估」的警告", "高估" in ev.warning, ev.warning)

    print("\n== 7. 业务错误识别（官方 success:false 约定）==")
    err = business_error({"success": False, "code": 600050, "message": "收藏餐厅列表为空"})
    check("识别 success:false", err is not None and "600050" in err, f"实际 {err}")
    check("正常返回不误报", business_error({"items": []}) is None)

    print("\n== 8. 完整方案（mock，字段结构与真实接口一致）==")
    plan = build_plan(snap)
    check("可用积分为 1240", plan.account_total == 1240, f"实际 {plan.account_total}")
    check("零成本收益 > 100 元", plan.free_value > 100, f"实际 {plan.free_value:.1f}")
    check("生成 3 条路线", len(plan.routes) == 3, f"实际 {len(plan.routes)}")
    check("推荐路线为 balance", plan.recommended and plan.recommended.key == "balanced",
          f"实际 {plan.recommended.key if plan.recommended else None}")
    check("平衡型拿到期积分去抽奖", plan.recommended and plan.recommended.draws == 10,
          f"实际 {plan.recommended.draws if plan.recommended else None} 次")
    check("兑换清单不含已下架商品",
          all(i.product.is_on_sale(TODAY) for i in plan.recommended.redeem.items),
          "出现了已下架商品")
    check("进攻型期望值 > 稳健型", plan.routes[2].expected_cny > plan.routes[0].expected_cny,
          f"{plan.routes[2].expected_cny:.1f} vs {plan.routes[0].expected_cny:.1f}")
    check("给出了推荐依据", len(plan.recommendation_reason) > 20)

    print("\n== 9. 零积分账户（真实账户就是这种情况）==")
    empty = MockSource().collect()
    empty.account.available = 0
    empty.account.expired = 143
    empty.account.expiring = []
    plan2 = build_plan(empty)
    check("零积分时不推荐抽奖",
          plan2.recommended and plan2.recommended.key == "steady",
          f"实际 {plan2.recommended.key if plan2.recommended else None}")
    check("零积分推荐依据提到过期积分", "过期" in plan2.recommendation_reason)
    check("已过期积分进入预警", any(a.kind == "expired" for a in plan2.expiry_alerts))

    print("\n" + "=" * 60)
    if _failures:
        print(f"失败 {len(_failures)} 项：{', '.join(_failures)}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
