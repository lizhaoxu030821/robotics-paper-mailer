from __future__ import annotations

import email.utils
import hashlib
import html
import json
import mimetypes
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
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, TypeVar


ARXIV_API = "https://export.arxiv.org/api/query"
ZOTERO_API = "https://api.zotero.org"
SMTP_HOST = "smtp.qq.com"
SMTP_SSL_PORT = 465
MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024
HISTORY_PATH = Path("data") / "sent_papers.json"
DEFAULT_OBSIDIAN_OUTBOX_ROOT = Path("obsidian-outbox")
DEFAULT_OBSIDIAN_PROJECT_ROOT = "ResearchVault/legged-robot-motion-control"

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

T = TypeVar("T")


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


def timed_step(label: str, func: Callable[[], T]) -> T:
    start = time.monotonic()
    print(f"[timer] {label} started", flush=True)
    try:
        return func()
    finally:
        elapsed = time.monotonic() - start
        print(f"[timer] {label} finished in {elapsed:.1f}s", flush=True)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def split_author_name(name: str) -> dict[str, str]:
    parts = name.strip().split()
    if len(parts) >= 2:
        return {"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]}
    return {"creatorType": "author", "name": name}


def arxiv_id_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def safe_filename(value: str, suffix: str = ".pdf") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned[:120] or "daily_robotics_paper") + suffix


def safe_markdown_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned[:36] or "daily-robotics-paper"


def yaml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


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
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 1:
                raise
        wait_seconds = 5 * (attempt + 1)
        print(f"arXiv request failed temporarily ({last_error}); retrying in {wait_seconds}s.", file=sys.stderr)
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
    errors: list[str] = []
    for query in QUERIES:
        try:
            raw = arxiv_request(query)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            print(f"Skipping query after repeated arXiv failures: {query}: {exc}", file=sys.stderr)
            continue
        for paper in parse_feed(raw):
            current = papers_by_url.get(paper.url)
            if current is None or paper.score > current.score:
                papers_by_url[paper.url] = paper
        time.sleep(1)
    if not papers_by_url:
        detail = "\n".join(errors) if errors else "No query errors were captured."
        raise RuntimeError(f"No arXiv papers found for the configured robotics queries.\n{detail}")
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
        with urllib.request.urlopen(req, timeout=25) as response:
            target.write_bytes(response.read())
        size = target.stat().st_size
        if 10_000 < size <= MAX_ATTACHMENT_BYTES:
            return target
        return None
    except Exception as exc:
        print(f"PDF download failed: {exc}", file=sys.stderr)
        return None


def zotero_enabled() -> bool:
    return all(
        optional_env(name)
        for name in ("ZOTERO_API_KEY", "ZOTERO_USER_ID", "ZOTERO_COLLECTION_NAME")
    )


