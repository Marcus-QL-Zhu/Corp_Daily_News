"""公司日报 — 配置层

【使用者看这里】整个项目只需要改这一个文件，就能跑自己公司的日报。

改造步骤：
  1. 改下方「① 公司信息」——公司名、股票代码、日报标题、自己的别名
  2. 改「② 产品线」——你的业务分类，以及每类的关键词
  3. 改「③ 竞对名录」「④ 客户名录」——你关注的公司
  4. 改「⑤ 信源」——行业媒体、竞对官网、你自己官网
  5. 改「⑥ 播报」——收件人、飞书 open_id、存储路径

下面出现的「示例：模拟芯片行业」内容全部可以删掉换成你的领域。
词表改动只动这里，不动流水线代码。
"""
import os

# ═══════════════════════════════════════════════════════════════════
# ① 公司信息 —— 必须改
# ═══════════════════════════════════════════════════════════════════
COMPANY = "示例科技"                      # 中文全称，写进提示词（换成你公司）
COMPANY_EN = "ExampleTech"                # 英文名/常用简称
COMPANY_TICKER = "000000.SH"              # 股票代码，没有就留空
REPORT_NAME = "行业情报"                   # 日报标题前缀，如「XX情报」
SELF_ALIASES = ["示例科技", "ExampleTech"]   # 识别「自家新闻」的别名

# 你所在行业的圈层词（用于预筛：命中才认为与公司相关）
INDUSTRY_NAME = "模拟与嵌入式芯片"          # 行业名，写进提示词
INDUSTRY_KW = ["芯片", "半导体", "IC ", "晶圆", "封装", "封测", "制程", "代工", "EDA",
               "模拟", "功率器件", "MOSFET", "IGBT", "SiC", "碳化硅", "车规", "AEC-Q100",
               "ISO 26262", "ASIL", "流片", "量产", "semiconductor", "wafer", "foundry",
               "chip", "analog", "power device", "automotive grade", "tape-out"]

# ═══════════════════════════════════════════════════════════════════
# ② 产品线（示例：模拟芯片行业）—— 换成你的业务分类
#     key 用英文短名，name 是显示名，kw 是匹配关键词
# ═══════════════════════════════════════════════════════════════════
PRODUCT_LINES = {
    "battery": {"name": "电池管理", "tag": "电池管理", "md": "产品线-电池管理",
                "kw": ["电荷泵", "快充", "无线充电", "Qi2", "锂电保护", "电量计", "电池管理",
                       "充电协议", "PD3", "PD 3", "电池均衡", "gauge", "charger", "charging",
                       "BMS", "battery", "cell balancing", "fuel gauge", "MPP", "WPC"]},
    "power":   {"name": "电源管理", "tag": "电源管理", "md": "产品线-电源管理",
                "kw": ["AC-DC", "ACDC", "DC-DC", "DCDC", "LDO", "PMIC", "多相", "DrMOS", "LLC",
                       "PFC", "GaN", "氮化镓", "电源管理", "power management", "buck", "boost",
                       "buck-boost", "converter", "regulator", "PMU", "SBC", "EFuse", "eFuse",
                       "hot swap", "48V", "12V", "POL", "power stage", "VRM", "server power"]},
    "driver":  {"name": "智能驱动芯片", "tag": "智能驱动", "md": "产品线-智能驱动芯片",
                "kw": ["高边开关", "低边开关", "半桥", "全桥", "马达驱动", "电机驱动", "栅极驱动",
                       "LED驱动", "背光驱动", "eFuse", "EFuse", "HSD", "LSD", "gate driver",
                       "high-side", "low-side", "half-bridge", "motor driver", "solenoid",
                       "LED driver", "smart switch", "load switch", "预驱", "pre-driver"]},
    "sensor":  {"name": "传感芯片", "tag": "传感", "md": "产品线-传感芯片",
                "kw": ["传感器", "传感", "CIS", "CMOS图像", "图像传感器", "SPAD", "ToF", "dToF",
                       "iToF", "单光子", "激光雷达", "LiDAR", "MEMS", "霍尔", "磁传感", "电流传感",
                       "压力传感", "惯性", "IMU", "光传感", "sensor", "image sensor", "photodiode",
                       "APD", "SiPM", "3D sensing", "structured light", "AFE", "信号链"]},
    "link":    {"name": "传输芯片", "tag": "传输", "md": "产品线-传输芯片",
                "kw": ["CAN FD", "CANFD", "CAN", "LIN", "RS485", "RS-485", "RS232", "SerDes",
                       "redriver", "retimer", "USB PD", "USB4", "Type-C", "电平转换",
                       "level shift", "隔离", "isolator", "transceiver", "收发器", "以太网 PHY",
                       "Ethernet PHY", "MIPI", "LVDS", "桥接", "bridge"]},
    "mcu":     {"name": "MCU 芯片", "tag": "MCU", "md": "产品线-MCU芯片",
                "kw": ["MCU", "微控制器", "单片机", "RISC-V", "RISC V", "ARM Cortex", "Cortex-M",
                       "POWERMCU", "embedded controller", "EC ", "SoC", "微处理器", "MPU"]},
}

