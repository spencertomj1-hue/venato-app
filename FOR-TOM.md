# For Tom

Things for Tom to pick up, newest at the top. Add a line or a section whenever something comes up; tick it (`[x]`) when it's done.

## Added 24 Nov 2026

### Switch on anonymous usage stats

- [ ] Make a PostHog project (posthog.com, **EU cloud**) and put its project API key (starts `phc_`) in `PROJECT_KEY` in `venato/analytics.py`. It's write-only, so it's fine in the public repo. Until then the switch is hidden and nothing is sent.

Opt-in, off by default (setup's Welcome step and Settings → About). Sends page views, time on each page (capped at 30 minutes), sessions, setup steps reached and finished or skipped, focus started, goal created, to-do ticked, assistant used, and blocks switched on. Never anything typed: `analytics.clean` drops any property not on the list in `EVENTS` and any text that isn't a short plain word. To add an event, add it to `EVENTS` and call `analytics.track(...)`.

In PostHog, build: a page views by page chart, median `seconds` of `page_left` by page, and a funnel of `onboarding_step` by `index` to `onboarding_finished`.

### A/B tests and gradual rollouts

Ready once the key above is in. In PostHog make a feature flag (e.g. `onboarding-v2`, variants `control` and `test`, 50/50), then in the code:

```python
from venato import analytics
if analytics.variant("onboarding-v2") == "test":
    ...   # the new version
```

For an on/off rollout use `analytics.is_on("flag-key")`. People who haven't opted in, or are offline, always get `control` / off. Make an Experiment in PostHog on that flag with a goal event (e.g. `onboarding_finished`). With fewer than about 1,000 weekly users, use flags for rollouts rather than A/B tests: the results won't be meaningful.

### Paid Claude assistant (Venato Pro)

- [ ] Read `docs/subscriptions-plan.md` and answer the five decisions at the bottom.

## Added 21 Nov 2026 (from Magnus)

### 1. Analyse what people actually get done

- [ ] Look at the done / not done data and work out what's worth showing.

Every block and calendar event on the timetable can now be marked **✓ Done** (it turns green) or **✗ Not done** from its card. Nothing analyses it yet; it's just being saved.

- Where it is: the `tt_status` table. `store.status_log(first, last)` returns every mark with a snapshot of the block (date, start, end, label, category, done / missed, when it was marked), so it survives the block being moved or deleted.
- Questions worth answering: what share of planned blocks get done, by category, by time of day and by weekday? Which activities slip most? Does marking things done line up with the confirmed Actual?
- Then decide where it goes (Review, Stats, Home) and whether Claude should use it when planning.

### 2. First questions: learn what people's goals are

- [x] Write the first questions a new user is asked, so Venato learns their goals before anything else. *(Partly, 22 Nov 2026: setup now asks for goals right after Welcome, with how long, how you'll know, why and a first step. The questions themselves still need designing with customer discovery, item 3.)*

The aim is to understand what someone is trying to achieve (study, training, work, habits) and set the app up around it, instead of starting from an empty timetable.

### 3. Customer discovery

- [ ] Do as much customer discovery as possible.

Talk to people who'd use Venato: what they use now, what they've tried and dropped, what a good week looks like for them, and what they'd pay for. Write down what you learn here or in its own doc so it can shape items 1 and 2.
