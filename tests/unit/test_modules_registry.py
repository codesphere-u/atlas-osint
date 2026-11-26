import importlib.metadata

import pytest

from integrations.sources.base import SourceAdapter, SourceMetadata
from integrations.sources.registry import SourceRegistry, build_default_registry
from modules.email.module import EmailModule
from modules.name.module import NameModule
from modules.phone.module import PhoneModule
from modules.username.module import UsernameModule, username_variants
from shared.types import Identifier, IdentifierType, MatchType
from tests.unit.helpers import finding


def test_every_builtin_adapter_declares_complete_metadata():
    reg = build_default_registry(load_plugins=False)
    assert len(reg.names()) >= 30
    for a in reg.all():
        m = a.meta
        assert m.name and m.display_name and m.description and m.homepage.startswith(("http", "dns"))
        assert m.input_types and m.fields and m.freshness and m.legal.restrictions
        assert m.rate_limit.per_seconds > 0
        assert "{url}" in m.citation_format or "{title}" in m.citation_format
        if m.auth.required:
            assert m.auth.settings_fields


def test_duplicate_adapter_rejected():
    reg = build_default_registry(load_plugins=False)
    with pytest.raises(ValueError):
        reg.register(reg.all()[0].__class__())


def test_entry_point_plugins_are_loaded(monkeypatch):
    class PluginAdapter(SourceAdapter):
        meta = build_default_registry(load_plugins=False).get("github").meta.model_copy(update={"name": "plugin_x"})

        async def collect(self, identifier, ctx):
            return []

    class EP:
        name = "plugin_x"

        def load(self):
            return PluginAdapter

    class BrokenEP:
        name = "broken"

        def load(self):
            raise ImportError("nope")

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda group: [EP(), BrokenEP()])
    reg = SourceRegistry()
    assert reg.load_entry_points() == 1 and reg.get("plugin_x") is not None
    assert isinstance(PluginAdapter.meta, SourceMetadata)


def test_username_variants():
    assert username_variants("john_doe") == ["johndoe", "john.doe", "john-doe"]
    assert username_variants("johndoe") == []


def test_username_plan_marks_variants_similar():
    reg = build_default_registry(load_plugins=False)
    tasks = UsernameModule().plan(
        Identifier(type=IdentifierType.USERNAME, value="john_doe"), reg, set(reg.names()), {"include_variants": True}
    )
    assert len(tasks) == 4
    assert all(t.match_override == MatchType.SIMILAR for t in tasks[1:])


def test_email_module_pivots_only_for_organisational_domains():
    reg = build_default_registry(load_plugins=False)
    m = EmailModule()
    org = m.plan(Identifier(type=IdentifierType.EMAIL, value="a@acme.org"), reg, set(reg.names()), {})
    free = m.plan(Identifier(type=IdentifierType.EMAIL, value="a@gmail.com"), reg, set(reg.names()), {})
    assert len(org) == 2 and {a.meta.name for a in org[1].adapters} <= {"rdap_domain", "dns_records", "wayback"}
    assert len(free) == 1


def test_phone_module_strips_subscriber_identity():
    f = finding(subject=("phone", "+14155550199"), attrs={"subscriber_name": "John", "phone_region": "US"})
    [out] = PhoneModule().postprocess([f], f.subject)
    assert "subscriber_name" not in out.attributes and "subscriber_identity_removed" in out.flags


def test_name_module_flags_collisions():
    subj = ("name", "Maria Example")
    fs = [
        finding("a", subject=subj, hint="person:x:1", kind="person", attrs={"candidate_name": "Maria Example"}),
        finding("b", subject=subj, hint="person:x:2", kind="person", attrs={"candidate_name": "María Example"}),
    ]
    out = NameModule().postprocess(fs, fs[0].subject)
    assert all("name_collision" in f.flags for f in out)
