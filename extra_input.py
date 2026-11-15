"""extra 아래 입력창 (사용자 11/14). Claude Code 와 같은 그리기 방식:
스크롤 영역이나 절대 위치를 쓰지 않는다. 끝난 출력은 평소처럼 위로 쌓이고(스크롤로 남는다), 맨 아래 '살아 있는 부분'만
매번 지우고 다시 그린다. 살아 있는 부분 = 지금 쓰는 중인 줄 + 흐르는 칸(생각·명령 출력) + 기다림 표시 + 구분선 + 입력줄 + 안내줄.
모든 줄은 화면 폭 안으로 자르므로 터미널이 줄을 다시 접지 않는다. 창 크기가 바뀌면 화면을 지우고 최근 출력과 함께 다시 그린다.
입력한 줄은 상황에 따라 간다: 권한 질문의 대답 / 실행 중인 명령의 입력 / extra 에게 하는 말."""
import codecs, collections, os, queue, re, shutil, signal, sys, termios, threading, tty, unicodedata

P, D, R = "\x1b[38;5;141m", "\x1b[38;5;244m", "\x1b[0m"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]")


def cw(c):
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def width(s):
    return sum(cw(c) for c in ANSI.sub("", s))


def cut(s, n):
    """색 코드는 살리고, 보이는 글자 폭이 n 을 넘지 않게 자른다."""
    out, w, i = [], 0, 0
    while i < len(s):
        m = ANSI.match(s, i)
        if m:
            out.append(m.group()); i = m.end(); continue
        c = "    " if s[i] == "\t" else s[i]
        k = sum(cw(x) for x in c)
        if w + k > n:
            out.append("…" if n - w >= 1 else "")
            break
        out.append(c); w += k; i += 1
    return "".join(out) + R


class _Out:
    """sys.stdout 대신: 다 쓴 줄은 위로 쌓고, 쓰는 중인 줄은 살아 있는 부분에 둔다."""
    def __init__(self, ui, real):
        self.ui, self.real = ui, real

    def write(self, t):
        self.ui.feed(t)
        return len(t)

    def flush(self):
        pass

    def isatty(self):
        return True

    def fileno(self):
        return self.real.fileno()


