# MCP_INTEGRATION

本项目使用**麦当劳中国官方 MCP Server**（`https://mcp.mcd.cn`）提供的能力，
不依赖任何私有接口、爬虫或非公开渠道。

> 本文档中的所有字段名、错误码、参数约定均为 **2026-10-22 实测**结果，
> 来自真实 Token 的端到端调用，不是根据官方文档推测的。

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
| 协议版本 | `2025-06-18`（服务端返回 `serverInfo: {name: "mcd-mcp", version: "1.0.0"}`） |
| 限流 | 单 Token 每分钟最多 600 次请求，超出返回 `429` |
| 错误码 | `401` Token 无效/过期；`429` 触发限流 |
| 开放 Tool 数 | **35 个**（实测） |

### 1.4 客户端实现要点（`mcd_steward/mcp_client.py`）

用标准库实现了完整握手：`initialize` → `notifications/initialized` → `tools/list` → `tools/call`，
并处理了三件实测踩到的工程问题：

| 问题 | 现象 | 本项目的处理 |
|---|---|---|
| **TLS 握手被中间设备掐断** | `urllib` 每次请求都新建 TLS 连接，在企业代理 / WAF 环境下偶发 `SSLEOFError` | 改用 `http.client.HTTPSConnection` **保持 keep-alive**，单次会话只握手一次 |
| **需要走 HTTP 代理** | 国内公司网络普遍有代理 | 自动读取 `https_proxy` / `HTTPS_PROXY`，用 CONNECT 隧道连接 |
| **连接被复用端关闭** | 长会话中途 `RemoteDisconnected` | 捕获后自动重连并重放请求（最多 3 次，退避重试） |

同时兼容 `application/json` 与 `text/event-stream` 两种响应体。

---

## 2. 实际使用的 Tool 与真实返回结构

### 2.1 Tool 清单

服务端共开放 35 个 Tool，本项目使用其中 **8 个只读接口**：

| # | Tool | 必填参数 | 在本项目中的用途 |
|---|---|---|---|
| 1 | `query-my-account` | — | 积分账户总览：可用 / 累计 / 冻结 / 已过期 / 即将过期 |
| 2 | `query-my-coupons` | — （可选 `page` / `pageSize`） | 卡包中已持有的优惠券 |
| 3 | `available-coupons` | — | 麦麦省当前可领但未领的券 |
| 4 | `mall-points-products` | — （可选 `catRuleIds`） | 麦麦商城积分兑换商品清单（含上下架时间） |
| 5 | `query-lottery-info` | — | 积分抽奖：奖品池、消耗积分、是否可参与 |
| 6 | `query-nearby-stores` | `beType` | 解析门店编码（`searchType=2` 需再加 `city` + `keyword`） |
| 7 | `query-meals` | `storeCode` `beType` `orderType` | 门店在售菜单与价格 |
| 8 | `query-store-coupons` | `storeCode` `beType` `orderType` | 该门店实际可用的优惠券 |

> ⚠️ **刻意未接入**：`auto-bind-coupons`（一键领券）、`create-order`、`mall-create-order`、
> `draw-lottery`、`party-order-create` —— 本项目**只读**，不做任何写操作。

### 2.2 真实返回结构（实测原样）

#### `query-my-account`

```json
{
  "availablePoint": "0",
  "accumulativePoint": "143.3",
  "currency": "麦享会积分",
  "currentMouthExpirePoint": "0",
  "expiredPoint": "143.3",
  "frozenPoint": "0",
  "lastMouthExpirePoint": "0",
  "nextMouthExpirePoint": "0",
  "usedPoint": "0"
}
```

> ⚠️ 三个关键点：
> 1. 官方把 **Month 拼成了 Mouth**（`currentMouthExpirePoint` / `nextMouthExpirePoint`）；
> 2. 数值是**字符串**，且带小数（`"143.3"`）；
> 3. 本月 / 下月到期积分是两个独立字段，**没有统一的 expiring 列表**。

#### `query-my-coupons`

```json
{ "coupons": [], "totalCount": 0, "currentPage": 1, "pageSize": 200, "totalPages": 0 }
```

#### `available-coupons`

```json
[
  { "couponName": "11.9元麦辣鸡腿堡", "couponImage": "https://img.mcd.cn/…",
    "couponStatus": "CAN_GET", "label": "可领取" }
]
```

