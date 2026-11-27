"""公司日报 — 配置模板（完整可运行示例）

════════════════════════════════════════════════════════════════════
怎么用
════════════════════════════════════════════════════════════════════

不要直接改这个文件。复制一份，改名成 config_local.py：

    cp src/config.example.py src/config_local.py

然后只改 config_local.py。config.py 会自动优先加载它。
config_local.py 已加入 .gitignore，不会被提交，也不会覆盖别人的配置。

如果你什么都不做，系统会自动用本文件（config.example.py）跑起来——
所以 clone 下来就能跑通，不需要先删任何东西。

════════════════════════════════════════════════════════════════════
只需改 6 个地方
════════════════════════════════════════════════════════════════════

  ① 公司信息      COMPANY / REPORT_NAME / SELF_ALIASES / INDUSTRY_NAME
  ② 业务线        PRODUCT_LINES        ← 最关键，决定新闻怎么归类
  ③ 竞对名录      COMPETITORS          → 决定 role=竞对 和 +20 分
  ④ 客户名录      CUSTOMERS
  ⑤ 信源          SOURCES              ← 抓哪些站
  ⑥ 播报          MAIL_TO / FEISHU_OPEN_ID（走环境变量，通常不用改这里）

其余（DISTRIBUTORS / POLICY_FACT_RE / ALERT_* / THRESHOLDS）是通用规则，
沿用默认即可，除非你确知自己在调什么。

════════════════════════════════════════════════════════════════════
本示例的行业：模拟与嵌入式芯片
════════════════════════════════════════════════════════════════════
下面的产品线、竞对、客户、信源都是真实可用的配置，可以直接跑。
换成你自己的行业时，①③④⑤ 全部重写，②按你的团队分工重写。
"""

import os
import re

# ═══════════════════════════════════════════════════════════════════
# ① 公司信息
# ═══════════════════════════════════════════════════════════════════

# 公司中文全称。会写进 LLM 提示词，形如「你在为{COMPANY}做判定」。
COMPANY = "示例科技"

# 英文名或常用简称。
COMPANY_EN = "ExampleTech"

# 股票代码。没有就留空字符串。
COMPANY_TICKER = "000000.SH"

# 日报标题前缀。邮件标题会是「{REPORT_NAME} · 2026-11-27 早报」。
REPORT_NAME = "行业情报"

# 识别「自家新闻」的别名。用于：
#   - 拼 CN_VENDOR_RE（综合列表页的 must_match 过滤）
#   - 判断某条新闻是否在讲自己
# 中英文、股票代码都放进来，宁多勿少。
SELF_ALIASES = ["示例科技", "ExampleTech", "000000"]

# 行业名，写进提示词。形如「{COMPANY}是{INDUSTRY_NAME}设计公司」。
INDUSTRY_NAME = "模拟与嵌入式芯片"

# 行业圈层词：命中任意一个，才认为这条新闻「可能与本公司相关」。
# 这一步是预筛，宁宽勿严——精判在后面的 LLM 评分。
INDUSTRY_KW = [
    "芯片", "半导体", "IC ", "晶圆", "封装", "封测", "制程", "代工", "EDA",
    "模拟", "功率器件", "MOSFET", "IGBT", "SiC", "碳化硅", "车规", "AEC-Q100",
    "ISO 26262", "ASIL", "流片", "量产",
    "semiconductor", "wafer", "foundry", "chip", "analog", "power device",
    "automotive grade", "tape-out",
]


# ═══════════════════════════════════════════════════════════════════
# ② 业务线 / 产品线  ← 最关键
# ═══════════════════════════════════════════════════════════════════
#
# 填写原则：只问一个问题——你们团队按什么分工？
# 按分工填，不要按行业教科书填。
#
# 每个 key（英文短名，小写）对应一个 dict：
#   name  : 显示名，邮件分栏标题用它
#   tag   : 标签短名，写进 Markdown 的 tag
#   md    : Obsidian 双链目标名
#   kw    : 匹配关键词，10-20 个，中英文都要
#
# 关于 kw：这一步只用于预筛和展示，不要求精确。宁可多写，
# 因为「看起来可能相关」的会进 LLM 精判，精判会把它刷掉。
#
# 下面是「模拟芯片行业」的真实配置，可直接用，也可整体替换。

