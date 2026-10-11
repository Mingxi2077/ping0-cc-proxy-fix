# Fixing ping0.cc (and similar sites) when they only break through the proxy

> **Symptoms**: works with a direct connection but fails through the proxy —
> `ERR_CONNECTION_CLOSED`, upstream connection resets, or HTTP 502; or the page loads but renders
> broken (missing CSS/JS, raw `{{ }}` template placeholders).
>
> **Applies to**: Clash / mihomo-family clients (FlClash, Clash Verge Rev, Clash Meta for Android,
> Clash for Windows, Mihomo Party, …) on Windows / Android / macOS / Linux.

## TL;DR

1. **Pin the site to a working IP via client-level `hosts`** — solves the core problem.
2. **Switch DNS** from AliDNS to DNSPod (`https://doh.pub/dns-query`).
3. **Try another node** — some node exit IPs are refused by the target site.

## Why it happens

- Some public DNS resolvers return *stale/dead IPs* for the domain.
- The site publishes AAAA (IPv6) records whose endpoint is dead, while most proxy chains have no usable IPv6.
- In mihomo's `fake-ip` mode the **domain is handed to the proxy node for resolution**; a bad remote
  resolution (or a node exit IP the site blocks) kills the connection.
- CDN subdomains fail the same way, so page assets (JS/CSS) never load — hence the broken rendering.

## Working hosts (verified 2026-10-11)

```yaml
hosts:
  ping0.cc: 104.218.235.243
  www.ping0.cc: 104.218.235.243
  cdn.ping0.cc: 172.67.188.46
  map.ping0.cc: 172.67.188.46
  ip.ping0.cc: 104.218.235.243
```

Client entry points:
- **FlClash**: Tools → Basic Config → Hosts
- **Clash Verge Rev**: Settings → Hosts (or profile merge/extension scripts)
- **Clash Meta for Android**: Settings → Override → Hosts

If the site changes IPs later, re-run `scripts/find_working_ip.py` and update.

## Diagnosis commands

```bash
# direct vs proxy
curl -sS --noproxy '*' -o /dev/null -w 'direct: %{http_code}\n' https://ping0.cc/
curl -sS -x http://127.0.0.1:7890 -o /dev/null -w 'proxy : %{http_code}\n' https://ping0.cc/

# force a specific IP through the proxy (skips resolution entirely)
curl -sS -x http://127.0.0.1:7890 --connect-to ping0.cc:443:104.218.235.243:443 \
     -o /dev/null -w 'force-ip: %{http_code}\n' https://ping0.cc/
```

| direct | forced-IP via proxy | domain via proxy | conclusion |
|--------|--------------------|------------------|------------|
| OK | OK | FAIL | resolution problem → pin hosts |
| OK | FAIL | FAIL | node exit problem → switch node |
| FAIL | — | — | site/network problem |

## Scripts

- `scripts/find_working_ip.py` — query multiple DoH resolvers, TCP+TLS test every candidate IP,
  print a ready-to-paste hosts block. Pure stdlib, cross-platform.
- `scripts/patch_flclash_windows.py` — write hosts entries into FlClash (Windows) config, with
  auto-backup and a running-process guard.

## License

MIT
