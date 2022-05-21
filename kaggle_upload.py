import json
import os
from datetime import date
from glob import glob

from kaggle import api

schema_fields = [
    ("query_time", "Estimated time of when the data was queried", "datetime"),
    ("place_id", "A string identifier of the station", "string"),
    ("lat", "Latitude of the station", "number"),
    ("lon", "Longitude of the station", "number"),
    ("bikes", "Number of bikes at the station", "number"),
    ("empty_docks", "Number of empty docks at the station", "number"),
    ("docks", "Number of total docks at the station", "number"),
]

with open("dataset-metadata.json") as r:
    dataset_metadata = json.load(r)


resources = []
dates = []

today = date.today()


for file in sorted(glob("data/*.csv")):
    date_parts = file[5:-4].split("-")
    if len(date_parts) == 4:
        print("Skipping stations info")
        continue

    date_parts = [int(part) for part in date_parts]
    file_date = date(*date_parts)

    if file_date >= today:
        print(f"Skipping {file}")
        os.remove(file)
        continue

    dates.append(file_date)

    schema = []
    for name, description, _type in schema_fields:
        schema.append({"name": name, "description": description, "type": _type})
    resource = {
        "path": file[5:],
        "description": f"Station data for the {file_date.strftime('%B %d %Y')}",
        "schema": {"fields": schema},
    }
    resources.append(resource)

dataset_metadata["resources"] = resources

with open("data/dataset-metadata.json", "w") as w:
    json.dump(dataset_metadata, w, indent=4)

update_message = f"Data from {min(dates)} to {max(dates)}"

api.dataset_create_version("data", update_message, dir_mode="zip", quiet=False)
