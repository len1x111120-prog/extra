"""extra — terminal (사용자 11/14: 터미널도 구성해줘. claude code 처럼).
지금 있는 폴더(프로젝트)에서 일한다. 로컬 모델, 생각 방식(Plan / Expect / Act → 실행 → Result / Alternatives), 같은 안전장치.
 - 읽기·찾기는 바로 한다. 파일을 쓰거나 고치기, 읽기 전용이 아닌 명령은 매번 물어본다 (y = 이번만, a = 이번 세션 내내, n = 하지 않음).
 - 이 폴더 밖에는 쓰지 못한다. 비밀 파일(.env, 키 등)은 읽지 않는다.
쓰기:
  extra                 대화형 (질문하거나 일을 맡긴다)
  extra "할 일"          한 번만 하고 끝
  extra <폴더>          그 폴더에서 시작
  extra continue        Claude Code 세션 목록에서 번호로 골라 이어서 하기
  extra run "할 일" --test "명령"   Claude 가 넘긴 문제를 복사본에서 혼자 끝까지 (공동 작업, extra_jobs.py)
  extra jobs / show ID / apply ID   넘겨받은 일 목록 / 결과와 바뀐 내용 / 프로젝트에 적용
  extra prompt [add|clear|edit] [--global]   내 지시 (기본 규칙보다 아래에 붙는다)
  안에서: /continue, /prompt, /set, /new 새 대화, /exit 끝, Ctrl-C 지금 하던 것 멈추기"""
import difflib, fnmatch, json, os, re, readline, shlex, shutil, subprocess, sys, time, urllib.request  # noqa: F401 (readline: 입력 줄 편집·기록)
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import extra_core as app      # 같은 모델 호출, 생각 줄이기, 기억 창 맞추기, 포기 감지
T = app                       # 웹 검색·웹 읽기

import extra_jobs as J
from extra_input import UI   # 아래 입력창 (작업 중에도 입력)
RUN = None            # extra run: (작업 폴더, job, 옵션)
HEADLESS = False      # 뒤에서 혼자 일하는 중 (묻지 않는다)
DEADLINE = 0.0        # 이 시각이 지나면 멈추고 결과를 남긴다
JOB_DIR = None
PROMPT_ROOT = Path.cwd().resolve()   # 사용자 프롬프트(.extra/prompt.md)를 찾을 프로젝트 (run 에서는 복사본이 아니라 원래 프로젝트)
_sub = sys.argv[1] if len(sys.argv) > 1 else ""
if _sub in ("--version", "-V", "version"):
    try:
        print("extra " + (APP_DIR / "VERSION").read_text().strip())
    except OSError:
        print("extra (dev)")
    sys.exit(0)
if _sub == "run":
    _o = J.parse_run(sys.argv[2:])
    _proj = Path.cwd().resolve()
    if _o["job"]:
        _d, _job = J.find(_proj, _o["job"])
        _proj = Path(_job["project"])
        _job["status"], _job["pid"] = "running", os.getpid()
        if _o["minutes"] != 30:
            _job["minutes"] = _o["minutes"]
        J.save(_d, _job)
    else:
        _d, _job = J.new_job(_proj, _o["task"], _o["test"], _o["minutes"], _o["prompt"], _o["files"])
    RUN, PROMPT_ROOT = (_d, _job, _o), _proj
    os.chdir(_d / "work")
    del sys.argv[1:]
elif _sub in ("jobs", "show", "apply"):
    _proj, _rest = Path.cwd().resolve(), sys.argv[2:]
    if _sub == "jobs":
        rows = J.list_jobs(_proj)
        _o, _r = ("\x1b[38;5;214m", "\x1b[0m") if sys.stdout.isatty() else ("", "")
        _g, _e = ("\x1b[38;5;114m", "\x1b[38;5;203m") if _o else ("", "")
        def _st(b):
            return (_g if b.startswith(("passed", "done")) else _e if b.startswith(("failed", "error", "timeout", "stopped")) else "") + f"{b:<20}" + _r
        print("\n".join(f"{(_o + '✻ Claude' + _r) if f == 'claude' else '  you   '}  {a}  {_st(b)} {c:<8} {d}" for a, b, c, d, f in rows)
              if rows else "no extra jobs for this project yet")
    elif _sub == "show":
        print(J.show(_proj, _rest[0] if _rest else "last"))
    else:
        print(J.apply(_proj, _rest[0] if _rest and not _rest[0].startswith("-") else "last", force="--force" in _rest))
    sys.exit(0)

# extra <폴더 경로> → 그 폴더에서 일한다 (없으면 만든다). 사용자 11/14: 새 폴더에서 시작하면 생각부터 하지 말고 무엇을 할지 묻기
_arg0 = sys.argv[1] if len(sys.argv) > 1 else ""
if _arg0 and not _arg0.startswith("-") and _arg0 not in ("continue", "chat", "prompt", "help", "skills") and (
        _arg0.startswith(("/", "~", "./", "../")) or Path(os.path.expanduser(_arg0)).is_dir()) and "\n" not in _arg0 and len(_arg0) < 400:
    _target = Path(os.path.expanduser(_arg0)).resolve()
    if not _target.exists():
        _target.mkdir(parents=True)
    if _target.is_dir():
        os.chdir(_target)
        del sys.argv[1]
        PROMPT_ROOT = _target
CWD = Path.cwd().resolve()
HOME = Path.home()
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", "dist", "build"}
SAFE_CMDS = ("ls", "cat", "head", "tail", "wc", "pwd", "grep", "rg", "find", "tree", "which", "echo", "date", "file", "stat", "du", "df",
             "git status", "git diff", "git log", "git show", "git branch", "python --version", "python3 --version", "node --version", "npm ls")
OUT_MAX = 30_000

# 색: 보라 = 모델의 목소리, 흰색 = 결정, 회색 = 자세한 것, 빨강 = 실패, 초록 = 성공
P, D, B, R, G, E = "\x1b[38;5;141m", "\x1b[38;5;244m", "\x1b[1m", "\x1b[0m", "\x1b[38;5;114m", "\x1b[38;5;204m"
W, LP, PINK, ACT, O = "\x1b[38;5;255m", "\x1b[38;5;183m", "\x1b[38;5;217m", "\x1b[48;5;55;38;5;255m", "\x1b[38;5;214m"
if not sys.stdout.isatty():
    P = D = B = R = G = E = W = LP = PINK = ACT = O = ""
LABEL = {"Problem": W + B, "Plan": LP + B, "Expect": D + B, "Result": W + B, "Failed": E + B, "Alternatives": PINK + B, "Check": G + B}


def color_thought(line):
    """'Plan: …' 같은 머리말에 색을 입힌다. Act 는 보라 바탕."""
    m = re.match(r"\s*(Problem|Plan|Expect|Act|Result|Failed|Alternatives|Check)\s*:\s*(.*)", line, re.S)
    if not m:
        return D + line + R
    k, rest = m.group(1), m.group(2)
    if k == "Act":
        return f"{ACT} Act {R} {W}{rest}{R}"
    return f"{LABEL[k]}{k}:{R} {W if k in ('Plan', 'Result') else D}{rest}{R}"

SYSTEM = f"""You are extra, a coding and computer assistant running in the user's terminal.
Project folder (your working directory): {CWD}. Home folder: {HOME}. Today is {{today}}.

How you think (the user sees it):
Always think in English, even when the user writes Korean. You may think again whenever you need to: before each action and after each tool result.
Before every action, write inside <think>...</think>, short, in English:
Problem / Plan / Expect ("If I do this, then this will happen") / Act ("So I will do: ..." — one concrete action, adjusted by your Expect).
After a tool result: Result (did it match your Expect, why not) / Failed (what and why) / Alternatives (at least three other ways, each with
"If I do this, then...") / then a new Plan, Expect, Act — or Check before the final answer.

YOUR ROLE: people use you when their main AI assistant (for example Claude) hits its usage limit. You take over ONE task and keep
working on it for a long time until it is completely done and verified, like a careful engineer. You are not a chatbot that answers once.
Do not stop to ask the user questions unless you are truly blocked; make sensible choices yourself and keep going step after step.
After every tool result, continue with the next step on your own. Finish only when the whole task works, with a short summary.

CHOOSING HOW TO BUILD (the user may be a beginner who does not know which tools exist — choosing well is your job, not theirs):
- Pick tools you can drive completely from the terminal with code. Avoid apps that are mainly used through their own editor window
  (Godot, Unity, Unreal, the Blender editor, Xcode storyboards) unless the user names them, because you cannot click in them.
- Prefer what already works on this Mac: first check with run_command (python3 --version, node --version, ls) before installing anything big.
- Good defaults: a game or anything visual → a web page (index.html + JavaScript files; for 3D use Three.js loaded from a CDN such as
  https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js), which needs no install. JavaScript modules do not load from a
  double-clicked file, so serve the folder: python3 -m http.server 8000, then open http://localhost:8000 in the browser.
  A tool or script → Python in a .venv. A website or server → Node or Python.
- Say your choice and the reason in one short sentence before building, and at the end tell the user exactly how to run it
  (for example: run python3 -m http.server 8000 in the project folder and open http://localhost:8000).

TOOLS ARE THE ONLY WAY YOU CAN DO ANYTHING (most important rule):
- Typing a file name and a code block in your reply does NOT create a file. Nothing happens unless you make a real tool call.
- Every Act must be carried out right away with a real tool call: write_file to create a file, edit_file to change one,
  run_command to run, install or test anything, download_file to fetch a file from the internet.
- Never print a file's contents as your answer. If your reply contains a whole file in a code block, you have made a mistake: call write_file instead.
- Do not announce what you "will" do and then stop. Do it with the tool in the same step.

GETTING WHAT YOU NEED FROM THE INTERNET:
- If you need a package, a library, a tool or a file, get it yourself: run_command with pip / npm / brew / git clone, or download_file.
  The user approves each install or download with y/n, so just ask through the tool and continue after it is approved.
- If the user says no, choose another way and keep going.
- Never guess a download URL. First web_fetch the official download or releases page (for example the project's GitHub releases page),
  copy the exact file link from it, then download_file that link. web_fetch reads a page; download_file is only for real files.
- On this Mac use python3. System Python is "externally managed", so for Python packages make a virtual environment in the project
  (python3 -m venv .venv, then .venv/bin/pip install ...) and run code with .venv/bin/python. Homebrew (if installed) is `brew`.
- Servers and other commands that never finish (python3 -m http.server, npm run dev, flask run, ...) are started in the background
  automatically; do not wait for them. Check them with curl (for example curl -s http://localhost:8000 | head) and keep working.
- Prefer non-interactive flags (-y, --yes, --no-input) so commands do not stop to wait for an answer. If a command does ask, the user answers it in the terminal.

Rules:
- Work inside the project folder. Read files before you change them.
- When you build something new, make it a real project: create a folder for it with a proper structure (code split into several files or
  modules, assets, a README that says how to run it, a requirements or package file, a run script). Never squeeze a whole app or game into one small file. Prefer edit_file for small changes and write_file for new files.
- After changing code, run it or its tests with run_command and read the real output. Do not claim something works without running it.
- Never say something cannot be done before trying several real alternatives.
- Do the work yourself. Asking the user to sign up, get a key, install something or run something is the last resort: first choose options
  that need nothing from the user (for example a free service with no key or sign-up). Ask only after those really failed.
- When the user asks you to make or build something (a game, a page, an app, a script), the deliverable is a SAVED FILE in the project:
  call write_file with the complete content. Never paste the code into the chat instead of saving it. Then say briefly what you made and how to run it.
- {{lang_rule}}
- Be brief. Show code only when it helps.
- If the user asks how to use extra itself (commands, settings, features), answer briefly and suggest /help <question> for details.
- Know what you cannot see: you cannot see a browser window, its console or its network tab. `open <url>` only shows the page to the
  user; once is enough. Verify web pages with things you can read: the task's check script, curl on the files and APIs, reading the code.
  JavaScript that runs in the browser does not run under curl. When the task's check passes and you have verified what you can observe,
  finish with Check and tell the user what to look at in the browser.
- Do not repeat the same command hoping for a different result. If it gave the same result twice, use a different way.
- Never wait for the user to confirm a tool call; just call it (the program asks the user itself when needed).
- Saving code: call write_file or edit_file. If a tool call is hard to write, you can also save code by writing a line
  FILE: <path>
  followed by a code block. A complete file replaces the file; for a Python file, a block with only some functions or classes
  replaces just those functions or classes and keeps the rest of the file."""


# ---------------- 스킬 (사용자 11/15: Claude 처럼 스킬 기능) ----------------
def skill_dirs():
    return [APP_DIR / "skills"]   # 기본 스킬만 (사용자 11/15: 사용자가 넣는 스킬은 없앤다)


def load_skills():
    """SKILL.md 들을 읽는다: 앞머리(name, description, triggers)와 본문."""
    out = {}
    for d in skill_dirs():
        for f in sorted(d.glob("*/SKILL.md")) if d.is_dir() else []:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            meta, body = {}, text
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
            if m:
                body = m.group(2)
                for line in m.group(1).splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
            name = meta.get("name") or f.parent.name
            out[name] = {"name": name, "description": meta.get("description", ""), "body": body.strip()[:6000], "path": str(f),
                         "triggers": [t.strip().lower() for t in meta.get("triggers", "").split(",") if t.strip()]}
    return out


def pick_skills(task_text, limit=2):
    """작업 글에 스킬의 키워드가 있으면 그 스킬 (많이 맞는 것부터, 최대 2 개)."""
    t = (task_text or "").lower()
    scored = []
    for sk in load_skills().values():
        hits = sum(1 for k in sk["triggers"]       # comment ↔ comments / commenting 도 맞게 (11/15)
                   if re.search(rf"(?<![a-z]){re.escape(k)}(?:s|es|ing|ed|er)?(?![a-z])", t) or (not k.isascii() and k in t))
        if hits:
            scored.append((hits, sk["name"]))
    scored.sort(reverse=True)
    return [n for _, n in scored[:limit]]


def skill_text(name):
    sk = load_skills().get(name)
    if not sk:
        names = ", ".join(sorted(load_skills())) or "none"
        return f"no skill named {name!r}. Skills: {names}"
    return f"[Skill: {sk['name']} — {sk['description']}]\n{sk['body']}"


def t_use_skill(name):
    print(f"{P}✦ skill:{R} {W}{name}{R}")
    return skill_text(str(name).strip())


def tool(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}, "required": req}}}


TOOLS = [
    tool("read_file", "Read a text file (with line numbers). Optional start and end line.", {"path": "file path", "start": "first line (optional)", "end": "last line (optional)"}, ["path"]),
    tool("list_dir", "List a folder.", {"path": "folder path, default ."}, []),
    tool("find_files", "Find files by name pattern inside the project, for example *.py or test_*.", {"pattern": "glob pattern"}, ["pattern"]),
    tool("search_text", "Search for text or a regular expression in the project's files.", {"pattern": "text or regex", "path": "folder or file, default ."}, ["pattern"]),
    tool("write_file", "Create or overwrite a file inside the project with its complete content.", {"path": "file path", "content": "the full new content"}, ["path", "content"]),
    tool("edit_file", "Replace one exact piece of text in a file. old must appear exactly once.", {"path": "file path", "old": "exact text to replace", "new": "replacement text"}, ["path", "old", "new"]),
    tool("run_command", "Run a shell command in the project folder and get its output.", {"command": "the command"}, ["command"]),
    tool("web_search", "Search the web.", {"query": "short search words"}, ["query"]),
    tool("web_fetch", "Read a public web page.", {"url": "http or https address"}, ["url"]),
    tool("download_file", "Download a file from the internet into the project.", {"url": "http or https address", "path": "where to save it in the project"}, ["url", "path"]),
    tool("use_skill", "Load a skill: short expert instructions for a kind of work (see the skills list in your instructions).", {"name": "skill name"}, ["name"]),
]
ACT_ASK = ("[Carry out your Act NOW with a real tool call (write_file, edit_file, run_command, download_file, ...). A code block in your reply does "
           "not create anything. Only if the whole task is finished and verified, write a short final summary for the user "
           "(in the answer language from your instructions). Your thinking is already done: do not write <think> again, do not restate the plan — act now.]")
# 생각 수준 (사용자 11/14): low = 계획과 실행만 / medium = 여러 방법(Options)까지, 예측은 안 함 / high = 여러 방법 + 예측(Expect)
THINK_LEVEL = {
    "low": "Problem / Plan / Act (\"So I will do: <exact tool call>\"). Do not list options and do not predict outcomes; just decide and act.",
    "medium": "Problem / Plan / Options (two or three ways to do the next step) / Act (\"So I will do: <exact tool call>\" — the best option). Do not predict outcomes.",
    "high": "Problem / Plan / Options (two or three ways to do the next step) / Expect (for each option, \"If I do this, then this will happen\") / "
            "Act (\"So I will do: <exact tool call>\" — the option your predictions say is best).",
}


def think_ask():
    lvl = SETTINGS.get("effort", "high")
    return (f"[Think in English only. Write ONLY your thinking now, inside <think>...</think>, short: {THINK_LEVEL.get(lvl, THINK_LEVEL['high'])} "
            "The Act names the one tool you will call next: write_file, edit_file, run_command, download_file, read_file, ... "
            "Do not plan to ask the user; decide yourself and keep working. Stop right after </think>.]")
# 검증 (사용자 11/14: 검토는 코드를 훑는 게 아니라 직접 돌려 보면서 확인하는 것 → 이름도 '검증')
REVIEW_ASK = ("[Think in English only. Write ONLY your verification now, inside <think>...</think>. Verifying means RUNNING things, not reading code: "
              "Result (what the real output showed, did it match your Expect, why not) / Failed (what and why, if it failed) / "
              "Alternatives (if it failed: at least three other ways, each with \"If I do this, then...\") / then either "
              "Check (only if the WHOLE task is done AND you have run it and seen it work: quote the command and its output) or the next Plan / Expect / Act. "
              "If you just wrote or edited code and have not run it yet, your next Act must run it or its tests with run_command. Stop right after </think>.]")
# 사용자에게 일을 떠넘기며 멈추기 (11/14: 키 없는 다른 API 를 Alternatives 에 적어 놓고도 '가입해서 키를 달라'며 멈췄다)
ASK_USER_RE = re.compile(r"(please\s+(sign\s*up|register|provide|share|enter|give|create|send|install|download)|"
                         r"(share|provide|send|give)\s+(me\s+)?(the|your|an?)\s+(free\s+)?(api\s+)?(key|token|password|credentials)|"
                         r"(need|want)\s+you\s+to|could\s+you\s+(please\s+)?(provide|sign|share|run|open|install)|"
                         r"key\s+here|after\s+you\s+provide|once\s+you\s+(have|provide|share|sign)|"
                         r"가입(해|하)\s*주|키를?\s*(알려|주시|보내)|직접\s*(실행|설치|가입))", re.I)
ASK_USER_NUDGE = ("[Do not hand the work back to the user yet. Asking the user is the last resort. First try every alternative that does not need "
                  "the user (for example a different free service that needs no key or sign-up, another library, or another way to get the same result). "
                  "Pick the best one and do it now with a tool. Ask the user only if all of them have really failed, and then say exactly what you tried.]")
