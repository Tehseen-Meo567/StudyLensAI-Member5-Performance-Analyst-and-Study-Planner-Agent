# StudyLens AI — Study Coach: Performance Analysis + Study Planner Agent

Takes the Quiz Agent's (Member 4) result and turns it into weak/strong topics and a
personalised, adaptive day-by-day study plan up to the exam date.

## Files

| File | Purpose |
|---|---|
| `performance_agent.py` | Performance Agent — `analyze_performance()` |
| `study_planner_agent.py` | Study Planner Agent — `generate_study_plan()` |
| `study_coach_agent.py` | One-call entry for the Orchestrator — `run_study_coach_agent()` |
| `app.py` | Streamlit demo |
| `test_study_coach.py` | Level 1 tests (`python test_study_coach.py`) |
| `sample_quiz_result.json` | Real output of Member 4's agent, used by tests and demo |

## Interface

**Input** — exactly what Member 4's `run_quiz_agent()` returns (`score`, `total`,
`percentage`, `results`, `topic_performance`), plus `exam_date` (`YYYY-MM-DD`) and
`hours_per_day`.

```python
from study_coach_agent import run_study_coach_agent
out = run_study_coach_agent(quiz_result, exam_date="2026-10-20", hours_per_day=2)

out["performance"]   # weak / needs_practice / strong topics + insight
out["study_plan"]    # day-by-day plan
```

**Output of `analyze_performance()`**

```
{"status": "success", "error": None,
 "overall": {"score", "total", "percentage", "level", "trend"},
 "topics": [{"topic", "percentage", "correct", "total", "status", "priority_rank",
             "low_confidence", "unanswered", "wrong_questions", "trend"}],   # weakest first
 "weak_topics": [...], "needs_practice_topics": [...], "strong_topics": [...],
 "insight": "...", "insight_source": "rules" | "llm"}
```

Topic status: **weak** < 50% · **needs_practice** 50–74.9% · **strong** ≥ 75%.

**Output of `generate_study_plan()`**

```
{"status": "success", "error": None, "exam_date", "start_date", "days_until_exam",
 "hours_per_day", "warnings": [], "total_minutes", "total_hours",
 "topic_allocation": [{"topic", "status", "percentage", "total_minutes", "total_hours",
                       "share_percent"}],
 "daily_plan": [{"day", "date", "weekday", "phase": "study" | "final_revision",
                 "total_minutes", "total_hours", "blocks": [{"topic", "minutes", "status", "activity",
                 "focus_questions"}], "note"}],
 "summary": "...", "coach_message": None | "..."}
```

**Errors** — never raises. On failure: `{"status": "error", "error": "message", ...}`
(same style as Member 4). If only the planner fails (e.g. bad exam date), `run_study_coach_agent`
returns `status: "error"` with `performance` still filled.

## How the plan works

- Days 1…N-1 are study days; the day before the exam is final revision.
- Each topic's time is weighted by weakness: `weight = max(15, 100 − score%)`.
  Weak topics get the most time, strong ones a light recap, every topic appears.
- Time is split into 15-minute slots and spread over the days so weak topics come back
  repeatedly (spaced practice). Weakest topic is scheduled first each day.
- The first time a weak topic appears, the plan lists the exact questions the student missed.
- Plans with 5+ study days get a mid-way checkpoint day to retake the quiz.
- All numbers are computed in plain Python; an optional LLM only rewrites the insight text
  and adds a short coach message. If the LLM fails, rule-based text is used.

## Adaptive re-planning

After the student retakes the quiz, call again with the new result and the old analysis:

```python
out2 = run_study_coach_agent(new_quiz_result, exam_date, hours,
                         previous_performance=out["performance"])
```

The plan is rebuilt from today to the exam with the updated weak topics, and each topic
shows whether it improved, declined, or stayed steady.

## Optional LLM (Member 3's GroqLLM)

Pass any object with `generate_json(system, prompt, max_tokens)`:

```python
out = run_study_coach_agent(quiz_result, exam_date, 2, llm=my_groq_llm)
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
python test_study_coach.py
```

No API keys needed. For the integration test, copy Member 4's `quiz_agent.py` next to
these files (it is skipped automatically if not found).
