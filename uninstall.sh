#!/bin/bash
# extra uninstaller: removes the program, its Python packages and the command. Your projects are not touched.
# Asks before removing your settings (~/.extra) and the model.
set -uo pipefail
b=$'\e[1m'; g=$'\e[38;5;114m'; r=$'\e[0m'

printf "${b}Uninstall extra${r}\n"
rm -f "$HOME/.local/bin/extra"
rm -rf "$HOME/.extra/app" "$HOME/.extra/venv"
printf "  ${g}✓${r} removed the program, its Python packages and the extra command\n"

read -r -p "  Also remove your extra settings and logs in ~/.extra? [y/N] " a
if [[ "$a" =~ ^[Yy] ]]; then rm -rf "$HOME/.extra"; printf "  ${g}✓${r} removed ~/.extra\n"; fi

if command -v ollama >/dev/null 2>&1; then
  read -r -p "  Also remove the model extra-beta from Ollama? [y/N] " a
  if [[ "$a" =~ ^[Yy] ]]; then
    ollama rm extra-beta >/dev/null 2>&1
    printf "  ${g}✓${r} removed extra-beta\n"
    read -r -p "  And its base model ministral-3:8b (frees about 6 GB; say no if you use it yourself)? [y/N] " a
    if [[ "$a" =~ ^[Yy] ]]; then ollama rm ministral-3:8b >/dev/null 2>&1; printf "  ${g}✓${r} removed ministral-3:8b\n"; fi
  fi
fi

AGENT="$HOME/Library/LaunchAgents/com.extra.ollama-speed.plist"
if [ -f "$AGENT" ]; then
  read -r -p "  Also turn off the Ollama speed settings extra added? [y/N] " a
  if [[ "$a" =~ ^[Yy] ]]; then
    rm -f "$AGENT"; launchctl unsetenv OLLAMA_FLASH_ATTENTION; launchctl unsetenv OLLAMA_KV_CACHE_TYPE
    printf "  ${g}✓${r} turned off (restart Ollama to apply)\n"
  fi
fi
printf "Done. The PATH line in your shell profile (marked 'extra installer') is harmless; delete it if you like.\n"
