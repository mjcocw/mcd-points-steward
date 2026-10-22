"""估值引擎：把积分、券、商城商品、抽奖池换算成同一把尺子（元）。

本模块是整个项目的"硬核部分"，回答三个问题：

1. **我的积分一块钱值多少？**（名义汇率 + 个人效用汇率）
2. **抽奖到底划不划算？**（期望值、方差、颗粒无收概率）
3. **这么多积分该怎么花？**（稳健 / 平衡 / 进攻三条路线的量化对比）

真实接口带来的三个硬约束（2026-10 实测）
------------------------------------------
1. 麦麦商城的 ``price`` 字段对商品券**恒为 0**，真实面值藏在商品名里
   （"21.9元巨无霸可乐组合"）。所以价值必须从名称解析。
2. 商城商品带 ``downTime``，**很多已下架**（实测 23 个可兑换商品里过半已过期）。
   不过滤就会推荐买不到的东西。
3. 抽奖接口**不返回中奖概率，也不返回奖品面值**。概率只能等分假设并**明确标注**，
   面值从奖品名解析（"下单立减3元券" → 3 元，"麦辣三件套5折券" → 三件套 × 5 折）。

关键设计：所有估值都乘一个「个人边际效用折扣」。
券上写 5 元，但如果你本来就会花这 5 元买可乐，这张券对你的真实价值远不止 5 元；
反过来，50 元的周边你不一定想要。把这件事显式建模，结论才不会误导人。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from .domain import (
    Coupon,
    LotteryInfo,
    MallProduct,
    McSnapshot,
    discount_from_name,
    points_from_name,
    price_from_name,
)

# --------------------------------------------------------------------------- #
# 个人效用折扣表：同一张券/奖品，对不同人的价值完全不同
# --------------------------------------------------------------------------- #

#: 品类级默认效用系数
CATEGORY_UTILITY: Dict[str, float] = {
    "代金券": 0.85,   # 通用、能立刻抵扣
    "商品券": 0.70,   # 只能点指定的东西
    "餐品": 0.60,     # 要真去吃才有价值
    "到店专用": 0.60,
    "周边": 0.35,     # 实物，喜好差异极大
    "玩具": 0.30,
    "权益": 0.50,     # 会员权益，按需
    "读书会": 0.40,
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
    "麦旋风": 0.50,
    "鳕鱼": 0.65,
    "脆薯饼": 0.70,
    "中可乐": 0.25,        # 你本来就会买可乐
    "可乐": 0.25,
    "冰可乐": 0.25,
    "中薯条": 0.45,
    "薯条": 0.45,
    "麦满分": 0.60,
    "甜品站": 0.40,
    "派": 0.45,
    "冰咖啡": 0.55,
    "拿铁": 0.60,
    "麦麦省": 0.85,
    "代金券": 0.85,
    "立减": 0.80,          # 立减券几乎无门槛
    "谢谢参与": 0.00,
}

#: 常见麦当劳中国单品参考价（元）—— **可自行编辑**
#: ⚠ 只放「真实单价」，**不要**把券面额（如 "11.9元麦辣鸡腿堡"）塞进来：
#:   券面额是促销价，不代表商品单价，会把"买一送一"这类券的价值算错。
REFERENCE_PRICES: Dict[str, float] = {
    "巨无霸": 22.0, "巨无霸套餐": 35.0,
    "麦辣鸡腿堡": 21.0, "板烧鸡腿堡": 21.0, "麦香鸡": 21.0, "麦香鱼": 22.0,
    "双层鳕鱼堡": 24.0, "鳕鱼堡": 22.0,
    "麦乐鸡": 39.0, "麦乐鸡腿": 12.0, "麦辣鸡翅": 9.9,
    "中可乐": 10.0, "大可乐": 13.0, "冰可乐": 10.0, "无糖可乐": 10.0,
    "中薯条": 11.0, "大薯条": 14.0, "黄金脆薯": 9.9, "脆薯饼": 9.9,
    "麦满分": 15.0, "猪柳蛋麦满分": 16.0,
    "甜品站": 8.0, "香芋派": 6.5, "菠萝派": 6.5, "麦旋风": 11.0,
    "冰咖啡": 13.0, "拿铁": 22.0, "美式": 13.0,
    "鸡翅": 9.9, "鸡块": 11.0, "小食拼盘": 18.0, "上校鸡块": 12.0,
    # —— 组合 / 套餐里的主料，用于 "X三件套Y折券" 的估值 ——
    "麦辣": 21.0, "板烧": 21.0, "鳕鱼": 24.0, "甜辣": 21.0, "小食": 9.9, "派": 6.5,
}


#: 饮料类词条：出现在"组合 / 套餐"里时不能代表整份套餐的价值
_BEVERAGES = ("可乐", "咖啡", "拿铁", "雪碧", "美式", "茶")


def _utility_for(name: str, category: str = "") -> Tuple[float, str]:
    """返回 (效用系数, 依据说明)。

    ⚠ 特判：**组合 / 套餐**里的饮料词条不算数。
    "16.9元麦辣可乐组合" 是一份汉堡+一杯可乐，按"可乐 0.25"算会把整份套餐严重低估。
    """
    is_combo = any(k in name for k in ("组合", "套餐", "全家桶", "任选", "件套", "份"))
    for key, val in NAME_UTILITY.items():
        if not key or key not in name:
            continue
        if is_combo and any(b in key for b in _BEVERAGES):
            continue          # 组合里的饮料不单独计价，继续找下一个更贴切的词条
        return val, f"品名命中「{key}」"
    for key, val in CATEGORY_UTILITY.items():
        if key and (key in (category or "") or key in name):
            return val, f"品类「{key}」"
    return DEFAULT_UTILITY, "默认系数"


# --------------------------------------------------------------------------- #
# 参考价：从商品名 / 菜单反推单价
# --------------------------------------------------------------------------- #

def _normalize(text: str) -> str:
    """去掉括号补充说明与空白，便于商品匹配。"""
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"\s+", "", text or "")


def reference_price(item: str) -> float:
    """查参考价表。

    多词条同时命中时，取**在名称里出现得最早**的（"甜辣小食组合" 里的"甜辣"
    才是主料，"小食"只是搭配）；位置相同时取更长的词条。
    """
    norm = _normalize(item)
    if not norm:
        return 0.0
    best: Optional[Tuple[int, int, float]] = None   # (位置, -长度, 价格)
    for name, price in REFERENCE_PRICES.items():
        base = _normalize(name)
        if not base:
            continue
        pos = norm.find(base)
        if pos < 0:
            continue
        key = (pos, -len(base), price)
        if best is None or key < best:
            best = key
    return best[2] if best else 0.0


def menu_lookup(text: str, price_map: Dict[str, float]) -> Optional[Tuple[str, float]]:
    """在价格表里找出券名/奖品名里提到的商品。

    同样按「出现位置最早优先，长度次之」挑选，避免"甜辣小食组合"被"小食"抢走。
    """
    norm = _normalize(text)
    best: Optional[Tuple[int, int, str, float]] = None
    for item_name, price in price_map.items():
        if price <= 0:
            continue
        base = _normalize(item_name)
        if not base:
            continue
        pos = norm.find(base)
        if pos < 0:
            continue
        key = (pos, -len(base), base, price)
        if best is None or key < best:
            best = key
    return (best[2], best[3]) if best else None


def _multiplier(name: str) -> float:
    """从名称里解析份数："三件套" → 3，"2份" → 2。

    ⚠ 顺序敏感：必须先判"四件套"，否则正则 ``[三四]件套`` 会把"四"也匹配成 3。
    """
    if "四件套" in name:
        return 4.0
    if "三件套" in name:
        return 3.0
    if "两件套" in name or "2份" in name:
        return 2.0
    if re.search(r"\d+份", name):
        m = re.search(r"(\d+)份", name)
        if m:
            return float(m.group(1))
    return 1.0


# --------------------------------------------------------------------------- #
# 优惠券面值估算
# --------------------------------------------------------------------------- #

_RE_FULL_OFF = re.compile(r"满\s*\d+(?:\.\d+)?\s*减\s*(\d+(?:\.\d+)?)")
_RE_OFF = re.compile(r"(?:减|立减|直降|省)\s*(\d+(?:\.\d+)?)\s*元?")
_RE_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*元")
_RE_BUY1GET1 = re.compile(r"买\s*一\s*送\s*一|买1送1|第二份免费")
_RE_HALF = re.compile(r"半价")
_RE_FREE = re.compile(r"免费|免单|0元")
_RE_RMB_PREFIX = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*元\s*(.+)$")


def estimate_coupon_value(coupon: Coupon, price_map: Dict[str, float],
                           utility: float = 1.0) -> Tuple[float, str]:
    """估算一张券的实际价值（元）与依据。

    ``utility`` 对"已持有的券"默认为 1.0（不用就作废，真实价值≈面值），
    对"还没领的券"默认 0.85（要花点时间去用）。
    """
    name = coupon.name or ""

    # "21.9元巨无霸可乐组合" —— 麦当劳券名的主要形态，直接就是面值
    m = _RE_RMB_PREFIX.match(name)
    if m:
        return float(m.group(1)) * utility, f"券面额 {m.group(1)} 元（{m.group(2)}）"

    m = _RE_FULL_OFF.search(name)
    if m:
        return float(m.group(1)) * utility, f"满减券：直减 {m.group(1)} 元"

    if _RE_BUY1GET1.search(name):
        hit = menu_lookup(name, price_map)
        if hit:
            return hit[1] * utility, f"买一送一：{hit[0]} 单价 {hit[1]:g} 元"
        return 15.0 * utility, "买一送一：按常见单品 15 元估算"

    if _RE_HALF.search(name):
        hit = menu_lookup(name, price_map)
        if hit:
            return hit[1] * 0.5 * utility, f"第二份半价：{hit[0]} {hit[1]:g} 元 × 50%"
        return 18.0 * 0.5 * utility, "第二份半价：按常见单品 18 元估算"

    if _RE_FREE.search(name):
        hit = menu_lookup(name, price_map)
        if hit:
            return hit[1] * utility, f"免费券：{hit[0]} 单价 {hit[1]:g} 元"
        ref = reference_price(name)
        if ref:
            return ref * utility, f"免费券：参考价 {ref:g} 元"
        return 10.0 * utility, "免费券：按常见单品 10 元保守估算"

    m = _RE_OFF.search(name)
    if m:
        return float(m.group(1)) * utility, f"立减/减额券：{m.group(1)} 元"

    m = _RE_AMOUNT.search(name)
    if m:
        return float(m.group(1)) * utility, f"代金券：面额 {m.group(1)} 元"

    hit = menu_lookup(name, price_map)
    if hit:
        return hit[1] * utility, f"兑换券：{hit[0]} 单价 {hit[1]:g} 元"

    ref = reference_price(name)
    if ref:
        return ref * utility, f"参考价 {ref:g} 元"

    return 10.0 * utility, "无法从券名解析，按常见单品 10 元保守估算"


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
    skipped: int = 0


def infer_point_rate(products: Sequence[MallProduct], fallback: float = 0.04) -> PointRate:
    """从麦麦商城的「面值 ÷ 积分价」反推积分汇率。

    只用**仍在架上**且积分价 > 0 的商品做样本，取中位数，避免促销品与下架品拉偏。
    """
    today = date.today()
    pairs: List[Tuple[float, str]] = []
    skipped = 0
    for p in products:
        if p.points_price <= 0:
            skipped += 1
            continue
        if not p.is_on_sale(today):
            skipped += 1
            continue
        if p.cash_price <= 0:
            skipped += 1
            continue
        pairs.append((p.cash_price / p.points_price, p.name))

    if not pairs:
        return PointRate(nominal=fallback, effective=fallback,
                         basis=f"无可用样本，采用默认口径 {fallback:g} 元/积分", skipped=skipped)

    rates = sorted(r for r, _ in pairs)
    median = rates[len(rates) // 2]
    best = max(pairs, key=lambda x: x[0])
    return PointRate(
        nominal=median,
        effective=median,
        basis=f"由 {len(pairs)} 件在架商品的「面值 ÷ 积分价」取中位数",
        samples=len(pairs),
        best_product=best[1],
        skipped=skipped,
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
    probability_source: str = "官方未公布概率，按等概率假设"
    lines: List[str] = field(default_factory=list)
    warning: str = ""


def _prize_value(name: str, price_map: Dict[str, float], point_rate: float) -> Tuple[float, str]:
    """估算一个奖品/券的面值（元）。"""
    face = price_from_name(name)
    if face > 0:
        return face, f"券面额 {face:g} 元"

    disc = discount_from_name(name)
    if disc > 0:
        hit = menu_lookup(name, price_map)
        if hit:
            base = hit[1] * _multiplier(name)
            return base * disc, f"{hit[0]} {base:g} 元 × {disc * 10:g} 折"
        ref = reference_price(name)
        if ref:
            base = ref * _multiplier(name)
            return base * disc, f"参考价 {ref:g} 元 × {disc * 10:g} 折"
        return 0.0, "折扣券但无价格基准，按 0 计"

    pts = points_from_name(name)
    if pts > 0:
        return pts * point_rate, f"{pts:g} 积分 × {point_rate:.4f} 元/分"

    hit = menu_lookup(name, price_map)
    if hit:
        return hit[1], f"{hit[0]} 单价 {hit[1]:g} 元"

    ref = reference_price(name)
    if ref:
        return ref, f"参考价 {ref:g} 元"

    return 0.0, "无法估值"


def lottery_expected_value(lottery: Optional[LotteryInfo], price_map: Dict[str, float],
                            point_rate: float = 0.04) -> LotteryEV:
    """计算抽奖的期望值、方差与"颗粒无收"概率。

    ⚠ 官方**不返回**中奖概率，这里默认按等概率假设，并在结果中明确标注。
       真实分布通常远不均匀（大奖稀有），因此该期望值是**上界估计**。
    """
    if lottery is None or not lottery.prizes:
        return LotteryEV(available=False, warning="当前账号未开放积分抽奖活动")

    prob_source = "官方未公布概率，按等概率假设（结果偏乐观）"
    total_p = sum(p.probability or 0.0 for p in lottery.prizes)
    if total_p <= 0:
        stocks = [float(p.raw.get("stock", 0) or 0) for p in lottery.prizes]
        tot = sum(stocks)
        if tot > 0:
            for p, s in zip(lottery.prizes, stocks):
                p.probability = s / tot
            prob_source = "官方未公布概率，按奖品库存占比推断"
        else:
            n = len(lottery.prizes)
            for p in lottery.prizes:
                p.probability = 1.0 / n
    else:
        prob_source = "使用接口返回的中奖概率"

    ev = 0.0
    ev2 = 0.0
    lose = 0.0
    lines: List[str] = []
    best_name, best_prob, best_val = "", 0.0, 0.0

    for p in lottery.prizes:
        prob = float(p.probability or 0.0)
        util, _ = _utility_for(p.name, "")
        face, why = _prize_value(p.name, price_map, point_rate)
        p.value_cny = face
        p.value_reason = why
        value = face * util
        contrib = prob * value
        ev += contrib
        ev2 += prob * (value ** 2)
        if value <= 0:
            lose += prob
        if prob > best_prob:
            best_name, best_prob, best_val = p.name, prob, value
        lines.append(
            f"  {p.name:<18} 概率 {prob * 100:5.1f}%  面值 {face:>6g} 元  效用 {util:.2f}  贡献 {contrib:>6.2f} 元"
        )

    stdev = math.sqrt(max(ev2 - ev * ev, 0.0))
    cost = lottery.cost_points or 0

    warn = ""
    if lottery.eligible is False:
        warn = f"当前账户无法参与抽奖：{lottery.ineligible_reason or '接口未说明原因'}"
    elif "等概率" in prob_source:
        warn = "官方未公开中奖概率，等概率假设会**高估**期望值（真实分布中大奖通常更稀有）"

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
        probability_source=prob_source,
        lines=lines,
        warning=warn,
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
    skipped_off_sale: int = 0


def knapsack_redeem(products: Sequence[MallProduct], capacity: int,
                    max_slots: int = 4000) -> RedeemResult:
    """在积分上限内，用 0/1 背包挑出效用价值最高的商品组合。

    每个商品最多兑换一件；**已下架商品直接排除**（官方只给 downTime，不给库存）。
    积分按粒度离散化，控制状态空间规模。
    """
    if capacity <= 0:
        return RedeemResult()

    today = date.today()
    cand: List[RedeemItem] = []
    skipped = 0
    for p in products:
        if p.points_price <= 0:
            skipped += 1
            continue
        if not p.is_on_sale(today):
            skipped += 1
            continue
        value, reason = product_utility_value(p)
        if value <= 0:
            skipped += 1
            continue
        cand.append(RedeemItem(product=p, points=p.points_price, value_cny=value, reason=reason))
    if not cand:
        return RedeemResult(leftovers=capacity, skipped_off_sale=skipped)

    min_price = min(c.points for c in cand)
    gran = max(1, min(min_price, math.ceil(capacity / max_slots)))
    cap = capacity // gran

    n = len(cand)
    weights = [max(1, round(c.points / gran)) for c in cand]
    values = [c.value_cny for c in cand]

    dp = [0.0] * (cap + 1)
    take = [[False] * n for _ in range(cap + 1)]
    for i in range(n):
        w, v = weights[i], values[i]
        for j in range(cap, w - 1, -1):
            cand_val = dp[j - w] + v
            if cand_val > dp[j] + 1e-9:
                dp[j] = cand_val
                take[j][i] = True

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

    res = RedeemResult(skipped_off_sale=skipped)
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
    kind: str          # points | coupon | expired
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

    # 价格表：真实菜单价优先，参考价表兜底。
    # ⚠ 绝不能把「券面额」（"11.9元麦辣鸡腿堡"）混进单价表 ——
    #   那样会把"麦辣鸡腿堡买一送一"这种券的价值从 21 元算成 11.9 元。
    price_map: Dict[str, float] = dict(REFERENCE_PRICES)
    price_map.update(snapshot.menu_price_map)

    # ---- 1. 券：0 成本收益，先算 -------------------------------------- #
    held_value = 0.0
    for c in snapshot.my_coupons:
        v, why = estimate_coupon_value(c, price_map, utility=1.0)
        c.est_value_cny = v
        c.value_reason = why
        held_value += v
        plan.expiry_alerts.append(ExpiryAlert(
            kind="coupon", label=c.name, value_cny=v,
            days_left=c.days_left(today), action=why,
        ))

    claim_value = 0.0
    for c in snapshot.claimable_coupons:
        v, why = estimate_coupon_value(c, price_map, utility=default_utility)
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
            + "、".join(f"{a.label}（{a.days_left} 天后失效，约 {a.value_cny:.0f} 元）" for a in urgent[:3])
        )
    if held_value:
        plan.free_actions.append(
            f"账户内已持有的券合计面值约 {held_value:.0f} 元，{len(snapshot.my_coupons)} 张，优先使用"
        )

    # ---- 2. 汇率与抽奖 ------------------------------------------------- #
    plan.rate = infer_point_rate(snapshot.mall_products)
    plan.lottery = lottery_expected_value(snapshot.lottery, price_map, plan.rate.nominal)
    plan.account_total = snapshot.account.available

    if plan.rate.skipped:
        plan.notes.append(
            f"商城共 {len(snapshot.mall_products)} 件商品，{plan.rate.skipped} 件因下架/非积分兑换/"
            f"缺面值被排除，实际参与汇率计算的样本 {plan.rate.samples} 件"
        )
    if plan.lottery.available and plan.lottery.cost_points > 0 and plan.rate.nominal > 0:
        ratio = plan.lottery.rate_per_point / plan.rate.nominal
        if ratio >= 1.0:
            plan.notes.append(
                f"抽奖每积分期望 {plan.lottery.rate_per_point:.4f} 元，是兑换汇率 "
                f"({plan.rate.nominal:.4f} 元/分) 的 {ratio:.1f} 倍 —— 但方差大、奖品未必是你想吃的。"
            )
        else:
            plan.notes.append(
                f"抽奖每积分期望 {plan.lottery.rate_per_point:.4f} 元，低于兑换汇率 "
                f"({plan.rate.nominal:.4f} 元/分)，抽奖不划算。"
            )
    if plan.lottery.warning:
        plan.notes.append(plan.lottery.warning)

    # ---- 3. 积分到期预警 ----------------------------------------------- #
    for b in snapshot.account.expiring:
        plan.expiry_alerts.append(ExpiryAlert(
            kind="points",
            label=b.label or "即将过期积分",
            points=b.points,
            days_left=b.days_left(today),
            value_cny=b.points * plan.rate.nominal,
        ))
    if snapshot.account.expired > 0:
        plan.expiry_alerts.append(ExpiryAlert(
            kind="expired",
            label="已经过期的积分",
            points=snapshot.account.expired,
            days_left=0,
            value_cny=snapshot.account.expired * plan.rate.nominal,
            action="已无法挽回 —— 下次记得在到期前用掉",
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

    # ---- 5. 推荐 -------------------------------------------------------- #
    if total_points <= 0:
        # 没有可用积分时，"该抽还是该换"是个伪问题 —— 唯一能立刻变现的是 0 成本的券
        plan.recommended = steady
        plan.recommendation_reason = (
            f"你当前**没有可用积分**，所以「抽还是换」暂时不成立。"
            f"眼下能立刻变现的是约 {plan.free_value:.0f} 元的零成本券"
            f"（{len(snapshot.claimable_coupons)} 张待领 + {len(snapshot.my_coupons)} 张已持有）"
            f"；同时你的 {snapshot.account.expired} 积分已经过期，"
            f"下次记得在到期前用掉 —— 积分是靠下单和活动攒的，不是靠等。"
        )
    elif expiring_points > 0 and plan.lottery.available and cost > 0:
        plan.recommended = balanced
        plan.recommendation_reason = (
            f"你有 {expiring_points} 积分将在 {horizon_days} 天内过期，机会成本为零 —— "
            f"抽奖的每积分期望值（{plan.lottery.rate_per_point:.4f} 元）是兑换汇率"
            f"（{plan.rate.nominal:.4f} 元）的 "
            f"{plan.lottery.rate_per_point / plan.rate.nominal:.1f} 倍，"
            f"所以「到期就抽、长期就换」是期望值最高且风险可控的组合。"
        )
    elif plan.lottery.available and cost > 0 and plan.rate.nominal > 0 \
            and plan.lottery.rate_per_point > plan.rate.nominal:
        plan.recommended = aggressive
        plan.recommendation_reason = (
            f"抽奖每积分期望值（{plan.lottery.rate_per_point:.4f} 元）高于兑换汇率"
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
        lose_txt = (f"颗粒无收概率 {route.all_lose_prob * 100:.0f}%"
                    if plan.lottery.lose_prob > 0 else "颗粒无收概率未知（官方未公布概率）")
        steps.append(
            f"用 {route.draw_points} 积分抽奖 {route.draws} 次"
            f"（期望 {route.draws * plan.lottery.per_draw_cny:.1f} 元，{lose_txt}）"
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
