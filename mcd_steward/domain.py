"""数据模型：把麦当劳 MCP Server 的真实返回结构归一化成可计算的对象。

真实结构备忘（2026-10 实测，open.mcd.cn/mcp）
--------------------------------------------
``query-my-account``
    {"availablePoint":"1240","accumulativePoint":"5860","frozenPoint":"0",
     "usedPoint":"0","expiredPoint":"143.3",
     "currentMouthExpirePoint":"240","nextMouthExpirePoint":"100", ...}
    ⚠ 官方把 Month 拼成了 **Mouth**（currentMouthExpirePoint / nextMouthExpirePoint），
      别名表里必须同时收这两种写法。

``query-my-coupons``
    {"coupons":[...],"totalCount":0,"currentPage":1,"pageSize":200,"totalPages":0}

``available-coupons``
    [{"couponName":"11.9元麦辣鸡腿堡","couponImage":"...","couponStatus":"CAN_GET","label":"可领取"}]

``mall-points-products``
    [{"spuName":"21.9元巨无霸可乐组合","spuId":1234,"point":"800","price":"0",
      "catName":"到店专用","status":2,"upTime":"...","downTime":"2026-12-30 23:59:59"}]
    ⚠ ``price`` 对商品券恒为 0，**真实面值藏在 spuName 里**（"21.9元…"）；
      ⚠ ``downTime`` 早于当前时间的商品已下架，必须过滤，否则会推荐买不到的东西；
      ⚠ ``point`` 为 0 的是派对/读书会等体验类，不是积分兑换物。

``query-lottery-info``
    {"activityName":"麦麦积分抽奖","drawPoint":"24","availablePoint":"1240",
     "drawDecision":{"resourceEligible":true,"reason":"","nextConsumption":{...}},
     "prizes":[{"name":"下单立减3元券","typeText":"优惠券","imageUrl":"..."}]}
    ⚠ 奖品**不返回中奖概率，也不返回面值** —— 概率只能等分假设并明确标注，
      面值必须从奖品名里解析。

``query-meals``  需要 storeCode + beType + orderType，必须先经
``query-nearby-stores`` 拿到门店。

设计原则
--------
1. 每一处解析都走 ``_alias``（多候选键名 + 别名表），官方字段改名不会让项目崩掉。
2. 解析失败的项不会被静默丢弃，而是计数并在报告里提示。
3. 所有金额一律用「元」的 float 表达，积分数一律用 int。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

_ONE_DAY = timedelta(days=1)

# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

#: 候选键名表：标准名 -> 候选键名（小驼峰 / 下划线 / 中文）
_ALIASES: Dict[str, Sequence[str]] = {
    "id": ("id", "couponId", "coupon_id", "spuId", "spu_id", "productId", "product_id",
           "prizeId", "recordId", "code"),
    "name": ("name", "title", "couponName", "spuName", "productName", "prizeName",
             "goodsName", "activityName", "desc", "description"),
    "points": ("point", "points", "pointPrice", "point_price", "costPoints", "cost_points",
               "drawPoint", "积分", "积分价格", "needPoints", "exchangePoints"),
    "cash": ("price", "cash", "cashPrice", "cash_price", "amount", "money", "originalPrice",
             "售价", "现金价", "marketPrice"),
    "stock": ("stock", "quantity", "remain", "inventory", "total", "totalStock", "剩余库存"),
    "expire": ("downTime", "expireDate", "expire_date", "expireTime", "expire", "validUntil",
               "endTime", "end_date", "有效期", "过期时间", "expireAt", "endDate"),
    "effective": ("upTime", "effectiveDate", "effective_date", "startTime", "beginTime", "生效时间"),
    "value": ("value", "valueCny", "value_cny", "faceValue", "face_value", "面值", "金额"),
    "probability": ("probability", "prob", "rate", "chance", "odds", "中奖概率", "概率"),
    "weight": ("weight", "stockWeight", "w"),
    "cost": ("drawPoint", "cost", "costPoints", "cost_points", "consumePoints", "consume",
             "消耗积分", "每次消耗"),
    "prizes": ("prizes", "prizeList", "awardList", "prize_list", "奖品列表", "奖品", "awards"),
    "rules": ("drawTypeText", "rules", "rule", "description", "desc", "说明", "consumeRule",
              "消耗规则"),
    "category": ("catName", "category", "cat", "type", "分类", "类目"),
    "items": ("coupons", "items", "list", "records", "rows", "data", "content", "列表", "明细",
              "spuList", "productList"),
    "available": ("availablePoint", "available", "usable", "current", "可用积分", "可用"),
    "total_earned": ("accumulativePoint", "accumulative", "totalEarned", "total_earned",
                     "accumulated", "累计积分", "累计"),
    "frozen": ("frozenPoint", "frozen", "locked", "冻结积分", "冻结"),
    "expired": ("expiredPoint", "expired", "已过期积分", "已过期"),
    "used": ("usedPoint", "used", "usedPoints", "已使用积分", "已使用"),
    "expiring": ("currentMouthExpirePoint", "nextMouthExpirePoint", "expiring",
                 "expiringPoints", "expiring_points", "expireSoon", "即将过期积分",
                 "willExpire", "expiringPointsDetail", "expiring_detail"),
    "points_amount": ("point", "points", "pointAmount", "point_amount", "expirePoints",
                      "积分", "积分数", "积分数量", "即将过期积分"),
    "status": ("couponStatus", "status", "state"),
    "label": ("label", "tag"),
}

#: 从商品名里解析「21.9元」这类面值
_RE_PRICE_IN_NAME = re.compile(r"(\d+(?:\.\d+)?)\s*元")
#: 从商品名里解析「5折」「5.5折」
_RE_DISCOUNT_IN_NAME = re.compile(r"(\d+(?:\.\d+)?)\s*折")
#: 从商品名里解析「30积分」
_RE_POINTS_IN_NAME = re.compile(r"(\d+(?:\.\d+)?)\s*积分")


def _alias(obj: Any, name: str, default: Any = None) -> Any:
    """按 ``_ALIASES`` 别名表取值。"""
    if not isinstance(obj, dict):
        return default
    for k in _ALIASES.get(name, (name,)):
        if k in obj and obj[k] is not None:
            return obj[k]
    return default


def _as_int(v: Any, default: int = 0) -> int:
    """尽最大努力把任意值转成 int，失败返回 default。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v))
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    if not m:
        return default
    try:
        return int(round(float(m.group(0))))
    except ValueError:
        return default