class BottomInput:
    def __init__(self):
        self.on = False
        self.lock = threading.RLock()
        self.buf = ""
        self.msgs = queue.Queue()      # extra 에게 하는 말
        self.answers = queue.Queue()   # 권한 질문의 대답
        self.asking = False
        self.proc = None               # 지금 실행 중인 명령
        self.wants_input = False       # 그 명령이 지금 대답을 기다리나 ([y/N], ? 로 끝난 출력) — 그때만 입력을 명령에 넘긴다
        self.busy = False              # extra 가 일하는 중
        self.on_expand = None          # Ctrl-O 로 부를 펼치기
        self.on_line = None            # 화면에 확정된 줄마다 불린다 (전체 기록 파일에 쓰기)
        self.on_command = None         # 일하는 중에 친 /명령 (대화로 보내지 않고 바로 실행)
        self.pending = []              # 일하는 중에 보낸 말: extra 가 읽을 때까지 '대기 중' 으로 아래에 보인다
        self.real = sys.stdout
        self.partial = ""              # 아직 줄이 안 끝난 글
        self.box = []                  # 흐르는 칸의 줄들 (생각, 명령 출력, 파일 쓰기)
        self.status = ""               # 기다림 표시
        self.history = collections.deque(maxlen=3000)   # 창 크기가 바뀌면 다시 그릴 최근 출력
        self.up = 0                    # 지난번 살아 있는 부분에서 커서 위로 몇 줄이 있었나
        self.size = (0, 0)
        self.top = 1                   # 살아 있는 부분의 맨 윗줄이 화면 몇 번째 줄에 있나 (입력창을 맨 아래에 붙이려고)
        self.timer = None

    # ---------- 켜고 끄기 ----------
    def start(self):
        if self.on or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)                     # 글자를 바로 받고, 터미널이 따라 찍지 않게 (Ctrl-C 는 그대로)
        att = termios.tcgetattr(self.fd)           # macOS 는 Ctrl-O(출력 버리기)·Ctrl-V 를 먼저 가로챈다 → 꺼서 extra 가 받게 (11/15: Ctrl-O 가 안 됐다)
        att[3] &= ~termios.IEXTEN
        termios.tcsetattr(self.fd, termios.TCSANOW, att)
        self.real = sys.stdout
        self.size = self._term()
        self.top = self._cursor_row()
        self.on = True
        sys.stdout = _Out(self, self.real)
        signal.signal(signal.SIGWINCH, lambda *_: self._resized())
        threading.Thread(target=self._reader, daemon=True).start()
        self.render()
        return True

    def stop(self):
        if not self.on:
            return
        with self.lock:
            self.on = False
            self.real.write(self._erase() + (self.partial + "\n" if self.partial else ""))
            self.real.flush()
            sys.stdout = self.real
            self.partial, self.box, self.status, self.up = "", [], "", 0
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def _cursor_row(self):
        """터미널에 지금 커서가 몇 번째 줄인지 묻는다 (ESC[6n → ESC[줄;칸R). 모르면 맨 아래로 친다."""
        import select
        try:
            self.real.write("\x1b[6n"); self.real.flush()
            got, end = b"", __import__("time").time() + 0.5
            while __import__("time").time() < end:
                r, _, _ = select.select([self.fd], [], [], 0.05)
                if r:
                    got += os.read(self.fd, 64)
                    m = re.search(rb"\x1b\[(\d+);(\d+)R", got)
                    if m:
                        return int(m.group(1))
        except OSError:
            pass
        return self.size[1]

    def _resized(self):
        """창 크기를 바꾸는 동안 신호가 여러 번 온다: 잠깐 모았다가 한 번만 다시 그린다."""
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(0.12, lambda: self.render(resized=True))
        self.timer.daemon = True
        self.timer.start()

    def _rows(self, line):
        """한 줄이 화면에서 몇 줄을 차지하나 (긴 줄은 터미널이 접는다)."""
        cols = max(1, self.size[0])
        return max(1, -(-width(line) // cols))

    def _term(self):
        try:
            s = os.get_terminal_size(self.real.fileno())
            return s.columns, s.lines
        except OSError:
            return tuple(shutil.get_terminal_size())

    def rows_free(self):
        return max(5, self.size[1] - 6) if self.on else shutil.get_terminal_size().lines

    # ---------- 그리기 ----------
    def _erase(self):
        """지난번에 그린 살아 있는 부분을 지운다 (그 맨 윗줄 처음으로 가서 아래를 모두 지운다)."""
        return (f"\x1b[{self.up}A" if self.up else "") + "\r\x1b[J"

    def _live_lines(self):
        cols = self.size[0]
        w = max(10, cols - 1)
        lines = []
        if self.partial:
            lines.append(cut(self.partial, w))
        lines += [cut(l, w) for l in self.box]
        for m in self.pending:          # 보냈지만 아직 안 읽은 말
            lines.append(cut(f"{P}↳ you:{R} {m}  {D}· waiting — extra reads it at its next step{R}", w))
        if self.status:
            lines.append(cut(self.status, w))
        hint = ("" if self.asking else      # 질문 중에는 비운다: 번호 질문에 y/a/n 안내가 헷갈린다 (사용자 11/15)
                "the command is asking — what you type goes to it" if (self.proc and self.wants_input) else
                "a command is running — type to tell extra something; it reads it after the command" if self.proc else
                "working — type to change or add something; extra reads it at its next step" if self.busy else
                "/help commands · /exit quit")
        shown = self.buf
        while width(shown) > w - 3:
            shown = shown[1:]
        bg = "\x1b[48;5;236m"
        lines.append(f"{P}{'━' * w}{R}")
        lines.append(f"{bg}{P}› {R}{bg}{shown}{' ' * max(0, w - 2 - width(shown))}{R}")
        lines.append(cut(f"{D} {hint}", w))
        return lines, 3 + width(shown)

    def render(self, new_lines=(), resized=False):
        if not self.on:
            return
        with self.lock:
            size = self._term()
            out = []
            if resized or size != self.size:
                # 창 크기가 바뀌면 터미널이 예전 줄을 새 폭으로 다시 접고, macOS 터미널은 지운 화면을 스크롤 기록으로 밀어 올린다
                # (그래서 입력창이 위로 여러 개 쌓였다). 스크롤 기록까지 지우고 지금까지의 출력을 새 폭으로 처음부터 다시 그린다.
                self.size = size
                out.append("\x1b[3J\x1b[H\x1b[2J")
                hist = list(self.history)
                out.append("".join(l + R + "\x1b[K\n" for l in hist))
                used = sum(self._rows(l) for l in hist)
                self.top = min(size[1], used + 1)
            else:
                out.append(self._erase())
            for l in new_lines:
                out.append(l + R + "\x1b[K\n")
                self.top += self._rows(l)
            live, col = self._live_lines()
            rows = size[1]
            # 입력창을 화면 맨 아래에 붙인다: 출력이 적으면 그 사이를 빈 줄로 채운다
            pad = rows - (self.top - 1) - len(live) if self.top - 1 + len(live) < rows else 0
            if self.top > rows:
                self.top = rows
            live = live[:-3] + [""] * max(0, pad) + live[-3:]
            out.append("\n".join(live))
            out.append(f"\x1b[1A\r\x1b[{col}C")          # 커서는 입력줄에 (한글 조합 글자가 여기 보인다)
            self.up = len(live) - 2
            # 화면을 넘치면 터미널이 위로 스크롤한다: 살아 있는 부분의 맨 윗줄 위치를 다시 계산
            self.top = max(1, min(self.top, rows - len(live) + 1))
            self.real.write("".join(out))
            self.real.flush()

    def feed(self, t):
        """print 로 들어온 글: 다 쓴 줄은 위로 쌓고, 나머지는 쓰는 중인 줄로."""
        with self.lock:
            t = re.sub(r"\x1b\[\d*[FAJK]|\x1b\[2K|\x1b[78]", "", t)      # 예전 방식의 커서 이동은 버린다
            parts = (self.partial + t).split("\n")
            done, self.partial = parts[:-1], parts[-1]
            if "\r" in self.partial:
                self.partial = self.partial.split("\r")[-1]
            done = [d.split("\r")[-1] for d in done]
            self.history.extend(done)
            if self.on_line:                 # 전체 기록 파일에도 (extra log)
                for d in done:
                    self.on_line(d)
            self.render(done)

    def set_box(self, lines):
        with self.lock:
            self.box = list(lines)
            self.render()

    def set_status(self, text):
        with self.lock:
            self.status = text
            self.render()

    def redraw(self):
        self.render()

    # ---------- 키 읽기 ----------
    def _reader(self):
        dec = codecs.getincrementaldecoder("utf-8")(errors="ignore")
        esc = ""
        while self.on:
            try:
                data = os.read(self.fd, 256)
            except OSError:
                return
            if not data:
                return
            for ch in dec.decode(data):
                if esc:                                  # 방향키 같은 것은 버린다
                    esc += ch
                    if len(esc) > 1 and (ch.isalpha() or ch == "~"):
                        esc = ""
                    continue
                if ch == "\x1b":
                    esc = ch
                elif ch in ("\r", "\n"):
                    line, self.buf = self.buf, ""
                    self._route(line)
                elif ch in ("\x7f", "\b"):
                    self.buf = self.buf[:-1]
                elif ch == "\x15":                       # Ctrl-U: 줄 지우기
                    self.buf = ""
                elif ch >= " " or ch == "\t":
                    self.buf += ch
            self.render()

    def _route(self, line):
        if self.asking:
            self.answers.put(line)
        elif self.proc is not None and self.proc.poll() is None and self.proc.stdin and self.wants_input:
            try:
                self.proc.stdin.write((line + "\n").encode()); self.proc.stdin.flush()
                sys.stdout.write(f"{D}  │ ‹ {line}{R}\n")
            except OSError:
                pass
        else:
            if not line.strip():
                return
            if self.busy and line.strip().startswith("/") and self.on_command:   # 일하는 중의 /set, /show, /help … 는 바로 실행
                self.on_command(line.strip())
                return
            self.msgs.put(line)
            if self.busy:
                self.pending.append(line)
                self.render()

    # ---------- 쓰는 쪽 ----------
    def ask(self, prompt):
        """권한 질문: 아래 칸에 친 대답을 기다린다."""
        self.asking = True
        sys.stdout.write(prompt + "\n")
        try:
            return self.answers.get()
        finally:
            self.asking = False
            self.render()

    def take_messages(self):
        """extra 가 다음 단계에서 읽는다: '대기 중' 을 지우고 '읽음' 으로 남긴다."""
        out = []
        while True:
            try:
                out.append(self.msgs.get_nowait())
            except queue.Empty:
                break
        if out and self.on:
            with self.lock:
                for m in out:
                    if m in self.pending:
                        self.pending.remove(m)
                    sys.stdout.write(f"{P}↳ you:{R} {m}  \x1b[38;5;114m✓ read{R}\n")
        return out


UI = BottomInput()