VERIFY_NUDGE = ("[Before you finish, verify by running: you changed files but have not run anything since. Run the code or its tests with run_command "
                "and check the real output. Reading the code is not verification.]")
FINISH_ASK = ("[You wrote Check: the task is done and verified. Do not call any tool. Write the final summary for the user now, in the "
              "answer language from your instructions: what you changed (files), how you verified it (the commands you ran and what they printed), and "
              "anything they should look at themselves. Short, no headings like 'summary in X'.]")
TOOL_NAME_RE = re.compile(r"\b(read_file|list_dir|find_files|search_text|write_file|edit_file|run_command|web_search|web_fetch|download_file)\b")
WORK_RE = re.compile(r"\b(run|edit|write|fetch|search|read|create|install|download|serve|test|check|open|implement|update|fix|replace|build|save|curl|verify|try|use)\b", re.I)
ACT_PASTE = ("[You wrote code in your reply, but text in a reply changes no file and runs nothing. Call the tool now: edit_file (old -> new) "
             "or write_file with the complete file content, or run_command for a command. Do not write a code block in the reply again.]")
ACT_STRICT = ("[You did not call a tool. Do not think and do not explain. Call the tool from your Act line right now as a real tool call.]")
ALLOW_ALL = set()
# 권한 설정 (/set 으로 바꾸고 ~/.extra/settings.json 에 남긴다). 설치·패키지 조회는 처음부터 항상 허락 (사용자 11/14)
SET_FILE = HOME / ".extra" / "settings.json"
# 답하는 언어 (사용자 11/15: 처음 설정에서 고르고, 고른 언어에 맞는 규칙이 기본 프롬프트에 들어간다). 생각은 늘 영어.
LANGS = {
    "auto": ("Match the user", "Answer in the language the user writes in."),
    "en": ("English", "Always answer the user in English, whatever language they write in. Plain, friendly, direct."),
    "ko": ("한국어", "Always answer the user in Korean (commands, file names and code stay as they are). Be polite and warm: every sentence "
                   "ends with -습니다 / -ㅂ니다 / -십시오 (for example: 바꿨습니다, 통과했습니다, 확인하십시오) — never -요, -세요, or plain -다."),
    "ja": ("日本語", "Always answer the user in Japanese, in the polite です/ます form (commands, file names and code stay as they are)."),
    "zh": ("中文", "Always answer the user in Simplified Chinese (commands, file names and code stay as they are)."),
    "es": ("Español", "Always answer the user in Spanish, addressing them as usted (commands, file names and code stay as they are)."),
    "de": ("Deutsch", "Always answer the user in German, addressing them as Sie (commands, file names and code stay as they are)."),
    "fr": ("Français", "Always answer the user in French, addressing them as vous (commands, file names and code stay as they are)."),
}


def lang_rule():
    return LANGS.get(SETTINGS.get("language", "auto"), LANGS["auto"])[1]


DEFAULTS = {"installs": "always", "downloads": "ask", "writes": "ask", "commands": "ask", "dangerous": "ask", "effort": "high", "review": "on"}
KIND = {"install": "installs", "download": "downloads", "write": "writes", "run": "commands", "danger": "dangerous"}
# 위험한 것까지 허락해도 이것만은 막는다: 컴퓨터 전체·홈 폴더 통째 지우기 (되돌릴 수 없다)
WIPE_RE = re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(/|~|~/|\$HOME|/Users|/Users/[^/\s]+/?|/System|/Applications|/Library)(\s|$)")
try:
    SETTINGS = {**DEFAULTS, **json.loads(SET_FILE.read_text())}
except (OSError, ValueError):
    SETTINGS = dict(DEFAULTS)
INSTALL_RE = re.compile(r"^\s*(sudo\s+)?(pip3?|python3?\s+-m\s+pip|uv\s+(pip|add)|npm|npx|pnpm|yarn|brew|gem|cargo\s+install|go\s+install|conda|mamba|git\s+clone|pipx)\b(?!.*\b(uninstall|remove|rm)\b)")
DANGER_RE = re.compile(r"(\brm\s+-[a-z]*r|\bsudo\b|\bdd\s+if=|\bmkfs|\bshutdown\b|\breboot\b|diskutil\s+erase|:\(\)\s*\{|>\s*/dev/|chmod\s+-R\s+777\s+/|launchctl\s+(unload|bootout)|\bkillall\b)")


def save_settings():
    SET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SET_FILE.write_text(json.dumps(SETTINGS, indent=1))


def set_command(arg):
    """/set                → 지금 설정 보기
    /set all always        → 전부 묻지 않고 허락 (지우기·sudo 같은 위험한 명령만은 계속 묻는다)
    /set all ask           → 전부 물어보기 (설치는 설정대로)
    /set <항목> always|ask  → 항목: installs, downloads, writes, commands"""
    parts = ["review" if x == "verify" else x for x in arg.split()]
    if len(parts) == 2 and parts[0] == "speedup":
        if parts[1] == "on":
            speedup_on()
        else:
            SETTINGS["speedup"] = "no"; save_settings(); print(f"{G}✓ saved{R} {D}(the Ollama settings stay as they are; extra will not ask again){R}")
        return
    names = list(DEFAULTS)
    perms = [k for k in names if k not in ("effort", "review")]
    if len(parts) == 2 and parts[0] == "effort" and parts[1] in ("low", "medium", "high"):
        SETTINGS["effort"] = parts[1]; save_settings(); print(f"{G}✓ saved{R}")
    elif len(parts) == 2 and parts[0] == "review" and parts[1] in ("on", "off"):
        SETTINGS["review"] = parts[1]; save_settings(); print(f"{G}✓ saved{R}")
    elif len(parts) == 2 and parts[1] in ("always", "ask") and (parts[0] in perms or parts[0] == "all"):
        for k in (perms if parts[0] == "all" else [parts[0]]):
            SETTINGS[k] = parts[1]
        save_settings()
        print(f"{G}✓ saved{R}")
    elif parts:
        print(f"{E}usage: /set <installs|downloads|writes|commands|dangerous|all> <always|ask>  ·  /set effort <low|medium|high>  ·  /set verify <on|off>{R}")
    label = {"installs": "install / look up packages (pip, npm, brew, git clone)", "downloads": "download files from the internet",
             "writes": "create or edit files in this project", "commands": "run other commands", "dangerous": "rm -r, sudo, killall … (wiping / or your home is always blocked)"}
    print(f"\n {B}thinking{R}")
    eff = {"low": "plan → act (fastest)", "medium": "plan → options → act", "high": "plan → options → expect → act (most careful)"}
    print(f"  {P}{SETTINGS['effort']:>6}{R}  effort     {D}{eff.get(SETTINGS['effort'], '')}{R}")
    print(f"  {G if SETTINGS['review'] == 'on' else O}{SETTINGS['review']:>6}{R}  verify     {D}run it and check the real result after each step; find other ways when it fails{R}")
    print(f"\n {B}permissions{R}  {D}(saved in {SET_FILE}){R}")
    for k in [x for x in names if x not in ("effort", "review")]:
        v = SETTINGS[k]
        print(f"  {G if v == 'always' else O}{v:>6}{R}  {k:<10} {D}{label[k]}{R}")
    print(f"  {D}change: /set <name|all> <always|ask> · /set effort <low|medium|high> · /set verify <on|off>{R}\n")


# ---------------- 도구 ----------------
def resolve(path, write=False):
    p = (CWD / os.path.expanduser(str(path or "."))).resolve()
    if any(T.SECRET.search(x) for x in p.parts[-3:]):
        return None, "this file looks secret, so it is not opened"
    if write and p != CWD and CWD not in p.parents:
        return None, f"you can only write inside the project folder {CWD}"
    return p, None


def read_answer(prompt):
    """질문의 대답: 아래 입력창이 켜져 있으면 거기서, 아니면 보통 input."""
    if UI.on:
        return UI.ask(prompt)
    try:
        return input(prompt)
    except EOFError:
        return ""


def denied():
    if HEADLESS:
        return "not allowed in a background job (nobody can approve it). Choose another way and keep going; mention it in your summary if it matters."
    return "the user said no. Ask what they want instead, or try another approach."


def ask(kind, what, preview=""):
    """쓰기·실행 전에 묻는다. y 이번만 / a 이번 세션 내내 / n 하지 않음. /set 에서 always 로 둔 것은 묻지 않는다."""
    if kind in ALLOW_ALL or (kind in KIND and SETTINGS.get(KIND[kind]) == "always"):
        print(f"{G}✓ allowed{R} {D}{what}{R}")
        return True
    if HEADLESS:
        ok = kind in ("write", "run", "install")
        print(f"{G}✓ allowed{R} {D}{what}{R}" if ok else f"{E}✗ not allowed in a background job{R} {D}{what}{R}")
        return ok
    print(f"\n{P}?{R} {B}{what}{R}")
    if preview:
        print(preview)
    a = read_answer(f"{P}  allow? [y]es / [a]lways / [n]o › {R}").strip().lower()
    if a.startswith("a"):
        ALLOW_ALL.add(kind)
        return True
    return a.startswith("y")


def colored_diff(old, new, name, limit=60):
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=2))
    out = []
    for l in lines[:limit]:
        out.append((G if l.startswith("+") and not l.startswith("+++") else E if l.startswith("-") and not l.startswith("---") else D) + "  " + l + R)
    if len(lines) > limit:
        out.append(f"{D}  … {len(lines) - limit} more diff lines{R}")
    return "\n".join(out)


def t_read_file(path, start="", end=""):
    p, why = resolve(path)
    if why:
        return why
    if not p.is_file():
        return "not a file"
    lines = p.read_text(errors="replace").splitlines()
    a = max(1, int(start)) if str(start).strip().isdigit() else 1
    b = min(len(lines), int(end)) if str(end).strip().isdigit() else len(lines)
    out = "\n".join(f"{i:5}  {lines[i - 1]}" for i in range(a, b + 1))
    return (out[:OUT_MAX] + ("\n… (cut; read a smaller range)" if len(out) > OUT_MAX else "")) or "(empty file)"


def t_list_dir(path="."):
    p, why = resolve(path)
    if why:
        return why
    if not p.is_dir():
        return "not a folder"
    rows = [x.name + ("/" if x.is_dir() else "") for x in sorted(p.iterdir()) if x.name not in SKIP]
    return "\n".join(rows[:300]) or "(empty)"


def t_find_files(pattern):
    out = []
    for base, dirs, files in os.walk(CWD):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if fnmatch.fnmatch(f, pattern):
                out.append(str(Path(base, f).relative_to(CWD)))
        if len(out) > 300:
            break
    return "\n".join(out[:300]) or "nothing found"


def t_search_text(pattern, path="."):
    p, why = resolve(path)
    if why:
        return why
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    out = []
    files = [p] if p.is_file() else [Path(b, f) for b, ds, fs in os.walk(p) for f in fs if not any(x in SKIP for x in Path(b).parts)]
    for f in files:
        try:
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f.relative_to(CWD) if CWD in f.parents or f == CWD else f}:{i}: {line.strip()[:200]}")
                    if len(out) >= 200:
                        break
        except (OSError, ValueError):
            pass
        if len(out) >= 200:
            break
    return "\n".join(out) or "no match"


def show_writing(rel, content, edit=False):
    """파일에 쓰는 내용을 줄 번호와 함께 흘려 보여 준다 (사용자 11/14: 파일 쓰기도 실시간으로). 길어도 2초 안에."""
    if rel in STREAMED or Path(rel).name in {Path(x).name for x in STREAMED}:
        for x in [x for x in STREAMED if x == rel or Path(x).name == Path(rel).name]:
            STREAMED.discard(x)
        return                      # 답장 안에서 쓰는 모습을 이미 보여 주었다
    print(f"{P}✎ {'editing' if edit else 'writing'} {rel}{R}")
    if not live():
        return
    lines = content.split("\n")
    box = LiveBox(8, D, "  ")
    delay = min(0.03, 2.0 / max(1, len(lines)))
    for i, l in enumerate(lines, 1):
        box.add(f"{D}{i:>4}{R}  {hl(l, rel)}\n")
        time.sleep(delay)
    box.close()


def file_summary(rel, old, new):
    FLOG.detail(f"content of {rel}", "\n".join(hl(l, rel) for l in new.split("\n")), color="")
    a = d_ = 0
    for l in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""):
        if l.startswith("+") and not l.startswith("+++"):
            a += 1
        elif l.startswith("-") and not l.startswith("---"):
            d_ += 1
    tag = fold(f"changes in {rel}", colored_diff(old, new, rel, limit=100000))
    print(f"{G}  ✓ {rel}{R} {D}· {len(new.splitlines())} lines{R} {G}+{a}{R} {E}−{d_}{R} {tag}")


PROTECTED = set()       # 작업을 시작할 때 이미 있던 시험 파일 (고치지 못한다)
TEST_FILE_RE = re.compile(r"(^|/)(check[\w-]*\.py|test_[\w-]*\.py|[\w-]+_test\.py|[\w-]+\.(test|spec)\.[jt]sx?|conftest\.py)$|(^|/)(tests?|__tests__|spec)/")


def protect_tests(task_text):
    """작업이 '시험을 고쳐/추가해' 가 아니면, 지금 있는 시험 파일을 보호한다 (11/15: 실패하자 check.py 를 고쳤다)."""
    PROTECTED.clear()
    if re.search(r"(write|add|fix|update|change|edit|create|rewrite|고쳐|추가|수정|만들)\W{0,3}.{0,30}(test|check|테스트|시험)", task_text or "", re.I):
        return
    for f in CWD.rglob("*"):
        try:
            rel = str(f.relative_to(CWD))
        except ValueError:
            continue
        if f.is_file() and TEST_FILE_RE.search(rel) and not any(part in SKIP for part in f.relative_to(CWD).parts):
            PROTECTED.add(f.resolve())


def guarded(p):
    if p.resolve() in PROTECTED:
        return (f"refused: {p.relative_to(CWD)} is the task's check (a test that existed before you started). Do not change it — "
                "it defines when the task is done. Change the code so that it passes.")
    return None


def t_write_file(path, content):
    p, why = resolve(path, write=True)
    if why:
        return why
    if guarded(p):
        return guarded(p)
    old = p.read_text(errors="replace") if p.exists() else ""
    rel = str(p.relative_to(CWD))
    show_writing(rel, content)
    preview = colored_diff(old, content, rel)
    if not ask("write", f"{'Overwrite' if p.exists() else 'Create'} {rel} ({len(content.splitlines())} lines)", preview):
        return denied()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    file_summary(rel, old, content)
    return f"saved {rel}"


def loose_replace(text, old, new):
    """old 가 글자 그대로는 없을 때: 줄마다 앞뒤 공백을 무시하고 맞춰 본다. 딱 한 곳이 맞으면 그 줄들을 new 로 바꾼다.
    (11/15: old 의 들여쓰기가 파일과 달라 edit_file 이 실패했다)"""
    want = [l.strip() for l in old.strip("\n").split("\n")]
    if not any(want):
        return None
    lines = text.split("\n")
    hits = [i for i in range(len(lines) - len(want) + 1) if [l.strip() for l in lines[i:i + len(want)]] == want]
    if len(hits) != 1:
        return None
    i = hits[0]
    return "\n".join(lines[:i] + new.rstrip("\n").split("\n") + lines[i + len(want):])


def t_edit_file(path, old, new):
    p, why = resolve(path, write=True)
    if why:
        return why
    if guarded(p):
        return guarded(p)
    if not p.is_file():
        return "no such file; use write_file to create it"
    text = p.read_text(errors="replace")
    n = text.count(old)
    if n == 1:
        new_text = text.replace(old, new)
    else:
        new_text = loose_replace(text, old, new) if n == 0 else None
        if new_text is None:
            return f"old text found {n} times; it must appear exactly once. Read the file again and copy the exact text."
    rel = str(p.relative_to(CWD))
    show_writing(rel, new, edit=True)
    if not ask("write", f"Edit {rel}", colored_diff(text, new_text, rel)):
        return denied()
    p.write_text(new_text)
    file_summary(rel, text, new_text)
    return f"edited {rel}"


# 끝나지 않는 명령(웹 서버 등)은 뒤에서 띄운다 (11/14: python3 -m http.server 에서 멈췄다)
SERVER_RE = re.compile(r"(http\.server|\b(npm|yarn|pnpm|bun)\s+(run\s+)?(dev|start|serve|preview)\b|\bnpx\s+(serve|http-server|vite|live-server|next\s+dev)|"
                       r"^\s*vite\b|flask\s+run|uvicorn|gunicorn|runserver|\brails\s+s(erver)?\b|php\s+-S|live-server|http-server|nodemon|"
                       r"node\s+\S*(server|app|index)\.m?js\s*$|streamlit\s+run|jupyter\s+(notebook|lab)|&\s*$)")
BG = []   # 뒤에서 도는 명령들 (extra 를 끌 때 같이 끈다)


def _kill_bg():
    import signal as _sig
    for pr in BG:
        try:
            os.killpg(pr.pid, _sig.SIGTERM)
        except OSError:
            pass


import atexit
atexit.register(_kill_bg)


