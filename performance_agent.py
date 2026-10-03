"""
StudyLens AI - Performance Analysis Agent 
"""
from __future__ import annotations
 
from typing import Optional
 
WEAK_BELOW = 50.0          # percentage below which a topic is "weak"
STRONG_AT = 75.0           # percentage at/above which a topic is "strong"
LOW_CONFIDENCE_BELOW = 2   # topics with fewer questions are only a rough signal
TREND_DELTA = 5.0          # change (in points) needed to call it improved/declined
NOT_ANSWERED = "(not answered)"   # marker used by Member 4's Quiz Agent
 
WEIGHT_FLOOR = 15.0        # even a 100% topic keeps a small share of time/questions
FOCUS_MIN_QUESTIONS = 5    # size limits for the suggested next quiz
FOCUS_MAX_QUESTIONS = 30
TYPE_GAP_POINTS = 25.0     # score gap between question types worth mentioning
MIN_TYPE_QUESTIONS = 2     # a type needs this many questions to be compared
SKIPPED_MANY_SHARE = 0.2   # share of unanswered questions that is worth a warning
 
TYPE_LABELS = {
    "mcq": "multiple-choice",
    "true_false": "true/false",
    "short": "short-answer",
    "long": "long-answer",
}
 
 
# ----------------------------------------------------------------- helpers
def _error(message: str) -> dict:
    return {
        "status": "error", "error": message, "overall": {}, "topics": [],
        "weak_topics": [], "needs_practice_topics": [], "strong_topics": [],
        "mistake_analysis": {}, "quiz_focus": {},
        "insight": "", "insight_source": None,
    }
 
 
def classify(percentage: float) -> str:
    """Map a topic percentage to weak / needs_practice / strong."""
    if percentage < WEAK_BELOW:
        return "weak"
    if percentage < STRONG_AT:
        return "needs_practice"
    return "strong"
 
 
def topic_weight(percentage: float) -> float:
    """How much attention a topic deserves: the weaker, the bigger (never below the floor)."""
    return max(WEIGHT_FLOOR, 100.0 - percentage)
 
 
def allocate_by_weight(total: int, topics: list[dict]) -> dict:
    """Split `total` units (questions or time slots) between topics by weight.
 
    `topics` is a list of {"topic", "weight"} sorted weakest-first. Every topic
    gets at least one unit when there are enough; if not, the weakest topics get
    them first. Uses the largest-remainder method so the units add up exactly."""
    alloc = {t["topic"]: 0 for t in topics}
    if total <= 0 or not topics:
        return alloc
    if total < len(topics):
        for t in topics[:total]:
            alloc[t["topic"]] = 1
        return alloc
 
    for t in topics:
        alloc[t["topic"]] = 1
    spare = total - len(topics)
    total_weight = sum(t["weight"] for t in topics)
    exact = {t["topic"]: spare * t["weight"] / total_weight for t in topics}
    for name, value in exact.items():
        alloc[name] += int(value)
    leftover = spare - sum(int(v) for v in exact.values())
    by_remainder = sorted(
        enumerate(topics),
        key=lambda it: (-(exact[it[1]["topic"]] - int(exact[it[1]["topic"]])), it[0]),
    )
    for _, t in by_remainder[:leftover]:
        alloc[t["topic"]] += 1
    return alloc
 
 
def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
 
 
def _topic_percentage(stats: dict) -> float:
    """Use Member 4's 'percentage'; fall back to marks/max_marks or correct/total."""
    pct = _num(stats.get("percentage"))
    if pct is not None:
        return pct
    got = _num(stats.get("marks"))
    if got is None:
        got = _num(stats.get("correct"))
    out_of = _num(stats.get("max_marks"))
    if out_of is None:
        out_of = _num(stats.get("total"))
    if got is None or not out_of:
        raise ValueError("no usable score data")
    return round(100 * got / out_of, 1)
 
 
def _previous_data(previous) -> tuple[dict, Optional[float]]:
    """Return ({topic: percentage}, overall_percentage) from an earlier run."""
    if not isinstance(previous, dict):
        return {}, None
    topics: dict = {}
    if isinstance(previous.get("topics"), list):            # earlier analysis
        for t in previous["topics"]:
            if isinstance(t, dict) and "topic" in t and _num(t.get("percentage")) is not None:
                topics[t["topic"]] = float(t["percentage"])
        overall = _num((previous.get("overall") or {}).get("percentage"))
    elif isinstance(previous.get("topic_performance"), dict):  # earlier quiz result
        for name, stats in previous["topic_performance"].items():
            try:
                topics[name] = _topic_percentage(stats)
            except Exception:
                pass
        overall = _num(previous.get("percentage"))
    else:
        return {}, None
    return topics, overall
 
 
def _trend(current: float, previous: Optional[float]) -> Optional[dict]:
    if previous is None:
        return None
    change = round(current - previous, 1)
    if change >= TREND_DELTA:
        direction = "improved"
    elif change <= -TREND_DELTA:
        direction = "declined"
    else:
        direction = "steady"
    return {"previous": round(previous, 1), "change": change, "direction": direction}
 
 
