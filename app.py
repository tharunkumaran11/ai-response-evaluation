"""Run with python -m streamlit run app.py."""
import csv
import io
import json
import os
import sqlite3
from statistics import mean

import streamlit as st

from rubric import RUBRIC, VERSION
from store import DATA, ROOT, Store, benchmark, load_dataset

st.set_page_config(page_title="Response Benchmark", layout="wide")
st.title("AI Response Evaluation & Benchmarking")
try:
    dataset = load_dataset(os.environ.get("BENCHMARK_DATASET", DATA))
    store = Store(os.environ.get("BENCHMARK_DB", ROOT / "reviews.sqlite3"), dataset["id"])
except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
    st.error(f"Could not open the dataset or review database: {exc}")
    st.stop()

cases = {case["id"]: case for case in dataset["cases"]}
if dataset["kind"] == "illustrative":
    st.info("Illustrative dataset · Prompts and candidate responses are authored examples. Scores entered here are demonstration results and do not measure real model performance.")
else:
    st.caption(f"User-provided evaluation dataset · {dataset['id']}")
page = st.sidebar.radio("Workspace", ["Compare & score", "QA review", "Dashboard", "Rubric"], key="workspace")
st.sidebar.caption(f"Dataset: {dataset['id']} · Rubric v{VERSION}")


def display_case(case):
    st.subheader("Prompt")
    st.text(case["prompt"])
    with st.expander("Reference and evaluator guidance"):
        st.text(case["reference"])
    for candidate, column in zip(("A", "B"), st.columns(2)):
        with column:
            st.subheader(f"Response {candidate}")
            st.text(case["responses"][candidate])


if page == "Compare & score":
    category = st.selectbox("Category", sorted({c["category"] for c in cases.values()}))
    case_id = st.selectbox("Case", [key for key, case in cases.items() if case["category"] == category])
    display_case(cases[case_id])
    candidate = st.radio("Response to score", ("A", "B"), horizontal=True, key="candidate")
    with st.expander("Rating anchors"):
        for name, (_, low, mid, high) in RUBRIC.items():
            st.write(f"**{name}** · 1: {low} · 3: {mid} · 5: {high}")
        st.caption("Use 2 or 4 when performance falls between adjacent anchors.")
    with st.form(f"score-{case_id}-{candidate}", clear_on_submit=True):
        reviewer = st.text_input("Reviewer ID")
        scores = {name: st.selectbox(name, range(1, 6), index=None, placeholder="Choose a rating")
                  for name in RUBRIC}
        rationale = st.text_area("Rationale", help="Cite specific evidence from the response.")
        if st.form_submit_button("Submit for QA"):
            try:
                store.submit(case_id, candidate, reviewer, scores, rationale)
                st.success("Review submitted for QA.")
            except sqlite3.IntegrityError:
                st.error("That reviewer ID already scored this response.")
            except ValueError as exc:
                st.error(str(exc))

elif page == "QA review":
    history = [row for row in store.rows() if row["case_id"] in cases]
    status = st.selectbox("Review status", ["Pending", "Approved", "Needs revision"])
    matching = {r["id"]: r for r in history if (r["decision"] or "Pending") == status}
    if not matching:
        st.info(f"No reviews with status {status.lower()}.")
    else:
        review_id = st.selectbox("Review", list(matching), format_func=lambda key:
                                 f"#{key} · {matching[key]['case_id']} · Response {matching[key]['candidate']}")
        item = matching[review_id]
        display_case(cases[item["case_id"]])
        st.write(f"Reviewer **{item['reviewer']}** · Weighted score **{item['score']:.2f}/100**")
        st.json(json.loads(item["scores"]), expanded=True)
        st.text(item["rationale"])
        if status == "Pending":
            with st.form(f"qa-{review_id}"):
                reviewer = st.text_input("QA reviewer ID")
                decision = st.selectbox("Decision", ["Approved", "Needs revision"], index=None)
                note = st.text_area("QA note", help="Check ratings against the anchors and rationale against the evidence.")
                if st.form_submit_button("Save decision"):
                    try:
                        store.review(review_id, reviewer, decision, note)
                        st.session_state["qa_saved"] = True
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("A QA decision already exists. Refresh the queue.")
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.caption(f"QA by {item['qa_reviewer']} · {item['qa_at']} UTC")
            st.text(item["note"])
            if status == "Needs revision":
                st.caption("To submit a revision, score this response again using the original reviewer ID.")
    if st.session_state.pop("qa_saved", False):
        st.success("QA decision saved.")

elif page == "Dashboard":
    scope = st.selectbox("Category filter", [None, *sorted({c["category"] for c in cases.values()})],
                         format_func=lambda value: value or "All categories")
    allowed = {key for key, case in cases.items() if scope is None or case["category"] == scope}
    rows = [row for row in store.rows() if row["case_id"] in allowed]
    pairs = benchmark(rows, allowed)
    cols = st.columns(4)
    cols[0].metric("Reviews", len(rows))
    cols[1].metric("Pending QA", sum(row["decision"] is None for row in rows))
    cols[2].metric("QA approved", sum(row["decision"] == "Approved" for row in rows))
    cols[3].metric("Paired case coverage", f"{len(pairs)} / {len(allowed)}")
    st.caption("Only cases with QA-approved scores for both responses enter the benchmark. Reviews are averaged within each case and candidate, then cases receive equal weight.")
    if pairs:
        wins_a = sum(pair["A"] > pair["B"] for pair in pairs)
        wins_b = sum(pair["B"] > pair["A"] for pair in pairs)
        st.write(f"Case wins · A: {wins_a} · B: {wins_b} · Ties: {len(pairs) - wins_a - wins_b}")
        for candidate, column in zip(("A", "B"), st.columns(2)):
            column.metric(f"Response {candidate} mean", f"{mean(p[candidate] for p in pairs):.2f} / 100")
        st.bar_chart(pairs, x="Case", y=["A", "B"], stack=False, y_label="Approved score (0–100)")
        st.dataframe(pairs, hide_index=True)
    else:
        st.info("Approve at least one score for each response on the same case to see a benchmark.")
    if rows:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["dataset_kind", *rows[0]])
        writer.writeheader()
        for row in rows:
            # Avoid formula execution when free-text fields are opened in a spreadsheet.
            safe_row = {k: "'" + v if isinstance(v, str) and (v.startswith(("\t", "\r", "\n"))
                        or v.lstrip().startswith(("=", "+", "-", "@"))) else v for k, v in row.items()}
            writer.writerow({"dataset_kind": dataset["kind"], **safe_row})
        st.download_button("Export filtered reviews (CSV)", buffer.getvalue(), "reviews.csv", "text/csv")

else:
    st.subheader(f"Human scoring rubric · v{VERSION}")
    st.dataframe([
        {"Criterion": key, "Weight": f"{weight:.0%}", "1": low, "3": mid, "5": high}
        for key, (weight, low, mid, high) in RUBRIC.items()
    ], hide_index=True)
    st.write("Use 2 or 4 between adjacent anchors. Score each response independently and support the ratings with concrete evidence.")
    st.code("Total (0–100) = Σ weight × (rating − 1) × 25", language=None)
    st.write("QA checks evidence and rubric application. A different reviewer ID records an approval or requests revision. Approval makes the score eligible for the benchmark.")

