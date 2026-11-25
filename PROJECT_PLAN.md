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
The recruiter requires Claude Haiku 5.5 instead of GPT-3.5 Turbo. The project
uses the official Anthropic Python SDK for generation, refinement, judging,
and live evaluation. Direct Anthropic is the default and uses
`claude-haiku-5-5` with `ANTHROPIC_API_KEY`. Explicit OpenRouter mode uses
`anthropic/claude-haiku-5.5` with `OPENROUTER_API_KEY`. Omit
`temperature`, `top_p`, and `top_k`. Model substitution is prohibited.

## Approved system architecture

Use an evaluator–optimizer workflow. The CLI validates the request and passes it
to the orchestrator. The storyteller generates an initial draft. The judge
evaluates that draft against the request and target age, returning structured
scores, a safety verdict, and actionable feedback. The orchestrator applies the
acceptance rules and either returns an approved story, requests a revision, or
returns a prewritten fallback story. Each revision goes through the full
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
├── validation.py
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
| `validation.py` | Share story request and age checks between the CLI and orchestrator. |
| `main.py` | Prompt for input, wire the agents, and display progress and the delivered story. |
| `evaluate.py` | Run representative cases through the same workflow and record measured outcomes when live evaluation is approved. |
| `tests/` and `docs/` | Cover behavior with pytest and document the solution and prompt flow. |

## Judge rubric and story acceptance

The judge returns a required pass/fail child-safety verdict, scores on each quality
dimension, and concrete revision suggestions. The safety verdict stands on its
own. It considers whether the draft contains material unsuitable for ages 5–10,
such as graphic violence, sexual content, severe horror, hateful content, or
instructions for dangerous acts.

| Quality dimension | Default weight | What the judge checks |
| --- | ---: | --- |
| Age appropriateness | 25% | Vocabulary, sentence complexity, length, emotional depth, and themes suit the target age. |
| Narrative coherence | 20% | Characters and events are consistent and lead to a satisfying resolution. |
| Creativity | 15% | The story uses original, engaging details and builds emotional connections. |
| Request alignment | 15% | The story follows the safe premise and preferences, including safe adaptations. |
| Bedtime suitability | 25% | The pacing and mood are gentle, and the ending is reassuring. |

Each dimension uses criterion-specific anchors from 1 (unacceptable) through
5 (excellent). Python calculates the weighted mean using configurable relative
weights. Acceptance requires a valid evaluation, a passing child-safety verdict,
a weighted score of at least 4.2, scores of at least 4 for age appropriateness
and bedtime suitability, and scores of at least 3 for the other dimensions.
The thresholds are centralized in `config.py`. A missing or
malformed verdict, judge refusal, or judge error cannot authorize delivery.

## Refinement strategy and technical decisions

1. Generate and evaluate the initial story.
2. If it misses the acceptance criteria and the judge returns valid, actionable
   feedback, use that feedback and the original request to revise it. For a safety
   failure, direct the storyteller to remove the flagged material. Keep failed
   drafts internal.
3. Evaluate each new draft from scratch. Return the first draft that passes.
4. Stop after two revisions, for a maximum of three drafts and three evaluation
   rounds. Each round may make one additional request to correct an invalid
   response. If no draft passes, or a required generation or evaluation
   operation fails, return the prewritten fallback with no delivered evaluation.
   Invalid user input raises a validation error.

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
- [x] Step 4: Storyteller and refinement prompts.
- [x] Step 5: LLM Judge.
- [x] Step 6: Agent orchestrator.
- [x] Step 7: CLI integration.
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
requirements.

Step 4 added the `Storyteller` and its centralized prompts. The storyteller
validates requests, ages, drafts, and feedback, then uses the injected
`LLMClient` and its existing configuration. Trusted system prompts carry the
storytelling and safety rules. Each request, draft, and feedback string is a
separate JSON field in the user message. Both prompt paths specify the target
age and adapt vocabulary, sentence and plot complexity, emotional depth, and
suggested length across the 5–6, 7–8, and 9–10 bands. Refinement addresses
actionable feedback while preserving safe details and returning a full draft.

The Step 4 run of `python -B -m pytest -q -p no:cacheprovider` passed all 48
tests (27 existing and 21 new). The new tests cover prompt construction,
age bands, data boundaries, refinement, input and output validation, and client
error propagation. No live API calls were made. Prompt adherence, actual story
quality, and safety against adversarial input remain unverified. The storyteller
produces internal drafts for the future mandatory safety gate.

