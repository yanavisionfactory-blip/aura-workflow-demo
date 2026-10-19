# SEO audit input connections

Connect the official research sources under **Connect → Find apps → Agents**.
Paste the exact endpoint, start discovery, then open the vendor approval link.
A pending authorization is disabled and has no capabilities. AURA publishes a
connection only after consent, token exchange and live MCP tool discovery.

| Source | Endpoint | Requirements |
| --- | --- | --- |
| Semrush | `https://mcp.semrush.com/v2/mcp` | Semrush sign-in and MCP access; OAuth scopes `mcp.access` and, if offered, `offline_access`. |
| Sitebulb Cloud | `https://mcp.sitebulb.com/cloud` | Sitebulb sign-in, selected workspace and existing completed crawl; scope `mcp:read`. |
| Sitebulb Desktop | `https://mcp.sitebulb.com/desktop` | Sitebulb sign-in and licensed, running, online Desktop machine; scope `mcp:read`. |

Semrush also supports an API key when OAuth client registration is unavailable.
After entering the official Semrush endpoint, use the optional password field
in AURA's agent form. The backend pins the endpoint and sends the documented
`Authorization: Apikey …` header; it encrypts the key and requires live tool
discovery before enabling the connection. A key is never accepted for another
autoconnect URL, stored in browser persistence, or returned in the connection
response. An account with appropriate MCP/API access is still required.

A vendor may reject a custom OAuth callback even when discovery succeeds.
Registration errors show the vendor's bounded error message rather than just
an HTTP status. Do not reuse another application's callback or client ID to
work around a vendor allowlist. Use the vendor's approved setup, a documented
alternative such as Semrush API-key authentication, or supplied exports.

Sitebulb currently rejects AURA's callback domain during public-client
registration, before sign-in. AURA displays the exact callback and official
support link under **Provider setup requirements**. Sitebulb must approve this
callback before AURA can complete OAuth; retrying or changing the client name
cannot grant that approval. No account credentials are requested at this stage.

The existing Ahrefs embedded actions use API v3. A successful OAuth connection
and three discovered actions do not establish plan entitlement. Preserve the
actual API response when a research request returns `Insufficient plan`.

Vendor metadata must match the reviewed resource and issuer. Authorization,
registration and token hosts are restricted per provider. PKCE, signed state,
tenant membership and one-use callback checks also apply to these routes.
Service outages, rejected metadata, insufficient account access or failed live
discovery do not produce a verified connection. Sitebulb's issuer must match
`https://auth.sitebulb.com`; a changed issuer requires an operator review.

Sitebulb MCP reads completed crawls; it cannot start a new audit. Its URL lists
are samples (up to 50 per hint), so retain full exports for exhaustive coverage.

Screaming Frog's official MCP is a paid SEO Spider feature, hosted by the
licensed user's running application. AURA cannot reach a desktop `localhost`
address. Use supplied exports unless an authorized, reachable MCP connection
has been separately configured. Do not expose a desktop server publicly just
to bypass this limitation, or claim that installing the free Spider enables MCP.

For each audit, retain the client domain and goal confirmation, source audit or
export dates, database/country/device settings and original row identifiers.
Missing evidence remains a coverage gap. Google Docs and Jira can deliver a
report and backlog if connected and the actual destination is established;
their presence in AURA does not prove that they are the client's internal tools.

Official references:

- [Semrush MCP setup](https://www.semrush.com/kb/1619-getting-started-with-mcp)
- [Sitebulb remote MCP setup](https://support.sitebulb.com/en/articles/15984107-connect-any-mcp-client-to-sitebulb)
- [Sitebulb permissions and limitations](https://support.sitebulb.com/en/articles/15984092-sitebulb-mcp-security-and-privacy-overview)
- [Screaming Frog MCP configuration](https://www.screamingfrog.co.uk/seo-spider/user-guide/configuration/#mcp-server)
