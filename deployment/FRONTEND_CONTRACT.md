# Frontend deployment contract

## Request routing

Browser integrations call the API with relative same-origin paths under `/api/v1`. They do not append `XTransformPort`, do not construct an absolute backend URL, and do not send an API origin or credential from client code.

`next.config.ts` owns the external rewrite:

```text
/api/v1/:path*  ->  ${CROPTWIST_API_ORIGIN}/api/v1/:path*
```

The destination is created from a server-only, validated origin. The validator accepts `http`/`https` for local execution; Vercel requires HTTPS plus host and optional port. It rejects credentials, query strings, fragments, and path prefixes. Because the rewrite is same-origin from the browser’s perspective, the frontend does not require a browser CORS configuration for this route.

When not running on Vercel, a missing origin resolves to local `http://127.0.0.1:3030` for the existing local/direct-Next workflow. Vercel never uses that fallback: a missing `CROPTWIST_API_ORIGIN` fails the build/runtime configuration. Standalone Docker output remains `output: "standalone"` and continues to start on `PORT` (default `3000`); configure the origin explicitly when its backend is not loopback-local.

## Authentication contract

The existing Next route handlers under `/api/auth/*` remain the browser-facing auth boundary. They call the backend server-side through the same validated origin, set the existing HttpOnly `fs_token` and `fs_refresh` cookies, strip token material from response payloads, and preserve the existing refresh/logout behavior. The browser never receives bearer tokens and no Supabase auth SDK is introduced.

API calls rely on same-origin cookies. A 401 may trigger the existing single-flight refresh request and one retry. Backend error envelopes continue to map to the existing `ApiError` contract.

## Security constraints

- `CROPTWIST_API_ORIGIN` is server-only; never expose it through `NEXT_PUBLIC_*` or client runtime configuration.
- Do not put credentials, API keys, bearer tokens, query parameters, or fragments in the origin value.
- Keep browser API paths relative to preserve cookies and avoid leaking backend topology.
- Do not replace the existing auth boundary with Supabase or a client-side token store.
- The Vercel Git deployment gate remains disabled until an owner-authorized isolated preview is explicitly enabled and then disabled again.
