"""数据来源层：真实 MCP 与离线 mock 的统一入口。

上层（valuation / report）只认 :class:`McSnapshot`，不关心数据是打真接口还是打假的。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from . import fixtures
from .domain import (
    Coupon,
    McSnapshot,
    MealPrice,
    parse_account,
    parse_coupons,
    parse_lottery,
    parse_mall_products,
    parse_menu,
)
from .mcp_client import McpClient, McpError

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")

# 本项目用到的 Tool 及其业务含义（MCP_INTEGRATION.md 里也逐条对应）
TOOL_PLAN: List[tuple] = [
    ("query-my-account", "拉取积分账户总览：可用 / 累计 / 冻结 / 即将过期积分"),
    ("query-my-coupons", "拉取账户中已持有的优惠券"),
    ("available-coupons", "拉取麦麦省当前可领取但尚未领取的优惠券"),
    ("mall-points-products", "拉取麦麦商城中可用积分兑换的商品清单"),
    ("query-lottery-info", "拉取积分抽奖活动的奖品池、消耗规则与中奖概率"),
    ("query-meals", "拉取当前门店在售菜单，用于给\"免费券\"估算实际面值"),
]


class McSource:
    """数据来源基类。"""

    is_mock: bool = False

    def collect(self) -> McSnapshot:  # pragma: no cover - 抽象
        raise NotImplementedError


class LiveSource(McSource):
    """连接麦当劳官方 MCP Server 抓取真实数据。"""

    is_mock = False

    def __init__(self, token: Optional[str] = None, url: str = MCP_URL,
                 only: Optional[List[str]] = None) -> None:
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        self.url = url
        self.only = only
        self.client = McpClient(url=url, token=self.token)
        self.available_tools: List[str] = []

    def collect(self) -> McSnapshot:
        snap = McSnapshot(is_mock=False)
        available = set(self.client.list_tools())
        self.available_tools = sorted(available)

        def call(tool: str, args: Optional[Dict[str, Any]] = None) -> Any:
            if tool not in available:
                snap.notes.append(f"服务端未开放 `{tool}`，已跳过该部分数据")
                return None
            return self.client.call_tool(tool, args or {})

        acc = call("query-my-account")
        if acc is not None:
            snap.account = parse_account(acc)

        my = call("query-my-coupons")
        if my is not None:
            snap.my_coupons = parse_coupons(my, claimed=True)

        claim = call("available-coupons")
        if claim is not None:
            snap.claimable_coupons = parse_coupons(claim, claimed=False)

        mall = call("mall-points-products")
        if mall is not None:
            snap.mall_products = parse_mall_products(mall)

        lot = call("query-lottery-info")
        if lot is not None:
            snap.lottery = parse_lottery(lot)

        menu = call("query-meals")
        if menu is not None:
            snap.menu = parse_menu(menu)

        if not snap.menu:
            nutrition = call("list-nutrition-foods")
            if nutrition is not None:
                snap.menu = parse_menu(nutrition)

        return snap


class MockSource(McSource):
    """离线演示数据源，无需 Token。"""

    is_mock = True

    def collect(self) -> McSnapshot:
        snap = McSnapshot(is_mock=True)
        snap.account = parse_account(fixtures.account_payload())
        snap.my_coupons = parse_coupons(fixtures.my_coupons_payload(), claimed=True)
        snap.claimable_coupons = parse_coupons(fixtures.claimable_coupons_payload(), claimed=False)
        snap.mall_products = parse_mall_products(fixtures.mall_products_payload())
        lottery = parse_lottery(fixtures.lottery_payload())
        snap.lottery = lottery
        snap.menu = parse_menu(fixtures.menu_payload())
        snap.notes.append("当前为离线演示数据（mock），并非你的真实账户")
        return snap


def build_source(mode: str = "auto", token: Optional[str] = None) -> McSource:
    """按模式选择数据源。

    - ``live``：强制走真实 MCP
    - ``mock``：强制走离线数据
    - ``auto``：有 Token 就走真实，否则回退到 mock
    """
    mode = (mode or "auto").lower()
    token = token or os.environ.get("MCD_MCP_TOKEN", "")
    if mode == "mock":
        return MockSource()
    if mode == "live":
        return LiveSource(token=token)
    if token:
        return LiveSource(token=token)
    return MockSource()


__all__ = ["McSource", "LiveSource", "MockSource", "build_source", "MCP_URL", "TOOL_PLAN", "McpError"]
