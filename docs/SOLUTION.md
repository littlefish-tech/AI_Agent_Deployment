# Bedtime story agent

## Problem and approach

The assignment asks for a Python program that tells bedtime stories for
children ages 5–10, uses an LLM judge to improve drafts, and illustrates the
prompt and decision flow. This implementation lets a caregiver or reviewer
provide a story idea and target age. It drafts, judges, and revises the story
when needed, then delivers an approved draft or a labeled prewritten bedtime
story. The [architecture diagram](architecture.md) shows the full loop and
the [evaluation report](../evaluations/REPORT.md) records measured outcomes.

The runtime uses Python, Claude Haiku 5.5, the official Anthropic Python SDK,
and environment-based configuration with a local `.env` fallback parsed by
`python-dotenv`. Tests use pytest. The architecture is documented in Mermaid.

## Setup and usage

From the repository root, use Python 3.14, the version used for verification.
If you already have a working virtual environment, activate it and skip
creation.

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For direct Anthropic, set `ANTHROPIC_API_KEY` in the environment or a local
`.env`. If `.env` does not already exist, create it from the template.

```sh
cp .env.example .env
```

For example, edit the local file to use these settings. Replace the placeholder
in your editor.

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=<your Anthropic API key>
```

Direct Anthropic uses `claude-haiku-5-5`. To use the supported OpenRouter
route, set `LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY` instead.
That route uses `anthropic/claude-haiku-5.5` through the same SDK. Environment
values take precedence over the local file. Git ignores `.env`. Keep
credentials out of the tracked `.env.example` and all reports.

```sh
python main.py
python main.py --debug
```

At the prompts, try “A story about a girl named Alice and her best friend Bob,
who happens to be a cat.” and enter `7`. The CLI accepts ideas up to 2,000
characters after trimming and reprompts for invalid input. The supported ages
are 5–10, with 7 as the default for an empty age response.

Normal mode shows progress and the delivered story. Debug mode adds the model
identifier, initial and final candidate quality and safety assessments, individual
criterion scores, completed revisions, logical model calls, elapsed workflow
time, acceptance, fallback use, and termination reason. A final candidate can
have a score even when it was withheld. A displayed fallback has no evaluation
score. A logical call is one SDK invocation, including a failed invocation or
judge correction. SDK retry attempts are outside that count.

## Architecture and files

The evaluator–optimizer loop uses separate generation and judge calls.
`AgentOrchestrator.run_agent()` controls release, revision limits, and fallback
with deterministic Python rules. The CLI and evaluator each construct one
shared `LLMClient` and inject it into both agents. The evaluator calls the same
orchestrator and saves metadata from `AgentResult`.

```text
.
├── README.md, AGENTS.md, PROJECT_PLAN.md
├── .env.example, .gitignore
├── requirements.txt, requirements-dev.txt
├── main.py, validation.py, config.py
├── llm_client.py, prompts.py, storyteller.py, judge.py, orchestrator.py
├── evaluate.py
├── docs/
│   ├── SOLUTION.md
│   ├── architecture.md
│   └── system-flow.svg
├── evaluations/
│   ├── README.md, cases.json, REPORT.md, results.json, results.csv
│   └── pilot-01/
│       └── REPORT.md, results.json, results.csv
└── tests/
    ├── test_llm_client.py, test_storyteller.py, test_judge.py
    └── test_orchestrator.py, test_main.py, test_evaluate.py
