---
type: paper-mailer-preferences
status: active
owner: robotics-paper-mailer
---

# Paper Preferences

Edit only the YAML block below. The daily GitHub Action reads this block before sending papers.

```paper-mailer-config
paper_preferences:
  max_attachment_mb: 18
  history_limit: 500
  freshness_bonus_days: 30
  min_score: 0
  queries:
    - query: "cat:cs.RO AND all:control"
      enabled: true
  keywords:
    - keyword: "whole-body"
      weight: 1
      enabled: true
  category_weights:
    - category: "cs.RO"
      weight: 1
      enabled: true

obsidian:
  outbox_root: "obsidian-outbox"
  project_root: "ResearchVault/legged-robot-motion-control"
```

## Editing Notes

- `queries` controls which arXiv searches run.
- `keywords` controls title/abstract scoring.
- Higher `weight` means stronger preference.
- Disable an item with `enabled: false` instead of deleting it when testing.
- Keep this note committed or synced before the next scheduled run.
