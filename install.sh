#!/bin/bash
# extra installer (beta) — macOS.
# Installs the program into ~/.extra/app, its Python packages into ~/.extra/venv, the command into ~/.local/bin/extra,
# and the model "extra-beta" into Ollama (Ollama's ministral-3:8b plus extra's settings). Run it again to update.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/.extra/app"
VENV="$HOME/.extra/venv"
BIN="$HOME/.local/bin"
BASE_MODEL="ministral-3:8b"
MODEL="extra-beta"
SKIP_MODEL="${EXTRA_SKIP_MODEL:-0}"       # 1 = do not touch Ollama models (for testing)
SKIP_BROWSER="${EXTRA_SKIP_BROWSER:-0}"   # 1 = do not install a browser for Playwright

b=$'\e[1m'; d=$'\e[2m'; g=$'\e[38;5;114m'; o=$'\e[38;5;214m'; e=$'\e[38;5;203m'; r=$'\e[0m'
step() { printf "\n${b}%s${r}\n" "$1"; }
ok()   { printf "  ${g}✓${r} %s\n" "$1"; }
warn() { printf "  ${o}!${r} %s\n" "$1"; }
die()  { printf "  ${e}✗ %s${r}\n" "$1"; exit 1; }

printf "${b}extra %s — installer${r}\n" "$(cat "$HERE/VERSION")"

step "1/6  Checking this computer"
[ "$(uname -s)" = "Darwin" ] || die "The beta runs on macOS only."
ok "macOS $(sw_vers -productVersion) on $(uname -m)"
MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if [ "$MEM_GB" -lt 16 ]; then warn "${MEM_GB} GB memory: the model needs about 6 GB; 16 GB or more is recommended."; else ok "${MEM_GB} GB memory"; fi
FREE_GB=$(df -g "$HOME" | awk 'NR==2{print $4}')
if [ "$FREE_GB" -lt 10 ]; then warn "${FREE_GB} GB free disk: the model download is 6 GB."; else ok "${FREE_GB} GB free disk"; fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || die "Python 3.9 or newer is needed. Install the Xcode command line tools:  xcode-select --install"
ok "Python $("$PY" -c 'import platform; print(platform.python_version())') ($PY)"
command -v git >/dev/null 2>&1 && ok "git" || warn "git not found: Claude hand-off jobs (extra run) need it. Install with: xcode-select --install"

step "2/6  Ollama (runs the model on this Mac)"
if ! command -v ollama >/dev/null 2>&1 && [ ! -d /Applications/Ollama.app ]; then
  die "Ollama is not installed. Download it from https://ollama.com/download (or: brew install --cask ollama), open it once, then run this installer again."
fi
if ! curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then
  printf "  starting Ollama…\n"
  open -a Ollama 2>/dev/null || (command -v ollama >/dev/null && (nohup ollama serve >/dev/null 2>&1 &))
  for _ in $(seq 1 60); do curl -fsS http://localhost:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
fi
curl -fsS http://localhost:11434/api/version >/dev/null 2>&1 || die "Ollama is not answering. Open the Ollama app, then run this installer again."
ok "Ollama $(curl -fsS http://localhost:11434/api/version | sed -E 's/.*"version":"([^"]+)".*/\1/')"
OLLAMA_BIN="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"

step "3/6  The model"
if [ "$SKIP_MODEL" = "1" ]; then
  warn "skipped (EXTRA_SKIP_MODEL=1)"
elif "$OLLAMA_BIN" list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$MODEL:latest"; then
  ok "$MODEL is already installed"
else
  if ! "$OLLAMA_BIN" list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$BASE_MODEL"; then
    printf "  downloading %s (about 6 GB, once)…\n" "$BASE_MODEL"
    "$OLLAMA_BIN" pull "$BASE_MODEL"
  fi
  "$OLLAMA_BIN" create "$MODEL" -f "$HERE/Modelfile" >/dev/null
  ok "$MODEL created from $BASE_MODEL"
fi

step "4/6  The program"
mkdir -p "$APP"
for f in extra_cli.py extra_input.py extra_jobs.py extra_core.py extra_help.md VERSION; do cp "$HERE/$f" "$APP/$f"; done
rm -rf "$APP/skills"; cp -R "$HERE/skills" "$APP/skills"
ok "installed in ~/.extra/app"

step "5/6  Python packages (syntax colors, browser checks)"
if [ ! -x "$VENV/bin/python" ]; then "$PY" -m venv "$VENV"; fi
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
if "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$HERE/requirements.txt"; then
  ok "pygments, playwright"
else
  warn "could not install the packages (offline?). extra still works; code colors and browser checks need them. Run this installer again later."
fi
if [ "$SKIP_BROWSER" != "1" ] && [ ! -d "/Applications/Google Chrome.app" ] && "$VENV/bin/python" -c "import playwright" 2>/dev/null; then
  printf "  Google Chrome not found: downloading a browser for page checks (about 150 MB)…\n"
  "$VENV/bin/python" -m playwright install chromium >/dev/null 2>&1 && ok "Chromium for Playwright" || warn "browser download failed; page checks will not work until it succeeds"
else
  ok "browser for page checks: $([ -d "/Applications/Google Chrome.app" ] && echo "Google Chrome" || echo "skipped")"
fi

step "6/6  The extra command"
mkdir -p "$BIN"
cat > "$BIN/extra" <<EOF
#!/bin/bash
exec "$VENV/bin/python" "$APP/extra_cli.py" "\$@"
EOF
chmod +x "$BIN/extra"
ok "$BIN/extra"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    RC="$HOME/.zshrc"; [ "${SHELL##*/}" = "bash" ] && RC="$HOME/.bash_profile"
    if ! grep -qs 'extra installer: PATH' "$RC"; then
      printf '\n# extra installer: PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
    fi
    warn "added ~/.local/bin to your PATH in $RC — open a new terminal window (or run: source $RC)"
    ;;
esac

printf "\n${g}${b}Done.${r} Open a project folder and start:\n\n    cd ~/my-project\n    extra\n\n${d}The first start asks five quick settings. Uninstall: bash %s/uninstall.sh${r}\n" "$HERE"
