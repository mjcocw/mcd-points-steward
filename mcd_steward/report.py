"""报告渲染：终端文本 + 单文件 HTML。

HTML 报告刻意做成"零外部依赖的单文件"：
评审者双击就能打开、可以直接截图发群里，不需要装任何东西。
"""

from __future__ import annotations

import html
from datetime import date, datetime
from typing import List

from .domain import McSnapshot
from .valuation import Plan, Route

# --------------------------------------------------------------------------- #
# 终端报告
# --------------------------------------------------------------------------- #

def render_terminal(plan: Plan, snapshot: McSnapshot, width: int = 68) -> str:
    """生成终端可读的报告。"""
    L: List[str] = []
    bar = "═" * width
    thin = "─" * width

    L.append(bar)
    L.append("  麦麦积分资产体检报告  McPoints Steward")
    L.append(f"  生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
             + ("   [离线演示数据]" if plan.is_mock else "   [真实账户数据]"))
    L.append(bar)
    L.append("")

    # 总览
    L.append("【资产总览】")
    L.append(f"  可用积分      {plan.account_total:>8,}")
    L.append(f"  名义汇率      {plan.rate.nominal:.4f} 元/积分   （{plan.rate.basis}）")
    L.append(f"  积分折合价值  {plan.account_total * plan.rate.nominal:>8.1f} 元")
    L.append(f"  零成本收益    {plan.free_value:>8.1f} 元   （优惠券 + 可领券）")
    if plan.lottery.available:
        L.append(f"  抽奖期望      {plan.lottery.per_draw_cny:>8.2f} 元/次"
                 f"   （每次 {plan.lottery.cost_points} 积分）")
    L.append("")

    # 到期预警
    L.append("【到期预警】")
    alerts = sorted(plan.expiry_alerts, key=lambda a: a.days_left)
    if not alerts:
        L.append("  没有临近到期的积分或优惠券")
    for a in alerts:
        if a.kind == "points":
            L.append(f"  ⚠ 积分 {a.points:>6,} 份  {a.days_left:>3} 天后过期"
                     f"   约值 {a.value_cny:.1f} 元")
        elif a.kind == "expired":
            L.append(f"  ✖ 积分 {a.points:>6,} 份  已经过期"
                     f"   约值 {a.value_cny:.1f} 元   —— 无法挽回")
        else:
            L.append(f"  ⚠ 优惠券 {a.label[:18]:<18} {a.days_left:>3} 天后过期"
                     f"   约值 {a.value_cny:.1f} 元")
    L.append("")

    # 路线对比
    L.append("【三条路线对比】")
    L.append(thin)
    L.append(f"  {'路线':<16}{'期望值':>9}{'最差情况':>10}{'积分用掉':>10}")
    L.append(thin)
    for r in plan.routes:
        mark = " ←推荐" if plan.recommended and r.key == plan.recommended.key else ""
        L.append(f"  {r.title[:14]:<16}{r.expected_cny:>8.1f}元{r.worst_cny:>9.1f}元"
                 f"{r.draw_points + r.redeem.spent_points:>9,}分{mark}")
    L.append(thin)
    L.append("")

    # 推荐方案
    if plan.recommended:
        L.append(f"【推荐方案】{plan.recommended.title}")
        for i, s in enumerate(plan.recommended.steps):
            L.append(f"  {'①②③④⑤⑥⑦⑧'[i] if i < 8 else f'({i+1})'} {s}")
        if plan.recommendation_reason:
            L.append("")
            L.append(f"  依据：{plan.recommendation_reason}")
        L.append("")

    if plan.lottery.available:
        L.append("【抽奖期望值拆解】")
        L.append(f"  活动：{plan.lottery.name}   概率来源：{plan.lottery.probability_source}")
        for line in plan.lottery.lines:
            L.append(line)
        lose_txt = (f"颗粒无收概率 {plan.lottery.lose_prob * 100:.0f}%"
                    if plan.lottery.lose_prob > 0 else "颗粒无收概率 未知（官方未公布概率）")
        L.append(f"  单次期望 {plan.lottery.per_draw_cny:.2f} 元"
                 f"   标准差 {plan.lottery.stdev_cny:.2f} 元   {lose_txt}")
        if plan.lottery.warning:
            L.append(f"  ! {plan.lottery.warning}")
        L.append("")

    if plan.recommended and plan.recommended.redeem.items:
        L.append("【兑换清单】")
        for it in plan.recommended.redeem.items:
            L.append(f"  · {it.product.name:<24} {it.points:>6,} 分"
                     f"   效用价值 {it.value_cny:>6.2f} 元   （{it.reason}）")
        L.append("")

    if plan.notes:
        L.append("【说明】")
        for n in plan.notes:
            L.append(f"  · {n}")
        L.append("")

    L.append(bar)
    L.append("  数据来源：麦当劳官方 MCP Server。本报告为个人消费决策参考，")
    L.append("  餐品信息、价格与供应状态以麦当劳官方渠道实时结果为准。")
    L.append(bar)
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# HTML 报告
# --------------------------------------------------------------------------- #