def zotero_request(
    method: str,
    path: str,
    *,
    api_key: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, bytes, dict[str, str]]:
    request_headers = {
        "Zotero-API-Version": "3",
        "Zotero-API-Key": api_key,
        "User-Agent": "daily-robotics-paper-mailer/1.0",
    }
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(
        f"{ZOTERO_API}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read(), dict(response.headers)


def zotero_json_request(
    method: str,
    path: str,
    *,
    api_key: str,
    payload: object | None = None,
    timeout: int = 60,
) -> tuple[int, object, dict[str, str]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, raw, response_headers = zotero_request(
        method,
        path,
        api_key=api_key,
        data=data,
        headers=headers,
        timeout=timeout,
    )
    if not raw:
        return status, None, response_headers
    return status, json.loads(raw.decode("utf-8")), response_headers


def zotero_find_collection_key(api_key: str, user_id: str, collection_name: str) -> str:
    params = urllib.parse.urlencode({"q": collection_name, "limit": 100})
    _, collections, _ = zotero_json_request(
        "GET",
        f"/users/{user_id}/collections?{params}",
        api_key=api_key,
    )
    if not isinstance(collections, list):
        raise RuntimeError("Unexpected Zotero collections response.")
    for collection in collections:
        data = collection.get("data", {})
        if data.get("name") == collection_name:
            return data["key"]
    raise RuntimeError(f"Zotero collection not found: {collection_name}")


def zotero_create_item(
    api_key: str,
    user_id: str,
    collection_key: str,
    paper: Paper,
) -> str:
    item = {
        "itemType": "journalArticle",
        "title": paper.title,
        "creators": [split_author_name(author) for author in paper.authors],
        "abstractNote": paper.abstract,
        "date": paper.published.strftime("%Y-%m-%d"),
        "url": paper.url,
        "archive": "arXiv",
        "archiveLocation": arxiv_id_from_url(paper.url),
        "language": "en",
        "collections": [collection_key],
        "tags": [{"tag": category} for category in paper.categories],
    }
    _, response, _ = zotero_json_request(
        "POST",
        f"/users/{user_id}/items",
        api_key=api_key,
        payload=[item],
    )
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected Zotero create item response.")
    successful = response.get("successful", {})
    if not successful:
        raise RuntimeError(f"Zotero item creation failed: {response}")
    first = successful.get("0") or next(iter(successful.values()))
    return first["key"]


def zotero_create_link_attachment(
    api_key: str,
    user_id: str,
    parent_key: str,
    paper: Paper,
) -> str | None:
    if not paper.pdf_url:
        return None
    attachment = {
        "itemType": "attachment",
        "linkMode": "linked_url",
        "title": "arXiv PDF",
        "accessDate": email.utils.format_datetime(datetime.now(timezone.utc)),
        "url": paper.pdf_url,
        "parentItem": parent_key,
        "contentType": "application/pdf",
    }
    _, response, _ = zotero_json_request(
        "POST",
        f"/users/{user_id}/items",
        api_key=api_key,
        payload=[attachment],
    )
    successful = response.get("successful", {}) if isinstance(response, dict) else {}
    if not successful:
        print(f"Zotero linked PDF attachment creation failed: {response}", file=sys.stderr)
        return None
    first = successful.get("0") or next(iter(successful.values()))
    return first["key"]


def zotero_create_imported_attachment(
    api_key: str,
    user_id: str,
    parent_key: str,
    paper: Paper,
    pdf_path: Path,
) -> str:
    filename = safe_filename(arxiv_id_from_url(paper.url))
    content_type = mimetypes.guess_type(filename)[0] or "application/pdf"
    attachment = {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "title": "Full Text PDF",
        "filename": filename,
        "parentItem": parent_key,
        "contentType": content_type,
    }
    _, response, _ = zotero_json_request(
        "POST",
        f"/users/{user_id}/items",
        api_key=api_key,
        payload=[attachment],
    )
    successful = response.get("successful", {}) if isinstance(response, dict) else {}
    if not successful:
        raise RuntimeError(f"Zotero imported attachment creation failed: {response}")
    first = successful.get("0") or next(iter(successful.values()))
    attachment_key = first["key"]
    zotero_upload_attachment_file(api_key, user_id, attachment_key, pdf_path, filename, content_type)
    return attachment_key


def zotero_upload_attachment_file(
    api_key: str,
    user_id: str,
    attachment_key: str,
    pdf_path: Path,
    filename: str,
    content_type: str,
) -> None:
    data = pdf_path.read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    auth_body = urllib.parse.urlencode(
        {
            "md5": md5,
            "filename": filename,
            "filesize": str(len(data)),
            "mtime": str(int(pdf_path.stat().st_mtime * 1000)),
        }
    ).encode("utf-8")
    status, raw, _ = zotero_request(
        "POST",
        f"/users/{user_id}/items/{attachment_key}/file",
        api_key=api_key,
        data=auth_body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "If-None-Match": "*",
        },
    )
    if status == 204:
        return
    upload_info = json.loads(raw.decode("utf-8"))
    if not upload_info.get("exists"):
        upload_url = upload_info["url"]
        upload_body = upload_info["prefix"].encode("utf-8") + data + upload_info["suffix"].encode("utf-8")
        upload_req = urllib.request.Request(
            upload_url,
            data=upload_body,
            headers={"Content-Type": upload_info["contentType"]},
            method="POST",
        )
        with urllib.request.urlopen(upload_req, timeout=45) as response:
            response.read()
    zotero_request(
        "POST",
        f"/users/{user_id}/items/{attachment_key}/file",
        api_key=api_key,
        data=urllib.parse.urlencode({"upload": upload_info["uploadKey"]}).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "If-None-Match": "*",
        },
    )


