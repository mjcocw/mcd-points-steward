"""麦麦积分资产管家 (McPoints Steward)。

一个基于麦当劳官方 MCP Server 的开源 Skill：扫描你的积分账户与优惠券，
把"即将过期的积分"和"最值钱的兑换路线"算清楚，输出一张可截图的资产体检报告。

零第三方依赖，Python 3.9+ 直接可跑。
"""

__version__ = "1.0.0"
__all__ = ["domain", "valuation", "report", "mcp_client", "source"]
