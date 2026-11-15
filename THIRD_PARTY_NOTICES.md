# Third-party notices

## Built-in skills (in `skills/`)
Each skill folder keeps its original license file. The texts were shortened and adapted for extra (see the `source:` line
at the top of each SKILL.md for what changed).

| Skill | From | License |
|---|---|---|
| frontend-design | https://github.com/anthropics/skills — skills/frontend-design | Apache License 2.0 (`skills/frontend-design/LICENSE.txt`) |
| webapp-testing | https://github.com/anthropics/skills — skills/webapp-testing. Copyright 2026 Anthropic, PBC | Apache License 2.0 (`skills/webapp-testing/LICENSE.txt`) |
| systematic-debugging | https://github.com/obra/superpowers — skills/systematic-debugging. Copyright (c) 2025 Jesse Vincent | MIT (`skills/systematic-debugging/LICENSE`) |
| verification-before-completion | https://github.com/obra/superpowers — skills/verification-before-completion. Copyright (c) 2025 Jesse Vincent | MIT (`skills/verification-before-completion/LICENSE`) |

## Model
extra uses Mistral AI's Ministral 3 8B as packaged by Ollama (`ministral-3:8b`). The installer downloads it from Ollama's
library; it is not included in this package. See https://ollama.com/library/ministral-3 for its license.

## Python packages (installed by install.sh, not included)
- Pygments — BSD-2-Clause — https://pygments.org
- Playwright for Python — Apache License 2.0 — https://github.com/microsoft/playwright-python