PRODUCT_LINES = {
    "battery": {
        "name": "电池管理", "tag": "电池管理", "md": "产品线-电池管理",
        "kw": ["电荷泵", "快充", "无线充电", "Qi2", "锂电保护", "电量计", "电池管理",
               "充电协议", "PD3", "PD 3", "电池均衡", "gauge", "charger", "charging",
               "BMS", "battery", "cell balancing", "fuel gauge", "MPP", "WPC"],
    },
    "power": {
        "name": "电源管理", "tag": "电源管理", "md": "产品线-电源管理",
        "kw": ["AC-DC", "ACDC", "DC-DC", "DCDC", "LDO", "PMIC", "多相", "DrMOS", "LLC",
               "PFC", "GaN", "氮化镓", "电源管理", "power management", "buck", "boost",
               "buck-boost", "converter", "regulator", "PMU", "SBC", "EFuse", "eFuse",
               "hot swap", "48V", "12V", "POL", "power stage", "VRM", "server power"],
    },
    "driver": {
        "name": "智能驱动芯片", "tag": "智能驱动", "md": "产品线-智能驱动芯片",
        "kw": ["高边开关", "低边开关", "半桥", "全桥", "马达驱动", "电机驱动", "栅极驱动",
               "LED驱动", "背光驱动", "eFuse", "EFuse", "HSD", "LSD", "gate driver",
               "high-side", "low-side", "half-bridge", "motor driver", "solenoid",
               "LED driver", "smart switch", "load switch", "预驱", "pre-driver"],
    },
    "sensor": {
        "name": "传感芯片", "tag": "传感", "md": "产品线-传感芯片",
        "kw": ["传感器", "传感", "CIS", "CMOS图像", "图像传感器", "SPAD", "ToF", "dToF",
               "iToF", "单光子", "激光雷达", "LiDAR", "MEMS", "霍尔", "磁传感", "电流传感",
               "压力传感", "惯性", "IMU", "光传感", "sensor", "image sensor", "photodiode",
               "APD", "SiPM", "3D sensing", "structured light", "AFE", "信号链"],
    },
    "link": {
        "name": "传输芯片", "tag": "传输", "md": "产品线-传输芯片",
        "kw": ["CAN FD", "CANFD", "CAN", "LIN", "RS485", "RS-485", "RS232", "SerDes",
               "redriver", "retimer", "USB PD", "USB4", "Type-C", "电平转换",
               "level shift", "隔离", "isolator", "transceiver", "收发器", "以太网 PHY",
               "Ethernet PHY", "MIPI", "LVDS", "桥接", "bridge"],
    },
    "mcu": {
        "name": "MCU 芯片", "tag": "MCU", "md": "产品线-MCU芯片",
        "kw": ["MCU", "微控制器", "单片机", "RISC-V", "RISC V", "ARM Cortex", "Cortex-M",
               "POWERMCU", "embedded controller", "EC ", "SoC", "微处理器", "MPU"],
    },
}


# ── 角色判定关键词（通用，一般不用改）───────────────────────────────────
# LLM 判 role 时参考；也用于兜底规则。空列表表示靠 LLM 自己判。
ROLE_KW = {
    "竞对": ["竞对", "竞争对手", "competitor"],
    "客户": ["客户", "customer", "采用", "导入", "定点", "design win", "design-in"],
    "供应链": ["晶圆", "代工", "封测", "产能", "缺货", "涨价", "降价", "交期", "库存",
              "foundry", "capacity", "lead time", "inventory"],
    "政策": ["政策", "监管", "标准", "工信部", "发改委", "出口管制", "关税", "认证",
            "regulation", "standard", "export control", "tariff"],
    "行业": [],
}


