"""Health data block: Apple Health export (zip / xml, phone + watch, sleep, workouts, unsafe XML),
Google Fit / Strava / Whoop CSVs, no doubles, the tool."""

import importlib
import io
import zipfile

import pytest

APPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
]>
<HealthData locale="en_GB">
 <ExportDate value="2026-10-10 09:00:00 +0100"/>
 <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-10-05 09:00:00 +0100" endDate="2026-10-05 10:00:00 +0100" value="4000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-10-05 15:00:00 +0100" endDate="2026-10-05 16:00:00 +0100" value="3000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" unit="count" startDate="2026-10-05 09:00:00 +0100" endDate="2026-10-05 10:00:00 +0100" value="7500"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2020-01-01 09:00:00 +0000" endDate="2020-01-01 10:00:00 +0000" value="99"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Watch" unit="count/min" startDate="2026-10-05 08:00:00 +0100" endDate="2026-10-05 08:00:00 +0100" value="54"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Scale" unit="lb" startDate="2026-10-05 07:00:00 +0100" endDate="2026-10-05 07:00:00 +0100" value="160">
  <MetadataEntry key="x" value="y"/>
 </Record>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-10-04 23:30:00 +0100" endDate="2026-10-05 03:30:00 +0100" value="HKCategoryValueSleepAnalysisAsleepCore"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-10-05 03:30:00 +0100" endDate="2026-10-05 07:00:00 +0100" value="HKCategoryValueSleepAnalysisAsleepREM"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="2026-10-04 23:00:00 +0100" endDate="2026-10-04 23:30:00 +0100" value="HKCategoryValueSleepAnalysisInBed"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30.5" durationUnit="min" sourceName="Watch" startDate="2026-10-05 18:00:00 +0100" endDate="2026-10-05 18:30:30 +0100">
  <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" startDate="x" endDate="y" sum="5.2" unit="km"/>
  <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" startDate="x" endDate="y" sum="320" unit="kcal"/>
 </Workout>
</HealthData>
"""


@pytest.fixture
def hl(store):
    from venato import blocks, tools
    importlib.reload(tools)
    importlib.reload(blocks)
    from venato.blocks import health as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["health", "workouts"])
    return module


def _zip(xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apple_health_export/export.xml", xml)
        z.writestr("apple_health_export/export_cda.xml", "<x/>")
    buf.seek(0)
    return buf


def test_apple_export(hl, store):
    from venato.blocks import workouts as wk
    r = hl.import_apple(_zip(APPLE), since="2026-01-01")
    assert r["workouts"] == 1
    day = "2026-10-05"
    assert hl.series("steps", day, day) == {day: 7500}           # watch beats phone, not 14,500
    assert hl.series("steps", "2020-01-01", "2020-01-01") == {}   # before 'since'
    assert hl.series("resting_hr", day, day) == {day: 54}
    assert hl.series("weight_kg", day, day)[day] == pytest.approx(72.57, abs=0.01)
    assert hl.series("sleep_h", day, day) == {day: 7.5}           # in bed doesn't count
    w = wk.workouts(day, day)
    assert len(w) == 1 and w[0]["title"] == "Running" and w[0]["minutes"] == 30.5 and w[0]["source"] == "apple health"
    assert wk.sets_of(w[0]["id"])[0]["distance"] == 5.2
    hl.import_apple(io.BytesIO(APPLE.encode()))                    # the plain xml, again: no doubles
    assert len(wk.workouts(day, day)) == 1
    assert hl.counts()["Apple Health"][1] == 1
    hl.clear("Apple Health")
    assert not hl.counts() and not wk.workouts(day, day)


def test_apple_rejects_entities(hl):
    bomb = """<?xml version="1.0"?><!DOCTYPE HealthData [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>
<HealthData><Record type="HKQuantityTypeIdentifierStepCount" value="&b;"/></HealthData>"""
    with pytest.raises(hl.HealthError):
        hl.read_apple(io.BytesIO(bomb.encode()))
    with pytest.raises(hl.HealthError):
        hl.read_apple(_zip("<HealthData>").__class__(b"PK\x03\x04 not really a zip"))


def test_strava_csv(hl):
    from venato.blocks import workouts as wk
    raw = ("Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Distance,Calories\n"
           '111,"Oct 6, 2026, 7:15:00 AM",Morning Run,Run,1900,5.01,1800,5010.0,350\n'
           '112,"Oct 7, 2026, 6:00:00 PM",Commute,Ride,2400,12.3,2300,12300.0,\n').encode()
    cols, rows = hl.read_csv(raw)
    assert cols.count("Distance") == 1
    m = hl.guess_mapping("Strava", cols)
    assert m["id"] == "Activity ID" and m["minutes"] == "Moving Time" and m["km"] == "Distance"
    _, workouts, problems = hl.convert("Strava", rows, m)
    assert not problems and workouts[0]["minutes"] == 30 and workouts[0]["start"] == "07:15"
    assert workouts[0]["title"] == "Morning Run" and workouts[1]["title"] == "Commute (Ride)" and workouts[0]["km"] == 5.01
    assert hl.import_csv("Strava", rows, m)["workouts"] == 2
    assert hl.import_csv("Strava", rows, m)["workouts"] == 0
    assert {w["source"] for w in wk.workouts("2026-10-06", "2026-10-07")} == {"strava"}


def test_google_fit_and_whoop(hl):
    fit = ("Date,Move Minutes count,Calories (kcal),Distance (m),Heart Points,Step count,Average heart rate (bpm)\n"
           "2026-10-01,40,2100.5,4500,20,6012,\n2026-10-02,10,1900,,5,,\n").encode()
    cols, rows = hl.read_csv(fit)
    m = hl.guess_mapping("Google Fit", cols)
    assert m["steps"] == "Step count" and m["distance_km"] == "Distance (m)"
    hl.import_csv("Google Fit", rows, m)
    assert hl.series("steps", "2026-10-01", "2026-10-02") == {"2026-10-01": 6012}
    assert hl.series("distance_km", "2026-10-01", "2026-10-01") == {"2026-10-01": 4.5}
    whoop = ("Cycle start time,Cycle end time,Recovery score %,Resting heart rate (bpm),Heart rate variability (ms),"
             "Day Strain,Asleep duration (min)\n2026-10-01 23:10:00,2026-10-02 22:50:00,67,52,71,12.4,452\n").encode()
    cols, rows = hl.read_csv(whoop)
    m = hl.guess_mapping("Whoop", cols)
    hl.import_csv("Whoop", rows, m)
    assert hl.series("recovery", "2026-10-01", "2026-10-01") == {"2026-10-01": 67}
    assert hl.series("sleep_h", "2026-10-01", "2026-10-01")["2026-10-01"] == pytest.approx(7.53, abs=0.01)
    _, _, problems = hl.convert("Whoop", [{"Cycle start time": "garbage"}], m)
    assert problems


def test_tool(hl, store):
    from venato import assistant
    assert "No health data" in hl.tool_health().text
    t = store.local_today().isoformat()
    hl.save_metrics([(t, "steps", 8000), (t, "resting_hr", 55)], "Whoop")
    hl.save_metrics([(t, "steps", 9000)], "Apple Health")
    out = hl.tool_health(7).text
    assert "Steps 9,000" in out and "Resting heart rate 55.0 bpm" in out
    assert "9000" in hl.tool_health(7, "steps").text
    assert "health_data" in {s[0] for s in assistant.tool_specs()}
