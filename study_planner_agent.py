"""
StudyLens AI - Study Planner Agent


"""
from __future__ import annotations
 
from datetime import date, datetime, timedelta
from typing import Optional
 
from performance_agent import allocate_by_weight, topic_weight
 
SLOT_MINUTES = 15
MIN_HOURS, MAX_HOURS = 0.5, 16.0
CHECKPOINT_MIN_STUDY_DAYS = 5
MAX_FOCUS_QUESTIONS = 3
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
 
# readiness rule of thumb (an estimate, not a grade prediction)
MINUTES_PER_GAP_POINT = 3.0
MIN_MINUTES_PER_TOPIC = 30
COVERAGE_WEIGHT = 0.3
READY_ON_TRACK = 75.0
READY_GETTING_THERE = 55.0
 
BREAK_TIP_FROM_MINUTES = 90
BREAK_TIP = "Take a 10-minute break after every 45-50 minutes of study."
REST_NOTE = "Rest day - recharge, no study planned."
 
STUDY_ACTIVITY = {
    "weak": "Re-learn the core concepts from your notes, then redo the questions you missed",
    "needs_practice": "Practise questions on this topic and review the explanations for your mistakes",
    "strong": "Quick recap and a few practice questions to stay sharp",
}
FINAL_ACTIVITY = {
    "weak": "Final pass over your key weak points and previously missed questions",
    "needs_practice": "Skim your summary notes and retry a few missed questions",
    "strong": "Quick skim of key points only",
}
FINAL_NOTE = ("Retake the StudyLens quiz today as a mock check, then rest well "
              "before your exam.")
CHECKPOINT_NOTE = ("Checkpoint: retake the StudyLens quiz today so your plan can be "
                   "updated with your new scores.")
 
 
# ----------------------------------------------------------------- helpers
def format_duration(minutes) -> str:
    """Human-friendly length: 45 -> '45 min', 120 -> '2h', 105 -> '1h 45m'."""
    m = int(round(minutes))
    if m < 60:
        return f"{m} min"
    hours, rest = divmod(m, 60)
    return f"{hours}h" if rest == 0 else f"{hours}h {rest}m"
 
 
def minutes_with_hours(minutes) -> str:
    """Minutes with hours in brackets: 2100 -> '2100 min (35h)'; under an hour -> '45 min'."""
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m} min ({format_duration(m)})"
 
 
def _error(message: str) -> dict:
    return {
        "status": "error", "error": message, "exam_date": None, "start_date": None,
        "days_until_exam": 0, "hours_per_day": 0, "warnings": [],
        "total_minutes": 0, "total_hours": 0.0, "schedule": {}, "readiness": None,
        "topic_allocation": [], "daily_plan": [], "summary": "", "coach_message": None,
    }
 
 
def _parse_date(value, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    raise ValueError(f"{label} must be a date in YYYY-MM-DD format (got {value!r}).")
 
 
def _clean_weekday_hours(hours_by_weekday, warnings: list) -> dict:
    """Validate {"Sat": 4, "Sun": 0} -> {weekday_index: hours}. Raises ValueError."""
    if hours_by_weekday is None:
        return {}
    if not isinstance(hours_by_weekday, dict):
        raise ValueError("hours_by_weekday must be a dict like {'Sat': 4, 'Sun': 0}.")
    cleaned: dict = {}
    for key, value in hours_by_weekday.items():
        name = str(key).strip()[:3].title()
        if name not in WEEKDAYS:
            raise ValueError(f"hours_by_weekday has an unknown weekday {key!r} "
                             "(use Mon, Tue, Wed, Thu, Fri, Sat, Sun).")
        if isinstance(value, bool):
            raise ValueError(f"hours_by_weekday[{key!r}] must be a number.")
        try:
            hours = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"hours_by_weekday[{key!r}] must be a number.")
        if hours < 0:
            raise ValueError(f"hours_by_weekday[{key!r}] cannot be negative.")
        if hours > 0 and (hours < MIN_HOURS or hours > MAX_HOURS):
            clamped = min(max(hours, MIN_HOURS), MAX_HOURS)
            warnings.append(f"{name} hours adjusted from {hours:g} to {clamped:g} "
                            f"(allowed range {MIN_HOURS:g}-{MAX_HOURS:g}).")
            hours = clamped
        cleaned[WEEKDAYS.index(name)] = hours
    return cleaned
 
 