# ═══════════════════════════════════════════════════════════════════
# ③ 竞对名录
# ═══════════════════════════════════════════════════════════════════
#
# 影响两件事：
#   1. role 判定（主体命中 → role=竞对）
#   2. score 加分（竞对实质动作 +20）
#
# 重要提醒：不要只填头部国际大厂。只填 TI/ADI 会漏掉一堆国产同行，
# 而那些往往才是真正跟你抢人的公司。宁可多填。
#
# 分组（dict 的 key）只是给人看的，程序会拍平成 COMPETITOR_SET。

COMPETITORS = {
    "国际大厂": [
        "TI", "德州仪器", "ADI", "亚德诺", "Maxim", "美信", "Infineon", "英飞凌",
        "STMicro", "意法半导体", "ST ", "NXP", "恩智浦", "Renesas", "瑞萨",
        "onsemi", "安森美", "Microchip", "MPS", "芯源系统", "Power Integrations",
        "Rohm", "罗姆", "Allegro", "Melexis", "迈来芯", "Navitas", "纳微",
        "Wolfspeed", "Silicon Labs", "Skyworks", "Qorvo", "Richtek", "立锜",
        "Silergy", "矽力杰", "Parade", "谱瑞", "Sony", "索尼", "Samsung", "三星电子",
        "ams-OSRAM", "艾迈斯欧司朗", "TDK", "InvenSense", "Bosch Sensortec",
    ],
    "国内同行": [
        "圣邦微", "圣邦股份", "杰华特", "芯朋微", "英集芯", "钰泰", "智融",
        "赛微微电", "希荻微", "帝奥微", "思瑞浦", "纳芯微", "士兰微", "华润微",
        "比亚迪半导体", "斯达半导", "芯导科技", "力芯微", "芯海科技", "必易微",
        "东科半导体", "亚成微", "硅动力", "英诺赛科", "能华微", "芯茂微",
        "上海贝岭", "贝岭", "南麟", "昂宝", "通嘉", "川土微", "芯力特", "龙迅",
        "集睿致远", "硅谷数模", "澜起科技", "兆易创新", "中颖电子", "国民技术",
        "极海半导体", "华大半导体", "复旦微电", "航顺芯片", "灵动微", "沁恒",
        "海思", "上海海思", "HiSilicon", "地平线", "黑芝麻智能", "芯擎科技",
    ],
    "CIS/SPAD/ToF": [
        "韦尔股份", "豪威", "OmniVision", "思特威", "SmartSens", "格科微",
        "GalaxyCore", "晶相光电", "灵明光子", "Adaps", "阜时科技", "芯视界",
        "宇称电子", "北极芯微", "纵慧芯光", "长光华芯", "深迪半导体",
        "美新半导体", "明皜传感", "矽睿科技", "歌尔微电子", "汇顶科技",
        "钛深科技", "芯视界微电子", "光微科技", "芯探科技",
    ],
}

# 实体别名归一：同一家公司有多种叫法时，统一成一个名字，
# 避免在 Obsidian 里建出多个条目、也避免去重时把同一家当两家。
ENTITY_ALIAS = {
    "德州仪器": "TI", "德仪": "TI", "TI ": "TI",
    "亚德诺": "ADI", "Analog Devices": "ADI",
    "意法半导体": "ST", "STMicroelectronics": "ST", "STMicro": "ST",
    "英飞凌科技": "英飞凌", "Infineon": "英飞凌",
    "恩智浦": "NXP", "瑞萨电子": "瑞萨", "Renesas": "瑞萨",
    "安森美": "onsemi", "ON Semiconductor": "onsemi",
    "芯源系统": "MPS", "Monolithic Power": "MPS",
    "上海海思": "海思", "HiSilicon": "海思",
    "韦尔": "韦尔股份", "豪威科技": "豪威", "OmniVision": "豪威",
    "思特威电子": "思特威", "SmartSens": "思特威",
    "格科": "格科微", "GalaxyCore": "格科微",
    "矽力杰股份": "矽力杰", "Silergy": "矽力杰",
    "立锜科技": "立锜", "Richtek": "立锜",
    "纳微半导体": "纳微", "Navitas": "纳微",
    "圣邦股份": "圣邦微", "杰华特微电子": "杰华特",
    "索尼半导体": "索尼", "Samsung": "三星电子",
    "迈来芯": "Melexis",
}


