---
name: verification-before-completion
description: Use before saying work is complete, fixed or passing — run the verification command and read its output first; evidence before claims.
triggers: done, finish, finished, complete, completed, verify, check, test, tests, pass, passing, fix, 완료, 끝, 확인, 검증, 테스트
source: Adapted from obra/superpowers — skills/verification-before-completion (https://github.com/obra/superpowers). Copyright (c) 2025 Jesse Vincent. MIT License; see LICENSE. Changes: shortened for a small local model; removed parts about commits, PRs and other agents.
---

# Verification Before Completion

**Core principle:** evidence before claims, always.

## The iron law
```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```
If you have not run the verification command in this step, you cannot say it passes.

## The gate
Before saying anything is done, fixed or working:
1. IDENTIFY: which command proves it? (the task's check, the tests, running the program)
2. RUN: run the full command now — fresh and complete.
3. READ: the whole output and the exit code; count the failures.
4. VERIFY: does the output confirm it?
   - No → say the real status, with the evidence.
   - Yes → say it is done, with the evidence (the command and what it printed).
5. Only then make the claim.

## What each claim needs
| Claim | Needs | Not enough |
|---|---|---|
| Tests pass | the test command's output: 0 failures | an earlier run, "should pass" |
| Bug fixed | the original symptom now passes | the code changed, assumed fixed |
| Page works | a browser check of the page (see webapp-testing) | curl showing the HTML, "looks right" |
| Requirements met | each requirement checked one by one | the tests passing |

## Red flags — stop
- Words like "should", "probably", "seems to"
- Saying "Done!" or "Perfect!" before running the check
- Relying on a partial check, or on an earlier run
- Wanting to finish because it is taking long

## Patterns
```
✅ ran python3 check.py → it printed PASS → "Done: python3 check.py prints PASS"
❌ "It should work now" / "Looks correct"
✅ re-read the task → make a checklist → verify each item → report what is done and what is not
```
