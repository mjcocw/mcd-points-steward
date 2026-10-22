"""离线演示数据（mock）。

为什么一定要有 mock 模式
------------------------
1. 评审者和路人没有麦当劳 MCP Token，没法跑通你的项目 —— 演示页必须人人可看。
2. 真实接口返回结构会变，mock 让 README 的截图和线上表现保持一致。

本文件里的价格、积分比例均来自公开可见的麦当劳中国菜单与活动页面口径，
仅用于演示，**不代表任何官方承诺**。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

TODAY = date.today()


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------- #
# query-my-account
# --------------------------------------------------------------------------- #

def account_payload() -> Dict[str, Any]:
    return {
        "available": 1240,
        "totalEarned": 5860,
        "frozen": 0,
        "expiring": [
            {"points": 240, "expireDate": _d(9), "name": "10月底到期积分"},
            {"points": 100, "expireDate": _d(38), "name": "11月底到期积分"},
        ],
    }


# --------------------------------------------------------------------------- #
# query-my-coupons
# --------------------------------------------------------------------------- #

def my_coupons_payload() -> Dict[str, Any]:
    return {
        "items": [
            {"couponId": "C8821", "name": "巨无霸套餐满60减15元券", "expireDate": _d(17)},
            {"couponId": "C8822", "name": "免费中可乐一杯", "expireDate": _d(6)},
            {"couponId": "C8823", "name": "麦辣鸡腿堡买一送一", "expireDate": _d(24)},
            {"couponId": "C8824", "name": "第二份麦乐鸡半价券", "expireDate": _d(46)},
            {"couponId": "C8825", "name": "甜品站任选一件免费券", "expireDate": _d(3)},
        ]
    }


# --------------------------------------------------------------------------- #
# available-coupons（麦麦省可领）
# --------------------------------------------------------------------------- #

def claimable_coupons_payload() -> Dict[str, Any]:
    return {
        "items": [
            {"couponId": "N1041", "name": "早餐时段麦满分减6元", "expireDate": _d(29)},
            {"couponId": "N1042", "name": "麦麦省满35减10元券", "expireDate": _d(11)},
            {"couponId": "N1043", "name": "免费中薯条一份", "expireDate": _d(7)},
            {"couponId": "N1044", "name": "巨无霸单点立减8元", "expireDate": _d(20)},
        ]
    }


# --------------------------------------------------------------------------- #
# mall-points-products
# --------------------------------------------------------------------------- #

def mall_products_payload() -> Dict[str, Any]:
    return {
        "items": [
            {"productId": "P01", "name": "限量联名保温杯", "points": 1000, "cash": 20, "stock": 120, "category": "周边"},
            {"productId": "P02", "name": "新品尝鲜礼盒", "points": 800, "cash": 15, "stock": 260, "category": "餐品"},
            {"productId": "P03", "name": "经典麦乐鸡3件装兑换券", "points": 1200, "cash": 12, "stock": 999, "category": "餐品"},
            {"productId": "P04", "name": "5元麦麦省代金券", "points": 500, "cash": 5, "stock": 999, "category": "代金券"},
            {"productId": "P05", "name": "10元麦麦省代金券", "points": 1000, "cash": 10, "stock": 999, "category": "代金券"},
            {"productId": "P06", "name": "麦麦咖啡兑换券", "points": 900, "cash": 9, "stock": 340, "category": "餐品"},
            {"productId": "P07", "name": "儿童套餐玩具兑换", "points": 1500, "cash": 15, "stock": 80, "category": "周边"},
            {"productId": "P08", "name": "巨无霸造型帆布袋", "points": 1800, "cash": 18, "stock": 45, "category": "周边"},
            {"productId": "P09", "name": "麦麦年卡电子权益", "points": 5000, "cash": 50, "stock": 999, "category": "权益"},
        ]
    }


# --------------------------------------------------------------------------- #
# query-lottery-info
# --------------------------------------------------------------------------- #

def lottery_payload() -> Dict[str, Any]:
    return {
        "name": "麦麦幸运抽奖",
        "cost": 100,
        "rules": "每次抽奖消耗 100 积分，奖品随机发放，库存有限抽完即止。",
        "prizes": [
            {"name": "巨无霸套餐", "value": 45, "probability": 0.02},
            {"name": "麦辣鸡腿堡", "value": 21, "probability": 0.08},
            {"name": "中可乐", "value": 10, "probability": 0.12},
            {"name": "5元麦麦省代金券", "value": 5, "probability": 0.35},
            {"name": "经典麦乐鸡3件装", "value": 39, "probability": 0.03},
            {"name": "谢谢参与", "value": 0, "probability": 0.40},
        ],
    }


# --------------------------------------------------------------------------- #
# query-meals（用于给"免费券"估算面值）
# --------------------------------------------------------------------------- #

def menu_payload() -> Dict[str, Any]:
    return {
        "items": [
            {"name": "巨无霸", "price": 22.0, "calories": 550},
            {"name": "麦辣鸡腿堡", "price": 21.0, "calories": 480},
            {"name": "板烧鸡腿堡", "price": 21.0, "calories": 490},
            {"name": "麦香鱼", "price": 22.0, "calories": 450},
            {"name": "麦香鸡", "price": 21.0, "calories": 500},
            {"name": "麦乐鸡（5块）", "price": 39.0, "calories": 750},
            {"name": "中可乐", "price": 10.0, "calories": 140},
            {"name": "中薯条", "price": 11.0, "calories": 330},
            {"name": "麦满分", "price": 15.0, "calories": 400},
            {"name": "甜品站", "price": 8.0, "calories": 260},
            {"name": "冰咖啡", "price": 13.0, "calories": 120},
            {"name": "拿铁", "price": 22.0, "calories": 150},
        ]
    }


# --------------------------------------------------------------------------- #
# 工具调用名 -> payload 的映射（mock 模式用）
# --------------------------------------------------------------------------- #

MOCK_BY_TOOL: Dict[str, Any] = {
    "query-my-account": account_payload,
    "query-my-coupons": my_coupons_payload,
    "available-coupons": claimable_coupons_payload,
    "mall-points-products": mall_products_payload,
    "query-lottery-info": lottery_payload,
    "query-meals": menu_payload,
    "list-nutrition-foods": menu_payload,
}


def mock_snapshot_tools() -> List[str]:
    return list(MOCK_BY_TOOL.keys())