def run_background(c):
    """서버처럼 끝나지 않는 명령: 뒤에서 띄우고 처음 몇 초의 출력만 돌려준다."""
    c = re.sub(r"&\s*$", "", c).strip()
    log = HOME / ".extra" / "bg" / f"{time.strftime('%H%M%S')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", PYTHONUNBUFFERED="1")
    pr = subprocess.Popen(c, shell=True, cwd=CWD, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    BG.append(pr)
    tick = Ticker(f"starting in the background: {c[:50]}")
    for _ in range(30):
        time.sleep(0.1)
        if pr.poll() is not None:
            break
    tick.stop()
    first = log.read_text(errors="replace")[-3000:].strip()
    if pr.poll() is not None:
        print(f"{D}  └{R} {E}exited at once (exit {pr.returncode}){R}")
        return f"exit code {pr.returncode} (it stopped right away)\n" + (first or "(no output)")
    port = re.search(r"(?:-p|--port|:|\s)(\d{4,5})\b", c)
    port = port.group(1) if port else ("8000" if "http.server" in c else None)
    print(f"{D}  └{R} {G}running in the background{R} {D}· pid {pr.pid}{' · port ' + port if port else ''} · it stops when extra exits{R}")
    return (f"started in the background (pid {pr.pid}); it keeps running, so do not wait for it. First output:\n{first or '(none yet)'}\n"
            + (f"Check it responds with: curl -s http://localhost:{port} | head -20\n" if port else "")
            + f"Stop it with: kill {pr.pid}")


def t_run_command(command):
    c = str(command).strip()
    # 명령 앞에 도구 이름을 붙여 쓴 경우 (11/15: 'run_command python3 check.py' → exit 127 이 나자 '도구가 고장 났다' 고 판단했다)
    c = re.sub(r"^(?:run_command|bash|shell|sh -c|zsh|terminal)\s*[:(]?\s*|^\$\s+", "", c).strip()
    if c.endswith(")") and str(command).strip().startswith("run_command("):
        c = c[:-1].strip().strip("'\"")
    safe = any(c == s or c.startswith(s + " ") for s in SAFE_CMDS) and not re.search(r"[;&|>`$]|\brm\b", c.replace("2>/dev/null", ""))
    if WIPE_RE.search(c):
        return "refused: this would delete the whole computer or home folder. Delete only specific files inside the project."
    for pf in PROTECTED:     # 셸로 시험 파일을 바꾸는 것도 막는다 (>, >>, sed -i, rm, mv, cp … 대상)
        try:
            rel = str(pf.relative_to(CWD))
        except ValueError:
            continue
        if re.search(rf"(>>?|\bsed\s+-i\S*|\brm\b|\bmv\b|\bcp\b|\btee\b|\btruncate\b)[^|;&]*\b{re.escape(rel)}\b", c):
            return f"refused: {rel} is the task's check. Do not change it; change the code so that it passes."
    kind = "danger" if DANGER_RE.search(c) else "install" if INSTALL_RE.search(c) and not re.search(r"[;&|`]", c) else "run"
    if not safe and not ask(kind, f"Run: {c}"):
        return denied()
    # 명령의 출력은 흐리게 바로 보여 주고(설치 진행 상황 등), 명령이 직접 묻는 질문(Proceed? [y/N])에는 사용자가 터미널에서 답한다.
    # (11/14: 출력을 숨기고 입력도 막아 두어서, brew·pip 의 확인 질문에 답할 수 없어 같은 일만 되풀이했다)
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_ENV_HINTS="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    print(f"{D}  ┌ {c[:term_cols() - 6]}{R}")
    if SERVER_RE.search(c) and not HEADLESS:
        return run_background(c)
    start, buf = time.time(), []
    shown = {"n": 0, "part": ""}
    SHOW_MAX = 12

    def out_lines(text):
        """명령 출력을 줄 단위로 바로 보여 준다. 40 줄을 넘으면 개수만 센다 (11/15: curl 결과가 화면을 덮었다)."""
        shown["part"] += text
        while "\n" in shown["part"]:
            line, shown["part"] = shown["part"].split("\n", 1)
            shown["n"] += 1
            if shown["n"] <= SHOW_MAX:
                line = line if len(line) <= 300 else line[:300] + " …"
                print(f"{D}  │ {line}{R}")
            else:
                FLOG.line(f"{D}  │ {line}")
    try:
        proc = subprocess.Popen(c, shell=True, cwd=CWD, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL if HEADLESS else subprocess.PIPE if UI.on else None)
        if UI.on:
            UI.proc = proc
        cap = min(900, max(30, DEADLINE - time.time())) if DEADLINE else 900
        fd = proc.stdout.fileno()
        import select
        while True:
            r_, _, _ = select.select([fd], [], [], 0.5)
            if r_:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                text = chunk.decode(errors="replace")
                buf.append(text)
                out_lines(text)
                tail = "".join(buf)[-200:]
                UI.wants_input = (not tail.endswith("\n")) and bool(re.search(r"(\?|\[[yYnN]/[yYnN]\]|\([yYnN]/[yYnN]\)|password|passphrase|:)\s*$", tail, re.I))
            elif proc.poll() is not None:
                break
            if time.time() - start > cap:
                proc.kill()
                buf.append(f"\n(stopped after {cap / 60:.0f} minutes)")
                break
        proc.wait(timeout=10)
        UI.proc = None
        UI.wants_input = False
        out = "".join(buf).strip()
        if shown["part"]:
            out_lines("\n")
        n = len(out.splitlines())
        more = f" {D}· {n - SHOW_MAX} more lines not shown{R}" if n > SHOW_MAX else ""
        col = G if proc.returncode == 0 else E
        print(f"{D}  └{R} {col}exit {proc.returncode}{R} {D}· {n} lines{R}{more}")
        return f"exit code {proc.returncode}\n" + (out[-OUT_MAX:] if out else "(no output)")
    except Exception as e:
        UI.proc = None
        return f"failed to run: {type(e).__name__}: {e}"


def t_download_file(url, path):
    url = str(url).strip()
    if not url.startswith(("http://", "https://")) or not T.public_url(url):
        return "only public http/https addresses can be downloaded"
    p, why = resolve(path, write=True)
    if why:
        return why
    size = ""
    try:
        h = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": T.BROWSER}), timeout=15)
        n = int(h.headers.get("Content-Length") or 0)
        size = f" ({n / 1e6:.1f} MB)" if n else ""
    except Exception:
        pass
    if not ask("download", f"Download {url}{size} → {p.relative_to(CWD)}"):
        return denied()
    p.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": T.BROWSER}), timeout=120) as r, open(p, "wb") as f:
        shutil.copyfileobj(r, f)
    return f"saved {p.relative_to(CWD)} ({p.stat().st_size / 1e6:.1f} MB)"


CALLS = {"use_skill": t_use_skill, "read_file": t_read_file, "list_dir": t_list_dir, "find_files": t_find_files, "search_text": t_search_text, "write_file": t_write_file,
         "edit_file": t_edit_file, "run_command": t_run_command, "download_file": t_download_file, "web_search": lambda query: T.web_search(query), "web_fetch": lambda url: T.web_fetch(url)}


# ---------------- 화면 ----------------
def text_calls(content):
    """모델이 도구 호출을 글로 써 버린 것 되살리기 (11/14: 'edit_file\n{"path": ...}' 처럼 썼는데 [TOOL_CALLS] 표시가 빠져
    Ollama 가 도구 호출로 알아보지 못했다). 이름 + JSON 인자 형태만 받는다. 설명 글('So I will do: edit_file ...')은 건드리지 않는다."""
    names = "|".join(re.escape(t["function"]["name"]) for t in TOOLS)
    calls, spans = [], []
    for m in re.finditer(rf"(?:\[TOOL_CALLS\]\s*)?\b({names})\s*(?:\[ARGS\])?\s*(?=\{{)", content):
        try:
            args, end = json.JSONDecoder().raw_decode(content, m.end())
        except json.JSONDecodeError:
            continue
        if isinstance(args, dict) and args:
            calls.append({"id": f"text_{len(calls)}", "function": {"name": m.group(1), "arguments": args}})
            spans.append((m.start(), end))
    for st, en in reversed(spans):
        content = content[:st] + content[en:]
    return calls, content


def block_calls(answer, thought=""):
    """코드 블록을 저장 호출로 (작은 모델은 긴 코드를 도구 인자 JSON 에 넣기 어려워한다, 11/14 공동 작업 시험).
    'FILE: 경로' 다음 코드 블록, 또는 생각의 Act 가 write_file/edit_file <경로> 이고 코드 블록이 하나뿐일 때만."""
    # <edit_file>path: ... old: ... new: ...</edit_file> / <write_file>path: ... </write_file> XML 흉내 (11/15: 이 형식을 글로만 쓰고 반복에 빠졌다)
    xml = []
    for m in re.finditer(r"<(edit_file|write_file)>(.*?)</\1>", answer, re.S | re.I):
        kind, body = m.group(1).lower(), m.group(2)
        pm = re.search(r"path\s*:\s*`?([^\s`\n]+)", body)
        if not pm:
            continue
        if kind == "edit_file":
            om = re.search(r"old\s*:\s*(.*?)(?:\n\s*new\s*:|$)", body, re.S | re.I)
            nm = re.search(r"new\s*:\s*(.*)", body, re.S | re.I)
            if om and nm:
                xml.append({"id": f"xml_{len(xml)}", "function": {"name": "edit_file",
                    "arguments": {"path": pm.group(1), "old": om.group(1).strip("\n"), "new": nm.group(1).strip().strip("\n")}}})
        else:
            cm = re.search(r"(?:content|code)\s*:\s*\n?(.*)", body, re.S | re.I)
            if cm:
                xml.append({"id": f"xml_{len(xml)}", "function": {"name": "write_file",
                    "arguments": {"path": pm.group(1), "content": cm.group(1).strip("\n") + "\n"}}})
    if xml:
        return xml
    blocks = list(re.finditer(r"(?:\**FILE:\**\s*`?([^\s`*]+)`?\s*\n)?```([^\n]*)\n(.*?)\n```", answer, re.S))
    act = re.findall(r"\b(?:write_file|edit_file)\b\W{0,3}`?([\w./-]+\.\w+)`?", thought or "")
    calls = []
    # 답장이 짧은 셸 코드 블록 하나뿐이면 그 명령을 실행하려던 것 (11/15: 'python3 -m http.server 8000' 을 블록으로만 쓰고 끝났다).
    # 설명 글이 붙은 완료 답장('이렇게 실행하세요')은 건드리지 않는다.
    SHELL = ("bash", "sh", "shell", "zsh", "console", "terminal")
    if blocks and len(blocks) <= 3 and all(b.group(2).strip().lower() in SHELL for b in blocks):
        prose = re.sub(r"```.*?```", "", answer, flags=re.S).strip()
        finished = bool(re.search(r"^\s*\**\s*Check\s*\**\s*:", thought or "", re.M))
        if len(prose) < 80 or not finished:
            out = []
            for k, b in enumerate(blocks):
                lines = [re.sub(r"^\$\s*", "", l) for l in b.group(3).strip().splitlines() if l.strip() and not l.strip().startswith("#")]
                if lines and len(lines) <= 5:
                    out.append({"id": f"shell_{k}", "function": {"name": "run_command", "arguments": {"command": " && ".join(lines)}}})
            if out:
                return out
    for m in blocks:
        body = m.group(3)
        if re.search(r"\b(edit_file|write_file|run_command|read_file|web_fetch|web_search)\s*\(", body):
            continue          # 도구 호출을 흉내 낸 글 (11/15: 이걸 app.js 에 덮어써 버렸다)
        before = answer[max(0, m.start() - 200):m.start()]
        near = re.findall(r"`?((?:\.?[\w-]+/)*[\w.-]+\.(?:md|html?|js|jsx|ts|tsx|css|py|json|txt|sh))`?", before)
        handoff = ".extra/handoff.md" if body.lstrip().startswith("# Handoff") else None
        named = m.group(1) or (act[-1] if act and len(blocks) == 1 else None) or handoff or (near[-1] if near else None)
        path = named or guess_file(m.group(2), body)
        if not path:
            continue
        code = m.group(3) + "\n"
        p, err = resolve(path, write=True)
        if err or p is None:
            continue
        if p.is_file() and p.suffix == ".py":
            merged = merge_python(p.read_text(), code)
            if merged is None:
                continue
            code = merged
        elif p.is_file() and p.suffix in (".js", ".mjs", ".ts", ".jsx", ".tsx") and merge_js(p.read_text(errors="replace"), code) is not None:
            code = merge_js(p.read_text(errors="replace"), code)      # 블록이 함수 몇 개뿐이면 그 함수만 바꾼다 (11/15)
        elif p.is_file() and not named:
            old = p.read_text(errors="replace")
            # 이름을 추측했을 뿐이면, 기존 파일을 통째로 바꿀 만큼 완전한 코드일 때만 (길이가 비슷하고 뼈대가 겹칠 때)
            ids = lambda t: set(re.findall(r"\b(?:function|class|def|const|let|var|id=)\s*\"?([A-Za-z_]\w+)", t))
            if len(code) < 0.6 * len(old) or (ids(old) and len(ids(old) & ids(code)) < 0.5 * len(ids(old))):
                continue
        calls.append({"id": f"block_{len(calls)}", "function": {"name": "write_file", "arguments": {"path": path, "content": code}}})
    return calls


LANG_EXT = {"markdown": ".md", "md": ".md", "html": ".html", "htm": ".html", "javascript": ".js", "js": ".js", "css": ".css", "python": ".py", "py": ".py",
            "typescript": ".ts", "ts": ".ts", "json": ".json", "jsx": ".jsx", "tsx": ".tsx"}


def guess_file(lang, code):
    """FILE: 표시가 없는 코드 블록의 파일 이름 (11/14: 이름 없이 코드만 쓰고 멈췄다).
    1) 첫 줄 주석의 파일 이름 (// script.js, # app.py, <!-- index.html -->)  2) 같은 종류 파일이 프로젝트에 하나뿐이면 그것."""
    first = code.strip().split("\n", 1)[0] if code.strip() else ""
    m = re.match(r"^\s*(?://|#|<!--|/\*)\s*([\w./-]+\.(?:html?|js|jsx|ts|tsx|css|py|json))\b", first)
    if m:
        return m.group(1)
    ext = LANG_EXT.get(lang.strip().lower().split()[0] if lang.strip() else "")
    if not ext and code.lstrip().lower().startswith(("<!doctype html", "<html")):
        ext = ".html"
    if not ext:
        return None
    found = [x for x in CWD.rglob(f"*{ext}") if not any(part in SKIP or part.startswith(".") for part in x.relative_to(CWD).parts)][:3]
    if len(found) == 1:
        return str(found[0].relative_to(CWD))
    if not found and ext == ".html":
        return "index.html"          # 아직 HTML 이 하나도 없으면 첫 페이지
    return None


JS_FN = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)", re.M)


def _js_span(text, start):
    """start 줄에서 시작하는 함수의 끝(닫는 중괄호 다음)까지. 문자열·주석 안의 괄호는 대충 건너뛴다."""
    i, depth, seen, q = text.index("{", start) if "{" in text[start:] else -1, 0, False, None
    if i < 0:
        return None
    while i < len(text):
        c = text[i]
        if q:
            if c == "\\":
                i += 2; continue
            if c == q:
                q = None
        elif c in "'\"`":
            q = c
        elif text.startswith("//", i):
            j = text.find("\n", i); i = len(text) if j < 0 else j; continue
        elif c == "{":
            depth += 1; seen = True
        elif c == "}":
            depth -= 1
            if seen and depth == 0:
                end = i + 1
                while end < len(text) and text[end] in ";":
                    end += 1
                return end
        i += 1
    return None


def merge_js(old, block):
    """블록이 최상위 함수 몇 개뿐이고 그 함수들이 파일에 이미 있으면, 그 함수만 바꾼 파일을 돌려준다. 아니면 None."""
    new_fns = [(m.group(1) or m.group(2), m.start()) for m in JS_FN.finditer(block)]
    if not new_fns:
        return None
    old_fns = {(m.group(1) or m.group(2)): m.start() for m in JS_FN.finditer(old)}
    if not all(n in old_fns for n, _ in new_fns):
        return None
    if len(new_fns) >= len(old_fns) * 0.8:           # 거의 전부면 파일 전체로 보고 여기서는 다루지 않는다
        return None
    out = old
    for name, bstart in new_fns:
        bend = _js_span(block, bstart)
        ostart = {(m.group(1) or m.group(2)): m.start() for m in JS_FN.finditer(out)}.get(name)
        oend = _js_span(out, ostart) if ostart is not None else None
        if bend is None or oend is None:
            return None
        out = out[:ostart] + block[bstart:bend] + out[oend:]
    return out


