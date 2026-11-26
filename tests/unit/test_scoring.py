from engine.correlation.resolver import resolve
from engine.verification.scoring import classify, score_findings
from shared.types import ConfidenceLevel, EvidenceKind, MatchType, Reliability, VerificationStatus
from tests.unit.helpers import finding


def rules(f):
    return [r.rule for r in f.confidence.reasons]


def test_base_score_from_reliability():
    [f] = score_findings([finding(reliability=Reliability.A)])
    assert f.confidence.score == 0.9 and f.confidence.level == ConfidenceLevel.HIGH
    assert classify(f) == "confirmed"


def test_similar_match_penalty_and_explanation():
    [f] = score_findings([finding(match=MatchType.SIMILAR)])
    assert f.confidence.score == 0.5
    assert "match_similar" in rules(f)
    assert classify(f) == "possible"


def test_inference_penalty():
    [f] = score_findings([finding(evidence=EvidenceKind.INFERENCE)])
    assert round(f.confidence.score, 2) == 0.65 and classify(f) == "possible"


def test_corroboration_by_independent_sources():
    fs = score_findings(
        [finding("a", claim="c1", reliability=Reliability.C), finding("b", claim="c1"), finding("c", claim="c1")]
    )
    assert fs[0].confidence.score == round(0.65 + 0.14, 4)
    assert fs[0].verification_status == VerificationStatus.CORROBORATED
    # same source repeated is NOT independent corroboration
    fs = score_findings([finding("a", claim="c2"), finding("a", claim="c2")])
    assert "corroboration" not in rules(fs[0])


def test_name_only_person_is_capped():
    [f] = score_findings([finding(subject=("name", "Maria Example"), kind="person", reliability=Reliability.A)])
    assert f.confidence.score == 0.5 and "name_only_cap" in rules(f)
    assert classify(f) == "possible"


def test_news_and_variant_caps():
    [n] = score_findings([finding(ftype="news_mention", reliability=Reliability.A)])
    assert n.confidence.score == 0.35 and classify(n) == "unverified"
    [v] = score_findings([finding(flags=["variant_query"])])
    assert v.confidence.score == 0.4


def test_analyst_decisions_override():
    a = finding(verification_status=VerificationStatus.VERIFIED, match=MatchType.SIMILAR)
    r = finding(verification_status=VerificationStatus.REJECTED)
    a, r = score_findings([a, r])
    assert a.confidence.score == 0.95 and classify(a) == "confirmed"
    assert r.confidence.score == 0.0 and classify(r) == "rejected"


def test_contradiction_penalty_and_disputed_status():
    f1 = finding("rdap", hint="domain:x.com", kind="domain", attrs={"registrar": "Registrar One"}, claim="k1")
    f2 = finding("other", hint="domain:x.com", kind="domain", attrs={"registrar": "Registrar Two"}, claim="k2")
    corr = resolve([f1, f2], f1.subject)
    assert len(corr.contradictions) == 1
    f1, f2 = score_findings([f1, f2], corr)
    assert "contradiction" in rules(f1) and f1.verification_status == VerificationStatus.DISPUTED
    assert classify(f1) != "confirmed"


def test_scores_are_bounded_and_every_score_is_explained():
    fs = score_findings([finding(str(i), claim="same", reliability=Reliability.A) for i in range(10)])
    for f in fs:
        assert 0.0 <= f.confidence.score <= 1.0
        assert round(sum(r.delta for r in f.confidence.reasons), 4) == f.confidence.score
