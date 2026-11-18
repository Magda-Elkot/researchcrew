"""ResearchCrew's single Streamlit page: ask a question, watch the agents work, read the report.

Run: `make frontend` (the API must be running, see API_URL). Not named `app.py`: Streamlit puts
this folder first on `sys.path`, and `import app` would then find this page, not our package.

Streamlit reruns this script on every interaction; the current job id lives in
`st.session_state`. Report text comes from models and web pages, so it is shown with
Streamlit's Markdown, which escapes raw HTML; Arabic is set right-to-left with CSS on a keyed
container, not with HTML inside the report (DECISIONS #89).
"""

from typing import Any

import httpx
import streamlit as st

from app.log import get_logger
from frontend.client import FINAL_EVENTS, ApiClient, FrontendSettings

logger = get_logger(__name__)

ICONS = {
    "agent_started": "▶",
    "tool_called": "🔧",
    "tool_failed": "⚠",
    "agent_finished": "✓",
    "revision_requested": "↺",
    "job_completed": "✅",
    "job_failed": "❌",
}
# Our own static CSS (the only HTML this page renders). Streamlit gives a container with
# key="x" the class "st-key-x".
RTL_CSS = """<style>
.st-key-report-rtl { direction: rtl; text-align: right; }
.st-key-report-rtl ol, .st-key-report-rtl ul { padding-right: 1.5em; padding-left: 0; }
</style>"""


@st.cache_resource
def api() -> ApiClient:
    return ApiClient(FrontendSettings().api_url)


def event_line(event: dict[str, Any]) -> str:
    agent = f"{event['agent']}: " if event.get("agent") else ""
    return f"{ICONS.get(event['type'], '•')} {agent}{event['message']}"


def show_progress(job_id: str, finished: bool) -> None:
    """The progress feed; live while the job runs, a collapsed replay afterwards."""
    label = "Agents' progress" if finished else "Researching… (a quick report takes ~5-10 min)"
    with st.status(
        label, expanded=not finished, state="complete" if finished else "running"
    ) as box:
        for event in api().follow(job_id):
            st.text(event_line(event))
            if event["type"] in FINAL_EVENTS:
                ok = event["type"] == "job_completed"
                box.update(label="Agents' progress", state="complete" if ok else "error")


def show_result(job: dict[str, Any]) -> None:
    if job["status"] == "failed":
        st.error(job.get("error") or "The research run failed.")
        return
    report = job.get("report")
    if not report or not job.get("report_markdown"):
        st.warning("The job finished without a report.")
        return
    usage = job["token_usage"]
    cols = st.columns(4)
    cols[0].metric("Citations", len(job["citations"]))
    cols[1].metric("Tokens", f"{usage['total_tokens']:,}")
    cols[2].metric("Cost", f"${job['cost_usd']:.4f}")
    cols[3].metric("Time", f"{job['latency_s'] or 0:.0f} s")
    rtl = report["language"] == "ar"
    with st.container(key="report-rtl" if rtl else "report", border=True):
        st.markdown(job["report_markdown"])  # raw HTML stays escaped
    st.download_button(
        "Download Markdown",
        job["report_markdown"],
        file_name=f"report-{job['job_id']}.md",
        mime="text/markdown",
    )


def main() -> None:
    st.set_page_config(page_title="ResearchCrew", page_icon="🔎")
    st.markdown(RTL_CSS, unsafe_allow_html=True)
    st.title("ResearchCrew")
    st.caption("A crew of five AI agents researches your question and writes a cited report.")

    with st.form("ask"):
        question = st.text_area("Research question (English or Arabic)", max_chars=2000, height=100)
        depth = st.radio("Depth", ["quick", "deep"], horizontal=True)
        submitted = st.form_submit_button("Research", type="primary")
    if submitted:
        if not question.strip():
            st.warning("Please enter a question.")
        else:
            try:
                st.session_state["job_id"] = api().start(question, depth or "quick")
            except httpx.HTTPError as exc:
                logger.warning("could not start a job", extra={"error": str(exc)})
                st.error(f"Could not reach the API at {FrontendSettings().api_url}: {exc}")

    job_id = st.session_state.get("job_id")
    if not job_id:
        return
    try:
        job = api().job(job_id)
        st.caption(f"Job `{job_id}` · {job['depth']} · {job['question']}")
        show_progress(job_id, finished=job["status"] in ("completed", "failed"))
        show_result(api().job(job_id))
    except httpx.HTTPError as exc:
        logger.warning("api request failed", extra={"job_id": job_id, "error": str(exc)})
        st.error(f"Lost contact with the API: {exc}")


main()
