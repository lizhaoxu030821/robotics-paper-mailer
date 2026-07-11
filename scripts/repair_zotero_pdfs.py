from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ZOTERO_DIR = Path.home() / "Zotero"
DEFAULT_COLLECTION_ID = 9
USER_AGENT = "zotero-pdf-repair/1.0"


@dataclass(frozen=True)
class MissingPdf:
    parent_item_id: int
    parent_key: str
    attachment_item_id: int
    attachment_key: str
    title: str
    arxiv_id: str
    target_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan a local Zotero collection for missing imported PDF files and optionally redownload them from arXiv."
    )
    parser.add_argument("--zotero-dir", type=Path, default=DEFAULT_ZOTERO_DIR)
    parser.add_argument("--collection-id", type=int, default=DEFAULT_COLLECTION_ID)
    parser.add_argument("--apply", action="store_true", help="Actually download missing PDFs. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum PDFs to repair. 0 means no limit.")
    return parser.parse_args()


def connect_readonly(database: Path) -> sqlite3.Connection:
    if not database.exists():
        raise FileNotFoundError(f"Zotero database not found: {database}")
    return sqlite3.connect(f"file:{database}?mode=ro", uri=True)


def field_map(conn: sqlite3.Connection) -> dict[str, int]:
    return {name: field_id for field_id, name in conn.execute("SELECT fieldID, fieldName FROM fields")}


def item_fields(conn: sqlite3.Connection, item_id: int, fields: dict[str, int]) -> dict[str, str]:
    interesting = {name: fields[name] for name in ("title", "url", "archiveLocation", "DOI") if name in fields}
    if not interesting:
        return {}
    placeholders = ",".join("?" for _ in interesting)
    rows = conn.execute(
        f"""
        SELECT f.fieldName, v.value
        FROM itemData d
        JOIN fields f ON f.fieldID = d.fieldID
        JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE d.itemID = ? AND d.fieldID IN ({placeholders})
        """,
        [item_id, *interesting.values()],
    )
    return {name: str(value or "") for name, value in rows}


def canonical_arxiv_id(value: str) -> str:
    value = value.strip()
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", value)
    if match:
        return match.group(1)
    old_style = re.search(r"([a-z.-]+/\d{7})(?:v\d+)?", value, re.IGNORECASE)
    return old_style.group(1) if old_style else ""


def arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def storage_target(zotero_dir: Path, attachment_key: str, attachment_path: str) -> Path | None:
    if not attachment_path.startswith("storage:"):
        return None
    filename = attachment_path.split(":", 1)[1].strip()
    if not filename:
        return None
    return zotero_dir / "storage" / attachment_key / filename


def find_missing_pdfs(conn: sqlite3.Connection, zotero_dir: Path, collection_id: int) -> list[MissingPdf]:
    fields = field_map(conn)
    rows = conn.execute(
        """
        SELECT
            parent.itemID,
            parent.key,
            attachment.itemID,
            attachment.key,
            itemAttachments.path
        FROM collectionItems
        JOIN items parent ON parent.itemID = collectionItems.itemID
        JOIN itemAttachments ON itemAttachments.parentItemID = parent.itemID
        JOIN items attachment ON attachment.itemID = itemAttachments.itemID
        WHERE collectionItems.collectionID = ?
          AND itemAttachments.contentType = 'application/pdf'
          AND itemAttachments.path LIKE 'storage:%'
        ORDER BY parent.dateAdded DESC
        """,
        (collection_id,),
    )
    missing: list[MissingPdf] = []
    for parent_id, parent_key, attachment_id, attachment_key, attachment_path in rows:
        target = storage_target(zotero_dir, str(attachment_key), str(attachment_path or ""))
        if target is None or target.exists():
            continue
        metadata = item_fields(conn, int(parent_id), fields)
        arxiv_id = canonical_arxiv_id(
            " ".join(
                [
                    metadata.get("archiveLocation", ""),
                    metadata.get("url", ""),
                    metadata.get("DOI", ""),
                    metadata.get("title", ""),
                ]
            )
        )
        if not arxiv_id:
            continue
        missing.append(
            MissingPdf(
                parent_item_id=int(parent_id),
                parent_key=str(parent_key),
                attachment_item_id=int(attachment_id),
                attachment_key=str(attachment_key),
                title=metadata.get("title", str(parent_key)),
                arxiv_id=arxiv_id,
                target_path=target,
            )
        )
    return missing


def download_pdf(arxiv_id: str, target: Path) -> None:
    request = urllib.request.Request(arxiv_pdf_url(arxiv_id), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
    if len(data) < 10_000 or not data.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded file does not look like a PDF for {arxiv_id}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main() -> int:
    args = parse_args()
    database = args.zotero_dir / "zotero.sqlite"
    conn = connect_readonly(database)
    try:
        missing = find_missing_pdfs(conn, args.zotero_dir, args.collection_id)
    finally:
        conn.close()

    print(f"collection_id={args.collection_id}")
    print(f"missing_pdf_attachments={len(missing)}")
    if not missing:
        return 0

    selected = missing[: args.limit] if args.limit > 0 else missing
    for item in selected:
        print(f"- {item.arxiv_id} | {item.title} | {item.target_path}")
        if args.apply:
            try:
                download_pdf(item.arxiv_id, item.target_path)
                print(f"  repaired: {item.target_path}")
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                print(f"  failed: {exc}", file=sys.stderr)

    if not args.apply:
        print("dry_run=true; rerun with --apply to download missing PDFs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
