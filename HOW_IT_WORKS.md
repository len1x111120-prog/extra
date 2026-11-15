# How extra works

extra runs a small local model (Ollama's Ministral 3 8B) as a terminal coding agent. A small model is slow and makes more
mistakes than a frontier model, so extra is built around one idea: **make up for a small brain with patience and real
feedback.** Plan, actually run the code, read the real result, and try another way when something fails — for as long as the
task needs. This file explains the approach; the code is all here to read.

## The loop

Each step is two turns:

1. **Think / verify** (no tools). The model writes a short plan in one of three depths:
   - low: `Problem → Plan → Act`
   - medium: adds `Options` (two or three ways to do the next step)
   - high: adds `Expect` (predict the result of each option before choosing)
   After an action it writes a **verification** turn: `Result` (what actually happened), `Failed` (what and why), and, if it
   failed, `Alternatives` (at least three other ways, each with a prediction) before picking one.
2. **Act** (tools). The model calls exactly one tool: `read_file`, `write_file`, `edit_file`, `run_command`, `web_search`,
   `web_fetch`, `download_file`, or `use_skill`.

Only the `Plan` and `Act` lines are fed back into the next turn (not the whole thought), so a long task does not drown in its
own reasoning.

## Verification is running, not reading

"Verify" means executing. extra does not claim something works because the code looks right — it runs the code or its tests
with `run_command`, reads the output and the exit code, and only then decides. If you give it a check script, it runs that and
never edits it.

## Guardrails for a small model

Most of extra's value is a set of small corrections that keep an 8B model on track. They are the result of watching where it
goes wrong, one failure at a time:

- **Code written as text becomes a real file.** If the model pastes code or writes `FILE: name` instead of calling
  `write_file`, extra saves it. A guessed filename never overwrites an existing file.
- **"I will now…" with no tool call is caught** and the model is asked to actually make the call.
- **Finished-but-not-run is caught.** It cannot end a task while the check is failing; it must say so honestly.
- **Repeated commands are blocked.** The same call a third time gets a note; a fourth is refused.
- **Test files are protected.** It cannot edit a task's tests to make them pass — it must fix the code.
- **The task stays in view.** On long tasks the original request is pinned so it is not forgotten when old turns scroll off.
- **Errors point to the cause.** A failing command's error is traced to the source line plus its enclosing function and the
  helper definitions around it.
- **Don't give up.** "It can't be done" is detected and the model is pushed to find another way (e.g. a free, no-key API).
- **Servers run in the background** and are stopped when extra exits, so a dev server never freezes the session.

## Continue a Claude Code task

When Claude Code hits its usage limit, it can leave a short note in `.extra/handoff.md` (goal, done, next, how to test). Run
`extra continue` in the same folder and extra picks the task up from there. Claude can also hand a self-contained piece of work
to extra in the background with `extra run "task" --test "command"`; extra works in a copy, and `extra apply <id>` merges the
result back.

## Skills

Four built-in skills (design, browser testing, systematic debugging, verify-before-done) are short instruction files adapted
from open-source skills. extra attaches the matching ones automatically based on your request. See `THIRD_PARTY_NOTICES.md`.

## What is NOT in the beta

The beta uses the base Ministral 3 8B model unchanged — everything above is in the harness (this code), not the weights. The
planned full version trains a LoRA on top of the model so the behaviour above comes from the model itself, not only from the
prompts and guardrails here.

## Privacy and safety

The model runs on your Mac; your code and chats are not sent anywhere. The only outside requests are the ones a task needs
(web search via DuckDuckGo then Wikipedia, pages and downloads it opens, package installs). Secrets like `.env` are never read,
and extra never writes outside the project folder or wipes your home folder. A local-only log is kept in `~/.extra/`.

---
extra was designed and built by Jeon Seol together with Claude (Anthropic).
