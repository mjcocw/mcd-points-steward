# 参赛操作清单（PUBLISH）

> 报名截止：**2026-10-25 23:59** ｜ 定榜：**10-26 00:00** ｜ 排名 = GitHub 公开 Star 数
> 官方仓库：https://github.com/M-China/mcd-developer-innovation-challenge
>
> ⚠️ **仓库地址已按本机 git 配置回填为 `mojc`**。如果你的 GitHub 用户名不是 `mojc`，
> 推送前先跑这一条（把所有文档里的地址一次性改掉）：
> ```bash
> cd C:/Users/Administrator/WorkBuddy/2026-10-22-12-44-16/mcd-points-steward
> sed -i "s|mojc|<你的用户名>|g" README.md PUBLISH.md docs/*.md
> ```
> 改完记得 `git add -A && git commit -m "docs: 修正仓库地址" && git push`。

---

## 第 1 步：推送仓库（今天就做）

**① 在 GitHub 新建仓库**
- 仓库名：`mcd-points-steward`
- 选 **Public**（必须是公开仓库）
- ⚠️ **不要**勾选 "Add a README"（本地已有，否则会冲突）

**② 关联远程并推送**

```bash
cd C:/Users/Administrator/WorkBuddy/2026-10-22-12-44-16/mcd-points-steward
git remote add origin https://github.com/mojc/mcd-points-steward.git
git branch -M main
git push -u origin main
```

**③ 检查占位符是否还有残留**

```bash
grep -rn "你的用户名\|你的仓库地址\|<repo>" --include="*.md" .
```

应该只在上面那条 `sed` 提示里出现（那是命令示例，不是待替换内容）。

---

## 第 2 步：开启 GitHub Pages（把在线演示挂上去）

仓库已经有现成的 `site/` 目录（`index.html` + `report.html` + `hero.svg`），一条命令就能发布：

```bash
cd C:/Users/Administrator/WorkBuddy/2026-10-22-12-44-16/mcd-points-steward
git subtree push --prefix site origin gh-pages
```

> 这会把 `site/` 的内容作为 `gh-pages` 分支推上去，是 GitHub Pages 最省事的做法。

然后在 GitHub 上：

1. 仓库 → **Settings** → 左侧 **Pages**
2. **Source** 选 `Deploy from a branch`
3. **Branch** 选 `gh-pages` / 目录选 `/ (root)` → **Save**
4. 等 1~2 分钟，得到 `https://mojc.github.io/mcd-points-steward/`
5. **验证链接能打开**（浏览器访问一下，确认报告正常渲染）

README 首屏的「🍔 在线体验」已经指向这个地址（`https://mojc.github.io/mcd-points-steward/`），
Pages 生效后**无需再改任何文件**。

> ⚠️ 顺序很重要：**先推 `gh-pages` 分支并开启 Pages，再确认链接能打开**，
> 否则 README 首屏会挂一个 404，反而拉低点击转化。
> 如果暂时不想折腾 Pages，把 README 首屏那一行删掉也不影响其他部分 ——
> 但**有在线演示的 README 转化率明显更高**，强烈建议开。

---

## 第 3 步：报名 Issue（⏰ 最晚 10-25 23:59，别拖）

在 **M-China/mcd-developer-innovation-challenge** 仓库 → **Issues** → **New issue** 填：

**Issue 标题**（一行，不要换行）：
```
麦麦积分资产管家 McPoints Steward — 把麦当劳积分从"看得见"变成"算得清"
```

**Issue 正文**（严格照抄这个格式，**标题和正文之间、正文各字段之间都不要用换行符**）：
```
【参赛申请】
项目名称：麦麦积分资产管家 McPoints Steward
项目地址：https://github.com/mojc/mcd-points-steward
项目简介：基于麦当劳官方 MCP 的积分资产体检工具，逆向出官方接口的六个隐藏行为（price 恒为 0、商城过半已下架、抽奖不公布概率等），用个人边际效用折扣 + 抽奖期望值 + 0/1 背包算出"该抽还是该换"。全程只读，零第三方依赖，无需 Token 也能 10 秒跑通。
```

