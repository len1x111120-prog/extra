# extra (beta)

*Built by Jeon Seol together with Claude (Anthropic).*

extra is a coding agent that runs in your terminal on a **local model** — no account, no API key, no usage limit.
It is slow next to a frontier model, so it is built to make up for that with patience: it plans, runs the code, reads the real
result and tries another way when something fails, for as long as the task needs. It can also **continue a task Claude Code
started** when you hit your usage limit, or take a piece of work from Claude in the background.

> Beta: free while it is in beta. It has been tested on a small number of tasks; expect rough edges and please send feedback.

## Requirements
- A Mac (Apple Silicon recommended), macOS 13 or newer, 16 GB memory recommended, about 10 GB free disk
- [Ollama](https://ollama.com/download) — runs the model on your Mac
- Python 3.9 or newer (comes with the Xcode command line tools: `xcode-select --install`)

## Install
```bash
tar -xzf extra-0.1.0-beta.tar.gz
cd extra-0.1.0-beta
bash install.sh
```
The installer checks your Mac, downloads the model once (Ollama's `ministral-3:8b`, about 6 GB) and creates `extra-beta`
from it, installs the program into `~/.extra`, and adds the `extra` command. Run it again to update.

## Start
```bash
cd ~/my-project
extra
```
The first start asks five things once — language, how carefully to think, whether to verify each step, what extra may do
without asking, and whether to turn on Ollama's speed settings. Change them later with `/set`.

| Command | What it does |
|---|---|
| `extra` | start in the current folder |
| `extra <folder>` | start in that folder |
| `extra "task"` | do one task and exit |
| `extra continue` | pick up a task from your Claude Code sessions or a handoff note |
| `/set` (inside extra) | settings menu — pick by number |
| `/help <question>` | ask extra about itself |
| `/exit` | quit |

You can type in the box at the bottom even while extra works; it reads your message at its next step.

## Working with Claude Code
- **When you hit your limit:** keep a short handoff note in `.extra/handoff.md` (Claude can write it for you), then run
  `extra continue` in the same folder.
- **Background jobs:** Claude can hand a self-contained piece of work to extra with a test command:
  `extra run "task" --test "command"`. Check results with `extra jobs`, `extra show <id>`, `extra apply <id>`.

## Privacy
The model runs on your Mac. Your code and conversations are not sent anywhere. The only outside requests are the ones the task
needs: web searches (DuckDuckGo, then Wikipedia), web pages and downloads extra opens, and package installs. A log of what
happened in the terminal is kept only on your Mac in `~/.extra/cli_log.jsonl`.

## Safety
extra asks before risky commands depending on your permission setting, never deletes or wipes your home folder, never changes a
task's test files to make them pass, and stops background servers it started when it exits.

## Uninstall
```bash
bash uninstall.sh
```
It removes the program and the command, and asks before removing your settings and the model.

## License
MIT — free to use, change and share, keep the copyright notice (see `LICENSE`). extra is open source so you can see exactly
what it does with your code. The built-in skills keep their own open-source licenses (`THIRD_PARTY_NOTICES.md`).
How it works: see `HOW_IT_WORKS.md`.

## Credits
Made by Jeon Seol, with Claude (Anthropic).