def sync_to_zotero(paper: Paper, pdf_path: Path | None) -> None:
    if not zotero_enabled():
        print("Zotero sync skipped: missing Zotero secrets.", file=sys.stderr)
        return
    api_key = require_env("ZOTERO_API_KEY")
    user_id = require_env("ZOTERO_USER_ID")
    collection_name = require_env("ZOTERO_COLLECTION_NAME")
    try:
        collection_key = zotero_find_collection_key(api_key, user_id, collection_name)
        item_key = zotero_create_item(api_key, user_id, collection_key, paper)
        if pdf_path is not None:
            try:
                zotero_create_imported_attachment(api_key, user_id, item_key, paper, pdf_path)
            except Exception as exc:
                print(f"Zotero PDF upload failed; falling back to linked PDF: {exc}", file=sys.stderr)
                zotero_create_link_attachment(api_key, user_id, item_key, paper)
        else:
            zotero_create_link_attachment(api_key, user_id, item_key, paper)
        print(f"ZOTERO_SYNCED: {paper.title}")
    except Exception as exc:
        print(f"Zotero sync failed: {exc}", file=sys.stderr)


def obsidian_project_root() -> str:
    return optional_env("OBSIDIAN_PROJECT_ROOT") or DEFAULT_OBSIDIAN_PROJECT_ROOT


def obsidian_outbox_root() -> Path:
    value = optional_env("OBSIDIAN_OUTBOX_ROOT")
    return Path(value) if value else DEFAULT_OBSIDIAN_OUTBOX_ROOT


def obsidian_project_relative(*segments: str) -> str:
    return "/".join([obsidian_project_root().strip("/"), *segments])


def build_obsidian_intake_note(paper: Paper, stamp: str) -> str:
    authors = ", ".join(paper.authors)
    date_text = paper.published.strftime("%Y-%m-%d")
    request_path = obsidian_project_relative(
        "Agent Dashboard",
        "Outbox",
        "Runner",
        "Requests",
        f"{stamp}-zotero-deep-read.md",
    )
    return "\n".join(
        [
            "---",
            "type: zotero-daily-paper",
            f"created: {datetime.now(timezone.utc).isoformat()}",
            "status: outbox",
            f"zotero_key: {yaml_string(arxiv_id_from_url(paper.url))}",
            f"title: {yaml_string(paper.title)}",
            f"authors: {yaml_string(authors)}",
            f"published: {yaml_string(date_text)}",
            'source: "arXiv via robotics-paper-mailer"',
            f"url: {yaml_string(paper.url)}",
            f"pdf_url: {yaml_string(paper.pdf_url)}",
            "---",
            "",
            f"# {paper.title}",
            "",
            "## Abstract",
            "",
            paper.abstract or "No abstract captured from arXiv.",
            "",
            "## Daily Intake",
            "",
            f"- arXiv ID: {arxiv_id_from_url(paper.url)}",
            f"- Authors: {authors or 'Unknown authors'}",
            f"- Date: {date_text}",
            f"- URL: {paper.url}",
            f"- PDF: {paper.pdf_url or 'No PDF URL'}",
            f"- Codex request: [[{request_path}]]",
            f"- Score: {paper.score}",
            f"- Categories: {', '.join(paper.categories)}",
            "",
            "## Next",
            "",
            "- [ ] Import this outbox item from Agent Dashboard Today.",
            "- [ ] Decide whether to run the Codex deep-read request.",
            "- [ ] Review generated notes before promoting them into the indexed knowledge base.",
            "",
        ]
    )


