"""extra 공동 작업 (사용자 11/14).
Claude 가 할 일이 많을 때, 놀고 있는 extra 에게 문제 하나를 넘긴다. extra 는 프로젝트 복사본에서 혼자 끝까지
(생각 → 실행 → 테스트 → 실패 이유 → 다른 길) 풀고, 결과를 바뀐 내용(patch)으로 남긴다.
Claude 는 기다리지 않고 자기 일을 하다가, 끝났다는 알림을 받으면 검토해서 쓰거나(extra apply) 이유와 함께 다시 보낸다(--feedback).

복사본과 결과는 ~/.extra/jobs/<프로젝트>/<번호>/ 에 둔다 (프로젝트 폴더를 어지럽히지 않게).
  job.json     할 일, 상태, 회차
  work/        extra 가 일하는 복사본 (처음 상태를 git 'base' 로 남겨 둔다)
  log.txt      extra 의 생각과 도구 실행 전부
  progress.md  시도 기록 (무엇을 했고 왜 실패했는지) — Claude 가 이어받을 때 쓴다
  result.md    결과 요약, result.patch  바뀐 내용
"""
import hashlib, json, os, re, secrets, shlex, subprocess, tempfile, time
from pathlib import Path

HOME = Path.home()
BIG = ("node_modules", ".venv", "venv", "env")           # 복사하지 않고 연결만 한다 (테스트 실행에 필요)
NOCOPY_ANY = (".git", ".extra", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store", "node_modules", ".venv")
NOCOPY_TOP = ("/venv", "/env", "/dist", "/build")


def jobs_root(project):
    project = Path(project).resolve()
    h = hashlib.sha1(str(project).encode()).hexdigest()[:8]
    return HOME / ".extra" / "jobs" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', project.name)[:40]}-{h}"


def git(args, cwd, **kw):
    return subprocess.run(["git", "-c", "user.name=extra", "-c", "user.email=extra@local", *args], cwd=cwd, capture_output=True, **kw)


def save(d, job):
    (Path(d) / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))


def find(project, jid):
    """번호 앞부분이나 'last' 로도 찾는다."""
    root = jobs_root(project)
    ds = sorted([x for x in root.glob("*") if (x / "job.json").is_file()], key=lambda x: x.name) if root.exists() else []
    if jid in ("last", "", None):
        hit = ds[-1:]
    else:
        hit = [x for x in ds if x.name == jid] or [x for x in ds if x.name.startswith(jid) or x.name.endswith(jid)]
    if len(hit) != 1:
        raise SystemExit(f"job '{jid}' not found" + (" (more than one match)" if len(hit) > 1 else "") + ". See: extra jobs")
    return hit[0], json.loads((hit[0] / "job.json").read_text())