# 泛行业词：命中即认为属于本行业圈层（用于预筛），但不足以定产品线
# （已上移至 ①，见 INDUSTRY_KW）

# ── 角色判定 ────────────────────────────────────────────────────────────
ROLE_KW = {
    "竞对": ["竞对", "竞争对手", "competitor"],
    "客户": ["客户", "customer", "采用", "导入", "定点", "design win", "design-in"],
    "供应链": ["晶圆", "代工", "封测", "产能", "缺货", "涨价", "降价", "交期", "库存",
              "foundry", "capacity", "lead time", "inventory"],
    "政策": ["政策", "监管", "标准", "工信部", "发改委", "出口管制", "关税", "认证",
            "regulation", "standard", "export control", "tariff"],
    "行业": [],
}

# ── 竞对名录（按产品线，含 CIS / SPAD / ToF）────────────────────────────
COMPETITORS = {
    "国际大厂": ["TI", "德州仪器", "ADI", "亚德诺", "Maxim", "美信", "Infineon", "英飞凌",
                 "STMicro", "意法半导体", "ST ", "NXP", "恩智浦", "Renesas", "瑞萨",
                 "onsemi", "安森美", "Microchip", "MPS", "芯源系统", "Power Integrations",
                 "Rohm", "罗姆", "Allegro", "Melexis", "迈来芯", "Navitas", "纳微",
                 "Wolfspeed", "Silicon Labs", "Skyworks", "Qorvo", "Richtek", "立锜",
                 "Silergy", "矽力杰", "Parade", "谱瑞", "Sony", "索尼", "Samsung", "三星电子",
                 "ams-OSRAM", "艾迈斯欧司朗", "TDK", "InvenSense", "Bosch Sensortec"],
    "国内同行": ["圣邦微", "圣邦股份", "杰华特", "芯朋微", "英集芯", "钰泰", "智融",
                 "赛微微电", "希荻微", "帝奥微", "思瑞浦", "纳芯微", "士兰微", "华润微",
                 "比亚迪半导体", "斯达半导", "芯导科技", "力芯微", "芯海科技", "必易微",
                 "东科半导体", "亚成微", "硅动力", "英诺赛科", "能华微", "芯茂微",
                 "上海贝岭", "贝岭", "南麟", "昂宝", "通嘉", "川土微", "芯力特", "龙迅",
                 "集睿致远", "硅谷数模", "澜起科技", "兆易创新", "中颖电子", "国民技术",
                 "极海半导体", "华大半导体", "复旦微电", "航顺芯片", "灵动微", "沁恒",
                 "昇生微", "海思", "上海海思", "HiSilicon", "地平线", "黑芝麻智能", "芯擎科技"],
    "CIS/SPAD/ToF": ["韦尔股份", "豪威", "OmniVision", "思特威", "SmartSens", "格科微",
                     "GalaxyCore", "晶相光电", "灵明光子", "Adaps", "阜时科技", "芯视界",
                     "宇称电子", "北极芯微", "纵慧芯光", "长光华芯", "深迪半导体",
                     "美新半导体", "明皜传感", "矽睿科技", "歌尔微电子", "汇顶科技",
                     "钛深科技", "芯视界微电子", "光微科技", "芯探科技"],
}
COMPETITOR_SET = [x.strip() for v in COMPETITORS.values() for x in v if x.strip()]

