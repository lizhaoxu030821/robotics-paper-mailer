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
  - query: cat:cs.RO AND all:control
    enabled: true
  - query: cat:cs.RO AND all:locomotion
    enabled: true
  - query: cat:cs.RO AND all:humanoid
    enabled: true
  - query: cat:cs.RO AND all:manipulation
    enabled: true
  - query: cat:cs.RO AND all:reinforcement
    enabled: true
  - query: cat:eess.SY AND all:robot
    enabled: true
  keywords:
  - keyword: whole-body
    weight: 12
    enabled: true
  - keyword: whole body
    weight: 12
    enabled: true
  - keyword: mpc
    weight: 11
    enabled: true
  - keyword: model predictive control
    weight: 11
    enabled: true
  - keyword: locomotion
    weight: 10
    enabled: true
  - keyword: legged
    weight: 10
    enabled: true
  - keyword: humanoid
    weight: 10
    enabled: true
  - keyword: quadruped
    weight: 9
    enabled: true
  - keyword: biped
    weight: 9
    enabled: true
  - keyword: reinforcement learning
    weight: 9
    enabled: true
  - keyword: rl
    weight: 5
    enabled: true
  - keyword: motion control
    weight: 8
    enabled: true
  - keyword: robot control
    weight: 8
    enabled: true
  - keyword: manipulation
    weight: 7
    enabled: true
  - keyword: loco-manipulation
    weight: 12
    enabled: true
  - keyword: trajectory optimization
    weight: 7
    enabled: true
  - keyword: sim-to-real
    weight: 7
    enabled: true
  - keyword: policy
    weight: 4
    enabled: true
  category_weights:
  - category: cs.RO
    weight: 10
    enabled: true
  - category: eess.SY
    weight: 5
    enabled: true
obsidian:
  outbox_root: obsidian-outbox
  project_root: ResearchVault/legged-robot-motion-control
```

## Editing Notes

- `queries` controls which arXiv searches run.
- `keywords` controls title/abstract scoring.
- Higher `weight` means stronger preference.
- Disable an item with `enabled: false` instead of deleting it when testing.
- Keep this note committed or synced before the next scheduled run.