def merge_python(old, block):
    """블록이 파일 전체면 그대로, 일부 함수·클래스만이면 그 부분만 바꾼다. 알 수 없으면 None (덮어써서 지우는 일이 없게)."""
    import ast
    try:
        new_t, old_t = ast.parse(block), ast.parse(old)
    except SyntaxError:
        return None
    names = lambda t: {n.name: n for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    on, nn = names(old_t), names(new_t)
    if not nn:
        return None
    if set(on) <= set(nn):            # 원래 있던 함수·클래스가 다 들어 있다 → 파일 전체
        return block
    lines, blines = old.splitlines(keepends=True), block.splitlines(keepends=True)
    out = old
    for name, node in sorted(((k, v) for k, v in nn.items() if k in on), key=lambda kv: -on[kv[0]].lineno):
        o = on[name]
        start = (o.decorator_list[0].lineno if o.decorator_list else o.lineno) - 1
        ns = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
        cur = out.splitlines(keepends=True)
        new_src = "".join(blines[ns:node.end_lineno])
        if not new_src.endswith("\n"):
            new_src += "\n"
        out = "".join(cur[:start]) + new_src + "".join(cur[o.end_lineno:])
    extra_new = [k for k in nn if k not in on]
    if extra_new:                      # 새 함수는 끝에 붙인다
        for k in extra_new:
            node = nn[k]
            ns = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
            out = out.rstrip("\n") + "\n\n\n" + "".join(blines[ns:node.end_lineno]).rstrip("\n") + "\n"
    return out


def term_rows():
    if UI.on:
        return UI.rows_free()
    return shutil.get_terminal_size((100, 40)).lines


def term_cols():
    return shutil.get_terminal_size((100, 40)).columns


LOG_DIR = HOME / ".extra" / "logs"
STEP = [0]     # 단계 번호 (생각·검증마다 하나씩)


class FullLog:
    """작업창에는 흐름만 짧게, 여기에는 전부 (생각 전체, 명령 출력 전체, 파일 내용). 다른 터미널에서 extra log 로 실시간으로 본다."""
    def __init__(self):
        self.f = None

    def open(self, where):
        return          # (사용자 11/15: log 를 없앴다)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.f = open(LOG_DIR / (J.jobs_root(where).name + ".log"), "a", buffering=1)
            self.f.write(f"\n{B}══════ {time.strftime('%F %T')} · {str(where).replace(str(HOME), '~')} ══════{R}\n")
        except OSError:
            self.f = None

    def line(self, text):
        if self.f:
            try:
                self.f.write(text + R + "\n")
            except (OSError, ValueError):
                pass

    def detail(self, title, body, color=None):
        """작업창에는 안 나오는 자세한 내용."""
        if self.f and body:
            self.line(f"{D}  ┄┄ {title} ┄┄{R}")
            for l in str(body).split("\n"):
                self.line(f"{D if color is None else color}  {l}")


FLOG = FullLog()


def open_log_viewer(args):
    """extra log: 가장 최근 작업 기록을 따로 연다 (less, 실시간 따라가기). 이 폴더의 기록이 있으면 그것."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    here = LOG_DIR / (J.jobs_root(Path.cwd()).name + ".log")
    logs = sorted(LOG_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    target = here if here.is_file() and here.stat().st_size and "--latest" not in args else (logs[0] if logs else None)
    if not target:
        print("No extra log yet. Start extra in a folder first, then run extra log in another terminal."); return
    print(f"{P}extra log{R} {D}{target}{R}")
    print(f"{D}following live · Ctrl-C to stop following and scroll · / to search · F to follow again · q to quit{R}")
    time.sleep(0.6)
    os.execvp("less", ["less", "-R", "+F", str(target)])


FOLDS = []   # 접어 둔 것들: (제목, 전체 내용). Ctrl-O = 마지막 것 펼치기, /show N = N 번 펼치기


def fold(title, full):
    """(접기는 없앴다, 사용자 11/15) 예전 호출을 위해 빈 글을 돌려준다."""
    return ""


def show_fold(n=None):   # (펼치기는 없앴다 — 전체 내용은 extra log)
    if not FOLDS:
        print(f"{D}nothing folded yet{R}"); return
    i = len(FOLDS) if n is None else max(1, min(len(FOLDS), n))
    title, full = FOLDS[i - 1]
    print(f"{P}▾ #{i} {title}{R}")
    for line in full.split("\n"):
        print("  " + line)
    print(f"{P}▴ end of #{i}{R}")


def live():
    return sys.stdout.isatty()


class LiveBox:
    """흐르는 동안 마지막 k 줄만 보여 주는 칸 (화면을 넘지 않으니 끝나면 깨끗이 접을 수 있다). 터미널이 아니면 그냥 흘려 쓴다."""
    def __init__(self, k=6, color=None, prefix="  "):
        self.k, self.color, self.prefix = k, color or D, prefix
        self.text, self.drawn, self.last = "", 0, 0.0

    head = ""   # 칸 맨 위에 붙일 머리줄 (생각 중… 같은 것)

    def add(self, t, force=False):
        self.text += t
        if not live():
            sys.stdout.write(t); sys.stdout.flush(); return
        now = time.time()
        if force or now - self.last > 0.06:
            self._draw(); self.last = now

    def _draw(self):
        if UI.on:   # Claude Code 방식: 아래 살아 있는 부분에만 그린다
            tail = self.text.replace("\t", "    ").split("\n")[-self.k:]
            UI.set_box(([self.head] if self.head else []) + [f"{self.color}{self.prefix}{R}{l}{R}" for l in tail])
            return
        cols = max(20, term_cols() - len(self.prefix) - 2)
        tail = self.text.replace("\t", "    ").split("\n")[-self.k:]
        out = f"\x1b[{self.drawn}F\x1b[J" if self.drawn else ""
        from extra_input import cut as _cut
        out += "".join(f"{self.color}{self.prefix}{R}{_cut(l, cols)}{R}\n" for l in tail)
        sys.stdout.write(out); sys.stdout.flush()
        self.drawn = len(tail)

    def close(self):
        if UI.on:
            UI.set_box([]); return
        if live() and self.drawn:
            sys.stdout.write(f"\x1b[{self.drawn}F\x1b[J"); sys.stdout.flush()
        elif not live() and self.text and not self.text.endswith("\n"):
            sys.stdout.write("\n")
        self.drawn = 0


STREAMED = set()   # 답장 안의 코드 블록으로 이미 흘려 보여 준 파일 (저장할 때 다시 보여 주지 않는다)


# 코드에 단어마다 색 (사용자 11/15). pygments 로, 파일 확장자나 코드 모양으로 언어를 고른다
_LEXERS = {}


def hl(line, name=""):
    """코드 한 줄에 색을 입힌다. 실패하면 그대로."""
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import get_lexer_for_filename, guess_lexer, TextLexer
        key = Path(name).suffix.lower() if name else ""
        lx = _LEXERS.get(key)
        if lx is None:
            try:
                lx = get_lexer_for_filename(name, stripnl=False, ensurenl=False) if name else None
            except Exception:
                lx = None
            if lx is None:
                try:
                    lx = guess_lexer(line, stripnl=False, ensurenl=False)
                except Exception:
                    lx = TextLexer()
            if name:
                _LEXERS[key] = lx
        if "fmt" not in _LEXERS:
            _LEXERS["fmt"] = Terminal256Formatter(style="monokai")
        return highlight(line, lx, _LEXERS["fmt"]).rstrip("\n")
    except Exception:
        return line


def code_lang(lang_tag, file=None):
    """``` 뒤의 언어 이름을 파일 이름처럼 바꿔 hl 에 넘긴다."""
    if file:
        return file
    ext = LANG_EXT.get((lang_tag or "").strip().lower(), "")
    return ("x" + ext) if ext else ("x.sh" if (lang_tag or "").strip().lower() in ("bash", "sh", "zsh", "shell") else "")


CODE_LINE = re.compile(r"^\s*(async\s|function\b|const\s|let\s|var\s|return\b|if\s*\(|else\b|for\s*\(|while\s*\(|try\s*\{|catch\b|"
                       r"import\s|export\s|def\s|class\s|from\s\S+\simport|\}|\{|<\/?[a-zA-Z][\w-]*[\s>]|//|/\*|\*/|\$\(|document\.|console\.|"
                       r"[A-Za-z_$][\w$.]*\s*=\s*.+;\s*$|.*[;{]\s*$)")


class AnswerStream:
    """답장 글을 줄 단위로 보여 준다. 코드 블록은 화면에 통째로 찍지 않고 작은 칸에서 흐르게 한 뒤 접는다 (사용자 11/14).
    'FILE: 경로' 줄 다음의 코드 블록이면 그 파일을 쓰는 것으로 표시한다."""
    def __init__(self):
        self.buf, self.code, self.file, self.box, self.lines, self.lang = "", False, None, None, [], ""

    def feed(self, t):
        self.buf += t
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._line(line)

    def _line(self, line):
        st = line.strip()
        if self.code == "bare":            # ``` 없이 시작한 코드 (11/15: 표시 없는 코드가 화면에 그대로 찍혔다)
            if st and not CODE_LINE.search(line) and not line.startswith((" ", "\t")):
                self._close_code()             # 코드가 끝나고 글이 나왔다
            else:
                self.lines.append(line)
                self.box.add(f"{D}{len(self.lines):>4}{R}  {hl(line, self.lang)}\n")
                return
        if not self.code and st and CODE_LINE.search(line) and not st.startswith(("```", "FILE:", "**FILE")):
            self._open_code(bare=True)
            self.lines.append(line)
            self.box.add(f"{D}{len(self.lines):>4}{R}  {hl(line, self.lang)}\n")
            return
        if not self.code:
            m = re.match(r"\**FILE:\**\s*`?([^\s`*]+)`?", st)
            if m:
                self.file = m.group(1); return
            if st.startswith("```"):
                self.lang = code_lang(st[3:], self.file)
                self._open_code()
                return
            sys.stdout.write(line + "\n"); sys.stdout.flush()
            return
        if st.startswith("```"):
            self._close_code(); return
        self.lines.append(line)
        self.box.add(f"{D}{len(self.lines):>4}{R}  {hl(line, self.lang)}\n")

    def _open_code(self, bare=False):
        if bare:
            self.lang = code_lang("", self.file) or "x.js"
        self.code, self.lines = ("bare" if bare else True), []
        label = f"{P}✎ writing {self.file}{R}" if self.file else f"{D}code{R}"
        self.box = LiveBox(8, D, "  ")
        if UI.on:
            self.box.head = label
            UI.set_box([label])
        else:
            print(label)

    def _close_code(self):
        self.box.close()
        code = "\n".join(self.lines)
        FLOG.detail(self.file or "code in the reply", "\n".join(hl(l, self.lang) for l in self.lines), color="")
        name = self.file or "code block"
        tag = fold(name, code)
        print(f"{P}✎{R} {W}{name}{R} {D}· {len(self.lines)} lines{R} {tag}")
        if self.file:
            STREAMED.add(self.file)
        self.code, self.file, self.box = False, None, None

    def close(self):
        if self.buf:                    # 마지막 줄 (줄바꿈 없이 끝난 ``` 포함) 도 줄로 처리한다
            rest, self.buf = self.buf, ""
            self._line(rest)
        if self.code:
            self._close_code()


class Ticker:
    """모델이 도구 호출을 만드는 동안(글이 안 흘러오는 동안) 일하고 있다는 걸 보여 준다."""
    def __init__(self, label):
        self.label, self.on, self.t0 = label, live(), time.time()
        if self.on:
            import threading
            self.th = threading.Thread(target=self._run, daemon=True); self.th.start()

    def _run(self):
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while self.on:
            line = f"{P}{frames[i % 10]}{R} {D}{self.label} {time.time() - self.t0:4.0f}s{R}"
            if UI.on:
                UI.set_status(line)
            else:
                sys.stdout.write(f"\r{line}\x1b[K"); sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def stop(self):
        if self.on:
            self.on = False
            self.th.join(0.5)
            if UI.on:
                UI.set_status("")
            else:
                sys.stdout.write("\r\x1b[2K"); sys.stdout.flush()


def shown_lines(text):
    """화면에 남길 생각: Plan 과 Act 의 첫 줄씩. 둘 다 없으면 Result / Check 첫 줄."""
    keys = list(app.KEY_RE.finditer(text))
    parts = {}
    for i, m in enumerate(keys):
        end = keys[i + 1].start() if i + 1 < len(keys) else len(text)
        body = next((l.strip() for l in text[m.end():end].splitlines() if l.strip()), "")
        parts.setdefault(m.group(1), body)
    out = [f"{k}: {parts[k]}" for k in ("Plan", "Act") if parts.get(k)]
    if not out:
        out = [f"{k}: {parts[k]}" for k in ("Result", "Check") if parts.get(k)][:1]
    return out or [text.strip().splitlines()[0][:200] if text.strip() else ""]


class ThinkView:
    """생각은 쓰는 동안 보이고, 다 쓰면 접혀서 단계 번호와 Plan / Act 한 줄씩만 남는다 (사용자 11/15). 펼치기는 없다."""
    def __init__(self, label):
        self.label, self.text, self.raw = label, "", ""
        self.review = label.startswith("Verif")
        STEP[0] += 1
        self.n = STEP[0]
        self.word = "Verifying" if self.review else label
        self.color = O if self.review else P
        self.head = f"{self.color}◆ {self.word}…{R}"
        self.box = LiveBox(10, D, "  ")
        self.box.head = self.head
        self._first = False
        self._spin_on = live()
        if UI.on:
            UI.set_box([self.head])
        else:
            sys.stdout.write(self.head + "\n"); sys.stdout.flush()
        if self._spin_on:          # 첫 토큰 전까지 머리글을 돌린다: "◆ ⠹ Thinking… 8s"
            import threading
            self._t0 = time.time()
            self._th = threading.Thread(target=self._spin, daemon=True); self._th.start()

    def _spin(self):
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while self._spin_on and not self._first:
            el = time.time() - self._t0
            head = f"{self.color}◆ {frames[i % 10]} {self.word}…{R} {D}{el:0.0f}s{R}"
            self.head = head; self.box.head = head
            if UI.on:
                UI.set_box([head])
                UI.set_status(f"{self.color}{frames[i % 10]}{R} {D}{self.word.lower()}… {el:0.0f}s{R}")   # 상태줄에도 (확실히 보이게)
            else:
                sys.stdout.write(f"\r{head}\x1b[K"); sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def _stop_spin(self):
        if self._spin_on and not self._first:
            self._first = True
            self._spin_on = False
            if UI.on:
                UI.set_status("")
            try: self._th.join(0.3)
            except Exception: pass
            self.head = f"{self.color}◆ {self.word}…{R}"; self.box.head = self.head
            if not UI.on:
                sys.stdout.write("\r\x1b[K" + self.head + "\n"); sys.stdout.flush()

    def add(self, t):
        self._stop_spin()
        self.raw += t
        clean = re.sub(r"</?t?h?i?n?k?$", "", re.sub(r"</?think>", "", self.raw)).lstrip()   # 조각으로 와도 태그를 지운다
        new = clean[len(self.text):] if clean.startswith(self.text) else None
        self.text = clean
        if new is None:          # 태그가 지워지며 앞부분이 바뀌었다: 다시 그린다
            self.box.text = ""
            new = clean
        if new:
            self.box.add(new)

    def looping(self):
        """같은 줄만 되풀이하는 반복에 빠졌나 (11/14: '<think>' 만 수십 줄)."""
        lines = [l.strip() for l in self.raw.strip().split("\n")[-8:]]
        return len(lines) >= 6 and len(set(lines)) <= 2

    def close(self):
        if self._spin_on and UI.on:
            UI.set_status("")
        self._spin_on = False
        self.box.close()
        lines = shown_lines(self.text)
        if not lines or not self.text.strip():
            return
        mark = f"{G}✓{R}" if self.review else f"{P}◆{R}"
        word = f"{G}verified{R} " if self.review else ""            # 검증 단계는 '검증했다' 가 보이게 (11/15)
        cols = max(20, term_cols() - 18)
        for k, line in enumerate(lines):
            line = line if len(line) <= cols else line[:cols - 1] + "…"
            head = f"{mark} {D}{self.n:>2}{R} {word}" if k == 0 else ("     " + " " * (9 if self.review else 0))
            sys.stdout.write(head + color_thought(line) + "\n")
        sys.stdout.flush()


def UI_print(text):
    """작업창에만 (전체 기록에는 ThinkView 가 따로 쓴다)."""
    if UI.on:
        on, UI.on_line = UI.on_line, None
        sys.stdout.write(text + "\n")
        UI.on_line = on
    else:
        sys.stdout.write(text + "\n")
    sys.stdout.flush()


def show_tool(name, args):
    a = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items() if k not in ("content", "new", "old")) or ""
    print(f"{P}→ {name}{R} {D}{a}{R}")


BAD_RE = re.compile(r"(fail|error|traceback|exception|exit code [1-9]|said no|not allowed|denied|no such|✗)", re.I)
OK_RE = re.compile(r"(\bpassed\b|\bok\b|exit code 0|saved |edited |✓|success)", re.I)


def show_result(text, name=""):
    text = str(text)
    lines = text.splitlines() or [""]
    bad = bool(BAD_RE.search(text[:400]))
    if name == "run_command":          # 출력은 실행하면서 이미 보여 주고 접었다: 결과만
        print(f"{E}  ✗ error{R}" if bad else f"{G}  ✓ done{R}")
        return
    if name in ("write_file", "edit_file") and not bad:
        return                         # 파일 쓰기는 쓰는 동안 보여 주고 요약했다
    keep = 4
    print(f"{E}  ✗ error{R}" if bad else f"{G}  ✓ done{R}")   # 실행 결과: 오류는 빨강, 된 것은 초록
    for l in lines[:keep]:
        c = E if BAD_RE.search(l) else G if OK_RE.search(l) else D
        print(f"{c}  ⎿ {pad(l, term_cols() - 6).rstrip()}{R}")
    if len(lines) > keep:
        print(f"{D}  ⎿ … {len(lines) - keep} more lines{R}")
        FLOG.detail(f"full result of {name}", "\n".join(lines[keep:]))


# ---------------- 한 턴 ----------------
CLOG = HOME / ".extra" / "cli_log.jsonl"   # 프로그램 폴더가 아니라 사용자 폴더에 (베타)


