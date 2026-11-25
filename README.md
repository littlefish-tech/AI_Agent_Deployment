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

## Running the bedtime story agent

The recruiter updated the model requirement to Claude Haiku 5.5. The
application uses Anthropic's Python SDK for both supported routes.

From the project directory, activate your Python virtual environment and install
the runtime requirements. Set the provider and matching key in your
environment or copy `.env.example` to `.env` and configure it locally.

| Route | Configuration | Model ID |
| --- | --- | --- |
| Direct Anthropic (default) | `ANTHROPIC_API_KEY` | `claude-haiku-5-5` |
| OpenRouter | `LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY` | `anthropic/claude-haiku-5.5` |

```sh
python -m pip install -r requirements.txt
python main.py
```

The CLI asks for a story idea of up to 2,000 characters and an age from
5 to 10. Press Enter at the age
prompt to use age 7. The CLI labels the prewritten fallback if a personalized
draft cannot be approved.

Run `python main.py --debug` to see candidate scores, safety status, and
execution metrics. To run the offline test suite, install the development
requirements and use pytest.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Run `python evaluate.py` to preview the evaluation cases offline. See the
[evaluation guide](evaluations/README.md) for live-run options, metric
definitions, and the manual review checklist.
