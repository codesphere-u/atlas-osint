"""Decentralised social networks with public, unauthenticated profile APIs.

Both platforms *verify* certain links, which makes them unusually strong evidence:

* Mastodon marks a profile link as verified (``verified_at``) when the linked page links back with
  ``rel="me"``.
* A Bluesky handle that is a custom domain proves control of that domain (DNS TXT or HTTPS well-known file).
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from engine.normalization.identifiers import try_normalize
from integrations.sources.base import CollectionContext, RateLimit, SourceError, parse_datetime
from integrations.sources.username import _meta, _ProfileAdapter, _strip_html, website_links
from shared.types import AdapterStatus, Finding, Identifier, IdentifierType, LinkedIdentifier

_HREF = re.compile(r'href="(https?://[^"]+)"')


class MastodonAdapter(_ProfileAdapter):
    platform = "mastodon"
    meta = _meta(
        "mastodon",
        "Mastodon account lookup API",
        "https://docs.joinmastodon.org/methods/accounts/#lookup",
        "https://mastodon.social/terms",
        RateLimit(requests=60, per_seconds=300, notes="per instance (default Mastodon limit 300/5 min)"),
        description="Public Mastodon accounts on the configured instances (ATLAS_FEDIVERSE_INSTANCES), including "
        'profile links verified by the instance via rel="me".',
    )

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        out: list[Finding] = []
        errors = 0
        instances = ctx.settings.fediverse_instances or ["mastodon.social"]
        for instance in instances[:5]:
            try:
                resp = await self.fetch(
                    ctx, f"https://{instance}/api/v1/accounts/lookup", params={"acct": identifier.value}
                )
            except SourceError:
                errors += 1
                continue
            if resp.status_code == 404:
                continue
            if not resp.ok:
                errors += 1
                continue
            d = resp.json()
            linked: list[LinkedIdentifier] = []
            verified = []
            for field in d.get("fields") or []:
                for url in _HREF.findall(str(field.get("value") or ""))[:2]:
                    url = html.unescape(url)
                    if field.get("verified_at"):
                        verified.append(url)
                        norm = try_normalize(IdentifierType.URL, url)
                        if norm:
                            linked.append(LinkedIdentifier(identifier=norm, relation="verified_link"))
                    else:
                        linked += website_links(url)
            handle = f"{d.get('username', identifier.value)}@{instance}"
            finding = self.profile_finding(
                identifier,
                handle=d.get("username", identifier.value),
                profile_url=d.get("url") or f"https://{instance}/@{quote(identifier.value)}",
                attrs={
                    "display_name": d.get("display_name") or None,
                    "account_id": f"{d.get('id')}@{instance}",
                    "created_at": d.get("created_at"),
                    "followers": d.get("followers_count"),
                    "linked_accounts": verified[:10],
                    "account_state": "bot" if d.get("bot") else "person_or_org",
                },
                linked=linked,
                raw=resp.content,
                bio=_strip_html(d.get("note")),
                created=parse_datetime(d.get("created_at")),
            )
            finding.entity_hint = f"account:mastodon:{handle.lower()}"
            finding.claim_key = f"account.exists:mastodon:{handle.lower()}"
            if verified:
                finding.description += f" {len(verified)} profile link(s) are verified by the instance (rel=me)."
            out.append(finding)
        if not out and errors == len(instances[:5]):
            raise SourceError(AdapterStatus.UNAVAILABLE, "all configured instances failed")
        return out


class BlueskyAdapter(_ProfileAdapter):
    platform = "bluesky"
    meta = _meta(
        "bluesky",
        "Bluesky public AppView API",
        "https://docs.bsky.app/docs/api/app-bsky-actor-get-profile",
        "https://bsky.social/about/support/tos",
        RateLimit(requests=30, per_seconds=60),
        description="Public Bluesky (AT Protocol) profiles. A custom-domain handle proves control of that domain.",
    )

    @staticmethod
    def candidates(handle: str) -> list[str]:
        if "." in handle:
            return [handle] if try_normalize(IdentifierType.DOMAIN, handle) else []
        return [f"{handle}.bsky.social"]

    async def collect(self, identifier: Identifier, ctx: CollectionContext) -> list[Finding]:
        out: list[Finding] = []
        for actor in self.candidates(identifier.value):
            resp = await self.fetch(
                ctx, "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile", params={"actor": actor}
            )
            if resp.status_code == 400:
                continue  # "Profile not found"
            if not resp.ok:
                raise SourceError(AdapterStatus.UNAVAILABLE, f"HTTP {resp.status_code}", resp.status_code)
            d = resp.json()
            handle = str(d.get("handle") or actor)
            linked: list[LinkedIdentifier] = []
            if not handle.endswith(".bsky.social"):
                dom = try_normalize(IdentifierType.DOMAIN, handle)
                if dom:
                    linked.append(LinkedIdentifier(identifier=dom, relation="verified_domain_handle"))
            for url in re.findall(r"https?://[^\s]+", d.get("description") or "")[:3]:
                linked += website_links(url.rstrip(".,)"))
            finding = self.profile_finding(
                identifier,
                handle=handle.removesuffix(".bsky.social"),
                profile_url=f"https://bsky.app/profile/{quote(handle)}",
                attrs={
                    "display_name": d.get("displayName") or None,
                    "account_id": d.get("did"),
                    "created_at": d.get("createdAt"),
                    "followers": d.get("followersCount"),
                },
                linked=linked,
                raw=resp.content,
                bio=_strip_html(d.get("description")),
                created=parse_datetime(d.get("createdAt")),
            )
            finding.entity_hint = f"account:bluesky:{handle.lower()}"
            finding.claim_key = f"account.exists:bluesky:{handle.lower()}"
            if linked and linked[0].relation == "verified_domain_handle":
                finding.description += f" The handle is the domain {handle}, verified by Bluesky."
            out.append(finding)
        return out


SOCIAL_ADAPTERS = [MastodonAdapter, BlueskyAdapter]
