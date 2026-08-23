# Example profiles

Saved answers for `python -m cli --profile <file>`, so a run can be repeated
without retyping eight questions. Useful because the Groq daily ceiling is the
binding constraint here: you re-run the same profile many times while changing
one thing upstream.

| File | What it shows |
| --- | --- |
| `beginner_renewables.json` | The main demo. A restriction (`no fossil fuels`) that has to survive all the way from the profile to the themes to the companies. |
| `semiconductors_high_risk.json` | A well-covered sector, so retrieval finds plenty and the run usually reaches a recommendation. |
| `conflicted_crypto.json` | Wants crypto AND rules out crypto, so **Agent 1 stops and asks**. Use this to see the clarification interrupt and the resume. |

Write your own with `python -m cli --save-profile mine.json`; the schema is
`UserInput` in [models/user_input.py](../models/user_input.py).
