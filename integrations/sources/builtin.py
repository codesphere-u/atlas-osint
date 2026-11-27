"""Built-in source adapters shipped with ATLAS OSINT."""

from collections.abc import Callable

from integrations.sources.base import SourceAdapter
from integrations.sources.domain import DOMAIN_ADAPTERS
from integrations.sources.email import EmailDomainDnsAdapter, EmailSyntaxAdapter, HibpAdapter
from integrations.sources.infrastructure import INFRASTRUCTURE_ADAPTERS
from integrations.sources.name import CrossrefWorksAdapter, OpenAlexAuthorsAdapter, OrcidAdapter, WikidataAdapter
from integrations.sources.phone import LibPhoneNumberAdapter, NumverifyAdapter
from integrations.sources.public_records import PUBLIC_RECORD_ADAPTERS
from integrations.sources.social import SOCIAL_ADAPTERS
from integrations.sources.username import USERNAME_ADAPTERS

BUILTIN_ADAPTERS: list[Callable[[], SourceAdapter]] = [
    LibPhoneNumberAdapter,
    NumverifyAdapter,
    *USERNAME_ADAPTERS,
    *SOCIAL_ADAPTERS,
    OpenAlexAuthorsAdapter,
    OrcidAdapter,
    WikidataAdapter,
    CrossrefWorksAdapter,
    EmailSyntaxAdapter,
    EmailDomainDnsAdapter,
    HibpAdapter,
    *DOMAIN_ADAPTERS,
    *INFRASTRUCTURE_ADAPTERS,
    *PUBLIC_RECORD_ADAPTERS,
]