> ⚠️ **不返回面值、不返回有效期** —— 面值必须从 `couponName` 里解析。

#### `mall-points-products`

```json
[
  { "spuName": "21.9元巨无霸可乐组合", "spuId": 1234, "point": "800", "price": "0",
    "catName": "到店专用", "status": 2,
    "upTime": "2023-08-01 00:00:00", "downTime": "2026-12-30 23:59:59" }
]
```

> ⚠️ 三个关键点：
> 1. **`price` 对商品券恒为 0**，真实面值在 `spuName` 里（`"21.9元…"`）；
> 2. **没有库存字段**，只有 `upTime` / `downTime`，**必须按 `downTime` 过滤已下架商品**
>    （实测 50 件里 43 件不可用）；
> 3. `point = 0` 的是派对 / 读书会 / 品鉴会等**体验类**，不是积分兑换物。

#### `query-lottery-info`

```json
{
  "activityCode": "dtx2", "activityName": "麦麦积分抽奖",
  "activityStatusText": "进行中",
  "beginTime": "2025-01-26 00:00:00", "endTime": "2030-12-31 23:59:59",
  "drawPoint": "24", "drawTypeText": "消耗积分抽奖", "availablePoint": "0",
  "drawDecision": { "resourceEligible": false, "reason": "积分不足",
                    "nextConsumption": { "type": "POINTS", "points": "24", "chances": 0 } },
  "prizes": [ { "name": "下单立减3元券", "typeText": "优惠券", "imageUrl": "…" } ]
}
```

> ⚠️ 三个关键点：
> 1. 奖品**只有 `name` / `typeText` / `imageUrl`** —— **既没有中奖概率，也没有面值**；
> 2. 面值必须从奖品名解析（`"下单立减3元券"` → 3 元；`"麦辣三件套5折券"` → 三件套 × 5 折；
>    `"30积分"` → 30 × 积分汇率）；
> 3. `drawDecision.resourceEligible` / `reason` 直接告诉你**能不能参与**（如"积分不足"）。

#### `query-meals` / `query-nearby-stores`

`query-meals` **强制要求** `storeCode` + `beType` + `orderType`，必须先解析门店：

| `searchType` | 含义 | 实测行为 |
|---|---|---|
| `1` | 查收藏餐厅 | 没有收藏时返回 `600050`「收藏餐厅列表为空，请您提供城市+关键词进行搜索」 |
| `2` | 按位置搜索 | **必须同时给 `city` 和 `keyword`**，否则返回 `600058`「城市名或者关键词不能为空」 |

```bash
# 本项目暴露为 CLI 参数
python main.py --live --city 上海 --keyword 麦当劳
```

### 2.3 业务错误约定

官方在业务失败时**不抛 MCP 错误**，而是返回 HTTP 200 + 业务错误体：

```json
{ "success": false, "code": 600050, "message": "收藏餐厅列表为空，请您提供城市+关键词进行搜索" }
```

`domain.business_error()` 专门识别这种结构。
不识别就会把错误当成"查到了但没数据"，静默丢信息。

---

## 3. 调用流程

```
                  ┌─────────────────────────┐
                  │  tools/list             │  ← 先确认服务端实际开放了哪些 Tool
                  │  （实测 35 个）           │     只调用开放且只读的
                  └───────────┬─────────────┘
                              │
    ┌──────────────┬──────────┴──────────┬──────────────┬──────────────┐
    ▼              ▼                     ▼              ▼              ▼
query-my-      query-my-             available-      mall-points-    query-lottery-
account        coupons               coupons         products        info
    │              │                     │              │              │
PointsAccount  List[Coupon]        List[Coupon]   List[MallProduct]  LotteryInfo
    │              │                     │              │              │
    │              └─────────┬───────────┘              │              │
    │                        ▼                          │              ▼
    │              estimate_coupon_value()               │      lottery_expected_value()
    │              （券名正则 + 菜单价匹配）               │      （面值解析 + 效用加权）
    │                                                   ▼
    │                                          infer_point_rate()
    │                                          （仅在架商品中位数）
    │                                                   │
    └──────────────────────────┬────────────────────────┘
                               ▼
                    query-nearby-stores  ──▶  storeCode
                               │
                               ├──▶ query-meals          （菜单价格）
                               └──▶ query-store-coupons  （该店可用券）
                               ▼
                    knapsack_redeem()  ──▶ build_plan()
                    （0/1 背包 DP）        （三路线 + 推荐）
                                              ▼
                                   终端报告 / 单文件 HTML / JSON
```

