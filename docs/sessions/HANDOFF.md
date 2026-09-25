# Session handoff

Updated at the end of each working session. Pair with [`BESLUTSLOGG.md`](BESLUTSLOGG.md) for the reasoning behind each change.

## 2026-09-24: audit and fixes (branch `arbete/funny-ramanujan-2m40l7`)

### Goal (from the user)
1. As a user, I can log in privately, enter my known wallet addresses, and get my taxes calculated correctly under Swedish law, revealing no personal information beyond what correct results require.
2. As the site owner, I want as little liability as possible and a site that complies with Swedish and EU law.
3. Simpler and more intuitive UI. Changing data sources is fine as long as the site runs with no API costs.

### Done
| Area | Change | Commit (subject) |
|---|---|---|
| Tax | Own-wallet transfers are cost-neutral (were resetting the GAV) | fix(gav): own-wallet transfers carry cost basis |
| Tax | 70 % loss rule shown in the year summary and dashboard | feat: login hardening, legal pages … |
| Security | Manual prices per account (migration 017), unsafe price upload removed | fix: per-account manual prices … |
| GDPR | Complete erasure and export, purge of inactive accounts | fix: per-account manual prices … / fix: upload limits … |
| Security | SSRF guard for explorer URLs | fix(security): block SSRF … |
| Security | Stronger account IDs, global cap on failed logins, ID not in URL | feat: login hardening … |
| Privacy | Google Fonts removed, access logs off, rate limiter drops IPs | feat: login hardening … / fix: upload limits … |
| Legal | Terms, privacy policy, method page, terms acceptance at sign-up | feat: login hardening … |
| Cost | Key-free Blockscout for ETH/Base/Arbitrum/Polygon | feat: login hardening … |
| UI | Step-based navigation, guided dashboard | feat(ui): step-based navigation … |

Verification: `pytest` 629 passed, `ruff check src/` clean, `mypy` clean (Python 3.13, latest dependency versions).

### The operator must do before deploying
- Set `SECRET_KEY`, `OPERATOR_NAME` and `OPERATOR_CONTACT` in `.env`. The privacy policy shows a warning until these are set.
- Set `FORWARDED_ALLOW_IPS` to the reverse proxy's IP if the proxy runs in its own container.
- Run migration 017 (the container does this automatically). Existing manual prices are copied to every account that has transactions in that coin.
- Have a lawyer review the terms and privacy policy. They are written in good faith, but no one can guarantee "no liability at all" (see decision D6).

### Open / next steps
- Fees paid in a coin other than the one traded are not counted as a disposal (documented under "Kända begränsningar").
- Solana has no key-free source. A free Helius key costs nothing but requires signing up.
- BNB Chain: no public Blockscout instance was found, so it requires a (free) Etherscan key.
- Accounts using the old 3-word ID (~2^43) keep working. A way to "upgrade" the ID could be added.
- Dependencies are deliberately not pinned (the user's earlier choice: auto-updating builds). CI catches regressions, as happened with mypy 2.x this session.

## 2026-09-24 (continued): documentation and further improvements (same branch / PR #13)

### Done
- **Bugs found while documenting:** the web fetch paths blocked keyless EVM fetching and ignored per-account keys. `/actions/refetch` could delete other accounts' rows (in practice it matched none because of a format mismatch). Fetch and the address tagger were missing account filters. The export excluded the wrong session table name.
- **Improvements:** "Alla år" as the default calculation target, warning box on the year page, export button under Settings, clearer transfer action, link to results after a calculation.
- **Documentation:** README (features, env, checklist before public launch, keyless table), `anvandare.md` (whole flow, keys, 70 %, privacy), `user.md` rewritten in English, `arkitektur.md` (price chain, GAV algorithm, isolation, GDPR, SSRF), `api.md` (actual response formats, removed endpoint, 413/503, limits), `forbattringar.md` (2026-09 section).

Verification: 632 tests, ruff and mypy clean.

### Open
See "Kvar (förslag)" in `docs/forbattringar.md`.

## 2026-09-25: user and administrator documentation (PR #13 merged, new branch from main)

### Done
- `docs/drift.md`: complete administrator guide for a public site on Linux.
- Production setup: `docker-compose.prod.yml` (Caddy + automatic HTTPS, internal network 172.28.0.0/24), `deploy/Caddyfile` (no access log), `deploy/backup.sh` (pg_dump + rotation), `deploy.sh` rewritten (backup → git pull → build → health check).
- `docker-compose.yml`: the app port is bound to 127.0.0.1 (Docker bypasses ufw).
- `docs/anvandare.md` is end-user only (installation removed, security tips added). README has a documentation map and quick starts. SECURITY.md updated.
- Verified: `docker compose config` with the overlay (the app has no published port; Caddy has 80/443), `bash -n` on the scripts.

### Not verified
- A full start on a real server with a real domain (certificate issuance) has not been tested in this environment.
