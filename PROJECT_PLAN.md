# Hippocratic AI bedtime story agent

## Objective and assignment requirements

Build a Python CLI that turns a simple request into a bedtime story appropriate
for children ages 5–10. Use an LLM judge to improve story quality and submit a
block diagram showing how prompts and feedback move among the user, storyteller,
judge, and other components. The assignment leaves story length and input design
open and sets a 2–3 hour time budget. Preserve the original instructions in
[README.md](README.md), keep credentials out of the submission, and be able to
explain the design and code.

The original README asks for the starter OpenAI model and a personal OpenAI key.
The recruiter's updated requirement supersedes those two instructions. Every
generation, refinement, judging, and live evaluation call must use the official
Anthropic Python SDK with model ID `claude-haiku-5-5` and authentication from
`ANTHROPIC_API_KEY`. Omit `temperature`, `top_p`, and `top_k`. Model
substitution is prohibited.

## Approved system architecture

Use an evaluator–optimizer workflow. The CLI validates the request and passes it
to the orchestrator. The storyteller generates an initial draft. The judge
evaluates that draft against the request and target age, returning structured
scores, a safety verdict, and actionable feedback. The orchestrator applies the
acceptance rules and either returns an approved story, requests a revision, or
ends with a brief user-facing message. Each revision goes through the full
evaluation again. The storyteller and judge share one Anthropic client.

### Planned directory structure

```text
.
├── AGENTS.md
├── PROJECT_PLAN.md
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── config.py
├── llm_client.py
├── prompts.py
├── storyteller.py
├── judge.py
├── orchestrator.py
├── main.py
├── evaluate.py
├── tests/
└── docs/
    └── system-flow.svg
```

| Component | Responsibility |
| --- | --- |
| `config.py` | Centralize the fixed model ID, request limits, revision cap, and configurable quality thresholds. |
| `llm_client.py` | Authenticate from the environment, call Anthropic, extract usable text, and surface errors without exposing credentials. |
| `prompts.py` | Hold the generation, judge, and refinement templates. Delimit user and model content as untrusted data. |
| `storyteller.py` | Generate drafts and revise them using the original request and the judge's feedback. |
| `judge.py` | Evaluate each draft and validate the structure and values of the returned verdict. |
| `orchestrator.py` | Enforce the safety gate, quality thresholds, revision limit, and final outcome deterministically. |
| `main.py` | Validate CLI input and display the approved story or a brief failure message. |
| `evaluate.py` | Run representative cases through the same workflow and record measured outcomes when live evaluation is approved. |
| `tests/` and `docs/` | Cover behavior with pytest and document the solution and prompt flow. |

## Judge rubric and story acceptance

The judge returns a required pass/fail child-safety verdict, scores on each quality
dimension, and concrete revision suggestions. The safety verdict stands on its
own. It considers whether the draft contains material unsuitable for ages 5–10,
such as graphic violence, sexual content, severe horror, hateful content, or
instructions for dangerous acts.

| Quality dimension | What the judge checks |
| --- | --- |
| Age fit | Vocabulary, sentence complexity, and themes suit the target age or the 5–10 range. |
| Request alignment | The story captures the requested premise and appropriate details. |
| Narrative coherence | The story has a clear beginning, development, and satisfying resolution. |
| Bedtime tone | The pacing and mood are gentle, and the ending is reassuring. |
| Creativity and engagement | The story uses memorable details and holds a child's interest. |

Proposed scoring defaults for Steps 5–6 are integer scores from 1 to 5, where 1
means a major shortfall, 3 means adequate, and 5 means excellent. Accept a usable
draft only when its evaluation is valid, child safety explicitly passes, its
average score is at least 4, and every dimension scores at least 3. Keep both
quality thresholds configurable. A missing or malformed verdict, judge refusal,
or judge error cannot authorize delivery.

## Refinement strategy and technical decisions

1. Generate and evaluate the initial story.
2. If it misses the acceptance criteria and the judge returns valid, actionable
   feedback, use that feedback and the original request to revise it. For a safety
   failure, direct the storyteller to remove the flagged material. Keep failed
   drafts internal.
