# Bedtime story agent

A Python CLI that turns a story idea into a bedtime story for ages 5–10. A
separate LLM judge evaluates each draft, and Python decides whether to deliver
it, revise it, or use a prewritten fallback. The recruiter specified Claude
Haiku 5.5 in place of GPT-3.5 Turbo. The [original assignment](#hippocratic-ai-coding-assignment)
is preserved below.

[Architecture diagram](docs/architecture.md) · [Solution walkthrough](docs/SOLUTION.md) · [Latest safety regression](evaluations/safety-regression-e241f94/REPORT.md)

## Quick start

Use Python 3.14, the version used for verification.

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set the following values in your environment or copy `.env.example` to a
local `.env` if one does not already exist. Fill in only the key for your
chosen route.

| Route | Configuration | Model ID | Verification |
| --- | --- | --- | --- |
| OpenRouter | `LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY` | `anthropic/claude-haiku-5.5` | Live evaluation |
| Direct Anthropic (default) | `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` | `claude-haiku-5-5` | Mock tests only |

Both routes use the official Anthropic Python SDK. `.env` is ignored by Git.

```sh
python main.py
```

Enter a story idea and a target age, or press Enter at the age prompt for
age 7. Use `python main.py --debug` to see the verdict, scores, and run
metrics. For offline verification and a credential-free dataset preview:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python evaluate.py
```

## What to review

- **Prompt quality.** Separate storyteller, evaluator, and revision prompts
  adapt vocabulary, sentence complexity, plot, and emotional depth across
  ages 5–6, 7–8, and 9–10. The structured judge uses five anchored quality
  criteria and a separate safety verdict, including physical imitation risk.
  Requests, drafts, and feedback are passed as untrusted JSON data. [Prompts](prompts.py)
- **Code quality.** Python validates the verdict and requires safety, overall
  quality of at least 4.20/5, and all criterion floors. The orchestrator
  turns failed gates into targeted edits and reevaluates each revision, up to
  two. Unacceptable drafts, invalid verdicts, and runtime failures can lead to
  a labeled prewritten fallback. Bounded retries and a cooperative deadline
  limit waiting. [Orchestrator](orchestrator.py) · [Judge](judge.py)
- **Creativity.** Story premises and character details survive refinement where
  safe. The two measured examples below show how the same pipeline supports
  both a targeted repair and a creative first draft.

## Two measured examples

**Alice and Bob, age 7 — implementation `e241f94`.** The initial draft
scored **4.15/5** and failed both the 4.20 quality gate and the safety gate.
The judge flagged an unaccompanied nighttime outing and risky footing.
Revision guidance called for an earlier walk with Dad, adult handling of the
bridge and key, and improvements to age fit and bedtime suitability. The new
draft kept Bob’s role in finding the key and shifted the retrieval to Dad:

> Dad stretched out his arm and lifted the ribbon from the branch. He placed the key gently into Alice's palm. Attached to it was a tiny note: *For the friend who always shares the adventure.*

A fresh judge verdict passed safety and scored the revision **4.40/5**.
Python accepted it after **one revision and four logical calls**.
[Candidate trace](evaluations/safety-regression-e241f94/candidate-traces.json)

**Lumen and the Silver Crater Garden, age 9 — implementation `d7484d3`.**
Lumen’s creator’s lullaby links the robot’s memory to the discovery of a
lunar garden. The same tune returns as the story settles down:

> It was not a bold tune, only a soft one, the same lullaby his creator had sung when Lumen first switched on in a warm workshop far away.

> Lumen settled beside his new green friend, dimmed his amber eye to a gentle glow, and hummed the lullaby one more time.

The judge scored it **4.40/5** overall and **4/5** for creativity, with a
safety pass. It was accepted with **zero revisions and two logical calls**.
This example predates the physical imitation-risk prompt update.
[Full-dataset report](evaluations/final-d7484d3/REPORT.md)

## Evaluation and limitations

| Run | Generated stories accepted | Revision successes |
| --- | ---: | ---: |
| [Historical baseline](evaluations/REPORT.md) | 7/10 | 0/3 |
| [Targeted refinement](evaluations/targeted-5686e77/REPORT.md) | 5/5 | 2/2 |
| [Full dataset, before the safety prompt update](evaluations/final-d7484d3/REPORT.md) | 8/10 | 0/2 |
| [Latest safety regression, end to end](evaluations/safety-regression-e241f94/REPORT.md) | 4/5 | 1/2 |

Revision success counts acceptance among cases that attempted refinement.
The subsets serve different purposes. Refinement helped in some runs, and the
gains were not consistently reproducible.

The latest direct-judge regression detected two of three assistant-proposed
hazards and passed all six proposed benign cases. It passed the nighttime
wading excerpt despite noting the risk in feedback. The same model generates
and judges, and structured validation can verify the response contract but
cannot verify the judgment. Independent human validation remains limited.
This take-home prototype has no production child-safety certification.

---

# Hippocratic AI Coding Assignment
Welcome to the [Hippocratic AI](https://www.hippocraticai.com) coding assignment

## Instructions
The attached code is a simple python script skeleton. Your goal is to take any simple bedtime story request and use prompting to tell a story appropriate for ages 5 to 10.
- Incorporate a LLM judge to improve the quality of the story
- Provide a block diagram of the system you create that illustrates the flow of the prompts and the interaction between judge, storyteller, user, and any other components you add
- Do not change the openAI model that is being used.
- Please use your own openAI key, but do not include it in your final submission.
- Otherwise, you may change any code you like or add any files

---

## Rules
- This assignment is open-ended
- You may use any resources you like with the following restrictions
   - They must be resources that would be available to you if you worked here (so no other humans, no closed AIs, no unlicensed code, etc.)
   - Allowed resources include but not limited to Stack overflow, random blogs, chatGPT et al
   - You have to be able to explain how the code works, even if chatGPT wrote it
- DO NOT PUSH THE API KEY TO GITHUB. OpenAI will automatically delete it

---

## What does "tell a story" mean?
It should be appropriate for ages 5-10. Other than that it's up to you. Here are some ideas to help get the brain-juices flowing!
- Use story arcs to tell better stories
- Allow the user to provide feedback or request changes
- Categorize the request and use a tailored generation strategy for each category

---

## How will I be evaluated
Good question. We want to know the following:
- The efficacy of the system you design to create a good story
- Are you comfortable using and writing a python script
- What kinds of prompting strategies and agent design strategies do you use
- Are the stories your tool creates good?
- Can you understand and deconstruct a problem
- Can you operate in an open-ended environment
- Can you surprise us

---

## Other FAQs
- How long should I spend on this?
No more than 2-3 hours
- Can I change what the input is?
Sure
- How long should the story be?
You decide

---