# ═══════════════════════════════════════════════════════════════════
# ④ 客户名录
# ═══════════════════════════════════════════════════════════════════
#
# 命中 → role=客户。用于判断「这条是不是我的客户在动」。
# 按你自己的客户结构分组，分组名只是给人看。

CUSTOMERS = {
    "消费电子": ["小米", "OPPO", "vivo", "荣耀", "传音", "realme", "摩托罗拉", "一加",
                 "三星", "苹果"],
    "充电与配件": ["安克创新", "Anker", "绿联", "倍思", "Baseus", "紫米", "贝尔金",
                   "Belkin", "图拉斯"],
    "汽车与 Tier1": ["比亚迪", "理想", "蔚来", "小鹏", "吉利", "长城汽车", "奇瑞",
                     "赛力斯", "长安汽车", "上汽", "广汽", "零跑", "小米汽车",
                     "安波福", "Aptiv", "德赛西威", "华阳集团", "经纬恒润", "伯特利",
                     "联合电子"],
    "工业储能光伏": ["阳光电源", "宁德时代", "亿纬锂能", "德业股份", "锦浪科技",
                     "固德威", "正泰", "汇川技术", "禾迈", "昱能科技"],
    "算力与光模块": ["浪潮信息", "新华三", "联想", "中科曙光", "工业富联",
                     "中际旭创", "新易盛", "天孚通信", "光迅科技", "华工科技"],
}


# ═══════════════════════════════════════════════════════════════════
# ⑤ 信源清单  ← 决定抓哪些站
# ═══════════════════════════════════════════════════════════════════
#
# 每条必填：id（唯一短名）、name（显示名）、kind、tier、url、interval（秒）
#
# kind 两种：
#   "rss"      → 直接给 RSS/Atom 地址，最简单，优先选这种
#   "web_list" → 抓列表页，用 pattern 正则从 HTML 里挑文章链接
#
# web_list 额外字段：
#   pattern     : 匹配文章链接的正则（对绝对 URL 匹配；有 base 时对 path 匹配）
#   base        : 站点根，用于把相对路径拼成绝对 URL；没有就留 ""
#   must_match  : 可选，链接/标题命中此正则才收（用于聚合站降噪）
#   title_strip : 可选，从抓到的标题里去掉尾部噪声（如 "2026.11.27 新闻详情"）
#   enabled     : 可选，False 表示暂不启用（配置占位用）
#
# 怎么写 pattern：用浏览器打开目标列表页 → F12 → 看一篇文章链接长什么样
# → 照着写正则。写错了不会崩，日志里会显示该源 0 条。
#
# tier 含义：T1 = 一手/权威（官网、公告），T2 = 行业媒体。
# 门槛按 tier 分档，见 THRESHOLDS。
#
# 综合列表页的降噪正则，用占位符代替。
#
# 不在这里直接拼——config.py 会统一从 SELF_ALIASES + 竞对名录派生，
# 并给短 ASCII 名（ST / TI 等）加词边界，避免 "BEST Semiconductors" 这类
# 单词内部误命中。config.py 加载完本文件后，会把下面 SOURCES 里的
# VENDOR_RE_TOKEN 替换成真正的正则。
#
# 你想改筛选范围，改 SELF_ALIASES / COMPETITORS 即可，不用动这里。
VENDOR_RE_TOKEN = "__CN_VENDOR_RE__"

# ⚠️ 下面 15 个源自带可用配置（模拟芯片行业），中文源已实测可达。
#    换成你自己的行业时，把不适用的删掉，加上你行业的垂直媒体。

