"""数据来源层：真实 MCP 与离线 mock 的统一入口。

上层（valuation / report）只认 :class:`McSnapshot`，不关心数据是打真接口还是打假的。

真实接口的调用顺序（有依赖，不能乱）
--------------------------------------
    query-nearby-stores  →  拿到 storeCode
              │
              ├──→ query-meals          (需要 storeCode + beType + orderType)
              └──→ query-store-coupons  (需要 storeCode + beType + orderType)

``query-meals`` 与 ``query-store-coupons`` 都依赖门店，属于**可选增强**：
拿不到门店时降级为「参考价表 + 从商品名反推价格」，报告仍可生成。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from . import fixtures
from .domain import (
    McSnapshot,
    business_error,
    parse_account,
    parse_coupons,
    parse_lottery,
    parse_mall_products,
    parse_menu,
)
from .mcp_client import McpClient, McpError

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")

#: 本项目用到的 Tool 及其业务含义（MCP_INTEGRATION.md 里也逐条对应）
TOOL_PLAN: List[Tuple[str, str]] = [
    ("query-my-account", "积分账户总览：可用 / 累计 / 冻结 / 已过期 / 即将过期积分"),
    ("query-my-coupons", "卡包中已持有的优惠券"),
    ("available-coupons", "麦麦省当前可领取但尚未领取的优惠券"),
    ("mall-points-products", "麦麦商城积分兑换商品清单（含上下架时间）"),
    ("query-lottery-info", "积分抽奖活动：奖品池、消耗积分、是否可参与"),
    ("query-nearby-stores", "（可选）解析门店编码，为下面的菜单查询铺路"),
    ("query-meals", "（可选）当前门店在售菜单与价格，用于给券估值"),
    ("query-store-coupons", "（可选）该门店实际可用的优惠券"),
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
                 city: str = "", keyword: str = "麦当劳") -> None:
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        self.url = url
        self.city = city or os.environ.get("MCD_CITY", "")
        self.keyword = keyword
        self.client = McpClient(url=url, token=self.token)
        self.available_tools: List[str] = []

    # ------------------------------------------------------------------ #

    def _call(self, tool: str, args: Optional[Dict[str, Any]] = None,
              snap: Optional[McSnapshot] = None) -> Any:
        """调用一个 Tool；服务端未开放或出错时返回 None 并记录说明。"""
        if tool not in self.available_tools:
            if snap is not None:
                snap.notes.append(f"服务端未开放 `{tool}`，已跳过该部分数据")
            return None
        try:
            data = self.client.call_tool(tool, args or {})
        except McpError as exc:
            if snap is not None:
                snap.notes.append(f"`{tool}` 调用失败：{exc}")
            return None
        # 官方在业务失败时返回 {"success": false, "code": ..., "message": ...}
        err = business_error(data)
        if err:
            if snap is not None:
                snap.notes.append(f"`{tool}` 返回业务错误：{err}")
            return None
        return data

    def _resolve_store(self, snap: McSnapshot) -> Optional[Dict[str, Any]]:
        """用 query-nearby-stores 拿一个可用门店。

        实测参数约定：
        - ``searchType=1``：查收藏餐厅 —— 没有收藏时返回 600050「收藏餐厅列表为空」
        - ``searchType=2``：按位置搜 —— **必须同时给 city 和 keyword**，
          否则返回 600058「城市名或者关键词不能为空」

        两种方式依次尝试；只有**全部失败**才在报告里提示（否则正常的
        "先查收藏、再按城市搜"流程会留下一条误导性的错误说明）。
        """
        attempts: List[Dict[str, Any]] = [{"beType": 1, "searchType": 1}]
        if self.city:
            attempts.append({"beType": 1, "searchType": 2,
                             "city": self.city, "keyword": self.keyword})
        errors: List[str] = []
        for args in attempts:
            try:
                data = self.client.call_tool("query-nearby-stores", args)
            except McpError as exc:
                errors.append(str(exc))
                continue
            err = business_error(data)
            if err:
                errors.append(err)
                continue
            items = data if isinstance(data, list) else (
                data.get("stores") or data.get("items") or [])
            for store in items:
                if isinstance(store, dict) and store.get("storeCode"):
                    return store
        if errors:
            snap.notes.append("门店解析未成功：" + "；".join(errors[:2]))
        return None

    # ------------------------------------------------------------------ #

    def collect(self) -> McSnapshot:
        snap = McSnapshot(is_mock=False)
        available = set(self.client.list_tools())
        self.available_tools = sorted(available)

        # --- 资产 -------------------------------------------------------- #
        acc = self._call("query-my-account", None, snap)
        if acc is not None:
            snap.account = parse_account(acc)

        my = self._call("query-my-coupons", None, snap)
        if my is not None:
            snap.my_coupons = parse_coupons(my, claimed=True)

        claim = self._call("available-coupons", None, snap)
        if claim is not None:
            snap.claimable_coupons = parse_coupons(claim, claimed=False)

        mall = self._call("mall-points-products", None, snap)
        if mall is not None:
            snap.mall_products = parse_mall_products(mall)

        lot = self._call("query-lottery-info", None, snap)
        if lot is not None:
            snap.lottery = parse_lottery(lot)

        # --- 门店相关（可选增强） ---------------------------------------- #
        store = self._resolve_store(snap)
        if store:
            store_code = str(store.get("storeCode"))
            snap.store_name = str(store.get("storeName") or store.get("name") or store_code)
            meals = self._call("query-meals", {
                "storeCode": store_code, "beType": 1, "orderType": 1,
            }, snap)
            if meals is not None:
                snap.menu = parse_menu(meals)
            store_coupons = self._call("query-store-coupons", {
                "storeCode": store_code, "beType": 1, "orderType": 1,
            }, snap)
            if store_coupons is not None:
                known = {c.name for c in snap.claimable_coupons}
                for c in parse_coupons(store_coupons, claimed=False):
                    if c.name and c.name not in known:
                        snap.claimable_coupons.append(c)
                        known.add(c.name)
        else:
            snap.notes.append("未能解析到门店，菜单价格改用参考价表与商品名反推")

        if not snap.menu:
            nutrition = self._call("list-nutrition-foods", None, snap)
            if nutrition is not None:
                snap.menu = parse_menu(nutrition)

        return snap


class MockSource(McSource):
    """离线演示数据源，无需 Token。

    ⚠ mock 的字段结构与真实接口**完全一致**（含 ``spuName`` / ``point`` /
    ``downTime`` / ``currentMouthExpirePoint`` / ``drawPoint`` 等），
    所以 mock 下跑通 = 真实接口下也能跑通。
    """

    is_mock = True

    def collect(self) -> McSnapshot:
        snap = McSnapshot(is_mock=True)
        snap.account = parse_account(fixtures.account_payload())
        snap.my_coupons = parse_coupons(fixtures.my_coupons_payload(), claimed=True)
        snap.claimable_coupons = parse_coupons(fixtures.claimable_coupons_payload(), claimed=False)
        snap.mall_products = parse_mall_products(fixtures.mall_products_payload())
        snap.lottery = parse_lottery(fixtures.lottery_payload())
        snap.menu = parse_menu(fixtures.menu_payload())
        snap.store_name = "国金中心店（上海）"
        snap.notes.append("当前为离线演示数据（mock），字段结构与真实接口一致，并非你的真实账户")
        return snap


def build_source(mode: str = "auto", token: Optional[str] = None,
                 city: str = "", keyword: str = "麦当劳") -> McSource:
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
        return LiveSource(token=token, city=city, keyword=keyword)
    if token:
        return LiveSource(token=token, city=city, keyword=keyword)
    return MockSource()


__all__ = ["McSource", "LiveSource", "MockSource", "build_source", "MCP_URL", "TOOL_PLAN", "McpError"]
