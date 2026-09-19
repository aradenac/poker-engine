#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    manual = (ROOT / "site/manual-import.js").read_text(encoding="utf-8")

    # The normal CENTRAL-UI no longer exposes the legacy independent JSON loaders.
    assert 'id="rangesSection" class="panel wide" hidden aria-hidden="true" data-legacy-import-surface="advanced-only"' in index
    assert 'id="fileInput"' in index
    assert 'id="populationModelInput"' in index
    assert 'id="postflopModelInput"' in index

    # Expert capability is preserved by navigation to the already-merged surface.
    assert 'id="advancedManualImportLink" href="./manual-import.html">Outils avancés / Import manuel</a>' in index
    assert 'id="centralManualImportLink" href="./manual-import.html">Outils avancés / Import manuel</a>' in index
    assert '<a href="./packs.html">Packs de population</a>' in index

    # Reuse the E-owned contracts in their required dependency order.
    identity = '<script src="./pack-identity.js"></script>'
    packs = '<script src="./population-packs.js"></script>'
    overrides = '<script src="./manual-import.js"></script>'
    assert index.index(identity) < index.index(packs) < index.index(overrides)
    assert "window.PokerManualOverrides" in manual
    assert 'RESTORE_ACTION="RESTORE_ACTIVE_PACK"' in manual

    # Central state is explicit and never presents an experimental override as promoted/default.
    assert "MANUAL_OVERRIDE / NON_STANDARD" in index
    assert 'contract.classification==="MANUAL_OVERRIDE"' in index
    assert 'contract.configuration_status==="NON_STANDARD"' in index
    assert 'contract.compatibility_status==="COMPATIBLE"' in index
    assert "non appliqué au runtime" in index
    assert "recommended" not in index[index.index("function refreshCentralManualOverrideState"):index.index("function centralRestoreActivePack")]

    # Historical local snapshots are consumed only through an active compatible override contract.
    assert "const manualOverrideAllowed=centralManualOverrideLoadAllowed(overrideContract);" in index
    assert "if(manualOverrideAllowed&&rangeSource?.content)" in index
    assert "if(manualOverrideAllowed&&populationModelSource?.content)" in index
    assert "if(manualOverrideAllowed&&postflopModelSource?.content)" in index

    # Restore delegates to the merged E contract; no copy of its mutation/import implementation.
    assert "const restored=await api.restoreActivePack();" in index
    assert "window.centralRestoreActivePack=centralRestoreActivePack;" in index
    assert "function restoreActivePack(" not in index
    assert "function activateFiles(" not in index
    assert 'localDbDelete("populationModelSource")' not in index[index.index("function centralRestoreActivePack"):index.index("const LOCAL_DB_NAME")]

    # Existing five-domain architecture remains unchanged; advanced import lives under Settings.
    quick = index[index.index('<nav id="quickNav"'):index.index('</nav>') + len('</nav>')]
    assert quick.count('data-product-domain=') == 5
    assert "manual-import.html" not in quick

    print("advanced manual import CENTRAL-UI contract checks: OK")


if __name__ == "__main__":
    main()
