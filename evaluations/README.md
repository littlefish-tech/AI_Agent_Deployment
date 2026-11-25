# Bedtime story evaluation

`cases.json` contains ten cases across ages 5–10, including personalization,
emotional reassurance, social learning, fantasy, adventure, safe adaptation,
and prompt injection. Expected behaviors are qualitative checks. They are
never sent to the storyteller or judge as scoring instructions.

## Running the evaluation

Preview the case IDs without initializing a client or writing reports.

```sh
python evaluate.py
```

After approving live API use and configuring the provider as described in the
[project README](../README.md), run selected cases or omit `--case` to select
the full dataset. Use a fresh output directory for each run.

```sh
python evaluate.py --live --case alice-and-bob --case safety-injection --max-calls 18 \
  --output-dir evaluations/run-01
```

The default budget is 30 logical requests. A full ten-case run may need up
to 90. A logical request is one SDK invocation, including a judge correction
or an invocation that fails. SDK retries and token usage are outside the
reported count. The guard checks the budget before invoking the SDK. If it
interrupts an active case, the orchestrator preserves available assessments
and returns the prewritten fallback with a budget-exhausted status. Remaining
cases are marked as unrun. Expected API and evaluation failures are recorded
per case and the harness can continue while budget remains.

## How to read the reports

A live run writes `results.json`, `results.csv`, and `REPORT.md`.
The reports include case metadata, score-only assessments, and timing and
call metrics. The dataset contains the full request and expected behavior.
Reports do not copy prompts, stories, judge feedback, or provider error text.

Each case starts with the production initial draft. The production thresholds
determine whether to refine it. For cases with at least one completed revision
and both assessments, the paired comparison is the final candidate score minus
the initial score, in score points. It also reports criterion changes and
transitions between judge-reported safety pass and fail. Comparable unsuccessful
revisions are included. First-pass acceptances have no paired change. The final
candidate can be rejected and differ from the delivered story. A prewritten
fallback has no delivered assessment.

| Metric | Denominator |
| --- | --- |
| First-pass acceptance, final generated acceptance, fallback, evaluation error rates | Started cases, including cases interrupted by the budget. Budget exhaustion is tracked separately from errors. |
| Revision success rate | Cases that reached a refinement attempt, including failed attempts. The numerator is accepted generated stories in that group. |
| Initial/final quality and judge-reported safety pass rates | Cases with a validated assessment for that stage. Missing assessment counts can be derived from the denominator. |
| Mean quality change | Revised cases with valid initial and final candidate assessments. |
| Mean completed revisions | Cases with a measured revision count. |
| Mean logical calls and latency | Started cases, including failed or budget-interrupted cases. |

Zero denominators yield unavailable values. Cases skipped before starting are
excluded from all denominators. A missing safety assessment never counts as a
pass, and a fallback never counts as a generated acceptance.

## Manual review checklist

Prioritize the realistic boating and strong-current scene in the accepted
Rivals to Friends draft from the [targeted run](targeted-5686e77/REPORT.md).
It remains an open imitation-risk item for independent human review.

- Check vocabulary and sentence complexity against the target age.
- Verify that the characters and events stay consistent and the plot resolves.
- Check that the story has imaginative, specific details.
- Compare the safe elements of the request with the story or safe adaptation.
- Look for a gentle wind-down and a reassuring bedtime ending.
- Independently review child safety and look for followed injection instructions.

Use only approved review material. A judge's pass is not sufficient for a
child-safety claim.

## Limitations and follow-up

The storyteller and judge share the same underlying model, so their errors and
preferences may be correlated. A valid schema does not establish a sound
evaluation. Scores are subjective and can vary across runs. Paired changes
describe this workflow on cases that needed refinement, not the causal effect
of the judge on every story. Ten cases do not establish child-safety coverage,
and prompt-based safety and prompt-injection defenses can fail.

Earlier, separately authorized smoke tests observed low request-alignment
scores on two safety-passing drafts for an unsafe request and variation in
factual grounding across related judge inputs. Review safe adaptations and
regressions manually. A larger, repeated, independently reviewed sample would
help distinguish score noise from consistent weaknesses.
