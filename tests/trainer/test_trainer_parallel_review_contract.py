#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def require(needle: str) -> None:
    assert needle in HTML, f"missing parallel-review contract: {needle}"


require("function reviewBatchWorkerLimit(){")
require("if(!document.body.classList.contains('trainer-view-open'))return 1;")
require("return hc>=8?3:hc>=4?2:1;")
require("state.reviewBatchWorkers=[];")
require("while(active<limit&&pos<all.length)")
require("queueMicrotask(pump);")
require("__reviewOrder:order")
require("a.sizingResults.sort((x,y)=>Number(x.__reviewOrder||0)-Number(y.__reviewOrder||0))")
require("for(const z of a.sizingResults)delete z.__reviewOrder;")

# Non-trainer review/background behavior must remain sequential.
assert "trainer-view-open" in HTML and "return 1;" in HTML

# Old serialized loop must be gone from the patched function.
start = HTML.index("function runReviewBatchPlan(plan){")
end = HTML.index("function scheduleBackgroundReviewScoring(delay=120){", start)
block = HTML[start:end]
assert "const next=()=>" not in block

print("trainer parallel review contract: OK")
