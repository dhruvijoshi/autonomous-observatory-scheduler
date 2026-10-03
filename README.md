# autonomous-observatory-scheduler

A deterministic, simulation-based scheduler for a robotic telescope. Given a
set of observation requests with priorities and deadlines, it decides what the
telescope should observe during a night, checks every decision against the
physical and operational constraints, and records the whole night as an event
log.

The project is a simulation, not a control system: nothing here talks to real
hardware. The goal is a small, well-tested core in which scheduling strategies
can be compared fairly on identical conditions.

## What it does

For one night (a `Mission`), the system:

1. Computes, from the telescope's latitude and each target's coordinates,
   when every target is above its minimum altitude (its *visibility windows*).
2. Builds a precomputed timeline of world events: the observatory opening and
   closing, weather changes, targets rising and setting, and request deadlines.
3. Repeatedly asks a planner what to do next, using a read-only snapshot of
   the world.
4. Validates each proposed action against a fixed list of constraints.
5. Executes approved actions in the simulator (slew, expose, complete) and
   advances time to the next event that warrants a replan.
6. Stops when the observatory closes and returns the full event log.

Every run is reproducible: the same mission and planner always produce the
same event log.

## Current status

- **Domain model**: immutable configuration (observatory, targets, request
  definitions, mission) kept separate from per-run mutable state.
- **Astronomy**: closed-form spherical-trigonometry altitude, sidereal time,
  and rise/set windows. No runtime dependency on an astronomy library.
- **Discrete-event simulator**: a time-ordered event queue with deterministic
  tie-breaking, plus the happy path of slew → expose → complete.
- **Constraint validator**: six named checks for an observation (valid
  request, visibility for the full exposure, telescope idle, instrument idle,
  weather permits observing, deadline feasible).
- **Baseline planner**: greedy choice of the highest-priority visible request,
  with earliest deadline as the tiebreaker.
- **Orchestrator loop**: planner → validator → simulator, with a full
  telemetry log of proposals, approvals, rejections and replans.
- **Mission loading** from plain structured data (a dictionary).
- **Test suite**: 30 tests covering the domain, astronomy, simulator, event
  queue, validator, and end-to-end runs, including reproducibility checks.

## Quick start

Requires Python 3.9 or newer. There are no runtime dependencies.

```python
from backend.domain.entities import (
    Mission, ObservationTarget, Observatory, RequestDefinition, WeatherCondition,
)
from backend.missions.mission_loader import load_mission
from backend.orchestrator.loop import run_mission
from backend.planners.baseline import BaselinePlanner

observatory = Observatory(
    id="obs1", name="Example Site", latitude=40.0, longitude=-105.0,
    elevation=1655.0, default_minimum_altitude=30.0,
    telescope_slew_rate_deg_per_sec=2.0,
)

targets = [ObservationTarget(id="t1", name="Example Star", ra=180.0, dec=0.0)]

mission = load_mission({
    "id": "night-1",
    "name": "Example night",
    "observatory_id": "obs1",
    "request_definitions": [
        {"id": "d1", "target_id": "t1", "priority": 5,
         "required_exposure_duration": 30, "deadline": 200},
    ],
    "weather_script": [[0, "CLEAR"]],
    "night_window": [0, 400],            # minutes since night start
    "starting_local_sidereal_time": 170.0,  # degrees
})

event_log = run_mission(mission, observatory, targets, BaselinePlanner())
for event in event_log.all():
    print(event.sim_time, event.type.value, event.payload)
```

Times are in simulated minutes measured from the start of the night window.
There is no calendar or time zone; the mission's starting sidereal time is
what anchors the sky.

## Running the tests

```bash
pip install pytest
pytest
```

The astronomy test cross-checks the altitude formula against Astropy. It is
skipped unless Astropy is installed (`pip install astropy`).

## Project layout

```
backend/
  domain/        entities, value objects, events, astronomy math
  constraints/   the constraint validator
  simulator/     event queue, weather script, the simulator itself
  planners/      the Planner protocol and the baseline planner
  orchestrator/  the planner → validator → simulator loop
  missions/      mission loading and run instantiation
  telemetry/     the in-memory event log
tests/           mirrors backend/ and includes end-to-end runs
```

## Design principles

- **Determinism.** No randomness and no wall-clock time. A run is a pure
  function of its mission and planner ID.
- **Planner-agnostic core.** Planners see only a read-only snapshot of the
  world and cannot touch the simulator. Any planner, baseline or otherwise,
  is compared under identical conditions.
- **Validation before execution.** The simulator only executes proposals that
  the validator has approved. Rejected proposals change nothing.
- **Precompute once, consume twice.** Visibility windows are computed once per
  run. The simulator uses them to schedule events, and the validator uses the
  same windows to check proposals, so the two cannot disagree.
- **Scope.** The project models scheduling, not the sky. Astrophysics, orbital
  mechanics, computer vision, and 3D rendering are deliberately out of scope.
