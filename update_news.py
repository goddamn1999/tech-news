# -*- coding: utf-8 -*-
"""
增强版 RSS 新闻抓取与分析工具
功能：
1. 抓取多源国际/国内重大事件 RSS 源
2. 新闻内容关键词提取、分类、热度分析
3. 生成带分析维度的可视化 HTML 页面
4. 更健壮的异常处理和配置管理
"""
import os
import re
import json
import jieba
import jieba.analyse
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from collections import Counter, defaultdict

import feedparser
import requests
from bs4 import BeautifulSoup

# ===================== 配置项 =====================
# 扩展的重大事件 RSS 源（覆盖国际、政治、经济）
RSS_URLS = {
    "国际新闻": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "国内要闻": "https://www.ithome.com/rss/",
    "财经大事": "https://rsshub.app/36kr/news/finance",
    "全球时政": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "突发新闻": "https://rsshub.app/bbc/news/live/world"
}

MAX_ITEMS_PER_SOURCE = 8  # 每个源最多抓取条数
TOTAL_MAX_ITEMS = 30      # 总条数上限
TOP_KEYWORDS = 10         # 提取关键词数量

# 文件路径配置
TEMPLATE_PATH = os.environ.get("TEMPLATE_PATH", "template.html")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "index.html")
KEYWORD_STATS_PATH = "keyword_stats.json"

# 模板占位符
PLACEHOLDER_ITEMS = "{{NEWS_ITEMS}}"
PLACEHOLDER_UPDATED = "{{UPDATED_AT}}"
PLACEHOLDER_KEYWORDS = "{{TOP_KEYWORDS}}"
PLACEHOLDER_CATEGORY_STATS = "{{CATEGORY_STATS}}"

# 停用词（过滤无意义词汇）
STOPWORDS = {"的", "了", "在", "是", "我", "你", "他", "她", "它", "和", "与", "及", "等", "都", "也", "就", "还", "有", "不", "没", "要", "会", "将", "着", "过", "为", "对", "因", "由", "于", "随", "从", "到", "以", "按", "据", "凭", "靠", "用", "通过", "基于", "关于", "对于", "有关", "相比", "比如", "例如", "包括", "包含", "涉及", "其中", "此外", "另外", "同时", "并且", "但是", "然而", "因此", "所以", "那么", "这么", "那样", "如何", "为何", "什么", "哪里", "何时", "多少", "几", "每", "各", "某", "本", "该", "此", "那", "这", "之", "而", "或", "即", "则", "虽", "若", "如", "只要", "只有", "除非", "倘若", "假如", "如果", "即使", "既然", "因为", "既然", "尽管"}

# ===================== 核心工具函数 =====================
def _safe_html(text: Optional[str]) -> str:
    """安全转义 HTML 特殊字符"""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


def _parse_rss_time(time_str: Optional[str]) -> str:
    """标准化时间格式"""
    if not time_str:
        return ""
    try:
        # 处理不同格式的时间字符串
        dt = feedparser._parse_date(time_str)
        if dt:
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    # 保底：提取年月日时分
    time_pattern = r"(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})?"
    match = re.search(time_pattern, str(time_str))
    if match:
        return f"{match.group(1)} {match.group(2) or '00:00'}"
    return ""


