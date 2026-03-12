# -*- coding: utf-8 -*-
# 用途：抓取 RSS 新闻并渲染到 index.html（GitHub Pages）
# 说明：
# - 默认抓取 IT之家 RSS: https://www.ithome.com/rss/
# - 生成/覆盖仓库根目录的 index.html（由 GitHub Actions 提交回仓库）
# - 模板文件默认使用仓库根目录的 index.html（包含占位符），也可用 TEMPLATE_PATH 指定

import os
import re
from datetime import datetime, timezone
from typing import List, Dict

import feedparser


RSS_URLS = [
    "https://www.ithome.com/rss/",
    # 可按需添加更多 RSS 源（建议同类新闻源不要太多，避免页面过长）
    # "https://sspai.com/feed",
    # "https://rsshub.app/36kr/news/latest",
]

MAX_ITEMS = 10

# 模板占位符
PLACEHOLDER_ITEMS = "{{NEWS_ITEMS}}"
PLACEHOLDER_UPDATED = "{{UPDATED_AT}}"

# 默认模板路径：仓库根目录 index.html（同名文件既是模板也是输出）
TEMPLATE_PATH = os.environ.get("TEMPLATE_PATH", "index.html")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "index.html")


def _safe_html(text: str) -> str:
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


def _pick_time(entry: dict) -> str:
    # 优先 published，其次 updated；尽量输出为可读字符串
    for key in ("published", "updated"):
        if key in entry and entry.get(key):
            return str(entry.get(key))
    # 若 feedparser 提供结构化时间
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone()
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
    return ""


def fetch_items(rss_urls: List[str], max_items: int) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for url in rss_urls:
        d = feedparser.parse(url)
        if getattr(d, "bozo", 0):
            # bozo=1 表示解析异常，但可能仍有 entries；不中断
            pass

        for e in getattr(d, "entries", [])[:max_items]:
            title = _safe_html(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            published = _safe_html(_pick_time(e))

            if not title or not link:
                continue

            items.append({"title": title, "link": link, "published": published})

    # 去重（按 link）
    seen = set()
    uniq = []
    for it in items:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        uniq.append(it)
        if len(uniq) >= max_items:
            break
    return uniq


def render_items(items: List[Dict[str, str]]) -> str:
    # 生成 <li> 列表
    li_list = []
    for it in items:
        time_html = f'<span class="time">{it["published"]}</span>' if it["published"] else ""
        li_list.append(
            f'<li class="item">'
            f'  <a class="title" href="{it["link"]}" target="_blank" rel="noopener noreferrer">{it["title"]}</a>'
            f'  {time_html}'
            f'</li>'
        )
    return "\n".join(li_list)


def load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_output(path: str, html: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    template = load_template(TEMPLATE_PATH)

    items = fetch_items(RSS_URLS, MAX_ITEMS)
    items_html = render_items(items)

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 若模板缺少占位符，尽量不破坏原文件：用正则替换一个标记区域（可选）
    if PLACEHOLDER_ITEMS not in template:
        # 兼容：替换 <!-- NEWS_ITEMS_START -->...<!-- NEWS_ITEMS_END -->
        pattern = r"<!--\s*NEWS_ITEMS_START\s*-->.*?<!--\s*NEWS_ITEMS_END\s*-->"
        repl = f"<!-- NEWS_ITEMS_START -->\n{items_html}\n<!-- NEWS_ITEMS_END -->"
        template = re.sub(pattern, repl, template, flags=re.S)

    else:
        template = template.replace(PLACEHOLDER_ITEMS, items_html)

    if PLACEHOLDER_UPDATED in template:
        template = template.replace(PLACEHOLDER_UPDATED, updated_at)

    write_output(OUTPUT_PATH, template)


if __name__ == "__main__":
    main()
