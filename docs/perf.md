# Page timing

Measured with `.venv/bin/python scripts/profile_pages.py --runs 9`. It builds a throwaway data folder with
`scripts/seed_demo.py`, switches every block on, and times each page's rerun with Streamlit's `AppTest`
(the first, cold run is discarded). Times are server-side script time in milliseconds, not browser paint,
and vary a little between runs (about 10%), so compare orders of magnitude, not single digits.

Machine for these numbers: Linux container, Python 3.13, Streamlit 1.66.1, AppTest, demo data, Outlook
not linked, assistant off.

## Before

| page | median_ms | p90_ms |
|---|---:|---:|
| Home | 412 | 456 |
| Timetable | 254 | 271 |
| Focus | 28 | 39 |
| Goals | 430 | 447 |
| Daily Log | 36 | 50 |
| Workouts | 24 | 26 |
| Cut down | 49 | 76 |
| Food | 44 | 47 |
| Grades | 15 | 16 |
| Applications | 21 | 23 |
| Money | 45 | 46 |
| Involvement | 32 | 40 |
| Network | 15 | 17 |
| Health data | 19 | 26 |
| Stats | 286 | 333 |
| Settings | 60 | 79 |

| interaction | median_ms | p90_ms |
|---|---:|---:|
| Home: tick a to-do | 454 | 494 |
| Daily Log: tick a habit | 42 | 47 |
| Home: tick a habit | 445 | 485 |
| Focus: start (Home quick-focus button) | 507 | 559 |
| Focus: stop (rerun after) | 459 | 476 |
| Timetable: Plan / Actual switch | n/a | n/a |

Notes on the interactions:

- To-do ticks and Focus stop go through browser components that AppTest cannot click. The script saves the
  change in the store (what the component's callback does) and times the rerun that follows.
- The Plan / Actual switch lives in the browser and never reruns Python, so there is nothing to time (n/a).
- "Home: tick a habit" is on Home; "Daily Log: tick a habit" is the Daily Log page's own checkbox.

### Slowest three

Pages: **Goals (430)**, **Home (412)**, **Stats (286)**. Timetable (254) is close behind.

Interactions: every Home-page interaction (focus start 507, to-do 454, habit 445, focus stop 459) costs about
one full Home rerun (about 410-500), so Home is the target. A tick on the Daily Log page costs only 42.

## After

(to be filled in by re-running the script at the end of the plan)
