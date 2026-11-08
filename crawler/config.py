"""抓取来源配置。

新增来源时，复制一个 Source 定义并实现对应的列表解析器即可。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
ITEMS_DIR = DATA_DIR / "items"
INDEX_FILE = DATA_DIR / "index.json"
STATE_FILE = DATA_DIR / "state.json"

# 每次请求之间的最小间隔（秒），避免对学校服务器造成压力
REQUEST_DELAY = 0.25
REQUEST_TIMEOUT = 25
DETAIL_WORKERS = 4

# 索引中每篇文章参与搜索的正文长度上限
INDEX_TEXT_LIMIT = 1500


@dataclass(frozen=True)
class Source:
    key: str
    name: str          # 展示名称
    base: str          # 站点根地址
    list_url: str      # 列表页地址（第一页）
    channel: str       # 栏目名称
    parser: str        # 列表解析器：home / xxgk / wcce
    full_pages: int    # 首次全量抓取的页数
    daily_pages: int   # 每日增量抓取的页数
    fetch_detail: bool = True  # 是否抓取详情正文


SOURCES: tuple[Source, ...] = (
    Source(
        key="scau",
        name="华南农业大学",
        base="https://www.scau.edu.cn",
        list_url="https://www.scau.edu.cn/",
        channel="通知公告",
        parser="home",
        full_pages=1,
        daily_pages=1,
    ),
    Source(
        key="xxgk",
        name="信息公开",
        base="https://xxgk.scau.edu.cn",
        list_url="https://xxgk.scau.edu.cn/zxxxgk/list.htm",
        channel="最新信息公开",
        parser="xxgk",
        full_pages=150,
        daily_pages=2,
    ),
    Source(
        key="wcce",
        name="水利与土木工程学院",
        base="https://wcce.scau.edu.cn",
        list_url="https://wcce.scau.edu.cn/4275/list.htm",
        channel="通知公告",
        parser="wcce",
        full_pages=10,
        daily_pages=2,
    ),
)

SOURCE_BY_KEY = {s.key: s for s in SOURCES}
