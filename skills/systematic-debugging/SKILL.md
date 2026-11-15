---
name: systematic-debugging
description: Use for any bug, test failure or unexpected behavior, before proposing fixes — find the root cause first.
triggers: bug, error, fix, fails, failing, failed, broken, crash, exception, traceback, debug, wrong, 버그, 오류, 에러, 고쳐, 안돼, 실패
source: Adapted from obra/superpowers — skills/systematic-debugging (https://github.com/obra/superpowers). Copyright (c) 2025 Jesse Vincent. MIT License; see LICENSE. Changes: shortened for a small local model; removed references to other skills and files that are not included.
---

# Systematic Debugging

**Core principle:** always find the root cause before attempting fixes. Symptom fixes are failure.

## The iron law
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```
If you have not done Phase 1, you cannot propose a fix. Simple bugs have root causes too, and systematic is faster than guessing.

## Phase 1: Root cause investigation
1. **Read error messages carefully.** Don't skip errors or warnings — they often contain the exact answer. Read stack traces
   completely; note line numbers, file paths, error codes.
2. **Reproduce consistently.** What exact command shows it? Does it happen every time? If not, gather more data, don't guess.
3. **Check recent changes.** What did you (or the last person) change that could cause this?
4. **Gather evidence at each boundary.** When data passes through several parts (input → function → output, API → page),
   print what goes in and what comes out at each step, run once, and see WHERE it breaks.
5. **Trace the data flow.** Where does the bad value come from? What called this with the bad value? Keep going up until you
   find the source. Fix at the source, not where it shows up.

## Phase 2: Pattern analysis
1. Find working code that is similar (in this project or the docs).
2. Compare against the reference completely — don't skim.
3. List every difference between working and broken, however small.
4. Know the dependencies: settings, environment, assumptions.

## Phase 3: Hypothesis and testing
1. Form one hypothesis and write it down: "I think X is the root cause because Y."
2. Test it with the smallest possible change — one variable at a time.
3. Did it work? Yes → Phase 4. No → form a NEW hypothesis. Don't pile more fixes on top.
4. If you don't understand something, say so and look it up instead of pretending.

## Phase 4: Implementation
1. Have a failing check first (the task's check, a test, or a small script that shows the bug).
2. Make one fix that addresses the root cause. No "while I'm here" changes.
3. Run the check again: does it pass, and is nothing else broken?
4. If the fix did not work: count your attempts. Fewer than 3 → back to Phase 1 with the new information.
   **3 or more failed fixes → stop and question the approach itself** (each fix revealing a new problem in another place means
   the design is wrong, not the last line). Say what you tried and why each failed, then choose a different approach.

## Red flags — stop and go back to Phase 1
- "Quick fix for now, investigate later" / "Just try changing X and see"
- Several changes at once, then running the tests
- "It's probably X, let me fix that" without evidence
- Proposing fixes before tracing the data flow
- "One more fix attempt" after 2+ failures

## Quick reference
| Phase | Do | Done when |
|---|---|---|
| 1. Root cause | read errors, reproduce, check changes, gather evidence | you know WHAT and WHY |
| 2. Pattern | find working examples, compare | differences listed |
| 3. Hypothesis | one theory, smallest test | confirmed, or a new theory |
| 4. Implementation | failing check, one fix, verify | check passes, nothing else broken |

Never change the test or the task's check to make it pass — change the code.
