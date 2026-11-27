# Corp_Daily_News

给**特定企业/组织**搭建自己的行业新闻日报。每天自动采集信源 → LLM 判定归类 → 按业务线分组 → 发邮件/飞书 → 写 Markdown 库。

> 设计思路参考 [AIHOT](https://github.com/KKKKhazix/AIHOT)（MIT）。本项目为**独立实现**，非 fork：AIHOT 是 TypeScript 网站框架，本项目是 Python 脚本管线，输出为邮件 + 飞书 + Obsidian Markdown。详见 [LICENSE](LICENSE) 的 attribution 说明。

---

## 它解决什么问题

公司里每天需要有人「看行业新闻，挑出跟我们有关系的，转给团队」。这件事：

- 人工做要 1-2 小时/天，且不稳定
- 通用新闻聚合站按热度排，跟你的业务无关
- 现成的行业媒体订阅，噪声太大

本项目把它变成一条全自动管线，核心是把**「什么算有用」写成可配置的判据**，而不是靠算法猜。

## 核心设计

```
采集          判定            过滤              输出
────          ────            ────              ────
RSS/列表页 → LLM 评分归类 → 硬门 + 门槛 →  邮件 HTML
15+ 信源      keep/score     渠道稿排除      飞书突发推送
条件请求      line/role      政策实质门      Obsidian MD
(ETag)        impact/type    跨天去重        TOP5 + 分线
```

**几处值得单独说的设计**（都是一路踩坑改出来的）：

| 机制 | 为什么 |
|---|---|
| **硬门与软评分分离** | 关键词堆满但跑偏的稿子，靠加权分压不住。硬门单独拦。 |
| **事件级去重（主体交集 + 字面相似）** | 中文财经标题模板高度雷同，纯字面会把两家不相干的公司聚成一条。 |
| **跨天去重 + 突发接续** | 昨天推过的突发，今天的日报要能看到，不能因为「昨天推过」就消失。 |
| **渠道稿硬门** | 「某分销商开售某大厂 XX 芯片」会被判成大厂动态，实际对研发零情报价值。 |
| **政策实质门** | 只有「管制再升级 + 某公司表态国产化」而无具体法规/日期/税率的，是废话。 |
| **非事件稿 -20** | 研究报告、拆解实测、趋势综述没有「谁做了什么」，扣分而非直接杀。 |
| **公司 pitch 事实底座** | 模型不知道你公司是谁，靠一篇 pitch 建立认知，才能写出具体的招聘理由。 |
| **判定缓存** | 同一 URL 不重复烧 token。改提示词时要记得绕过缓存，否则改动不生效。 |

## 快速开始

### 1. 环境

```bash
git clone <your-repo> Corp_Daily_News
cd Corp_Daily_News
python3 -m venv .venv && source .venv/bin/activate
pip install requests
```

需要 Python 3.10+。全部依赖只有 `requests`。

### 2. 配置密钥

```bash
export DEEPSEEK_API_KEY=sk-...        # LLM 判定用，OpenAI 兼容接口
export DAILY_MAIL_TO=you@example.com  # 邮件收件人
export DAILY_FEISHU_OPEN_ID=ou_...    # 可选，飞书推送
```

邮件发送依赖一个 SMTP 脚本（默认 `scripts/smtp.js`，Node）。不用邮件就改 `src/main.py` 的发信段。

### 3. 配置（不改也可先跑，想改就复制一份）

配置采用**两层加载**，不需要先删任何东西：

```
src/config_local.py    ← 你的私有配置（优先加载，已 gitignore）
src/config.example.py  ← 完整示例（回退，clone 下来就能跑）
```

**只想先看看效果** → 什么都不做，直接用示例配置跑 `--dry`。

**要改成自己的公司** →

```bash
cp src/config.example.py src/config_local.py
# 然后只改 config_local.py，别动 config.example.py
```

`src/config.py` 是加载层，负责选文件、算派生值、启动自检，**你不需要改它**。

#### config_local.py 里只需改 6 处

```python
# ① 公司信息
COMPANY = "你的公司全称"
COMPANY_TICKER = "000001.SH"
REPORT_NAME = "你们日报的名字"
SELF_ALIASES = ["公司简称", "EnglishName", "000001"]
INDUSTRY_NAME = "你们所在的行业"

# ② 业务线 / 产品线  ← 最关键，决定新闻怎么归类
PRODUCT_LINES = {
    "line_a": {"name": "业务线A", "tag": "...", "md": "...",
               "kw": ["关键词1", "关键词2"]},
}

# ③ 竞对   ④ 客户    ⑤ 信源
COMPETITORS = {"分组名": ["公司A", "公司B"]}
CUSTOMERS  = {"分组名": ["客户A", "客户B"]}
SOURCES    = [{"id": "...", "name": "...", "kind": "rss", ...}]

# ⑥ 播报（也可走环境变量）
MAIL_TO = "you@example.com"
FEISHU_OPEN_ID = "ou_xxx"
```

其余字段（`DISTRIBUTORS` / `POLICY_FACT_RE` / `ALERT_*` / `THRESHOLDS`）是**通用规则**，
沿用默认即可。每个字段在 `config.example.py` 里都有「为什么需要这条」的注释。

#### 启动自检

配置有问题会在跑之前先告诉你，而不是跑到一半炸：

```bash
python -c "import sys;sys.path.insert(0,'src');import config;print(config.check(verbose=True))"
```

```
配置来源: config_local.py
公司    : 你的公司 / 你的日报
业务线  : 6 条 ['line_a', 'line_b', ...]
竞对/客户: 125 / 59
信源    : 15 个（启用 14）
输出目录: /path/to/Corp_Daily_News
自检: OK
```

检查项包括：业务线为空、竞对为空、无信源、邮箱未配置——这四件是新人最常错的地方。

### 4. 写公司 pitch

`pitch/company-pitch.md` 按模板填。**这一步不要跳**——模型不知道你公司是做什么的，没有这篇它写出来的「为什么该选我们」全是「平台广阔、成长空间大」这种废话。

### 5. 跑

```bash
python src/run_daily.py --dry    # 演练，写入 /tmp，不发信
python src/run_daily.py          # 正式，发邮件
python src/poll.py               # 突发轮询（每 10 分钟）
```

### 6. 挂定时

```cron
50 6 * * *   cd /path/to/Corp_Daily_News && python src/run_daily.py
0  8 * * *   cd /path/to/Corp_Daily_News && python src/run_daily.py --check
*/10 * * * * cd /path/to/Corp_Daily_News && python src/poll.py
```

## 如何适配到你的企业

这是本项目和其他新闻聚合工具的主要差别：**判据是显式写在配置和提示词里的，不是黑盒模型猜的**。

### 改造顺序（建议）

**第一步：定业务线。** 打开 `src/config_local.py`（还没建就先复制）的 `PRODUCT_LINES`。这是整个系统的骨架——新闻按它归类，TOP5 按它排序，邮件按它分栏。填的时候只问一个问题：**你们团队是按什么分工的？** 按分工填，不要按行业教科书填。

关键词给 10-20 个，中英文都要（`"AC-DC"`, `"ACDC"`, `"电源管理"`）。宁可多，因为这一步只用于预筛，精判在后面。

**第二步：定竞对和客户。** `COMPETITORS` / `CUSTOMERS`。这些名单直接影响 `role` 判定和 `score`（竞对动作 +20）。**不要只填头部**——只填 TI/ADI 会漏掉一堆国产同行，反而那些才是真正抢人的。

**第三步：写信源。** `SOURCES` 里每条三种字段必填：`kind`（rss / web_list）、`url`、`pattern`（web_list 用正则抓链接）。先用浏览器打开目标页，F12 看文章链接长什么样，再写正则。

**第四步：调门槛。** `THRESHOLDS = {"T1": 40, "T1_5": 44, "T2": 44}`。跑一次 dry-run 看日志里的分数分布，再定。模型输出通常集中在 40-65，门槛设太高会全灭。

**第五步：写 pitch。** 见上一节。

**第六步：改提示词里的行业描述。** `src/analyze.py` 的 `build_prompt()` 里有一句 `${INDUSTRY_NAME} 设计公司`，`src/alert.py` 的突发判定也有类似表述。改成你自己行业的说法。

### 不用改的地方

- `dedup.py` — 去重算法与行业无关
- `collect.py` — 抓取解析通用
- `state.py` — 状态层通用
- `render.py` — Markdown 输出通用

## 项目结构

```
├── src/
│   ├── config.py        ← 加载层：选配置、算派生值、启动自检（不用改）
│   ├── config.example.py ← 完整可运行示例，带逐字段注释（参照这份改）
│   ├── config_local.py  ← 你的私有配置（gitignore，自己创建）
│   ├── collect.py       ← 采集：RSS + 网页列表，ETag 条件请求
│   ├── dedup.py         ← 事件级去重：主体交集 + 字面相似
│   ├── analyze.py       ← 判定：评分/归类/摘要/招聘素材
│   ├── alert.py         ← 突发判定（A 类竞对动作 / B 类行业冲击）
│   ├── main.py          ← 主流水线：采集→判定→过滤→聚簇→输出
│   ├── poll.py          ← 突发轮询：每 10 分钟条件请求
│   ├── render.py        ← Markdown 输出（Obsidian 兼容）
│   ├── mail.py          ← 邮件 HTML 渲染（窄窗口自适应）
│   ├── state.py         ← SQLite 状态：已见 URL / 历史 / 突发记录
│   └── run_daily.py     ← 日报入口，含重试与兜底告警
├── pitch/
│   └── company-pitch.md   ← 公司事实底座模板（必填）
└── data/  logs/  vault/   ← 运行时生成
```

## 已知限制

- **判定是关键词 + LLM，没有语义检索**。能判断「这条讲的是不是 MEMS 工艺」，但难区分「做了 MEMS 工艺研发」和「MEMS 只是项目里的一个环节」。
- **英文信源的摘要质量差**。部分站点只给英文 og:description，中文摘要会退化成标题。
- **改提示词后必须绕过判定缓存**。缓存以 `url|title` 为 key，不清理的话新提示词不生效（这是一个反直觉的坑，本项目踩过）。
- **突发判定和日报判定是两套提示词**，口径需人工保持同步。

## 许可与致谢

本项目采用 **MIT License**（与 AIHOT 一致），全文见 [LICENSE](LICENSE)。

### 与 AIHOT 的关系

本项目的**设计思路**受 [AIHOT](https://github.com/KKKKhazix/AIHOT)（MIT，by KKKKhazix）启发——尤其是那个核心构想：「一个自己找热点、自己写日报的框架，把信源和精选标准换成你的，它就是你的行业热点站」。

**但本项目不是 AIHOT 的 fork**，两者不共享任何源码：

| | AIHOT | 本项目 |
|---|---|---|
| 语言 | TypeScript | Python 3.10+ |
| 架构 | DB + API + Worker，Docker，SSR 网站 | 单进程脚本管线，无网站 |
| 输出 | 网站 | 邮件 + 飞书 + Markdown 库 |
| 定位 | 面向公众的行业热点站 | 面向单一企业的内部日报 |

原始构想与框架思路的功劳属于 AIHOT 作者。本实现中的任何 bug 由本项目自负。

如果你想要的是一个**公开的行业热点网站**，建议直接用 [AIHOT](https://github.com/KKKKhazix/AIHOT)；本项目解决的是「一家公司每天给自己人挑相关新闻」这个更窄的场景。
