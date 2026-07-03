import csv
import html
import io
import re
import textwrap
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Tuple
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import streamlit as st


# =========================
# Siltherm 默认销售背景
# =========================

COMPANY_NAME = "Siltherm"
COMPANY_POSITIONING = (
    "advanced insulation materials and thermal management solutions"
)
TARGET_MARKETS = ["Europe", "Germany", "DACH"]
PUBLIC_APP_URL = "https://siltherm-news-radar.streamlit.app"


# 这些关键词会影响行业分类。现在只保留用户要看的 3 个大类：ESS / EV / AI。
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "ESS": [
        "bess",
        "battery energy storage",
        "energy storage system",
        "grid-scale storage",
        "containerized storage",
        "storage container",
        "utility-scale storage",
        "residential energy storage",
        "home battery",
        "household storage",
        "solar storage",
        "behind-the-meter",
        "virtual power plant",
        "vpp",
        "储能",
        "储能集装箱",
        "大型储能",
        "户储",
        "家庭储能",
        "家用储能",
        "虚拟电厂",
    ],
    "EV": [
        "ev",
        "electric vehicle",
        "e-mobility",
        "automotive battery",
        "battery pack",
        "battery module",
        "cell-to-pack",
        "gigafactory",
        "traction battery",
        "电动车",
        "动力电池",
        "电池包",
    ],
    "AI": [
        "ai data center",
        "data centre",
        "data center",
        "hyperscale",
        "gpu cluster",
        "power infrastructure",
        "backup power",
        "ups",
        "liquid cooling",
        "数据中心",
        "智算中心",
        "算力",
        "electrical cabinet",
        "control cabinet",
        "switchgear",
        "power cabinet",
        "distribution cabinet",
        "enclosure",
        "inverter cabinet",
        "pcs cabinet",
        "电气柜",
        "电力柜",
        "配电柜",
        "控制柜",
        "industrial thermal management",
        "critical power",
    ],
}


# 这些不再作为分类展示，而是作为销售触发信号保留。
SIGNAL_KEYWORDS: Dict[str, List[str]] = {
    "VPP": ["vpp", "virtual power plant", "虚拟电厂", "aggregator", "demand response"],
    "battery thermal safety": [
        "battery thermal safety",
        "thermal runaway",
        "fire propagation",
        "battery fire",
        "fire safety",
        "安全",
        "热失控",
    ],
    "expansion": [
        "factory",
        "plant",
        "production line",
        "capacity",
        "investment",
        "expansion",
        "launch",
        "order",
        "contract",
        "partnership",
        "gigawatt",
        "mw",
        "mwh",
        "工厂",
        "扩产",
        "投产",
        "项目",
        "订单",
    ],
}


# 自动新闻雷达会按这 3 个大类去扫 Google News RSS。每个主题都自动加 Europe / Germany / DACH。
TRACKED_NEWS_QUERIES: Dict[str, str] = {
    "ESS": "BESS energy storage thermal safety battery storage",
    "EV": "EV battery pack thermal safety electric vehicle battery",
    "AI": "AI data center power infrastructure critical power thermal management",
}


COUNTRY_ALIASES: Dict[str, List[str]] = {
    "Germany": ["germany", "german", "deutschland", "德国"],
    "Austria": ["austria", "österreich", "oesterreich", "奥地利"],
    "Switzerland": ["switzerland", "swiss", "schweiz", "suisse", "瑞士"],
    "Netherlands": ["netherlands", "dutch", "holland", "荷兰"],
    "France": ["france", "french", "法国"],
    "Italy": ["italy", "italian", "意大利"],
    "Spain": ["spain", "spanish", "西班牙"],
    "Poland": ["poland", "polish", "波兰"],
    "Czech Republic": ["czech", "czechia", "捷克"],
    "Hungary": ["hungary", "hungarian", "匈牙利"],
    "Sweden": ["sweden", "swedish", "瑞典"],
    "Norway": ["norway", "norwegian", "挪威"],
    "Denmark": ["denmark", "danish", "丹麦"],
    "Finland": ["finland", "finnish", "芬兰"],
    "United Kingdom": ["uk", "u.k.", "britain", "united kingdom", "英国"],
    "Europe": ["europe", "european", "eu", "欧洲", "欧盟"],
}


