from shared.types import (
    EvidenceKind,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
)


def finding(
    source="src",
    *,
    subject=("username", "octo"),
    ftype="account_profile",
    hint=None,
    kind=None,
    claim=None,
    reliability=Reliability.B,
    match=MatchType.EXACT,
    evidence=EvidenceKind.DIRECT,
    attrs=None,
    linked=None,
    title="t",
    description="d",
    flags=None,
    module="username",
    **kw,
) -> Finding:
    return Finding(
        module=module,
        source_name=source,
        source_display_name=source.title(),
        source_url=f"https://{source}.example/",
        source_category=SourceCategory.USERNAME,
        reliability=reliability,
        finding_type=ftype,
        title=title,
        description=description,
        subject=Identifier(type=IdentifierType(subject[0]), value=subject[1]),
        match_type=match,
        evidence_kind=evidence,
        attributes=attrs or {},
        linked=[
            LinkedIdentifier(identifier=Identifier(type=IdentifierType(t), value=v), relation=r)
            for t, v, r in (linked or [])
        ],
        entity_hint=hint,
        entity_kind=kind,
        claim_key=claim,
        flags=flags or [],
        **kw,
    )