def new_job(project, task, test="", minutes=30, prompt="", files=""):
    project = Path(project).resolve()
    jid = time.strftime("%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    d = jobs_root(project) / jid
    work = d / "work"
    work.mkdir(parents=True)
    # 프로젝트의 지금 상태 그대로 복사 (아직 commit 하지 않은 Claude 의 수정도 들어간다)
    ex = sum((["--exclude", x] for x in NOCOPY_ANY + NOCOPY_TOP), [])
    subprocess.run(["rsync", "-a", *ex, f"{project}/", f"{work}/"], check=True)
    for b in BIG:
        if (project / b).exists():
            (work / b).symlink_to(project / b)
    git(["init", "-q"], work)
    (work / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (work / ".git" / "info" / "exclude").write_text("\n".join(BIG + ("__pycache__/", ".pytest_cache/", "*.pyc", ".DS_Store")) + "\n")
    git(["add", "-A"], work)
    git(["commit", "-q", "--allow-empty", "-m", "base"], work)
    job = {"id": jid, "project": str(project), "task": task, "test": test, "minutes": int(minutes), "prompt": prompt, "files": files,
           "status": "running", "created": time.strftime("%F %T"), "rounds": [], "pid": os.getpid(),
           "from": "claude" if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_SESSION_ID") else "user"}
    save(d, job)
    return d, job


def task_text(job, work):
    parts = ["[Background job from Claude, the user's main AI assistant. Claude is busy with other parts of this project and handed this "
             "problem to you so that no time is wasted. You work ALONE in a private copy of the project (your working directory). "
             "Nobody will answer questions: decide yourself and keep going until it is solved. Your changes go back to Claude as a patch, and "
             "Claude reviews them before using them.",
             "Task:\n" + job["task"].strip()]
    if job.get("files"):
        parts.append("Files to focus on: " + job["files"])
    if job.get("test"):
        parts.append(f"Done means this command passes (exit code 0). Run it yourself with run_command to check: {job['test']}")
    if job.get("prompt"):
        parts.append("Extra instructions from Claude for this job:\n" + job["prompt"].strip())
    parts.append("Take your time: try one way, run it, read the real output, and if it fails find why and try another way. "
                 "Change only what the task needs; do not reformat unrelated code. When finished, reply with a short summary: "
                 "what you changed, why, how you verified it, and anything Claude should double-check.]")
    return "\n\n".join(parts)


def feedback_text(fb):
    return ("[Claude reviewed your result and sent it back.\nReason: " + fb.strip() + "\n"
            "Your earlier changes are still in this folder. Fix the problem, run the test again, and finish with a short summary.]")


def changes(work):
    git(["add", "-A"], work)
    names = git(["diff", "--cached", "--name-status", "--no-renames", "HEAD"], work, text=True).stdout.split("\n")
    out = []
    for line in names:
        if "\t" in line:
            st, path = line.split("\t", 1)
            out.append((st[0], path))
    return out


def finish(d, job, status, summary, test_out=""):
    d, work = Path(d), Path(d) / "work"
    ch = changes(work)
    patch = git(["diff", "--cached", "--binary", "HEAD"], work).stdout
    (d / "result.patch").write_bytes(patch)
    stat = git(["diff", "--cached", "--stat", "HEAD"], work, text=True).stdout.strip()
    job["status"], job["finished"] = status, time.strftime("%F %T")
    job["changed"] = [p for _, p in ch]
    save(d, job)
    took = (time.time() - time.mktime(time.strptime(job["created"], "%Y-%m-%d %H:%M:%S"))) / 60
    lines = [f"# extra job {job['id']} — {status.upper()}",
             f"Task: {job['task'].strip()[:300]}",
             f"Time: {took:.0f} min since start · rounds: {len(job['rounds'])}"]
    if job.get("test"):
        lines.append(f"Test: {job['test']} → {'passed' if status == 'passed' else 'NOT passing'}")
        if status != "passed" and test_out:
            lines.append("Last test output (end):\n" + test_out[-1500:])
    lines.append("Changed files:\n" + (stat or "(none)"))
    lines.append("Summary from extra:\n" + (summary.strip()[:2500] or "(no summary)"))
    prog = d / "progress.md"
    if status not in ("passed", "done") and prog.is_file():
        lines.append("What extra tried (last steps):\n" + "\n".join(prog.read_text().splitlines()[-15:]))
    lines.append(f"Review the diff:  extra show {job['id']}\nUse it:           extra apply {job['id']}\n"
                 f"Send it back:     extra run --job {job['id']} --feedback \"what is wrong and why\"")
    text = "\n\n".join(lines)
    (d / "result.md").write_text(text)
    return text


def apply(project, jid, force=False):
    """복사본에서 바뀐 파일을 프로젝트로 옮긴다. Claude 가 그사이 같은 파일을 고쳤으면 3-way 로 합치고, 겹치면 아무것도 바꾸지 않는다."""
    project = Path(project).resolve()
    d, job = find(project, jid)
    work = d / "work"
    plan, conflicts = [], []
    for st, path in changes(work):
        w, r = work / path, project / path
        base = git(["show", f"HEAD:{path}"], work).stdout if st != "A" else None
        cur = r.read_bytes() if r.is_file() else None
        new = w.read_bytes() if st != "D" else None
        if cur == new:
            continue                                      # 이미 같다
        if st == "D":
            plan.append(("delete", r, None)) if cur == base else conflicts.append(path)
        elif cur is None and st == "A":
            plan.append(("write", r, new))
        elif cur == base:
            plan.append(("write", r, new))
        elif base is not None and cur is not None:
            with tempfile.TemporaryDirectory() as td:     # 둘 다 고쳤다: 3-way 합치기
                fc, fb, fn = (Path(td) / n for n in ("cur", "base", "new"))
                fc.write_bytes(cur); fb.write_bytes(base); fn.write_bytes(new)
                m = subprocess.run(["git", "merge-file", "-p", str(fc), str(fb), str(fn)], capture_output=True)
            if m.returncode == 0:
                plan.append(("write", r, m.stdout))
            else:
                conflicts.append(path)
        else:
            conflicts.append(path)
    if conflicts and not force:
        return (f"Not applied: these files were also changed in the project in a way that overlaps extra's changes:\n  " + "\n  ".join(conflicts)
                + f"\nLook at the diff (extra show {job['id']}) and merge by hand, or send it back with --feedback.")
    for act, r, data in plan:
        if act == "delete":
            r.unlink(missing_ok=True)
        else:
            r.parent.mkdir(parents=True, exist_ok=True)
            r.write_bytes(data)
    job["applied"] = time.strftime("%F %T")
    save(d, job)
    return f"Applied job {job['id']}: {len(plan)} file(s) changed in {project}" + (f" (skipped conflicts: {', '.join(conflicts)})" if conflicts else "")


def ago(ts):
    s = time.time() - ts
    return f"{int(s // 60)}m ago" if s < 3600 else f"{int(s // 3600)}h ago" if s < 86400 else f"{int(s // 86400)}d ago"


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def list_jobs(project):
    root = jobs_root(project)
    rows = []
    for d in sorted(root.glob("*")) if root.exists() else []:
        try:
            job = json.loads((d / "job.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        st = job["status"]
        if st == "running" and not alive(job.get("pid")):
            st = "stopped"
        rows.append((job["id"], st + (" · applied" if job.get("applied") else ""), ago((d / "job.json").stat().st_mtime),
                     job["task"].strip().split("\n")[0][:70], job.get("from", "claude")))
    return rows


def show(project, jid, max_lines=400):
    d, job = find(project, jid)
    res = (d / "result.md").read_text() if (d / "result.md").is_file() else f"job {job['id']} is {job['status']} (no result yet)"
    if job["status"] == "running" and (d / "progress.md").is_file():
        res += "\n\nProgress so far:\n" + "\n".join((d / "progress.md").read_text().splitlines()[-20:])
    patch = (d / "result.patch").read_text(errors="replace").splitlines() if (d / "result.patch").is_file() else []
    if patch:
        res += "\n\nDiff:\n" + "\n".join(patch[:max_lines]) + (f"\n… {len(patch) - max_lines} more lines" if len(patch) > max_lines else "")
    return res


def parse_run(argv):
    """extra run "할 일" [--test CMD] [--minutes N] [--prompt TEXT] [--files A,B]   /   extra run --job ID --feedback "이유" """
    o = {"task": [], "test": "", "minutes": 30, "prompt": "", "files": "", "job": "", "feedback": ""}
    i = 0
    while i < len(argv):
        a = argv[i]
        key = a[2:] if a.startswith("--") else None
        if key in ("test", "minutes", "prompt", "files", "job", "feedback") and i + 1 < len(argv):
            o[key] = argv[i + 1]
            i += 2
            continue
        o["task"].append(a)
        i += 1
    o["task"] = " ".join(o["task"]).strip()
    o["minutes"] = max(1, min(240, int(o["minutes"])))
    if not o["task"] and not o["job"]:
        raise SystemExit('usage: extra run "task" [--test "command"] [--minutes 30] [--files a.py,b.py] [--prompt "extra instructions"]\n'
                         '       extra run --job ID --feedback "what is wrong and why"')
    return o


# ---------------- 사용자 프롬프트 (기본 규칙과 겹쳐 망가지지 않게) ----------------
PROMPT_MAX = 3000
CONFLICT = [
    (r"(don'?t|do not|never|no)\s+(use|call)\s+(any\s+)?tools?|도구\S*\s*(쓰지|사용하지|부르지)\s*마", "extra only works through tools"),
    (r"(don'?t|do not|never|no)\s+think|no\s*<think>|생각\S*\s*(하지|쓰지)\s*마", "the thinking step is part of how extra works"),
    (r"(skip|don'?t run|do not run|no)\s+(the\s+)?(tests?|testing|verification)|테스트\S*\s*(하지|돌리지)\s*마|확인\S*\s*하지\s*마", "extra must run and verify its work"),
    (r"(just|only)\s+(paste|print|show)\s+(the\s+)?code|코드만\s*(보여|출력)", "deliverables are saved files, not pasted code"),
    (r"(ignore|forget|override)\s+(all\s+|the\s+|your\s+)?(previous|above|system|core)\s+(rules|instructions)|위\s*(규칙|지시)\S*\s*무시", "core rules cannot be switched off"),
]


def prompt_files(project):
    return [("global", HOME / ".extra" / "prompt.md"), ("project", Path(project) / ".extra" / "prompt.md")]


def conflicts_in(text):
    out = []
    for line in text.splitlines():
        for pat, why in CONFLICT:
            if re.search(pat, line, re.I):
                out.append((line.strip()[:80], why))
    return out


def prompt_block(project, job_prompt=""):
    """시스템 글 맨 끝에 붙일 사용자 지시. 기본 규칙보다 아래에 두고, 겹치면 기본 규칙이 이긴다고 못 박는다."""
    parts = []
    for scope, f in prompt_files(project):
        if f.is_file():
            t = f.read_text(errors="replace").strip()[:PROMPT_MAX]
            if t:
                parts.append(f"({scope})\n{t}")
    if not parts:
        return ""
    return ("\n\nTHE USER'S OWN INSTRUCTIONS (follow them for style, preferences and project conventions). They add to the rules above and "
            "never replace the core rules: always act through real tool calls, think in English in the Plan/Act format, run and verify before "
            "claiming success, stay inside the project folder, be safe and honest. If one of them conflicts with a core rule, follow the core rule "
            "and say so in one short sentence.\n<<<\n" + "\n\n".join(parts) + "\n>>>")