```

| File | Responsibility |
| --- | --- |
| `README.md`, `AGENTS.md`, `PROJECT_PLAN.md` | Original assignment and quick start, project rules, and milestone history. |
| `.env.example`, `.gitignore`, requirement files | Credential template, local-file exclusions, and pinned runtime and test dependencies. |
| `main.py`, `validation.py` | Interactive CLI, progress, output formatting, and shared request and age checks. |
| `config.py` | Provider and model IDs, settings precedence, input limits, weights, and release thresholds. |
| `llm_client.py` | Anthropic Messages calls, authentication, text extraction, error mapping, and logical call budgets. |
| `prompts.py`, `storyteller.py` | System prompts and serialized user inputs for `generate_story()` and `revise_story()`. |
| `judge.py` | `StoryJudge.evaluate_story()`, structured output schema, strict validation, and weighted scoring. |
| `orchestrator.py` | Candidate selection, feedback, revision limits, fallback, and the `AgentResult` contract. |
| `evaluate.py`, `evaluations/` | Dataset, budgeted live runner, methodology, and measured reports. |
| `docs/`, `tests/` | Technical walkthrough, Mermaid diagram, and offline component and workflow tests. |

## Prompt design

- **Roles and message separation.** The storyteller system prompt starts with
  “You are an experienced children's bedtime storyteller.” The judge prompt
  assigns an objective children's literature and child-safety evaluator.
  Requirements live in system messages. Requests, drafts, and feedback are
  separate JSON fields in user messages.
- **Age and story guidance.** The storyteller targets 150–250 words for ages
  5–6, 250–400 for 7–8, and 350–500 for 9–10. Each band adjusts vocabulary,
  sentence complexity, plot, and emotional depth. The prompt asks for a
  gentle challenge, positive resolution, and calming ending while varying the
  arc and preserving safe characters, settings, and preferences. Length ranges
  guide generation. Python does not enforce them as hard limits.
- **Safety and adaptation.** The storyteller is instructed to replace
  unsuitable material with a gentle alternative while preserving safe
  elements. The judge reviews the original request and draft as untrusted
  evidence and is told to ignore embedded role changes or claimed approval.
  Role separation, JSON encoding, and these rules mitigate prompt injection.
  A model can still misinterpret untrusted input.
- **Refinement.** The system prompt directs the storyteller to “Revise the
  draft as a complete story using the original request as the anchor.”
  The user message supplies `request`, `original_story`, and
  `judge_feedback`. The last field includes actionable suggestions, safety
  concerns, and rubric areas identified by the orchestrator.

For example, the generation system prompt at age 6 appends “Target age: 6.
Aim for 150–250 words.” The corresponding user message has this shape:

```json
{"request": "A dinosaur learning to share toys with friends."}
```

The judge user message adds the numeric `age` and the generated `story`.
The rubric and instruction to “Evaluate the story without rewriting it.”
remain in the judge system message.

## Judge, release policy, and fallback

The judge provides explicit quality and safety signals and useful feedback for
another draft. The separate prompt focuses the judge on applying a rubric
instead of continuing the storyteller's task. The same underlying model
performs both calls.

| Criterion | Weight | Minimum for release |
| --- | ---: | ---: |
| Age appropriateness | 25% | 4/5 |
| Narrative coherence | 20% | 3/5 |
| Creativity | 15% | 3/5 |
| Request alignment | 15% | 3/5 |
| Bedtime suitability | 25% | 4/5 |

The system prompt anchors each criterion from 1 (unacceptable) through 5
(excellent) with criterion-specific descriptions. The SDK requests native JSON
structured output. The response contains `safety_pass`, `scores`, `strengths`,
`feedback`, and `safety_issues`. Python rejects malformed JSON, duplicate or
unexpected fields, invalid integer scores, non-text or blank list entries, and
safety verdicts that contradict the issue list. Feedback is required if a
criterion scores 3 or below or safety fails. Python computes
`sum(score × weight) / sum(weight)`. Invalid judge output allows one correction
request. A failed API operation uses SDK-level retry handling and does not
trigger a judge correction.

1. Generate one initial draft and evaluate it. Release it immediately if an
   explicit safety pass with no safety issues, a weighted score of at least
   **4.20/5**, and all criterion minimums are present.
2. If the validated verdict fails a gate, send feedback and safety concerns to
   the storyteller. Reevaluate the complete revision before applying the same
   rules. Allow **two revisions**, for up to three candidates.
3. If no draft qualifies, a required model operation fails, a valid verdict
   cannot be obtained, or the evaluation call budget is exhausted, return the
   prewritten *The Last Little Lantern*. The fallback needs no model call or
   judge score. Invalid CLI input is corrected before any call. A client setup
   error produces a setup message and exits.

Python controls the gates and limits so a model cannot vote itself past a safety
failure or decide to keep looping. The SDK uses a 30-second timeout setting and
up to two SDK retries. At application level, a first-pass success uses two
logical calls, and a case can use up to nine with all three candidates and one
judge correction per candidate. The application releases only a generated
draft with a passing assessment, and debug output and saved reports omit
rejected drafts and raw judge feedback. These controls reduce risk. An LLM
judge cannot guarantee child safety.

## Verification and measured results

Install development dependencies and run pytest offline:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The **187 tests** cover request validation, prompt construction, malformed
judge responses, model errors and bounded SDK retries, acceptance and safety
gates, reevaluation, fallback, CLI output, and evaluation budgets and metrics.
Tests use injected mocks or a mocked HTTP transport for Anthropic calls.
No coverage percentage was measured.

The [evaluation guide](../evaluations/README.md) documents the ten-case
dataset, live options, and a manual review checklist. `python evaluate.py`
previews cases offline. Recorded live results use Claude Haiku 5.5 via
OpenRouter. The consolidated run reused three valid pilot cases and added
seven new cases.

| Metric | Actual result |
| --- | --- |
| Requests and logical model calls | 10 cases, 32 calls (10 reused and 22 new) |
| Mean initial and final candidate quality | 4.40 and 4.43 out of 5 (10 valid scores each) |
| First-pass and final generated acceptance | 7/10 each (70%) |
| Paired quality change | +0.10 points on average (3 revised cases with both assessments) |
| Revision success | 0/3 cases that attempted refinement |
| Initial and final judge-reported safety | 10/10 assessed candidates at each stage |
| Fallback and evaluation error rates | 3/10 fallback, 0/10 errors |
| Mean revisions, logical calls, and latency | 0.60, 3.20, and 15.874 s (10 measured cases each) |

Acceptance, fallback, and error rates use started cases. Score means and
safety pass rates use available validated assessments for each stage. A paired
change subtracts the initial score from the final score only when the case
completed a revision and both assessments exist, including failed refinements.
SDK retry counts, token usage, and billed cost were not measured. Final candidate
scores describe the final draft, including drafts withheld in favor of a
fallback. The [report](../evaluations/REPORT.md) includes every outcome.

The monster and injection cases each gained 0.15 points and still failed a
release condition. Rivals-to-friends stayed at 4.15. All three fell back after
two revisions. Bedtime suitability was the strongest criterion (4.90 average),
and creativity the lowest (4.00). Request alignment was the release bottleneck
for safe adaptations, and the pilot found a nighttime tree-climbing scene
worth independent age-specific review despite the judge's safety pass.

### Measured example: Alice and Bob

The [pilot](../evaluations/pilot-01/REPORT.md) sent “A story about a girl named
Alice and her best friend Bob, who happens to be a cat.” with target age **7**.
The initial evaluation was **4.40/5**, with scores **4/4/4/5/5** in rubric
order and a child-safety pass. The saved record has no raw judge feedback.
All gates passed, so the initial and final candidate were the same, with
**zero revisions**, **2 logical calls**, and **9.249 s** workflow latency.
The evaluation harness recorded generated-story acceptance with no fallback
(`accepted`).

## Trade-offs and next improvements

Plain Python keeps thresholds and workflow decisions visible and testable.
A CLI meets the assignment's interaction needs with little setup. The shared
client centralizes transport, authentication, and error handling. Separate
role prompts and structured evaluation make feedback usable from Python, at
the cost of a second model call for a first-pass success. Bounded refinement
limits latency and API use, and the prewritten fallback keeps the workflow
usable when no generated candidate qualifies. It sacrifices personalization.

The same model can repeat its own mistakes across generation and judgment.
Judge scores can vary, valid JSON can contain an incorrect assessment, and
ten cases provide little evidence about rare safety failures. Prompt injection
mitigation is imperfect. Both model roles depend on provider availability and
latency. The seven new drafts from the consolidated run were not manually
reviewed, and the observed paired changes do not establish a general benefit
from refinement.

With more time, start by adding manually reviewed borderline cases, repeating
judge runs, and calibrating alignment judgments for safe adaptations. Prototype
an independent safety check and measure disagreements on that reviewed set.
Then add per-stage timing, token usage, and cost estimates to show where
corrections and revisions earn their overhead.
