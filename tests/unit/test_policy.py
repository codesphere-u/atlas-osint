from shared.policy import PolicyReport, apply_privacy_policy, scrub_text
from shared.types import Finding, Identifier, IdentifierType, LinkedIdentifier, Reliability, SourceCategory, SubjectKind


def make(**kw):
    base = dict(
        module="username",
        source_name="t",
        source_display_name="T",
        source_url="https://t.example/",
        source_category=SourceCategory.USERNAME,
        reliability=Reliability.B,
        finding_type="account_profile",
        title="t",
        description="d",
        subject=Identifier(type=IdentifierType.USERNAME, value="octo"),
    )
    base.update(kw)
    return Finding(**base)


def test_individual_forbidden_attributes_removed():
    f = make(
        attributes={
            "location": "Home Street 1",
            "home_address": "x",
            "date_of_birth": "1990-01-01",
            "religion": "x",
            "language": "en",
            "display_name": "Octo",
            "password": "hunter2",
            "homepage": "https://x.example",
        }
    )
    [out], report = apply_privacy_policy([f], SubjectKind.INDIVIDUAL)
    assert set(out.attributes) == {"language", "display_name", "homepage"}
    assert report.attributes_removed["password"] == 1


def test_organization_keeps_registered_address_but_never_credentials():
    f = make(attributes={"registered_address": "1 Corp Way", "api_key": "abc", "registered_city": "X"})
    [out], _ = apply_privacy_policy([f], SubjectKind.ORGANIZATION)
    assert "registered_address" in out.attributes and "api_key" not in out.attributes


def test_excerpt_scrubbing_for_individuals():
    report = PolicyReport()
    text = scrub_text(
        "Call +1 415 555 0199, card 4111 1111 1111 1111, lives at 12 Baker Street. Year 2019.",
        keep=set(),
        report=report,
    )
    assert "415 555" not in text and "4111" not in text and "Baker Street" not in text
    assert "2019" in text
    assert report.redactions["phone_number"] == 1 and report.redactions["payment_card"] == 1


def test_subject_phone_is_preserved():
    f = make(subject=Identifier(type=IdentifierType.PHONE, value="+14155550199"), description="Listed: +1 415 555 0199")
    [out], _ = apply_privacy_policy([f], SubjectKind.INDIVIDUAL)
    assert "+1 415 555 0199" in out.description


def test_linked_phone_numbers_dropped_for_individuals():
    f = make(
        linked=[
            LinkedIdentifier(
                identifier=Identifier(type=IdentifierType.PHONE, value="+14155550100"), relation="lists_phone"
            )
        ]
    )
    [out], report = apply_privacy_policy([f], SubjectKind.INDIVIDUAL)
    assert out.linked == [] and report.attributes_removed["linked_phone"] == 1


def test_forbidden_finding_types_dropped():
    f = make(finding_type="residential_address")
    out, report = apply_privacy_policy([f], SubjectKind.INDIVIDUAL)
    assert out == [] and report.findings_dropped["residential_address"] == 1