def _names(topics: list[dict]) -> str:
    return ", ".join(t["topic"] for t in topics)
 
 
# ------------------------------------------------------- mistake analysis
def _mistake_analysis(results: list[dict]) -> dict:
    """Look for patterns in HOW the student lost marks (type, skipped, partial credit)."""
    marks_by_type: dict = {}
    by_type: dict = {}
    skipped_ids: list = []
    partial = 0
 
    for r in results:
        marks = _num(r.get("marks"))
        if marks is None:
            marks = 1.0 if r.get("is_correct") else 0.0
        if r.get("student_answer") == NOT_ANSWERED:
            skipped_ids.append(r.get("id"))
        qtype = r.get("type")
        if qtype:
            stats = by_type.setdefault(qtype, {
                "label": TYPE_LABELS.get(qtype, str(qtype)), "correct": 0, "total": 0})
            stats["total"] += 1
            stats["correct"] += 1 if r.get("is_correct") else 0
            marks_by_type[qtype] = marks_by_type.get(qtype, 0.0) + marks
            if qtype in ("short", "long") and 0 < marks < 1:
                partial += 1
 
    for qtype, stats in by_type.items():
        stats["percentage"] = round(100 * marks_by_type[qtype] / stats["total"], 1)
 
    n_results = len(results)
    skipped = {
        "count": len(skipped_ids),
        "ids": skipped_ids,
        "percentage": round(100 * len(skipped_ids) / n_results, 1) if n_results else 0.0,
    }
 
    patterns: list[str] = []
    if skipped["count"]:
        n = skipped["count"]
        if n_results and n / n_results >= SKIPPED_MANY_SHARE:
            patterns.append(
                f"You left {n} of {n_results} questions unanswered. That can mean knowledge "
                "gaps or running short of time - practise finishing the whole quiz.")
        else:
            patterns.append(
                f"You left {n} question{'s' if n != 1 else ''} unanswered. Review those topics "
                "and, if there is no negative marking, attempt every question.")
 
    comparable = [s for s in by_type.values() if s["total"] >= MIN_TYPE_QUESTIONS]
    if len(comparable) >= 2:
        best = max(comparable, key=lambda s: s["percentage"])
        worst = min(comparable, key=lambda s: s["percentage"])
        if best["percentage"] - worst["percentage"] >= TYPE_GAP_POINTS:
            patterns.append(
                f"You scored {worst['percentage']:g}% on {worst['label']} questions vs "
                f"{best['percentage']:g}% on {best['label']} - practise more "
                f"{worst['label']} questions.")
 
    if partial:
        patterns.append(
            f"{partial} written answer{'s were' if partial != 1 else ' was'} partly right - "
            "you know the idea but are missing key terms, so revise the key vocabulary.")
 
    return {"by_type": by_type, "skipped": skipped, "partial_credit": partial,
            "patterns": patterns}
 
 
# --------------------------------------------------------- next-quiz focus
def _quiz_focus(topics: list[dict], overall_total: int) -> dict:
    """Suggest how many questions per topic the next quiz should have (weak topics most)."""
    total = min(max(int(overall_total or 0), FOCUS_MIN_QUESTIONS), FOCUS_MAX_QUESTIONS)
    items = [{"topic": t["topic"], "weight": topic_weight(t["percentage"])} for t in topics]
    alloc = allocate_by_weight(total, items)          # topics are already weakest-first
    return {
        "total_questions": total,
        "topics": {name: n for name, n in alloc.items() if n > 0},
        "note": "Suggested questions per topic for the next quiz - weak topics get the most.",
    }
 
 
# ----------------------------------------------------------------- insight
def _rule_insight(overall: dict, topics: list[dict]) -> str:
    parts = [f"You scored {overall['percentage']:g}% overall "
             f"({overall['score']:g}/{overall['total']})."]
    trend = overall.get("trend")
    if trend and trend["direction"] != "steady":
        parts.append(f"That is {abs(trend['change']):g} points "
                     f"{'up' if trend['change'] > 0 else 'down'} from your last attempt.")
    weak = [t for t in topics if t["status"] == "weak"]
    mid = [t for t in topics if t["status"] == "needs_practice"]
    strong = [t for t in topics if t["status"] == "strong"]
    if weak:
        parts.append(f"Focus first on {_names(weak)} - these scored below {WEAK_BELOW:g}%.")
    if mid:
        parts.append(f"{_names(mid)} {'needs' if len(mid) == 1 else 'need'} more practice.")
    if strong:
        parts.append(f"You are doing well in {_names(strong)}; a light revision will keep it fresh.")
    if not weak and not mid:
        parts.append("Great work - keep revising regularly to stay at this level.")
    if any(t["low_confidence"] for t in topics):
        parts.append("Topics with only one question are a rough signal, so retake the quiz to confirm them.")
    return " ".join(parts)
 
 
