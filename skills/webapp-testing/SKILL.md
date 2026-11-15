---
name: webapp-testing
description: Test local web apps for real with Playwright in headless Chrome — check what the page shows, click and type, read console logs.
triggers: verify, check, test, browser, page, website, web app, webapp, game, headless, playwright, screenshot, console, 확인, 검증, 테스트, 게임
source: Adapted from anthropics/skills — skills/webapp-testing (https://github.com/anthropics/skills). Copyright 2026 Anthropic, PBC. Licensed under the Apache License 2.0; see LICENSE.txt. Changes: the bundled helper scripts are not included, so this version shows how to start the server and Playwright directly; shortened.
---

# Web Application Testing

To test a local web app, write a native Python Playwright script. You cannot see a browser window, so the script must print
what it finds.

Playwright comes with extra: run your script with `~/.extra/venv/bin/python`. Launch the browser with
`p.chromium.launch(channel="chrome", headless=True)` (uses Google Chrome); if Chrome is not installed, use
`p.chromium.launch(headless=True)`. If the task already has a check script, run that and never change it.

## Decision tree
```
Task → Is it static HTML (no build step)?
  ├─ Yes → read the HTML to find selectors → write the Playwright script (serve the folder, see below)
  └─ No (dynamic app) → is its dev server already running?
       ├─ No  → start it in the background (extra runs servers in the background), then run the script
       └─ Yes → reconnaissance, then action:
            1. go to the page and wait for networkidle
            2. inspect the DOM (page.content(), locators) or save a screenshot
            3. find selectors from the rendered state
            4. act with those selectors and print the results
```

## Template
```python
import functools, http.server, socketserver, threading, sys
from playwright.sync_api import sync_playwright

# serve this folder (JavaScript modules do not load from file://)
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory="."))
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/"

errors = []
with sync_playwright() as p:
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)   # always headless
    except Exception:
        browser = p.chromium.launch(headless=True)                     # no Google Chrome: Playwright's own Chromium
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    page.goto(url)
    page.wait_for_load_state("networkidle")       # CRITICAL: wait for JavaScript to run
    print("title:", page.title())
    print("status:", page.text_content("#status"))   # print what the page shows
    # interact: page.fill("#amount", "1000"); page.click("text=Convert"); page.keyboard.press("ArrowUp")
    print("errors:", errors[:5])
    browser.close()
srv.shutdown()
sys.exit(1 if errors else 0)
```
Run it with `~/.extra/venv/bin/python your_check.py`.

## Common pitfall
- Don't inspect the DOM before `page.wait_for_load_state("networkidle")` on a dynamic app.

## Best practices
- Use `sync_playwright()`; always close the browser.
- Use clear selectors: `text=`, `role=`, CSS selectors or IDs.
- Add waits where needed: `page.wait_for_selector(...)` or `page.wait_for_timeout(...)`.
- Print what you saw (text, classes, values), so a failure tells you what to fix.
- To test offline behaviour, block outside requests: `context.route(re.compile(r"^https?://(?!127\.0\.0\.1).*"), lambda r: r.abort())`.
- For games or canvas apps, have the app expose its state (for example `window.game`) and read it with `page.evaluate(...)`.