JOB_TITLE_MAP: Dict[str, List[str]] = {
    "ESS": [
        "BESS Product Manager",
        "Energy Storage System Engineering Manager",
        "Battery Safety / Compliance Manager",
        "Project Procurement Manager",
        "Grid Storage Technical Director",
        "Residential ESS Product Manager",
        "VPP / Aggregation Partnerships Manager",
    ],
    "EV": [
        "Battery Pack Engineering Manager",
        "Thermal Management Engineer",
        "Battery Safety Engineer",
        "EV Platform / Battery System Product Manager",
        "Strategic Sourcing Manager - Battery Components",
    ],
    "AI": [
        "Data Center Power Infrastructure Manager",
        "Critical Power Engineering Manager",
        "Data Center Design Manager",
        "Thermal / Fire Safety Manager",
        "Procurement Manager - Power Systems",
        "Electrical Cabinet Product Manager",
        "Switchgear Engineering Manager",
        "Electrical Design Engineer",
        "Panel Builder Technical Director",
        "Procurement Manager - Enclosures and Insulation",
        "Thermal Management Engineering Manager",
        "Industrial Safety Manager",
        "Materials Engineering Manager",
        "R&D Manager - Insulation Materials",
        "Technical Procurement Manager",
    ],
}


CSV_COLUMNS = [
    "分析时间",
    "雷达主题",
    "发布时间",
    "输入类型",
    "标题",
    "链接",
    "摘要",
    "分类",
    "重点信号",
    "相关性评分",
    "评分理由",
    "涉及公司",
    "项目或产品线",
    "国家/地区",
    "推荐联系岗位",
    "LinkedIn建联话术",
    "英文冷邮件主题",
    "英文冷邮件正文",
    "原文节选",
]


class TextExtractor(HTMLParser):
    """从网页 HTML 里提取可读文字，避免依赖复杂爬虫库。"""

    def __init__(self) -> None:
        super().__init__()
        self.skip_tag = False
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_tag = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_tag = False

    def handle_data(self, data: str) -> None:
        if not self.skip_tag:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned)

    def get_text(self) -> str:
        return " ".join(self.parts)


def normalize_text(text: str) -> str:
    """统一空格，方便后续分析。"""
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def split_sentences(text: str) -> List[str]:
    """把新闻正文切成句子，中英文标点都兼容。"""
    text = normalize_text(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[。！？.!?])\s+|(?<=[。！？])", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def keyword_count(text_lower: str, keywords: List[str]) -> int:
    """统计关键词命中次数，用于分类和打分。"""
    return sum(text_lower.count(k.lower()) for k in keywords)


def fetch_url_text(url: str) -> Tuple[str, str]:
    """读取新闻链接正文。部分网站有反爬或登录墙，失败时会给出友好提示。"""
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=12) as response:
        raw = response.read(1_500_000)
        charset = response.headers.get_content_charset() or "utf-8"
        html_text = raw.decode(charset, errors="ignore")

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
    title = normalize_text(title_match.group(1)) if title_match else urlparse(url).netloc

    extractor = TextExtractor()
    extractor.feed(html_text)
    body = extractor.get_text()
    return title, body


def split_news_title_source(title: str) -> Tuple[str, str]:
    """Google News 标题常见格式是“标题 - 媒体名”，这里拆一下来源。"""
    if " - " not in title:
        return title, ""
    clean_title, source = title.rsplit(" - ", 1)
    return clean_title.strip(), source.strip()


def fetch_google_news_rss(keyword: str, limit: int = 5) -> List[Dict[str, str]]:
    """用 Google News RSS 抓取关键词新闻，适合第一版本地雷达使用。"""
    query = quote_plus(f"{keyword} Germany OR DACH OR Europe")
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={query}&hl=en-DE&gl=DE&ceid=DE:en"
    )
    request = Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=12) as response:
        xml_text = response.read().decode("utf-8", errors="ignore")

    root = ET.fromstring(xml_text)
    items: List[Dict[str, str]] = []
    for item in root.findall(".//item")[:limit]:
        raw_title = normalize_text(item.findtext("title", default=""))
        title, source = split_news_title_source(raw_title)
        link = normalize_text(item.findtext("link", default=""))
        description = normalize_text(re.sub("<.*?>", " ", item.findtext("description", default="")))
        published = normalize_text(item.findtext("pubDate", default=""))
        items.append(
            {
                "title": title,
                "link": link,
                "source": source,
                "published": published,
                "text": f"{title}. {description}. Published: {published}",
            }
        )
    return items