SOURCES = [
    # ── 国际行业媒体（T2）──
    {"id": "eetimes", "name": "EE Times", "kind": "rss", "tier": "T2",
     "url": "https://www.eetimes.com/feed/", "interval": 180},
    {"id": "semieng", "name": "Semiconductor Engineering", "kind": "rss", "tier": "T2",
     "url": "https://semiengineering.com/feed/", "interval": 240},
    {"id": "digitimes", "name": "DigiTimes", "kind": "rss", "tier": "T2",
     "url": "https://www.digitimes.com/rss/daily.xml", "interval": 180},
    {"id": "edn", "name": "EDN", "kind": "rss", "tier": "T2",
     "url": "https://www.edn.com/feed/", "interval": 240},
    {"id": "penews", "name": "Power Electronics News", "kind": "rss", "tier": "T2",
     "url": "https://www.powerelectronicsnews.com/feed/", "interval": 240},

    # ── 国内产业媒体（T2，网页列表；选择器已实测）──
    {"id": "laoyaoba", "name": "爱集微", "kind": "web_list", "tier": "T2",
     "url": "https://www.laoyaoba.com/", "interval": 180,
     "pattern": r"^/n/\d+$", "base": "https://www.laoyaoba.com"},
    {"id": "chongdiantou", "name": "充电头网", "kind": "web_list", "tier": "T2",
     "url": "https://www.chongdiantou.com/", "interval": 180,
     "pattern": r"^https?://www\.chongdiantou\.com/archives/\d+", "base": ""},
    {"id": "eefocus", "name": "与非网", "kind": "web_list", "tier": "T2",
     "url": "https://www.eefocus.com/", "interval": 240,
     "pattern": r"^https://www\.eefocus\.com/article/\d+\.html$", "base": ""},
    {"id": "elecfans", "name": "电子发烧友", "kind": "web_list", "tier": "T2",
     "url": "https://www.elecfans.com/", "interval": 240,
     "pattern": r"^https?://www\.elecfans\.com/[a-z]+/\d+\.html$", "base": ""},

    # ── 竞对官网（T1）──
    # 竞对官网是一手信源，比媒体转载更早更准。建议至少加 1-2 家主要对手。
    {"id": "ti", "name": "TI", "kind": "web_list", "tier": "T1",
     "url": "https://www.ti.com/about-ti/newsroom.html", "interval": 360,
     "pattern": r"^/en-us/about-ti/newsroom/news-releases/", "base": "https://www.ti.com"},
    {"id": "st", "name": "STMicroelectronics", "kind": "web_list", "tier": "T1",
     "url": "https://newsroom.st.com/", "interval": 360,
     "pattern": r"^https://newsroom\.st\.com/media-center/press-item\.html/", "base": ""},

    # ── 自家官网（T1，默认关闭）──
    # 官网新闻通常滞后于媒体，只作权威兜底。填好 url 和 pattern 后
    # 把 enabled 改成 True（或删掉这一行）。
    {"id": "own_site", "name": f"{COMPANY}官网", "kind": "web_list", "tier": "T1",
     "url": "https://www.example.com/news", "interval": 360,
     "pattern": r"^https://", "base": "",
     "title_strip": r"\s*20\d\d\.\d{1,2}\.\d{1,2}\s*新闻详情\s*$",
     "enabled": False},

    # ── 新品速递聚合频道（T2）──
    # 国产厂商官网普遍 404/403/无日期，逐家爬不可行。
    # 这类垂直新品频道是一手发布的实际转载载体。
    # must_match 用 CN_VENDOR_RE（自动由 SELF_ALIASES + 竞对名录拼成），
    # 避免整站内容涌入评分。
    {"id": "eetrend_new", "name": "电子创新网·新品", "kind": "web_list", "tier": "T2",
     "url": "https://www.eetrend.com/newproduct.html", "interval": 240,
     "pattern": r"/content/20\d\d-\d\d/", "base": "https://www.eetrend.com",
     "must_match": VENDOR_RE_TOKEN},
    {"id": "cntronics_new", "name": "电子元件技术网·新品", "kind": "web_list", "tier": "T2",
     "url": "http://www.cntronics.com/cp-art/product", "interval": 240,
     "pattern": r"/industry/new-products/", "base": "http://www.cntronics.com",
     "must_match": VENDOR_RE_TOKEN},
    {"id": "eccn_new", "name": "中电网·产品", "kind": "web_list", "tier": "T2",
     "url": "http://products.eccn.com/", "interval": 240,
     "pattern": r"products_\d+\.htm", "base": "",
     "must_match": VENDOR_RE_TOKEN},
]