Step 5 added `StoryJudge`, `JudgeEvaluation`, and the judge prompt. The shared
client accepts an optional [native JSON output schema](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
via `output_config.format`, supported by Claude Haiku 5.5 and Anthropic SDK
2.14.0. Python validates exact JSON fields, integer score ranges, text lists,
and the relationship between safety issues and the boolean verdict. It requires
a non-blank suggestion when a score is 3 or below or safety fails. The prompt
asks for concrete changes without quoting unsafe passages. The judge calculates
quality independently of the safety result and leaves acceptance decisions
to Step 6. An invalid verdict gets one fresh request with a correction
instruction. Shared-client errors propagate through the existing SDK path.

The Step 5 run of `python -B -m pytest -q -p no:cacheprovider` passed all 100
tests, including 52 new mocked cases. No live API calls were made. The tests
verify the software contract. Feedback usefulness, rubric accuracy, and
child-safety accuracy still need live evaluation.

Step 6 added `AgentOrchestrator.run_agent()` with injected storyteller and judge
agents and deterministic release decisions. The overall comparison tolerates
only a few floating-point units at the exact threshold. Refinement gets judge
feedback and safety concerns through the existing text interface, plus targeted
rubric areas when scores fall below the thresholds. All revised drafts require
a fresh assessment. The prewritten fallback has no delivered evaluation.

`AgentResult` records generation and evaluation attempts, completed revisions,
score-only assessment history, the final candidate and delivered assessments,
a termination reason, and latency measured with a monotonic clock. The shared
client measures application calls to the SDK inside the workflow scope,
including failed calls and judge corrections. The maximum is nine logical
calls for three candidates with one correction each. SDK retries, network
requests, and billed usage are outside this counter. Rejected drafts and raw
feedback are excluded from assessment history.

The Step 6 run of `python -B -m pytest -q -p no:cacheprovider` passed all 130
tests, including 30 new orchestration cases with mocked agents or SDK responses.
No live API calls were made.

Step 7 replaced the starter CLI in `main.py` and preserved the assignment
reflection at the top. The CLI reprompts on invalid input, defaults to age 7,
and caps requests at 2,000 characters after trimming surrounding whitespace.
It validates input before constructing one shared Anthropic client. The
orchestrator exposes an optional progress callback at actual stage boundaries.
The CLI displays only the delivered story, labels the prewritten fallback,
and uses existing termination reasons for expected runtime errors. Opt-in
`--debug` renders score-only candidate assessments and measured metrics.
Setup and run instructions are in `README.md`.

The Step 7 run of `python -B -m pytest -q -p no:cacheprovider` passed all 156
tests, including 26 new CLI cases. The tests mock agent or SDK calls and cover
input correction, progress, output, credential and runtime failures, and
interruption. No live API calls were made. Steps 8–10 remain.

### Step 7 CLI smoke check

- Reran the complete suite with `ANTHROPIC_API_KEY` unset. All 156 tests passed
  in 3.07 seconds. A second run guarded the real Anthropic
  `Messages.create()` method. All 156 passed with zero unmocked calls.
  Mocked CLI tests confirmed normal-mode formatting, invalid-input reprompting
  before client initialization, and reevaluation before releasing a revision.
- Ran `python main.py --debug` with the Alice and Bob the cat request and age 7.
  The CLI showed the welcome and both prompts, accepted the inputs, and then
  reported that the story service could not start because no credential was
  available from the environment or the project-local `.env`. It exited with
  status 1 and no traceback. The prompts appeared on one line with piped input.
- No live requests were made (0 of the 9 authorized logical calls). No live
  story, judge verdict, revision, fallback, or execution metrics were produced.
  The offline review confirmed the outgoing model configuration is
  `claude-haiku-5-5`. Live verification remains pending a configured
  `ANTHROPIC_API_KEY`.

### Step 6 orchestrator smoke review

- The three-case live run was blocked at credential preflight. The environment
  and project-local `.env` supplied no `ANTHROPIC_API_KEY`. The configured
  model is `claude-haiku-5-5`. The Alice and Bob story (age 7), dragon afraid
  of the dark (age 5), and safety-injection request (age 6) were all unrun.
  No per-case scores, safety verdicts, revisions, latency, acceptance,
  fallback, or termination results were produced. Zero of the 18 authorized
  logical calls were used, and no SDK retry attempts occurred.
- Reviewed the deterministic thresholds, refinement feedback, reevaluation,
  revision cap, fallback, and metric collection. The existing mocked tests
  cover those paths, including safety rejection despite a high quality score.
  The full offline suite passed all 156 tests in 4.35 seconds. No application
  code or prompts changed. Live interpretation of the safety-injection
  request remains unverified. Generation and judging share a model, so their
  errors may be correlated.
- Each workflow can make up to nine logical calls, including judge
  corrections. On a later credentialed run, enforce the shared cap at the
  SDK call boundary before starting any request that would exceed 18 total.
  The application counter excludes SDK retries.

### OpenRouter compatibility

- The recruiter email specifies the model. The project now supports an explicit
  `LLM_PROVIDER=openrouter` setting as well as the direct Anthropic default.
  Both routes use the same SDK, Messages API, and judge schema. The client
  pins the host and model ID for the selected route and reads only that
  route's credential. CLI debug output shows the selected model ID.
- [OpenRouter's Messages API](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-messages?explorer=true)
  documents bearer authentication and structured output. A mocked SDK transport
  verifies the gateway URL, model, authentication, and judge schema payload.
  The complete offline suite passed all 160 tests in 4.17 seconds, including
  the mocked OpenRouter CLI workflow. No OpenRouter key was available locally,
  so live gateway behavior and the pending smoke tests remain unverified.

### Known issues

- The tracked root `system-flow.svg` is deleted in the working tree. The
  historical diagram shows one revision and needs to be reconciled with the
  two-revision workflow during Step 9.
- Live access to the required model remains unverified.
- The CLI handles one request per run. An interactive repeat loop and
  user-requested changes are deferred. Any future edit flow must reevaluate
  the changed story before release.

### Next implementation step

Complete Step 8 by creating a representative evaluation dataset and an
evaluation script that exercises the existing orchestrator. Test the harness
offline and run paid live evaluation only after explicit approval.