def build_obsidian_codex_request(paper: Paper, stamp: str) -> str:
    authors = ", ".join(paper.authors)
    date_text = paper.published.strftime("%Y-%m-%d")
    intake_path = obsidian_project_relative(
        "Agent Dashboard",
        "Outbox",
        "Zotero Intake",
        f"{stamp}.md",
    )
    prompt = "\n".join(
        [
            f"继续这个库，精读这篇论文：{paper.title}",
            "",
            "请按当前 Vault 根目录的《论文精读工作流.md》执行。",
            "先读根目录四个索引页，再定位 note/ 下相关笔记。",
            "不要把外部知识当作本 Vault 证据；Zotero/arXiv 信息只能作为新文献来源。",
            "先生成主笔记和同名细读子文件夹草稿；必要时提出索引更新建议，但不要直接改已有索引，除非用户确认。",
            "",
            "论文信息：",
            f"- Title: {paper.title}",
            f"- Authors: {authors or 'Unknown authors'}",
            f"- Date: {date_text}",
            f"- arXiv ID: {arxiv_id_from_url(paper.url)}",
            f"- URL: {paper.url}",
            f"- PDF: {paper.pdf_url or 'No PDF URL'}",
            f"- Categories: {', '.join(paper.categories)}",
            "",
            "Abstract:",
            paper.abstract or "No abstract captured from arXiv.",
            "",
            "期望输出：",
            "- 主笔记：基本信息、一句话摘要、精读导航、研究对象、研究方法、研究结论、关键证据、我的判断。",
            "- 细读页：方法拆解、实验与消融、我的解读、摘录与线索。",
            "- 写入位置应与本库现有 note/ 分类一致；如果分类不确定，先写到 Agent Dashboard/Research Tasks 并说明建议分类。",
        ]
    )
    estimated_tokens = max(1, len(prompt) // 4)
    return "\n".join(
        [
            "---",
            "type: agent-dashboard-runner-request",
            f"created: {datetime.now(timezone.utc).isoformat()}",
            "status: outbox",
            "model: codex",
            f"estimated_tokens: {estimated_tokens}",
            "write_policy: confirm-before-existing-files",
            f"zotero_key: {yaml_string(arxiv_id_from_url(paper.url))}",
            f"paper_title: {yaml_string(paper.title)}",
            f"intake_note: {yaml_string(intake_path)}",
            "---",
            "",
            f"# Codex deep read request {stamp}",
            "",
            "## Prompt",
            "",
            "```text",
            prompt,
            "```",
            "",
            "## Runner checklist",
            "",
            "- [ ] Codex has generated the daily deep-read template.",
            "- [ ] User reviewed proposed notes before index promotion.",
            "- [ ] If accepted, paper is discoverable through the project literature index.",
            "",
        ]
    )


def write_text_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def write_obsidian_outbox(paper: Paper) -> None:
    root = obsidian_outbox_root()
    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = f"{date_key}-{arxiv_id_from_url(paper.url)}-{safe_markdown_stem(paper.title)}"
    project_root = obsidian_project_root().strip("/")
    intake_path = (
        root
        / project_root
        / "Agent Dashboard"
        / "Outbox"
        / "Zotero Intake"
        / f"{stamp}.md"
    )
    request_path = (
        root
        / project_root
        / "Agent Dashboard"
        / "Outbox"
        / "Runner"
        / "Requests"
        / f"{stamp}-zotero-deep-read.md"
    )
    wrote_intake = write_text_if_missing(intake_path, build_obsidian_intake_note(paper, stamp))
    wrote_request = write_text_if_missing(request_path, build_obsidian_codex_request(paper, stamp))
    if wrote_intake or wrote_request:
        print(f"OBSIDIAN_OUTBOX_CREATED: {paper.title}")
    else:
        print(f"OBSIDIAN_OUTBOX_EXISTS: {paper.title}")


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
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, context=context, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_code)
        smtp.send_message(msg)


def send_failure_email(error: Exception) -> None:
    try:
        smtp_user = require_env("QQ_SMTP_USER")
        smtp_code = require_env("QQ_SMTP_AUTH_CODE")
        recipient = os.environ.get("MAIL_TO", smtp_user).strip()
    except Exception:
        return

    msg = EmailMessage()
    msg["Subject"] = "每日机器人论文推送失败提醒"
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.set_content(
        "今天的机器人论文自动推送没有完成。\n\n"
        "失败位置：arXiv 论文检索或后续发送流程。\n\n"
        f"错误信息：\n{error}\n\n"
        "这通常是 arXiv API 临时超时、限流或 GitHub runner 网络波动造成的。"
        "脚本已经内置重试；如果连续多天失败，需要检查 arXiv 访问、GitHub Actions 日志和 SMTP 配置。\n",
        charset="utf-8",
    )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, context=context, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_code)
        smtp.send_message(msg)


def main() -> int:
    try:
        sent_urls = timed_step("load sent history", load_sent_urls)
        paper = timed_step("find best arXiv paper", lambda: find_best_paper(sent_urls))
        pdf_path = timed_step("download PDF", lambda: download_pdf(paper.pdf_url))
        timed_step("send email", lambda: send_email(paper, pdf_path))
        timed_step("sync to Zotero", lambda: sync_to_zotero(paper, pdf_path))
        timed_step("write Obsidian outbox", lambda: write_obsidian_outbox(paper))
        timed_step("record sent paper", lambda: record_sent_paper(paper))
        print(f"EMAIL_SENT: {paper.title}")
        return 0
    except Exception as exc:
        send_failure_email(exc)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
