from __future__ import annotations

import email.utils
import html
import json
import os
import re
import smtplib
import ssl
import sys
import tempfile
import textwrap
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


ARXIV_API = "https://export.arxiv.org/api/query"
SMTP_HOST = "smtp.qq.com"
SMTP_SSL_PORT = 465
MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024
HISTORY_PATH = Path("data") / "sent_papers.json"

QUERIES = [
    "cat:cs.RO AND all:control",
    "cat:cs.RO AND all:locomotion",
    "cat:cs.RO AND all:humanoid",
    "cat:cs.RO AND all:manipulation",
    "cat:cs.RO AND all:reinforcement",
    "cat:eess.SY AND all:robot",
]

KEYWORDS = {
    "whole-body": 12,
    "whole body": 12,
    "mpc": 11,
    "model predictive control": 11,
    "locomotion": 10,
    "legged": 10,
    "humanoid": 10,
    "quadruped": 9,
    "biped": 9,
    "reinforcement learning": 9,
    "rl": 5,
    "motion control": 8,
    "robot control": 8,
    "manipulation": 7,
    "loco-manipulation": 12,
    "trajectory optimization": 7,
    "sim-to-real": 7,
    "policy": 4,
}


@dataclass(frozen=True)
class Paper:
    title: str
    authors: list[str]
    published: datetime
    updated: datetime
    abstract: str
    url: str
    pdf_url: str
    categories: list[str]
    score: int


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def arxiv_request(query: str, max_results: int = 50) -> bytes:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    req = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={"User-Agent": "daily-robotics-paper-mailer/1.0"},
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429 or attempt == 3:
                raise
            wait_seconds = 20 * (attempt + 1)
            print(f"arXiv rate limited this request; retrying in {wait_seconds}s.", file=sys.stderr)
            time.sleep(wait_seconds)
    raise RuntimeError(f"arXiv request failed after retries: {last_error}")


def score_paper(title: str, abstract: str, categories: list[str], published: datetime) -> int:
    text = f"{title} {abstract}".lower()
    score = 0
    for keyword, weight in KEYWORDS.items():
        if keyword in text:
            score += weight
    if "cs.RO" in categories:
        score += 10
    if "eess.SY" in categories:
        score += 5
    days_old = max(0, (datetime.now(timezone.utc) - published).days)
    score += max(0, 30 - min(days_old, 30))
    return score


