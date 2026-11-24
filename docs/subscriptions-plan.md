# Venato Pro: paid Claude assistant (plan)

Status: **plan, nothing built yet.** The decisions at the bottom need answering before any code.

## The idea

Today the assistant needs the user's own Anthropic API key or Claude Code login. Pro lets someone pay Venato a monthly fee instead: Venato's server holds one Anthropic key and passes their requests through, counting what each person uses.

Free stays as it is (bring your own key, nothing goes through Venato).

## How it fits together

```
Venato app ──(Venato token)──▶ Venato API (proxy) ──(real key)──▶ Anthropic
                                    │
                         Supabase: users, usage   ◀── Stripe webhooks (who has paid)
```

1. **The app** sends its Claude requests to the Venato API instead of Anthropic. The Claude CLI already follows `ANTHROPIC_BASE_URL`, and `assistant._env()` (`venato/assistant.py`) already builds the CLI's environment, so Pro sets two variables there: `ANTHROPIC_BASE_URL=https://api.<domain>` and `ANTHROPIC_API_KEY=<the user's Venato token>`. Nothing else in the assistant changes.
2. **The proxy** (FastAPI, small) checks the token, checks the user is paid up and under quota, swaps in the real key, forwards to `api.anthropic.com`, streams the answer back, and records the tokens used (from the response's `usage`).
3. **Supabase** gives email sign-in (magic link, no passwords) and a Postgres database.
4. **Stripe** takes the money. Its webhook tells the proxy who's paid.

The real Anthropic key only ever lives on the server. Never in the app: anyone can unzip the installer.

## Steps

### 1. Accounts (half a day, Tom)
- Anthropic Console: an organisation for Venato, a production key, a **monthly spend limit**.
- Supabase project (EU region), Stripe account (test mode first), a domain for the API.

### 2. Database
- `users`: id (Supabase auth id), email, tier (`free` / `pro`), stripe_customer_id, created_at
- `tokens`: token hash, user_id, created_at, last_used (store a hash, never the token)
- `usage`: user_id, month, input_tokens, output_tokens, cache_read_tokens, requests

### 3. Proxy (`server/`, its own deploy)
- `POST /v1/messages`: the Anthropic Messages API shape, so the CLI talks to it unchanged.
  - token → user; not Pro → 402; over this month's allowance → 429 with a friendly message
  - rate limit per user (e.g. 20 requests a minute)
  - allow only the models Venato uses (stops someone pointing their token at the priciest model all day)
  - forward with streaming; add the usage to `usage` when the reply ends
- `GET /me`: tier, allowance left this month
- `POST /checkout`, `POST /portal`: Stripe Checkout and Customer Portal links
- `POST /stripe/webhook`: verify the signature; set `tier` on `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
- Logs: request counts and token totals only, **never message text** (it contains people's diaries).
- Host: Fly.io or Railway, EU region, the Anthropic and Stripe secrets as platform secrets.

### 4. App
- Settings → Assistant: a third choice beside "API key" and "Claude Code login": **Venato Pro**.
- Sign in: email → magic link → the app keeps the Venato token in the system's secret store (`keyring`, like the API key today).
- Show the allowance left (`/me`), an **Upgrade** button (Checkout in the browser) and **Manage subscription** (the Portal).
- A 402/429 from the proxy shows as a normal assistant message ("You've used this month's assistant allowance…").
- Analytics events (opt-in, `venato/analytics.py`): `pro_upgrade_clicked`, `pro_signed_in`, `pro_limit_hit`. No emails in events.

### 5. Keep the bill down
- Haiku by default (already: `DEFAULT_MODEL` in `venato/assistant.py`); the proxy only allows a bigger model for the heavy planning requests, if at all.
- Prompt caching on the system prompt and tool list: they're the same every turn, so most input tokens become cheap cache reads.
- Monthly allowance per user, plus the Anthropic spend limit as the last line of defence.
- Before setting the price: measure average tokens per active assistant user (the proxy's `usage` table, or a beta with a few friends), multiply by **current** Anthropic prices, add Stripe's fee and a margin.

### 6. Legal (before taking money)
- Privacy policy and terms: what's stored (email, usage counts), that Pro chat messages pass through Venato's server to Anthropic and aren't kept, how to delete an account.
- Check Anthropic's Commercial Terms and Usage Policy for offering Claude inside a paid product. Users must not share Claude Code / consumer logins through Venato: Pro is billed on Venato's own API key.
- UK GDPR: a lawful basis (contract), a way to export and delete data, Supabase/Stripe/Anthropic listed as processors.

### 7. Launch
- Stripe test mode end to end (card `4242 4242 4242 4242`), including cancelling.
- Roll out behind a flag: `analytics.is_on("venato-pro")` shows the Pro option only to the people the flag picks.
- Then everyone.

## Decisions for Tom

1. **Price and allowance**: e.g. £X a month for N assistant requests. Needs the usage measurement in step 5 first.
2. **Free trial?** e.g. 7 days of Pro, or a small free allowance through the proxy (costs you money per free user).
3. **Where the server code lives**: `server/` in this repo (simple) or its own private repo (keeps billing code out of the public one; recommended).
4. **Domain** for the API.
5. **Who's the legal seller**: you as a sole trader, or a limited company (Stripe needs to know; a company limits your liability).
