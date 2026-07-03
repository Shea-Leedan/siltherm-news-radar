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


# 这些关键词会影响行业分类。后续你可以直接在这里增删关键词。
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
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
    "ESS": [
        "bess",
        "battery energy storage",
        "energy storage system",
        "grid-scale storage",
        "containerized storage",
        "storage container",
        "utility-scale storage",
        "储能",
        "储能集装箱",
        "大型储能",
    ],
    "户储": [
        "residential energy storage",
        "home battery",
        "household storage",
        "solar storage",
        "behind-the-meter",
        "户储",
        "家庭储能",
        "家用储能",
    ],
    "AI数据中心": [
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
    ],
    "电力柜": [
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
    ],
    "工业热管理": [
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
    ],
}


# VPP 是重点行业信号，但最终仍映射到 ESS / 户储 / 电力系统相关销售场景。
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
    "EV": [
        "Battery Pack Engineering Manager",
        "Thermal Management Engineer",
        "Battery Safety Engineer",
        "EV Platform / Battery System Product Manager",
        "Strategic Sourcing Manager - Battery Components",
    ],
    "ESS": [
        "BESS Product Manager",
        "Energy Storage System Engineering Manager",
        "Battery Safety / Compliance Manager",
        "Project Procurement Manager",
        "Grid Storage Technical Director",
    ],
    "户储": [
        "Residential ESS Product Manager",
        "Home Battery Engineering Manager",
        "Solar Storage Product Lead",
        "Quality and Safety Manager",
        "Procurement Manager - Storage Systems",
    ],
    "AI数据中心": [
        "Data Center Power Infrastructure Manager",
        "Critical Power Engineering Manager",
        "Data Center Design Manager",
        "Thermal / Fire Safety Manager",
        "Procurement Manager - Power Systems",
    ],
    "电力柜": [
        "Electrical Cabinet Product Manager",
        "Switchgear Engineering Manager",
        "Electrical Design Engineer",
        "Panel Builder Technical Director",
        "Procurement Manager - Enclosures and Insulation",
    ],
    "工业热管理": [
        "Thermal Management Engineering Manager",
        "Industrial Safety Manager",
        "Materials Engineering Manager",
        "R&D Manager - Insulation Materials",
        "Technical Procurement Manager",
    ],
}


CSV_COLUMNS = [
    "分析时间",
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
        title = normalize_text(item.findtext("title", default=""))
        link = normalize_text(item.findtext("link", default=""))
        description = normalize_text(re.sub("<.*?>", " ", item.findtext("description", default="")))
        published = normalize_text(item.findtext("pubDate", default=""))
        items.append(
            {
                "title": title,
                "link": link,
                "text": f"{title}. {description}. Published: {published}",
            }
        )
    return items


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
        reasons.append("命中 Siltherm 重点行业")

    if any(country in {"Germany", "Austria", "Switzerland", "Europe"} for country in countries):
        score += 1
        reasons.append("涉及欧洲/德国/DACH 市场")

    if "battery thermal safety" in signals or keyword_count(lower, CATEGORY_KEYWORDS["工业热管理"]) > 0:
        score += 1
        reasons.append("出现隔热、热管理、阻燃或电池热安全信号")

    if "expansion" in signals:
        score += 1
        reasons.append("出现项目、扩产、订单、合作或投资信号")

    if "VPP" in signals and any(category in {"ESS", "户储"} for category in categories):
        score += 1
        reasons.append("VPP 与储能/户储场景相关")

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
        1: "#9ca3af",
        2: "#64748b",
        3: "#2563eb",
        4: "#d97706",
        5: "#dc2626",
    }.get(score, "#64748b")

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