def scan_radar_news(per_topic_limit: int = 5, extra_keyword: str = "") -> List[Dict[str, str]]:
    """自动扫描多个重点主题，生成新闻线索池。"""
    seen = set()
    records: List[Dict[str, str]] = []
    queries = dict(TRACKED_NEWS_QUERIES)
    if extra_keyword.strip():
        queries["自定义关键词"] = extra_keyword.strip()

    for topic, keyword in queries.items():
        try:
            items = fetch_google_news_rss(keyword, limit=per_topic_limit)
        except Exception:
            # 单个主题失败不影响其他主题扫描。
            continue

        for item in items:
            key = item["link"] or item["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            record = analyze_item(item["title"], item["link"], item["text"], "自动雷达")
            categories = record_categories(record)
            if topic in {"ESS", "EV", "AI"} and topic not in categories:
                categories = [topic] if categories == ["待判断"] else [topic] + categories
                signals = (
                    []
                    if record.get("重点信号") == "未识别"
                    else [signal.strip() for signal in record.get("重点信号", "").split("/") if signal.strip()]
                )
                countries = (
                    []
                    if record.get("国家/地区") == "待补充"
                    else [country.strip() for country in record.get("国家/地区", "").split("；") if country.strip()]
                )
                company = "" if record.get("涉及公司") == "待补充" else record.get("涉及公司", "").split("；")[0]
                jobs = recommend_job_titles(categories, signals)
                email_subject, email_body = generate_cold_email(
                    company,
                    record.get("标题", ""),
                    categories,
                    countries,
                    jobs,
                )
                record["分类"] = " / ".join(categories)
                record["推荐联系岗位"] = "；".join(jobs)
                record["LinkedIn建联话术"] = generate_linkedin_note(
                    company,
                    record.get("标题", ""),
                    categories,
                )
                record["英文冷邮件主题"] = email_subject
                record["英文冷邮件正文"] = email_body
            record["雷达主题"] = topic
            record["发布时间"] = item.get("published", "")
            if item.get("source"):
                record["标题"] = f'{record["标题"]} · {item["source"]}'
            records.append(record)

    records.sort(key=lambda r: int(r.get("相关性评分", "1")), reverse=True)
    return records


def summarize_news(title: str, text: str) -> str:
    """抽取最像销售线索的 3 句话，形成新闻摘要。"""
    sentences = split_sentences(text)
    if not sentences:
        return normalize_text(title)[:500] or "未提取到足够正文，可尝试粘贴新闻正文。"

    scoring_terms = []
    for terms in CATEGORY_KEYWORDS.values():
        scoring_terms.extend(terms)
    for terms in SIGNAL_KEYWORDS.values():
        scoring_terms.extend(terms)
    scoring_terms.extend(["Germany", "DACH", "Europe", "project", "plant", "partnership"])

    ranked = []
    for index, sentence in enumerate(sentences):
        lower = sentence.lower()
        score = keyword_count(lower, scoring_terms)
        # 新闻开头通常最重要，给前 5 句一点权重。
        if index < 5:
            score += 1
        ranked.append((score, index, sentence))

    best = sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]
    best_sorted = [sentence for _, _, sentence in sorted(best, key=lambda item: item[1])]
    return " ".join(best_sorted)[:900]


def classify_news(text: str) -> Tuple[List[str], List[str]]:
    """根据关键词把新闻归入 Siltherm 关心的行业分类。"""
    lower = text.lower()
    category_scores = {
        category: keyword_count(lower, keywords)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    categories = [category for category, score in category_scores.items() if score > 0]

    # 如果只有 VPP 线索，通常先按 ESS 处理。
    if not categories and keyword_count(lower, SIGNAL_KEYWORDS["VPP"]) > 0:
        categories.append("ESS")

    signals = [
        signal for signal, keywords in SIGNAL_KEYWORDS.items() if keyword_count(lower, keywords) > 0
    ]
    return categories or ["待判断"], signals


def extract_countries(text: str) -> List[str]:
    """提取欧洲、德国、DACH 相关国家。"""
    lower = text.lower()
    countries = []
    for country, aliases in COUNTRY_ALIASES.items():
        if any(alias.lower() in lower for alias in aliases):
            countries.append(country)
    return countries


def extract_companies(text: str, title: str) -> List[str]:
    """用常见公司后缀和大写短语提取公司名，第一版先做轻量识别。"""
    source = f"{title}. {text}"
    patterns = [
        r"\b[A-Z][A-Za-z0-9&.\- ]{1,60}\s(?:GmbH|AG|SE|Group|Energy|Power|Solutions|Systems|Technologies|Technology|Battery|Batteries|Automotive|Ltd|Limited|Inc|Corp|Corporation|PLC|B\.V\.|BV|AB|SAS|SA)\b",
        r"\b(?:BMW|Mercedes-Benz|Volkswagen|VW|Audi|Porsche|Siemens|ABB|Schneider Electric|Eaton|Rittal|Northvolt|CATL|BYD|Tesla|Fluence|Sungrow|Huawei|Envision|EVE Energy|LG Energy Solution|Samsung SDI)\b",
    ]
    found: List[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, source))

    # 清理明显不是公司的噪音。
    bad_words = {"Europe", "Germany", "DACH", "News", "Reuters", "Published"}
    cleaned = []
    for company in found:
        company = normalize_text(company).strip(" -|,.;:")
        if company and company not in bad_words and company not in cleaned:
            cleaned.append(company)
    return cleaned[:8]


