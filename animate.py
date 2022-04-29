# -*- coding: utf-8 -*-
# +
import csv
from pathlib import Path
import pandas as pd
import numpy as np
import datetime

from typing import Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.colors import Colormap
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredText
from matplotlib.animation import FuncAnimation
from astral.sun import sun
from astral import LocationInfo
import pytz

utc = pytz.timezone('UTC')


# -

def get_sun_times(date):
    
    tz = pytz.timezone('Europe/London')
    london = LocationInfo("London", "England", "Europe/London", 51.507351, -0.127758)
    sun_over_london = sun(london.observer, date=date)
    date = date.replace(tzinfo=utc)
    
    return {
        (date, sun_over_london["dawn"]) : "#8B8B8D", # night
        (sun_over_london["dawn"], sun_over_london["sunrise"]) : "#D1D2D3", # sunrise
        (sun_over_london["sunrise"], sun_over_london["sunset"]) : "#F4F6F7", # daylight
        (sun_over_london["sunset"],sun_over_london["dusk"]) : "#D1D2D3", # sunset
        (sun_over_london["dusk"], date + datetime.timedelta(days=1)) : "#8B8B8D", # night
    }



PADDING = 0.005

data = Path("data")

frames = []
for csv_file in data.glob("*.csv"):
    datum = pd.read_csv(csv_file, parse_dates=["query_time"])
    frames.append(datum)

datum = pd.concat(frames)

datum['query_time'] = pd.to_datetime(datum['query_time'].dt.floor('15min'))
datum["proportion"] = (datum["docks"] - datum["empty_docks"]) / datum["docks"]


def show_figure(fig):

    # create a dummy figure and use its
    # manager to display "fig"  
    dummy = plt.figure()
    new_manager = dummy.canvas.manager
    new_manager.canvas.figure = fig
    fig.set_canvas(new_manager.canvas)


times = sorted(datum['query_time'].unique())


# +
def prepare_axes(ax: plt.Axes, cycles_info: pd.DataFrame) -> Tuple[float, float, float, float]:
    min_y = cycles_info["lat"].min() - PADDING
    max_y = cycles_info["lat"].max() + PADDING
    min_x = cycles_info["lon"].min() - PADDING
    max_x = cycles_info["lon"].max() + PADDING
    ax.set_ylim((min_y, max_y))
    ax.set_xlim((min_x, max_x))
    ax.set_axis_off()
    return min_x, max_x, min_y, max_y



def set_custom_legend(ax: plt.Axes, cmap: Colormap) -> None:
    values = [(0.0, "Empty"), (0.5, "Busy"), (1.0, "Full")]
    legend_elements = []
    for gradient, label in values:
        color = cmap(gradient)
        legend_elements.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                label=label,
                markerfacecolor=color,
                markeredgewidth=0.5,
                markeredgecolor="k",
            )
        )
    ax.legend(handles=legend_elements, loc="upper left", prop={"size": 6}, ncol=len(values))


# -

def create_frame(step, ax):
    ax.cla()
    time = times[step]
    time_dt = pd.to_datetime(time).replace(tzinfo=utc)
    cycles_info = datum[datum['query_time'] == time]
    london_map = gpd.read_file("shapefiles/London_Borough_Excluding_MHW.shp").to_crs(epsg=4326)
    
    map_color = get_sun_times(date=time_dt.replace(minute=0, hour=0))
    # [color] = [value for key, value in map_color.items() if key[0] < time_dt < key[1]]

    
    min_x, max_x, min_y, max_y = prepare_axes(ax, cycles_info)
    cmap = plt.get_cmap("OrRd")
    ax.fill_between([min_x, max_x], min_y, max_y, color="#9CC0F9")
        
    london_map.plot(ax=ax, linewidth=0.5, color="#F4F6F7", edgecolor="black")
    sns.scatterplot(
        y="lat", x="lon", hue="proportion", edgecolor="k", linewidth=0.1,palette=cmap, data=cycles_info, s=25, ax=ax
    )
    
    text_year = time_dt.strftime("%Y/%m/%d")
    text_time = time_dt.strftime("%H:%M")
    
    ax.text(-0.063368, 51.477, text_year, fontsize=9, ha="center")
    ax.text(-0.063368, 51.470, text_time, fontsize=20, ha="center")
    
    text = AnchoredText("u/fferegrino – Data from TFL", loc=4, prop={"size": 5}, frameon=True)
    ax.add_artist(text)
    
    set_custom_legend(ax, cmap)

# +
fig = plt.Figure(figsize=(6, 4), dpi=200, frameon=False)
ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
fig.add_axes(ax)

animation = FuncAnimation(fig, create_frame, frames=len(times), fargs=(ax,))

# +
# times[:]

# +
from IPython.display import HTML

animation.save('animation.mp4', writer='ffmpeg', fps=10);
# HTML(animation.to_jshtml())
# -