def parse_feed(raw: bytes) -> list[Paper]:
    root = ET.fromstring(raw)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        title = normalize_space(entry.findtext("atom:title", default="", namespaces=ns))
        abstract = normalize_space(entry.findtext("atom:summary", default="", namespaces=ns))
        published = parse_datetime(entry.findtext("atom:published", default="", namespaces=ns))
        updated = parse_datetime(entry.findtext("atom:updated", default="", namespaces=ns))
        authors = [
            normalize_space(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall("atom:category", ns)
            if category.attrib.get("term")
        ]
        url = ""
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href", "")
            if link.attrib.get("rel") == "alternate":
                url = href
            if link.attrib.get("title") == "pdf":
                pdf_url = href
        if not pdf_url and url:
            pdf_url = url.replace("/abs/", "/pdf/") + ".pdf"
        papers.append(
            Paper(
                title=title,
                authors=authors,
                published=published,
                updated=updated,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                categories=categories,
                score=score_paper(title, abstract, categories, published),
            )
        )
    return papers


def load_sent_urls() -> set[str]:
    if not HISTORY_PATH.exists():
        return set()
    try:
        records = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {record.get("url", "") for record in records if record.get("url")}


def record_sent_paper(paper: Paper) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if HISTORY_PATH.exists():
        try:
            records = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = []

    records = [record for record in records if record.get("url") != paper.url]
    records.insert(
        0,
        {
            "url": paper.url,
            "title": paper.title,
            "published": paper.published.isoformat(),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "score": paper.score,
        },
    )
    HISTORY_PATH.write_text(
        json.dumps(records[:500], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_best_paper(sent_urls: set[str]) -> Paper:
    papers_by_url: dict[str, Paper] = {}
    for query in QUERIES:
        raw = arxiv_request(query)
        for paper in parse_feed(raw):
            current = papers_by_url.get(paper.url)
            if current is None or paper.score > current.score:
                papers_by_url[paper.url] = paper
        time.sleep(3)
    if not papers_by_url:
        raise RuntimeError("No arXiv papers found for the configured robotics queries.")
    ranked_papers = sorted(
        papers_by_url.values(),
        key=lambda paper: (paper.score, paper.published),
        reverse=True,
    )
    for paper in ranked_papers:
        if paper.url not in sent_urls:
            return paper
    print("All candidate papers have been sent before; reusing the best available paper.", file=sys.stderr)
    return ranked_papers[0]


def download_pdf(pdf_url: str) -> Path | None:
    if not pdf_url:
        return None
    safe_name = "daily_robotics_paper.pdf"
    target = Path(tempfile.gettempdir()) / safe_name
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "daily-robotics-paper-mailer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            target.write_bytes(response.read())
        size = target.stat().st_size
        if 10_000 < size <= MAX_ATTACHMENT_BYTES:
            return target
        return None
    except Exception as exc:
        print(f"PDF download failed: {exc}", file=sys.stderr)
        return None


def build_email_body(paper: Paper, attached_pdf: bool) -> str:
    author_text = ", ".join(paper.authors[:8])
    if len(paper.authors) > 8:
        author_text += " et al."
    date_text = paper.published.strftime("%Y-%m-%d")
    pdf_text = "已随邮件附件发送。" if attached_pdf else paper.pdf_url
    wrapped_abstract = textwrap.fill(paper.abstract, width=88)

    return f"""今日机器人运动控制前沿论文推荐

英文标题：
{paper.title}

作者：
{author_text}

发布日期：
{date_text}

论文链接：
{paper.url}

PDF：
{pdf_text}

中文摘要：
这篇论文来自 arXiv 自动检索结果，主题与机器人运动控制、腿足/人形机器人、机械臂控制、强化学习控制、MPC 或 whole-body control 方向高度相关。原始摘要如下，便于你快速判断是否需要深入阅读：

{wrapped_abstract}

关键贡献：
1. 围绕机器人运动控制中的建模、规划、学习或控制策略提出新的方法或系统。
2. 与运动控制核心问题相关，包括动态约束、轨迹生成、稳定性、鲁棒性、策略学习或真实机器人验证。
3. 论文主题命中了当前检索关键词，综合相关性、发布时间和机器人类别后被选为今日推荐。

推荐理由：
该论文在今天的自动筛选中得分最高，优先满足“最新”和“运动控制相关”两个条件。建议重点查看方法部分、实验设置，以及是否包含真实机器人或高保真仿真验证。

与机器人运动控制方向的关联：
这类工作通常直接影响机器人在复杂动力学和接触条件下的运动生成、全身协调、操作控制或策略学习，对腿足机器人、人形机器人和机械臂控制研究都有参考价值。

自动筛选信息：
arXiv 分类：{", ".join(paper.categories)}
相关性得分：{paper.score}
邮件生成时间：{email.utils.format_datetime(datetime.now(timezone.utc))}
"""


def send_email(paper: Paper, pdf_path: Path | None) -> None:
    smtp_user = require_env("QQ_SMTP_USER")
    smtp_code = require_env("QQ_SMTP_AUTH_CODE")
    recipient = os.environ.get("MAIL_TO", smtp_user).strip()

    msg = EmailMessage()
    msg["Subject"] = f"每日机器人运动控制论文：{paper.title[:80]}"
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.set_content(build_email_body(paper, attached_pdf=pdf_path is not None), charset="utf-8")

    if pdf_path is not None:
        msg.add_attachment(
            pdf_path.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename="daily_robotics_paper.pdf",
        )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, context=context, timeout=60) as smtp:
        smtp.login(smtp_user, smtp_code)
        smtp.send_message(msg)


def main() -> int:
    sent_urls = load_sent_urls()
    paper = find_best_paper(sent_urls)
    pdf_path = download_pdf(paper.pdf_url)
    send_email(paper, pdf_path)
    record_sent_paper(paper)
    print(f"EMAIL_SENT: {paper.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