def extract_projects_products(text: str) -> List[str]:
    """抽取包含项目、产品线、工厂、平台等信号的短句。"""
    sentences = split_sentences(text)
    project_terms = [
        "project",
        "plant",
        "factory",
        "production line",
        "platform",
        "product line",
        "battery pack",
        "bess",
        "container",
        "data center",
        "switchgear",
        "cabinet",
        "项目",
        "工厂",
        "产线",
        "产品线",
        "平台",
        "电池包",
        "储能",
        "数据中心",
        "电力柜",
    ]
    projects = []
    for sentence in sentences:
        lower = sentence.lower()
        if any(term.lower() in lower for term in project_terms):
            projects.append(sentence[:240])
    return projects[:5]


def score_relevance(text: str, categories: List[str], countries: List[str], signals: List[str]) -> Tuple[int, str]:
    """给 Siltherm 销售相关性打 1-5 分，并解释原因。"""
    lower = text.lower()
    score = 1
    reasons = []

    if any(category != "待判断" for category in categories):
        score += 1
        reasons.append("命中 Siltherm 核心分类")

    if any(country in {"Germany", "Austria", "Switzerland", "Europe"} for country in countries):
        score += 1
        reasons.append("涉及欧洲/德国/DACH 市场")

    thermal_terms = [
        "thermal management",
        "insulation",
        "thermal insulation",
        "heat shield",
        "fire protection",
        "thermal runaway",
        "flame retardant",
        "temperature control",
        "工业热管理",
        "隔热",
        "热失控",
        "阻燃",
    ]
    if "battery thermal safety" in signals or keyword_count(lower, thermal_terms) > 0:
        score += 1
        reasons.append("出现隔热、热管理、阻燃或电池热安全信号")

    if "expansion" in signals:
        score += 1
        reasons.append("出现项目、扩产、订单、合作或投资信号")

    if "VPP" in signals and "ESS" in categories:
        score += 1
        reasons.append("VPP 与 ESS 场景相关")

    score = max(1, min(score, 5))
    if not reasons:
        reasons.append("暂未出现明显的 Siltherm 销售触发点")
    return score, "；".join(reasons)


def recommend_job_titles(categories: List[str], signals: List[str]) -> List[str]:
    """根据分类推荐更可能关心 Siltherm 方案的联系人岗位。"""
    titles: List[str] = []
    for category in categories:
        titles.extend(JOB_TITLE_MAP.get(category, []))
    if "battery thermal safety" in signals:
        titles.extend(["Battery Safety Manager", "Fire Safety / Compliance Manager"])
    if "VPP" in signals:
        titles.extend(["Energy Flexibility Product Manager", "VPP / Aggregation Partnerships Manager"])

    # 去重并限制数量，方便直接导入表格。
    deduped = []
    for title in titles:
        if title not in deduped:
            deduped.append(title)
    return deduped[:8] or ["Product Manager", "Engineering Manager", "Technical Procurement Manager"]


def generate_linkedin_note(company: str, topic: str, categories: List[str]) -> str:
    """生成 LinkedIn 建联话术，控制在较短长度。"""
    topic_short = topic[:90] if topic else "your recent energy / power infrastructure news"
    category_text = ", ".join([c for c in categories if c != "待判断"][:2]) or "thermal management"
    return (
        f"Hi {{first_name}}, I saw the news about {topic_short}. "
        f"{COMPANY_NAME} works on advanced insulation and thermal management for {category_text}. "
        "Would be glad to connect and exchange ideas on thermal safety and reliability."
    )


def generate_cold_email(company: str, title: str, categories: List[str], countries: List[str], jobs: List[str]) -> Tuple[str, str]:
    """生成英文冷邮件草稿，不会发送，只供复制到 Outlook 草稿。"""
    company_text = company or "your team"
    category_text = ", ".join([c for c in categories if c != "待判断"][:3]) or "thermal management"
    country_text = ", ".join(countries[:2]) if countries else "Europe"
    job_text = jobs[0] if jobs else "your engineering team"

    subject = f"Thermal insulation ideas for {company_text}'s {category_text} work"
    body = f"""Hi {{first_name}},

I noticed the recent news about {title or company_text}, especially its relevance to {category_text} in {country_text}.

Siltherm provides advanced insulation materials and thermal management solutions for battery systems, energy storage, power infrastructure, electrical cabinets and thermal safety applications.

For teams like {job_text}, we typically look for ways to support:
- Better thermal insulation and temperature stability
- Improved battery and cabinet fire-safety design
- More reliable integration in high-power or space-constrained systems

Would it be useful to exchange a few technical notes or arrange a short call to see whether Siltherm materials could support your current projects?

Best regards,
{{your_name}}
{COMPANY_NAME}
"""
    return subject, body


