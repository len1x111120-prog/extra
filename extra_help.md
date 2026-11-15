# extra — complete reference (what extra is and everything it can do)

## What extra is
- extra is a local coding agent that runs in the terminal on the user's own Mac. The model runs on this computer through Ollama
  (model: extra-beta, built on Ministral 3 8B). There is no usage limit and no cloud account.
- Main use: when the user's main AI assistant (for example Claude) hits its usage limit, extra takes over ONE task and keeps
  working on it for a long time until it is done and verified. It is not a chatbot that answers once.
- It is slower than a large model, but thorough: before each step it plans, and after each result it verifies by running the code and reading the real output,
  finds out why something failed and tries other ways. Measured: on 292 coding problems (MBPP+ and HumanEval+), the same 8B
  model went from 72.3% to 79.1% with extra's method (p = 0.0055).

## Starting extra (shell commands)
- `extra` — start extra. It loads the model (with a progress bar), then asks by number: 1 continue a task, 2 work in a folder.
- `extra <folder>` — start in that folder (it is created if missing). On start extra shows what is in the folder
  (file count, top-level names, README first line, git changes, a handoff note if there is one) and waits for you.
- `extra "task"` — do one task and exit.
- `extra continue` — shows your recent Claude Code sessions (title, folder, time, last request) with numbers. Pick one with its
  letter or number (Enter = the newest handoff note, q = cancel); extra moves to that folder and continues that task. Handoff notes Claude left are listed first (a, b, c). You can add words: `extra continue fix the tests too`.
- `extra help` — show the command list.

## Commands inside extra (type them in the box at the bottom)
- `/help` — command list. `/help <question>` — ask extra anything about itself (answered directly, without the thinking step).
- `/continue` — same as `extra continue`, from inside extra.
- `/new` — start a new task (forget the current conversation).
- `/set` — the settings menu: pick by number. 1 Language (which language extra answers in), 2 Permissions, 3 Thinking (effort, verify),
  4 Skills (see the built-in skills), 5 Your instructions, 6 Speed settings. 0 goes back. (Short forms still work: `/set <installs|downloads|writes|commands|dangerous|all> <always|ask>`.)
  `/set effort <low|medium|high>` — how much it thinks. `/set verify <on|off>` — whether it verifies each result by running it.
- `/prompt` — show your own instructions. `/prompt add <text>` (add `--global` for every project), `/prompt edit`, `/prompt clear`.
- `/exit` — quit. `Ctrl-C` — stop what it is doing right now. `Ctrl-U` — clear the input line.

## The input box at the bottom
- The bottom of the screen is always an input box, even while extra works.
- While extra is working: what you type goes to extra and it reads it at its next step (change the plan, add something, or tell it to stop).
- When extra asks for permission: what you type is the answer (y = yes, a = always, n = no).
- When a command is running and asks something (like `Proceed? [y/N]`): what you type goes to that command.

## What you see on screen
- Thinking is shown while extra writes it, then it folds into a numbered step with its Plan and Act lines. Folded steps cannot be opened again.
- Each tool call is shown, with the first 12 lines of command output and the first 4 lines of tool results.
- When it writes a file, you see the lines being written in a small window, then a summary like: index.html · 40 lines +40 −0. Open the file to see all of it.
- While it prepares a tool call you see a spinner: working on the next action… 12s.

## How it thinks (effort and verify)
- Each step: a thinking step in English (shown in full, labels colored), then a real action with a tool.
- effort low: Plan → Act. medium: Plan → Options → Act. high (default): Plan → Options → Expect (predict what each option will do) → Act.
- verify on (default): verifying means running, not reading. After each tool result it writes Result (what the real output showed) / Failed / Alternatives (at least three other ways) / next step,
  and after changing code it runs the code or its tests before it says it is done. Shown in orange "Verifying…", then a green ✓.
- It never says something is impossible before trying several real alternatives.

## Tools it uses
read_file, list_dir, find_files, search_text (reading and searching); write_file, edit_file (shows a colored diff);
run_command (output streams live; 15-minute limit per command); web_search, web_fetch; download_file (shows the size first).
It can also save code from a code block (a line `FILE: path` and a code block; for Python, a block with only some functions replaces just those).
It installs what it needs itself (pip in a .venv, npm, brew, git clone) and prefers tools it can drive fully from the terminal
(for games: a web page with Three.js, not editors like Godot or Unity unless you ask).

## Permissions and safety
- Settings are saved in ~/.extra/settings.json. Defaults: installs always; downloads, writes, commands, dangerous: ask.
- It never writes outside the project folder and does not open secret files (.env, keys).
- Deleting the whole computer or home folder (rm of /, ~, /Users/<name>, /System, /Applications, /Library) is always refused, even if dangerous is set to always.

## Working together with Claude
- Claude can hand a self-contained problem to extra in the background and keep working (Claude never waits):
  `extra run "task" --test "check command" --files a.py,b.py --minutes 30 --prompt "extra instructions"`.
