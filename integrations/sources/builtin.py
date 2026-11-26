"""Built-in source adapters shipped with ATLAS OSINT."""

from collections.abc import Callable

from integrations.sources.base import SourceAdapter
from integrations.sources.domain import DOMAIN_ADAPTERS
from integrations.sources.email import EmailDomainDnsAdapter, EmailSyntaxAdapter, HibpAdapter
from integrations.sources.name import OpenAlexAuthorsAdapter, OrcidAdapter, WikidataAdapter
from integrations.sources.phone import LibPhoneNumberAdapter, NumverifyAdapter
from integrations.sources.public_records import PUBLIC_RECORD_ADAPTERS
from integrations.sources.username import USERNAME_ADAPTERS

BUILTIN_ADAPTERS: list[Callable[[], SourceAdapter]] = [
    LibPhoneNumberAdapter,
    NumverifyAdapter,
    *USERNAME_ADAPTERS,
    OpenAlexAuthorsAdapter,
    OrcidAdapter,
    WikidataAdapter,
    EmailSyntaxAdapter,
    EmailDomainDnsAdapter,
    HibpAdapter,
    *DOMAIN_ADAPTERS,
    *PUBLIC_RECORD_ADAPTERS,
]