def clog(row):
    """터미널에서 있었던 일을 남긴다 (문제가 생기면 보고 고칠 수 있게)."""
    try:
        CLOG.parent.mkdir(parents=True, exist_ok=True)
        if CLOG.exists() and CLOG.stat().st_size > 50_000_000:       # 너무 커지면 오래된 기록을 한 벌만 남긴다
            CLOG.replace(CLOG.with_suffix(".old.jsonl"))
        with open(CLOG, "a") as f:
            f.write(json.dumps({"t": time.strftime("%F %T"), "cwd": str(CWD), **row}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    if JOB_DIR:
        line = ""
        if "tool" in row:
            first = str(row.get("result", "")).strip().split("\n")[0][:120]
            line = f"- {row['tool']} {json.dumps(row.get('args', {}), ensure_ascii=False)[:160]} → {first}"
        elif "review" in row or "think" in row:
            got = re.findall(r"^\s*\**(Failed|Act|Check)\**\s*:\s*(.+)$", row.get("review") or row.get("think") or "", re.M)
            line = "\n".join(f"  {k}: {v[:200]}" for k, v in got)
        if line:
            with open(JOB_DIR / "progress.md", "a") as f:
                f.write(line + "\n")


class Stop(Exception):
    pass


def project_overview(limit=120):
    """작업 폴더 전체를 한눈에: 파일 구조와 README 앞부분 (첫 질문에 붙여서 모델이 프로젝트 전체를 알고 시작하게).
    너무 크면 로컬 모델이 느려지므로 크기를 제한한다 (11/15: 홈에서 시작하니 ~3700 토큰이 붙어 멈춘 듯 느려졌다)."""
    if CWD == HOME:   # 홈 폴더 전체를 훑지 않는다 (느림·프라이버시). 프로젝트 폴더에서 열라고만.
        return "Working in the home folder (no project scan). Open a project folder for a full overview, e.g. a folder under ~/Documents."
    rows = []
    for base, dirs, files in os.walk(CWD):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
        depth = len(Path(base).relative_to(CWD).parts)
        if depth > 3:
            dirs[:] = []
            continue
        for f in sorted(files):
            if not f.startswith("."):
                rows.append(str((Path(base) / f).relative_to(CWD)))
        if len(rows) >= limit:
            break
    out = "Project folder files (first %d):\n" % min(limit, len(rows)) + "\n".join(rows[:limit]) if rows else "The project folder is empty."
    out = out[:2500]   # 파일 목록은 여기까지 (프롬프트를 작게 유지)
    for name in ("README.md", "readme.md", "CLAUDE.md", ".extra/handoff.md"):
        f = CWD / name
        if f.is_file():
            out += f"\n\n{name} (start):\n" + f.read_text(errors="replace")[:1200]
    return out[:4500]   # overview 전체 상한 (~1200 토큰)


def locate_errors(output):
    """실패한 명령의 출력에서 오류 메시지를 뽑아, 그 글이 프로젝트 코드의 어디에서 나오는지 찾아 준다 (앞뒤 3 줄과 함께).
    (11/15: 콘솔에 'Status element not found' 가 찍혔는데 그 줄을 찾아보지 않고 엉뚱한 곳만 고쳤다)"""
    cands = []
    for line in str(output).splitlines():
        m = re.search(r"(?:\b(?:error|Error|ERROR|TypeError|ReferenceError|SyntaxError|warning)\b[:\s]+)(.{8,120})$", line)
        if m:
            msg = m.group(1).strip().strip("'\"")
            msg = re.split(r"\s+at\s+|\s\(", msg)[0].strip()
            if len(msg) >= 8 and msg not in cands:
                cands.append(msg)
    found = []
    files = [f for f in CWD.rglob("*") if f.is_file() and f.suffix in (".js", ".ts", ".jsx", ".tsx", ".py", ".html", ".css", ".mjs")
             and not any(part in SKIP or part.startswith(".") for part in f.relative_to(CWD).parts)][:200]
    for msg in cands[:4]:
        probe = msg[:60]
        for f in files:
            try:
                lines = f.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for i, l in enumerate(lines):
                if probe in l:
                    lo = max(0, i - 3)
                    for k in range(i, max(-1, i - 25), -1):     # 그 줄이 속한 함수의 첫 줄부터 보여 준다
                        if re.match(r"\s*(async\s+)?function\b|\s*(const|let|var)\s+\w+\s*=\s*(async\s*)?(\(|function)|\s*def\s|\s*class\s", lines[k]):
                            lo = k
                            break
                    hi = min(len(lines), i + 4)
                    ctx = "\n".join(f"{n + 1:>5}  {lines[n]}" for n in range(lo, hi))
                    # 이 부분에서 부르는 함수가 같은 파일에 짧게 정의돼 있으면 그 정의도 (예: const $ = (id) => document.getElementById(id))
                    called = set(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", "\n".join(lines[lo:hi])))
                    defs = []
                    for n, dl in enumerate(lines):
                        if lo <= n < hi:
                            continue
                        dm = re.match(r"\s*(?:const|let|var|function|def)\s+([A-Za-z_$][\w$]*)", dl)
                        if dm and dm.group(1) in called:
                            defs.append(f"{n + 1:>5}  {dl.strip()[:160]}")
                    if defs:
                        ctx += "\n  (defined elsewhere in this file:)\n" + "\n".join(defs[:4])
                    found.append(f"'{probe}' comes from {f.relative_to(CWD)}:{i + 1}\n{ctx}")
                    break
            if len(found) >= 3:
                break
    if not found:
        return ""
    return ("\n\n[Where these error messages come from in your code — read these lines and the code they call to find the cause:\n"
            + "\n---\n".join(found) + "]")


def keep_task_view(msgs, state):
    """모델에게 보낼 대화: 작업 내용(첫 사용자 말)은 항상 맨 앞에 고정하고, 나머지는 최근 것부터 기억 창에 맞춘다.
    오래된 단계가 빠졌으면 지금까지의 진행(바꾼 파일, 마지막 확인)을 한 줄로 붙인다.
    (11/15: 기억 창이 넘치면 작업 내용까지 버려져, 긴 작업 끝에 할 일을 잊고 list_dir 만 되풀이했다)"""
    clean = [{k: v for k, v in m.items() if k not in ("full",)} for m in msgs]
    first = next((i for i, m in enumerate(clean) if m["role"] == "user"), None)
    if first is None:
        return app.fit_view(clean)
    task, rest = clean[first], clean[first + 1:]
    # 이전 턴은 Plan/Act 만 읽는다 (사용자 11/16: 뒤로 갈수록 느려짐). 생각은 이미 Plan/Act 로 압축돼 있고,
    # 큰 도구 결과(파일·명령 출력)는 가장 최근 것 하나만 남기고 이전 것은 버린다 — 직전 결과엔 반응해야 하므로 그것만 유지.
    last_tool = max((i for i, m in enumerate(rest) if m["role"] == "tool"), default=-1)
    rest = [m for i, m in enumerate(rest) if m["role"] != "tool" or i == last_tool]
    budget = app.TOKEN_BUDGET - app.est_tokens(task.get("content", "")) - 200
    keep = app.fit_view.__wrapped__(rest, budget) if hasattr(app.fit_view, "__wrapped__") else _fit(rest, budget)
    if len(keep) < len(rest):
        files = ", ".join(sorted(x for x in state.get("files", set()) if x)) or "none yet"
        cmd, out = state.get("last_check") or state.get("last_run") or ("", "")
        note = (f"[Earlier steps were left out to save memory. Progress so far — files you changed: {files}"
                + (f"; last check: `{cmd}` → {out}" if cmd else "") + ". Keep working on the task above.]")
        task = dict(task, content=task["content"] + "\n\n" + note)
    return [task] + keep


def _fit(view, budget):
    """최근 것부터 budget 토큰 안에 들어가는 만큼 (긴 도구 결과는 자른다). 앞이 도구 결과로 시작하지 않게."""
    out, used = [], 0
    for m in reversed(view):
        m = dict(m)
        if m["role"] == "tool" and len(str(m.get("content", ""))) > app.TOOL_KEEP:
            c = str(m["content"]); m["content"] = c[:app.TOOL_KEEP] + f"\n... ({len(c) - app.TOOL_KEEP} more characters cut)"
        t = app.est_tokens(m.get("content", ""))
        if out and used + t > budget:
            break
        out.append(m); used += t
    out.reverse()
    while out and out[0]["role"] == "tool":      # 짝을 잃은 도구 결과로 시작하지 않게
        out.pop(0)
    return out


CLARIFY_SYS = (
    "Decide whether to ask the user a clarifying question before acting. Reply with ONE word on the first line: CLEAR or ASK.\n\n"
    "Reply CLEAR (do NOT ask) for almost everything, including:\n"
    "- greetings, thanks, small talk, or anything conversational (hi, hello, 안녕, how are you)\n"
    "- a question you can simply answer (what can you do, 그냥 질문이야, explain X)\n"
    "- any request where you can make a sensible assumption and start, even if some details are open\n\n"
    "Reply ASK ONLY when ALL of these are true:\n"
    "1) the user is asking you to BUILD, MAKE, WRITE, or DO something concrete, AND\n"
    "2) a key detail is missing that would send the work in completely different directions, AND\n"
    "3) you genuinely cannot pick a reasonable default yourself.\n"
    "When unsure, choose CLEAR. It is better to start and adjust than to interrogate the user.\n\n"
    "When (and only when) you ASK, use EXACTLY this format after the ASK line:\n"
    "ASK\n"
    "<one short question in the user's language>\n"
    "- <a concrete choice>\n"
    "- <a concrete choice>\n"
    "Each option must be a thing they can pick, not another question. Give 2 to 4 options.\n\n"
    "Examples:\n"
    "\"안녕\" -> CLEAR.  \"그냥 질문이야\" -> CLEAR.  \"what can you do?\" -> CLEAR.  \"fix the failing test\" -> CLEAR.\n"
    "\"add dark mode to styles.css\" -> CLEAR.  \"make me an app\" -> ASK (what kind).  \"build a game\" -> ASK (which game).")


# 만들기/작업 요청처럼 보이는 말에만 clarify 모델 호출 (인사·잡담·단순 질문은 호출 없이 바로 → 느려지지 않게)
BUILD_INTENT = re.compile(
    r"\b(make|build|create|write|add|implement|generate|design|set ?up|develop|code|refactor|convert|turn into|"
    r"fix|debug|add a|build a|make a|create a)\b|게임|앱|사이트|웹|프로그램|스크립트|"
    r"만들|짜 ?줘|짜줘|구현|추가|생성|개발|설계|고쳐|고치|바꿔|디자인", re.I)


def ask_intent(user_text):
    """새 작업을 받으면 먼저 '무엇을 원하는가'를 생각하고, 구체적이지 않으면 선택지+직접 입력으로 묻는다 (사용자 11/15).
    돌아오는 값: 사용자가 고르거나 적은 보충 설명(문자열), 또는 None(물을 필요 없음 / 물을 수 없음).
    인사·잡담·단순 질문에는 비싼 모델 호출을 하지 않는다 (11/16: '안녕' 에 20초 걸렸다)."""
    if HEADLESS or not sys.stdin.isatty() or len(user_text) > 280:
        return None   # 백그라운드이거나, 이미 충분히 긴(구체적인) 요청이면 묻지 않는다
    if not BUILD_INTENT.search(user_text):
        return None   # 만들기/작업 요청이 아니면 (인사·질문 등) 그냥 평소대로 답한다
    tv = ThinkView("Understanding")   # 머리글 스피너만 돈다 (내용은 흘리지 않는다 → 끝에 사라지지 않게)
    out = ""
    try:
        for chunk in app.ollama_stream([{"role": "system", "content": CLARIFY_SYS}, {"role": "user", "content": user_text}],
                                       tools=False, stop=None, temp=0.0):
            out += (chunk.get("message") or {}).get("content") or ""
            low = out.strip().upper()
            if low.startswith("CLEAR") or low.startswith("CLEA"):   # 물을 필요 없음 → 더 생성하지 않고 끊는다
                out = "CLEAR"; break
            if len(out) > 400:                                      # 질문은 이 정도면 충분, 폭주 방지
                break
    except Exception:
        tv.close(); return None
    tv.close()   # 아무 글도 add 하지 않았으니 깨끗이 사라지고, 질문이 있으면 아래에 따로 보여 준다
    out = re.sub(r"</?think>", "", out).strip()
    if not out or out.split()[0].upper().startswith("CLEAR"):
        return None
    lines = [l.rstrip() for l in out.splitlines() if l.strip()]
    if lines and lines[0].upper().startswith("ASK"):
        lines = lines[1:]
    if not lines:
        return None
    question = lines[0].lstrip("#*- ").strip()
    options = [l.lstrip("-*•0123456789. ").strip() for l in lines[1:] if l.lstrip().startswith(("-", "*", "•")) or re.match(r"\s*\d+[.)]", l)]
    if not options:
        return None
    print(f"\n {P}◆{R} {W}{question}{R}")
    for i, opt in enumerate(options[:4], 1):
        print(f" {W}{i}{R}  {opt}")
    print(f" {D}0  something else — type it. (Enter = just go ahead){R}")
    try:
        a = read_answer(f"{P} › {R}").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return None
    if not a:
        return None   # 그냥 진행
    if a.isdigit():
        n = int(a)
        if 1 <= n <= len(options[:4]):
            return options[n - 1]
        return None   # 0 인데 아무것도 안 적음 → 진행
    return a   # 직접 입력한 내용


def one_turn(msgs, user_text):
    sys_msg = {"role": "system", "content": system_prefix() + J.prompt_block(PROMPT_ROOT)}
    orig_text = user_text
    if not msgs:   # 새 작업의 첫 말: 먼저 무엇을 원하는지 이해하고(구체적이지 않으면 질문), 폴더 전체를 같이 준다 + 맞는 스킬
        extra_ask = ask_intent(orig_text)
        if extra_ask:
            user_text = user_text + "\n\n[The user clarified what they want: " + extra_ask + "]"
        if CWD != HOME:   # 홈에서 시작 = 아직 뭘 할지 안 정한 것 → 폴더를 훑지 않는다 (사용자 11/15)
            user_text = user_text + "\n\n[" + project_overview() + "]"
        for name in pick_skills(orig_text):
            print(f"{P}✦ using skill:{R} {W}{name}{R}")
            user_text += "\n\n" + skill_text(name)
            clog({"skill": name})
    msgs.append({"role": "user", "content": user_text})
    clog({"user": orig_text})
    if len([m for m in msgs if m["role"] == "user"]) == 1:   # 새 작업: 지금 있는 시험 파일을 보호
        protect_tests(orig_text)
    nud = {"empty": 0, "giveup": 0, "verify": 0, "askuser": 0, "summary": 0, "failing": 0}
    seen = {}    # 같은 도구 호출이 몇 번 있었나 (11/15: 같은 open 명령을 8 번 되풀이했다)
    state = {"changed": False, "worked": False}   # 마지막으로 돌려 본 뒤에 파일을 바꿨나 / 이번 일에서 도구를 썼나
    for _ in range(200):
        if DEADLINE and time.time() > DEADLINE:
            raise Stop("time is up")
        said = UI.take_messages() if UI.on else []
        if said:   # 사용자 11/14: 작업 중에 바꾸고 싶은 게 있으면 바로 입력
            msgs.append({"role": "user", "content": "[The user adds while you work: " + " / ".join(said) +
                         "\nTake this into account from now on. If it changes the task, adjust your plan. If it asks you to stop, stop and give a short summary.]"})
            clog({"user_mid": said})
        review = msgs[-1]["role"] == "tool"
        thought = ""
        if review and SETTINGS.get("review") == "off":   # 검토 꺼짐: 결과를 보고 바로 다음 행동으로
            attempts = 0
        else:
            attempts = 3
        for attempt in range(attempts):
            view = keep_task_view(msgs, state)
            ask_ = REVIEW_ASK if review else think_ask()
            ask_ = f"[Now: {time.strftime('%H:%M')}] " + ask_
            if view and view[-1]["role"] in ("user", "tool"):
                view[-1] = dict(view[-1], content=view[-1]["content"] + "\n\n" + ask_)
            else:
                view.append({"role": "user", "content": ask_})
            if attempt:
                view = view[len(view) // 2:] if len(view) > 4 else view
                while len(view) > 1 and view[0]["role"] != "user":
                    view.pop(0)
            tv = ThinkView("Verifying" if review else "Thinking")
            for chunk in app.ollama_stream([sys_msg] + view, tools=False, stop=["</think>"], temp=0.3 + 0.2 * attempt):
                t = (chunk.get("message") or {}).get("content") or ""
                if t:
                    tv.add(t)
                    if tv.looping():
                        tv.text = ""   # 반복에 빠졌다 → 버리고 다시 (온도를 올려서)
                        break
            tv.close()
            thought = tv.text.strip()
            if thought:
                break
            print(f"{D}  (empty thought — retrying){R}")
        if attempts:
            clog({"think" if not review else "review": thought[:1500]})
        if thought:
            msgs.append({"role": "assistant", "content": f"<think>\n{app.compact_thought(thought)}\n</think>", "full": thought})
        out = {"tv": None, "ans": False}

        def show(ev):
            k = ev["type"]
            if k == "think_start":
                out["tv"] = ThinkView("Thinking")
            elif k == "think" and out["tv"]:
                out["tv"].add(ev["text"])
            elif k == "answer_start":
                if out["tv"]:
                    out["tv"].close(); out["tv"] = None
                sys.stdout.write("\n"); out["ans"] = True
                out["as"] = AnswerStream()
            elif k == "answer":
                if not out.get("as"):
                    out["as"] = AnswerStream()
                out["as"].feed(ev["text"])
        # 행동: 생각만 하고 도구도 답도 없으면, 다시 생각하지 말고 바로 행동만 시킨다 (최대 3 번)
        nxt_paste = ["", False]   # [글로 쓴 코드, 다음 시도에서 저장시키기]
        # 검증에서 끝(Check)을 선언했으면: 도구 없이 마지막 요약만 (11/15: Check 뒤에도 서버·kill·check 를 되풀이했다)
        checked = state.get("last_check_full", "")   # 검사가 실제로 통과했나 (11/15: 모델이 PASS 뒤에도 안 멈췄다)
        passed = bool(state.get("last_check")) and bool(re.search(r"\bPASS\b|passed|exit code 0", checked, re.I)) \
            and not re.search(r"\bFAIL\b|exit code [1-9]", checked)
        done_now = bool(review and (re.search(r"^\s*\**\s*Check\s*\**\s*:", thought or "", re.M)
                    or (passed and re.search(r"\b(pass|passed|done|complete|completed|success|succeed|works|working|finish)\b", thought or "", re.I))))
        for act_try in range(4):
            ask_act = ACT_ASK if act_try == 0 else ACT_STRICT
            if done_now:
                ask_act = FINISH_ASK
            if nxt_paste[1]:   # 방금 코드를 글로만 썼거나 말만 했다: 그 코드를 보여 주고 도구로 저장하게 한다
                ask_act = ACT_PASTE + ("\nThe code you wrote:\n" + nxt_paste[0] if nxt_paste[0] else "")
                nxt_paste[1] = False
            msgs.append({"role": "user", "content": ask_act})
            content, calls = "", []
            view = keep_task_view(msgs, state)
            sp = app.ActSplitter(show)
            tick = Ticker("working on the next action…")
            for chunk in app.ollama_stream([sys_msg] + view, tools=not done_now, tool_list=TOOLS):
                m = chunk.get("message") or {}
                t = m.get("content") or ""
                if t or m.get("tool_calls"):
                    tick.stop()
                if t:
                    content += t
                    sp.feed(t)
                calls += m.get("tool_calls") or []
                if not calls and (len(sp.thoughts) > 1 or sum(len(x) for x in sp.thoughts) > 400):
                    break   # 행동 대신 생각을 쪼개 쓰는 중 → 끊는다 (Ollama 는 연결이 끊기면 생성을 멈춘다)
            tick.stop()
            if out.get("as"):
                out["as"].close(); out["as"] = None
            if not calls and not done_now:
                tc, rest = text_calls(app.THINK_RE.sub("", content))
                if tc:
                    calls, content = tc, rest
                    clog({"text_calls": [c["function"]["name"] for c in tc]})
            if not calls and not done_now:
                bc = block_calls(app.THINK_RE.sub("", content), thought)
                if bc:
                    calls = bc
                    clog({"block_calls": [c["function"]["arguments"].get("path") or c["function"]["arguments"].get("command") for c in bc]})
            if out["tv"]:
                out["tv"].close(); out["tv"] = None
            for th in sp.thoughts:
                if th.strip():
                    msgs.insert(len(msgs) - 1, {"role": "assistant", "content": f"<think>\n{app.compact_thought(th.strip())}\n</think>", "full": th.strip()})
            msgs.pop(len(msgs) - 1 - next(i for i, x in enumerate(reversed(msgs)) if x.get("content") == ask_act))  # 행동 지시는 기록에서 뺀다
            answer = app.THINK_RE.sub("", content).strip()
            clog({"act_try": act_try + 1, "answer": answer[:300], "calls": calls, "thoughts": [x[:300] for x in sp.thoughts]})
            # 코드를 글에 붙여 넣고 도구는 안 부른 경우 (11/14 공동 작업 시험: Act 는 edit_file 인데 코드만 답에 써서 테스트가 계속 같은 곳에서 실패)
            announced = bool(re.match(r"\s*(I will|I'll|I am going to|Let me|Now I|Next,? I)\b", answer, re.I))   # "이제 저장하겠습니다" 말만 하고 끝
            long_code = any(len(b.split("\n")) > 8 for b in re.findall(r"```[^\n]*\n(.*?)(?:\n```|$)", answer, re.S))
            # 일이 아직 안 끝났는데(생각에 Check 가 없는데) 도구를 안 불렀으면 끝난 게 아니다 (11/15: "I will first use web_fetch…" 라고만 하고 멈췄다).
            # 단, 생각의 Act 가 사용자에게 답하는 것이면(질문에 답하기) 그대로 둔다.
            finished = bool(re.search(r"^\s*\**\s*Check\s*\**\s*:", thought or "", re.M))
            act_line = (re.findall(r"^\s*\**\s*Act\s*\**\s*:?\s*(.+)$", thought or "", re.M) or [""])[-1]
            answering = bool(re.search(r"\b(answer|reply|respond|explain|tell|summar|greet)\w*\b", act_line, re.I)) and not TOOL_NAME_RE.search(act_line)
            needs_tool = (not calls and not finished and not answering and
                          bool(TOOL_NAME_RE.search(act_line + " " + answer) or WORK_RE.search(act_line) or announced))
            pasted = (not calls and ("```" in answer or announced) and act_try < 3 and
                      (HEADLESS or long_code or re.search(r"\b(write_file|edit_file|run_command)\b", thought or "")))
            if done_now:
                pasted = needs_tool = False
            if not calls and not pasted and needs_tool and act_try < 3:
                print(f"{D}  (said what it will do but did not do it — acting now){R}")
                clog({"nudge": "act_not_done", "answer": answer[:200]})
                continue                                   # 다음 시도는 ACT_STRICT ('지금 Act 의 도구를 불러라')
            if pasted:
                print(f"{D}  (wrote code in the reply instead of saving it — calling the tool now){R}")
                nxt_paste[1] = True
                nxt_paste[0] = answer[:4000] if "```" in answer else nxt_paste[0]   # 다음 시도에서 이 코드를 보여 주며 도구로 저장하게 한다 (기록에는 남기지 않는다)
                continue
            if answer or calls:
                break
            print(f"{D}  (thought but did not act — acting now){R}")
        started = out["ans"]
        if started:
            sys.stdout.write("\n\n")
        if not calls and app.gave_up(answer) and nud["giveup"] < 2:
            nud["giveup"] += 1
            print(f"{D}  (looking for another way before giving up){R}")
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": "[Do not say it cannot be done yet. Write Alternatives (at least three other ways), pick the best, and try it with a tool.]"})
            continue
        msg = {"role": "assistant", "content": answer}
        if calls:
            msg["tool_calls"] = calls
        msgs.append(msg)
        # 끝내는 답이 너무 짧으면(요약 없이 'open http://…' 한 줄로 끝났다, 11/15) 한 번 요약을 쓰게 한다
        if (not calls and nud["summary"] < 1 and state["worked"] and len((answer or "").strip()) < 120
                and not ASK_USER_RE.search(answer or "")):
            nud["summary"] += 1
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": "[Now write the final summary for the user (no tool call): what you changed, how you verified it "
                         "(the commands you ran and what they printed), and anything they should look at themselves. Keep it short.]"})
            clog({"nudge": "summary", "answer": answer[:200]})
            continue
        failing = state.get("last_check") and not re.search(r"\bPASS\b|\bOK\b|passed|exit code 0", state.get("last_check_full", ""), re.I) \
            and re.search(r"exit code [1-9]", state.get("last_check_full", ""))
        if not calls and failing and nud["failing"] < 3:
            nud["failing"] += 1
            print(f"{O}  (the last check failed — not done yet, fixing){R}")
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": f"[The last check `{state['last_check'][0]}` FAILED, so the task is not done. Do not finish. "
                         "Read its output again, fix the code with edit_file or write_file (a real tool call, not code in the reply), "
                         "then run the check again.]"})
            clog({"nudge": "check_failing", "answer": (answer or "")[:200]})
            continue
        if not calls and failing:
            state["unfinished"] = True
            print(f"{E}  ✗ stopped while the last check still fails: {state['last_check'][0]}{R}")
        if not calls and ASK_USER_RE.search(answer or "") and nud["askuser"] < 2:
            nud["askuser"] += 1
            print(f"{O}  (trying the other ways before asking you){R}")
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": ASK_USER_NUDGE})
            clog({"nudge": "ask_user", "answer": answer[:300]})
            continue
        if not calls and state["changed"] and nud["verify"] < 1 and SETTINGS.get("review") != "off":
            nud["verify"] += 1
            print(f"{O}  (verify first: running it before finishing){R}")
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": VERIFY_NUDGE})
            continue
        if not calls and state["worked"]:
            note_handoff(msgs, answer, state)
        if not calls:
            clog({"assistant": answer})   # 밤 학습(사용자 판단)이 이 기록으로 '제안 → 대답' 짝을 만든다
            return
        for c in calls:
            f = c.get("function") or {}
            name, args = f.get("name"), f.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            show_tool(name, args)
            sig0 = (name, json.dumps(args, sort_keys=True, ensure_ascii=False)[:500], state.get("ver", 0))
            if seen.get(sig0, 0) >= 3:            # 네 번째부터는 실행하지 않는다 (11/15: 안내를 무시하고 list_dir 를 8 번)
                seen[sig0] += 1
                result = (f"[NOT RUN: you already did exactly this {seen[sig0] - 1} times and it was not run again. "
                          "Pick a different action that moves the task forward, or finish with Check if the task's check passes.]")
                print(f"{E}  ✗ not run — the same action again{R}")
                clog({"nudge": "repeat_blocked", "call": sig0[1][:200]})
                msgs.append({"role": "tool", "content": result, "tool_name": name})
                continue
            fn = CALLS.get(name)
            try:
                result = fn(**{k: str(v) for k, v in args.items()}) if fn else "unknown tool"
            except TypeError as e:
                result = f"wrong arguments: {e}"
            except Exception as e:
                result = f"failed: {type(e).__name__}: {e}"[:400]
            if name == "run_command" and re.match(r"exit code [1-9]", str(result)):
                where = locate_errors(result)
                if where:
                    result = str(result) + where
                    clog({"aid": "locate_errors", "found": where[:300]})
            sig = (name, json.dumps(args, sort_keys=True, ensure_ascii=False)[:500], state.get("ver", 0))
            seen[sig] = seen.get(sig, 0) + 1
            if seen[sig] >= 3:
                print(f"{O}  (same action {seen[sig]} times — telling extra to try another way or finish){R}")
                clog({"nudge": "repeat", "times": seen[sig], "call": sig[1][:200]})
                result = (str(result) + f"\n\n[NOTE: you have now done exactly this {seen[sig]} times and it cannot tell you anything new. "
                          "Do not do it again. Use a different way that you can actually observe (you cannot see a browser), or, if the task's "
                          "check already passes, finish now: write Check, say what you verified and what the user should look at themselves.]")
            show_result(result, name)
            clog({"tool": name, "args": {k: str(v)[:200] for k, v in args.items()}, "result": str(result)[:1000]})
            msgs.append({"role": "tool", "content": str(result), "tool_name": name})
            state["worked"] = True
            if name in ("write_file", "edit_file") and str(result).startswith(("saved", "edited")):
                state["ver"] = state.get("ver", 0) + 1    # 파일이 바뀌었다: 같은 명령(check 다시 돌리기)도 새 행동이다 (11/15)
            if name == "run_command":
                run = (str(args.get("command", ""))[:120], str(result).strip().splitlines()[-1][:120] if str(result).strip() else "")
                state["last_run"] = run
                if re.search(r"check|test|pytest|unittest|verify", run[0], re.I):
                    state["last_check"] = run
                    state["last_check_full"] = str(result)[:4000]
            if name in ("write_file", "edit_file") and not str(result).startswith(("the user", "not allowed", "wrong", "failed", "refused")):
                state.setdefault("files", set()).add(str(args.get("path", "")))
            if (name in ("write_file", "edit_file") and not str(result).startswith(("the user", "not allowed", "wrong", "failed", "refused"))
                    and not re.search(r"(\.md|\.txt)$|(^|/)\.extra/", str(args.get("path", "")))):   # 메모·문서는 '실행해서 확인' 대상이 아니다 (11/15)
                state["changed"] = True
            elif name == "run_command" and str(result).startswith("exit code"):
                state["changed"] = False


def note_handoff(msgs, answer, state):
    """일을 마치면 인계 메모(.extra/handoff.md) 끝에 extra 가 한 일을 덧붙인다 (Claude 가 다시 이어받을 때 보게).
    (11/15: 끝나면 도구를 못 쓰게 하면서 extra 가 메모를 갱신하지 못했다 → 프로그램이 쓴다)"""
    f = CWD / ".extra" / "handoff.md"
    if not f.is_file():
        return
    try:
        files = ", ".join(sorted(x for x in state.get("files", set()) if x and not x.endswith("handoff.md"))) or "none"
        cmd, out = state.get("last_check") or state.get("last_run", ("", ""))
        text = re.sub(r"```.*?```", " ", answer or "", flags=re.S)
        text = " ".join(l.strip() for l in text.splitlines() if l.strip())
        parts = re.split(r"(?<=[.!?。다])\s+", text)          # 앞 두 문장만 (출력은 넣지 않는다)
        summary = " ".join(parts[:2])[:300]
        head = ("- NOT finished: stopped while the last check still fails. Next: read the check output below and fix the code."
                if state.get("unfinished") else "- Finished this task in this folder.")
        block = (f"\n## extra ({time.strftime('%Y-%m-%d %H:%M')})\n{head}\n- Files changed: {files}\n"
                 + (f"- Last check: `{cmd}` → {out}\n" if cmd else "") + (f"- Summary: {summary}\n" if summary else ""))
        with open(f, "a") as fh:
            fh.write(block)
        print(f"{D}  (noted what extra did at the end of .extra/handoff.md){R}")
    except OSError:
        pass


def claude_handoff(session_file=None):
    """Claude Code 가 한도에 걸려 멈춘 일을 이어받는다: 이 폴더의 가장 최근 Claude Code 대화에서 사용자가 시킨 일과 마지막 상황을 읽고,
    git 상태와 함께 extra 에게 넘긴다 (모두 이 맥 안에서만 읽는다)."""
    d = HOME / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(CWD))
    files = [Path(session_file)] if session_file else sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if d.exists() else []
    asks, last = [], []
    if files:
        for line in open(files[0], errors="ignore"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = r.get("message") or {}
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
            text = (text or "").strip()
            if not text or text.startswith("<"):
                continue
            if r.get("type") == "user":
                asks.append(text[:600])
            elif r.get("type") == "assistant":
                last.append(text[:1500])
    git = ""
    if (CWD / ".git").exists() or subprocess.run(["git", "rev-parse"], cwd=CWD, capture_output=True).returncode == 0:
        git = "\n".join(subprocess.run(c, shell=True, cwd=CWD, capture_output=True, text=True).stdout.strip()[:1500]
                        for c in ("git status --short | head -30", "git log --oneline -5", "git diff --stat | tail -15"))
    parts = ["[Handoff] The user's main AI assistant hit its usage limit in the middle of a task in this folder. Take over and finish it."]
    note = CWD / ".extra" / "handoff.md"   # extra-handoff 스킬로 Claude 가 남긴 인계 메모 (가장 믿을 만한 정보)
    if note.is_file():
        parts.append("Handoff note the previous assistant left in .extra/handoff.md (trust this first):\n" + note.read_text(errors="replace")[:6000])
    if asks:
        parts.append("What the user asked recently (oldest first):\n- " + "\n- ".join(asks[-8:]))
    if last:
        parts.append("The assistant's last messages before it stopped:\n" + "\n---\n".join(last[-2:]))
    if git:
        parts.append("Current state of the project (git):\n" + git)
    if len(parts) == 1:
        return None
    parts.append("When you finish or stop, update .extra/handoff.md (Goal / Done / In progress / Next / How to test) so the next assistant can continue.")
    parts.append("First look at the files to see how far it got, then continue the task until it is done and verified.")
    return "\n\n".join(parts)


def session_info(f):
    """세션 파일 끝부분만 읽어서 제목·폴더·마지막 요청을 얻는다 (파일이 커도 빠르게)."""
    size = f.stat().st_size
    with open(f, "rb") as fh:
        fh.seek(max(0, size - 3_000_000))
        tail = fh.read().decode(errors="ignore").splitlines()
    title = cwd = lastp = ""
    for line in tail:
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = r.get("customTitle") or title
        lastp = r.get("lastPrompt") or lastp
        cwd = r.get("cwd") or cwd
    if not cwd:
        with open(f, errors="ignore") as fh:
            for _, line in zip(range(200), fh):
                m = re.search(r'"cwd":\s*"([^"]+)"', line)
                if m:
                    cwd = m.group(1); break
    return {"file": f, "title": title or (lastp[:50] if lastp else f.stem[:8]), "cwd": cwd, "last": lastp, "mtime": f.stat().st_mtime}


def pad(text, n):
    """화면 칸 수로 자르고 채운다 (한글은 한 글자가 두 칸)."""
    import unicodedata
    out, w = "", 0
    for ch in str(text):
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > n - (1 if len(text) > len(out) + 1 else 0):
            out += "…"; w += 1
            break
        out += ch; w += cw
    return out + " " * max(0, n - w)


DEMO_MODE = False  # True (또는 EXTRA_DEMO=1): 실제 작업 대신 가짜 예시 작업을 보여 준다 (스크린샷·데모용)


def _demo_on():
    return DEMO_MODE or bool(os.environ.get("EXTRA_DEMO"))


DEMO_SESSIONS = [   # 녹화용 가짜 작업 (EXTRA_DEMO=1). 실제 작업 대신 보여 준다 (사용자 11/15).
    {"title": "weather-dashboard",  "dir": "~/Projects/weather-dashboard",  "ago": 1800,
     "last": "Add a 5-day forecast panel and cache the API response."},
    {"title": "notes-api",          "dir": "~/Projects/notes-api",          "ago": 9000,
     "last": "Fix the failing test for the search endpoint."},
    {"title": "portfolio-site",     "dir": "~/Projects/portfolio-site",     "ago": 93600,
     "last": "Make the landing page responsive on mobile."},
]


def _demo_sessions(limit=9):
    import time as _t
    safe = str((CWD / ".extra" / "handoff.md"))   # 혹시 골라도 깨지지 않게 (실제로는 데모 인계 메모)
    return [{"title": d["title"], "cwd": d["dir"], "mtime": _t.time() - d["ago"], "last": d["last"], "file": safe}
            for d in DEMO_SESSIONS][:limit]


def claude_sessions(limit=9):
    if _demo_on():
        return _demo_sessions(limit)
    base = HOME / ".claude" / "projects"
    files = sorted(base.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) if base.exists() else []
    out = []
    for f in files:
        try:
            info = session_info(f)
        except OSError:
            continue
        if info["cwd"] and Path(info["cwd"]).is_dir():
            out.append(info)
        if len(out) >= limit:
            break
    return out


def find_handoffs(limit=6):
    """Claude 가 인계 메모(.extra/handoff.md)를 남긴 폴더들 (최근 것부터). 경로를 직접 칠 필요가 없게."""
    if _demo_on():
        for h in (CWD / ".extra" / "handoff.md", HOME / "Documents" / "typing-speed-test" / ".extra" / "handoff.md"):
            if h.is_file():
                return [h]
        return []
    seen, out = set(), []
    roots = [HOME / d for d in ("Documents", "Code", "Desktop", "Projects", "Developer", "dev", "src")]
    cands = [CWD / ".extra" / "handoff.md"]
    for r in roots:
        if r.is_dir():
            cands += list(r.glob("*/.extra/handoff.md")) + list(r.glob("*/*/.extra/handoff.md"))
    for x in claude_sessions(20):
        cands.append(Path(x["cwd"]) / ".extra" / "handoff.md")
    for f in cands:
        try:
            if f.is_file() and f.resolve() not in seen:
                seen.add(f.resolve()); out.append(f)
        except OSError:
            pass
    out.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return out[:limit]


def note_goal(f):
    text = f.read_text(errors="replace")
    return next((l.strip() for l in text.split("## Goal", 1)[-1].splitlines() if l.strip() and not l.startswith("#")), "")


def recent_folders(limit=8):
    """최근 extra 를 쓴 폴더 + 인계 메모가 있는 폴더 + Claude 세션 폴더 (홈 폴더에서 켰을 때 고르게)."""
    rows = {}
    try:
        for line in open(CLOG, errors="ignore").readlines()[-3000:]:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = r.get("cwd")
            if c and "/.extra/jobs/" not in c:
                rows[c] = r.get("t", "")
    except OSError:
        pass
    for f in find_handoffs(10):
        rows.setdefault(str(f.parent.parent), time.strftime("%F %T", time.localtime(f.stat().st_mtime)))
    for x in claude_sessions(10):
        rows.setdefault(x["cwd"], time.strftime("%F %T", time.localtime(x["mtime"])))
    keep = [(c, t) for c, t in rows.items() if Path(c).is_dir() and Path(c).resolve() != HOME]
    keep.sort(key=lambda ct: ct[1], reverse=True)
    return [c for c, _ in keep[:limit]]


def start_menu():
    """모델을 올린 뒤 무엇을 할지 번호로 고른다 (사용자 11/15): 1) 작업 이어받기 2) 폴더에서 일하기 3) 그냥 시작.
    이어받기를 고르면 이어받을 글을 돌려주고, 나머지는 None (대화형으로 바로 시작)."""
    in_project = CWD != HOME
    here = CWD.name
    rows = [("Continue a task", "pick up a Claude handoff note or session"),
            (f"Work in this folder ({here})" if in_project else "Work in a folder",
             "start a new task here" if in_project else "choose a folder, or make one"),
            ("Just start", "skip this and start typing here" + (f" (~/{CWD.relative_to(HOME)})" if in_project and str(CWD).startswith(str(HOME)) else " (home folder)" if CWD == HOME else f" ({here})"))]
    print(f"\n {B}What do you want to do?{R}")
    default = 2 if in_project else 1
    for i, (label, desc) in enumerate(rows, 1):
        mark = f" {D}(Enter){R}" if i == default else ""
        print(f" {W}{i}{R}  {pad(label, 30)} {D}{desc}{R}{mark}")
    try:
        a = read_answer(f"{P} › {R}").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return None
    choice = int(a) if a.isdigit() and 1 <= int(a) <= 3 else default
    if choice == 1:
        return pick_session()
    if choice == 2 and not in_project:
        pick_folder()
    return None   # 2(여기서 일하기) 또는 3(그냥 시작): 지금 폴더에서 바로 대화형 시작


def pick_folder():
    """홈 폴더에서 켰을 때: 최근 폴더를 번호로 고르거나 새 폴더 이름을 친다."""
    fs = recent_folders()
    print(f"\n {B}Where do you want to work?{R}")
    for i, c in enumerate(fs, 1):
        f = Path(c)
        mark = f" {P}note{R}" if (f / ".extra" / "handoff.md").is_file() else ""
        print(f" {W}{i}{R}  {pad(f.name, 26)} {D}{pad(c.replace(str(HOME), '~'), 40)}{R}{mark}")
    print(f" {D}type a number · or a new folder name (it is made in ~/Documents) · Enter = stay in your home folder{R}")
    a = read_answer(f"{P} › {R}").strip()
    if not a:
        return
    if a.isdigit() and 1 <= int(a) <= len(fs):
        target = Path(fs[int(a) - 1])
    else:
        target = Path(os.path.expanduser(a)) if a.startswith(("/", "~")) else HOME / "Documents" / a
        target.mkdir(parents=True, exist_ok=True)
    set_cwd(target)
    print(f"{P}↪ working in {str(CWD).replace(str(HOME), '~')}{R}")


def pick_session():
    """Claude Code 에서 하던 일 목록을 보여 주고 번호로 고른다. 고른 세션의 폴더로 옮기고, 이어받을 글을 돌려준다."""
    notes = find_handoffs()
    ss = claude_sessions(max(3, 9 - len(notes)))
    if not ss and not notes:
        print(f"{D}No Claude Code sessions or handoff notes found on this Mac.{R}")
        return None
    if notes:   # Claude 가 남긴 인계 메모 (extra-handoff 스킬) — 이어받기에 가장 믿을 만하다
        print(f"\n {B}Handoff notes Claude left{R} {D}(newest first){R}")
        for i, f in enumerate(notes):
            folder = f.parent.parent
            here = f" {G}← here{R}" if folder.resolve() == CWD else ""
            print(f" {W}{chr(97 + i)}{R}  {pad(folder.name, 34)} {D}{pad(str(folder).replace(str(HOME), '~'), 30)} {J.ago(f.stat().st_mtime):>7}{R} {P}note{R}{here}")
            g = note_goal(f)
            if g:
                print(f"    {D}goal: {pad(g, 70).rstrip()}{R}")
    print(f"\n {B}Claude sessions{R} {D}(newest first){R}")
    for i, x in enumerate(ss, 1):
        where = x["cwd"].replace(str(HOME), "~")
        marks = []
        if (Path(x["cwd"]) / ".extra" / "handoff.md").is_file():
            marks.append(f"{P}note{R}")
        jobs = J.list_jobs(x["cwd"])
        run_n = sum(1 for j in jobs if j[1].startswith("running"))
        if jobs:
            marks.append(f"{O}{run_n} running{R}" if run_n else f"{D}{len(jobs)} job(s){R}")
        here = f" {G}← here{R}" if Path(x["cwd"]).resolve() == CWD else ""
        print(f" {W}{i}{R}  {pad(x['title'], 34)} {D}{pad(where, 30)} {J.ago(x['mtime']):>7}{R} {' '.join(marks)}{here}")
        if x["last"]:
            print(f"    {D}last ask: {pad(x['last'].replace(chr(10), ' '), 70).rstrip()}{R}")
    try:
        a = read_answer(f"{P} pick a letter or number (Enter = {'a' if notes else 1}, q = cancel) › {R}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return None
    if a.startswith("q"):
        return None
    if notes and (a == "" or (len(a) == 1 and "a" <= a < chr(97 + len(notes)))):
        f = notes[ord(a or "a") - 97]
        set_cwd(f.parent.parent)
        print(f"{P}↪ continuing from the handoff note in {str(CWD).replace(str(HOME), '~')}{R}")
        return claude_handoff()
    try:
        x = ss[(int(a) if a else 1) - 1]
    except (ValueError, IndexError):
        print(f"{D}no such number{R}"); return None
    set_cwd(x["cwd"])
    print(f"{P}↪ continuing \"{x['title'][:50]}\" in {str(CWD).replace(str(HOME), '~')}{R}")
    h = claude_handoff(x["file"])
    jobs = J.list_jobs(CWD)
    if h and jobs:
        h += "\n\nJobs Claude handed to extra earlier in this project (id, status, task):\n" + "\n".join(f"- {j[0]} {j[1]}: {j[3]}" for j in jobs[-8:])
    return h


def set_cwd(p):
    global CWD, SYSTEM, PROMPT_ROOT
    p = Path(p).resolve()
    os.chdir(p)
    SYSTEM = SYSTEM.replace(f"Project folder (your working directory): {CWD}.", f"Project folder (your working directory): {p}.")
    CWD = PROMPT_ROOT = p
    if FLOG.f:
        FLOG.open(p)


def prompt_command(arg):
    """/prompt                 지금 들어간 내 지시 보기
       /prompt add 글          이 프로젝트에 지시 더하기  (--global: 모든 프로젝트)
       /prompt edit            편집기로 열기
       /prompt clear           지우기"""
    glob_ = "--global" in arg
    arg = arg.replace("--global", "").strip()
    scope, f = J.prompt_files(PROMPT_ROOT)[0 if glob_ else 1]
    if arg.startswith("add "):
        text = arg[4:].strip()
        f.parent.mkdir(parents=True, exist_ok=True)
        old = f.read_text() if f.is_file() else ""
        f.write_text((old.rstrip() + "\n" if old.strip() else "") + text + "\n")
        print(f"{G}✓ added to the {scope} prompt{R} {D}{f}{R}")
    elif arg == "edit":
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        was = UI.on
        UI.stop()
        subprocess.run([os.environ.get("EDITOR", "nano"), str(f)])
        if was:
            UI.start()
    elif arg == "clear":
        if f.is_file():
            f.with_suffix(".md.bak").write_text(f.read_text())
            f.unlink()
        print(f"{G}✓ cleared the {scope} prompt{R} {D}(backup: {f.with_suffix('.md.bak').name}){R}")
    shown = False
    for sc, ff in J.prompt_files(PROMPT_ROOT):
        if ff.is_file() and ff.read_text().strip():
            t = ff.read_text().strip()
            shown = True
            print(f" {B}{sc}{R} {D}{ff}{R}" + (f" {O}(only the first {J.PROMPT_MAX} characters are used){R}" if len(t) > J.PROMPT_MAX else ""))
            for line in t.splitlines()[:30]:
                print(f"   {line}")
            for line, why in J.conflicts_in(t):
                print(f" {O}! \"{line}\" conflicts with a core rule ({why}); the core rule wins{R}")
    if not shown:
        print(f"{D}No instructions of your own yet. Add one:  /prompt add Always write comments in Korean   (--global for every project){R}")
    print()


HELP_DOC = APP_DIR / "extra_help.md"


def help_command(arg):
    """/help → 명령 목록 (바로). /help <질문> → extra 가 자기 기능 설명서를 보고 답한다 (생각 단계 없이 바로)."""
    q = arg.strip()
    if not q:
        rows = [("extra [folder]", "start here or in that folder"), ("extra continue", "pick a Claude Code session by number and continue it"),
                ("extra \"task\"", "do one task and exit"),
                ("/help <question>", "ask extra anything about itself"), ("/continue", "pick a Claude task and continue it"),
                ("/new", "start a new task"), ("/set", "settings menu: permissions, thinking, skills, your rules, speed — pick by number"),
                ("/prompt", "your own instructions (add · edit · clear · --global)"),
                ("/skills · /skill <name>", "list skills · use one for your next request"), ("/exit", "quit · Ctrl-C stops the current step"),
                ("extra run \"task\" --test CMD", "Claude hands extra a job in the background"),
                ("extra jobs · show ID · apply ID", "jobs list (✻ Claude) · result and diff · use it")]
        print(f"\n {B}commands{R}")
        for a, b in rows:
            print(f"  {P}{a:<32}{R} {D}{b}{R}")
        print(f"  {D}Type in the bottom box any time, even while extra works. Ask more: /help how do I hand work from Claude to you?{R}\n")
        return
    sysm = ("You are extra. Answer the user's question about yourself (extra) using ONLY the reference below.\n"
            "- If the FAQ has the question, give that answer.\n- Copy commands exactly as written in the reference. Never invent commands, syntax or rules.\n"
            "- Commands that start with / are typed inside extra, not in the shell.\n- Only if nothing in the reference answers the question, reply with just a short sentence saying the manual does not cover it. Never add that sentence after a real answer.\n"
            "- Be short: 2 to 6 lines.\n- " + lang_rule() + "\n\n"
            + HELP_DOC.read_text())
    print(f"{P}◆{R} {D}extra about extra{R}")
    text = ""
    for ch in app.ollama_stream([{"role": "system", "content": sysm}, {"role": "user", "content": q}], tools=False, temp=0.0):
        t = (ch.get("message") or {}).get("content") or ""
        if t:
            text += t
            sys.stdout.write(t); sys.stdout.flush()
    print("\n")
    clog({"help": q, "answer": text[:800]})


def run_job():
    """extra run: Claude 가 넘긴 문제를 복사본에서 혼자 끝까지. 테스트 명령이 있으면 통과할 때까지 실제 실행 결과로 고친다."""
    global HEADLESS, DEADLINE, JOB_DIR
    d, job, o = RUN
    HEADLESS, JOB_DIR = True, d
    DEADLINE = time.time() + job["minutes"] * 60
    real = sys.stdout

    class Strip:
        def __init__(self, f): self.f = f
        def write(self, t): self.f.write(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", t)); self.f.flush()
        def flush(self): self.f.flush()
        def isatty(self): return False
    sys.stdout = Strip(open(d / "log.txt", "a"))
    mfile = d / "msgs.json"
    msgs = json.loads(mfile.read_text()) if (o["job"] and mfile.is_file()) else []
    text = J.feedback_text(o["feedback"] or "Continue and finish the task.") if o["job"] else J.task_text(job, CWD)
    who = "✻ Claude" if job.get("from", "claude") == "claude" else "you"
    print(f"\n===== {time.strftime('%F %T')} {who} → extra {'(sent back)' if o['job'] else ''}: {(o['feedback'] or job['task'])[:200]}")
    status, test_out = "timeout", ""
    for rnd in range(30):
        job["rounds"].append({"t": time.strftime("%F %T"), "kind": "feedback" if (o["job"] and rnd == 0) else "test-fix" if rnd else "start"})
        try:
            one_turn(msgs, text)
        except Stop:
            status = "timeout"; break
        except Exception as e:
            status, test_out = "error", f"{type(e).__name__}: {e}"; break
        if not job.get("test"):
            status = "done"; break
        print(f"\n===== running the test: {job['test']}")
        try:
            r = subprocess.run(job["test"], shell=True, cwd=CWD, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=max(30, min(600, DEADLINE - time.time())))
            test_out = (r.stdout + r.stderr).strip()
            code = r.returncode
        except subprocess.TimeoutExpired:
            test_out, code = "(test timed out)", 124
        print(test_out[-3000:])
        if code == 0:
            status = "passed"; break
        if time.time() > DEADLINE:
            status = "failed"; break
        status = "failed"
        text = (f"[I ran the test command myself: `{job['test']}` → exit code {code}. Output (end):\n{test_out[-2500:]}\n"
                "The task is not done yet. Find why it fails (read the error carefully), fix it, and run the test again.]")
    summary = next((m["content"] for m in reversed(msgs) if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls")
                    and not m["content"].startswith("<think>")), "")
    mfile.write_text(json.dumps([{k: v for k, v in m.items() if k != "full"} for m in msgs][-80:], ensure_ascii=False))
    res = J.finish(d, job, status, summary, test_out)
    sys.stdout = real
    print(res)
    sys.exit(0 if status in ("passed", "done") else 1)


def folder_summary():
    """폴더를 한 번 훑어 사람에게 알려 줄 짧은 요약 (모델을 쓰지 않는다)."""
    if CWD == HOME:
        return (f"{O}You are in your home folder.{R} {D}Better: open a project folder, e.g.  extra ~/Code/my-project{R}")
    items = [x for x in sorted(CWD.iterdir()) if not x.name.startswith(".") and x.name not in SKIP]
    if not items:
        return f"{D}This folder is empty — a fresh start.{R}"
    kinds, total = {}, 0
    for base, dirs, files in os.walk(CWD):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            total += 1
            ext = Path(f).suffix.lower() or "(none)"
            kinds[ext] = kinds.get(ext, 0) + 1
        if total > 5000:
            break
    top = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:6])
    names = "  ".join((x.name + ("/" if x.is_dir() else "")) for x in items[:14]) + ("  …" if len(items) > 14 else "")
    lines = [f"{W}{total} files{R} {D}({top}){R}", f"{D}{names}{R}"]
    for rd in ("README.md", "readme.md", "README.txt"):
        f = CWD / rd
        if f.is_file():
            first = next((l.strip("# ").strip() for l in f.read_text(errors="replace").splitlines() if l.strip()), "")
            if first:
                lines.append(f"{D}README: {first[:100]}{R}")
            break
    if (CWD / ".extra" / "handoff.md").is_file():
        lines.append(f"{P}A handoff note is here.{R} {D}Run /continue to pick up where the last assistant stopped.{R}")
    if (CWD / ".git").exists():
        st = subprocess.run(["git", "status", "--short"], cwd=CWD, capture_output=True, text=True).stdout.strip().splitlines()
        lines.append(f"{D}git: {len(st)} changed file(s){R}")
    return "\n ".join(lines)


WARM = {"thread": None, "start": 0.0, "ok": None}
LOAD_FILE = HOME / ".extra" / "load_seconds"


def model_loaded():
    try:
        ps = json.loads(urllib.request.urlopen("http://localhost:11434/api/ps", timeout=3).read())
        return any(m.get("name") == app.current_model() for m in ps.get("models", []))
    except Exception:
        return False


def system_prefix():
    """시스템 프롬프트의 안정된 앞부분 (SYSTEM + 스킬 목록). CWD 에 따라 달라지는 prompt_block 은 뒤에 따로 붙인다.
    로드할 때 이 부분을 미리 읽혀(캐시) 두면 첫 대화의 프롬프트 처리가 빨라진다 (사용자 11/16)."""
    sks = load_skills()
    sk_list = ("\n\nSKILLS (expert instructions you can load with the use_skill tool when the work matches):\n"
               + "\n".join(f"- {v['name']}: {v['description']}" for v in sks.values())) if sks else ""
    return SYSTEM.replace("{today}", time.strftime("%Y-%m-%d (%A)")).replace("{lang_rule}", lang_rule()) + sk_list


# 로드 때 프롬프트를 읽으라는 짧은 지시 (사용자가 설정한 언어로)
READY_MSG = {"en": "Reply with only: ready", "ko": "안내를 다 읽었으면 'ready'라고만 답하세요.",
             "ja": "指示を読んだら 'ready' とだけ答えてください。", "zh": "读完说明后只回复：ready",
             "es": "Responde solo con: ready", "de": "Antworte nur mit: ready", "fr": "Réponds seulement : ready"}


def warm_up():
    """화면이 뜨자마자 뒤에서 모델을 미리 올려 둔다 (첫 질문이 '생각 중'에서 오래 멈추지 않게)."""
    if WARM["thread"]:
        return
    def go():
        try:
            msg = READY_MSG.get(SETTINGS.get("language", "en"), READY_MSG["en"])
            body = {"model": app.current_model(),
                    "messages": [{"role": "system", "content": system_prefix()}, {"role": "user", "content": msg}],
                    "stream": False, "keep_alive": "30m", "options": {"num_predict": 2, "num_ctx": app.NUM_CTX}}
            urllib.request.urlopen(urllib.request.Request(app.OLLAMA_CHAT, data=json.dumps(body).encode()), timeout=300).read()
            WARM["ok"] = True
        except Exception as e:
            WARM["ok"] = f"{type(e).__name__}: {e}"
    import threading
    WARM["start"] = time.time()
    WARM["thread"] = threading.Thread(target=go, daemon=True)
    WARM["thread"].start()


SPEED_ENV = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
SPEED_AGENT = HOME / "Library" / "LaunchAgents" / "com.extra.ollama-speed.plist"


def speed_state():
    """(설정 등록됨, 지금 도는 Ollama 가 그 설정을 쓰는 중)"""
    env_ok = all(subprocess.run(["launchctl", "getenv", k], capture_output=True, text=True).stdout.strip() == v for k, v in SPEED_ENV.items())
    running = False
    try:
        pid = subprocess.run(["pgrep", "-f", "ollama serve"], capture_output=True, text=True).stdout.split()
        if pid:
            envtxt = subprocess.run(["ps", "eww", "-p", pid[0]], capture_output=True, text=True).stdout
            running = all(f"{k}={v}" in envtxt for k, v in SPEED_ENV.items())
    except Exception:
        pass
    return env_ok, running


def pad(text, n):
    """한글·한자처럼 두 칸 차지하는 글자를 세어서 칸을 맞춘다."""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(1, n - w)


def pick(title, options, default=1, note=""):
    """번호로 하나 고르기 (Enter = 기본값). options: [(라벨, 설명)] → 0부터 시작하는 번호."""
    print(f"\n {B}{title}{R}" + (f"  {D}{note}{R}" if note else ""))
    for i, (label, desc) in enumerate(options, 1):
        mark = f" {D}(default){R}" if i == default else ""
        print(f"  {W}{i}{R}  {pad(label, 26)} {D}{desc}{R}{mark}")
    while True:
        try:
            a = input(f"{P}  › {R}").strip()
        except (EOFError, KeyboardInterrupt):
            print(); return default - 1
        if not a:
            return default - 1
        if a.isdigit() and 1 <= int(a) <= len(options):
            return int(a) - 1
        print(f"  {D}Type a number from 1 to {len(options)}, or press Enter for the default.{R}")


def first_setup():
    """맨 처음 extra 를 열 때 한 번만 (사용자 11/15): 언어, 생각 수준, 검증, 허용 범위, 빠르게 하는 설정. 나중에는 /set 에서 바꾼다."""
    if SETTINGS.get("setup_done") or not sys.stdin.isatty():
        return
    print(f"\n {P}◆{R} {W}Welcome to extra.{R} {D}Five quick choices — press Enter to keep the default. You can change them later with /set.{R}")
    codes = list(LANGS)
    SETTINGS["language"] = codes[pick("1/5  Language — which language should extra answer in?",
                                      [(LANGS[c][0], "same language as your message" if c == "auto" else "") for c in codes])]
    SETTINGS["effort"] = ["low", "medium", "high"][pick("2/5  Thinking — how carefully should extra think before each step?",
        [("low", "plan → act · fastest"), ("medium", "plan → compare options → act"),
         ("high", "plan → options → predict the result → act · most careful")], default=3)]
    SETTINGS["review"] = ["on", "off"][pick("3/5  Verify — after each change, run it and check the real result?",
        [("on", "slower, catches mistakes"), ("off", "faster, checks only at the end")])]
    perm = pick("4/5  Permissions — what may extra do without asking you?",
        [("Ask me first", "writing files, running commands and downloads each ask"),
         ("Everyday work", "write files and run commands freely; ask before installs, downloads and risky commands"),
         ("Everything", "never ask (risky commands like rm -r or sudo included)")], default=2)
    levels = [{"installs": "ask", "downloads": "ask", "writes": "ask", "commands": "ask", "dangerous": "ask"},
              {"installs": "ask", "downloads": "ask", "writes": "always", "commands": "always", "dangerous": "ask"},
              {"installs": "always", "downloads": "always", "writes": "always", "commands": "always", "dangerous": "always"}][perm]
    SETTINGS.update(levels)
    env_ok, running = speed_state()
    if env_ok and running and SPEED_AGENT.exists():
        print(f"\n {B}5/5  Speed{R}  {G}✓ already on{R} {D}(Ollama flash attention + smaller memory cache){R}")
        SETTINGS["speedup"] = "on"
    else:
        sp = pick("5/5  Speed — turn on two Ollama settings that make extra about 30% faster?",
                  [("Yes", "same answers; 10.3 → 13.6 tokens a second on our Mac, about 1 GB less memory; Ollama restarts once"),
                   ("No", "leave Ollama as it is")])
        if sp == 0:
            speedup_on(restart=not (env_ok and running))
        else:
            SETTINGS["speedup"] = "no"
    SETTINGS["setup_done"] = True
    save_settings()
    lang = LANGS[SETTINGS["language"]][0]
    print(f"\n {G}✓ saved{R} {D}{lang} · thinking {SETTINGS['effort']} · verify {SETTINGS['review']} · "
          f"{['ask first', 'everyday work', 'everything'][perm]} · speed {SETTINGS.get('speedup')} — change any time with /set{R}\n")


def offer_speedup():
    """켤 때마다: 처음 설정에서 '켜기'를 골랐는데 실제로는 안 먹은 경우만 알린다 (묻는 건 처음 설정에서 한 번뿐)."""
    if SETTINGS.get("speedup") != "on" or not sys.stdin.isatty():
        return
    env_ok, running = speed_state()
    if env_ok and running:
        return
    if env_ok and not running:
        print(f" {O}●{R} The speed settings are on, but Ollama was started before them. {D}Quit Ollama from the menu bar and open it again to use them.{R}\n")
        return
    print(f" {O}●{R} The speed settings are off now. {D}Turn them on again: /set speedup on{R}\n")


def speedup_on(restart=True):
    for k, v in SPEED_ENV.items():
        subprocess.run(["launchctl", "setenv", k, v])
    # 재부팅 뒤에도 켜지게: 로그인할 때 같은 설정을 다시 넣는 작은 등록 파일
    args = "".join(f"launchctl setenv {k} {v}; " for k, v in SPEED_ENV.items())
    SPEED_AGENT.parent.mkdir(parents=True, exist_ok=True)
    SPEED_AGENT.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.extra.ollama-speed</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string><string>{args}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""")
    SETTINGS["speedup"] = "on"; save_settings()
    print(f"   {G}✓ turned on{R} {D}(kept after restarts: {SPEED_AGENT.name}){R}")
    if not restart:
        return
    r = subprocess.run(["osascript", "-e", 'quit app "Ollama"'], capture_output=True, text=True)
    ok = r.returncode == 0
    if ok:
        for _ in range(40):
            if subprocess.run(["pgrep", "-f", "ollama serve"], capture_output=True).returncode != 0:
                break
            time.sleep(0.25)
        subprocess.run(["open", "-a", "Ollama"])
        for _ in range(60):
            try:
                urllib.request.urlopen("http://localhost:11434/api/version", timeout=1); break
            except Exception:
                time.sleep(0.5)
        print(f"   {G}✓ Ollama restarted with the faster settings{R}\n")
    else:
        print(f"   {O}Ollama did not quit by itself.{R} {D}Quit it from the menu bar and open it again to use the new settings.{R}\n")


def load_bar():
    """모델이 다 올라갈 때까지 로딩바 (사용자 11/14). 걸리는 시간은 지난번 기록으로 어림하고, 끝나면 100% 로 채운다. Ctrl-C 로 건너뛸 수 있다."""
    if model_loaded():
        print(f" {G}✓{R} {D}model ready · {app.current_model()}{R}\n")
        return
    warm_up()
    try:
        est = max(5.0, float(LOAD_FILE.read_text()))
    except (OSError, ValueError):
        est = 25.0
    width = 28
    try:
        while WARM["thread"].is_alive():
            el = time.time() - WARM["start"]
            frac = min(0.95, el / est) if el < est else 0.95 + 0.04 * (1 - 1 / (1 + (el - est) / est))
            n = int(width * frac)
            sys.stdout.write(f"\r {P}◆{R} {D}loading {app.current_model()}{R}  {P}{'█' * n}{D}{'░' * (width - n)}{R} {W}{int(frac * 100):>3}%{R} {D}{el:4.0f}s{R}  ")
            sys.stdout.flush()
            time.sleep(0.15)
    except KeyboardInterrupt:
        print(f"\n {D}skipped — the model keeps loading in the background{R}\n")
        return
    el = time.time() - WARM["start"]
    if WARM["ok"] is True:
        sys.stdout.write(f"\r {G}✓{R} {D}model ready · {app.current_model()}{R}  {G}{'█' * width}{R} {W}100%{R} {D}{el:4.0f}s{R}  \n\n")
        try:
            LOAD_FILE.parent.mkdir(parents=True, exist_ok=True)
            LOAD_FILE.write_text(f"{el:.1f}")
        except OSError:
            pass
    else:
        sys.stdout.write(f"\r {E}✗ could not load the model{R} {D}{WARM['ok']} — is Ollama running? (open the Ollama app){R}\n\n")
    sys.stdout.flush()


def banner():
    model = app.current_model()
    where = str(CWD).replace(str(HOME), "~")
    print(f"\n {B}extra{R}{P}.{R}  {D}{where} · {model}{R}")
    print(" " + folder_summary())
    jobs = [j for j in J.list_jobs(CWD) if j[4] == "claude"][-5:]
    if jobs:
        print(f" {O}✻ Claude{R} {D}handed extra {len(jobs)} job(s) here:{R}")
        for jid, st, ago_, task, _ in jobs:
            c = G if st.startswith(("passed", "done")) else O if st.startswith("running") else E
            mark = "●" if st.startswith("running") else "✓" if st.startswith(("passed", "done")) else "✗"
            print(f"   {O}✻{R} {c}{mark} {st:<18}{R} {D}{ago_:>7}  {task[:60]}{R}")
    for sc, ff in J.prompt_files(PROMPT_ROOT):
        if ff.is_file() and ff.read_text().strip():
            bad = J.conflicts_in(ff.read_text())
            print(f" {D}your {sc} prompt is on{R}" + (f" {O}— {len(bad)} line(s) conflict with core rules (see /prompt){R}" if bad else ""))
    print(f" {D}/set settings, skills and permissions (pick by number) · /help · /continue pick a Claude task · /exit{R}")
    print(f" {D}Type in the box below any time — even while extra is working, it reads your note at its next step.{R}")
    print()


def open_chat():
    try:
        urllib.request.urlopen("http://127.0.0.1:8780/health", timeout=2)
    except Exception:
        subprocess.Popen([sys.executable, str(APP_DIR / "app.py"), "--no-window"], stdout=open(APP_DIR / "server.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(3)
    subprocess.run(["open", "http://127.0.0.1:8780"])


def main():
    args = sys.argv[1:]
    if args[:1] == ["--as"] and len(args) > 1:   # 사람별 모델: extra --as dad  (밤 학습으로 만든 그 사람 판단 모델)
        st = APP_DIR / "nightly" / "profiles" / args[1] / "state.json"
        models = json.loads(st.read_text()).get("models", []) if st.exists() else []
        if not models:
            print(f"no trained model for '{args[1]}' yet"); return
        app.current_model = lambda m=models[-1]: m
        args = args[2:]
    if RUN:
        run_job(); return
    if args[:1] == ["chat"]:
        print("extra is terminal-only now. Just run: extra"); return
    if args[:1] == ["prompt"]:
        prompt_command(" ".join(args[1:])); return
    if args[:1] == ["skills"]:
        skills_command(" ".join(args[1:])); return
    if args[:1] in (["help"], ["--help"], ["-h"]):
        help_command(" ".join(args[1:])); return
    msgs, first = [], None
    if args[:1] == ["continue"]:    # extra continue [덧붙일 말]: Claude 세션 목록에서 골라 이어서 (그다음은 대화형)
        load_bar()
        first = pick_session()
        if first is None:
            return
        if args[1:]:
            first += "\n\nThe user adds: " + " ".join(args[1:])
        args = []
    if args:
        try:
            one_turn(msgs, " ".join(args))
        except KeyboardInterrupt:
            print(f"\n{D}stopped{R}")
        return
    if first is None:
        first_setup()        # 맨 처음 한 번만: 언어, 생각, 검증, 허용 범위, 속도 (녹화에 나와야 한다)
        offer_speedup()      # 설정이 켜졌는데 Ollama 가 그 전에 켜진 경우만 알린다
        load_bar()           # 모델을 먼저 올린다 (로딩 바), 다 되면 무엇을 할지 고른다 (사용자 11/15)
        first = start_menu()
    # (extra continue 는 위에서 이미 로드하고 골랐다)
    UI.on_command = busy_command
    FLOG.open(CWD)
    UI.start()          # 아래 입력창을 먼저 켠다 (시작 안내도 기록에 남아 창 크기가 바뀌어도 다시 그려진다)
    banner()
    try:
        repl(msgs, first)
    finally:
        UI.stop()


PENDING_SKILLS = []   # /skill 이름 으로 고른 스킬 (다음에 시키는 말에 붙인다)


def skill_install(src, project=False):
    """받은 SKILL.md 파일이나 그 파일이 든 폴더를 내 스킬로 설치한다 (Claude Code 스킬 폴더도 된다)."""
    p = Path(os.path.expanduser(src.strip().strip("'\""))).resolve()
    f = p / "SKILL.md" if p.is_dir() else p
    if not f.is_file():
        return f"no SKILL.md at {p}"
    text = f.read_text(errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    meta = dict(l.split(":", 1) for l in (m.group(1).splitlines() if m else []) if ":" in l)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    name = re.sub(r"[^A-Za-z0-9_-]", "-", meta.get("name") or (p.name if p.is_dir() else p.stem)).strip("-").lower() or "my-skill"
    if not meta.get("triggers"):     # Claude 스킬에는 키워드가 없다: 이름과 설명에서 뽑는다
        stop = {"when", "with", "that", "this", "your", "from", "into", "about", "use", "used", "using", "and", "the", "for", "any", "you"}
        words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", (meta.get("name", "") + " " + meta.get("description", "")).lower())
        trig = list(dict.fromkeys(w for w in words if w not in stop))[:12]
        if m:
            text = text.replace(m.group(0), m.group(0)[:-4] + f"\ntriggers: {', '.join(trig)}\n---\n", 1)
        else:
            text = f"---\nname: {name}\ndescription: {text.strip().splitlines()[0][:120]}\ntriggers: {', '.join(trig)}\n---\n" + text
    dest = (PROMPT_ROOT / ".extra" / "skills" if project else HOME / ".extra" / "skills") / name
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(text)
    if p.is_dir():                    # 스킬 폴더에 같이 있는 파일(예시, 스크립트)도 복사
        for extra_f in p.iterdir():
            if extra_f.is_file() and extra_f.name != "SKILL.md" and extra_f.stat().st_size < 2_000_000:
                shutil.copy2(extra_f, dest / extra_f.name)
    return f"installed skill {name} → {dest}"


SKILL_TEMPLATE = """---
name: {name}
description: one line — what this skill is for
triggers: words that should load it, separated by commas
---
# {name}

Write the instructions here: rules, steps and short examples.
Keep it short — extra reads it at the start of a matching task.
"""


def skills_command(arg):
    """/skills — 목록. /skill 이름 — 다음 할 일에 그 스킬을 붙인다.
    /skill new 이름 — 새 스킬을 만들어 편집기로 연다. /skill add 경로 — 받은 스킬 설치. /skill remove 이름 — 내 스킬 지우기 (휴지통).
    --project 를 붙이면 이 프로젝트에만."""
    arg = arg.strip()
    if arg.split(" ", 1)[0] in ("new", "add", "remove"):
        print(f"{D}  Skills are built in; adding your own is not available.{R}\n"); return
    if False:
        name = re.sub(r"[^A-Za-z0-9_-]", "-", arg[4:].strip()).strip("-").lower() or "my-skill"
        dest = (PROMPT_ROOT / ".extra" / "skills" if project else HOME / ".extra" / "skills") / name
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "SKILL.md"
        if not f.exists():
            f.write_text(SKILL_TEMPLATE.format(name=name))
        was = UI.on
        UI.stop()
        subprocess.run([os.environ.get("EDITOR", "nano"), str(f)])
        if was:
            UI.start()
        print(f"{G}✓ skill {name}{R} {D}{f}{R}\n"); return
    if arg.startswith("add "):
        msg = skill_install(arg[4:], project)
        print((G + "✓ " if msg.startswith("installed") else E) + msg + R + "\n"); return
    if arg.startswith("remove "):
        name = arg[7:].strip()
        sk = load_skills().get(name)
        if not sk or str(APP_DIR) in sk["path"]:
            print(f"{E}no skill of yours named {name}{R} {D}(built-in skills cannot be removed){R}\n"); return
        folder = Path(sk["path"]).parent
        trash = HOME / ".Trash" / f"extra-skill-{name}-{time.strftime('%H%M%S')}"
        shutil.move(str(folder), str(trash))
        print(f"{G}✓ removed {name}{R} {D}(moved to the Trash){R}\n"); return
    sks = load_skills()
    if arg:
        if arg not in sks:
            print(f"{E}no skill named {arg}{R} {D}(see /skills){R}"); return
        PENDING_SKILLS.append(arg)
        print(f"{P}✦ {arg}{R} {D}will be used for your next request{R}"); return
    print(f"\n {B}skills{R} {D}(used automatically when your request matches; /skill <name> to use one now){R}")
    for v in sks.values():
        print(f"  {P}{v['name']:<32}{R} {D}{v['description'][:90]}{R}")
    print(f"  {D}/skill <name> uses one for your next request{R}\n")


# ---------------- 설정 메뉴 (사용자 11/15: 명령을 외우지 말고 /set 에서 번호로) ----------------
def ask_line(prompt):
    a = read_answer(f"{P} {prompt} › {R}")
    return (a or "").strip()


def menu(title, rows):
    """rows: [(라벨, 지금 값)] → 고른 번호(1..) 또는 0."""
    print(f"\n {B}{title}{R}")
    for i, (label, value) in enumerate(rows, 1):
        print(f"  {W}{i}{R}  {pad(label, 22)} {D}{value}{R}")
    print(f"  {W}0{R}  {D}back{R}")
    a = ask_line("pick a number")
    return int(a) if a.isdigit() and int(a) <= len(rows) else 0


PERM_LABEL = {"installs": "Install packages", "downloads": "Download files", "writes": "Write and edit files",
              "commands": "Run commands", "dangerous": "Risky commands (rm -r, sudo…)"}


def menu_permissions():
    keys = list(PERM_LABEL)
    while True:
        rows = [(PERM_LABEL[k], SETTINGS[k] + ("   (always = never asks)" if SETTINGS[k] == "always" else "   (ask = asks each time)")) for k in keys]
        rows += [("Allow everything", "never ask"), ("Ask for everything", "ask each time")]
        n = menu("Permissions — pick one to switch between always / ask", rows)
        if not n:
            return
        if n <= len(keys):
            k = keys[n - 1]
            SETTINGS[k] = "ask" if SETTINGS[k] == "always" else "always"
        else:
            for k in keys:
                SETTINGS[k] = "always" if n == len(keys) + 1 else "ask"
        save_settings()
        print(f"  {G}✓ saved{R}  {D}(wiping the whole computer or home folder is always refused){R}")


def menu_thinking():
    while True:
        n = menu("Thinking", [("Effort", f"{SETTINGS['effort']}   (low = fastest · medium · high = most careful)"),
                             ("Verify each step", f"{SETTINGS['review']}   (run and check the real result after each step)")])
        if not n:
            return
        if n == 1:
            m = menu("Effort", [("low", "plan → act"), ("medium", "plan → options → act"), ("high", "plan → options → expect → act")])
            if m:
                SETTINGS["effort"] = ["low", "medium", "high"][m - 1]
        else:
            SETTINGS["review"] = "off" if SETTINGS["review"] == "on" else "on"
        save_settings()
        print(f"  {G}✓ saved{R}")


def menu_skills():
    while True:
        sks = load_skills()
        mine = [v for v in sks.values() if str(APP_DIR) not in v["path"]]
        n = menu("Skills (built in — extra uses them by itself when a request matches)", [("See the skills", f"{len(sks)} built-in")])
        if not n:
            return
        if n == 1:
            names = list(sks)
            m = menu("Skills — pick one to read it", [(v["name"], v["description"][:70]) for v in sks.values()])
            if m:
                v = sks[names[m - 1]]
                print(f"\n {P}✦ {v['name']}{R} {D}{v['path']}{R}")
                for line in v["body"].splitlines()[:40]:
                    print("   " + line)


def menu_instructions():
    while True:
        files = J.prompt_files(PROMPT_ROOT)
        cur = {sc: (f.read_text().strip() if f.is_file() else "") for sc, f in files}
        n = menu("Your instructions (rules extra follows every time)", [
            ("See them", f"every project: {len(cur['global'].splitlines())} lines · this project: {len(cur['project'].splitlines())} lines"),
            ("Add a rule for every project", "for example: write code comments in Korean"),
            ("Add a rule for this project", ""),
            ("Clear the rules for this project", "")])
        if not n:
            return
        if n == 1:
            prompt_command("")
        elif n in (2, 3):
            rule = ask_line("the rule")
            if rule:
                prompt_command(("--global " if n == 2 else "") + "add " + rule)
        else:
            prompt_command("clear")


def menu_language():
    codes = list(LANGS)
    n = menu("Language — which language should extra answer in?", [(LANGS[c][0], "← now" if SETTINGS.get("language", "auto") == c else "") for c in codes])
    if n:
        SETTINGS["language"] = codes[n - 1]; save_settings()
        print(f"  {G}✓ saved{R} {D}(from the next message){R}")


def menu_speed():
    env_ok, running = speed_state()
    state = "on" if env_ok and running else ("on, but restart Ollama to use it" if env_ok else "off")
    n = menu("Speed settings (Ollama: flash attention + smaller memory cache, about 30% faster, same answers)",
             [("Turn on", state)])
    if n == 1:
        speedup_on()


def settings_menu():
    while True:
        perms = " · ".join(f"{k} {SETTINGS[k]}" for k in PERM_LABEL)
        sks = load_skills()
        mine = sum(1 for v in sks.values() if str(APP_DIR) not in v["path"])
        rules = sum(1 for _, f in J.prompt_files(PROMPT_ROOT) if f.is_file() and f.read_text().strip())
        env_ok, running = speed_state()
        n = menu("Settings", [("Language", LANGS.get(SETTINGS.get("language", "auto"), LANGS["auto"])[0]),
                              ("Permissions", perms[:70]),
                              ("Thinking", f"effort {SETTINGS['effort']} · verify {SETTINGS['review']}"),
                              ("Skills", f"{len(sks)} built-in"),
                              ("Your instructions", f"{rules} set" if rules else "none"),
                              ("Speed settings", "on" if env_ok and running else "off")])
        if not n:
            print(); return
        [menu_language, menu_permissions, menu_thinking, menu_skills, menu_instructions, menu_speed][n - 1]()


def busy_command(q):
    """extra 가 일하는 중에 친 /명령: 대화로 보내지 않고 바로 실행한다 (사용자 11/15)."""
    print(f"{P}›{R} {W}{q}{R}")
    if q.startswith("/set"):
        if q[4:].strip():
            set_command(q[4:].strip())
            print(f"{D}  (applies from extra's next step){R}")
        else:
            set_command("")
            print(f"{D}  The settings menu opens when extra is not working (or press Ctrl-C first).{R}")
    elif q == "/help":
        help_command("")
    elif q.startswith("/help "):
        print(f"{D}  /help with a question uses the model, so ask it when extra is not working (or press Ctrl-C first).{R}")
    elif q == "/prompt":
        prompt_command("")
    elif q == "/skills":
        skills_command("")
    elif q in ("/exit", "/quit", "/new", "/continue"):
        print(f"{D}  extra is working. Press Ctrl-C to stop it first, then type {q}.{R}")
    else:
        print(f"{D}  unknown command while working: {q} (see /help){R}")


def next_line():
    """할 일이 없을 때 다음 입력을 기다린다."""
    if not UI.on:
        return input(f"{P}›{R} ").strip()
    import queue as _q
    while True:
        try:
            q = UI.msgs.get(timeout=0.3)
        except _q.Empty:
            continue
        print(f"{P}›{R} {W}{q}{R}")
        return q.strip()


def repl(msgs, first):
    while True:
        if first:
            q, first = first, None
        else:
            try:
                q = next_line()
            except (EOFError, KeyboardInterrupt):
                print(); return
        if not q:
            continue
        if q in ("/exit", "/quit"):
            return
        if q == "/continue":
            h = pick_session()
            if not h:
                continue
            msgs = []
            q = h
        if q.startswith("/prompt"):
            prompt_command(q[7:].strip()); continue
        if q.startswith("/skill "):
            skills_command(q[7:].strip()); continue
        if PENDING_SKILLS and not q.startswith("/"):
            q = q + "\n\n" + "\n\n".join(skill_text(n) for n in PENDING_SKILLS)
            PENDING_SKILLS.clear()
        if q == "/help" or q.startswith("/help "):
            help_command(q[5:]); continue
        if q.startswith("/set") or q in ("/settings", "/skills"):
            arg = q[4:].strip() if q.startswith("/set") and not q.startswith("/settings") else ""
            if arg:
                set_command(arg)
            else:
                settings_menu()
            continue
        if q == "/new":
            msgs = []; print(f"{D}new chat{R}\n"); continue
        UI.busy = True
        UI.redraw()
        try:
            one_turn(msgs, q)
        except KeyboardInterrupt:
            print(f"\n{D}stopped{R}\n")
            while msgs and msgs[-1]["role"] != "user":
                msgs.pop()
            if msgs:
                msgs.pop()
        except Exception as e:
            print(f"{E}error: {type(e).__name__}: {e}{R}\n")
        finally:
            UI.busy = False
            UI.redraw()
            if UI.on and UI.pending:   # 일이 끝날 때까지 안 읽힌 말은 다음 할 일로 (대기 표시는 지운다)
                UI.pending.clear()
                UI.redraw()


if __name__ == "__main__":
    main()