_CSS = """
:root{--ink:#1a1a1a;--sub:#6b6b6b;--line:rgba(0,0,0,.10);--bg:#f7f6f3;--card:#fff;
--red:#D8382F;--amber:#E8890C;--green:#1D9E75;--blue:#185FA5;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
line-height:1.6;padding:28px 16px;-webkit-font-smoothing:antialiased}
.wrap{max-width:760px;margin:0 auto}
.hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:22px}
h1{font-size:22px;font-weight:500;letter-spacing:.3px}
.sub{font-size:13px;color:var(--sub);margin-top:4px}
.badge{font-size:12px;padding:3px 10px;border-radius:999px;background:#FDECEA;color:var(--red);
border:1px solid rgba(216,56,47,.25);white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.m{background:var(--card);border:.5px solid var(--line);border-radius:12px;padding:14px 16px}
.m .k{font-size:12px;color:var(--sub)}
.m .v{font-size:25px;font-weight:500;margin-top:3px;letter-spacing:-.5px}
.m .v small{font-size:13px;font-weight:400;color:var(--sub);margin-left:3px}
.card{background:var(--card);border:.5px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:16px}
h2{font-size:15px;font-weight:500;margin-bottom:14px;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:3px;height:14px;background:var(--red);border-radius:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:500;color:var(--sub);font-size:12px;padding:0 10px 8px 0;
border-bottom:.5px solid var(--line)}
td{padding:9px 10px 9px 0;border-bottom:.5px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
tr.pick td{background:#FFF8F2}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;white-space:nowrap}
.p-red{background:#FDECEA;color:var(--red)}
.p-amber{background:#FEF3E2;color:var(--amber)}
.p-green{background:#E4F5EF;color:var(--green)}
.p-blue{background:#E9F1FB;color:var(--blue)}
.alert{display:flex;gap:11px;align-items:flex-start;padding:11px 13px;border-radius:10px;
background:#FDECEA;border:.5px solid rgba(216,56,47,.18);margin-bottom:9px}
.alert.warn{background:#FEF3E2;border-color:rgba(232,137,12,.22)}
.alert.gone{background:#F2F1EE;border-color:rgba(0,0,0,.10)}
.alert.gone .n{color:var(--sub)}
.alert .t{font-size:13px;flex:1}
.alert .t b{font-weight:500}
.alert .d{font-size:12px;color:var(--sub);margin-top:2px}
.alert .n{font-size:15px;font-weight:500;color:var(--red);white-space:nowrap}
.alert.warn .n{color:var(--amber)}
ol.steps{margin:0;padding-left:0;list-style:none;counter-reset:s}
ol.steps li{counter-increment:s;position:relative;padding:9px 0 9px 32px;font-size:13.5px;
border-bottom:.5px solid var(--line)}
ol.steps li:last-child{border-bottom:none}
ol.steps li::before{content:counter(s);position:absolute;left:0;top:9px;width:21px;height:21px;
border-radius:50%;background:var(--red);color:#fff;font-size:12px;display:flex;
align-items:center;justify-content:center;font-weight:500}
.note{font-size:12.5px;color:var(--sub);background:var(--bg);border-radius:8px;padding:9px 12px;margin-top:10px}
.lot{display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;
border-bottom:.5px solid var(--line)}
.lot:last-child{border-bottom:none}
.lot .r{color:var(--sub);font-variant-numeric:tabular-nums}
.bar{height:6px;border-radius:3px;background:#EEECEA;overflow:hidden;margin-top:5px}
.bar i{display:block;height:100%;background:var(--green);border-radius:3px}
.ft{font-size:11.5px;color:var(--sub);text-align:center;padding:18px 8px 6px;line-height:1.7}
@media print{body{background:#fff;padding:0}.card{break-inside:avoid}}
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render_html(plan: Plan, snapshot: McSnapshot) -> str:
    """生成单文件 HTML 报告。"""
    today = date.today()
    parts: List[str] = []
    A = parts.append

    A(f"<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    A("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    A(f"<title>麦麦积分资产体检报告 · {today.isoformat()}</title>")
    A(f"<style>{_CSS}</style></head><body><div class=\"wrap\">")

    # 头部
    A("<div class=\"hd\"><div>")
    A(f"<h1>麦麦积分资产体检报告</h1>")
    A(f"<div class=\"sub\">McPoints Steward · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
      f" · 数据来源：麦当劳官方 MCP Server</div>")
    A("</div>")
    if plan.is_mock:
        A("<span class=\"badge\">离线演示数据</span>")
    A("</div>")

    # 总览
    A("<div class=\"grid\">")
    A(f"<div class=\"m\"><div class=\"k\">可用积分</div><div class=\"v\">{plan.account_total:,}<small>分</small></div></div>")
    A(f"<div class=\"m\"><div class=\"k\">积分名义价值</div><div class=\"v\">{plan.account_total * plan.rate.nominal:.0f}<small>元</small></div></div>")
    A(f"<div class=\"m\"><div class=\"k\">零成本收益</div><div class=\"v\">{plan.free_value:.0f}<small>元</small></div></div>")
    if plan.lottery.available:
        A(f"<div class=\"m\"><div class=\"k\">抽奖单次期望</div><div class=\"v\">{plan.lottery.per_draw_cny:.2f}<small>元</small></div></div>")
    A("</div>")

    # 到期预警
    A("<div class=\"card\"><h2>到期预警</h2>")
    alerts = sorted(plan.expiry_alerts, key=lambda a: a.days_left)
    if not alerts:
        A("<div class=\"note\">没有临近到期的积分或优惠券。</div>")
    for a in alerts:
        if a.kind == "points":
            cls, label = ("warn" if a.days_left > 7 else ""), f"{a.points:,} 份积分"
            A(f"<div class=\"alert {cls}\"><div class=\"t\"><b>{_e(a.label or '即将过期积分')}</b>"
              f"<div class=\"d\">约值 {a.value_cny:.1f} 元 · 建议优先用掉</div></div>"
              f"<div class=\"n\">{a.days_left} 天</div></div>")
        elif a.kind == "expired":
            A(f"<div class=\"alert gone\"><div class=\"t\"><b>已过期积分 {_e(a.label)}</b>"
              f"<div class=\"d\">约值 {a.value_cny:.1f} 元 · {_e(a.action or '无法挽回')}</div></div>"
              f"<div class=\"n\">已失效</div></div>")
        else:
            cls = "warn" if a.days_left > 7 else ""
            A(f"<div class=\"alert {cls}\"><div class=\"t\"><b>{_e(a.label)}</b>"
              f"<div class=\"d\">{_e(a.action)}</div></div>"
              f"<div class=\"n\">{a.days_left} 天</div></div>")
    A("</div>")

    # 路线对比
    A("<div class=\"card\"><h2>三条路线对比</h2><table>")
    A("<tr><th>路线</th><th>期望值</th><th>最差情况</th><th>积分用掉</th><th>颗粒无收</th></tr>")
    for r in plan.routes:
        pick = plan.recommended is not None and r.key == plan.recommended.key
        if r.draws > 0 and plan.lottery.lose_prob <= 0:
            lose = "未知"
        elif r.draws > 0:
            lose = f"{r.all_lose_prob * 100:.0f}%"
        else:
            lose = "—"
        badge = " <span class=\"pill p-red\">推荐</span>" if pick else ""
        A(f"<tr class=\"{'pick' if pick else ''}\"><td>{_e(r.title)}{badge}</td>"
          f"<td><b>{r.expected_cny:.1f} 元</b></td>"
          f"<td>{r.worst_cny:.1f} 元</td>"
          f"<td>{r.draw_points + r.redeem.spent_points:,} 分</td>"
          f"<td>{lose}</td></tr>")
    A("</table>")
    for r in plan.routes:
        A(f"<div class=\"note\"><b>{_e(r.title)}</b> — {_e(r.desc)}</div>")
    A("</div>")

    # 推荐方案
    if plan.recommended:
        A("<div class=\"card\"><h2>推荐执行清单</h2>")
        if plan.recommendation_reason:
            A(f"<div class=\"note\" style=\"margin:0 0 12px\"><b>为什么选它：</b>{_e(plan.recommendation_reason)}</div>")
        A("<ol class=\"steps\">")
        for s in plan.recommended.steps:
            A(f"<li>{_e(s)}</li>")
        A("</ol>")
        for n in plan.notes:
            A(f"<div class=\"note\">{_e(n)}</div>")
        A("</div>")

    # 抽奖拆解
    if plan.lottery.available:
        A("<div class=\"card\"><h2>抽奖期望值拆解</h2>")
        A(f"<div class=\"sub\" style=\"margin-bottom:10px\">{_e(plan.lottery.name)} · "
          f"每次消耗 {plan.lottery.cost_points} 积分 · "
          f"概率来源：{_e(plan.lottery.probability_source)}</div>")
        max_p = max((p.probability or 0) for p in snapshot.lottery.prizes) if snapshot.lottery else 1
        for line, prize in zip(plan.lottery.lines, snapshot.lottery.prizes if snapshot.lottery else []):
            p = prize.probability or 0
            w = int(p / max_p * 100) if max_p else 0
            left, right = line.rsplit("  贡献", 1)
            A(f"<div class=\"lot\"><span>{_e(left.strip())}<div class=\"bar\">"
              f"<i style=\"width:{w}%\"></i></div></span>"
              f"<span class=\"r\">贡献{_e(right.strip())}</span></div>")
        lose_txt = (f"颗粒无收概率 {plan.lottery.lose_prob * 100:.0f}%"
                    if plan.lottery.lose_prob > 0 else "颗粒无收概率未知（官方未公布概率）")
        A(f"<div class=\"note\">单次期望 <b>{plan.lottery.per_draw_cny:.2f} 元</b> · "
          f"标准差 {plan.lottery.stdev_cny:.2f} 元 · {lose_txt} · "
          f"最高奖 {plan.lottery.best_prize} 概率 {plan.lottery.best_prize_prob * 100:.1f}%</div>")
        A("</div>")

    # 兑换清单
    if plan.recommended and plan.recommended.redeem.items:
        A("<div class=\"card\"><h2>兑换清单</h2><table>")
        A("<tr><th>商品</th><th>需要积分</th><th>效用价值</th><th>依据</th></tr>")
        for it in plan.recommended.redeem.items:
            A(f"<tr><td>{_e(it.product.name)}</td><td>{it.points:,}</td>"
              f"<td>{it.value_cny:.2f} 元</td><td>{_e(it.reason)}</td></tr>")
        A("</table></div>")

    A(f"<div class=\"ft\">本报告由麦麦积分资产管家（McPoints Steward）生成，基于麦当劳官方 MCP Server 数据。<br>"
      f"为个人消费决策参考，不构成任何官方承诺；餐品信息、价格与供应状态以麦当劳官方渠道实时结果为准。</div>")
    A("</div></body></html>")
    return "".join(parts)
