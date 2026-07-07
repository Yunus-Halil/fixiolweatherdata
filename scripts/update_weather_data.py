#!/usr/bin/env python3
"""Append recent NOAA SPC storm reports to the current-year data file.

Fetches the last DAYS_BACK days of SPC filtered storm reports (hail, wind,
tornado) from https://www.spc.noaa.gov/climo/reports/ and converts them to
the StormEvents-style JSON schema used by the `<year>data` files in this
repo (the format Fixiol's weather-service reads as "combined storm format").

Existing events are never modified; new reports are de-duplicated against
what is already in the file, so the script is safe to re-run any time.

Usage:
    python scripts/update_weather_data.py            # last 10 days
    DAYS_BACK=30 python scripts/update_weather_data.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

SPC_URL = "https://www.spc.noaa.gov/climo/reports/{ymd}_rpts_filtered_{kind}.csv"

# SPC report kind -> NOAA StormEvents EVENT_TYPE
KINDS = {
    "hail": "Hail",
    "wind": "Thunderstorm Wind",
    "torn": "Tornado",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

STATE_NAMES = {
    "AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS",
    "CA": "CALIFORNIA", "CO": "COLORADO", "CT": "CONNECTICUT",
    "DE": "DELAWARE", "DC": "DISTRICT OF COLUMBIA", "FL": "FLORIDA",
    "GA": "GEORGIA", "HI": "HAWAII", "ID": "IDAHO", "IL": "ILLINOIS",
    "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY",
    "LA": "LOUISIANA", "ME": "MAINE", "MD": "MARYLAND",
    "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA",
    "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA",
    "NE": "NEBRASKA", "NV": "NEVADA", "NH": "NEW HAMPSHIRE",
    "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK",
    "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA", "OH": "OHIO",
    "OK": "OKLAHOMA", "OR": "OREGON", "PA": "PENNSYLVANIA",
    "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA",
    "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT",
    "VA": "VIRGINIA", "WA": "WASHINGTON", "WV": "WEST VIRGINIA",
    "WI": "WISCONSIN", "WY": "WYOMING", "PR": "PUERTO RICO",
    "VI": "VIRGIN ISLANDS", "GU": "GUAM", "AS": "AMERICAN SAMOA",
}


def fetch_csv(url):
    """Return the CSV text, or None if the file does not exist yet."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "fixiolweatherdata-updater/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def dedup_key(event):
    """Identity of a report, independent of the synthetic EVENT_ID."""
    try:
        lat = round(float(event.get("BEGIN_LAT")), 2)
        lon = round(float(event.get("BEGIN_LON")), 2)
    except (TypeError, ValueError):
        lat = lon = None
    return (
        event.get("BEGIN_YEARMONTH"),
        event.get("BEGIN_DAY"),
        event.get("BEGIN_TIME"),
        event.get("EVENT_TYPE"),
        lat,
        lon,
    )


