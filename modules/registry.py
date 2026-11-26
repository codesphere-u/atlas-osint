from __future__ import annotations

from modules.base import IntelligenceModule
from modules.domain.module import DomainModule
from modules.email.module import EmailModule
from modules.name.module import NameModule
from modules.phone.module import PhoneModule
from modules.public_records.module import PublicRecordsModule
from modules.username.module import UsernameModule
from shared.types import IdentifierType

MODULES: list[IntelligenceModule] = [
    PhoneModule(),
    UsernameModule(),
    NameModule(),
    EmailModule(),
    DomainModule(),
    PublicRecordsModule(),
]
_BY_TYPE = {t: m for m in MODULES for t in m.input_types}
_BY_NAME = {m.name: m for m in MODULES}


def module_for(identifier_type: IdentifierType) -> IntelligenceModule:
    return _BY_TYPE[identifier_type]


def module_by_name(name: str) -> IntelligenceModule | None:
    return _BY_NAME.get(name)
