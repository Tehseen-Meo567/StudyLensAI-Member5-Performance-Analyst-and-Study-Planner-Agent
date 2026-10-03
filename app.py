"""
StudyLens AI - Member 5 demo (Performance Analysis + Study Planner)

Run:  streamlit run app.py
Paste or upload Member 4's quiz result JSON (or use the sample), pick an exam
date and daily study hours, and see the analysis and the study plan.
"""

import json
import os
from datetime import date, timedelta

import streamlit as st

from member5_agent import run_member5_agent

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = {"weak": "🔴", "needs_practice": "🟡", "strong": "🟢"}
LABEL = {"weak": "Weak", "needs_practice": "Needs practice", "strong": "Strong"}

st.set_page_config(page_title="StudyLens AI - Performance & Study Plan", page_icon="📚", layout="wide")
st.title("📚 StudyLens AI - Performance & Study Plan")
st.caption("Member 5: Performance Analysis Agent + Study Planner Agent")


def load_json(uploaded, pasted):
    if uploaded is not None:
        return json.load(uploaded)
    if pasted.strip():
        return json.loads(pasted)
    return None


with st.sidebar:
    st.header("1. Quiz result")
    source = st.radio("Source", ["Sample quiz result", "Upload / paste JSON"])
    uploaded = pasted = None
    if source == "Upload / paste JSON":
        uploaded = st.file_uploader("Quiz Agent output (.json)", type="json")
        pasted = st.text_area("...or paste it here", height=120)
    prev_file = st.file_uploader("Previous attempt (optional)", type="json",
                                 help="Shows improvement or decline per topic.")

    st.header("2. Exam details")
    exam = st.date_input("Exam date", value=date.today() + timedelta(days=14),
                         min_value=date.today() + timedelta(days=1))
    hours = st.slider("Study hours per day", 0.5, 8.0, 2.0, 0.5)
    go = st.button("Generate my plan", type="primary", use_container_width=True)

if go:
    try:
        if source == "Sample quiz result":
            with open(os.path.join(HERE, "sample_quiz_result.json"), encoding="utf-8") as f:
                quiz = json.load(f)
        else:
            quiz = load_json(uploaded, pasted or "")
        previous = json.load(prev_file) if prev_file else None
    except (json.JSONDecodeError, OSError) as exc:
        st.error(f"Could not read the JSON: {exc}")
        st.stop()

    if quiz is None:
        st.warning("Upload or paste a quiz result first.")
        st.stop()

    with st.spinner("Analysing your performance and building your plan..."):
        st.session_state["out"] = run_member5_agent(quiz, exam.isoformat(), hours,
                                                    previous_performance=previous)

out = st.session_state.get("out")
if not out:
    st.info("Choose a quiz result and exam date in the sidebar, then click **Generate my plan**.")
    st.stop()

perf, plan = out["performance"], out["study_plan"]
if out["status"] == "error":
    st.error(out["error"])
if not perf:
    st.stop()

# ----------------------------------------------------------- performance
st.header("Your performance")
overall = perf["overall"]
c1, c2, c3 = st.columns(3)
c1.metric("Score", f"{overall['score']:g} / {overall['total']}")
c2.metric("Overall", f"{overall['percentage']:g}%",
          delta=(f"{overall['trend']['change']:+g} pts" if overall.get("trend") else None))
c3.metric("Level", LABEL[overall["level"]])
st.info(perf["insight"])

left, right = st.columns([3, 2])
with left:
    st.bar_chart({t["topic"]: t["percentage"] for t in perf["topics"]}, y_label="Score %")
with right:
    for t in perf["topics"]:
        trend = f" ({t['trend']['direction']}, {t['trend']['change']:+g})" if t.get("trend") else ""
        st.write(f"{ICON[t['status']]} **{t['topic']}** - {t['percentage']:g}%{trend}")

with st.expander("Questions to review"):
    for t in perf["topics"]:
        if t["wrong_questions"]:
            st.markdown(f"**{t['topic']}**")
            for q in t["wrong_questions"]:
                st.write(f"- {q['question']}  \n  Correct answer: {q['correct_answer']}")

# -------------------------------------------------------------- the plan
if plan:
    st.header("Your study plan")
    st.write(plan["summary"])
    if plan.get("coach_message"):
        st.success(plan["coach_message"])
    for w in plan["warnings"]:
        st.warning(w)

    st.subheader("Time per topic")
    st.bar_chart({a["topic"]: a["total_minutes"] for a in plan["topic_allocation"]}, y_label="Minutes")

    st.subheader("Day by day")
    for d in plan["daily_plan"]:
        title = f"Day {d['day']} - {d['weekday']} {d['date']} ({d['total_minutes']} min)"
        if d["phase"] == "final_revision":
            title += " - Final revision"
        with st.expander(title, expanded=d["day"] == 1):
            if d["note"]:
                st.caption(d["note"])
            for b in d["blocks"]:
                st.markdown(f"{ICON[b['status']]} **{b['topic']}** - {b['minutes']} min  \n{b['activity']}")
                for q in b["focus_questions"]:
                    st.write(f"  - Revisit: {q}")

    st.download_button("Download plan (JSON)", json.dumps(out, indent=2),
                       file_name="studylens_plan.json", mime="application/json")