# 实体别名归一：避免同一家公司建出多个 stub（如 TI / 德州仪器）
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

def norm_entity(name):
    if not name: return name
    n = name.strip()
    return ENTITY_ALIAS.get(n, n)

# ── 客户名录 ────────────────────────────────────────────────────────────
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
    "算力与光模块": ["浪潮信息", "新华夏", "新华三", "联想", "中科曙光", "工业富联",
                     "中际旭创", "新易盛", "天孚通信", "光迅科技", "华工科技"],
}
CUSTOMER_SET = [x.strip() for v in CUSTOMERS.values() for x in v if x.strip()]

# ── 分销商 / 代理商 ────────────────────────────────────────────────────
# 2026-11-27 加：贸泽开售 TI TRF2001 被当成「TI 竞对动作」入刊，实为
# 分销商上架，对公司无情报价值。这类条目的主体是渠道，不是原厂。
# 触发条件：标题/摘要出现下列名字 *且* 含上架类动作词（见 main.distributor_led）。
DISTRIBUTORS = [
    "贸泽", "Mouser", "得捷", "Digi-Key", "DigiKey", "艾睿", "Arrow",
    "大联大", "WPG", "富昌", "Future Electronics", "世强", "世健",
    "中电港", "科通", "力源", "立创商城", "华秋", "云汉芯城",
]
# 渠道动作词：分销商 + 下列任一动作 → 判为「渠道上架」，不是原厂动态。
DISTRIBUTOR_ACTIONS = [
    "开售", "上架", "开卖", "现货", "分销", "代理销售", "备货", "库存",
]

# ── 政策条目「实质内容」硬门 ──────────────────────
# 2026-11-27 加：「美国算力管制再升级东方算芯打造全国产供应链」被判 55 分
# impact=high 入刊，但全文只有「管制再升级 + 某公司表示要国产化」两句表态，
# 没有任何新事实（无新法规/生效日/税率/清单/文号）。用户判定为「没实质内容」。
# 规则：type=政策标准 的条目必须命中至少一个「具体事实标记」，否则不入刊。
POLICY_FACT_RE = (
    r"(\d+(\.\d+)?\s*%|\d+\s*个?百分?点|"
    r"第[一二三四五六七八九十百\d]+条|条款|文号|号文|公告第|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月\s*\d{1,2}\s*日(生效|起)|"
    r"\d+\s*(亿|万|千)?\s*(美元|欧元|元|日元)|关税税率|加征\d|"
    r"(禁止|限制|豁免|许可|清单)(出口|进口|对华|范围)|实体清单)"
)

# ── 前一日突发接续入日报 ──────────────────────────
# 2026-11-27 定：突发通道推过的条目，次日日报要能看到，不能因为是「昨天
# 的推送」就消失。原流程日报从不读 alerts 表，两条管道互不相通。
ALERT_CARRYOVER_HOURS = 36      # 回看窗口：覆盖前一日全天
ALERT_CARRYOVER_MAX = 6         # 最多接续几条（防政策类刷屏）
ALERT_SCORE_FLOOR = {"A": 62, "B": 56}   # 已判突发的，分数不低于此值