> ⚠️ **官方校验很严，这几个坑我踩过**：
> 1. 标题与正文之间**不要有换行符**
> 2. 各字段之间**也不要换行**
> 3. 项目地址**不要用 Markdown 链接格式**（直接贴纯 URL）
> 4. 仓库必须是 **Public**
> 5. 仓库必须包含：`README.md`、`CONTEST_DECLARATION.md`（内容一字不可改）、`MCP_INTEGRATION.md`、源码
> 6. 想拿 **WorkBuddy 专项 3000 积分**，还要有 `workbuddy.md`（已包含）

**提交后看机器人回复**：
- 回复「报名成功」→ 你的仓库会出现在活动仓库的 Issue 列表里（**官方免费流量**）
- 回复失败原因 → 按提示改完重新发一个 Issue

---

## 第 4 步：传播（决定名次的一步）

文案都已写好，在 [`docs/promotion.md`](./docs/promotion.md)：

| 平台 | 文案位置 | 预估带来的 Star |
|---|---|---|
| 掘金 / 腾讯云社区 | `docs/devlog.md` 全文 | 20~60 ⭐ |
| V2EX | promotion.md 第二节 | 5~15 ⭐ |
| 即刻 / 小红书 | promotion.md 第三节 | 5~20 ⭐ |
| 朋友圈 / 群聊 | promotion.md 第四节 | 3~10 ⭐ |
| X / Twitter | promotion.md 第五节 | 0~3 ⭐ |
| 官方 Issue 列表曝光 | 报名成功后自动获得 | 3~8 ⭐ |

**三个转化率最高的动作**（按性价比排序）：

1. **README 首屏挂在线演示链接** —— 别人点开就能看到效果，不用 clone、不用装 Python。
   这是本次比赛里**最容易被忽略、但提升最大**的一步。
2. **README 首屏放真实运行截图** —— 终端报告的代码块本身就是最好的图，比任何设计稿都可信。
3. **一句话差异点** —— 放在标题正下方：
   > 「不是帮你省钱的工具，是帮你把积分真正花出去的会计」

---

## 第 5 步：定榜前最后检查（10-25 白天）

```bash
# 1. 确认 5 个必需文件都在
git ls-files | grep -E "README.md|CONTEST_DECLARATION.md|MCP_INTEGRATION.md|workbuddy.md"

# 2. 确认没有泄露 Token
git ls-files -z | xargs -0 grep -n "Bearer [A-Za-z0-9]\{20,\}" && echo "!!! 有泄露 !!!" || echo "OK 无泄露"

# 3. 确认克隆后能跑通
cd /tmp && git clone https://github.com/mojc/mcd-points-steward.git && cd mcd-points-steward
python selftest.py && python main.py --mock --html /tmp/t.html && echo "OK 克隆后可跑通"
```

- [ ] 仓库已推送且为 Public
- [ ] README 无 `mojc` 占位符残留
- [ ] README 首屏：横幅 + 在线演示链接 + 一句话差异点
- [ ] 报名 Issue 已提交且收到「报名成功」回复
- [ ] 掘金/腾讯云文章已发布，链接回填到 README
- [ ] V2EX / 即刻 / 小红书 至少各发一条
- [ ] `workbuddy.md` 存在（3000 积分专项）
- [ ] 仓库无 Token 泄露
- [ ] 全新 clone 后 `python selftest.py` 通过

---

## ⚠️ 最后一件小事

Token 已经在对话里出现过一次。**赛后再去 https://open.mcd.cn/mcp 重新生成一个**，
同时把本地 `~/.workbuddy/mcp.json` 里的旧 Token 换掉。
仓库里没有任何 Token（已扫描确认），但环境变量和本地配置还留着旧的。