def parse_reports(text, kind, convective_day):
    """Parse one SPC filtered-report CSV into StormEvents-style dicts.

    SPC comments are unquoted and may contain commas, so the line is split
    a fixed number of times and the remainder is treated as the comment.
    """
    events = []
    lines = text.strip().splitlines()
    for line in lines[1:]:  # skip the header row
        parts = line.split(",", 7)
        if len(parts) < 7:
            continue
        time_str, magnitude_str, location, county, state_abbr, lat_str, lon_str = (
            p.strip() for p in parts[:7]
        )
        try:
            begin_time = int(time_str)
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            continue

        # SPC files cover the 1200Z-1159Z convective day: times before
        # 1200Z happened on the calendar day AFTER the file's date.
        actual = (
            convective_day + timedelta(days=1)
            if begin_time < 1200
            else convective_day
        )

        magnitude = None
        magnitude_type = None
        if kind == "hail":
            # SPC hail size is in hundredths of an inch (100 = 1.00"),
            # same convention as NOAA StormEvents MAGNITUDE
            try:
                magnitude = float(magnitude_str)
            except ValueError:
                pass
        elif kind == "wind":
            try:
                magnitude = float(magnitude_str)
                magnitude_type = "EG"
            except ValueError:
                pass  # "UNK" wind speed

        yearmonth = actual.year * 100 + actual.month
        begin_date_time = "{:02d}-{}-{:02d} {:02d}:{:02d}:00".format(
            actual.day,
            actual.strftime("%b").upper(),
            actual.year % 100,
            begin_time // 100,
            begin_time % 100,
        )

        events.append(
            {
                "BEGIN_YEARMONTH": yearmonth,
                "BEGIN_DAY": actual.day,
                "BEGIN_TIME": begin_time,
                "END_YEARMONTH": yearmonth,
                "END_DAY": actual.day,
                "END_TIME": None,
                "EPISODE_ID": None,
                "EVENT_ID": None,  # assigned after de-duplication
                "STATE": STATE_NAMES.get(state_abbr.upper(), state_abbr.upper()),
                "STATE_FIPS": None,
                "YEAR": actual.year,
                "MONTH_NAME": MONTH_NAMES[actual.month - 1],
                "EVENT_TYPE": KINDS[kind],
                "CZ_TYPE": "C",
                "CZ_FIPS": None,
                "CZ_NAME": county.upper(),
                "WFO": None,
                "BEGIN_DATE_TIME": begin_date_time,
                "CZ_TIMEZONE": None,
                "END_DATE_TIME": None,
                "INJURIES_DIRECT": 0,
                "INJURIES_INDIRECT": 0,
                "DEATHS_DIRECT": 0,
                "DEATHS_INDIRECT": 0,
                "DAMAGE_PROPERTY": None,
                "DAMAGE_CROPS": None,
                "SOURCE": "NOAA SPC",
                "MAGNITUDE": magnitude,
                "MAGNITUDE_TYPE": magnitude_type,
                "FLOOD_CAUSE": None,
                "CATEGORY": None,
                "TOR_F_SCALE": None,
                "TOR_LENGTH": None,
                "TOR_WIDTH": None,
                "TOR_OTHER_WFO": None,
                "TOR_OTHER_CZ_STATE": None,
                "TOR_OTHER_CZ_FIPS": None,
                "TOR_OTHER_CZ_NAME": None,
                "BEGIN_RANGE": None,
                "BEGIN_AZIMUTH": None,
                "BEGIN_LOCATION": location,
                "END_RANGE": None,
                "END_AZIMUTH": None,
                "END_LOCATION": location,
                "BEGIN_LAT": lat,
                "BEGIN_LON": lon,
                "END_LAT": lat,
                "END_LON": lon,
                "DATA_SOURCE": "SPC",
            }
        )
    return events


def main():
    days_back = int(os.environ.get("DAYS_BACK", "10"))
    today = date.today()

    # Collect new reports, grouped by the calendar year they belong to
    new_by_year = {}
    for offset in range(days_back, -1, -1):
        day = today - timedelta(days=offset)
        ymd = day.strftime("%y%m%d")
        for kind in KINDS:
            url = SPC_URL.format(ymd=ymd, kind=kind)
            text = fetch_csv(url)
            if text is None:
                print(f"  {url} -> not published yet, skipping")
                continue
            reports = parse_reports(text, kind, day)
            print(f"  {url} -> {len(reports)} reports")
            for event in reports:
                new_by_year.setdefault(event["YEAR"], []).append(event)

    for year, candidates in sorted(new_by_year.items()):
        filename = f"{year}data"
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                existing = json.load(f)
        else:
            existing = []

        seen = {dedup_key(e) for e in existing}
        next_id = 9_000_000
        for e in existing:
            try:
                next_id = max(next_id, int(e.get("EVENT_ID") or 0) + 1)
            except (TypeError, ValueError):
                pass

        added = 0
        for event in candidates:
            key = dedup_key(event)
            if key in seen:
                continue
            seen.add(key)
            event["EVENT_ID"] = next_id
            next_id += 1
            existing.append(event)
            added += 1

        if added == 0:
            print(f"{filename}: no new events (already up to date)")
            continue

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4)
        print(f"{filename}: added {added} new events ({len(existing)} total)")


if __name__ == "__main__":
    sys.exit(main())