def _fetch_article_content(url: str) -> str:
    """抓取文章正文（用于更精准的关键词分析）"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        
        soup = BeautifulSoup(response.text, "html.parser")
        # 移除广告、导航等无关标签
        for tag in soup(["script", "style", "nav", "footer", "aside", "ad"]):
            tag.decompose()
        
        # 提取正文（优先 p 标签）
        paragraphs = soup.find_all("p")
        content = " ".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text()) > 20])
        return content[:1000]  # 限制长度，避免内存占用过大
    except Exception:
        return ""


# ===================== 数据抓取 =====================
def fetch_rss_items(rss_config: Dict[str, str], max_per_source: int, total_max: int) -> List[Dict[str, str]]:
    """抓取多源 RSS 并去重"""
    all_items = []
    
    for category, url in rss_config.items():
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                print(f"警告：解析 {category} RSS 失败 - {url}")
                continue
            
            # 处理当前源的条目
            for entry in feed.entries[:max_per_source]:
                title = _safe_html(entry.get("title", ""))
                link = entry.get("link", "")
                published = _parse_rss_time(entry.get("published") or entry.get("updated"))
                content = _fetch_article_content(link)  # 抓取正文用于分析
                
                if not title or not link:
                    continue
                
                all_items.append({
                    "title": title,
                    "link": link,
                    "published": published,
                    "category": category,
                    "content": content
                })
                
        except Exception as e:
            print(f"错误：处理 {category} RSS 时出错 - {str(e)}")
            continue
    
    # 去重（按链接）并限制总数
    seen_links = set()
    unique_items = []
    for item in all_items:
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            unique_items.append(item)
            if len(unique_items) >= total_max:
                break
    
    # 按时间倒序排序
    unique_items.sort(key=lambda x: x["published"] or "", reverse=True)
    return unique_items


# ===================== 内容分析 =====================
def analyze_news_items(items: List[Dict[str, str]]) -> Tuple[Dict[str, int], List[Tuple[str, int]]]:
    """
    分析新闻内容：
    1. 分类统计
    2. 关键词提取（基于标题+正文）
    """
    # 1. 分类统计
    category_stats = Counter([item["category"] for item in items])
    
    # 2. 关键词提取
    all_text = " ".join([item["title"] + " " + item["content"] for item in items])
    
    # 初始化 jieba 并添加自定义词典（可选）
    jieba.analyse.set_stop_words("stopwords.txt") if os.path.exists("stopwords.txt") else None
    
    # 提取关键词（TF-IDF 算法）
    keywords = jieba.analyse.extract_tags(
        all_text,
        topK=TOP_KEYWORDS,
        withWeight=False,
        allowPOS=("n", "vn", "v", "nr", "ns")  # 只保留名词、动词、人名、地名
    )
    
    # 过滤停用词并统计词频
    keyword_counter = Counter()
    for keyword in keywords:
        if keyword not in STOPWORDS and len(keyword) > 1:
            keyword_counter[keyword] += all_text.count(keyword)
    
    return category_stats, keyword_counter.most_common(TOP_KEYWORDS)


# ===================== HTML 渲染 =====================
def render_news_items(items: List[Dict[str, str]]) -> str:
    """渲染新闻列表为 HTML"""
    item_html = []
    for item in items:
        category_tag = f'<span class="category {item["category"].replace(" ", "")}">{item["category"]}</span>'
        time_tag = f'<span class="time">{item["published"]}</span>' if item["published"] else ""
        
        item_html.append(f"""
<li class="news-item">
    {category_tag}
    <a href="{item["link"]}" target="_blank" rel="noopener noreferrer" class="news-title">{item["title"]}</a>
    {time_tag}
</li>
        """.strip())
    
    return "\n".join(item_html)


def render_keywords(keywords: List[Tuple[str, int]]) -> str:
    """渲染关键词云 HTML"""
    if not keywords:
        return '<div class="keyword-item">暂无关键词</div>'
    
    keyword_html = []
    for word, count in keywords:
        # 根据词频设置字体大小
        size = min(12 + count * 2, 24)  # 字体大小范围：12-24px
        keyword_html.append(f'<span class="keyword-item" style="font-size: {size}px;">{word}</span>')
    
    return "\n".join(keyword_html)


def render_category_stats(stats: Dict[str, int]) -> str:
    """渲染分类统计 HTML（简单的百分比展示）"""
    total = sum(stats.values())
    if total == 0:
        return '<div class="category-item">暂无数据</div>'
    
    category_html = []
    for cat, count in stats.items():
        percentage = round((count / total) * 100, 1)
        category_html.append(f"""
<div class="category-item">
    <span class="category-name">{cat}</span>
    <span class="category-value">{count}条 ({percentage}%)</span>
