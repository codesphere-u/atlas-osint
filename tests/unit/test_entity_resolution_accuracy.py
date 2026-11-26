"""Entity-resolution accuracy on the labelled synthetic dataset.

Design goal: **zero false merges** (precision 1.0 / FP rate 0) – ATLAS prefers to miss a link (false
negative, surfaced as a possible match for analyst review) over wrongly merging two people. Recall is
measured and recorded, not asserted to a marketing number; it is limited by design because records
without a shared persistent identifier are never merged.
"""

import json

from scripts.evaluate_entity_resolution import evaluate
from tests.conftest import FIXTURES


def test_no_false_merges_and_recall_is_measured():
    data = json.loads((FIXTURES / "er_synthetic.json").read_text())
    result = evaluate(data["records"])
    overall = result["overall"]
    assert overall["fp"] == 0 and overall["precision"] == 1.0
    assert overall["false_positive_rate"] == 0.0
    assert 0 < overall["recall"] < 1  # some true links have no shared identifier -> expected false negatives
    assert result["by_kind"]["person"]["name_collisions_flagged"] > 0
