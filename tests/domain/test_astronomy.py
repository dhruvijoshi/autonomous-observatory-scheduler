"""Tests for backend/domain/astronomy.py.

Astropy is used ONLY in test_altitude_matches_astropy_reference, as a one-time
correctness oracle. It is never imported by runtime code.
"""
import pytest

from backend.domain.astronomy import (
    altitude_deg,
    azimuth_deg,
    compute_observation_windows,
    is_visible_for,
    local_sidereal_time_deg,
)
from backend.domain.entities import ObservationTarget, Observatory


def make_observatory(lat=40.0, lon=-105.0, elev=1655.0, min_alt=30.0):
    return Observatory(
        id="obs1",
        name="Test Site",
        latitude=lat,
        longitude=lon,
        elevation=elev,
        default_minimum_altitude=min_alt,
        telescope_slew_rate_deg_per_sec=2.0,
    )


# --- goal 2: RA/Dec -> altitude calculation, cross-checked against Astropy --


def test_altitude_matches_astropy_reference():
    astropy = pytest.importorskip("astropy")  # test-time-only dependency
    from astropy.time import Time
    from astropy.coordinates import EarthLocation, SkyCoord, AltAz
    import astropy.units as u

    lat, lon, elev = 40.0, -105.0, 1655.0
    ra, dec = 100.0, 20.0

    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)
    t = Time("2024-06-15T05:00:00", scale="utc")
    lst = t.sidereal_time("mean", longitude=lon * u.deg).deg

    ours = altitude_deg(ra, dec, lat, lst)

    target = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    # AltAz with no `pressure` set applies no refraction, matching our model.
    altaz = target.transform_to(AltAz(obstime=t, location=location))
    theirs = altaz.alt.deg

    # Generous tolerance: our model deliberately excludes precession/nutation/
    # aberration, which Astropy's
    # full ICRS->AltAz transform includes and can differ by a few tenths of a
    # degree from a 2024 date vs. the J2000-ish coordinates given here. A
    # genuine formula bug (wrong trig identity, sign error, deg/rad mixup)
    # would be off by tens of degrees, not a fraction of one.
    assert ours == pytest.approx(theirs, abs=1.0)


def test_altitude_known_cases():
    # Target at zenith: dec == latitude, H == 0 -> altitude == 90.
    assert altitude_deg(ra_deg=0.0, dec_deg=40.0, latitude_deg=40.0, lst_deg=0.0) == pytest.approx(90.0, abs=1e-9)

    # Target on the celestial equator, observed from the equator, at transit -> altitude == 90.
    assert altitude_deg(ra_deg=0.0, dec_deg=0.0, latitude_deg=0.0, lst_deg=0.0) == pytest.approx(90.0, abs=1e-9)

    # Target exactly at the opposite hour angle from transit (H=180) for an
    # equatorial target seen from the equator -> altitude == -90 (nadir).
    assert altitude_deg(ra_deg=0.0, dec_deg=0.0, latitude_deg=0.0, lst_deg=180.0) == pytest.approx(-90.0, abs=1e-9)


def test_azimuth_is_bounded_and_defined():
    az = azimuth_deg(ra_deg=100.0, dec_deg=20.0, latitude_deg=40.0, lst_deg=150.0)
    assert 0.0 <= az < 360.0


def test_local_sidereal_time_advances_at_sidereal_rate_and_wraps():
    lst0 = local_sidereal_time_deg(starting_lst=350.0, sim_time=0)
    assert lst0 == pytest.approx(350.0)
    # After one full sidereal period (~1436.07 min) LST should return to start.
    from backend.domain.astronomy import SIDEREAL_PERIOD_MIN

    lst_after_period = local_sidereal_time_deg(starting_lst=350.0, sim_time=SIDEREAL_PERIOD_MIN)
    assert lst_after_period == pytest.approx(350.0, abs=1e-6)
    # It should wrap into [0, 360).
    lst_wrapped = local_sidereal_time_deg(starting_lst=350.0, sim_time=100)
    assert 0.0 <= lst_wrapped < 360.0


# --- goal 4: never-visible target -------------------------------------------


def test_never_visible_target():
    observatory = make_observatory(lat=60.0, min_alt=30.0)
    # Max possible altitude = 90 - |lat - dec| = 90 - |60 - (-60)| = -30 < 30.
    target = ObservationTarget(id="t1", name="Far South", ra=0.0, dec=-60.0)
    windows = compute_observation_windows(target, observatory, night_window=(0, 480), starting_lst=0.0)
    assert windows == []
    assert not is_visible_for(windows, start_time=0, duration=30)


# --- goal 5: always-visible target -------------------------------------------


def test_always_visible_target():
    observatory = make_observatory(lat=70.0, min_alt=20.0)
    # Lower-culmination altitude = dec + lat - 90 = 85 + 70 - 90 = 65 >= 20.
    target = ObservationTarget(id="t2", name="Near Pole", ra=0.0, dec=85.0)
    night_window = (0, 480)
    windows = compute_observation_windows(target, observatory, night_window=night_window, starting_lst=0.0)
    assert windows == [pytest.approx(night_window)] or (
        len(windows) == 1 and windows[0].rise_time == night_window[0] and windows[0].set_time == night_window[1]
    )
    assert is_visible_for(windows, start_time=0, duration=480)
    assert is_visible_for(windows, start_time=200, duration=100)


# --- goal 6: normal rise/set case -------------------------------------------


def test_normal_rise_and_set_within_night_window():
    observatory = make_observatory(lat=40.0, min_alt=30.0)
    # Max altitude at transit = 90 - |40-0| = 50 > 30 (visible sometime).
    # Lower-culmination altitude = 0 + 40 - 90 = -50 < 30 (not always visible).
    ra = 180.0
    target = ObservationTarget(id="t3", name="Normal", ra=ra, dec=0.0)
    night_window = (0, 480)

    # Choose starting_lst so meridian transit (H=0) falls at t=240, i.e.
    # squarely inside the window, giving a clean single rise-then-set arc.
    from backend.domain.astronomy import SIDEREAL_RATE_DEG_PER_MIN

    starting_lst = ra - 240 * SIDEREAL_RATE_DEG_PER_MIN

    windows = compute_observation_windows(target, observatory, night_window, starting_lst)

    assert len(windows) == 1
    window = windows[0]
    assert night_window[0] < window.rise_time < 240 < window.set_time < night_window[1]

    # Monotonicity / boundary correctness: just inside the window -> visible;
    # just outside -> not visible.
    assert is_visible_for(windows, window.rise_time + 1, 1)
    assert is_visible_for(windows, window.set_time - 1, 1)
    assert not is_visible_for(windows, window.rise_time - 5, 1)
    assert not is_visible_for(windows, window.set_time + 5, 1)

    # The full exposure-duration question: fits entirely inside the window.
    assert is_visible_for(windows, 235, 10)
    # Does not fit: starts inside but would run past set_time.
    assert not is_visible_for(windows, window.set_time - 2, 10)