def _llm_insight(llm, overall: dict, topics: list[dict]) -> Optional[str]:
    if llm is None:
        return None
    system = (
        "You are a supportive study coach. Using ONLY the facts provided, write 2-3 "
        "encouraging sentences summarising the student's quiz performance and what to "
        "focus on. Do not invent topics or numbers. "
        'Return ONLY JSON: {"insight": "..."}'
    )
    facts = [f"Overall: {overall['percentage']:g}% ({overall['score']:g}/{overall['total']})"]
    for t in topics:
        facts.append(f"- {t['topic']}: {t['percentage']:g}% ({t['status']})")
    try:
        out = llm.generate_json(system, "\n".join(facts), max_tokens=300)
        text = str(out.get("insight", "")).strip() if isinstance(out, dict) else ""
        return text or None
    except Exception:
        return None
 
 
# -------------------------------------------------------------- main entry
def analyze_performance(quiz_result: dict, previous_performance: Optional[dict] = None,
                        llm=None) -> dict:
    """Analyze Member 4's quiz result. Never raises."""
    try:
        if not isinstance(quiz_result, dict):
            return _error("quiz_result must be a dict (the Quiz Agent output).")
        if quiz_result.get("status") == "error":
            return _error(f"Quiz Agent reported an error: {quiz_result.get('error')}")
        topic_perf = quiz_result.get("topic_performance")
        if not isinstance(topic_perf, dict) or not topic_perf:
            return _error("quiz_result has no topic_performance data.")
 
        results = [r for r in (quiz_result.get("results") or []) if isinstance(r, dict)]
        prev_topics, prev_overall = _previous_data(previous_performance)
 
        topics: list[dict] = []
        for name, stats in topic_perf.items():
            if not isinstance(stats, dict):
                return _error(f"topic_performance['{name}'] must be a dict.")
            try:
                pct = _topic_percentage(stats)
            except ValueError:
                return _error(f"Topic '{name}' has no usable score data.")
 
            missed = [r for r in results if r.get("topic") == name and not r.get("is_correct")]
            total = int(_num(stats.get("total")) or sum(1 for r in results if r.get("topic") == name))
            correct = int(_num(stats.get("correct")) or 0)
            topics.append({
                "topic": name,
                "percentage": round(pct, 1),
                "correct": correct,
                "total": total,
                "status": classify(pct),
                "low_confidence": total < LOW_CONFIDENCE_BELOW,
                "unanswered": sum(1 for r in missed if r.get("student_answer") == NOT_ANSWERED),
                "wrong_questions": [
                    {"id": r.get("id"), "question": r.get("question"),
                     "student_answer": r.get("student_answer"),
                     "correct_answer": r.get("correct_answer"),
                     "marks": r.get("marks", 0)}
                    for r in missed
                ],
                "trend": _trend(pct, prev_topics.get(name)),
            })
 
        topics.sort(key=lambda t: (t["percentage"], t["topic"]))   # weakest first
        for rank, t in enumerate(topics, start=1):
            t["priority_rank"] = rank
 
        # overall numbers: prefer Member 4's, otherwise derive them
        total_q = _num(quiz_result.get("total"))
        score = _num(quiz_result.get("score"))
        overall_pct = _num(quiz_result.get("percentage"))
        if overall_pct is None:
            if score is not None and total_q:
                overall_pct = round(100 * score / total_q, 1)
            else:
                overall_pct = round(sum(t["percentage"] for t in topics) / len(topics), 1)
        overall = {
            "score": score if score is not None else 0.0,
            "total": int(total_q) if total_q is not None else sum(t["total"] for t in topics),
            "percentage": round(overall_pct, 1),
            "level": classify(overall_pct),
            "trend": _trend(overall_pct, prev_overall),
        }
 
        insight = _llm_insight(llm, overall, topics)
        source = "llm"
        if not insight:
            insight, source = _rule_insight(overall, topics), "rules"
 
        return {
            "status": "success", "error": None,
            "overall": overall, "topics": topics,
            "weak_topics": [t["topic"] for t in topics if t["status"] == "weak"],
            "needs_practice_topics": [t["topic"] for t in topics if t["status"] == "needs_practice"],
            "strong_topics": [t["topic"] for t in topics if t["status"] == "strong"],
            "mistake_analysis": _mistake_analysis(results),
            "quiz_focus": _quiz_focus(topics, overall["total"]),
            "insight": insight, "insight_source": source,
        }
    except Exception as exc:  # never crash the orchestrator
        return _error(f"analyze_performance failed: {exc}")
 
 
if __name__ == "__main__":
    import json
    demo = {
        "status": "success", "error": None, "score": 5.0, "total": 10, "percentage": 50.0,
        "results": [],
        "topic_performance": {
            "Cell Biology": {"correct": 3, "total": 3, "marks": 3.0, "max_marks": 3, "percentage": 100.0},
            "Genetics": {"correct": 1, "total": 3, "marks": 1.0, "max_marks": 3, "percentage": 33.3},
        },
    }
    print(json.dumps(analyze_performance(demo), indent=2))
 