# ═══════════════════════════════════════════════════════════════════
# ⑥ 播报与存储（通常不用改，走环境变量）
# ═══════════════════════════════════════════════════════════════════
#
# 邮件收件人。也可以不改这里，用环境变量 DAILY_MAIL_TO。
MAIL_TO = os.environ.get("DAILY_MAIL_TO", "you@example.com")

# 飞书接收人 open_id（ou_ 开头）。不用飞书就留空。
FEISHU_OPEN_ID = os.environ.get("DAILY_FEISHU_OPEN_ID", "")

# 数据与输出目录。默认仓库根目录下的 data/ 与 vault/。
# 想改位置就设环境变量 DAILY_BASE_DIR。
BASE_DIR = os.environ.get(
    "DAILY_BASE_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)


# ═══════════════════════════════════════════════════════════════════
# 以下为通用规则，沿用默认即可
# ═══════════════════════════════════════════════════════════════════

# ── 分销商 / 代理商 ──────────────────────────────────────────────────
# 为什么需要：分销商「开售某大厂某型号」会被 LLM 误判成该大厂的竞对动作，
# 但这类稿子对研发零情报价值——主体是渠道，不是原厂。
# 规则：标题同时命中「分销商名」+「渠道动作词」→ 直接不入刊。
DISTRIBUTORS = [
    "贸泽", "Mouser", "得捷", "Digi-Key", "DigiKey", "艾睿", "Arrow",
    "大联大", "WPG", "富昌", "Future Electronics", "世强", "世健",
    "中电港", "科通", "力源", "立创商城", "华秋", "云汉芯城",
]
DISTRIBUTOR_ACTIONS = [
    "开售", "上架", "开卖", "现货", "分销", "代理销售", "备货", "库存",
]

# ── 政策条目「实质内容」硬门 ─────────────────────────────────────────
# 为什么需要：「美国算力管制再升级，某公司打造全国产供应链」这种稿子
# 能拿到高分（影响范围大 + 新鲜），但全文只有两句表态，没有任何新事实。
# 规则：type=政策标准 的条目必须命中至少一个「具体事实标记」才入刊。
# 这个正则是通用的（百分比/条款/日期/金额/禁令），跨行业适用。
POLICY_FACT_RE = (
    r"(\d+(\.\d+)?\s*%|\d+\s*个?百分?点|"
    r"第[一二三四五六七八九十百\d]+条|条款|文号|号文|公告第|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月\s*\d{1,2}\s*日(生效|起)|"
    r"\d+\s*(亿|万|千)?\s*(美元|欧元|元|日元)|关税税率|加征\d|"
    r"(禁止|限制|豁免|许可|清单)(出口|进口|对华|范围)|实体清单)"
)

# ── 前一日突发接续 ───────────────────────────────────────────────────
# 为什么需要：突发通道和日报是两条管道。突发推过的行业级消息，
# 次日日报如果因为「推过了」就不再出现，等于直接消失。
# 规则：近 N 小时的突发接续进当日日报，同一线索只接一条。
ALERT_CARRYOVER_HOURS = 36   # 回看窗口，覆盖前一日全天
ALERT_CARRYOVER_MAX = 6      # 最多接续几条，防止政策类刷屏
ALERT_SCORE_FLOOR = {"A": 62, "B": 56}   # 已判突发的分数下限

# ── 评分门槛 ─────────────────────────────────────────────────────────
# 为什么是 40-44 而不是 68：LLM 实际输出集中在 40-65 分，
# 门槛设 68 会导致一条都进不来（我们踩过这个坑）。
# 调法：跑一次 --dry，看日志里分数分布，再定。
THRESHOLDS = {"T1": 40, "T1_5": 44, "T2": 44}

# ── 输出规模 ─────────────────────────────────────────────────────────
LOOKBACK_DAYS = 7   # 跨天去重回溯窗口（天）
TOP_N = 5           # 今日必读条数
