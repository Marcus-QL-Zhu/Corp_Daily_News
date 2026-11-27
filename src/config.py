"""公司日报 — 配置加载层

════════════════════════════════════════════════════════════════════
加载顺序（先找到谁就用谁，后面的不再读）
════════════════════════════════════════════════════════════════════

  1. src/config_local.py     ← 你的私有配置（推荐，已 gitignore）
  2. src/config.example.py   ← 完整示例，clone 下来不改也能跑

所以你不需要删任何东西：

  - 想用示例配置直接跑 → 什么都不做
  - 想改成自己的公司     → cp config.example.py config_local.py，只改后者

为什么这样设计：如果让人直接改 config.example.py，下次 git pull 就会
冲突；而且一不小心会把带有真实公司信息的配置提交上去。用 config_local.py
隔离后，示例文件可以随版本更新，你的私有配置始终干净。

════════════════════════════════════════════════════════════════════
本文件的作用
════════════════════════════════════════════════════════════════════

把「原始配置」（公司名、产品线、竞对、信源…）计算成「派生配置」：
  COMPETITOR_SET / CUSTOMER_SET  —— 把分组 dict 拍平成扁平列表
  ENTITY_ALIAS / norm_entity     —— 实体名归一
  CN_VENDOR_RE                   —— 综合列表页的降噪正则
  VAULT / DB_PATH / ...          —— 从 BASE_DIR 推导所有存储路径

这样使用者只需要填原始值，不用关心派生逻辑。
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_file(path: Path):
    """按文件路径加载模块。

    不能用 importlib.import_module("config.example")——在本文件内部，
    `config` 会被当成包名去找子模块，直接 ModuleNotFoundError。
    """
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_base():
    """优先私有配置，回退到示例配置。"""
    local = _HERE / "config_local.py"
    if local.exists():
        return _load_file(local), "config_local.py"
    example = _HERE / "config.example.py"
    if example.exists():
        return _load_file(example), "config.example.py"
    raise RuntimeError(
        f"找不到配置文件。请确认 {_HERE} 下存在 config.example.py，"
        f"或复制一份为 config_local.py 后填写。"
    )


_base, CONFIG_SOURCE = _load_base()

# ── 把原始配置搬进本模块命名空间 ────────────────────────────────────────
# 只搬全大写常量，避免把 os / re / sys 之类模块名也带进来。
for _name in dir(_base):
    if _name.isupper():
        globals()[_name] = getattr(_base, _name)

# ── 必填项校验：缺了就明确报错，而不是跑到 halfway 才炸 ──────────────────
_REQUIRED = ("COMPANY", "REPORT_NAME", "SELF_ALIASES", "PRODUCT_LINES", "SOURCES")
_missing = [k for k in _REQUIRED if k not in globals()]
if _missing:
    raise RuntimeError(
        f"{CONFIG_SOURCE} 缺少必填配置项：{', '.join(_missing)}。\n"
        f"请对照 src/config.example.py 补齐。"
    )

# ── 默认值：使用者没填就给合理默认 ──────────────────────────────────────
COMPANY_EN = globals().get("COMPANY_EN") or COMPANY
COMPANY_TICKER = globals().get("COMPANY_TICKER") or ""
INDUSTRY_NAME = globals().get("INDUSTRY_NAME") or "本行业"
INDUSTRY_KW = globals().get("INDUSTRY_KW") or []

COMPETITORS = globals().get("COMPETITORS") or {}
CUSTOMERS = globals().get("CUSTOMERS") or {}
ENTITY_ALIAS = globals().get("ENTITY_ALIAS") or {}
ROLE_KW = globals().get("ROLE_KW") or {}

DISTRIBUTORS = globals().get("DISTRIBUTORS") or []
DISTRIBUTOR_ACTIONS = globals().get("DISTRIBUTOR_ACTIONS") or []

ALERT_CARRYOVER_HOURS = globals().get("ALERT_CARRYOVER_HOURS", 36)
ALERT_CARRYOVER_MAX = globals().get("ALERT_CARRYOVER_MAX", 6)
ALERT_SCORE_FLOOR = globals().get("ALERT_SCORE_FLOOR", {"A": 62, "B": 56})
THRESHOLDS = globals().get("THRESHOLDS", {"T1": 40, "T1_5": 44, "T2": 44})
LOOKBACK_DAYS = globals().get("LOOKBACK_DAYS", 7)
TOP_N = globals().get("TOP_N", 5)

POLICY_FACT_RE = globals().get("POLICY_FACT_RE") or (
    r"(\d+(\.\d+)?\s*%|\d+\s*个?百分?点|"
    r"第[一二三四五六七八九十百\d]+条|条款|文号|号文|公告第|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月\s*\d{1,2}\s*日(生效|起)|"
    r"\d+\s*(亿|万|千)?\s*(美元|欧元|元|日元)|关税税率|加征\d|"
    r"(禁止|限制|豁免|许可|清单)(出口|进口|对华|范围)|实体清单)"
)

# ── 派生：分组 dict → 扁平列表 ──────────────────────────────────────────
COMPETITOR_SET = [x.strip() for v in COMPETITORS.values() for x in v if x and x.strip()]
CUSTOMER_SET = [x.strip() for v in CUSTOMERS.values() for x in v if x and x.strip()]


def norm_entity(name):
    """实体名归一：同一家公司有多种叫法时统一，避免建出多个条目。"""
    if not name:
        return name
    return ENTITY_ALIAS.get(name.strip(), name.strip())


# ── 派生：综合列表页降噪正则 ────────────────────────────────────────────
# 使用者可以在配置文件里自己给 CN_VENDOR_RE；没给就自动拼。
# 关键：必须 re.escape。公司名里的 "." "+" "(" 在正则里是元字符，
# 不转义会变成通配符（例如 "STMicro" 里的点会匹配任意字符）。
CN_VENDOR_RE = globals().get("CN_VENDOR_RE") or "|".join(
    re.escape(x) for x in (list(SELF_ALIASES) + COMPETITOR_SET) if x and x.strip()
)

# ── 派生：存储路径 ──────────────────────────────────────────────────────
BASE_DIR = globals().get("BASE_DIR") or os.path.dirname(str(_HERE))
VAULT = os.path.join(BASE_DIR, "vault")
DB_PATH = os.path.join(BASE_DIR, "data", "state.db")
CACHE_PATH = os.path.join(BASE_DIR, "data", "judge-cache.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
PITCH_PATH = os.path.join(BASE_DIR, "pitch", "company-pitch.md")

# ── 播报目标 ────────────────────────────────────────────────────────────
MAIL_TO = globals().get("MAIL_TO") or os.environ.get("DAILY_MAIL_TO", "")
FEISHU_OPEN_ID = globals().get("FEISHU_OPEN_ID") or os.environ.get("DAILY_FEISHU_OPEN_ID", "")

# ── 启动自检：第一次跑的人最常错的三件事，直接说出来 ────────────────────
def check(verbose=False):
    """返回 (ok, 问题列表)。run_daily 启动时会调。"""
    problems = []
    if not PRODUCT_LINES:
        problems.append("PRODUCT_LINES 为空：日报没有分栏依据，请填你的业务线")
    if not COMPETITOR_SET:
        problems.append("COMPETITORS 为空：所有公司都会被判成「行业」，竞对加分失效")
    if not SOURCES:
        problems.append("SOURCES 为空：没有信源可抓")
    if not MAIL_TO or "@" not in MAIL_TO:
        problems.append(f"MAIL_TO 未配置有效邮箱（当前 {MAIL_TO!r}），邮件发不出去")
    if verbose:
        print(f"配置来源: {CONFIG_SOURCE}")
        print(f"公司    : {COMPANY} / {REPORT_NAME}")
        print(f"业务线  : {len(PRODUCT_LINES)} 条 {list(PRODUCT_LINES)}")
        print(f"竞对/客户: {len(COMPETITOR_SET)} / {len(CUSTOMER_SET)}")
        print(f"信源    : {len(SOURCES)} 个（启用 {sum(1 for s in SOURCES if s.get('enabled', True))}）")
        print(f"输出目录: {BASE_DIR}")
    return (not problems), problems
