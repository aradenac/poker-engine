#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAIRS = (
    ("src/analytics/leak-training-target.js", "site/analytics/leak-training-target.js"),
    ("src/analytics/review-dashboard.js", "site/analytics/review-dashboard.js"),
)

def main() -> None:
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, (source, runtime)

    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    target_pos = index.index('<script src="./analytics/leak-training-target.js"></script>')
    dashboard_pos = index.index('<script src="./analytics/review-dashboard.js"></script>')
    assert target_pos < dashboard_pos

    assert 'Dashboard.buildReviewDashboard' in index
    assert 'function reviewDashboardSourceScores()' in index
    assert 'if(score&&score.signature===sig)out[id]=score;' in index
    assert 'complete:false,analyzableDecisions:0' not in index[index.index('function reviewDashboardSourceScores()'):index.index('function reviewDashboardBuild()')]
    assert 'Leak.analyzeLeaks' not in index
    assert 'PokerReviewDashboard' in index
    assert 'NO_HANDS' in index
    assert 'ANALYSIS_PENDING' in index
    assert 'ANALYSIS_INCOMPLETE' in index
    assert 'NO_SIGNIFICANT_LOSS' in index
    assert 'READY' in index

    assert 'return openReviewInboxDeepLink(cta.target);' in index
    assert 'target.dimension!=="spot_family"' in index
    assert 'UNSUPPORTED_LEAK_DIMENSION' in index
    assert 'String(target.scope_key)!==String(model.scope_key)' in index
    assert 'reviewDashboardTrainingBtn.hidden=!trainingEnabled' in index
    assert 'if(!cta?.enabled||!cta.target)' in index
    assert 'trainerOpenBtn?.click();' in index

    # Dashboard and inbox consume the same population-bound Review scope derived
    # from the Hero strategy resolver, never a hard-coded "Custom" identity.
    assert 'scope:reviewInboxScopeInput()' in index
    assert 'reviewScopeFromResolution' in index
    assert 'UNAVAILABLE_STRATEGY' in index
    assert 'hero-custom' not in index

    # The generic one-click destinations remain independent from gated dashboard CTAs.
    home = index.split('<div class="actions product-home-actions"', 1)[1].split('</div>', 1)[0]
    for label in ("Review", "Training", "Strategy", "Equity Lab"):
        assert label in home, (label, home)

    print("review dashboard UI contract checks: OK")

if __name__ == "__main__":
    main()
