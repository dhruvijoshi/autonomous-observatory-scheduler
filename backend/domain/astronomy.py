"""Altitude, azimuth and visibility-window math for one observatory.

Conventions:
- All angles in degrees at this module's boundary. Converted to radians only
  inside trig calls.
- RA is stored/passed in degrees, never hours.
- Longitude and elevation are not consumed here — their effect is fully
  absorbed into the Mission's `starting_local_sidereal_time` parameter.
- sim_time is minutes elapsed since night_window.start (the synthetic clock;
  no calendar, no timezone, no real UTC anywhere in this module).

No runtime dependency on Astropy or any other astronomy library — the trig
below is exact, closed-form spherical astronomy. Astropy is used only in
tests/domain/test_astronomy.py as a one-time correctness oracle for fixtures.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from backend.domain.entities import ObservationTarget, Observatory
from backend.domain.value_objects import ObservationWindow

# Ratio of a mean solar day to a mean sidereal day — the standard constant.
_SIDEREAL_TO_SOLAR_RATIO = 1.0027379
SIDEREAL_RATE_DEG_PER_MIN = 0.25 * _SIDEREAL_TO_SOLAR_RATIO  # ~0.250684 deg/min
SIDEREAL_PERIOD_MIN = 360.0 / SIDEREAL_RATE_DEG_PER_MIN  # ~1436.07 min


def local_sidereal_time_deg(starting_lst: float, sim_time: float) -> float:
    """LST(t) = starting_lst + t * sidereal_rate, wrapped into [0, 360)."""
    return (starting_lst + sim_time * SIDEREAL_RATE_DEG_PER_MIN) % 360.0


def _hour_angle_deg(lst_deg: float, ra_deg: float) -> float:
    """H = LST - RA, normalized into (-180, 180] for interpretability.
    Only cos(H) is used downstream, which is even in H, so this normalization
    only affects readability, not correctness."""
    h = (lst_deg - ra_deg) % 360.0
    if h > 180.0:
        h -= 360.0
    return h


def altitude_deg(ra_deg: float, dec_deg: float, latitude_deg: float, lst_deg: float) -> float:
    """Exact spherical-trigonometry altitude of a target — the only formula
    scheduling decisions depend on."""
    h = math.radians(_hour_angle_deg(lst_deg, ra_deg))
    dec = math.radians(dec_deg)
    lat = math.radians(latitude_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(h)
    # Guard against floating-point drift pushing sin_alt marginally outside [-1, 1].
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))


def azimuth_deg(ra_deg: float, dec_deg: float, latitude_deg: float, lst_deg: float) -> float:
    """Display-only. No scheduling decision depends on this value."""
    h = math.radians(_hour_angle_deg(lst_deg, ra_deg))
    dec = math.radians(dec_deg)
    lat = math.radians(latitude_deg)
    az = math.degrees(math.atan2(math.sin(h), math.cos(h) * math.sin(lat) - math.tan(dec) * math.cos(lat)))
    return (az + 180.0) % 360.0


def altitude_at_sim_time(target: ObservationTarget, observatory: Observatory, starting_lst: float, sim_time: int) -> float:
    lst = local_sidereal_time_deg(starting_lst, sim_time)
    return altitude_deg(target.ra, target.dec, observatory.latitude, lst)


def compute_observation_windows(
    target: ObservationTarget,
    observatory: Observatory,
    night_window: Tuple[int, int],
    starting_lst: float,
) -> List[ObservationWindow]:
    """Returns the maximal [rise_time, set_time] sub-intervals of night_window
    during which target's altitude >= its effective minimum altitude.
    Pure function of its inputs — computed once at Run instantiation, identical
    for every Run of the same Mission."""
    start, end = night_window
    min_alt = target.effective_minimum_altitude(observatory)

    dec = math.radians(target.dec)
    lat = math.radians(observatory.latitude)
    sin_min_alt = math.sin(math.radians(min_alt))

    denom = math.cos(dec) * math.cos(lat)
    if denom == 0.0:
        # Degenerate observer/target geometry (target at a celestial pole as seen
        # from the equator) — treat as never visible rather than dividing by zero.
        return []

    cos_h0 = (sin_min_alt - math.sin(dec) * math.sin(lat)) / denom

    if cos_h0 > 1.0:
        return []  # never reaches min_alt this Mission
    if cos_h0 < -1.0:
        return [ObservationWindow(rise_time=start, set_time=end)]  # never drops below min_alt

    h0 = math.degrees(math.acos(cos_h0))  # in [0, 180]

    # H(t) = starting_lst + t*rate - ra (mod 360). Solve H(t) = -h0 (rise) and
    # H(t) = +h0 (set) for t, then enumerate all instances within the window.
    def crossings_for(h_target: float) -> List[float]:
        base = ((target.ra - starting_lst + h_target) % 360.0) / SIDEREAL_RATE_DEG_PER_MIN
        times = []
        # Walk enough sidereal periods in both directions to cover [start, end].
        k_min = math.floor((start - base) / SIDEREAL_PERIOD_MIN) - 1
        k_max = math.ceil((end - base) / SIDEREAL_PERIOD_MIN) + 1
        for k in range(int(k_min), int(k_max) + 1):
            t = base + k * SIDEREAL_PERIOD_MIN
            if start <= t <= end:
                times.append(t)
        return times

    rises = sorted(crossings_for(-h0))
    sets = sorted(crossings_for(+h0))

    # Sweep: start with the visibility state at `start`, then walk boundary
    # crossings in time order, opening/closing windows as we go.
    events = sorted([(t, "rise") for t in rises] + [(t, "set") for t in sets])
    currently_visible = altitude_at_sim_time(target, observatory, starting_lst, start) >= min_alt

    windows: List[ObservationWindow] = []
    window_start = start if currently_visible else None
    for t, kind in events:
        t_i = int(round(t))
        if kind == "rise" and not currently_visible:
            currently_visible = True
            window_start = t_i
        elif kind == "set" and currently_visible:
            currently_visible = False
            if window_start is not None:
                windows.append(ObservationWindow(rise_time=window_start, set_time=t_i))
            window_start = None
        # A "rise" while already visible, or a "set" while already invisible,
        # is a numerically-adjacent duplicate crossing at a window boundary —
        # ignored rather than double-counted.
    if currently_visible and window_start is not None:
        windows.append(ObservationWindow(rise_time=window_start, set_time=end))

    return windows


def angular_separation_deg(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    """Great-circle angular separation between two equatorial coordinates —
    the standard spherical law of cosines. Used only for telescope slew-time
    estimation; not part of the visibility
    calculation itself."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.degrees(math.acos(cos_sep))


def is_visible_for(windows: List[ObservationWindow], start_time: int, duration: int) -> bool:
    """Interval-containment check ONLY — does not recompute trig. This is what
    the VISIBILITY constraint calls; it must read the same precomputed windows
    the simulation engine used to schedule TargetBecameVisible/Unavailable, so
    the two can never disagree."""
    return any(w.contains(start_time, duration) for w in windows)