</div>
        """.strip())
    
    return "\n".join(category_html)


# ===================== 文件处理 =====================
def load_template(path: str) -> str:
    """加载 HTML 模板"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # 提供默认模板（如果用户未提供）
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>全球重大事件汇总</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .update-time { color: #666; font-size: 14px; }
        .analysis-section { display: flex; gap: 20px; margin-bottom: 30px; }
        .keywords, .categories { flex: 1; padding: 15px; border: 1px solid #eee; border-radius: 8px; }
        .keyword-item { display: inline-block; margin: 5px; padding: 5px 10px; background: #f0f0f0; border-radius: 4px; }
        .category-item { margin: 10px 0; padding: 8px; border-bottom: 1px dashed #eee; }
        .news-list { list-style: none; padding: 0; }
        .news-item { margin: 10px 0; padding: 10px; border: 1px solid #eee; border-radius: 4px; }
        .category { font-size: 12px; padding: 2px 6px; border-radius: 3px; margin-right: 8px; }
        .category.国际新闻 { background: #e1f5fe; color: #01579b; }
        .category.国内要闻 { background: #e8f5e9; color: #2e7d32; }
        .category.财经大事 { background: #fff3e0; color: #e65100; }
        .category.全球时政 { background: #f3e5f5; color: #4a148c; }
        .category.突发新闻 { background: #ffebee; color: #c62828; }
        .news-title { text-decoration: none; color: #333; }
        .news-title:hover { color: #2196f3; }
        .time { color: #999; font-size: 12px; margin-left: 10px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>全球重大事件汇总</h1>
        <div class="update-time">最后更新：{{UPDATED_AT}}</div>
    </div>
    
    <div class="analysis-section">
        <div class="keywords">
            <h3>热点关键词</h3>
            {{TOP_KEYWORDS}}
        </div>
        <div class="categories">
            <h3>新闻分类统计</h3>
            {{CATEGORY_STATS}}
        </div>
    </div>
    
    <div class="news-section">
        <h3>最新新闻列表</h3>
        <ul class="news-list">
            {{NEWS_ITEMS}}
        </ul>
    </div>
</body>
</html>
        """


def save_analysis_results(stats: Dict[str, int], keywords: List[Tuple[str, int]], path: str):
    """保存分析结果到 JSON 文件（便于后续扩展）"""
    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "category_stats": stats,
        "top_keywords": keywords
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"警告：保存分析结果失败 - {str(e)}")


def write_output(path: str, html: str):
    """写入最终 HTML 文件"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"成功生成 HTML 文件：{path}")
    except Exception as e:
        print(f"错误：写入 HTML 文件失败 - {str(e)}")


# ===================== 主函数 =====================
def main():
    """主执行流程"""
    # 1. 加载模板
    template = load_template(TEMPLATE_PATH)
    
    # 2. 抓取 RSS 数据
    print("开始抓取 RSS 新闻...")
    news_items = fetch_rss_items(RSS_URLS, MAX_ITEMS_PER_SOURCE, TOTAL_MAX_ITEMS)
    print(f"抓取到 {len(news_items)} 条唯一新闻")
    
    # 3. 分析新闻内容
    print("开始分析新闻内容...")
    category_stats, top_keywords = analyze_news_items(news_items)
    print(f"提取到 {len(top_keywords)} 个热点关键词")
    
    # 4. 渲染 HTML 内容
    print("开始生成 HTML 页面...")
    news_html = render_news_items(news_items)
    keywords_html = render_keywords(top_keywords)
    category_html = render_category_stats(category_stats)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 5. 替换模板占位符
    final_html = template
    placeholders = {
        PLACEHOLDER_ITEMS: news_html,
        PLACEHOLDER_UPDATED: updated_at,
        PLACEHOLDER_KEYWORDS: keywords_html,
        PLACEHOLDER_CATEGORY_STATS: category_html
    }
    
    for placeholder, content in placeholders.items():
        if placeholder in final_html:
            final_html = final_html.replace(placeholder, content)
        else:
            # 兼容注释标记
            comment_tag = placeholder.strip("{}").lower()
            pattern = rf"<!--\s*{comment_tag}_start\s*-->.*?<!--\s*{comment_tag}_end\s*-->"
            final_html = re.sub(pattern, f"<!-- {comment_tag}_start -->\n{content}\n<!-- {comment_tag}_end -->", final_html, flags=re.S)
    
    # 6. 写入输出文件
    write_output(OUTPUT_PATH, final_html)
    
    # 7. 保存分析结果
    save_analysis_results(category_stats, top_keywords, KEYWORD_STATS_PATH)
    
    print("所有操作完成！")


if __name__ == "__main__":
    # 安装依赖（首次运行时）
    required_packages = ["feedparser", "requests", "beautifulsoup4", "jieba"]
    missing_packages = []
    
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing_packages.append(pkg)
    
    if missing_packages:
        print(f"正在安装缺失的依赖：{', '.join(missing_packages)}")
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_packages])
    
    # 执行主程序
    main()