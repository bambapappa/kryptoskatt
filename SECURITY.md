# Security Policy

## Supported versions

Only the latest release on `main` receives security fixes.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, open a [GitHub Security Advisory](../../security/advisories/new) (private disclosure). Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce
- Suggested fix (if any)

We will acknowledge the report within 5 business days and aim to publish a fix within 30 days for critical issues.

## Threat model

KryptoSkatt is designed to be self-hosted. The primary assets to protect are:

| Asset | Risk |
|---|---|
| API keys in `.env` | Exposure of exchange/blockchain API credentials |
| Transaction history | Financial data (amounts, dates, wallet addresses) |
| Session cookies | Account takeover |
| Database | Full financial history of all accounts |

## Security design

### No personal data
Accounts are identified by a randomly generated passphrase (`word-word-word-word-NNNN`, ~2^53 combinations; older accounts have three words). No email, name, or password is stored. Only strictly necessary cookies are set; no third-party scripts or fonts are loaded; HTTP access logs are off by default.

### Session security
- Sessions use HttpOnly, SameSite=Lax cookies
- Session tokens are stored **hashed (SHA-256)** in the database — a database leak does not expose usable session tokens
- `COOKIE_SECURE=true` must be set in production (enforces HTTPS-only)
- Sessions expire after 30 days of inactivity
- Login and account creation are rate limited per client IP (10 requests/minute), and failed logins have a site-wide cap (200/minute)
- A new account ID is only shown in the response body (`Cache-Control: no-store`), never in a URL
- CSRF: state-changing requests with a cross-origin `Origin`/`Referer` header are rejected (defense-in-depth on top of SameSite=Lax)
- `X-Forwarded-*` headers are only trusted from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`; `docker-compose.prod.yml` sets it to the internal Caddy network)

### Multi-tenant isolation
Every database query is scoped to `user_id`/`account_id`; manual prices are per account. Tests in `tests/test_multi_tenant_isolation.py`, `tests/test_account_deletion.py` and `tests/test_web.py` verify isolation, complete erasure and account-scoped refetch.

### Other controls
- User-supplied explorer URLs must be public `https` URLs (SSRF guard, re-checked at fetch time)
- User secrets are encrypted with Fernet (key derived from `SECRET_KEY`); without `SECRET_KEY` storing them is refused
- Uploads are limited to 20 MB
- GDPR export/erasure covers every per-account table; inactive accounts are purged after `INACTIVE_ACCOUNT_MONTHS`

### Configuration
All secrets (API keys, database credentials) are loaded from environment variables or `.env`. The `.env` file **must never be committed to version control** — `.gitignore` is pre-configured to prevent this.

## Deployment hardening checklist

Before exposing KryptoSkatt to the internet:

Follow [`docs/drift.md`](docs/drift.md) (full Linux guide). In short:

- [ ] Start with `docker-compose.prod.yml` (Caddy + TLS; app and database only on an internal network)
- [ ] Set `SECRET_KEY`, a strong `POSTGRES_PASSWORD`, `CORS_ORIGINS`, `OPERATOR_NAME`, `OPERATOR_CONTACT`
- [ ] Keep `DEBUG_MODE=false`, `ACCESS_LOG=false`, `WEB_CONCURRENCY=1`
- [ ] Firewall: only 22/80/443; SSH with keys only
- [ ] Nightly off-site encrypted backups (`deploy/backup.sh`), restore tested
- [ ] Rotate API keys if they were ever accidentally committed

## Repository governance

Controls on what gets merged into `main`:

- **CODEOWNERS**: all paths are owned by the repository owner — enable
  "Require review from Code Owners" in branch protection so external PRs
  cannot merge without owner approval.
- **CI + CodeQL**: every PR runs tests, lint, `pip-audit` and CodeQL
  static analysis. Make these required status checks.
- **Dependabot**: weekly PRs for pip, GitHub Actions and Docker base
  images, so dependency updates are reviewed like any other change.

Recommended branch protection for `main`
(Settings → Branches → Add branch ruleset):

- [ ] Require a pull request before merging (no direct pushes)
- [ ] Require review from Code Owners (1 approval)
- [ ] Require status checks to pass: `Tests & Lint`, `Analyze (Python)`
- [ ] Require branches to be up to date before merging
- [ ] Block force pushes and deletions
- [ ] Do not allow bypassing the above settings

Additionally, under Settings → Actions → General, set workflow
permissions to "Read repository contents" and require approval for
workflow runs from first-time contributors (default) so untrusted PRs
cannot exfiltrate secrets via CI.

## Known limitations

- The built-in rate limiter and background job manager are in-memory and per-process — behind a load balancer or with multiple workers, add an IP-based rate limit at the reverse proxy level and use sticky sessions.
- The application does not support two-factor authentication. Access control relies entirely on the secrecy of the `account_id` passphrase.
- Changing `SECRET_KEY` makes previously stored user API keys unreadable (users must re-enter them).
