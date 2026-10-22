"""数据模型：把 MCP 返回的原始 JSON 归一化成可计算的结构。

设计原则
--------
1. 官方接口字段名可能随版本变动，因此每一处解析都走 ``_pick``（多候选键名 + 别名），
   单一字段改名不会让整个项目崩掉。
2. 解析失败的项不会静默丢弃，而是进入 ``unparsed`` 计数并在报告里提示，
   避免"看起来算得很准其实漏了一半数据"。
3. 所有金额一律用「元」的 float 表达，积分数一律用 int。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

# 常见的字段别名，键为标准名，值为候选键名（小驼峰 / 下划线 / 中文）
_ALIASES: Dict[str, Sequence[str]] = {
    "id": ("id", "couponId", "coupon_id", "productId", "product_id", "prizeId", "recordId"),
    "name": ("name", "title", "couponName", "productName", "prizeName", "goodsName", "desc", "description"),
    "points": ("points", "point", "pointPrice", "point_price", "costPoints", "cost_points",
               "积分", "积分价格", "needPoints", "exchangePoints"),
    "cash": ("cash", "cashPrice", "cash_price", "price", "amount", "money", "originalPrice",
             "售价", "现金价", "marketPrice"),
    "stock": ("stock", "quantity", "remain", "inventory", "total", "totalStock", "剩余库存"),
    "expire": ("expireDate", "expire_date", "expireTime", "expire", "validUntil", "endTime",
               "end_date", "有效期", "过期时间", "expireAt"),
    "effective": ("effectiveDate", "effective_date", "startTime", "startTime", "beginTime", "生效时间"),
    "value": ("value", "valueCny", "value_cny", "faceValue", "face_value", "amount", "面值", "金额"),
    "points_amount": ("points", "point", "pointAmount", "point_amount", "expirePoints",
                      "积分", "积分数", "积分数量", "即将过期积分"),
    "probability": ("probability", "prob", "rate", "chance", "odds", "中奖概率", "概率"),
    "weight": ("weight", "stockWeight", "w"),
    "cost": ("cost", "costPoints", "cost_points", "consumePoints", "consume", "消耗积分", "每次消耗"),
    "prizes": ("prizes", "prizeList", "awardList", "prize_list", "奖品列表", "奖品", "awards"),
    "rules": ("rules", "rule", "description", "desc", "说明", "consumeRule", "消耗规则"),
    "category": ("category", "cat", "type", "分类", "类目"),
    "stock_total": ("totalStock", "total_stock", "poolSize", "pool_size", "奖池总量"),
    "items": ("items", "list", "records", "rows", "data", "content", "列表", "明细"),
    "available": ("available", "usable", "current", "可用积分", "可用"),
    "total_earned": ("totalEarned", "total_earned", "accumulated", "累计积分", "累计"),
    "frozen": ("frozen", "locked", "冻结积分", "冻结"),
    "expiring": ("expiring", "expiringPoints", "expiring_points", "expireSoon", "即将过期积分",
                 "expired", "willExpire", "expiringPointsDetail", "expiring_detail"),
    "used": ("used", "usedPoints", "已使用积分", "已使用"),
    "source": ("source", "type", "来源"),
    "reason": ("reason", "desc", "remark", "说明"),
    "action": ("action", "actionType", "type", "动作"),
}


def _pick(obj: Any, *keys: str, default: Any = None) -> Any:
    """在 dict 中按顺序取第一个存在且非 None 的键。"""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return default


def _alias(obj: Any, name: str, default: Any = None) -> Any:
    """按 ``_ALIASES`` 别名表取值。"""
    if not isinstance(obj, dict):
        return default
    candidates = _ALIASES.get(name, (name,))
    for k in candidates:
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
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
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


def _to_items(payload: Any) -> List[Dict[str, Any]]:
    """把 MCP 工具返回体规整成 list[dict]。

    兼容三种形态：
    - 直接是 list
    - dict 且含 items/list/records/data 等列表键
    - dict 本身被当作单条记录
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "list", "records", "rows", "data", "content", "result", "coupons",
                    "products", "prizes", "orders", "listOfXXX", "value"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return _to_items(v)
        # 只有一个 dict 值且是 dict，尝试下钻一层
        dict_vals = [v for v in payload.values() if isinstance(v, dict)]
        if len(dict_vals) == 1:
            return _to_items(dict_vals[0])
        return [payload]
    return []


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
    est_value_cny: float = 0.0
    value_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LotteryPrize:
    """一个奖品。"""
    name: str
    value_cny: float = 0.0
    probability: Optional[float] = None   # 0~1
    value_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LotteryInfo:
    """积分抽奖活动。"""
    name: str
    cost_points: int = 0
    prizes: List[LotteryPrize] = field(default_factory=list)
    rules: str = ""
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
    unparsed: int = 0
    notes: List[str] = field(default_factory=list)
    is_mock: bool = False

    @property
    def menu_price_map(self) -> Dict[str, float]:
        return {m.name: m.price_cny for m in self.menu if m.price_cny > 0}


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #

def parse_account(payload: Any) -> PointsAccount:
    """解析 ``query-my-account`` 的返回。"""
    items = _to_items(payload)
    acc = PointsAccount(raw=payload if isinstance(payload, dict) else {})

    # 情况 A：顶层就是一个账户对象
    if items and _alias(items[0], "available") is not None:
        root = items[0]
        acc.available = _as_int(_alias(root, "available"))
        acc.total_earned = _as_int(_alias(root, "total_earned"))
        acc.frozen = _as_int(_alias(root, "frozen"))
        acc.raw = root
        exp = _alias(root, "expiring")
        if exp is not None:
            acc.expiring = _parse_expiring(exp)
        return acc

    # 情况 B：多个分片对象
    for it in items:
        name = str(_alias(it, "name", "") or "")
        val = _as_int(_alias(it, "points_amount", default=None)
                      if _alias(it, "points_amount") is not None
                      else _alias(it, "available", default=None)
                      if _alias(it, "available") is not None
                      else _alias(it, "value"), default=0)
        if any(k in name for k in ("可用", "available", "可用积分")):
            acc.available = val
        elif any(k in name for k in ("累计", "total", "累计积分")):
            acc.total_earned = val
        elif any(k in name for k in ("冻结", "frozen", "冻结积分")):
            acc.frozen = val
        elif any(k in name for k in ("即将过期", "expiring", "即将过期积分")):
            acc.expiring = [ExpiringBucket(points=val, expire_date=None, label=name)]
        elif any(k in name for k in ("已使用", "used")):
            acc.used = val  # type: ignore[attr-defined]
    if not acc.raw:
        acc.raw = payload if isinstance(payload, dict) else {}
    return acc


def _parse_expiring(payload: Any) -> List[ExpiringBucket]:
    """解析即将过期积分结构（可能是 int、list[dict] 或 dict）。"""
    buckets: List[ExpiringBucket] = []
    if payload is None:
        return buckets
    if isinstance(payload, (int, float)):
        return [ExpiringBucket(points=_as_int(payload))]
    if isinstance(payload, dict):
        # {"points": 340, "expireDate": "2026-11-30"}
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
        cid = str(_alias(it, "id", default=f"coupon-{i}"))
        name = str(_alias(it, "name", default="") or "")
        if not name:
            continue
        out.append(Coupon(
            coupon_id=cid,
            name=name,
            expire_date=_as_date(_alias(it, "expire")),
            claimed=claimed,
            raw=it,
        ))
    return out


def parse_mall_products(payload: Any) -> List[MallProduct]:
    """解析 ``mall-points-products``。"""
    out: List[MallProduct] = []
    for i, it in enumerate(_to_items(payload)):
        name = str(_alias(it, "name", default="") or "")
        if not name:
            continue
        out.append(MallProduct(
            product_id=str(_alias(it, "id", default=f"prod-{i}")),
            name=name,
            points_price=_as_int(_alias(it, "points")),
            cash_price=_as_float(_alias(it, "cash")),
            stock=_as_int(_alias(it, "stock"), default=-1),
            category=str(_alias(it, "category", default="") or ""),
            raw=it,
        ))
    return out


def parse_lottery(payload: Any) -> Optional[LotteryInfo]:
    """解析 ``query-lottery-info``。"""
    if payload is None:
        return None
    items = _to_items(payload)
    root = payload if isinstance(payload, dict) else {}
    info = LotteryInfo(
        name=str(_alias(root, "name", default="") or "积分抽奖"),
        cost_points=_as_int(_alias(root, "cost")),
        rules=str(_alias(root, "rules", default="") or ""),
        raw=root,
    )
    prize_items = _to_items(_alias(root, "prizes")) or items
    for i, it in enumerate(prize_items):
        pname = str(_alias(it, "name", default="") or "")
        if not pname:
            continue
        prob = _alias(it, "probability")
        info.prizes.append(LotteryPrize(
            name=pname,
            value_cny=_as_float(_alias(it, "value")),
            probability=(float(_as_float(prob)) if prob is not None else None),
            raw=it,
        ))
    # 消耗规则可能只在文案里，抽不出来就保留 0，报告里会显式提示
    if not info.cost_points and info.rules:
        m = re.search(r"(\d+)\s*积分", info.rules)
        if m:
            info.cost_points = int(m.group(1))
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
            calories=_as_float(_alias(it, "calories", default=0.0)),
            raw=it,
        ))
    return out