3. Evaluate each new draft from scratch. Return the first draft that passes.
4. Stop after two revisions, for a maximum of three drafts and three evaluations.
   If none passes, or a usable evaluation cannot be obtained, return a safe
   failure message without a draft.

Keep the acceptance logic in Python so the judge supplies evidence and cannot
set thresholds or bypass the release decision. Validate the judge response
before using it. Treat requests, drafts, and feedback as untrusted text. Use the
same production workflow for the CLI and evaluation script, and keep dependencies
and setup small enough for the assignment time budget.

## Testing strategy

- Use pytest with mocked Anthropic calls. Cover the fixed model ID, omitted
  sampling parameters, missing credentials, response extraction, empty or
  incomplete responses, and SDK errors.
- Cover prompt construction, valid and malformed judge verdicts, safety
  failures regardless of quality scores, exact threshold boundaries, immediate
  acceptance, revision and reevaluation, exhaustion of both revisions, and
  failure to obtain a verdict.
- Exercise the CLI with valid and invalid input, including verification that
  failed drafts never reach its output.
- Start with an offline client smoke test using a mocked SDK response. Run a
  paid live smoke test or evaluation only with explicit approval. For a live
  evaluation, use representative requests across the age range, including
  challenging requests, and record actual outcomes, revision counts, and
  observed failures.

## Milestones and current status

- [x] Step 1: Requirements analysis and architecture planning.
- [x] Step 2: Project initialization and AGENTS.md.
- [x] Step 3: Anthropic API client and smoke test.
- [ ] Step 4: Storyteller and refinement prompts.
- [ ] Step 5: LLM Judge.
- [ ] Step 6: Agent orchestrator.
- [ ] Step 7: CLI integration.
- [ ] Step 8: Testing and live evaluation.
- [ ] Step 9: Documentation and architecture diagram.
- [ ] Step 10: Final code review and submission preparation.

Step 1 is supported by the assignment requirements, the approved design above,
and the early flow diagram in commit `e96c46b`. Step 2 is recorded in
`a889440` and `a2a2910`, which cover the repository instructions, dependency
pins, environment template, ignore rules, and test directory. The local virtual
environment was verified with Python 3.14.6, Anthropic SDK 2.14.0, and pytest
9.2.0.

Step 3 added the shared synchronous client in `llm_client.py` and its settings
in `config.py`. Anthropic's [model documentation](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
and [Messages API reference](https://platform.claude.com/docs/en/api/python/messages/create)
confirm the fixed model ID and the `system`, `messages`, and `max_tokens`
request fields. The client accepts a token limit per call (4,096 by default),
joins text blocks in order, and rejects empty, truncated, or otherwise incomplete
responses. It uses the [SDK's timeout and retry settings](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python#retries)
with a 30-second timeout setting and at most two SDK retries. Displayable errors
omit upstream details.

Install development dependencies with `python -m pip install -r requirements-dev.txt`.
Set `ANTHROPIC_API_KEY` in the environment or put it in the project-local
`.env` using `.env.example` as a template. The environment takes precedence.
The client reads the local fallback using `python-dotenv` without changing the
process environment. An injected SDK client permits offline tests without a key.

The Step 3 run of `python -B -m pytest -q -p no:cacheprovider` passed all 27
tests, including the mocked smoke test. `python -m pip check` found no broken
requirements. No live API calls or evaluations were made. Steps 4–10 remain.

### Known issues

- The working copy contains a modified `README.md` with the original assignment
  and an untracked `main.py` that still uses the starter OpenAI code.
- The tracked root `system-flow.svg` is deleted in the working tree. The
  historical diagram shows one revision and needs to be reconciled with the
  two-revision workflow during Step 9.
- Live access to the required model remains unverified.

### Next implementation step

Complete Step 4 by adding the story generation and refinement templates in
`prompts.py` and implementing `storyteller.py` with the shared
`LLMClient.generate_text()` interface. Test initial drafting and feedback-based
revision offline.
