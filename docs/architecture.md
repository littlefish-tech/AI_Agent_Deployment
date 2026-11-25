# Architecture

Solid arrows carry data or control. Dashed arrows show the model calls shared
by generation, judging, and refinement.

[Open the rendered SVG](system-flow.svg)

```mermaid
%%{init: {"theme": "base", "flowchart": {"htmlLabels": false, "nodeSpacing": 24, "rankSpacing": 38}, "themeVariables": {"fontFamily": "Arial, sans-serif", "fontSize": "15px", "lineColor": "#475569"}}}%%
flowchart TB
    accTitle: Bedtime story evaluator and optimizer
    accDescr: Python validates input, drafts and judges stories through Claude Haiku 5.5, and releases an approved draft or a prewritten fallback. Every revision returns to the judge.
    U(["User: story request and target age"])
    C["CLI and input validation<br/>main.py · validation.py"]
    E["Evaluation runner<br/>evaluate.py"]
    O["Python orchestrator<br/>AgentOrchestrator.run_agent"]
    G["Initial prompt<br/>Storyteller system prompt + age guidance<br/>User JSON: story request"]
    S["Storyteller Agent<br/>Generate or revise"]
    D["Generated story<br/>Initial draft or complete revision"]
    JP["Judge prompt<br/>System rubric + correction instruction when retrying<br/>User JSON: original request, age, draft"]
    J["LLM Judge Agent"]
    R["Structured evaluation JSON<br/>Scores, safety verdict, strengths, feedback, issues"]
    V{"Valid judge verdict?<br/>Python checks schema and invariants"}
    CR{"Correction still available?"}
    W["Python weighted quality score"]
    SAFE{"Child safety passes?"}
    QUAL{"Quality thresholds pass?"}
    REV{"Revisions remaining?<br/>Maximum two"}
    RP["Refinement prompt<br/>Storyteller rules + age guidance + revision instructions<br/>User JSON: request, draft, judge feedback and safety concerns"]
    F["Prewritten fallback<br/>The Last Little Lantern"]
    OUT(["Deliver approved story or labeled fallback"])
    API["Shared Anthropic Python SDK client<br/>Messages API, timeout, bounded retries"]
    MODEL["Claude Haiku 5.5<br/>Direct Anthropic or OpenRouter"]

    U --> C
    C -->|"Valid request + age"| O
    E -->|"Validated case + shared call budget"| O
    O --> G --> S --> D
    D -->|"Every draft, including revisions"| JP --> J --> R --> V
    V -->|"Yes"| W --> SAFE
    V -->|"No"| CR
    CR -->|"Yes, resend the same inputs once"| JP
    CR -->|"No"| F
    SAFE -->|"Yes"| QUAL
    SAFE -->|"No"| REV
    QUAL -->|"Yes, first passing draft"| OUT
    QUAL -->|"No"| REV
    REV -->|"No"| F
    REV -->|"Yes, include feedback and safety concerns"| RP --> S
    F --> OUT
    S -.->|"Generation or revision request"| API
    J -.->|"Structured evaluation request"| API
    API -.->|"Model request and response"| MODEL
    API -->|"Expected call failure or budget exhaustion during run"| F

    classDef python fill:#eaf2fb,stroke:#315d8a,color:#142d45;
    classDef model fill:#f2ebff,stroke:#6946a0,color:#32214e;
    classDef decision fill:#fff3d9,stroke:#9b6319,color:#472c0c;
    classDef delivery fill:#e6f5eb,stroke:#2d6846,color:#183d2b;
    classDef data fill:#f5f7fa,stroke:#64748b,color:#1e293b;
    class C,E,O,G,JP,W,RP,API python;
    class S,J,MODEL model;
    class V,CR,SAFE,QUAL,REV decision;
    class F,OUT delivery;
    class U,D,R data;
```

Blue blocks run in Python. Purple blocks invoke the model. Amber diamonds
are Python decisions. The judge reports a safety verdict and criterion
scores. Python validates the response, calculates the weighted quality score,
and requires both the child-safety gate and all quality thresholds to pass.
It accepts the first passing draft. A revised draft enters the same judge
path as the initial draft.

The CLI reprompts after invalid input and exits with a setup message if it
cannot initialize the client. During evaluation or an interactive story run,
expected model failures trigger the fallback after any eligible SDK retries.
If a completed judge reply fails validation, the judge resends the same
inputs with a trusted correction instruction. A second invalid verdict
triggers the fallback. The evaluation script reuses the same
orchestrator and stores score and execution metadata instead of story text.
See the [solution walkthrough](SOLUTION.md) for measured examples and the
exact release thresholds.