def analyze_item(title: str, link: str, text: str, input_type: str) -> Dict[str, str]:
    """把一条新闻转成销售线索记录。"""
    combined_text = normalize_text(f"{title}. {text}")
    categories, signals = classify_news(combined_text)
    countries = extract_countries(combined_text)
    companies = extract_companies(combined_text, title)
    projects = extract_projects_products(combined_text)
    score, reason = score_relevance(combined_text, categories, countries, signals)
    jobs = recommend_job_titles(categories, signals)
    summary = summarize_news(title, combined_text)

    primary_company = companies[0] if companies else ""
    linkedin_note = generate_linkedin_note(primary_company, title or summary, categories)
    email_subject, email_body = generate_cold_email(
        primary_company, title or summary[:120], categories, countries, jobs
    )

    return {
        "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "输入类型": input_type,
        "标题": title or "未识别标题",
        "链接": link,
        "摘要": summary,
        "分类": " / ".join(categories),
        "重点信号": " / ".join(signals) if signals else "未识别",
        "相关性评分": str(score),
        "评分理由": reason,
        "涉及公司": "；".join(companies) if companies else "待补充",
        "项目或产品线": "；".join(projects) if projects else "待补充",
        "国家/地区": "；".join(countries) if countries else "待补充",
        "推荐联系岗位": "；".join(jobs),
        "LinkedIn建联话术": linkedin_note,
        "英文冷邮件主题": email_subject,
        "英文冷邮件正文": email_body,
        "原文节选": combined_text[:1200],
    }


def records_to_csv(records: List[Dict[str, str]]) -> bytes:
    """把页面里的线索记录导出为 CSV，方便导入飞书多维表格。"""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow(record)
    return output.getvalue().encode("utf-8-sig")


