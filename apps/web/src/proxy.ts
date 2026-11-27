import { NextResponse, type NextRequest } from "next/server";

// UX-only guard: redirect to /login when there is no session cookie. Authorisation is enforced by the API.
const PUBLIC = ["/login", "/privacy", "/_next", "/favicon", "/api", "/healthz"];

export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();
  if (!req.cookies.get("atlas_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image).*)"] };
