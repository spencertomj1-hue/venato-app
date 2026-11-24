Build the plan in `docs/plans/goal-progress-effort.md` in the Venato repo (spencertomj1-hue/venato-app). Read it fully first, then CLAUDE.md / CONTRIBUTING.md / HANDOVER.md for house rules.

**Start from** branch `claude/cool-volta-o2tstu` (it has the groundwork: compact target rows, target to-dos ticked on their row, next step + pace tick on each goal header). Branch off it, or work on it if told to.

**Context you need**
- Venato is a local Streamlit + SQLite planner. Goals = `life_goals` table (`venato/store/life_goals.py`, UI `venato/ui/life_goals.py`). Targets = `goals` table (`venato/store/goals.py`, UI `venato/ui/goals.py`, row is `_goal_row`, form is `_goal_form`). To-dos = `todos` table (`venato/store/todos.py`).
- To-dos link up through to-do categories (`todo_groups`): a goal's own category has `life_goal_id`, a target's has `goal_id` (= the target's id). `store.target_todos(target_id)` and `store.ensure_target_group(target_id)` exist. There's no `target_id` column on todos; don't add one.
- Schema changes are additive only, via `_add_column` in `venato/store/schema.py`. Never break an existing database.
- A target's `kind` is derived in `store/goals.py` (~line 124: count / habit / hours). A milestone is a new flag, not a new derived kind that breaks those.
- Goal % is computed in one place, `store.life_goal_progress`; Home's tile, the weekly review and the assistant all read it. Pace: `venato/pace.py` and `ui/life_goals.expected_fraction`.
- Tests: `python -m pytest -q` (about 4 min, ~660 tests). AppTest page tests are in `tests/test_life_goals_app.py`, and the pattern is in `tests/nav_helpers.py`. If `pip install -r requirements.txt` fails on pywebview/proxy_tools on Linux, install everything else; the tests don't need it.

**How to work**
- Do the phases in the plan's order, one commit each, with the full test suite green before every commit. Phase 1 includes the cleanup listed in the plan.
- TDD: write the maths tests in phase 1 before the code.
- Keep the copy style: short, plain British English, no em dashes.
- After phases 2 and 3, run the app and screenshot the Goals page to check the layout: `VENATO_DATA_DIR=<tmp> python scripts/seed_demo.py <tmp>`, then `streamlit run app.py`. The weekly review dialog may pop up first; close it.
- Don't open a PR unless asked. Push the branch when done.

**Done means**
- All 4 phases are in, tests are green, and the Goals page shows effort dots, milestone rows ("3 of 5 steps · 60%") and an effort-weighted goal %.
- A short report: what changed, any plan decisions you had to make, and screenshots.
