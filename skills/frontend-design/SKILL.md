---
name: frontend-design
description: Distinctive, intentional visual design when building a new UI or reshaping one — aesthetic direction, typography, layout, copy.
triggers: design, ui, ux, css, style, page, website, landing, layout, beautiful, pretty, sophisticated, look, 디자인, 예쁘게, 화면, 웹페이지, 세련
source: Adapted from anthropics/skills — skills/frontend-design (https://github.com/anthropics/skills). Licensed under the Apache License 2.0; see LICENSE.txt. Changes: shortened for a small local model; removed parts that do not apply in extra.
---

# Frontend Design

Approach this as the design lead at a studio known for giving every client a distinct visual identity. Make deliberate,
opinionated choices about palette, typography and layout that are specific to this brief, not templated defaults.

## Ground the design in the subject
If the brief does not say what the product is, name one concrete subject, its audience and the design's main job yourself.
The subject's industry, materials and vernacular are where distinctive choices come from — a toy for children and a dashboard
for analysts look very different. Use the brief's real content throughout.

## Principles
- The hero is the first thing people see. Open with the most characteristic thing in the subject's world (a headline, an image,
  a live demo, an interactive moment). "Big number + small label + gradient accent" is the default — use it only if truly best.
- Typography carries the personality. One family or two clearly distinct ones. Set a clear type scale with deliberate weights.
- Keep line length under 80 characters.
- Avoid the commonest tells of a generated page: accenting one word of a headline in another color or italic; ALL-CAPS labels;
  unnecessary little labels above content.
- Visual structure is information: borders, numbering, dividers and labels must encode something. Use numbered markers
  (01 / 02 / 03) only when the content really is a sequence.
- Use motion sparingly: one orchestrated moment beats a fade-in on every section. Motion that answers a person's action
  (open, expand, confirm) is welcome when it shows what changed.

## Defaults to avoid unless the brief asks for them
1. warm cream background with a serif display and a terracotta accent;
2. near-black background with one acid-green or vermilion accent;
3. broadsheet look with hairline rules and zero border-radius;
4. the SaaS-card kit: identical rounded cards, one radius everywhere, the same soft grey shadow, gradient washes;
5. template chrome: an ALL-CAPS eyebrow above every heading, "A · B · C" meta strings, a monospace face for small labels,
   a "→" appended to every link.
When the brief pins down a direction, follow it exactly — the brief always wins.

## Process: plan, review, build, critique
1. Write a short design plan first: 4–6 named hex colors; the typefaces and their roles; a layout concept (one sentence plus a
   small ASCII wireframe, and whether content is left-aligned or centered); the principles that make this page unique.
2. Review the plan against the brief: if a part reads like the default you would make for any similar page, change it and say why.
3. Then write the code. Watch CSS specificity — classes that cancel each other out (often padding/margin between sections).

## Restraint and quality floor
Spend your boldness in one place; keep everything around it quiet. Always: responsive down to phone width (390px), visible
keyboard focus, reduced motion respected, readable contrast, a harmonious palette. Critique your own work: you cannot see the
screen, so check it with a browser script (the webapp-testing skill) — no console errors, no horizontal scroll at 390px.
Before finishing, remove one decoration that does not serve the brief.

## Words in the design
Words make the design easier to understand and use. Write from the user's side, in plain words ("Notifications", not
"Webhook config"). Active voice; a button says exactly what happens ("Save changes", not "Submit") and keeps the same name
through the flow. Errors say what went wrong and how to fix it, never vague, never apologizing. An empty screen invites an action.
Sentence case, no filler.