---

## 4. 降级策略

`source.py` 中的 `LiveSource.collect()` 会先调 `tools/list` 拿到服务端**当前实际开放**的 Tool 集合，
只调用已开放的接口，未开放的会在报告的「说明」区显式列出（而不是静默返回空）。

| 场景 | 行为 |
|---|---|
| 未提供 Token | 自动回退到 `--mock` 离线演示数据 |
| Token 失效（401） | 抛出明确错误并提示重新申请，同时建议先用 `--mock` 跑通流程 |
| 触发限流（429） | 提示降低调用频率 |
| 某 Tool 未开放 | 跳过该部分数据，在报告里注明，缺失部分不参与计算 |
| 业务错误（`success:false`） | 记录 `[code] message` 到报告说明区 |
| 门店解析失败 | 降级为「内置参考价表 + 券名解析」，报告仍可生成 |
| 字段名变更 | `domain.py` 的别名表覆盖多种候选键名，解析不出的项计入 `unparsed` |
| TLS / 连接中断 | 自动重连重试（3 次，退避） |

---

## 5. 字段映射与容错

所有解析都通过别名表完成（`domain.py` 的 `_ALIASES`），而不是写死单一字段名。

| 标准字段 | 候选键名（部分） |
|---|---|
| 可用积分 | `availablePoint` / `available` / `usable` / `可用积分` |
| 累计积分 | `accumulativePoint` / `accumulative` / `totalEarned` / `累计积分` |
| 已过期积分 | `expiredPoint` / `expired` / `已过期积分` |
| 即将过期积分 | `currentMouthExpirePoint` / `nextMouthExpirePoint` / `expiringPoints` |
| 商品名 | `spuName` / `couponName` / `name` / `title` |
| 积分价 | `point` / `points` / `costPoints` / `drawPoint` / `积分` |
| 面值 | `price` / `cash` / `amount`（**商品券恒为 0，需从名称反推**） |
| 分类 | `catName` / `category` / `cat` |
| 下架时间 | `downTime` / `expireDate` / `endTime` / `有效期` |
| 抽奖消耗 | `drawPoint` / `costPoints` / `消耗积分` |
| 中奖概率 | `probability` / `prob` / `rate` / `chance`（**官方不返回**） |

列表型返回兼容四种形态：直接 `list` / `dict` 含 `coupons`·`items`·`list` 等列表键 /
`dict` 被包了一层 / 单条 `dict`。

---

## 6. 业务价值

| 痛点 | 本项目的处理 | 价值 |
|---|---|---|
| 积分到期无感知 | `query-my-account` 的本月/下月到期积分 + 倒计时预警 | 避免真金白银的沉没损失 |
| 券领了不用、过期才发现 | 券名解析 + 菜单价匹配估算真实面值 + 按剩余天数排序 | 让每一张券都落地 |
| 抽奖"到底值不值"说不清 | 效用加权的期望值、标准差、颗粒无收概率 | 从"抽奖"变成"决策" |
| 商城兑换选哪个划算 | 0/1 背包求解 + 效用系数 + **下架过滤** | 在积分上限内拿到最大效用价值，且买得到 |
| 一次性决策缺全局视角 | 稳健 / 平衡 / 进攻三路线量化对比 | 风险与收益自己选 |

---

## 7. 合规声明

- 本项目**仅使用**麦当劳中国官方 MCP Server 开放的 Tool，**不抓取网页、不逆向、不绕过任何鉴权**。
- 全程**只读**，不创建订单、不发起支付、不领取优惠券、不修改账户信息。
- MCP Token 仅从环境变量读取，**不写入代码、配置或任何提交到 GitHub 的文件**。
- 所有价格与餐品信息以麦当劳官方渠道实时结果为准；本项目输出的估值仅为个人消费决策参考。
- 本项目为参赛者独立开发，**非麦当劳官方产品**，与麦当劳中国及其关联公司无任何隶属或背书关系。
