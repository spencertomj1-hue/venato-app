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

## Bundle size: leaving out unused parts of pyarrow

Measured with a real Linux PyInstaller build (`pyinstaller packaging/venato.spec`, Python 3.13, pyarrow 26.0.1,
PyInstaller 6.x; plotly already gone), before and after the excludes in `packaging/venato.spec`.

| | Before | After | Saved |
|---|---:|---:|---:|
| `dist/Venato` folder | 1014.5 MB | 959.3 MB | 55.2 MB |
| `_internal/pyarrow` | 163 MB | 110 MB | 53 MB |
| the folder as a .tar.gz | 373.6 MB | 354.4 MB | 19.2 MB |

What Streamlit loads from pyarrow to draw `st.dataframe` is only `pyarrow.lib`, `_compute`, `compute`, `ipc`,
`pandas_compat` and their helpers. The spec now excludes `pyarrow.parquet`, `.flight`, `.acero`, `.dataset`,
`.substrait`, `.gandiva` (plus `.orc` and `.tests`), drops their extension modules (`_parquet`, `_dataset*`,
`_acero`, `_substrait`, `_flight`, `_orc`, the cloud filesystem ones) and the shared libraries nothing links to
(`libarrow_flight` 32 MB, `libarrow_s3` 17 MB, the Flight and Parquet-encryption bridges).

Not dropped, although the brief listed them: `libarrow_acero`, `libarrow_dataset`, `libarrow_substrait` and
`libparquet` (about 24 MB). pyarrow's own `lib` module is linked against them, so without them `import pyarrow`
fails: with `libparquet.so` removed, `--check` still passed (it never imports pyarrow) but the Money page showed
`ImportError: libparquet.so.2600: cannot open shared object file` and no table drew. Getting rid of them needs a
slimmer pyarrow build, not an exclude.

Checked on the Linux bundle: `Venato --check` prints "Venato check OK: 8 pages drawn", `Venato --serve` answers
`/_stcore/health` with `ok`, and the Money page (5 `st.dataframe` tables and 3 charts) renders with no exception.
The Windows and macOS builds run in CI only and were not run here: the same exclusions apply, but their library
names (`.dll` / `.dylib`) are only matched by name, not tried.