- extra solves it alone in a private copy of the project (~/.extra/jobs/<project>/<id>/), runs the test itself, and keeps fixing until it passes or time runs out.
- `extra jobs` — list jobs (jobs from Claude have an orange "✻ Claude" mark; green = passed, red = failed or stopped).
- `extra show <id>` — result, what it tried, and the diff. `extra apply <id>` — copy the changes into the project
  (merges with edits made meanwhile; if they overlap, nothing is changed and the files are listed).
  `extra run --job <id> --feedback "why"` — send it back with the reason.
- On start, extra lists the jobs Claude handed it in this folder.
- Claude Code skills (in ~/.claude/skills): extra-handoff (Claude keeps .extra/handoff.md so extra can continue after a limit)
  and extra-delegate (how Claude hands work to extra and reviews it).

## Your own instructions
- `/prompt add ...` puts your instructions after extra's core rules. They change style and conventions, but never switch off the
  core rules (act through tools, think before acting, run and verify, stay in the project, be safe and honest). Lines that conflict
  with a core rule are shown with a warning.

## Logs
- What happens in the terminal is logged in ~/.extra/cli_log.jsonl (only on your Mac; nothing is sent anywhere) (for fixing problems).

## FAQ (exact answers — copy these commands exactly)
- How do I change the plan or add something while extra is working? → Just type it in the bottom box and press Enter. There is no special syntax. extra reads it at its next step and adjusts. To stop now, press Ctrl-C.
- How do I allow dangerous commands? → Inside extra type: /set dangerous always   (or /set all always for everything). Only wiping the whole computer or home folder stays blocked; normal rm inside the project is allowed.
- How do I make extra stop asking for permission? → /set all always   (back to asking: /set all ask)
- How do I make extra faster? → /set effort low   and, if you want, /set verify off
- How do I work together with Claude? → Install the extra-delegate skill in Claude Code (~/.claude/skills/extra-delegate/SKILL.md). Then Claude runs `extra run "task" --test "command"` in the background by itself, reviews with `extra show <id>`, and uses it with `extra apply <id>` or sends it back with `extra run --job <id> --feedback "why"`. You can watch the jobs with `extra jobs`.
- How do I continue after Claude hits its limit? → In the terminal: extra continue  → pick the session number. (Inside extra: /continue.) If Claude used the extra-handoff skill, extra reads .extra/handoff.md first.
- How do I give extra my own rules? → /prompt add <your rule>   (for every project: /prompt add --global <rule>). See them with /prompt.
- How do I start a new task? → /new
- How do I quit? → /exit
- Where is extra working? → In the folder you started it in (shown at the top). Start somewhere else with: extra <folder>
- What can you get from the internet? → Three things: (1) search the web (web_search) and read web pages (web_fetch); (2) download files into the project (download_file, it shows the size and asks first unless /set downloads always); (3) install packages and tools itself: pip into a .venv, npm, brew, git clone (allowed by default).
- What can you do? → Take over one coding task and work on it until it is done: read and search the project, write and edit files, run commands and tests, search the web, download and install what it needs, and keep trying other ways when something fails. It can also take jobs from Claude in the background.
- Is my code sent anywhere? → No. The model runs on your own Mac. Only web searches, web pages and downloads you allow go to the internet.
- Why is extra slow? → It is a small local model and it thinks before every step and verifies every result by running it. For speed: /set effort low and /set verify off.
- Does it work on Windows or Linux? → Not yet. extra runs on macOS (16 GB of memory or more). Windows and Linux are planned.
- What can /set change? → Only these: installs, downloads, writes, commands, dangerous, all (each always or ask), effort (low, medium, high), verify (on, off). Web search and web pages need no setting.
- Can I see the full thinking again after it folds? → No. You can read it while extra writes it; after that only the Plan and Act lines stay.

## Install, update, uninstall
- Version: `extra --version` (this is the beta, 0.1.0-beta).
- Update: download the new package and run `bash install.sh` again; your settings stay.
- Uninstall: `bash uninstall.sh` in the package folder. It removes the program and the command, and asks before removing
  your settings (~/.extra) and the model.
- Files: the program is in ~/.extra/app, its Python packages in ~/.extra/venv, settings in ~/.extra/settings.json.

## First start
- The very first time extra opens, it asks five things once: language, thinking effort, verify on/off, permissions
  (ask me first / everyday work / everything) and the speed settings. Press Enter for the default. Change them later with /set.

## Skills
- A skill is a short instruction file for one kind of work. extra has four built-in skills and uses the matching ones by itself
  when your request matches (up to 2). They come from public repositories, used under their licenses:
  - frontend-design — distinctive, intentional visual design (from anthropics/skills, Apache 2.0)
  - webapp-testing — test web apps for real with Playwright in headless Chrome (from anthropics/skills, Apache 2.0)
  - systematic-debugging — find the root cause before fixing (from obra/superpowers, MIT)
  - verification-before-completion — run the check and read its output before saying it is done (from obra/superpowers, MIT)
- See them: /set → 4 Skills, or /skills. Use one for your next request: /skill <name>. Adding your own skills is not available.

## Speed settings
- On first start, if two Ollama settings are off (flash attention, a smaller memory cache), extra asks once whether to turn them on.
  Answers stay the same; writing was about 32% faster on our Mac. Yes = they are turned on, kept after restarts, and Ollama restarts once.
  No = you are not asked again. Later: `/set speedup on`.