def _clean_rest_dates(rest_dates) -> set:
    """Validate a list of dates. Raises ValueError."""
    if rest_dates is None:
        return set()
    if isinstance(rest_dates, (str, date)):
        rest_dates = [rest_dates]
    try:
        items = list(rest_dates)
    except TypeError:
        raise ValueError("rest_dates must be a list of dates in YYYY-MM-DD format.")
    return {_parse_date(d, "rest_dates entry") for d in items}
 
 
def _hours_for(day: date, default_hours: float, weekday_hours: dict, rest_set: set) -> float:
    if day in rest_set:
        return 0.0
    return weekday_hours.get(day.weekday(), default_hours)
 
 
def _slots(hours: float) -> int:
    return max(1, int(round(hours * 60 / SLOT_MINUTES))) if hours > 0 else 0
 
 
def _distribute(capacities: list[int], alloc: dict, order: list[str]) -> list[dict]:
    """Spread each topic's slots across the days in proportion to what is left, so
    weak topics reappear every day. `capacities` is the number of slots each day can
    hold (0 = rest day). Returns one {topic: slots} dict per day."""
    remaining = dict(alloc)
    rank = {name: i for i, name in enumerate(order)}
    days = []
    for d, capacity in enumerate(capacities):
        counts: dict = {}
        capacity_left = sum(capacities[d:])
        if capacity > 0 and capacity_left > 0:
            quota = {t: remaining[t] * capacity / capacity_left for t in order}
            for _ in range(capacity):
                candidates = [t for t in order if remaining[t] > 0]
                if not candidates:
                    break
                pick = max(candidates, key=lambda t: (quota[t] - counts.get(t, 0), -rank[t]))
                counts[pick] = counts.get(pick, 0) + 1
                remaining[pick] -= 1
        days.append(counts)
    return days
 
 
def _shorten(text, limit: int = 120) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
 
 
def _blocks(counts: dict, order: list[str], by_name: dict, final: bool, seen: set) -> list[dict]:
    blocks = []
    for name in order:                         # weakest first - tackle hard stuff while fresh
        slots = counts.get(name, 0)
        if not slots:
            continue
        info = by_name[name]
        status = info["status"]
        focus: list[str] = []
        if name not in seen and status != "strong":
            focus = [_shorten(q.get("question")) for q in info["wrong_questions"][:MAX_FOCUS_QUESTIONS]
                     if q.get("question")]
        seen.add(name)
        blocks.append({
            "topic": name,
            "minutes": slots * SLOT_MINUTES,
            "status": status,
            "activity": (FINAL_ACTIVITY if final else STUDY_ACTIVITY)[status],
            "focus_questions": focus,
        })
    return blocks
 
 
def _readiness(topics: list[dict], planned_minutes: int) -> dict:
    """Rule-of-thumb readiness: 70% current knowledge + 30% how much of the
    recommended study time the plan covers."""
    mastery = sum(t["percentage"] for t in topics) / len(topics)
    recommended = int(round(sum(
        max(MIN_MINUTES_PER_TOPIC, (100.0 - t["percentage"]) * MINUTES_PER_GAP_POINT)
        for t in topics)))
    coverage = min(1.0, planned_minutes / recommended) if recommended else 1.0
    score = round((1 - COVERAGE_WEIGHT) * mastery + COVERAGE_WEIGHT * 100 * coverage, 1)
    if score >= READY_ON_TRACK:
        label = "On track"
    elif score >= READY_GETTING_THERE:
        label = "Getting there"
    else:
        label = "At risk"
    shortfall = max(0, recommended - planned_minutes)
    message = (
        f"If you follow this plan, your readiness is about {score:g}/100 ({label}). "
        f"It blends what you know now (average topic score {mastery:.0f}%) with how much of "
        f"the recommended study time ({minutes_with_hours(recommended)}) this plan covers "
        f"({round(100 * coverage, 1):g}%). It is a rule-of-thumb estimate, not a prediction "
        "of your exam mark."
    )
    if shortfall:
        message += (f" Add about {minutes_with_hours(shortfall)} of study time, or move the "
                    "exam date, to cover the rest.")
    return {
        "score": score, "label": label,
        "average_topic_score": round(mastery, 1),
        "time_coverage_percent": round(100 * coverage, 1),
        "planned_minutes": planned_minutes,
        "recommended_minutes": recommended,
        "shortfall_minutes": shortfall,
        "message": message,
    }
 
 
