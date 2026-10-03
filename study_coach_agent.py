

from __future__ import annotations

from typing import Optional

from performance_agent import analyze_performance
from study_planner_agent import generate_study_plan


def run_study_coach_agent(quiz_result: dict, exam_date, hours_per_day: float = 2.0,
                      start_date=None, previous_performance: Optional[dict] = None,
                      llm=None) -> dict:
    """One-call entry point: Performance Agent -> Study Planner Agent. Never raises."""
    try:
        perf = analyze_performance(quiz_result, previous_performance, llm)
        if perf["status"] == "error":
            return {"status": "error", "error": perf["error"],
                    "performance": None, "study_plan": None}
        plan = generate_study_plan(perf, exam_date, hours_per_day, start_date, llm)
        return {
            "status": plan["status"], "error": plan["error"],
            "performance": perf,
            "study_plan": plan if plan["status"] == "success" else None,
        }
    except Exception as exc:
        return {"status": "error", "error": f"run_study_coach_agent failed: {exc}",
                "performance": None, "study_plan": None}