# ── 信源清单（已实测可达）────────────────────────────────────────────────
# kind: rss | web_list
# 综合型列表页的 must_match 过滤：只把「自家 + 核心竞对」的条目送进评分。
# 默认自动用 SELF_ALIASES + 竞对名录拼出来，一般不用手改。
CN_VENDOR_RE = "|".join(
    [a.strip() for a in SELF_ALIASES if a.strip()]
    + [c.strip() for c in COMPETITOR_SET if c.strip()]
)

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

    # ── 国内产业媒体（T2，网页列表；选择器均已实测）──
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

    # ── 竞对官网（T1，网页列表；RSS 路径已失效，改列表页）──
    {"id": "ti", "name": "TI", "kind": "web_list", "tier": "T1",
     "url": "https://www.ti.com/about-ti/newsroom.html", "interval": 360,
     "pattern": r"^/en-us/about-ti/newsroom/news-releases/", "base": "https://www.ti.com"},
    {"id": "st", "name": "STMicroelectronics", "kind": "web_list", "tier": "T1",
     "url": "https://newsroom.st.com/", "interval": 360,
     "pattern": r"^https://newsroom\.st\.com/media-center/press-item\.html/", "base": ""},

    # ── 自家官网（T1）—— 换成你自己的官网新闻页 ──
    # 官网通常滞后于媒体，只作 T1 权威兜底，不要指望它抢时效。
    # 示例仅作格式参考；上线前请换成你自己公司的地址，
    # 或直接删掉这一段（只靠行业媒体也能跑）。
    {"id": "own_site", "name": f"{COMPANY}官网", "kind": "web_list", "tier": "T1",
     "url": "https://www.example.com/news", "interval": 360,
     "pattern": r"^https://", "base": "",
     "title_strip": r"\s*20\d\d\.\d{1,2}\.\d{1,2}\s*新闻详情\s*$",
     "enabled": False},   # 填好 url/pattern 后改成 True
    # 英文站已移除（2026-11-26）：与中文站同批发的中英双版本，跨天 URL 门
    # 管得住重复，但当天 cluster() 按中文字面相似度判同事件，中英标题相似度=0
    # → 同一新品会出两条。中文站链接直指公众号原文，本身就是一手。

    # ── 国产竞对「新品速递」聚合频道（T2，带发布日期，同日常态覆盖）──
    # 国产模拟厂官网普遍 404/403/无日期，逐家爬不可行（2026-11-26 实测 19 家）。
    # 这三个垂直新品频道是 SCS5130 / SC3606 这类一手发布的实际转载载体。
    # must_match 只留自家与核心国产竞对，避免整站内容涌入评分。
    {"id": "eetrend_new", "name": "电子创新网·新品", "kind": "web_list", "tier": "T2",
     "url": "https://www.eetrend.com/newproduct.html", "interval": 240,
     "pattern": r"/content/20\d\d-\d\d/", "base": "https://www.eetrend.com",
     "must_match": CN_VENDOR_RE},
    {"id": "cntronics_new", "name": "电子元件技术网·新品", "kind": "web_list", "tier": "T2",
     "url": "http://www.cntronics.com/cp-art/product", "interval": 240,
     "pattern": r"/industry/new-products/", "base": "http://www.cntronics.com",
     "must_match": CN_VENDOR_RE},
    {"id": "eccn_new", "name": "中电网·产品", "kind": "web_list", "tier": "T2",
     "url": "http://products.eccn.com/", "interval": 240,
     "pattern": r"products_\d+\.htm", "base": "",
     "must_match": CN_VENDOR_RE},
]

# ── 评分门槛 ────────────────────────────────────────────────────────────
# 门槛按本行业实测分数分布校准（2026-11-24）：
# 模型输出集中在 40-65 分，原 AIHOT 默认（T2=68）会导致全灭。
# 目标：广度优先，日入刊 20-30 条。
THRESHOLDS = {"T1": 40, "T1_5": 44, "T2": 44}

# ═══════════════════════════════════════════════════════════════════
# ⑥ 播报与存储 —— 必须改
# ═══════════════════════════════════════════════════════════════════
# 收件人（邮件）
MAIL_TO = os.environ.get("DAILY_MAIL_TO", "you@example.com")

# 飞书接收人 open_id（不用飞书就留空）
FEISHU_OPEN_ID = os.environ.get("DAILY_FEISHU_OPEN_ID", "")

# 数据与输出目录。默认当前仓库下的 data/ 与 vault/
BASE_DIR = os.environ.get("DAILY_BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VAULT = os.path.join(BASE_DIR, "vault")
DB_PATH = os.path.join(BASE_DIR, "data", "state.db")
CACHE_PATH = os.path.join(BASE_DIR, "data", "judge-cache.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
PITCH_PATH = os.path.join(BASE_DIR, "pitch", "company-pitch.md")

# 跨天去重回溯窗口（天）。日报只发「从未在窗口内刊出过」的条目。
LOOKBACK_DAYS = 7
TOP_N = 5
