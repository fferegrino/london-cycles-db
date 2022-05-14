import csv
from datetime import datetime
from pathlib import Path

from tfl.api import bike_point

execution_time = datetime.utcnow()

csv_file = Path("data", f"{execution_time.strftime('%Y-%m-%d')}.csv")


def get_number(additional_properties, key):
    [nb] = [prop.value for prop in additional_properties if prop.key == key]
    return int(nb)


def get_stations():
    all_bike_points = bike_point.all()
    data = []

    for place in all_bike_points:
        bikes = get_number(place.additionalProperties, "NbBikes")
        empty_docks = get_number(place.additionalProperties, "NbEmptyDocks")
        docks = get_number(place.additionalProperties, "NbDocks")
        data.append(
            (
                execution_time.isoformat(),
                place.id,
                place.lat,
                place.lon,
                bikes,
                empty_docks,
                docks,
            )
        )

    return data


headers = ["query_time", "place_id", "lat", "lon", "bikes", "empty_docks", "docks"]


write_headers = not csv_file.exists()
with open(csv_file, "a") as w:
    writer = csv.writer(w)
    if write_headers:
        writer.writerow(headers)

    for station_row in get_stations():
        writer.writerow(station_row)
