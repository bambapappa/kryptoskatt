# Decision log

Format: ID · date · decision · alternatives · rationale · source.

### D1 · 2026-09-24 · Linked transfers are cost-neutral in the GAV pool
- **Alternatives:** keep the per-wallet re-valuation; build separate pools per wallet.
- **Rationale:** the average-cost method pools all holdings of the same asset (IL 48 kap. 7 §). A move between your own wallets is not a disposal (IL 44 kap. 3 §), so the cost basis must carry over. Units consumed as network fee leave the pool, and their cost stays with the remaining units.
- **Verification:** `tests/test_gav.py::TestLinkedTransferCarriesCostBasis`.

### D2 · 2026-09-24 · Manual prices in their own per-account table
- **Alternatives:** add `user_id` to `price_cache` (would break the unique key and shared caching).
- **Rationale:** public prices can be shared, but user input must never affect another user's tax. When migrating ownerless MANUAL rows, they are copied to the accounts that hold the coin, so no one's current result changes.

### D3 · 2026-09-24 · Remove `/api/v1/prices/import-history`
- **Rationale:** it used the client-supplied filename as a path (path traversal) and wrote to the shared cache. The operator can still import through the server-side `PriceHistory` directory.

### D4 · 2026-09-24 · Account ID stays the only credential, but stronger
- **Alternatives:** password or passkey (requires more personal data or complexity); e-mail (conflicts with the anonymity goal).
- **Rationale:** meets "log in privately" with no personal data. 4 words + 4 digits (~2^53) combined with per-IP and site-wide limits on failed attempts makes online guessing impractical.

### D5 · 2026-09-24 · Privacy by default
- Google Fonts removed: LG München I, 20 Jan 2022, 3 O 17493/20, found that dynamically loading Google Fonts without consent violates the GDPR.
- Access logs off by default; the rate limiter drops IP addresses after the window.
- Only necessary cookies (session, language), so no consent banner is needed (9 kap. 28 § lag (2022:482) om elektronisk kommunikation).
- Storage limitation (GDPR art. 5.1 e): accounts are deleted after 24 months without use.

### D6 · 2026-09-24 · "No liability at all" cannot be guaranteed. Mitigate instead
- **Honest assessment:** Swedish law does not generally allow disclaiming liability for intent or gross negligence, and consumer-protection rules are mandatory. So the terms limit liability "to the extent the law allows".
- **Mitigations:** clear disclaimer (aid, not advice), the user's own responsibility for their tax return (skatteförfarandelagen 2011:1244), acceptance required at sign-up, a public method page with known limitations, data minimisation, and complete erasure.
- **Recommendation:** have a lawyer review the texts before launch. This is not legal advice.

### D7 · 2026-09-24 · Zero API cost: Blockscout as the fallback for EVM
- **Rationale:** eth/base/arbitrum/polygon.blockscout.com answer the Etherscan-compatible API without a key (verified with curl on 2026-09-24). Etherscan is still used when a key exists (it also covers internal transactions).

### D8 · 2026-09-24 · Keep unpinned dependencies
- **Rationale:** the user previously chose auto-updating builds (PR #11). The mypy 2.x breakage was fixed in the code instead.
