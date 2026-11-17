# AI Response Evaluation & Benchmarking System

A local Streamlit workspace for comparing two AI responses, collecting human ratings, and reviewing those ratings before they enter a paired benchmark. It uses Python 3.12 and SQLite and requires no model API or API key.

## Run locally

From the extracted repository folder, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

On macOS or Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`. Open the local URL printed by Streamlit.

## Try the full workflow

1. Open **Compare & score**. Select **Reasoning** and **arithmetic**. Read the prompt, reference, and both candidate responses.
2. Select **A** and score all five criteria. Use `reviewer-01` and cite the equation in the rationale. Submit the review.
3. Repeat for **B** with the same reviewer ID and cite its incorrect reversal of the discount.
4. Open **QA review**. Inspect each pending review and record a decision and note with a different ID, such as `qa-01`. Approval means the rating is justified, even if it is a low rating. For **Needs revision**, score that response again under the original reviewer ID. The previous attempt and its QA decision remain in the history.
5. Open **Dashboard**. With both scores approved, coverage will show one paired case. Filter by category or export the full filtered review history to CSV.

## Scoring and analytics

| Criterion | Weight |
| --- | ---: |
| Correctness | 35% |
| Instruction adherence | 25% |
| Relevance and completeness | 15% |
| Safety | 15% |
| Clarity | 10% |

The Rubric screen displays behavioral anchors for ratings 1, 3, and 5. Use 2 and 4 for intermediate judgments. The total is the sum of each criterion's weight multiplied by 25 × (rating − 1). For example, ratings of 5, 4, 3, 5, 4 in table order produce 83.75/100.

The dashboard averages QA-approved reviews per case and candidate, then averages across cases with an approved score for **both** candidates. Each paired case receives equal weight. The case wins and ties use the two per-case means. Pending and revision-requested scores appear in review history and are excluded from benchmark calculations. The dashboard reports paired coverage so readers can see how much of the dataset the means represent. This descriptive comparison does not estimate statistical uncertainty or establish a general model ranking.

## Data and storage

`data/sample.json` contains eight authored prompts and answer pairs. The sample is marked **illustrative** in the app and CSV export. The repository ships with an empty review history, and neither the sample answers nor the test scores are real model evaluation results.

To use real outputs, copy the sample structure into a new JSON file and set `BENCHMARK_DATASET` to its path before launching. Set `kind` to `real` for genuine collected outputs. Use a unique dataset ID for each version and keep the same model-to-candidate mapping across cases. Record the model versions, generation settings, prompt set, and collection conditions alongside your dataset so results can be interpreted and repeated.

SQLite defaults to `reviews.sqlite3` beside the app. Set `BENCHMARK_DB` to use a different file. Records are scoped by dataset ID and rubric version. For this local workflow, typed reviewer IDs provide attribution and prevent the same ID from approving its own review. They are not authenticated accounts.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover scoring validation, reviewer and QA rules, resubmission history, dataset isolation, paired aggregation, and the Streamlit workflow from scoring through dashboard display. GitHub Actions runs the same suite.


## Portfolio study

Five matched prompts yielded ten collected ChatGPT and Gemini responses across coding, instruction following, and summarization. Multiple reviewers contributed ratings. The review export contained 18 approved ratings and full paired coverage (5/5). Equal-weighted case means were 99.00/100 for ChatGPT and 95.63/100 for Gemini. ChatGPT scored higher on four cases and Gemini scored higher on one. These are descriptive results for the five prompts.

To inspect the collected responses in the app, set `BENCHMARK_DATASET` to `data/chatgpt-gemini.json` before launching Streamlit.
