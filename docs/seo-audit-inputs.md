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