def main() -> None:
    st.set_page_config(
        page_title="Siltherm 行业新闻雷达",
        page_icon="ST",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        <style>
        :root {
            --ink: #111827;
            --muted: #526070;
            --line: #e7edf4;
            --panel: #ffffff;
            --mint: #dff7ef;
            --mint-ink: #0f766e;
            --rose: #ffe8ef;
            --rose-ink: #be496f;
            --sky: #e3f2ff;
            --sky-ink: #2563eb;
            --butter: #fff4c9;
            --butter-ink: #a16207;
            --lavender: #efe9ff;
            --lavender-ink: #6d5bd0;
        }
        .stApp {background: #fbfcff;}
        .main .block-container {padding-top: 1rem; max-width: 1240px;}
        h1, h2, h3, p {letter-spacing: 0;}
        div[data-testid="stSidebar"] {background: #ffffff; border-right: 1px solid var(--line);}
        .radar-hero {
            background: #ffffff;
            color: var(--ink);
            border-radius: 8px;
            padding: 24px 26px;
            margin-bottom: 16px;
            border: 1px solid var(--line);
            position: relative;
            overflow: hidden;
            box-shadow: 0 14px 34px rgba(15, 23, 42, .06);
        }
        .color-ribbon {
            display:grid;
            grid-template-columns: 1.2fr .9fr 1fr .8fr;
            gap: 8px;
            margin-bottom: 18px;
        }
        .color-ribbon span {
            height: 8px;
            border-radius: 99px;
            display:block;
        }
        .brand-row {display:flex; justify-content:space-between; gap:16px; align-items:flex-start; position:relative; z-index:1;}
        .app-title {font-size: 2rem; line-height:1.15; font-weight: 780; margin-bottom: .38rem;}
        .app-subtitle {color: var(--muted); max-width: 760px;}
        .local-badge {
            border: 1px solid #d8e7f7;
            border-radius: 6px;
            padding: 7px 9px;
            color: var(--sky-ink);
            background: var(--sky);
            font-size: .82rem;
            white-space: nowrap;
            font-weight: 700;
        }
        .radar-strip {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 18px;
            position: relative;
            z-index: 1;
        }
        .radar-tile {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 11px 12px;
        }
        .radar-tile b {display:block; font-size:1.05rem;}
        .radar-tile span {display:block; margin-top:3px; color:var(--muted); font-size:.83rem;}
        .tile-mint {background: var(--mint); border-color: #cceee4;}
        .tile-rose {background: var(--rose); border-color: #f7d1de;}
        .tile-butter {background: var(--butter); border-color: #f4e5a6;}
        .steps {
            display:grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin: -4px 0 16px;
        }
        .step-box {
            background:#fff;
            border:1px solid var(--line);
            border-radius:8px;
            padding:13px 14px;
        }
        .step-box strong {
            display:block;
            color:var(--ink);
            margin-bottom:4px;
        }
        .step-box span {
            color:var(--muted);
            font-size:.9rem;
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 17px 18px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, .05);
        }
        .panel-title {
            font-weight: 760;
            color: var(--ink);
            margin: 0 0 10px;
            font-size: 1.06rem;
        }
        .hint-line {
            color: var(--muted);
            font-size: .9rem;
            margin: -2px 0 14px;
        }
        .result-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 17px 18px;
            margin: 14px 0 10px;
            background: #ffffff;
            box-shadow: 0 9px 24px rgba(15, 23, 42, .05);
        }
        .result-head {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: start;
        }
        .result-card h3 {font-size: 1.15rem; margin: 0.1rem 0 .55rem;}
        .eyebrow {font-size: .76rem; color: var(--mint-ink); font-weight: 800; text-transform: uppercase;}
        .score {color: #fff; min-width: 54px; text-align: center; border-radius: 6px; padding: 8px 10px; font-weight: 760;}
        .meta-row {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px;}
        .meta-row span {background: #eef2f7; color: #334155; border-radius: 6px; padding: 5px 8px; font-size: .82rem;}
        .empty-state {
            border: 1px dashed #cad7e5;
            border-radius: 8px;
            padding: 22px;
            background: #fffefe;
            color: var(--muted);
        }
        div.stButton > button[kind="primary"] {
            background: #111827;
            border: 1px solid #111827;
            color: #ffffff;
            border-radius: 8px;
            font-weight: 760;
        }
        div.stButton > button:not([kind="primary"]) {
            border-radius: 8px;
        }
        @media (max-width: 820px) {
            .brand-row {display:block;}
            .local-badge {display:inline-block; margin-top: 12px;}
            .radar-strip {grid-template-columns: 1fr;}
            .steps {grid-template-columns: 1fr;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "records" not in st.session_state:
        st.session_state.records = []

    st.markdown(
        f"""
        <section class="radar-hero">
          <div class="color-ribbon">
            <span style="background:#dff7ef"></span>
            <span style="background:#ffe8ef"></span>
            <span style="background:#e3f2ff"></span>
            <span style="background:#fff4c9"></span>
          </div>
          <div class="brand-row">
            <div>
              <div class="app-title">Siltherm 行业新闻雷达</div>
              <div class="app-subtitle">把欧洲 / 德国 / DACH 的行业新闻快速变成可跟进的销售线索、岗位建议和英文外联草稿。</div>
            </div>
            <div class="local-badge">PUBLIC WEB APP · siltherm-news-radar.streamlit.app</div>
          </div>
          <div class="radar-strip">
            <div class="radar-tile tile-mint"><b>7 个重点赛道</b><span>EV、ESS、户储、VPP、AI 数据中心、电力柜、热安全</span></div>
            <div class="radar-tile tile-rose"><b>1-5 分销售相关性</b><span>按区域、行业、项目和热管理信号自动评分</span></div>
            <div class="radar-tile tile-butter"><b>CSV 导出</b><span>可导入飞书多维表格继续跟进</span></div>
          </div>
        </section>
        <section class="steps">
          <div class="step-box"><strong>1. 输入新闻</strong><span>用关键词扫新闻，或粘贴新闻链接 / 正文。</span></div>
          <div class="step-box"><strong>2. 看销售价值</strong><span>重点看评分、分类、公司、国家和项目线索。</span></div>
          <div class="step-box"><strong>3. 拿去外联</strong><span>复制 LinkedIn 话术和邮件草稿，或导出 CSV。</span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    input_col, output_col = st.columns([0.92, 1.08], gap="large")

    with input_col:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">新闻输入</div>', unsafe_allow_html=True)
        st.markdown('<div class="hint-line">新手建议先用“关键词”，例如 BESS thermal safety Germany。</div>', unsafe_allow_html=True)
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
                  这里会显示销售线索卡片。先在左侧输入关键词，点击“分析新闻”，再看 1-5 分评分和外联草稿。
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("Siltherm Radar")
        st.caption("公网网页地址")
        st.code(PUBLIC_APP_URL)
        st.header("重点行业")
        st.write("EV battery packs")
        st.write("BESS containers")
        st.write("Residential energy storage")
        st.write("VPP")
        st.write("AI data center power infrastructure")
        st.write("Electrical cabinets")
        st.write("Battery thermal safety")
        st.header("评分")
        st.write("5 分：强相关，适合马上加入外联列表。")
        st.write("3-4 分：建议人工复核后跟进。")
        st.write("1-2 分：弱相关，作为市场观察。")


if __name__ == "__main__":
    main()
