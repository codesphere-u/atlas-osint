"""Phone number sources.

``libphonenumber`` provides numbering-plan intelligence offline: validity,
region, number type and – where the numbering plan allocates ranges to a
specific operator – the *original* carrier the range was assigned to. It
never identifies a subscriber, and number portability means the original
carrier may not be the current one; findings say so explicitly.
"""

from __future__ import annotations

import phonenumbers
from phonenumbers import PhoneNumberType, carrier, geocoder, timezone

from integrations.sources.base import (
    AuthRequirement,
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
)
from shared.types import (
    AccessMethod,
    AdapterStatus,
    Finding,
    Identifier,
    IdentifierType,
    Reliability,
    SourceCategory,
)

_TYPE_NAMES = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


class LibPhoneNumberAdapter(SourceAdapter):
    meta = SourceMetadata(
        name="libphonenumber",
        display_name="Google libphonenumber numbering-plan metadata",
        description="Offline E.164 validation, numbering-plan region, line type, time zones and "
        "range-allocated carrier from ITU/regulator numbering plans.",
        category=SourceCategory.PHONE,
        input_types=[IdentifierType.PHONE],
        access_method=AccessMethod.OFFLINE_DATASET,
        homepage="https://github.com/google/libphonenumber",
        rate_limit=RateLimit(requests=0, per_seconds=1, notes="offline"),
        legal=LegalInfo(
            license="Apache-2.0",
            terms_url="https://github.com/google/libphonenumber/blob/master/LICENSE",
            restrictions="Numbering-plan metadata only. Carrier = operator the number range was "
            "originally allocated to; ported numbers are not reflected.",
        ),
        fields=[
            "phone_e164",
            "phone_international_format",
            "phone_national_format",
            "phone_country_code",
            "phone_region",
            "phone_description",
            "phone_valid",
            "phone_possible",
            "phone_line_type",
            "phone_carrier",
            "phone_timezones",
        ],
        freshness=f"static dataset (phonenumbers {phonenumbers.__version__})",
        reliability=Reliability.A,
        citation_format="{display_name} (phonenumbers "
        + phonenumbers.__version__
        + "). {title}. Retrieved {collected_at}.",
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        try:
            num = phonenumbers.parse(identifier.value, None)
        except phonenumbers.NumberParseException as exc:
            raise SourceError(AdapterStatus.ERROR, f"unparseable number: {exc}") from exc
        valid = phonenumbers.is_valid_number(num)
        region = phonenumbers.region_code_for_number(num)
        line_type = _TYPE_NAMES.get(phonenumbers.number_type(num), "unknown")
        carrier_name = carrier.name_for_number(num, "en") or None
        attrs = {
            "phone_e164": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164),
            "phone_international_format": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "phone_national_format": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL),
            "phone_country_code": num.country_code,
            "phone_region": region,
            # Region description is country-level or numbering-area level (never a subscriber location).
            "phone_description": geocoder.country_name_for_number(num, "en") or None,
            "phone_valid": valid,
            "phone_possible": phonenumbers.is_possible_number(num),
            "phone_line_type": line_type,
            "phone_carrier": carrier_name,
            "phone_timezones": list(timezone.time_zones_for_number(num)),
        }
        desc = (
            f"{attrs['phone_international_format']} is {'a valid' if valid else 'NOT a valid'} number in the "
            f"{region or 'unknown'} numbering plan; line type: {line_type}."
        )
        if carrier_name:
            desc += (
                f" The number range was originally allocated to {carrier_name}; due to number portability "
                "this may not be the current operator."
            )
        desc += " Numbering-plan data does not identify the subscriber."
        url = f"https://github.com/google/libphonenumber#{region or 'unknown'}"
        findings = [
            self.finding(
                module="phone",
                subject=identifier,
                finding_type="phone_numbering_plan",
                title=f"Numbering-plan analysis of {attrs['phone_e164']}",
                description=desc,
                url=url,
                attributes=attrs,
                excerpt=f"region={region}; type={line_type}; valid={valid}",
                entity_hint=f"phone:{attrs['phone_e164']}",
                entity_kind="phone",
                claim_key=f"phone.valid:{attrs['phone_e164']}={valid}",
            )
        ]
        if region:
            findings.append(
                self.finding(
                    module="phone",
                    subject=identifier,
                    finding_type="phone_region",
                    title=f"Numbering-plan region: {region}",
                    description=f"The country calling code +{num.country_code} and prefix place this number "
                    f"in the {attrs['phone_description'] or region} numbering plan.",
                    url=url,
                    attributes={"phone_region": region, "phone_country_code": num.country_code},
                    entity_hint=f"phone:{attrs['phone_e164']}",
                    entity_kind="phone",
                    claim_key=f"phone.region:{attrs['phone_e164']}={region}",
                )
            )
        return findings


class NumverifyAdapter(SourceAdapter):
    """Commercial line-type/carrier verification (apilayer numverify). Optional, requires a key."""

    meta = SourceMetadata(
        name="numverify",
        display_name="numverify (apilayer) phone validation API",
        description="Licensed phone validation API returning validity, line type and carrier.",
        category=SourceCategory.PHONE,
        input_types=[IdentifierType.PHONE],
        access_method=AccessMethod.LICENSED_API,
        homepage="https://numverify.com/",
        auth=AuthRequirement(
            required=True,
            kind="api_key",
            settings_fields=["numverify_api_key"],
            how_to_obtain="Create an apilayer account and subscribe to numverify.",
        ),
        rate_limit=RateLimit(requests=1, per_seconds=1, notes="plan dependent"),
        legal=LegalInfo(
            terms_url="https://apilayer.com/terms",
            license="commercial",
            restrictions="Use under the apilayer terms of service; results may not be redistributed in bulk.",
        ),
        fields=["phone_e164", "phone_valid", "phone_line_type", "phone_carrier", "phone_region"],
        freshness="real-time (provider)",
        reliability=Reliability.C,
        default_enabled=False,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        key = ctx.secret("numverify_api_key")
        # numverify's free tier is HTTP-only; we require the HTTPS endpoint (paid plans).
        resp = await self.fetch(
            ctx,
            "https://apilayer.net/api/validate",
            params={"access_key": key, "number": identifier.value.lstrip("+")},
        )
        data = resp.json()
        if not isinstance(data, dict) or data.get("success") is False:
            raise SourceError(AdapterStatus.UNAVAILABLE, "provider returned an error")
        e164 = identifier.value
        attrs = {
            "phone_e164": e164,
            "phone_valid": data.get("valid"),
            "phone_line_type": data.get("line_type"),
            "phone_carrier": data.get("carrier") or None,
            "phone_region": data.get("country_code"),
        }
        return [
            self.finding(
                module="phone",
                subject=identifier,
                finding_type="phone_carrier_lookup",
                title=f"Carrier/line-type lookup for {e164}",
                description=f"Provider reports line type {attrs['phone_line_type'] or 'unknown'} and carrier "
                f"{attrs['phone_carrier'] or 'unknown'}. This does not identify the subscriber.",
                url="https://numverify.com/",
                attributes=attrs,
                raw=resp.content,
                entity_hint=f"phone:{e164}",
                entity_kind="phone",
                claim_key=f"phone.valid:{e164}={attrs['phone_valid']}",
            )
        ]
