"""离线演示数据（mock）。

⚠ **字段结构与麦当劳真实接口完全一致**（``spuName`` / ``point`` / ``downTime`` /
``currentMouthExpirePoint`` / ``drawPoint`` / ``drawDecision`` …），
所以「mock 下跑通」= 「真实接口下也能跑通」。

为什么一定要有 mock 模式
------------------------
1. 评审者和路人没有麦当劳 MCP Token，没法跑通你的项目 —— 演示页必须人人可看。
2. 真实接口返回结构会变，mock 让 README 的截图和线上表现保持一致。

本文件里的价格、积分比例均取自公开可见的麦当劳中国菜单与活动页面口径，
仅用于演示，**不代表任何官方承诺**。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

TODAY = date.today()


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _dt(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# query-my-account
# --------------------------------------------------------------------------- #

def account_payload() -> Dict[str, Any]:
    """真实结构里「本月到期 / 下月到期」是独立字段，且官方把 Month 拼成了 Mouth。"""
    return {
        "availablePoint": "1240",
        "accumulativePoint": "5860",
        "frozenPoint": "0",
        "usedPoint": "0",
        "expiredPoint": "0",
        "currentMouthExpirePoint": "240",
        "nextMouthExpirePoint": "100",
        "lastMouthExpirePoint": "0",
        "currency": "麦享会积分",
    }


# --------------------------------------------------------------------------- #
# query-my-coupons
# --------------------------------------------------------------------------- #

def my_coupons_payload() -> Dict[str, Any]:
    return {
        "coupons": [
            {"couponId": "C8825", "couponName": "甜品站任选一件免费券",
             "couponStatus": "UNUSED", "expireTime": _d(3)},
            {"couponId": "C8822", "couponName": "免费中可乐一杯",
             "couponStatus": "UNUSED", "expireTime": _d(6)},
            {"couponId": "C8821", "couponName": "巨无霸套餐满60减15元券",
             "couponStatus": "UNUSED", "expireTime": _d(17)},
            {"couponId": "C8824", "couponName": "麦辣鸡腿堡买一送一",
             "couponStatus": "UNUSED", "expireTime": _d(24)},
            {"couponId": "C8823", "couponName": "第二份麦乐鸡半价券",
             "couponStatus": "UNUSED", "expireTime": _d(46)},
        ],
        "totalCount": 5, "currentPage": 1, "pageSize": 200, "totalPages": 1,
    }


# --------------------------------------------------------------------------- #
# available-coupons（麦麦省可领）
# --------------------------------------------------------------------------- #

def claimable_coupons_payload() -> List[Dict[str, Any]]:
    return [
        {"couponName": "11.9元麦辣鸡腿堡", "couponImage": "https://img.mcd.cn/x.png",
         "couponStatus": "CAN_GET", "label": "可领取"},
        {"couponName": "19.9元王牌炸鸡任选2", "couponImage": "https://img.mcd.cn/y.png",
         "couponStatus": "CAN_GET", "label": "可领取"},
        {"couponName": "免费脆薯饼", "couponImage": "https://img.mcd.cn/z.png",
         "couponStatus": "CAN_GET", "label": "可领取"},
        {"couponName": "麦麦省满35减10元券", "couponImage": "https://img.mcd.cn/w.png",
         "couponStatus": "CAN_GET", "label": "可领取"},
    ]


# --------------------------------------------------------------------------- #
# mall-points-products
# --------------------------------------------------------------------------- #

def mall_products_payload() -> List[Dict[str, Any]]:
    """注意两个真实细节：

    1. ``price`` 对商品券恒为 0，真实面值藏在 ``spuName`` 里；
    2. 列表里混着**已下架**商品（``downTime`` 已过），必须过滤。
    """
    return [
        # —— 在架，可兑换 ——
        {"spuName": "5.9元香芋派/菠萝派任选", "spuId": 9001, "point": "50", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-60), "downTime": _dt(70),
         "selling": "香芋派/菠萝派任选一份"},
        {"spuName": "10.9元指定小食任选", "spuId": 9002, "point": "200", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-60), "downTime": _dt(70),
         "selling": "指定小食任选一份"},
        {"spuName": "12.9元麦旋风", "spuId": 9003, "point": "300", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-60), "downTime": _dt(240),
         "selling": "麦旋风一个"},
        {"spuName": "16.9元麦辣可乐组合", "spuId": 9004, "point": "500", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-60), "downTime": _dt(70),
         "selling": "麦辣鸡腿堡+可乐"},
        {"spuName": "21.9元巨无霸可乐组合", "spuId": 9005, "point": "800", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-60), "downTime": _dt(70),
         "selling": "巨无霸+中可乐"},
        {"spuName": "30元麦麦周边帆布袋", "spuId": 9006, "point": "1500", "price": "0",
         "catName": "周边", "status": 2, "upTime": _dt(-90), "downTime": _dt(40),
         "selling": "麦麦周边帆布袋一只"},
        {"spuName": "50元麦麦年卡电子权益", "spuId": 9007, "point": "5000", "price": "0",
         "catName": "权益", "status": 2, "upTime": _dt(-90), "downTime": _dt(500),
         "selling": "麦麦年卡电子权益"},
        # —— 已下架（downTime 已过），用来演示过滤逻辑 ——
        {"spuName": "18.8元板烧鸡腿堡两件套", "spuId": 8001, "point": "100", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-300), "downTime": _dt(-215),
         "selling": "已结束"},
        {"spuName": "22.8元2份麦辣鸡腿堡", "spuId": 8002, "point": "500", "price": "0",
         "catName": "到店专用", "status": 2, "upTime": _dt(-300), "downTime": _dt(-215),
         "selling": "已结束"},
        # —— point = 0：派对 / 读书会等体验类，不是积分兑换物 ——
        {"spuName": "麦当劳奇妙生日派对", "spuId": 7001, "point": "0", "price": "50",
         "catName": "生日类派对", "status": 2, "upTime": _dt(-400), "downTime": _dt(500),
         "selling": "迪士尼主题生日派对"},
        {"spuName": "麦当劳亲子读书会", "spuId": 7002, "point": "0", "price": "45",
         "catName": "读书会", "status": 2, "upTime": _dt(-400), "downTime": _dt(70),
         "selling": "亲子读书会"},
    ]


# --------------------------------------------------------------------------- #
# query-lottery-info
# --------------------------------------------------------------------------- #

def lottery_payload() -> Dict[str, Any]:
    """真实接口**不返回**中奖概率与奖品面值，这里如实保持一致。"""
    return {
        "status": {"code": "SUCCESS", "message": "成功"},
        "activityCode": "dtx2",
        "activityStatusText": "进行中",
        "activityName": "麦麦积分抽奖",
        "beginTime": "2025-01-26 00:00:00",
        "endTime": "2030-12-31 23:59:59",
        "drawPoint": "24",
        "drawTypeText": "消耗积分抽奖",
        "availablePoint": "1240",
        "drawDecision": {
            "resourceEligible": True,
            "reason": "",
            "nextConsumption": {"type": "POINTS", "points": "24", "chances": 51,
                                "text": "本次将消耗 24 积分"},
        },
        "prizes": [
            {"name": "下单立减3元券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/1.png"},
            {"name": "下单立减2元券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/2.png"},
            {"name": "下单立减1元券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/3.png"},
            {"name": "麦辣三件套5折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/4.png"},
            {"name": "板烧三件套5折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/5.png"},
            {"name": "双层鳕鱼三件套6折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/6.png"},
            {"name": "甜辣小食组合5折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/7.png"},
            {"name": "小食四件套5.5折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/8.png"},
            {"name": "麦旋风5折券", "typeText": "优惠券", "imageUrl": "https://img.mcd.cn/9.png"},
            {"name": "30积分", "typeText": "积分", "imageUrl": "https://img.mcd.cn/10.png"},
        ],
    }


# --------------------------------------------------------------------------- #
# query-meals
# --------------------------------------------------------------------------- #

def menu_payload() -> Dict[str, Any]:
    return {
        "items": [
            {"name": "巨无霸", "price": 22.0, "calories": 550},
            {"name": "麦辣鸡腿堡", "price": 21.0, "calories": 480},
            {"name": "板烧鸡腿堡", "price": 21.0, "calories": 490},
            {"name": "麦香鱼", "price": 22.0, "calories": 450},
            {"name": "麦香鸡", "price": 21.0, "calories": 500},
            {"name": "麦乐鸡", "price": 39.0, "calories": 750},
            {"name": "麦旋风", "price": 11.0, "calories": 350},
            {"name": "双层鳕鱼堡", "price": 24.0, "calories": 520},
            {"name": "中可乐", "price": 10.0, "calories": 140},
            {"name": "中薯条", "price": 11.0, "calories": 330},
            {"name": "脆薯饼", "price": 9.9, "calories": 240},
            {"name": "甜品站", "price": 8.0, "calories": 260},
            {"name": "香芋派", "price": 6.5, "calories": 280},
            {"name": "麦满分", "price": 15.0, "calories": 400},
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