def render_record(record: Dict[str, str]) -> None:
    """渲染单条分析结果。"""
    score = int(record["相关性评分"])
    score_color = {
        1: "#eee9e2",
        2: "#e6edf3",
        3: "#e6f1fb",
        4: "#fff2c8",
        5: "#fde8ee",
    }.get(score, "#e6edf3")

    st.markdown(
        f"""
        <div class="result-card">
          <div class="result-head">
            <div>
              <div class="eyebrow">SALES SIGNAL · {record["分类"]}</div>
              <h3>{html.escape(record["标题"])}</h3>
            </div>
            <div class="score" style="background:{score_color};">{score}/5</div>
          </div>
          <p>{html.escape(record["摘要"])}</p>
          <div class="meta-row">
            <span>{html.escape(record["重点信号"])}</span>
            <span>{html.escape(record["国家/地区"])}</span>
            <span>{html.escape(record["评分理由"])}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        st.text_area("LinkedIn 建联话术", record["LinkedIn建联话术"], height=120)
        st.text_area("推荐联系岗位", record["推荐联系岗位"], height=120)
    with right:
        st.text_input("英文冷邮件主题", record["英文冷邮件主题"])
        st.text_area("英文冷邮件正文", record["英文冷邮件正文"], height=260)

    with st.expander("查看结构化字段"):
        st.json({key: record[key] for key in CSV_COLUMNS if key in record})


def record_categories(record: Dict[str, str]) -> List[str]:
    """把记录里的分类字段拆成列表，方便页面筛选。"""
    categories = [
        category.strip()
        for category in record.get("分类", "").split("/")
        if category.strip()
    ]
    return categories or ["待判断"]


def build_summary_rows(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """生成总结版表格，只保留销售筛选最需要看的字段。"""
    rows: List[Dict[str, str]] = []
    for record in records:
        rows.append(
            {
                "评分": f'{record.get("相关性评分", "1")}/5',
                "分类": record.get("分类", ""),
                "标题": record.get("标题", ""),
                "国家": record.get("国家/地区", ""),
                "公司": record.get("涉及公司", ""),
                "推荐联系岗位": record.get("推荐联系岗位", ""),
            }
        )
    return rows


def main() -> None:
    st.set_page_config(
        page_title="Siltherm 行业新闻雷达",
        page_icon="S",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        <style>
        :root {
            --ink: #20242c;
            --muted: #697586;
            --line: #ece3d9;
            --panel: #fffdfa;
            --paper: #fbf7f1;
            --mint: #dff3eb;
            --mint-ink: #2f766a;
            --rose: #fde8ee;
            --rose-ink: #9a5870;
            --sky: #e6f1fb;
            --sky-ink: #3e6f99;
            --butter: #fff2c8;
            --butter-ink: #8c6a16;
            --lavender: #eee9fb;
            --lavender-ink: #665a92;
            --sage: #e5eddb;
            --taupe: #8b786d;
        }
        .stApp {background: var(--paper);}
        .main .block-container {padding-top: 1.35rem; max-width: 1180px;}
        h1, h2, h3, p {letter-spacing: 0;}
        div[data-testid="stSidebar"] {background: #fffaf4; border-right: 1px solid var(--line);}
        div[data-testid="stVerticalBlock"] {gap: .8rem;}
        .topbar {
            color: var(--ink);
            padding: 8px 2px 20px;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--line);
            position: relative;
        }
        .brand-row {
            display:flex;
            justify-content:space-between;
            gap: 8px;
            align-items:flex-start;
            position:relative;
            z-index:1;
        }
        .brand-kicker {
            color: var(--taupe);
            font-size: .78rem;
            font-weight: 760;
            letter-spacing: .08em;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .app-title {
            font-size: 2rem;
            line-height:1.12;
            font-weight: 780;
            margin-bottom: .42rem;
            color: var(--ink);
        }
        .app-subtitle {color: var(--muted); max-width: 700px; font-size: 1rem;}
        .local-badge {
            border: 1px solid #eadfce;
            border-radius: 6px;
            padding: 7px 10px;
            color: #7a665b;
            background: #fffaf4;
            font-size: .82rem;
            white-space: nowrap;
            font-weight: 680;
        }
        .signal-bar {
            display:flex;
            flex-wrap:wrap;
            gap: 10px;
            margin-top: 18px;
            align-items:center;
        }
        .soft-pill {
            border-radius: 999px;
            padding: 7px 11px;
            font-size: .84rem;
            font-weight: 720;
            color: var(--ink);
            border: 1px solid rgba(32,36,44,.04);
        }
        .pill-mint {background: var(--mint); color: var(--mint-ink);}
        .pill-rose {background: var(--rose); color: var(--rose-ink);}
        .pill-sky {background: var(--sky); color: var(--sky-ink);}
        .pill-butter {background: var(--butter); color: var(--butter-ink);}
        .pill-lavender {background: var(--lavender); color: var(--lavender-ink);}
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            background: #fffaf4;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 4px;
            width: fit-content;
            margin-bottom: 10px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px;
            padding: 8px 16px;
            color: var(--muted);
            font-weight: 720;
        }
        .stTabs [aria-selected="true"] {
            background: #ffffff;
            color: var(--ink);
            box-shadow: 0 3px 10px rgba(32,36,44,.05);
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 18px 18px;
            box-shadow: 0 9px 24px rgba(79, 60, 42, .045);
        }
        .panel-title {
            font-weight: 760;
            color: var(--ink);
            margin: 0 0 8px;
            font-size: 1.06rem;
        }
        .hint-line {
            color: var(--muted);
            font-size: .88rem;
            margin: -2px 0 13px;
        }
        .result-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 16px 17px;
            margin: 14px 0 10px;
            background: #fffefd;
            box-shadow: 0 8px 22px rgba(79, 60, 42, .04);
        }
        .result-head {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: start;
        }
        .result-card h3 {font-size: 1.08rem; margin: 0.1rem 0 .55rem; color: var(--ink);}
        .eyebrow {font-size: .72rem; color: var(--taupe); font-weight: 780; text-transform: uppercase;}
        .score {color: var(--ink); min-width: 54px; text-align: center; border-radius: 6px; padding: 8px 10px; font-weight: 760;}
        .meta-row {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px;}
        .meta-row span {background: #f5efe8; color: #5b4f48; border-radius: 999px; padding: 5px 9px; font-size: .8rem;}
        .empty-state {
            border: 1px dashed #e1d4c7;
            border-radius: 8px;
            padding: 18px;
            background: #fffaf4;
            color: var(--muted);
            font-size: .92rem;
        }
        div.stButton > button[kind="primary"] {
            background: #2f343b;
            border: 1px solid #2f343b;
            color: #ffffff;
            border-radius: 8px;
            font-weight: 760;
            min-height: 2.55rem;
        }
        div.stButton > button:not([kind="primary"]) {
            border-radius: 8px;
            border-color: #e1d4c7;
            color: #584c44;
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        textarea {
            border-radius: 8px !important;
            background: #fffaf4 !important;
            border-color: #e6dacd !important;
        }
        div[data-baseweb="radio"] label {
            background: #fffaf4;
            border: 1px solid #eadfce;
            border-radius: 999px;
            padding: 4px 10px;
            margin-right: 4px;
        }
        div[data-testid="stDownloadButton"] button {
            border-radius: 8px;
            background: #fffaf4;
            border-color: #e1d4c7;
            color: #584c44;
            font-weight: 720;
        }
        div[data-testid="stMetric"] {
            background: #fffaf4;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 10px 12px;
        }
        div[data-testid="stMetricLabel"] p {color: var(--muted); font-size: .78rem;}
        div[data-testid="stMetricValue"] {color: var(--ink); font-size: 1.34rem;}
        .stDataFrame {border-radius: 8px; overflow: hidden;}
        @media (max-width: 820px) {
            .brand-row {display:block;}
            .local-badge {display:inline-block; margin-top: 12px;}
            .signal-bar {gap: 8px;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "records" not in st.session_state:
        st.session_state.records = []
    if "radar_records" not in st.session_state:
        st.session_state.radar_records = []

    st.markdown(
        f"""
        <section class="topbar">
          <div class="brand-row">
            <div>
              <div class="brand-kicker">Siltherm Market Intelligence</div>
              <div class="app-title">Siltherm 行业新闻雷达</div>
              <div class="app-subtitle">Europe / Germany / DACH · advanced insulation materials and thermal management solutions</div>
            </div>
            <div class="local-badge">PUBLIC WEB APP · siltherm-news-radar.streamlit.app</div>
          </div>
          <div class="signal-bar">
            <span class="soft-pill pill-mint">ESS</span>
            <span class="soft-pill pill-rose">EV</span>
            <span class="soft-pill pill-sky">AI</span>
            <span class="soft-pill pill-butter">DACH Focus</span>
            <span class="soft-pill pill-lavender">Sales Relevance 1-5</span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    radar_tab, manual_tab = st.tabs(["自动新闻雷达", "手动分析"])

    with radar_tab:
        radar_control_col, radar_output_col = st.columns([0.85, 1.15], gap="large")

        with radar_control_col:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="panel-title">自动新闻池</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="hint-line">每天打开后先点这里，它会按 ESS / EV / AI 自动抓新闻候选。</div>',
                unsafe_allow_html=True,
            )
            per_topic_limit = st.slider("每类抓取数量", 3, 15, 8, key="radar_limit")
            extra_keyword = st.text_input(
                "额外关键词（可选）",
                placeholder="例如：thermal runaway Germany",
                key="radar_extra_keyword",
            )
            scan_clicked = st.button(
                "一键扫描 ESS / EV / AI 新闻",
                type="primary",
                use_container_width=True,
            )
            clear_radar_clicked = st.button("清空自动新闻池", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown(
                """
                <div class="empty-state">
                  <b>Radar scope</b><br>
                  Google News RSS · ESS / EV / AI · Europe / Germany / DACH · CSV ready
                </div>
                """,
                unsafe_allow_html=True,
            )

            if clear_radar_clicked:
                st.session_state.radar_records = []
                st.rerun()

        with radar_output_col:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="panel-title">今日雷达结果</div>', unsafe_allow_html=True)

            if scan_clicked:
                with st.spinner("正在扫描新闻源，通常需要几十秒..."):
                    st.session_state.radar_records = scan_radar_news(
                        per_topic_limit=per_topic_limit,
                        extra_keyword=extra_keyword,
                    )
                if not st.session_state.radar_records:
                    st.warning("这次没有抓到新闻。可以稍后再试，或在额外关键词里加 Germany / Europe / thermal safety。")

            radar_records: List[Dict[str, str]] = st.session_state.radar_records
            if radar_records:
                filter_col1, filter_col2 = st.columns([0.45, 0.55])
                with filter_col1:
                    min_score = st.slider("最低相关性评分", 1, 5, 3, key="radar_min_score")
                with filter_col2:
                    selected_categories = st.multiselect(
                        "分类筛选",
                        ["ESS", "EV", "AI"],
                        default=["ESS", "EV", "AI"],
                        key="radar_category_filter",
                    )
                selected_categories = selected_categories or ["ESS", "EV", "AI"]

                filtered_records = [
                    record
                    for record in radar_records
                    if int(record.get("相关性评分", "1")) >= min_score
                    and any(category in selected_categories for category in record_categories(record))
                ]

                metric_cols = st.columns(4)
                metric_cols[0].metric("筛选后新闻", len(filtered_records))
                metric_cols[1].metric(
                    "高分线索",
                    sum(int(record.get("相关性评分", "1")) >= 4 for record in filtered_records),
                )
                metric_cols[2].metric(
                    "ESS",
                    sum("ESS" in record_categories(record) for record in filtered_records),
                )
                metric_cols[3].metric(
                    "EV / AI",
                    sum(
                        any(category in record_categories(record) for category in ["EV", "AI"])
                        for record in filtered_records
                    ),
                )

                if filtered_records:
                    csv_bytes = records_to_csv(filtered_records)
                    st.download_button(
                        "导出当前筛选结果 CSV",
                        data=csv_bytes,
                        file_name=f"siltherm_auto_news_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                    summary_tab, detail_tab = st.tabs(["总结版", "逐条分析"])
                    with summary_tab:
                        st.dataframe(
                            build_summary_rows(filtered_records),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.markdown("#### 今日优先看")
                        for record in filtered_records[:5]:
                            st.markdown(
                                f'- **{record.get("相关性评分", "1")}/5 · {record.get("分类", "")}** '
                                f'{record.get("标题", "")}  \n'
                                f'  {record.get("评分理由", "")}'
                            )

                    with detail_tab:
                        selected_index = st.selectbox(
                            "选择一条新闻查看完整分析",
                            options=list(range(len(filtered_records))),
                            format_func=lambda index: (
                                f'{filtered_records[index].get("相关性评分", "1")}/5 · '
                                f'{filtered_records[index].get("分类", "")} · '
                                f'{filtered_records[index].get("标题", "")[:90]}'
                            ),
                        )
                        selected_record = filtered_records[selected_index]
                        if selected_record.get("链接"):
                            st.markdown(f'[打开原文]({selected_record["链接"]})')
                        render_record(selected_record)
                else:
                    st.markdown(
                        """
                        <div class="empty-state">
                          当前筛选条件下没有新闻。可以把最低评分调低，或取消某些分类筛选。
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    """
                    <div class="empty-state">
                      还没有自动新闻池。点击左侧“一键扫描 ESS / EV / AI 新闻”，这里会先给总结版，再让你逐条点开分析。
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

    with manual_tab:
        input_col, output_col = st.columns([0.92, 1.08], gap="large")

        with input_col:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="panel-title">新闻输入</div>', unsafe_allow_html=True)
            st.markdown('<div class="hint-line">如果你已经有具体新闻，就在这里粘贴链接或正文单独分析。</div>', unsafe_allow_html=True)
            input_type = st.radio(
                "选择输入类型",
                ["关键词", "新闻链接", "新闻正文"],
                horizontal=True,
            )

            max_news = 5
            title = ""
            link = ""
            body = ""
            keyword = ""

            if input_type == "关键词":
                keyword = st.text_input(
                    "关键词",
                    value="BESS thermal safety Germany",
                    placeholder="例如：BESS thermal safety Germany",
                )
                max_news = st.slider("抓取新闻数量", 1, 10, 5)
            elif input_type == "新闻链接":
                link = st.text_input(
                    "新闻链接",
                    placeholder="https://example.com/news/article",
                )
            else:
                title = st.text_input("新闻标题", placeholder="粘贴新闻标题")
                body = st.text_area("新闻正文", height=260, placeholder="粘贴新闻正文或摘要")
                link = st.text_input("原文链接（可选）")

            analyze_clicked = st.button("分析新闻", type="primary", use_container_width=True)

            clear_clicked = st.button("清空本页结果", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

            if clear_clicked:
                st.session_state.records = []
                st.rerun()

        with output_col:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown('<div class="panel-title">销售线索结果</div>', unsafe_allow_html=True)
            if analyze_clicked:
                try:
                    new_records: List[Dict[str, str]] = []
                    if input_type == "关键词":
                        if not keyword.strip():
                            st.warning("请先输入关键词。")
                        else:
                            items = fetch_google_news_rss(keyword.strip(), limit=max_news)
                            if not items:
                                st.warning("没有抓到新闻。可以换一个关键词，或直接粘贴新闻链接/正文。")
                            for item in items:
                                new_records.append(
                                    analyze_item(
                                        item["title"],
                                        item["link"],
                                        item["text"],
                                        "关键词RSS",
                                    )
                                )
                    elif input_type == "新闻链接":
                        if not link.strip():
                            st.warning("请先输入新闻链接。")
                        else:
                            fetched_title, fetched_text = fetch_url_text(link.strip())
                            new_records.append(
                                analyze_item(fetched_title, link.strip(), fetched_text, "新闻链接")
                            )
                    else:
                        if not body.strip() and not title.strip():
                            st.warning("请先粘贴新闻标题或正文。")
                        else:
                            new_records.append(analyze_item(title, link, body, "新闻正文"))

                    st.session_state.records = new_records + st.session_state.records
                except Exception as exc:
                    st.error(f"分析失败：{exc}")
                    st.info("如果网站无法抓取，可以复制新闻正文，切换到“新闻正文”再分析。")

            records: List[Dict[str, str]] = st.session_state.records
            if records:
                csv_bytes = records_to_csv(records)
                st.download_button(
                    "导出 CSV",
                    data=csv_bytes,
                    file_name=f"siltherm_news_radar_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

                for record in records:
                    render_record(record)
            else:
                st.markdown(
                    """
                    <div class="empty-state">
                      这里会显示销售线索卡片。先输入关键词，点击“分析新闻”，再看 1-5 分评分和外联草稿。
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("Siltherm Radar")
        st.caption("公网网页地址")
        st.code(PUBLIC_APP_URL)
        st.header("分类")
        st.write("ESS：BESS、户储、VPP、储能安全")
        st.write("EV：电池包、动力电池、整车电动化")
        st.write("AI：AI 数据中心、电力基础设施、电力柜")
        st.header("评分")
        st.write("5 分：强相关，适合马上加入外联列表。")
        st.write("3-4 分：建议人工复核后跟进。")
        st.write("1-2 分：弱相关，作为市场观察。")


if __name__ == "__main__":
    main()
