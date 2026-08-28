import datetime
import math
import os
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Optional

import geopandas as gpd
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import pytz
import seaborn as sns
import typer
from astral import LocationInfo
from astral.sun import sun
from colour import Color
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError
from matplotlib import font_manager as fm
from matplotlib.animation import FuncAnimation
from matplotlib.colors import Colormap
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredText

DATASET = os.environ.get("HF_DATASET_REPO") or "feregrino/london-cycles"
VIZ_DIR = Path(__file__).parent
LONDON_TZ = pytz.timezone("Europe/London")
PADDING = 0.005

legend_element_args = dict(
    marker="o",
    color="w",
    markeredgewidth=0.5,
    markeredgecolor="k",
)
legend_element = partial(Line2D, [0], [0], **legend_element_args)

roboto_mono = fm.FontProperties(fname=VIZ_DIR / "Roboto_Mono" / "RobotoMono-Italic-VariableFont_wght.ttf", size=30)


def load_observations(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    """Download one file per day and stack them into a single dataframe."""
    token = os.environ.get("HF_TOKEN")
    api = HfApi(token=token)
    frames = []
    day = start
    while day <= end:
        try:
            path = hf_hub_download(
                DATASET,
                f"data/year={day:%Y}/month={day:%m}/day={day:%d}/part.csv",
                repo_type="dataset",
                token=token,
            )
            frames.append(pd.read_csv(path, parse_dates=["query_time"]))
        except EntryNotFoundError:
            prefix = f"data/year={day:%Y}/month={day:%m}/day={day:%d}/"
            try:
                day_files = sorted(f for f in api.list_repo_files(DATASET, repo_type="dataset") if f.startswith(prefix))
            except Exception:
                day_files = []
            if day_files:
                for f in day_files:
                    p = hf_hub_download(DATASET, f, repo_type="dataset", token=token)
                    frames.append(pd.read_csv(p, parse_dates=["query_time"]))
            else:
                print(f"Warning: No observation data found for {day:%Y-%m-%d}")
        day += datetime.timedelta(days=1)
    if not frames:
        return pd.DataFrame(columns=["query_time", "place_id", "bikes", "empty_docks", "docks"])
    return pd.concat(frames, ignore_index=True)


def add_station_attributes(observations: pd.DataFrame) -> pd.DataFrame:
    """Attach lat/lon by resolving the versioned station table.

    A plain merge on `place_id` alone would multiply rows for every station
    that has more than one version, so the interval condition is what keeps
    the row count unchanged.
    """
    token = os.environ.get("HF_TOKEN")
    stations = pd.read_csv(
        hf_hub_download(DATASET, "stations.csv", repo_type="dataset", token=token),
        parse_dates=["valid_from", "valid_to"],
    )
    merged = observations.merge(
        stations[["place_id", "lat", "lon", "valid_from", "valid_to"]],
        on="place_id",
        how="left",
    )
    observed_day = merged["query_time"].dt.normalize()
    is_current = (merged["valid_from"] <= observed_day) & (
        merged["valid_to"].isna() | (observed_day < merged["valid_to"])
    )
    return merged[is_current].drop(columns=["valid_from", "valid_to"]).reset_index(drop=True)


def interpolate_bikepoint(dataframe: pd.DataFrame, interval: str = "15min") -> pd.DataFrame:
    resampled = dataframe.copy()
    resampled = resampled.set_index("query_time")
    resampled = resampled.resample(interval).median(numeric_only=True)
    resampled = resampled.interpolate()
    return resampled.reset_index()


def prepare_dataset(
    start_date: datetime.date, end_date: datetime.date, interval: str = "15min"
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    observations = load_observations(start_date, end_date)
    all_data = add_station_attributes(observations)

    all_data["query_time"] = pd.to_datetime(
        all_data["query_time"].dt.tz_localize("utc").dt.tz_convert(LONDON_TZ).dt.floor(interval)
    )
    all_data["proportion"] = (all_data["docks"] - all_data["empty_docks"]) / all_data["docks"]

    beginning = LONDON_TZ.localize(datetime.datetime.combine(start_date, datetime.time.min))
    end = LONDON_TZ.localize(datetime.datetime.combine(end_date, datetime.time.max))

    data_to_plot = all_data[(all_data["query_time"] >= beginning) & (all_data["query_time"] <= end)]

    all_bikepoints = data_to_plot["place_id"].unique()
    resampled_frames = []
    for bikepoint in all_bikepoints:
        resampled = interpolate_bikepoint(data_to_plot[data_to_plot["place_id"] == bikepoint], interval=interval)
        resampled["place_id"] = bikepoint
        resampled_frames.append(resampled)

    interpolated_data = pd.concat(resampled_frames, ignore_index=True)
    times = [pd.to_datetime(t) for t in sorted(interpolated_data["query_time"].unique())]
    return interpolated_data, times


def get_sun_intervals(date: datetime.datetime):
    london = LocationInfo("London", "England", "Europe/London", 51.507351, -0.127758)
    sun_over_london = sun(
        london.observer,
        date=date.date() if isinstance(date, (datetime.date, datetime.datetime)) else date,
        tzinfo=LONDON_TZ,
    )

    return [
        date,
        sun_over_london["dawn"],
        sun_over_london["sunrise"],
        sun_over_london["noon"],
        sun_over_london["sunset"],
        sun_over_london["dusk"],
        date + datetime.timedelta(days=1),
    ]


def get_colors_by_time(date: datetime.datetime):
    if hasattr(date, "tzinfo") and date.tzinfo is not None:
        date = date.replace(minute=0, hour=0, second=0, microsecond=0)
    else:
        date = LONDON_TZ.localize(date.replace(minute=0, hour=0, second=0, microsecond=0))
    sun_intervals = get_sun_intervals(date)

    minutes = [math.ceil((t2 - t1).total_seconds() / 60) for t1, t2 in zip(sun_intervals[:-1], sun_intervals[1:])]

    darkness = Color("#5D5D5E")
    night = Color("#7f7f7f")
    mid = Color("#a2a2a2")
    noon = Color("#c7c7c7")

    colors = []
    colors.extend(darkness.range_to(night, minutes[0]))
    colors.extend(night.range_to(mid, minutes[1]))
    colors.extend(mid.range_to(noon, minutes[2]))
    colors.extend(noon.range_to(mid, minutes[3]))
    colors.extend(mid.range_to(night, minutes[4]))
    colors.extend(night.range_to(darkness, minutes[5]))

    every_15_minutes = {date + datetime.timedelta(minutes=idx): colors[idx].hex for idx in range(0, 1441, 15)}
    return every_15_minutes


def prepare_axes(ax: plt.Axes, cycles_info: pd.DataFrame):
    min_y = cycles_info["lat"].min() - PADDING
    max_y = cycles_info["lat"].max() + PADDING
    min_x = cycles_info["lon"].min() - PADDING
    max_x = cycles_info["lon"].max() + PADDING
    ax.set_ylim((min_y, max_y))
    ax.set_xlim((min_x, max_x))
    ax.set_axis_off()
    return min_x, max_x, min_y, max_y


def set_custom_legend(ax: plt.Axes, cmap: Colormap):
    values = [(0.0, "Empty"), (0.5, "Busy"), (1.0, "Full")]
    legend_elements = []
    for gradient, label in values:
        color = cmap(gradient)
        legend_elements.append(
            legend_element(
                label=label,
                markerfacecolor=color,
            )
        )
    ax.legend(handles=legend_elements, loc="upper left", prop={"size": 6}, ncol=len(values))

    text = AnchoredText("u/fferegrino – Data from TFL", loc=4, prop={"size": 5}, frameon=True)
    ax.add_artist(text)


def plot_map(ax: plt.Axes, cycles_info: pd.DataFrame, map_color: str, london_map: gpd.GeoDataFrame):
    min_x, max_x, min_y, max_y = prepare_axes(ax, cycles_info)
    cmap = plt.get_cmap("OrRd")

    ax.fill_between([min_x, max_x], min_y, max_y, color="#9CC0F9")
    london_map.plot(ax=ax, linewidth=0.5, color=map_color, edgecolor="black")
    sns.scatterplot(
        y="lat", x="lon", hue="proportion", edgecolor="k", linewidth=0.4, palette=cmap, data=cycles_info, s=25, ax=ax
    )
    set_custom_legend(ax, cmap)


def plot_clock(axes: plt.Axes, time_of_day: datetime.datetime):
    text_year = time_of_day.strftime("%A, %d %B").upper()
    text_time = time_of_day.strftime("%H:%M")
    clock_center = (-0.063368, 51.4845)
    width = 0.04 / 2
    height = 0.011 / 2
    rect = patches.Rectangle(
        (clock_center[0] - width, clock_center[1] - height),
        width * 2,
        height * 2,
        linewidth=0.5,
        edgecolor="k",
        facecolor="#F4F6F7",
    )
    axes.add_patch(rect)
    axes.text(clock_center[0], clock_center[1] + 0.0025, text_year, fontsize=6, ha="center", fontproperties=roboto_mono)
    axes.text(clock_center[0], clock_center[1] - 0.004, text_time, fontsize=20, ha="center", fontproperties=roboto_mono)


def get_fig_and_ax(dpi: int = 100):
    fig = plt.Figure(figsize=(6, 4), dpi=dpi, frameon=False)
    ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
    fig.add_axes(ax)
    return fig, ax


def render_animation(
    data_to_plot: pd.DataFrame,
    times: list[pd.Timestamp],
    output_path: Path,
    day_night: bool = True,
    fps: int = 15,
    dpi: int = 100,
):
    fig, ax = get_fig_and_ax(dpi=dpi)
    london_map = gpd.read_file(VIZ_DIR / "shapefiles" / "London_Borough_Excluding_MHW.shp").to_crs(epsg=4326)

    cached_colors: dict[datetime.date, dict[datetime.datetime, str]] = {}

    def create_frame(step):
        ax.cla()
        selected_time = times[step]
        cycles_info = data_to_plot[data_to_plot["query_time"] == selected_time]

        if day_night:
            day_key = selected_time.date()
            if day_key not in cached_colors:
                cached_colors[day_key] = get_colors_by_time(selected_time)
            color = cached_colors[day_key].get(selected_time, "#F4F6F7")
        else:
            color = "#F4F6F7"

        plot_map(ax, cycles_info, color, london_map)
        plot_clock(ax, selected_time)

    animation = FuncAnimation(fig, create_frame, frames=len(times))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".gif":
        animation.save(str(output_path), writer="pillow", fps=fps, dpi=dpi)
    else:
        animation.save(str(output_path), fps=fps, dpi=dpi)


def upload_to_imagekit(
    file_path: Path,
    file_name: Optional[str] = None,
    folder: str = "/projects/london-cycles-db",
    private_key: Optional[str] = None,
    public_key: Optional[str] = None,
) -> None:
    from imagekitio import ImageKit

    key = private_key or os.environ.get("IMAGEKIT_PRIVATE_KEY")
    pub_key = public_key or os.environ.get("IMAGEKIT_PUBLIC_KEY")
    if not key:
        raise ValueError(
            "ImageKit private key not provided. Set IMAGEKIT_PRIVATE_KEY environment variable or pass --imagekit-private-key."
        )

    ik = ImageKit(private_key=key)
    target_name = file_name or file_path.name
    normalized_folder = f"/{folder.strip('/')}" if folder else "/"

    print(f"Uploading {file_path} to ImageKit as {target_name} in folder '{normalized_folder}'...")

    upload_kwargs = {
        "file": file_path.read_bytes(),
        "file_name": target_name,
        "folder": normalized_folder,
        "use_unique_file_name": False,
        "overwrite_file": True,
    }
    if pub_key:
        upload_kwargs["public_key"] = pub_key

    upload_response = ik.files.upload(**upload_kwargs)
    file_url = getattr(upload_response, "url", None)
    if file_url:
        print(f"Uploaded successfully to ImageKit: {file_url}")
    else:
        print(f"Uploaded successfully to ImageKit: {upload_response}")


class OutputFormat(str, Enum):
    mp4 = "mp4"
    gif = "gif"


app = typer.Typer(help="Animate London cycle network usage over time.")


@app.command()
def main(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Path to save the output animation file. Defaults to animation.<format>.",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.mp4,
        "--format",
        "-f",
        help="Animation format: mp4 or gif.",
    ),
    end_date: Optional[datetime.datetime] = typer.Option(
        None,
        "--end-date",
        "-e",
        formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"],
        help="End date (YYYY-MM-DD). Defaults to yesterday.",
    ),
    start_date: Optional[datetime.datetime] = typer.Option(
        None,
        "--start-date",
        "-s",
        formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"],
        help="Start date (YYYY-MM-DD). Defaults to end date minus 7 days.",
    ),
    day_night: bool = typer.Option(
        True,
        "--day-night/--no-day-night",
        help="Whether to animate the background colour based on day/night sunlight in London.",
    ),
    fps: int = typer.Option(
        10,
        "--fps",
        help="Frames per second for the output animation.",
    ),
    interval: str = typer.Option(
        "1h",
        "--interval",
        "-i",
        help="Time resampling interval (e.g. 15min, 30min, 1h).",
    ),
    dpi: int = typer.Option(
        100,
        "--dpi",
        help="DPI resolution for the animation output.",
    ),
    upload_imagekit: bool = typer.Option(
        False,
        "--upload-imagekit",
        help="Upload the generated animation to ImageKit.",
    ),
    imagekit_folder: str = typer.Option(
        "/projects/london-cycles-db",
        "--imagekit-folder",
        help="Folder in ImageKit to upload the file to.",
    ),
    imagekit_file_name: Optional[str] = typer.Option(
        None,
        "--imagekit-file-name",
        help="File name in ImageKit. Defaults to the output file name.",
    ),
):
    if end_date is None:
        end_d = datetime.date.today() - datetime.timedelta(days=1)
    else:
        end_d = end_date.date()

    if start_date is None:
        start_d = end_d - datetime.timedelta(days=7)
    else:
        start_d = start_date.date()

    if output is None:
        output_path = Path(f"animation.{format.value}")
    else:
        output_path = output
        if output_path.suffix.lower() not in [".mp4", ".gif"]:
            output_path = output_path.with_suffix(f".{format.value}")

    print(f"Loading data from {start_d} to {end_d}...")
    data_to_plot, times = prepare_dataset(start_d, end_d, interval=interval)

    if not times:
        typer.echo("No observation data found for the given date range.", err=True)
        raise typer.Exit(code=1)

    print(f"Rendering {len(times)} frames to {output_path} (day_night={day_night}, fps={fps}, dpi={dpi})...")
    render_animation(
        data_to_plot=data_to_plot,
        times=times,
        output_path=output_path,
        day_night=day_night,
        fps=fps,
        dpi=dpi,
    )
    print(f"Animation saved to {output_path}")

    if upload_imagekit:
        upload_to_imagekit(
            file_path=output_path,
            file_name=imagekit_file_name,
            folder=imagekit_folder,
        )


if __name__ == "__main__":
    app()