def _llm_coach_message(llm, performance: dict, summary: str) -> Optional[str]:
    if llm is None:
        return None
    system = (
        "You are a supportive study coach. In 2 short sentences, motivate the student "
        "about their study plan. Use ONLY the facts provided; do not invent numbers or "
        'topics. Return ONLY JSON: {"message": "..."}'
    )
    prompt = f"{performance.get('insight', '')}\n{summary}"
    try:
        out = llm.generate_json(system, prompt, max_tokens=200)
        text = str(out.get("message", "")).strip() if isinstance(out, dict) else ""
        return text or None
    except Exception:
        return None
 
 
# -------------------------------------------------------------- main entry
def generate_study_plan(performance: dict, exam_date, hours_per_day: float = 2.0,
                        start_date=None, llm=None, hours_by_weekday=None,
                        rest_dates=None) -> dict:
    """Build a personalised, weakness-weighted study plan. Never raises."""
    try:
        if not isinstance(performance, dict):
            return _error("performance must be a dict (the Performance Agent output).")
        if performance.get("status") == "error":
            return _error(f"Performance Agent reported an error: {performance.get('error')}")
        raw_topics = performance.get("topics")
        if not isinstance(raw_topics, list) or not raw_topics:
            return _error("performance has no topics. Run analyze_performance() first.")
 
        try:
            exam = _parse_date(exam_date, "exam_date")
            start = _parse_date(start_date, "start_date") if start_date is not None else date.today()
        except ValueError as exc:
            return _error(str(exc))
 
        if isinstance(hours_per_day, bool):
            return _error("hours_per_day must be a number.")
        try:
            hours = float(hours_per_day)
        except (TypeError, ValueError):
            return _error("hours_per_day must be a number.")
        if not hours > 0:
            return _error("hours_per_day must be greater than 0.")
 
        warnings: list[str] = []
        if hours < MIN_HOURS or hours > MAX_HOURS:
            clamped = min(max(hours, MIN_HOURS), MAX_HOURS)
            warnings.append(f"hours_per_day adjusted from {hours:g} to {clamped:g} "
                            f"(allowed range {MIN_HOURS:g}-{MAX_HOURS:g}).")
            hours = clamped
 
        days_available = (exam - start).days
        if days_available < 1:
            return _error(f"The exam date ({exam.isoformat()}) must be after the start date "
                          f"({start.isoformat()}).")
 
        try:
            weekday_hours = _clean_weekday_hours(hours_by_weekday, warnings)
            rest_set = _clean_rest_dates(rest_dates)
        except ValueError as exc:
            return _error(str(exc))
 
        # weakest first, each with a weight
        topics = []
        for t in raw_topics:
            if not isinstance(t, dict) or "topic" not in t or "percentage" not in t:
                return _error("Each performance topic needs 'topic' and 'percentage'.")
            topics.append({
                "topic": t["topic"],
                "percentage": float(t["percentage"]),
                "status": t.get("status") if t.get("status") in STUDY_ACTIVITY else "needs_practice",
                "weight": topic_weight(float(t["percentage"])),
                "wrong_questions": t.get("wrong_questions") or [],
            })
        topics.sort(key=lambda t: (t["percentage"], str(t["topic"])))
        order = [t["topic"] for t in topics]
        by_name = {t["topic"]: t for t in topics}
 
        n_study = days_available - 1       # the last day before the exam is final revision
        final_date = start + timedelta(days=days_available - 1)
        study_caps = [
            _slots(_hours_for(start + timedelta(days=i), hours, weekday_hours, rest_set))
            for i in range(n_study)
        ]
        final_hours = _hours_for(final_date, hours, weekday_hours, rest_set)
        if final_hours <= 0:
            final_hours = hours
            warnings.append(f"{final_date.isoformat()} (the day before your exam) was set as a "
                            "rest day, but it is always used for final revision.")
        final_slots = _slots(final_hours)
 
        study_counts = _distribute(
            study_caps, allocate_by_weight(sum(study_caps), topics), order
        ) if n_study else []
        final_counts = allocate_by_weight(final_slots, topics)
 
        active = [i for i, cap in enumerate(study_caps) if cap > 0]
        first_i = active[0] if active else None
        checkpoint_i = (active[len(active) // 2 - 1]
                        if len(active) >= CHECKPOINT_MIN_STUDY_DAYS else None)
 
        seen: set = set()
        daily_plan = []
        for i in range(days_available):
            current = start + timedelta(days=i)
            is_final = i == days_available - 1
            base = {"day": i + 1, "date": current.isoformat(), "weekday": current.strftime("%a")}
 
            if not is_final and study_caps[i] == 0:
                daily_plan.append({**base, "phase": "rest", "total_minutes": 0,
                                   "total_hours": 0.0, "blocks": [], "note": REST_NOTE,
                                   "break_tip": None})
                continue
 
            blocks = _blocks(final_counts if is_final else study_counts[i], order, by_name,
                             is_final, seen)
            total = sum(b["minutes"] for b in blocks)
            note = None
            if is_final:
                note = FINAL_NOTE
            elif i == checkpoint_i:
                note = CHECKPOINT_NOTE
            elif i == first_i:
                note = "Start with your weakest topic while your mind is fresh."
            daily_plan.append({
                **base,
                "phase": "final_revision" if is_final else "study",
                "total_minutes": total,
                "total_hours": round(total / 60, 2),
                "blocks": blocks,
                "note": note,
                "break_tip": BREAK_TIP if total >= BREAK_TIP_FROM_MINUTES else None,
            })
 
        minutes = {name: 0 for name in order}
        for day in daily_plan:
            for b in day["blocks"]:
                minutes[b["topic"]] += b["minutes"]
        grand_total = sum(minutes.values()) or 1
        topic_allocation = [
            {"topic": name, "status": by_name[name]["status"],
             "percentage": by_name[name]["percentage"],
             "total_minutes": minutes[name],
             "total_hours": round(minutes[name] / 60, 2),
             "share_percent": round(100 * minutes[name] / grand_total, 1)}
            for name in order
        ]
 
        top = max(topic_allocation, key=lambda a: (a["total_minutes"], -order.index(a["topic"])))
        study_days = sum(1 for d in daily_plan if d["total_minutes"] > 0)
        custom = bool(weekday_hours or rest_set)
        pace = (f"studying {hours:g}h/day" if not custom
                else f"studying on {study_days} of {days_available} days (custom schedule)")
        summary = (
            f"{days_available} day{'s' if days_available != 1 else ''} until your exam on "
            f"{exam.isoformat()}, {pace}, {minutes_with_hours(grand_total)} in total. "
        )
        if top["status"] == "strong":
            summary += "Your scores are strong everywhere, so the plan focuses on steady revision. "
        else:
            summary += (f"Most time goes to {top['topic']}: "
                        f"{minutes_with_hours(top['total_minutes'])}, "
                        f"{top['share_percent']:g}% of the plan. ")
        summary += "Retake the quiz to refresh the plan as you improve."
 
        return {
            "status": "success", "error": None,
            "exam_date": exam.isoformat(), "start_date": start.isoformat(),
            "days_until_exam": days_available, "hours_per_day": hours, "warnings": warnings,
            "total_minutes": grand_total, "total_hours": round(grand_total / 60, 2),
            "schedule": {
                "hours_per_day": hours,
                "hours_by_weekday": {WEEKDAYS[i]: h for i, h in sorted(weekday_hours.items())},
                "rest_dates": sorted(d.isoformat() for d in rest_set),
            },
            "readiness": _readiness(topics, grand_total),
            "topic_allocation": topic_allocation, "daily_plan": daily_plan,
            "summary": summary,
            "coach_message": _llm_coach_message(llm, performance, summary),
        }
    except Exception as exc:  # never crash the orchestrator
        return _error(f"generate_study_plan failed: {exc}")
 
