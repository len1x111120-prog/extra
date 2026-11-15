# extra built-in skills

These skills come from public repositories and are used under their licenses. Each folder keeps the original license file.

| Skill | Source | License |
|---|---|---|
| frontend-design | https://github.com/anthropics/skills (skills/frontend-design) | Apache License 2.0 (LICENSE.txt) |
| webapp-testing | https://github.com/anthropics/skills (skills/webapp-testing), Copyright 2026 Anthropic, PBC | Apache License 2.0 (LICENSE.txt) |
| systematic-debugging | https://github.com/obra/superpowers (skills/systematic-debugging), Copyright (c) 2025 Jesse Vincent | MIT (LICENSE) |
| verification-before-completion | https://github.com/obra/superpowers (skills/verification-before-completion), Copyright (c) 2025 Jesse Vincent | MIT (LICENSE) |

Changes made for extra: the texts are shortened for a small local model, parts that do not apply (bundled helper scripts,
references to other skills, commits/PRs) are removed, a `triggers` line is added so extra can pick them automatically,
and webapp-testing explains how to run Playwright on this Mac instead of using the helper script.
