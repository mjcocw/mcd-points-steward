# MCP_INTEGRATION

本项目使用**麦当劳中国官方 MCP Server**（`https://mcp.mcd.cn`）提供的能力，
不依赖任何私有接口、爬虫或非公开渠道。

---

## 1. 接入方式

### 1.1 申请 MCP Token

1. 打开 [麦当劳 MCP 开放平台](https://open.mcd.cn/mcp)
2. 右上角【登录】→ 手机号验证
3. 登录后右上角变为【控制台】→ 点击【激活】→ 申请 MCP Token
4. 复制 Token

### 1.2 配置连接

在 WorkBuddy 中：左侧边栏 →【专家·技能·连接器】→ 右上角【自定义连接器】→【配置 MCP】：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

> ⚠️ 务必把 `YOUR_MCP_TOKEN` 替换为真实 Token 后再保存。
> ⚠️ Token 仅存在于本地连接器配置与环境变量 `MCD_MCP_TOKEN` 中，**不会写入本仓库任何文件**。

### 1.3 传输协议要点

| 项目 | 值 |
|---|---|
| 传输 | Streamable HTTP |
| 端点 | `https://mcp.mcd.cn` |
| 鉴权 | 请求头 `Authorization: Bearer <token>` |
| 协议版本 | `2025-06-18` |
| 限流 | 单 Token 每分钟最多 600 次请求，超出返回 `429` |
| 错误码 | `401` Token 无效/过期；`429` 触发限流 |

本项目在 `mcd_steward/mcp_client.py` 中用标准库实现了完整的
`initialize` → `notifications/initialized` → `tools/list` → `tools/call` 握手流程，
同时兼容 `application/json` 与 `text/event-stream` 两种响应体。

---

## 2. 实际使用的 Tool 与调用流程

### 2.1 Tool 清单

| # | Tool 名称 | 官方描述 | 本项目用途 |
|---|---|---|---|
| 1 | `query-my-account` | 我的积分查询：可用、累计、冻结、即将过期积分 | 资产盘点；定位即将过期的积分池 |
| 2 | `query-my-coupons` | 我的优惠券查询 | 计算已持有券的真实面值；识别最先失效的券 |
| 3 | `available-coupons` | 麦麦省券列表查询 | 找出**尚未领取**的 0 成本收益 |
| 4 | `mall-points-products` | 麦麦商城商品列表查询 | 反推积分汇率（现金价 ÷ 积分价）；背包求解的物品池 |
| 5 | `query-lottery-info` | 查看积分抽奖活动信息 | 奖品池、消耗规则、中奖概率 → 期望值与方差 |
| 6 | `query-meals` | 查询当前可售卖的餐品列表 | 给「免费券 / 买一送一 / 半价券」估算真实面值 |

> `list-nutrition-foods` 作为**兜底**：当 `query-meals` 不可用时，用于获取餐品名称与热量，
> 至少能支撑券名 → 商品名的匹配。

### 2.2 调用流程

```
                   ┌─────────────────────────┐
                   │  tools/list             │  ← 先确认服务端开放了哪些 Tool
                   │  （本项目用 available 集合 │
                   │    做降级：未开放的直接跳过）  │
                   └───────────┬─────────────┘
                               │
     ┌──────────────┬──────────┴──────────┬──────────────┬──────────────┐
     ▼              ▼                     ▼              ▼              ▼
query-my-      query-my-             available-      mall-points-    query-lottery-
account        coupons               coupons         products        info
     │              │                     │              │              │
     │              │                     │              │              │
     │              │                     │              │              │
     ▼              ▼                     ▼              ▼              ▼
 PointsAccount  List[Coupon]        List[Coupon]   List[MallProduct]  LotteryInfo
     │              │                     │              │              │
     │              └─────────┬───────────┘              │              │
     │                        ▼                          │              │
     │              estimate_coupon_value()               │              │
     │              （券名正则 + 菜单价匹配）               │              │
     │                        │                          │              │
     │                        │                          ▼              ▼
     │                        │                 infer_point_rate   lottery_
     │                        │                 （中位数汇率）    expected_value
     │                        │                          │         （期望/方差/概率）
     └────────────────────────┴────────────┬─────────────┴──────────────┘
                                            ▼
                                   knapsack_redeem()
                                   （0/1 背包 DP）
                                            ▼
                                     build_plan()
                                   （三条路线 + 推荐）
                                            ▼
                              终端报告 / 单文件 HTML 报告 / JSON
```

### 2.3 降级策略

`source.py` 中的 `LiveSource.collect()` 会先调 `tools/list` 拿到服务端**当前实际开放**的 Tool 集合，
只调用已开放的接口，未开放的会在报告的「说明」区显式列出（而不是静默返回空）。

| 场景 | 行为 |
|---|---|
| 未提供 Token | 自动回退到 `--mock` 离线演示数据 |
| Token 失效（401） | 抛出明确错误并提示重新申请，同时建议先用 `--mock` 跑通流程 |
| 触发限流（429） | 提示降低调用频率 |
| 某 Tool 未开放 | 跳过该部分数据，在报告里注明，缺失部分不参与计算 |
| 字段名变更 | `domain.py` 的别名表覆盖多种候选键名，解析不出的项计入 `unparsed` |

---

## 3. 字段映射与容错

官方接口的返回结构可能随版本调整，因此**所有解析都通过别名表**完成
（`domain.py` 的 `_ALIASES`），而不是写死单一字段名。

| 标准字段 | 候选键名（部分） |
|---|---|
| 可用积分 | `available` / `usable` / `current` / `可用积分` |
| 即将过期积分 | `expiring` / `expiringPoints` / `expireSoon` / `即将过期积分` |
| 积分数量 | `points` / `point` / `pointAmount` / `积分` / `积分数` |
| 券名 | `name` / `title` / `couponName` / `productName` / `desc` |
| 积分价 | `points` / `pointPrice` / `costPoints` / `needPoints` / `积分价格` |
| 现金价 | `cash` / `cashPrice` / `price` / `amount` / `售价` |
| 到期日 | `expireDate` / `expireTime` / `validUntil` / `endTime` / `有效期` |
| 中奖概率 | `probability` / `prob` / `rate` / `chance` / `中奖概率` |

列表型返回兼容三种形态：直接 `list`、`dict` 中含 `items`/`list`/`records`/`data` 等列表键、
以及单个 `dict` 记录。

**解析失败不会被静默吞掉** —— 顶层返回体里识别不出结构的条目会计入 `unparsed`，
并在报告的「说明」区提示，避免出现"看起来算得很准其实漏了一半数据"。

---

## 4. 业务价值

| 痛点 | 本项目的处理 | 价值 |
|---|---|---|
| 积分到期无感知 | `query-my-account` 的即将过期积分 + 倒计时预警 | 避免真金白银的沉没损失 |
| 券领了不用、过期才发现 | 券名解析 + 菜单价匹配估算真实面值 + 按剩余天数排序 | 让每一张券都落地 |
| 抽奖"到底值不值"说不清 | 效用加权的期望值、标准差、颗粒无收概率 | 从"抽奖"变成"决策" |
| 商城兑换选哪个划算 | 0/1 背包求解 + 效用系数 | 在积分上限内拿到最大效用价值 |
| 一次性决策缺全局视角 | 稳健 / 平衡 / 进攻三路线量化对比 | 风险与收益自己选 |

---

## 5. 合规声明

- 本项目**仅使用**麦当劳中国官方 MCP Server 开放的 Tool，**不抓取网页、不逆向、不绕过任何鉴权**。
- 全程**只读**，不创建订单、不发起支付、不修改账户信息。
- 唯一的写操作是用户主动执行「一键领券」（`auto-bind-coupons`），本项目当前版本**未默认调用**该接口。
- MCP Token 仅从环境变量读取，**不写入代码、配置或任何提交到 GitHub 的文件**。
- 所有价格与餐品信息以麦当劳官方渠道实时结果为准；本项目输出的估值仅为个人消费决策参考。
- 本项目为参赛者独立开发，**非麦当劳官方产品**，与麦当劳中国及其关联公司无任何隶属或背书关系。
