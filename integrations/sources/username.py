"""Username / handle sources.

Each adapter queries the *official public API* of one platform for an account
with exactly the requested handle. Profile metadata is limited to the fields
declared in ``meta.fields``. Free-text fields (bios) are kept only as short
excerpts and are treated as untrusted content downstream.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from engine.normalization.identifiers import try_normalize
from integrations.sources.base import (
    AuthRequirement,
    CollectionContext,
    LegalInfo,
    RateLimit,
    SourceAdapter,
    SourceError,
    SourceMetadata,
    parse_datetime,
)
from shared.types import (
    AccessMethod,
    AdapterStatus,
    EvidenceKind,
    Finding,
    Identifier,
    IdentifierType,
    LinkedIdentifier,
    MatchType,
    Reliability,
    SourceCategory,
)

PROFILE_FIELDS = [
    "platform",
    "username",
    "display_name",
    "account_id",
    "profile_url",
    "website",
    "bio_excerpt",
    "organization",
    "created_at",
    "followers",
    "public_repos",
    "karma",
    "edit_count",
    "home_wiki",
    "packages",
    "linked_accounts",
    "proofs",
    "account_state",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None, limit: int = 280) -> str | None:
    if not text:
        return None
    clean = html.unescape(_TAG_RE.sub(" ", text))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit] or None


def _query_handle(identifier: Identifier, case_sensitive: bool) -> str:
    if case_sensitive and identifier.raw:
        return identifier.raw.strip().lstrip("@")
    return identifier.value


def website_links(url: str | None) -> list[LinkedIdentifier]:
    links: list[LinkedIdentifier] = []
    if not url:
        return links
    norm = try_normalize(IdentifierType.URL, url)
    if norm:
        links.append(LinkedIdentifier(identifier=norm, relation="lists_website"))
        host = re.sub(r"^https?://", "", norm.value).split("/", 1)[0].split(":", 1)[0]
        dom = try_normalize(IdentifierType.DOMAIN, host)
        if dom:
            links.append(LinkedIdentifier(identifier=dom, relation="lists_website_domain"))
    return links


def account_link(
    platform: str, handle: str | None, relation: str = "claims_account", kind: EvidenceKind = EvidenceKind.DIRECT
) -> list[LinkedIdentifier]:
    if not handle:
        return []
    norm = try_normalize(IdentifierType.USERNAME, handle)
    if not norm:
        return []
    return [
        LinkedIdentifier(
            identifier=Identifier(type=IdentifierType.USERNAME, value=f"{platform}:{norm.value}"),
            relation=relation,
            evidence_kind=kind,
        )
    ]


class _ProfileAdapter(SourceAdapter):
    platform: str = ""
    case_sensitive = False

    def _match_type(self, identifier: Identifier, returned: str) -> MatchType:
        if returned == _query_handle(identifier, self.case_sensitive):
            return MatchType.EXACT
        if returned.lower() == identifier.value.lower():
            return MatchType.EXACT if not self.case_sensitive else MatchType.SIMILAR
        return MatchType.SIMILAR

    def profile_finding(
        self,
        identifier: Identifier,
        *,
        handle: str,
        profile_url: str,
        attrs: dict[str, Any],
        linked: list[LinkedIdentifier],
        raw: bytes,
        bio: str | None,
        created: datetime | None,
    ) -> Finding:
        match = self._match_type(identifier, handle)
        attrs = {"platform": self.platform, "username": handle, "profile_url": profile_url, **attrs}
        if bio:
            attrs["bio_excerpt"] = bio
        title = f"{self.meta.display_name.split(' ')[0]} account '{handle}'"
        desc = f"A public {self.platform} account with the handle '{handle}' exists"
        desc += " (exact match)." if match == MatchType.EXACT else " (similar, not identical, handle)."
        desc += " An account with the same handle on a different platform is not necessarily the same person."
        return self.finding(
            module="username",
            subject=identifier,
            finding_type="account_profile",
            title=title,
            description=desc,
            url=profile_url,
            attributes=attrs,
            linked=linked,
            match_type=match,
            excerpt=bio,
            raw=raw,
            published_at=created,
            entity_hint=f"account:{self.platform}:{handle.lower()}",
            entity_kind="account",
            claim_key=f"account.exists:{self.platform}:{handle.lower()}",
        )


def _meta(
    name: str,
    display: str,
    homepage: str,
    terms: str,
    rl: RateLimit,
    reliability: Reliability = Reliability.B,
    auth: AuthRequirement | None = None,
    description: str | None = None,
    access: AccessMethod = AccessMethod.OFFICIAL_API,
) -> SourceMetadata:
    return SourceMetadata(
        name=name,
        display_name=display,
        description=description or f"Public profile lookup via the {display}.",
        category=SourceCategory.USERNAME,
        input_types=[IdentifierType.USERNAME],
        access_method=access,
        homepage=homepage,
        auth=auth or AuthRequirement(),
        rate_limit=rl,
        legal=LegalInfo(
            terms_url=terms,
            restrictions="Public profile metadata only; respect platform terms. No private data, no login.",
            contains_personal_data=True,
        ),
        fields=PROFILE_FIELDS,
        freshness="real-time",
        reliability=reliability,
    )


class GitHubAdapter(_ProfileAdapter):
    platform = "github"
    meta = _meta(
        "github",
        "GitHub REST API",
        "https://docs.github.com/en/rest/users/users",
        "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        RateLimit(requests=60, per_seconds=3600, notes="unauthenticated; 5000/h with ATLAS_GITHUB_TOKEN"),
        auth=AuthRequirement(
            required=False,
            optional=True,
            kind="bearer",
            settings_fields=["github_token"],
            how_to_obtain="Create a fine-grained token with no scopes.",
        ),
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = ctx.secret("github_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = await self.fetch(ctx, f"https://api.github.com/users/{quote(identifier.value)}", headers=headers)
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        if d.get("type") not in ("User", "Organization"):
            return []
        linked = website_links(d.get("blog")) + account_link("twitter", d.get("twitter_username"))
        return [
            self.profile_finding(
                identifier,
                handle=d["login"],
                profile_url=d.get("html_url") or f"https://github.com/{d['login']}",
                attrs={
                    "display_name": d.get("name"),
                    "account_id": str(d.get("id")),
                    "website": d.get("blog") or None,
                    "organization": d.get("company"),
                    "created_at": d.get("created_at"),
                    "followers": d.get("followers"),
                    "public_repos": d.get("public_repos"),
                    "account_state": d.get("type"),
                },
                linked=linked,
                raw=resp.content,
                bio=_strip_html(d.get("bio")),
                created=parse_datetime(d.get("created_at")),
            )
        ]


class GitLabAdapter(_ProfileAdapter):
    platform = "gitlab"
    meta = _meta(
        "gitlab",
        "GitLab.com Users API",
        "https://docs.gitlab.com/ee/api/users.html",
        "https://about.gitlab.com/terms/",
        RateLimit(requests=10, per_seconds=60),
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(ctx, "https://gitlab.com/api/v4/users", params={"username": identifier.value})
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        users = resp.json()
        if not users:
            return []
        u = users[0]
        detail: dict[str, Any] = {}
        raw = resp.content
        dresp = await self.fetch(ctx, f"https://gitlab.com/api/v4/users/{int(u['id'])}")
        if dresp.ok:
            detail = dresp.json()
            raw = dresp.content
        linked = website_links(detail.get("website_url")) + account_link("twitter", detail.get("twitter"))
        linked += account_link("github", detail.get("github"))
        return [
            self.profile_finding(
                identifier,
                handle=u["username"],
                profile_url=u.get("web_url") or f"https://gitlab.com/{u['username']}",
                attrs={
                    "display_name": u.get("name"),
                    "account_id": str(u.get("id")),
                    "website": detail.get("website_url") or None,
                    "organization": detail.get("organization") or None,
                    "created_at": detail.get("created_at"),
                    "account_state": u.get("state"),
                },
                linked=linked,
                raw=raw,
                bio=_strip_html(detail.get("bio")),
                created=parse_datetime(detail.get("created_at")),
            )
        ]


class HackerNewsAdapter(_ProfileAdapter):
    platform = "hackernews"
    case_sensitive = True
    meta = _meta(
        "hackernews",
        "Hacker News Firebase API",
        "https://github.com/HackerNews/API",
        "https://github.com/HackerNews/API",
        RateLimit(requests=30, per_seconds=60),
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        handle = _query_handle(identifier, True)
        resp = await self.fetch(ctx, f"https://hacker-news.firebaseio.com/v0/user/{quote(handle)}.json")
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        if not d:
            return []
        created = datetime.fromtimestamp(int(d["created"]), UTC) if d.get("created") else None
        about = _strip_html(d.get("about"))
        linked: list[LinkedIdentifier] = []
        for url in re.findall(r"https?://[^\s<>\"]+", html.unescape(d.get("about") or ""))[:5]:
            linked += website_links(url)
        return [
            self.profile_finding(
                identifier,
                handle=d["id"],
                profile_url=f"https://news.ycombinator.com/user?id={quote(d['id'])}",
                attrs={"karma": d.get("karma"), "created_at": created.isoformat() if created else None},
                linked=linked,
                raw=resp.content,
                bio=about,
                created=created,
            )
        ]


class RedditAdapter(_ProfileAdapter):
    platform = "reddit"
    meta = _meta(
        "reddit",
        "Reddit public JSON endpoint",
        "https://www.reddit.com/dev/api/",
        "https://www.redditinc.com/policies/data-api-terms",
        RateLimit(requests=10, per_seconds=60),
        reliability=Reliability.B,
        access=AccessMethod.PUBLIC_API,
        description="Public account 'about' endpoint. Reddit may block unauthenticated access; "
        "the adapter then reports the source as unavailable.",
    )
    meta.default_enabled = True

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(ctx, f"https://www.reddit.com/user/{quote(identifier.value)}/about.json")
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        body = resp.json()
        d = body.get("data") or {}
        if not d.get("name") or d.get("is_suspended"):
            return []
        created = datetime.fromtimestamp(int(d["created_utc"]), UTC) if d.get("created_utc") else None
        return [
            self.profile_finding(
                identifier,
                handle=d["name"],
                profile_url=f"https://www.reddit.com/user/{quote(d['name'])}",
                attrs={
                    "account_id": d.get("id"),
                    "karma": d.get("total_karma"),
                    "created_at": created.isoformat() if created else None,
                },
                linked=[],
                raw=resp.content,
                bio=_strip_html((d.get("subreddit") or {}).get("public_description")),
                created=created,
            )
        ]


class DevToAdapter(_ProfileAdapter):
    platform = "devto"
    meta = _meta(
        "devto",
        "DEV Community (Forem) API",
        "https://developers.forem.com/api",
        "https://dev.to/terms",
        RateLimit(requests=10, per_seconds=30),
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(ctx, "https://dev.to/api/users/by_username", params={"url": identifier.value})
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        linked = website_links(d.get("website_url")) + account_link("github", d.get("github_username"))
        linked += account_link("twitter", d.get("twitter_username"))
        return [
            self.profile_finding(
                identifier,
                handle=d["username"],
                profile_url=f"https://dev.to/{quote(d['username'])}",
                attrs={
                    "display_name": d.get("name"),
                    "account_id": str(d.get("id")),
                    "website": d.get("website_url"),
                    "created_at": d.get("joined_at"),
                },
                linked=linked,
                raw=resp.content,
                bio=_strip_html(d.get("summary")),
                created=parse_datetime(d.get("joined_at")),
            )
        ]


class CodebergAdapter(_ProfileAdapter):
    platform = "codeberg"
    meta = _meta(
        "codeberg",
        "Codeberg (Forgejo) API",
        "https://codeberg.org/api/swagger",
        "https://codeberg.org/codeberg/org/src/branch/main/TermsOfUse.md",
        RateLimit(requests=10, per_seconds=60),
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(ctx, f"https://codeberg.org/api/v1/users/{quote(identifier.value)}")
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        return [
            self.profile_finding(
                identifier,
                handle=d["login"],
                profile_url=f"https://codeberg.org/{quote(d['login'])}",
                attrs={
                    "display_name": d.get("full_name") or None,
                    "account_id": str(d.get("id")),
                    "website": d.get("website") or None,
                    "created_at": d.get("created"),
                    "followers": d.get("followers_count"),
                },
                linked=website_links(d.get("website")),
                raw=resp.content,
                bio=_strip_html(d.get("description")),
                created=parse_datetime(d.get("created")),
            )
        ]


class DockerHubAdapter(_ProfileAdapter):
    platform = "dockerhub"
    meta = _meta(
        "dockerhub",
        "Docker Hub API",
        "https://docs.docker.com/docker-hub/api/latest/",
        "https://www.docker.com/legal/docker-terms-service/",
        RateLimit(requests=10, per_seconds=60),
        access=AccessMethod.PUBLIC_API,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(ctx, f"https://hub.docker.com/v2/users/{quote(identifier.value)}/")
        if resp.status_code == 404:
            return []
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        d = resp.json()
        return [
            self.profile_finding(
                identifier,
                handle=d["username"],
                profile_url=f"https://hub.docker.com/u/{quote(d['username'])}",
                attrs={
                    "display_name": d.get("full_name") or None,
                    "account_id": d.get("id"),
                    "organization": d.get("company") or None,
                    "created_at": d.get("date_joined"),
                },
                linked=[],
                raw=resp.content,
                bio=None,
                created=parse_datetime(d.get("date_joined")),
            )
        ]


class NpmAdapter(_ProfileAdapter):
    platform = "npm"
    meta = _meta(
        "npm",
        "npm registry search API",
        "https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md",
        "https://docs.npmjs.com/policies/terms",
        RateLimit(requests=10, per_seconds=60),
        description="Packages maintained by an npm account (via maintainer search).",
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx, "https://registry.npmjs.org/-/v1/search", params={"text": f"maintainer:{identifier.value}", "size": 10}
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        objects = resp.json().get("objects") or []
        packages = []
        for obj in objects:
            pkg = obj.get("package") or {}
            maint = [m.get("username", "").lower() for m in pkg.get("maintainers") or []]
            if identifier.value in maint:
                packages.append(pkg.get("name"))
        if not packages:
            return []
        return [
            self.profile_finding(
                identifier,
                handle=identifier.value,
                profile_url=f"https://www.npmjs.com/~{quote(identifier.value)}",
                attrs={"packages": packages[:10]},
                linked=[],
                raw=resp.content,
                bio=None,
                created=None,
            )
        ]


class WikimediaAdapter(_ProfileAdapter):
    platform = "wikimedia"
    case_sensitive = True
    meta = _meta(
        "wikimedia",
        "Wikimedia global account API",
        "https://www.mediawiki.org/wiki/Extension:CentralAuth/API",
        "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
        RateLimit(requests=30, per_seconds=60),
        reliability=Reliability.A,
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        handle = _query_handle(identifier, True)
        handle = handle[:1].upper() + handle[1:]  # MediaWiki capitalises the first letter
        resp = await self.fetch(
            ctx,
            "https://meta.wikimedia.org/w/api.php",
            params={"action": "query", "meta": "globaluserinfo", "guiuser": handle, "format": "json"},
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        info = (resp.json().get("query") or {}).get("globaluserinfo") or {}
        if "missing" in info or not info.get("name"):
            return []
        return [
            self.profile_finding(
                identifier,
                handle=info["name"],
                profile_url=f"https://meta.wikimedia.org/wiki/Special:CentralAuth/{quote(info['name'])}",
                attrs={
                    "account_id": str(info.get("id")),
                    "created_at": info.get("registration"),
                    "home_wiki": info.get("home"),
                    "edit_count": info.get("editcount"),
                },
                linked=[],
                raw=resp.content,
                bio=None,
                created=parse_datetime(info.get("registration")),
            )
        ]


class KeybaseAdapter(_ProfileAdapter):
    platform = "keybase"
    meta = _meta(
        "keybase",
        "Keybase user lookup API",
        "https://keybase.io/docs/api/1.0/call/user/lookup",
        "https://keybase.io/docs/terms",
        RateLimit(requests=10, per_seconds=60),
        description="Keybase accounts and their cryptographically signed identity proofs "
        "(publicly documented cross-platform references).",
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        resp = await self.fetch(
            ctx, "https://keybase.io/_/api/1.0/user/lookup.json", params={"usernames": identifier.value}
        )
        if not resp.ok:
            raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
        body = resp.json()
        them = [t for t in (body.get("them") or []) if t]
        if not them:
            return []
        t = them[0]
        basics = t.get("basics") or {}
        proofs = []
        linked: list[LinkedIdentifier] = []
        for p in (t.get("proofs_summary") or {}).get("all") or []:
            ptype, pname = p.get("proof_type"), p.get("nametag")
            if not ptype or not pname:
                continue
            proofs.append({"type": ptype, "name": pname, "proof_url": p.get("proof_url")})
            if ptype in ("dns", "generic_web_site"):
                dom = try_normalize(IdentifierType.DOMAIN, pname)
                if dom:
                    linked.append(LinkedIdentifier(identifier=dom, relation="cryptographic_proof"))
            else:
                linked += account_link(ptype, pname, relation="cryptographic_proof")
        profile = t.get("profile") or {}
        return [
            self.profile_finding(
                identifier,
                handle=basics.get("username", identifier.value),
                profile_url=f"https://keybase.io/{quote(basics.get('username', identifier.value))}",
                attrs={"display_name": profile.get("full_name"), "account_id": t.get("id"), "proofs": proofs[:20]},
                linked=linked,
                raw=resp.content,
                bio=_strip_html(profile.get("bio")),
                created=None,
            )
        ]


USERNAME_ADAPTERS = [
    GitHubAdapter,
    GitLabAdapter,
    HackerNewsAdapter,
    RedditAdapter,
    DevToAdapter,
    CodebergAdapter,
    DockerHubAdapter,
    NpmAdapter,
    WikimediaAdapter,
    KeybaseAdapter,
]
