import csv
import re
from datetime import datetime
from pathlib import Path

from tfl.api import bike_point

execution_time = datetime.utcnow()

csv_file = Path("data", f"{execution_time.strftime('%Y-%m-%d')}.csv")


def get_number(additional_properties, key):
    [nb] = [prop.value for prop in additional_properties if prop.key == key]
    return int(nb)


def get_stations(all_bike_points):
    data = []
    for place in all_bike_points:
        bikes = get_number(place.additionalProperties, "NbBikes")
        empty_docks = get_number(place.additionalProperties, "NbEmptyDocks")
        docks = get_number(place.additionalProperties, "NbDocks")
        data.append((execution_time.isoformat(), place.id, place.lat, place.lon, bikes, empty_docks, docks,))

    return data


headers = ["query_time", "place_id", "lat", "lon", "bikes", "empty_docks", "docks"]


first_file_of_the_day = not csv_file.exists()
with open(csv_file, "a") as w:
    writer = csv.writer(w)
    if first_file_of_the_day:
        writer.writerow(headers)
    bike_points = bike_point.all()
    for station_row in get_stations(bike_points):
        writer.writerow(station_row)


if first_file_of_the_day:
    information_file = Path("data", f"stations-{execution_time.strftime('%Y-%m-%d')}.csv")
    # This is very inefficient, needs refactoring.
    dictionaries = []
    properties = set()
    pattern = re.compile(r"(?<!^)(?=[A-Z])")
    for bike_point in bike_points:
        props = {
            pattern.sub("_", prop.key).lower(): prop.value
            for prop in bike_point.additionalProperties
            if not prop.key.startswith("Nb")
        }
        station_dict = {"common_name": bike_point.commonName, "place_id": bike_point.id, **props}
        properties.update(station_dict.keys())
        dictionaries.append(station_dict)
    with open(information_file, "w") as w:
        writer = csv.DictWriter(w, fieldnames=list(set(properties)))
        writer.writeheader()
        for dd in dictionaries:
            writer.writerow(dd)