def _as_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    if not m:
        return default
    try:
        return float(m.group(0))
    except ValueError:
        return default


def _as_date(v: Any) -> Optional[date]:
    """解析多种常见日期格式，返回 date。"""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("年", "-").replace("月", "-").replace("日", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d",
                "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s[: len(fmt) + 6].strip(), fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def business_error(payload: Any) -> Optional[str]:
    """识别麦当劳接口的**业务错误**约定。

    官方在业务失败时不是抛 MCP 错误，而是返回
    ``{"success": false, "code": 600050, "message": "收藏餐厅列表为空…"}``。
    不识别这种结构，就会把错误当成"查到了但没数据"，静默丢信息。
    """
    if isinstance(payload, dict) and payload.get("success") is False:
        code = payload.get("code", "?")
        msg = payload.get("message", "未知业务错误")
        return f"[{code}] {msg}"
    return None


def _to_items(payload: Any) -> List[Dict[str, Any]]:
    """把 MCP 工具返回体规整成 list[dict]。

    兼容四种形态：直接 list / dict 含列表键 / dict 被包了一层 / 单条 dict。
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in _ALIASES["items"]:
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return _to_items(v)
        dict_vals = [v for v in payload.values() if isinstance(v, dict)]
        if len(dict_vals) == 1:
            return _to_items(dict_vals[0])
        return [payload]
    return []


def price_from_name(name: str) -> float:
    """从商品 / 券名里解析面值。

    麦当劳商城与券的名称里带价格（"21.9元巨无霸可乐组合"、"下单立减3元券"），
    而接口的 ``price`` 字段对商品券恒为 0 —— 所以价值只能从名字里取。
    """
    if not name:
        return 0.0
    m = _RE_PRICE_IN_NAME.search(name)
    return float(m.group(1)) if m else 0.0


def discount_from_name(name: str) -> float:
    """从名称里解析折扣（"麦辣三件套5折券" → 0.5）。没有则返回 0。"""
    if not name:
        return 0.0
    m = _RE_DISCOUNT_IN_NAME.search(name)
    if m:
        d = float(m.group(1))
        if 0 < d <= 10:
            return d / 10.0
    return 0.0


def points_from_name(name: str) -> float:
    """从名称里解析积分数（"30积分" → 30.0）。"""
    if not name:
        return 0.0
    m = _RE_POINTS_IN_NAME.search(name)
    return float(m.group(1)) if m else 0.0


# --------------------------------------------------------------------------- #
# 领域模型
# --------------------------------------------------------------------------- #

@dataclass
class ExpiringBucket:
    """一批即将过期的积分。"""
    points: int
    expire_date: Optional[date] = None
    label: str = ""

    def days_left(self, today: Optional[date] = None) -> int:
        if self.expire_date is None:
            return 9999
        return (self.expire_date - (today or date.today())).days


@dataclass
class PointsAccount:
    """积分账户快照。"""
    available: int = 0
    total_earned: int = 0
    frozen: int = 0
    used: int = 0
    expired: int = 0
    expiring: List[ExpiringBucket] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def expiring_total(self) -> int:
        return sum(b.points for b in self.expiring)

    def expiring_within(self, days: int, today: Optional[date] = None) -> List[ExpiringBucket]:
        return [b for b in self.expiring if 0 <= b.days_left(today) <= days]


@dataclass
class Coupon:
    """一张优惠券。"""
    coupon_id: str
    name: str
    expire_date: Optional[date] = None
    claimed: bool = False
    est_value_cny: float = 0.0
    value_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def days_left(self, today: Optional[date] = None) -> int:
        if self.expire_date is None:
            return 9999
        return (self.expire_date - (today or date.today())).days


@dataclass
class MallProduct:
    """麦麦商城可兑换商品。"""
    product_id: str
    name: str
    points_price: int = 0
    cash_price: float = 0.0
    stock: int = -1
    category: str = ""
    valid_until: Optional[date] = None
    est_value_cny: float = 0.0
    value_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_on_sale(self, today: Optional[date] = None) -> bool:
        """是否仍在架上。接口不返回库存，只返回上下架时间。"""
        if self.valid_until is None:
            return True
        return self.valid_until >= (today or date.today())


@dataclass
class LotteryPrize:
    """一个奖品。"""
    name: str
    value_cny: float = 0.0
    probability: Optional[float] = None   # 0~1，官方不返回时为 None
    value_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LotteryInfo:
    """积分抽奖活动。"""
    name: str
    cost_points: int = 0
    prizes: List[LotteryPrize] = field(default_factory=list)
    rules: str = ""
    eligible: Optional[bool] = None
    ineligible_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_probability(self) -> float:
        return sum(p.probability or 0.0 for p in self.prizes)


@dataclass
class MealPrice:
    """菜单项，用于给"免费券"估算面值。"""
    name: str
    price_cny: float = 0.0
    calories: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class McSnapshot:
    """一次体检的完整输入快照。"""
    account: PointsAccount = field(default_factory=PointsAccount)
    my_coupons: List[Coupon] = field(default_factory=list)
    claimable_coupons: List[Coupon] = field(default_factory=list)
    mall_products: List[MallProduct] = field(default_factory=list)
    lottery: Optional[LotteryInfo] = None
    menu: List[MealPrice] = field(default_factory=list)
    store_name: str = ""
    unparsed: int = 0
    notes: List[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def menu_price_map(self) -> Dict[str, float]:
        return {m.name: m.price_cny for m in self.menu if m.price_cny > 0}


# --------------------------------------------------------------------------- #
# 日期辅助
# --------------------------------------------------------------------------- #

def month_end(today: Optional[date] = None) -> date:
    """当月最后一天。"""
    today = today or date.today()
    if today.month == 12:
        return date(today.year, 12, 31)
    return date(today.year, today.month + 1, 1) - _ONE_DAY


def month_end_next(today: Optional[date] = None) -> date:
    """下月最后一天。"""
    today = today or date.today()
    return month_end(month_end(today) + _ONE_DAY)


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #

def parse_account(payload: Any) -> PointsAccount:
    """解析 ``query-my-account``。

    真实返回是一个扁平对象；``currentMouthExpirePoint`` / ``nextMouthExpirePoint``
    分别是本月、下月即将过期的积分数（官方把 Month 拼成了 Mouth）。
    """
    acc = PointsAccount(raw=payload if isinstance(payload, dict) else {})
    if not isinstance(payload, dict):
        return acc

    acc.available = _as_int(_alias(payload, "available"))
    acc.total_earned = _as_int(_alias(payload, "total_earned"))
    acc.frozen = _as_int(_alias(payload, "frozen"))
    acc.used = _as_int(_alias(payload, "used"))
    acc.expired = _as_int(_alias(payload, "expired"))

    today = date.today()
    this_month = _as_int(payload.get("currentMouthExpirePoint"))
    next_month = _as_int(payload.get("nextMouthExpirePoint"))
    if this_month:
        acc.expiring.append(ExpiringBucket(
            points=this_month, expire_date=month_end(today),
            label="本月底到期积分"))
    if next_month:
        acc.expiring.append(ExpiringBucket(
            points=next_month, expire_date=month_end_next(today),
            label="下月底到期积分"))

    # 兜底：某些版本可能直接给 expiring 列表
    if not acc.expiring:
        exp = _alias(payload, "expiring")
        if exp is not None:
            acc.expiring = _parse_expiring(exp)
    return acc


def _parse_expiring(payload: Any) -> List[ExpiringBucket]:
    """解析即将过期积分结构（可能是 int、list[dict] 或 dict）。"""
    buckets: List[ExpiringBucket] = []
    if payload is None:
        return buckets
    if isinstance(payload, (int, float)):
        return [ExpiringBucket(points=_as_int(payload))]
    if isinstance(payload, dict):
        pts = _as_int(_alias(payload, "points_amount"))
        if pts or "expire" in payload:
            buckets.append(ExpiringBucket(
                points=pts,
                expire_date=_as_date(_alias(payload, "expire")),
                label=str(_alias(payload, "name", default="") or ""),
            ))
        for key in ("items", "list", "details", "records"):
            if key in payload:
                return _parse_expiring(payload[key])
        return buckets
    if isinstance(payload, list):
        for it in payload:
            if isinstance(it, dict):
                buckets.append(ExpiringBucket(
                    points=_as_int(_alias(it, "points_amount")),
                    expire_date=_as_date(_alias(it, "expire")),
                    label=str(_alias(it, "name", default="") or ""),
                ))
            elif isinstance(it, (int, float)):
                buckets.append(ExpiringBucket(points=_as_int(it)))
    return buckets


def parse_coupons(payload: Any, claimed: bool = False) -> List[Coupon]:
    """解析 ``query-my-coupons`` / ``available-coupons``。"""
    out: List[Coupon] = []
    for i, it in enumerate(_to_items(payload)):
        name = str(_alias(it, "name", default="") or "")
        if not name:
            continue
        out.append(Coupon(
            coupon_id=str(_alias(it, "id", default=f"coupon-{i}")),
            name=name,
            expire_date=_as_date(_alias(it, "expire")),
            claimed=claimed,
            raw=it,
        ))
    return out


def parse_mall_products(payload: Any) -> List[MallProduct]:
    """解析 ``mall-points-products``。

    真实结构里 ``price`` 对商品券恒为 0，真实面值藏在 ``spuName``（"21.9元…"），
    这里两者都取，``cash_price`` 优先用名称解析出来的价格。
    """
    out: List[MallProduct] = []
    for i, it in enumerate(_to_items(payload)):
        name = str(_alias(it, "name", default="") or "")
        if not name:
            continue
        cash = _as_float(_alias(it, "cash"))
        name_price = price_from_name(name)
        if cash <= 0 and name_price > 0:
            cash = name_price
        out.append(MallProduct(
            product_id=str(_alias(it, "id", default=f"prod-{i}")),
            name=name,
            points_price=_as_int(_alias(it, "points")),
            cash_price=cash,
            stock=_as_int(_alias(it, "stock"), default=-1),
            category=str(_alias(it, "category", default="") or ""),
            valid_until=_as_date(_alias(it, "expire")),
            raw=it,
        ))
    return out


def parse_lottery(payload: Any) -> Optional[LotteryInfo]:
    """解析 ``query-lottery-info``。

    ⚠ 官方**不返回**中奖概率，也不返回奖品面值 —— 概率只能等分假设（并在报告中标注），
    面值必须从奖品名里解析（"下单立减3元券" → 3 元，"麦辣三件套5折券" → 5 折）。
    """
    if payload is None:
        return None
    root = payload if isinstance(payload, dict) else {}
    if not root:
        return None

    decision = root.get("drawDecision") if isinstance(root.get("drawDecision"), dict) else {}
    info = LotteryInfo(
        name=str(root.get("activityName") or _alias(root, "name", default="") or "积分抽奖"),
        cost_points=_as_int(root.get("drawPoint") or _alias(root, "cost")),
        rules=str(root.get("drawTypeText") or _alias(root, "rules", default="") or ""),
        eligible=decision.get("resourceEligible"),
        ineligible_reason=str(decision.get("reason") or ""),
        raw=root,
    )

    for it in _to_items(root.get("prizes")):
        pname = str(_alias(it, "name", default="") or "")
        if not pname:
            continue
        prob = _alias(it, "probability")
        info.prizes.append(LotteryPrize(
            name=pname,
            value_cny=price_from_name(pname),
            probability=(float(_as_float(prob)) if prob is not None else None),
            raw=it,
        ))
    if not info.prizes:
        return None
    return info


def parse_menu(payload: Any) -> List[MealPrice]:
    """解析 ``query-meals`` / ``list-nutrition-foods``，用于给券估值。"""
    out: List[MealPrice] = []
    for it in _to_items(payload):
        name = str(_alias(it, "name", default="") or "")
        if not name:
            continue
        out.append(MealPrice(
            name=name,
            price_cny=_as_float(_alias(it, "cash"), default=0.0),
            calories=_as_float(it.get("calories"), default=0.0),
            raw=it,
        ))
    return out
