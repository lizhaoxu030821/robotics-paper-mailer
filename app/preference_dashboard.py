from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.yml"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import send_daily_robotics_paper as mailer  # noqa: E402


st.set_page_config(
    page_title="Paper Preferences",
    page_icon="",
    layout="wide",
)


def read_config() -> dict:
    if not CONFIG_PATH.exists():
        return mailer.default_config()
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or mailer.default_config()


def write_config(config: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)


def normalize_table(rows: list[dict], columns: list[str]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    key_column = columns[0]
    for row in rows:
        value = str(row.get(key_column, "")).strip()
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        item = {column: row.get(column) for column in columns}
        item[key_column] = value
        item["enabled"] = bool(row.get("enabled", True))
        if "weight" in item:
            try:
                item["weight"] = int(item.get("weight", 0))
            except (TypeError, ValueError):
                item["weight"] = 0
        normalized.append(item)
    return normalized


def config_to_text(config: dict) -> str:
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


config = read_config()
paper_preferences = config.setdefault("paper_preferences", {})
obsidian = config.setdefault("obsidian", {})

st.title("Paper Preference Dashboard")
st.caption("Edit arXiv search queries, keyword weights, and Obsidian outbox settings used by the daily mailer.")

with st.sidebar:
    st.subheader("Runtime")
    st.write(f"Config: `{CONFIG_PATH}`")
    st.write(f"Queries: `{len(paper_preferences.get('queries', []))}`")
    st.write(f"Keywords: `{len(paper_preferences.get('keywords', []))}`")
    if st.button("Reload config", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

tab_queries, tab_keywords, tab_scoring, tab_obsidian, tab_preview, tab_raw = st.tabs(
    ["Queries", "Keywords", "Scoring", "Obsidian", "Preview", "Raw YAML"]
)

with tab_queries:
    st.subheader("arXiv queries")
    st.write("Each enabled query is sent to the arXiv API. Keep queries focused to reduce noise and rate-limit risk.")
    query_rows = paper_preferences.get("queries", [])
    queries_df = pd.DataFrame(query_rows or [{"query": "", "enabled": True}])
    edited_queries = st.data_editor(
        queries_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "query": st.column_config.TextColumn("query", width="large"),
            "enabled": st.column_config.CheckboxColumn("enabled"),
        },
        key="queries_editor",
    )

with tab_keywords:
    st.subheader("Keyword weights")
    st.write("A paper gets the configured weight when the keyword appears in its title or abstract.")
    keyword_rows = paper_preferences.get("keywords", [])
    keywords_df = pd.DataFrame(keyword_rows or [{"keyword": "", "weight": 1, "enabled": True}])
    edited_keywords = st.data_editor(
        keywords_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "keyword": st.column_config.TextColumn("keyword", width="medium"),
            "weight": st.column_config.NumberColumn("weight", min_value=-50, max_value=100, step=1),
            "enabled": st.column_config.CheckboxColumn("enabled"),
        },
        key="keywords_editor",
    )

with tab_scoring:
    st.subheader("Scoring controls")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        freshness_bonus_days = st.number_input(
            "Freshness bonus days",
            min_value=0,
            max_value=120,
            value=int(paper_preferences.get("freshness_bonus_days", 30)),
            step=1,
        )
    with col_b:
        min_score = st.number_input(
            "Minimum score",
            min_value=0,
            max_value=300,
            value=int(paper_preferences.get("min_score", 0)),
            step=1,
        )
    with col_c:
        max_attachment_mb = st.number_input(
            "Max PDF attachment MB",
            min_value=0.1,
            max_value=50.0,
            value=float(paper_preferences.get("max_attachment_mb", 18)),
            step=0.5,
        )

    history_limit = st.number_input(
        "History limit",
        min_value=1,
        max_value=5000,
        value=int(paper_preferences.get("history_limit", 500)),
        step=50,
    )

    st.subheader("Category weights")
    category_rows = paper_preferences.get("category_weights", [])
    categories_df = pd.DataFrame(category_rows or [{"category": "cs.RO", "weight": 10, "enabled": True}])
    edited_categories = st.data_editor(
        categories_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "category": st.column_config.TextColumn("category", width="medium"),
            "weight": st.column_config.NumberColumn("weight", min_value=-50, max_value=100, step=1),
            "enabled": st.column_config.CheckboxColumn("enabled"),
        },
        key="categories_editor",
    )

with tab_obsidian:
    st.subheader("Obsidian outbox")
    outbox_root = st.text_input("Outbox root", value=str(obsidian.get("outbox_root", "obsidian-outbox")))
    project_root = st.text_input(
        "Project root",
        value=str(obsidian.get("project_root", "ResearchVault/legged-robot-motion-control")),
    )
    st.write("The daily mailer writes intake notes and Codex deep-read requests under this project outbox.")

next_config = {
    "paper_preferences": {
        "max_attachment_mb": float(max_attachment_mb),
        "history_limit": int(history_limit),
        "freshness_bonus_days": int(freshness_bonus_days),
        "min_score": int(min_score),
        "queries": normalize_table(edited_queries.to_dict("records"), ["query", "enabled"]),
        "keywords": normalize_table(edited_keywords.to_dict("records"), ["keyword", "weight", "enabled"]),
        "category_weights": normalize_table(edited_categories.to_dict("records"), ["category", "weight", "enabled"]),
    },
    "obsidian": {
        "outbox_root": outbox_root.strip() or "obsidian-outbox",
        "project_root": project_root.strip() or "ResearchVault/legged-robot-motion-control",
    },
}

with tab_preview:
    st.subheader("Preview today's ranking")
    max_results = st.slider("Max results per query", min_value=5, max_value=50, value=20, step=5)
    top_n = st.slider("Rows to show", min_value=5, max_value=30, value=10, step=5)
    if st.button("Fetch arXiv candidates", type="primary"):
        try:
            preview_preferences = mailer.preferences_from_raw_config(next_config)
            mailer.apply_preferences(preview_preferences)
            with st.spinner("Querying arXiv and scoring candidates..."):
                ranked = mailer.collect_ranked_papers(max_results=max_results)
            rows = [
                {
                    "score": paper.score,
                    "published": paper.published.strftime("%Y-%m-%d"),
                    "title": paper.title,
                    "categories": ", ".join(paper.categories),
                    "url": paper.url,
                }
                for paper in ranked[:top_n]
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))

with tab_raw:
    st.subheader("Raw config preview")
    st.code(config_to_text(next_config), language="yaml")

st.divider()
left, middle, right = st.columns([1, 1, 2])
with left:
    if st.button("Save config", type="primary", use_container_width=True):
        write_config(next_config)
        st.success("Saved config.yml")
with middle:
    if st.button("Validate", use_container_width=True):
        try:
            mailer.load_preferences(CONFIG_PATH)
            st.success("Config is valid.")
        except Exception as exc:
            st.error(str(exc))
with right:
    st.download_button(
        "Download config.yml",
        data=config_to_text(next_config),
        file_name="config.yml",
        mime="text/yaml",
        use_container_width=True,
    )

with st.expander("JSON snapshot"):
    st.code(json.dumps(next_config, ensure_ascii=False, indent=2), language="json")
