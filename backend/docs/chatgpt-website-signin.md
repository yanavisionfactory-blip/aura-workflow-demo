# ChatGPT website sign-in: backend preparation

Status: **draft, not enabled or deployed**. `app/openai_signin.py` is not imported
or mounted by `app/main.py`. There are no frontend, marketplace, production
configuration, or existing authentication changes in this patch.

This implements the provider portion of OpenAI's website **identity-only**
Authorization Code / PKCE / OpenID Connect flow. It cannot use a customer's
ChatGPT subscription for model requests, access their conversation history, or
replace the OpenAI API connector's key with a ChatGPT session.

## Registration required before activation

OpenAI's commercial website guide requires a client registration issued to AURA.
The `oaiapp_example` identifier and sample JWT audience in the guide are examples;
the implementation rejects both. A successful AURA MCP connection inside ChatGPT
does not supply this separate registration.

Request the following through OpenAI's Sign in with ChatGPT interest process:

- Product: AURA, https://yanavisionfactory-blip.github.io/aura-workflow-demo/
- Proposed exact production callback:
  `https://impartial-emotion-production-49d4.up.railway.app/auth/openai/callback`
- Website identity scopes: `openid profile email`.
- The issued client ID, registered token authentication method (`none` or
  `client_secret_basic`), and a client secret only if the client is confidential.
- **Separately:** approval and the integration contract for ChatGPT plan usage
  in AURA's hosted product, if model usage under the user's plan is required.

The callback above is a proposed registration value, not an already live route.
Do not configure a placeholder client, borrow another application's registration,
or enable the open-source local-client flow on AURA's shared hosted backend.

## What is implemented

`OpenAISignInConfig` validates the registration shape and the HTTPS callback.
`OpenAISignInClient` discovers and validates the published OpenAI issuer and
endpoints, creates fresh state/nonce/S256 PKCE values, exchanges a one-use code
using the registered client authentication method, and verifies the RS256 ID
token's signature, issuer, audience, expiration, issue time, nonce, and subject.
It caches JWKS and refreshes unfamiliar key IDs with bounded retries. Identity
scopes require an ID token only; no access or refresh token is required or saved.

`RedisSignInTransactions` accepts the existing asynchronous Redis connection and
`CredentialVault`. It encrypts the temporary verifier and nonce, stores them for
10 minutes, hashes the browser handle for the Redis key, and uses atomic `GETDEL`
to prevent cross-worker replay. Use a Redis version supporting `GETDEL` (6.2+).
Redis failures fail closed. Redis must remain private to the backend.

`openai_signin_router` provides `/auth/openai` and `/auth/openai/callback` only
when explicitly included in an application. It sets an opaque, host-only,
HttpOnly, Secure, SameSite=Lax transaction cookie and removes it after success or
failure. A new attempt in the same browser invalidates the previous attempt.
Responses disable caching and referrer disclosure. Errors never echo provider
bodies, codes, tokens, or internal exceptions.

## Application integration still required

AURA currently authenticates browser API calls with Clerk bearer tokens. Creating
an independent cookie in this module would not sign a user into the current
frontend, and accepting OpenAI ID tokens as Clerk tokens would bypass AURA's
existing identity policy. This patch intentionally does neither.

The router requires an explicit `complete_signin(request, identity)` adapter.
Before mounting the routes, implement and test that adapter through the approved
Clerk/account integration:

1. Resolve existing identities by `(issuer, client_id, subject)`, with a database
   uniqueness constraint. OpenAI email and `sid` are not identity mapping keys.
2. Confirm a new link using an authenticated existing AURA account. Never attach
   an identity to an existing user solely because emails match, even if the email
   is marked verified. Enforce enterprise SSO and provisioning policy.
3. For an approved new-account flow, apply the existing AURA onboarding policy.
4. Issue the application's normal session and return a fixed approved redirect;
   do not put raw OpenAI tokens, identity claims, or session secrets in URLs.
5. Retain only necessary identity mapping and profile data; do not persist raw
   OpenAI tokens. Preserve the verified `sid` only if session-security handling
   requires it. Signing out should end the AURA session only.

Construct the client with a dedicated `httpx.AsyncClient` with no default API key,
Authorization header, or HTTP authentication. Manage its lifespan explicitly.
Keep confidential client secrets in server-side secret storage. A public client
must not send a secret; a confidential client must not fall back to public auth.
Retain AURA's access-log privacy filters, and disable request/body debug logging.

Only after provider registration and this adapter are validated should a separate
review add the recognizable **Continue with ChatGPT** entry point. The user's
current instruction is to leave the frontend unchanged. No new environment
variables or activation flag are read by this draft.

## Validation

Run `pytest -q tests/test_openai_signin.py` and the existing backend checks.
The focused suite uses real RSA signatures and a mocked OpenAI HTTP boundary.
It covers incorrect claims/signatures, PKCE, public/confidential clients, expired
state, cookie binding, concurrent callback replay, rejected consent, discovery
trust boundaries, key rotation, and failure cleanup. Redis contract tests model
atomic `GETDEL`; they are not a live Redis integration test.

Before declaring the feature live, also test real Redis expiry/atomic consumption,
an approved OpenAI registration, the Clerk/session adapter, explicit linking for
an existing account, a fresh external user, and cross-user workspace isolation.
No automated test here proves OpenAI approval or an external-user sign-in.

References:
- https://developers.openai.com/siwc/website
- https://developers.openai.com/siwc/request-client-id
- https://openai.com/form/sign-in-with-chatgpt-interest/
- https://auth.openai.com/.well-known/openid-configuration
