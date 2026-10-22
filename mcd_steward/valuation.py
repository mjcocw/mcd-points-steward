"""估值引擎：把积分、券、商城商品、抽奖池换算成同一把尺子（元）。

本模块是整个项目的"硬核部分"，回答三个问题：

1. **我的积分一块钱值多少？**（名义汇率 + 个人效用汇率）
2. **抽奖到底划不划算？**（期望值、方差、颗粒无收概率）
3. **这么多积分该怎么花？**（稳健 / 平衡 / 进攻三条路线的量化对比）

关键设计：所有估值都乘以一个「个人边际效用折扣」。
券上写 5 元，但如果你本来就会花这 5 元买可乐，这张券对你的真实价值远不止 5 元；
反过来，50 元的周边你不一定想要。
把这件事显式建模，结论才不会误导人。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from .domain import Coupon, LotteryInfo, MallProduct, McSnapshot

# --------------------------------------------------------------------------- #
# 个人效用折扣表：同一张券/奖品，对不同人的价值完全不同
# --------------------------------------------------------------------------- #

#: 品类级默认效用系数
CATEGORY_UTILITY: Dict[str, float] = {
    "代金券": 0.85,   # 通用、能立刻抵扣
    "餐品": 0.60,     # 要真去吃才有价值
    "周边": 0.35,     # 实物，喜好差异极大
    "权益": 0.50,     # 会员权益，按需
}
DEFAULT_UTILITY = 0.50

#: 具体品名效用覆盖（命中优先于品类）
NAME_UTILITY: Dict[str, float] = {
    "巨无霸": 1.00,        # 招牌且本来就是你会买的东西
    "巨无霸套餐": 1.00,
    "板烧鸡腿堡": 0.90,
    "麦辣鸡腿堡": 0.90,
    "麦香鱼": 0.70,
    "麦香鸡": 0.70,
    "麦乐鸡": 0.65,
    "中可乐": 0.25,        # 你本来就会买可乐
    "冰可乐": 0.25,
    "中薯条": 0.45,
    "麦满分": 0.60,
    "甜品站": 0.40,
    "冰咖啡": 0.55,
    "拿铁": 0.60,
    "麦麦省": 0.85,
    "代金券": 0.85,
    "谢谢参与": 0.00,
}

#: 商城商品默认按品类给效用，键为品类关键词
def _utility_for(name: str, category: str = "") -> Tuple[float, str]:
    """返回 (效用系数, 依据说明)。"""
    for key, val in NAME_UTILITY.items():
        if key and key in name:
            return val, f"品名命中「{key}」"
    for key, val in CATEGORY_UTILITY.items():
        if key and key in (category or "") or key in name:
            return val, f"品类「{key or '默认'}」"
    return DEFAULT_UTILITY, "默认系数"


# --------------------------------------------------------------------------- #
# 优惠券面值估算
# --------------------------------------------------------------------------- #

_RE_FULL_OFF = re.compile(r"满\s*\d+(?:\.\d+)?\s*减\s*(\d+(?:\.\d+)?)")
_RE_OFF = re.compile(r"(?:减|立减|直降)\s*(\d+(?:\.\d+)?)\s*元?")
_RE_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*元")
_RE_BUY1GET1 = re.compile(r"买\s*一\s*送\s*一|买1送1|第二份免费")
_RE_HALF = re.compile(r"半价")
_RE_FREE = re.compile(r"免费|免单|0元")


def _normalize(text: str) -> str:
    """去掉括号补充说明与空白，便于菜单名匹配。"""
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"\s+", "", text or "")


def menu_lookup(text: str, menu_map: Dict[str, float]) -> Optional[Tuple[str, float]]:
    """在菜单中找出券名里提到的商品（取最长匹配，避免「麦乐鸡」误配「麦乐鸡（5块）」）。"""
    norm = _normalize(text)
    best: Optional[Tuple[str, float]] = None
    for item_name, price in menu_map.items():
        if price <= 0:
            continue
        base = _normalize(item_name)
        if base and base in norm:
            if best is None or len(base) > len(best[0]):
                best = (base, price)
    return best


def estimate_coupon_value(coupon: Coupon, menu_map: Dict[str, float],
                           utility: float = 1.0) -> Tuple[float, str]:
    """估算一张券的实际价值（元）与依据。

    ``utility`` 对"已持有的券"默认为 1.0（不用就作废，真实价值≈面值），
    对"还没领的券"默认 0.85（要花点时间去用）。
    """
    name = coupon.name or ""

    m = _RE_FULL_OFF.search(name)
    if m:
        v = float(m.group(1)) * utility
        return v, f"满减券：直减 {m.group(1)} 元"

    if _RE_BUY1GET1.search(name):
        hit = menu_lookup(name, menu_map)
        if hit:
            return hit[1] * utility, f"买一送一：{hit[0]} 单价 {hit[1]:g} 元"
        return 15.0 * utility, "买一送一：按常见单品 15 元估算"

    if _RE_HALF.search(name):
        hit = menu_lookup(name, menu_map)
        if hit:
            return hit[1] * 0.5 * utility, f"第二份半价：{hit[0]} {hit[1]:g} 元 × 50%"
        return 18.0 * 0.5 * utility, "第二份半价：按常见单品 18 元估算"

    if _RE_FREE.search(name):
        hit = menu_lookup(name, menu_map)
        if hit:
            return hit[1] * utility, f"免费券：{hit[0]} 单价 {hit[1]:g} 元"
        return 12.0 * utility, "免费券：按常见单品 12 元估算"

    m = _RE_OFF.search(name)
    if m:
        return float(m.group(1)) * utility, f"立减/减额券：{m.group(1)} 元"

    m = _RE_AMOUNT.search(name)
    if m:
        return float(m.group(1)) * utility, f"代金券：面额 {m.group(1)} 元"

    hit = menu_lookup(name, menu_map)
    if hit:
        return hit[1] * utility, f"兑换券：{hit[0]} 单价 {hit[1]:g} 元"

    return 12.0 * utility, "无法从券名解析，按常见单品 12 元保守估算"


# --------------------------------------------------------------------------- #
# 积分汇率
# --------------------------------------------------------------------------- #

@dataclass
class PointRate:
    """积分汇率。"""
    nominal: float = 0.01      # 名义汇率：元 / 积分
    effective: float = 0.01    # 效用汇率：元 / 积分（乘上个人效用折扣后）
    basis: str = "默认 1 积分 = 0.01 元"
    samples: int = 0
    best_product: str = ""


def infer_point_rate(products: Sequence[MallProduct], fallback: float = 0.01) -> PointRate:
    """从麦麦商城的「积分价 / 现金价」反推积分汇率。

    优先用能同时拿到积分价和现金价的商品做样本，取中位数，避免个别促销品拉偏。
    """
    pairs: List[Tuple[float, str]] = []
    for p in products:
        if p.points_price > 0 and p.cash_price > 0:
            pairs.append((p.cash_price / p.points_price, p.name))
    if not pairs:
        return PointRate(nominal=fallback, effective=fallback, basis=f"默认口径 {fallback:g} 元/积分")

    rates = sorted(r for r, _ in pairs)
    median = rates[len(rates) // 2]
    best = max(pairs, key=lambda x: x[0])
    return PointRate(
        nominal=median,
        effective=median,
        basis=f"由 {len(pairs)} 件商城的「现金价 ÷ 积分价」取中位数",
        samples=len(pairs),
        best_product=best[1],
    )


def product_utility_value(p: MallProduct) -> Tuple[float, str]:
    """商品对你的效用价值（元）。"""
    util, why = _utility_for(p.name, p.category)
    base = p.cash_price if p.cash_price > 0 else p.est_value_cny
    return base * util, why


# --------------------------------------------------------------------------- #
# 抽奖期望值
# --------------------------------------------------------------------------- #

@dataclass
class LotteryEV:
    """一次抽奖的期望值画像。"""
    available: bool = False
    name: str = ""
    cost_points: int = 0
    per_draw_cny: float = 0.0
    rate_per_point: float = 0.0
    stdev_cny: float = 0.0
    lose_prob: float = 0.0
    best_prize: str = ""
    best_prize_prob: float = 0.0
    lines: List[str] = field(default_factory=list)
    warning: str = ""


def lottery_expected_value(lottery: Optional[LotteryInfo], menu_map: Dict[str, float]) -> LotteryEV:
    """计算抽奖的期望值、方差与"颗粒无收"概率。

    概率来源优先级：接口给的中奖概率 → 奖品库存占比 → 均分。
    奖品价值 = 面值 × 个人效用折扣。
    """
    if lottery is None or not lottery.prizes:
        return LotteryEV(available=False, warning="当前账号未开放积分抽奖活动")

    total_p = sum(p.probability or 0.0 for p in lottery.prizes)
    if total_p <= 0:
        # 没有概率信息：按库存占比推断
        stocks = []
        for p in lottery.prizes:
            s = p.raw.get("stock", 0) or 0
            stocks.append(float(s))
        tot = sum(stocks)
        if tot > 0:
            for p, s in zip(lottery.prizes, stocks):
                p.probability = s / tot
            total_p = 1.0
        else:
            for p in lottery.prizes:
                p.probability = 1.0 / len(lottery.prizes)
            total_p = 1.0

    ev = 0.0
    ev2 = 0.0
    lose = 0.0
    lines: List[str] = []
    best_name, best_prob, best_val = "", 0.0, 0.0

    for p in lottery.prizes:
        prob = float(p.probability or 0.0)
        util, why = _utility_for(p.name, "")
        face = p.value_cny
        if face <= 0:
            hit = menu_lookup(p.name, menu_map)
            face = hit[1] if hit else 0.0
        value = face * util
        contrib = prob * value
        ev += contrib
        ev2 += prob * (value ** 2)
        if value <= 0:
            lose += prob
        if prob > best_prob:
            best_name, best_prob, best_val = p.name, prob, value
        lines.append(f"  {p.name:<16} 概率 {prob * 100:5.1f}%  面值 {face:>6g} 元  效用 {util:.2f}  贡献 {contrib:>6.2f} 元")

    stdev = math.sqrt(max(ev2 - ev * ev, 0.0))
    cost = lottery.cost_points or 0

    return LotteryEV(
        available=True,
        name=lottery.name,
        cost_points=cost,
        per_draw_cny=ev,
        rate_per_point=(ev / cost) if cost else 0.0,
        stdev_cny=stdev,
        lose_prob=lose,
        best_prize=best_name,
        best_prize_prob=best_prob,
        lines=lines,
        warning="" if total_p >= 0.999 else f"奖品概率合计仅 {total_p * 100:.0f}%，期望值可能被高估",
    )


# --------------------------------------------------------------------------- #
# 0/1 背包：把积分换成确定性最高的效用
# --------------------------------------------------------------------------- #

@dataclass
class RedeemItem:
    product: MallProduct
    points: int
    value_cny: float
    reason: str


@dataclass
class RedeemResult:
    items: List[RedeemItem] = field(default_factory=list)
    spent_points: int = 0
    value_cny: float = 0.0
    leftovers: int = 0


def knapsack_redeem(products: Sequence[MallProduct], capacity: int,
                    max_slots: int = 4000) -> RedeemResult:
    """在积分上限内，用 0/1 背包挑出效用价值最高的商品组合。

    每个商品最多兑换一件（麦麦商城的积分兑换通常是限量的）。
    积分按粒度离散化，控制状态空间规模。
    """
    if capacity <= 0:
        return RedeemResult()

    cand: List[RedeemItem] = []
    for p in products:
        if p.points_price <= 0:
            continue
        if p.stock == 0:
            continue
        value, reason = product_utility_value(p)
        if value <= 0:
            continue
        cand.append(RedeemItem(product=p, points=p.points_price, value_cny=value, reason=reason))
    if not cand:
        return RedeemResult(leftovers=capacity)

    # 粒度：让容量格子数不超过 max_slots
    min_price = min(c.points for c in cand)
    gran = max(1, min(min_price, math.ceil(capacity / max_slots)))
    cap = capacity // gran

    n = len(cand)
    weights = [max(1, round(c.points / gran)) for c in cand]
    values = [c.value_cny for c in cand]

    # dp[j] = 用不超过 j 粒度积分能拿到的最大效用；take[j] = 是否取第 j 件
    dp = [0.0] * (cap + 1)
    take = [[False] * n for _ in range(cap + 1)]
    for i in range(n):
        w, v = weights[i], values[i]
        for j in range(cap, w - 1, -1):
            cand_val = dp[j - w] + v
            if cand_val > dp[j] + 1e-9:
                dp[j] = cand_val
                take[j][i] = True

    # 回溯
    chosen: List[int] = []
    j = cap
    while j > 0:
        for i in range(n - 1, -1, -1):
            if take[j][i]:
                chosen.append(i)
                j -= weights[i]
                break
        else:
            break

    res = RedeemResult()
    for i in chosen:
        c = cand[i]
        res.items.append(c)
        res.spent_points += c.points
        res.value_cny += c.value_cny
    res.leftovers = capacity - res.spent_points
    return res


# --------------------------------------------------------------------------- #
# 三条路线
# --------------------------------------------------------------------------- #

@dataclass
class Route:
    """一条积分处置路线。"""
    key: str
    title: str
    desc: str
    draws: int = 0
    draw_points: int = 0
    unspent_expiring: int = 0
    redeem: RedeemResult = field(default_factory=RedeemResult)
    free_value: float = 0.0
    expected_cny: float = 0.0
    worst_cny: float = 0.0
    all_lose_prob: float = 0.0
    steps: List[str] = field(default_factory=list)


@dataclass
class ExpiryAlert:
    """积分 / 券的到期预警。"""
    kind: str          # points | coupon
    label: str
    points: int = 0
    value_cny: float = 0.0
    days_left: int = 9999
    action: str = ""


@dataclass
class Plan:
    """完整的体检结论。"""
    account_total: int = 0
    account_value: float = 0.0
    rate: PointRate = field(default_factory=PointRate)
    lottery: LotteryEV = field(default_factory=LotteryEV)
    routes: List[Route] = field(default_factory=list)
    recommended: Optional[Route] = None
    recommendation_reason: str = ""
    expiry_alerts: List[ExpiryAlert] = field(default_factory=list)
    free_actions: List[str] = field(default_factory=list)
    free_value: float = 0.0
    notes: List[str] = field(default_factory=list)
    is_mock: bool = False


def build_plan(snapshot: McSnapshot, horizon_days: int = 30,
               default_utility: float = 0.85) -> Plan:
    """生成完整体检结论。

    ``horizon_days``：把"30 天内到期"视为高危窗口。
    """
    today = date.today()
    plan = Plan(is_mock=snapshot.is_mock)
    menu_map = snapshot.menu_price_map

    # ---- 1. 券：0 成本收益，先算 -------------------------------------- #
    held_value = 0.0
    for c in snapshot.my_coupons:
        v, why = estimate_coupon_value(c, menu_map, utility=1.0)
        c.est_value_cny = v
        c.value_reason = why
        held_value += v
        plan.expiry_alerts.append(ExpiryAlert(
            kind="coupon", label=c.name, value_cny=v,
            days_left=c.days_left(today), action=why,
        ))

    claim_value = 0.0
    for c in snapshot.claimable_coupons:
        v, why = estimate_coupon_value(c, menu_map, utility=default_utility)
        c.est_value_cny = v
        c.value_reason = why
        claim_value += v

    plan.free_value = held_value + claim_value
    if snapshot.claimable_coupons:
        plan.free_actions.append(
            f"先领 {len(snapshot.claimable_coupons)} 张麦麦省券（约 {claim_value:.0f} 元）——不花任何积分"
        )
    urgent = [a for a in plan.expiry_alerts if a.kind == "coupon" and a.days_left <= horizon_days]
    if urgent:
        urgent.sort(key=lambda a: a.days_left)
        plan.free_actions.append(
            "先吃掉最早过期的券："
            + "、".join(f"{a.label}（{a.days_left}天后失效，约 {a.value_cny:.0f} 元）" for a in urgent[:3])
        )
    if held_value:
        plan.free_actions.append(
            f"账户内已持有的券合计面值约 {held_value:.0f} 元，{len(snapshot.my_coupons)} 张，优先使用"
        )

    # ---- 2. 汇率与抽奖 ------------------------------------------------- #
    plan.rate = infer_point_rate(snapshot.mall_products)
    plan.lottery = lottery_expected_value(snapshot.lottery, menu_map)
    plan.account_total = snapshot.account.available

    if plan.lottery.available and plan.lottery.cost_points > 0:
        nominal = plan.rate.nominal
        if nominal > 0:
            ratio = plan.lottery.rate_per_point / nominal
            if ratio >= 1.0:
                plan.notes.append(
                    f"抽奖每积分期望 {plan.lottery.rate_per_point:.4f} 元，是兑换名义汇率 "
                    f"({nominal:.4f} 元/分) 的 {ratio:.1f} 倍 —— 但方差大，奖品未必是你想吃的。"
                )
            else:
                plan.notes.append(
                    f"抽奖每积分期望 {plan.lottery.rate_per_point:.4f} 元，低于兑换名义汇率 "
                    f"({nominal:.4f} 元/分)，抽奖不划算。"
                )

    # ---- 3. 积分到期预警 ----------------------------------------------- #
    for b in snapshot.account.expiring:
        days = b.days_left(today)
        plan.expiry_alerts.append(ExpiryAlert(
            kind="points",
            label=b.label or "即将过期积分",
            points=b.points,
            days_left=days,
            value_cny=b.points * plan.rate.nominal,
        ))

    # ---- 4. 三条路线 --------------------------------------------------- #
    total_points = snapshot.account.available
    expiring_points = sum(b.points for b in snapshot.account.expiring
                           if b.days_left(today) <= horizon_days)
    stable_points = max(0, total_points - expiring_points)
    cost = plan.lottery.cost_points if plan.lottery.available else 0

    def make_route(key: str, title: str, desc: str, draw_pool: int,
                   redeem_pool: int) -> Route:
        r = Route(key=key, title=title, desc=desc)
        r.free_value = plan.free_value
        draws = 0
        if cost > 0 and draw_pool > 0 and plan.lottery.available:
            draws = draw_pool // cost
        r.draws = draws
        r.draw_points = draws * cost
        r.unspent_expiring = max(0, draw_pool - r.draw_points)
        r.redeem = knapsack_redeem(snapshot.mall_products, redeem_pool)
        r.expected_cny = (plan.free_value
                          + draws * plan.lottery.per_draw_cny
                          + r.redeem.value_cny)
        r.worst_cny = plan.free_value + r.redeem.value_cny
        if draws > 0 and plan.lottery.lose_prob > 0:
            r.all_lose_prob = plan.lottery.lose_prob ** draws
        return r

    steady = make_route("steady", "稳健型：全部换成确定的商品 / 券",
                        "一分不赌，全部换成到手即用的兑换物。收益确定，但单位积分价值最低。",
                        0, total_points)
    balanced = make_route("balanced", "平衡型：到期积分抽奖，长期积分兑换",
                           "反正要过期的积分拿去抽奖（机会成本为零），长期积分换确定商品。",
                           expiring_points, stable_points)
    aggressive = make_route("aggressive", "进攻型：积分全部拿去抽奖",
                             "期望值最高，但有颗粒无收的风险。适合积分马上过期、且本来就爱玩抽奖的人。",
                             total_points, 0)

    for r in (steady, balanced, aggressive):
        r.steps = _route_steps(r, plan, cost, horizon_days)

    plan.routes = [steady, balanced, aggressive]
    if expiring_points > 0 and plan.lottery.available and cost > 0:
        plan.recommended = balanced
        plan.recommendation_reason = (
            f"你有 {expiring_points} 积分将在 {horizon_days} 天内过期，机会成本为零 —— "
            f"拿去抽奖的每积分期望值（{plan.lottery.rate_per_point:.4f} 元）"
            f"是兑换名义汇率（{plan.rate.nominal:.4f} 元）的 "
            f"{plan.lottery.rate_per_point / plan.rate.nominal:.1f} 倍，"
            f"所以「到期就抽、长期就换」是期望值最高且风险可控的组合。"
        )
    elif plan.lottery.available and cost > 0 and plan.lottery.rate_per_point > plan.rate.nominal:
        plan.recommended = aggressive
        plan.recommendation_reason = (
            f"抽奖每积分期望值（{plan.lottery.rate_per_point:.4f} 元）高于兑换名义汇率"
            f"（{plan.rate.nominal:.4f} 元），如果你不介意方差，可以全部拿去抽奖。"
        )
    else:
        plan.recommended = steady
        plan.recommendation_reason = (
            f"抽奖的每积分期望值（{plan.lottery.rate_per_point:.4f} 元）没有超过兑换汇率"
            f"（{plan.rate.nominal:.4f} 元），建议全部换成确定性的商品。"
        )

    if not snapshot.mall_products:
        plan.notes.append("未取到麦麦商城商品数据，兑换路线仅按抽奖期望值估算")
    plan.notes.extend(snapshot.notes)
    return plan


def _route_steps(route: Route, plan: Plan, cost: int, horizon_days: int) -> List[str]:
    """把一条路线拆成可执行的动作清单。"""
    steps: List[str] = []
    if plan.free_value > 0:
        steps.append(f"领取并用掉现有优惠券，锁定约 {plan.free_value:.0f} 元零成本收益")
    if route.draws > 0:
        steps.append(
            f"用 {route.draw_points} 积分抽奖 {route.draws} 次"
            f"（期望 {route.draws * plan.lottery.per_draw_cny:.1f} 元，"
            f"颗粒无收概率 {route.all_lose_prob * 100:.0f}%）"
        )
    if route.redeem.items:
        names = "、".join(i.product.name for i in route.redeem.items[:3])
        steps.append(
            f"剩余 {route.redeem.spent_points} 积分兑换：{names}"
            f"（效用价值约 {route.redeem.value_cny:.1f} 元）"
        )
    if route.redeem.leftovers > 0:
        steps.append(f"剩余 {route.redeem.leftovers} 积分不足兑换门槛，留待下一周期")
    if route.unspent_expiring > 0:
        steps.append(
            f"另有 {route.unspent_expiring} 积分到期但不够一次抽奖（每次 {cost} 积分），"
            f"建议直接用于低价券或代金券兑换"
        )
    return steps
