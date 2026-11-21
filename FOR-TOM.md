# For Tom

Things for Tom to pick up, newest at the top. Add a line or a section whenever something comes up; tick it (`[x]`) when it's done.

## Added 21 Nov 2026 (from Magnus)

### 1. Analyse what people actually get done

- [ ] Look at the done / not done data and work out what's worth showing.

Every block and calendar event on the timetable can now be marked **✓ Done** (it turns green) or **✗ Not done** from its card. Nothing analyses it yet; it's just being saved.

- Where it is: the `tt_status` table. `store.status_log(first, last)` returns every mark with a snapshot of the block (date, start, end, label, category, done / missed, when it was marked), so it survives the block being moved or deleted.
- Questions worth answering: what share of planned blocks get done, by category, by time of day and by weekday? Which activities slip most? Does marking things done line up with the confirmed Actual?
- Then decide where it goes (Review, Stats, Home) and whether Claude should use it when planning.

### 2. First questions: learn what people's goals are

- [ ] Write the first questions a new user is asked, so Venato learns their goals before anything else.

The aim is to understand what someone is trying to achieve (study, training, work, habits) and set the app up around it, instead of starting from an empty timetable.

### 3. Customer discovery

- [ ] Do as much customer discovery as possible.

Talk to people who'd use Venato: what they use now, what they've tried and dropped, what a good week looks like for them, and what they'd pay for. Write down what you learn here or in its own doc so it can shape items 1 and 2.
