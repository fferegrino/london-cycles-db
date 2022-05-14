# -*- coding: utf-8 -*-
# %%
import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytz
import seaborn as sns

# %% [markdown]
# ## Gathering the data
#
# Transport for London (TfL) offers an API that one can query to know the status of the London Cycle Network. A while ago I got curious about how the usage varies across the city troughout the day, so I wrote a script that creates a snapshot of the status roughly every 15 minutes. The following is an example of what can be done with these snapshots.

# %% [markdown]
# ## Load all the data
#
# The data for the cycles stations is split by days; I can use a *glob* pattern to read all of them into a list only to concatenate them into a single dataframe afterwards:

# %% gist="read_frames.py" dataframe="initial_data.png"
frames = []
for csv_file in Path("data").glob("*.csv"):
    df = pd.read_csv(csv_file, parse_dates=["query_time"])
    frames.append(df)
all_data = pd.concat(frames)

all_data.sample(10, random_state=42)

# %% [markdown]
# As you can see, due to the data collection process, the times are not evenly distributed. The following lines do two things:
#
#  - Modifies the `query_time` column: The dataset dates are in UTC, but when read from using *pandas*, this information is not taken into account. With `dt.tz_localize("utc")`, I set UTC as the timezone, then with `dt.tz_convert("Europe/London")` I change them to the London timezone and with `dt.floor("15min")` I round (or floor) the times to the nearest 15 minute.
#  - Calculates the `proportion`, a value ranging from 0 to 1 that summarises how empty or full the bike station is

# %% gist="transform_dataframe.py" dataframe="rounded.png"
london_tz = pytz.timezone("Europe/London")

all_data["query_time"] = pd.to_datetime(
    all_data["query_time"].dt.tz_localize("utc").dt.tz_convert(london_tz).dt.floor("15min")
)
all_data["proportion"] = (all_data["docks"] - all_data["empty_docks"]) / all_data["docks"]

all_data.sample(10, random_state=42)

# %% [markdown]
# And with that, data is evenly spaced and I now have a single column that tells how empty is a station at that specific point in time.

# %% [markdown]
# ### Filter a specific timeframe
#
# This is entirely optional; for the time being, I'll restrict the animation to a week's worth of data. Keep in mind that the more data I include, the more time it will take the processing to be done.

# %% gist="select_timeframe.py"
beginning = datetime.datetime(2022, 5, 7, tzinfo=london_tz)
end = datetime.datetime(2022, 5, 14, tzinfo=london_tz)

if beginning and end:
    data_to_plot = all_data[(all_data["query_time"] >= beginning) & (all_data["query_time"] <= end)]
else:
    data_to_plot = all_data

# %% [markdown]
# ## Are there problems in the data?
#
# Since the way I get the data is somewhat unreliable, I want to perform a quick check to see what the data looks like. A group by `query_time` should reveal any missing data:

# %% gist="show_times.py" dataframe="show_missing_times.png"
data_to_plot.groupby("query_time").count().head(5)

# %% [markdown]
# And there it is, see the jumps between the first and second row? It goes from `01:15:00` to `01:45:00`, and from the second to the third row there is almost an hour of missing data!
#
# There is a way to fix this problem... or at least make it less bad.

# %% [markdown]
# ### Resampling
#
# I need to do a bit of resampling to get this to work as I want it to. Let's start small, with a single bike point.

# %% gist="select_single.py" dataframe="single_bikepoint.png"
bikepoint = data_to_plot[data_to_plot["place_id"] == "BikePoints_87"]
bikepoint_resampled = bikepoint.copy()
bikepoint.head()

# %% [markdown]
# In order to use *pandas*'s resampling utilities, I need to set a time index in our dataframe; in this case, `query_time` will be my time index:

# %% gist="set_index.py" dataframe="resampled.png"
bikepoint_resampled = bikepoint_resampled.set_index("query_time")
bikepoint_resampled.head()

# %% [markdown]
# Then I can use `.resample` passing on the value `"15min"` since I want 15-minute intervals. But what resample returns is still not what I am after, I need to specify what to do with the newly resampled times that do not have a value assigned to them, I can use `.median()` to achieve my goal:

# %% gist="resampled_to_15minutes.py" dataframe="resampled_to_15.png"
bikepoint_resampled = bikepoint_resampled.resample("15min").median()
bikepoint_resampled.head()

# %% [markdown]
# Now it is possible to see the gaps; in the previous dataframe, the second, fourth and fifth rows were missing, and now they appear but have no value; I will take care of that next with the `.interpolate` method for data frames.
#
# The `.interpolate` method allows us to specify how we want this interpolation to happen via the `method` argument, it defaults to `linear`, which is something I can work with for the purposes of this post, but if you have other requirements, make sure you use the proper method.

# %% gist="interpolated_data.py" dataframe="interpolated.png"
bikepoint_resampled = bikepoint_resampled.interpolate()
bikepoint_resampled.head()

# %% [markdown]
# Finally, we can reset the index to return our `query_time` to the dataframe columns:

# %% gist="reset_index.py" dataframe="reset_index.png"
bikepoint_resampled = bikepoint_resampled.reset_index()
bikepoint_resampled.head()


# %% [markdown]
# Did you notice it? We lost the bike point the dataframe refers to throughout all our transformations! Nothing to worry about since we know it is the `BikePoint_87`, but we need to be careful when applying these transformations to the whole dataset.

# %% [markdown]
# And to apply those transformations to the whole dataset, the only thing that came to my mind was to create a function that does everything we have been discussing so far:

# %% gist="interpolate_function.py"
def interpolate_bikepoint(dataframe):
    resampled = dataframe.copy()
    resampled = resampled.set_index("query_time")
    resampled = resampled.resample("15min").median()
    resampled = resampled.interpolate()
    return resampled.reset_index()


# %% [markdown]
# And apply it to subsets (one *bikepoint* per subset) of our big dataframe while keeping track of the corresponding *bikepoint*:

# %% gist="interpolate_point_by_point.py" dataframe="all_interpolated.png"
all_bikepoints = data_to_plot["place_id"].unique()

resampled_frames = []

for bikepoint in all_bikepoints:
    resampled = interpolate_bikepoint(data_to_plot[data_to_plot["place_id"] == bikepoint])
    resampled["place_id"] = bikepoint
    resampled_frames.append(resampled)

data_to_plot = pd.concat(resampled_frames)
data_to_plot.head()

# %% [markdown]
# We can check that there are no more gaps:

# %% gist="no_more_gaps.py" dataframe="gapless.png"
data_to_plot.groupby("query_time").count().head(5)

# %% [markdown]
# ## Making the plot geographically realistic
#
# Let's try to convey more information in the plots; since I have the feeling that bike usage has to do with daylight, let's create a function that gives us a colour palette that depends on the time of day.
#
# I discovered some neat packages in the process:
#
#  - [Astral](https://github.com/sffjunkie/astral) provides calculations of the sun and moon position. I will be using this to know when the sunrise and sunset are happening in London.
#  - [Colour](https://github.com/vaab/colour) to manipulate colours. I will be using this package to create nice transitions between different colours.
#
#  I will not spend too much time explaining the functions; please refer to the documentation, read the inline comments or reach out to me for further clarification.

# %% gist="sun_intervals.py"
from astral import LocationInfo
from astral.sun import sun


def get_sun_intervals(date):
    london = LocationInfo("London", "England", "Europe/London", 51.507351, -0.127758)
    sun_over_london = sun(london.observer, date=date)

    return [
        date,  # Need to add the beginning of the day
        sun_over_london["dawn"],
        sun_over_london["sunrise"],
        sun_over_london["noon"],
        sun_over_london["sunset"],
        sun_over_london["dusk"],
        date + datetime.timedelta(days=1),  # Need to add the beginning of the next day
    ]


# %% gist="get_colors_by_time.py"
import math

import pytz
from colour import Color

utc = pytz.timezone("UTC")


def get_colors_by_time(date):
    date = date.replace(minute=0, hour=0, second=0, microsecond=0, tzinfo=london_tz)
    sun_intervals = get_sun_intervals(date)

    # Calculate the time between sun positions in seconds
    minutes = [math.ceil((t2 - t1).seconds / 60) for t1, t2 in zip(sun_intervals[:-1], sun_intervals[1:])]

    # Change if you want a different colour palette
    darkness = Color("#5D5D5E")
    night = Color("#7f7f7f")
    mid = Color("#a2a2a2")
    noon = Color("#c7c7c7")

    # Create an array of colours going from darkness to noon to darkness,
    # taking into consideration the minutes it takes to go from one state to the other
    colors = []
    colors.extend(darkness.range_to(night, minutes[0]))
    colors.extend(night.range_to(mid, minutes[1]))
    colors.extend(mid.range_to(noon, minutes[2]))
    colors.extend(noon.range_to(mid, minutes[3]))
    colors.extend(mid.range_to(night, minutes[4]))
    colors.extend(night.range_to(darkness, minutes[5]))

    # Sample the array every 15 minutes to return a dictionary where the time is the key and the color is the value
    every_15_minutes = {date + datetime.timedelta(minutes=idx): colors[idx].hex for idx in range(0, 1441, 15)}
    return every_15_minutes


# %% [markdown]
# Together, the above functions allow me to get a colour gradient for a specific date. For example, to check today's gradient, we can do the following:

# %% gist="print_gradients.py"
today = datetime.datetime.today()

today_gradients = get_colors_by_time(today)

for idx, (date, colour) in enumerate(today_gradients.items()):
    if idx > 10:
        break
    print(date.strftime("%H:%M:%S") + " – " + colour)

# %% [markdown]
# If you want to visualize this transition a bit better, let's do some trick with *pandas* and *matplotlib*:

# %% gist="show_gradients.py" image="gradients.png"
winter_solstice = get_colors_by_time(datetime.datetime(2022, 12, 21))
summer_solstice = get_colors_by_time(datetime.datetime(2022, 6, 21))

winter_solstice = pd.DataFrame.from_dict(winter_solstice, orient="index")
summer_solstice = pd.DataFrame.from_dict(summer_solstice, orient="index")

fig, axes = plt.subplots(2, 1, figsize=(16, 4))

for ax, gradients in zip(axes, [winter_solstice, summer_solstice]):

    for date, colour in gradients.iterrows():
        ax.axvline(date, c=colour[0], linewidth=6)
    ax.set_xlim(
        (gradients.index.min() - datetime.timedelta(minutes=15), gradients.index.max() + datetime.timedelta(minutes=15))
    )
    ax.axis("off")

axes[0].set_title("Winter solstice gradient")
axes[1].set_title("Summer solstice gradient")
fig.tight_layout()

# %% [markdown]
# ## Plotting a (single) map
#
# I have discussed most of the following functions [in a previous post](https://dev.to/fferegrino/maps-with-geopandas-tweeting-from-a-lambda-81k) feel free to check them out. In this case, I will just describe briefly what they do.

# %% [markdown]
# #### Zooming in
#
# The function `prepare_axes` adjusts the "view" for the plot, centring it on the actual bicycle stations.

# %% gist="prepare_axes.py"
PADDING = 0.005


def prepare_axes(ax: plt.Axes, cycles_info: pd.DataFrame):
    min_y = cycles_info["lat"].min() - PADDING
    max_y = cycles_info["lat"].max() + PADDING
    min_x = cycles_info["lon"].min() - PADDING
    max_x = cycles_info["lon"].max() + PADDING
    ax.set_ylim((min_y, max_y))
    ax.set_xlim((min_x, max_x))
    ax.set_axis_off()
    return min_x, max_x, min_y, max_y


# %% [markdown]
# #### Custom legend
#
# The function `set_custom_legend` creates a nice legend for the plot, one where only three values are visible: *"Empty"*, *"Busy"* and *"Full"*.

# %% gist="prepare_axes_and_custom_legend.py"
from functools import partial

from matplotlib.colors import Colormap
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredText

legend_element_args = dict(
    marker="o",
    color="w",
    markeredgewidth=0.5,
    markeredgecolor="k",
)

legend_element = partial(Line2D, [0], [0], **legend_element_args)


def set_custom_legend(ax: plt.Axes, cmap: Colormap):
    # Set custom "Empty, Busy or Full" legend
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

    # Add credit for the image
    text = AnchoredText("u/fferegrino – Data from TFL", loc=4, prop={"size": 5}, frameon=True)
    ax.add_artist(text)


# %% [markdown]
# #### The actual map
#
# The function `plot_map` uses the previous two functions to actually plot the bike stations and the outline of the London boroughs.

# %% gist="plot_map.py"
import geopandas as gpd


def plot_map(ax, cycles_info, map_color):
    # Calculate & set map boundaries
    min_x, max_x, min_y, max_y = prepare_axes(ax, cycles_info)

    # Get external resources
    cmap = plt.get_cmap("OrRd")
    london_map = gpd.read_file("shapefiles/London_Borough_Excluding_MHW.shp").to_crs(epsg=4326)

    # Plot elements
    ax.fill_between([min_x, max_x], min_y, max_y, color="#9CC0F9")
    london_map.plot(ax=ax, linewidth=0.5, color=map_color, edgecolor="black")
    sns.scatterplot(
        y="lat", x="lon", hue="proportion", edgecolor="k", linewidth=0.4, palette=cmap, data=cycles_info, s=25, ax=ax
    )
    set_custom_legend(ax, cmap)


# %% [markdown]
# #### A clock?
#
# Aside from my whole "let's make day and night happen", I think it is good to provide people with a visual reference of the actual time of day.
#
# The following snippet adds a patch in the plot with the time of the day. I wanted to add a nice touch by using a custom font via *matplotlib*'s `font_manager`; you can see that there are some *hardcoded* values to position the patch, but aside from that, the rest is standard *matplotlib* code.

# %% gist="plot_clock.py"
import matplotlib.patches as patches
from matplotlib import font_manager as fm

roboto_mono = fm.FontProperties(fname="Roboto_Mono/RobotoMono-Italic-VariableFont_wght.ttf", size=30)


def plot_clock(axes, time_of_day):
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


# %% [markdown]
# It is possible to test the above functions by plotting the data for a specific time – to do so, I will create a couple of helper functions:

# %% gist="get_fig_and_ax.py"
def get_fig_and_ax():
    fig = plt.Figure(figsize=(6, 4), dpi=170, frameon=False)
    ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
    fig.add_axes(ax)

    return fig, ax


def show_figure(figure):
    dummy = plt.figure()
    new_manager = dummy.canvas.manager
    new_manager.canvas.figure = figure
    figure.set_canvas(new_manager.canvas)


# %% [markdown]
# For example, plotting the data corresponding to the 30th of April 2022 at 1:30 PM.

# %% gist="sow_figure_test.py" dataframe="single_date_figure.png" image="test_fig.png"
fig, ax = get_fig_and_ax()

date_to_plot = datetime.datetime(2022, 4, 30, 13, 30, tzinfo=utc)
temporary_data = all_data[all_data["query_time"] == date_to_plot]

plot_map(ax, temporary_data, "#F4F6F7")
plot_clock(ax, date_to_plot)

show_figure(fig)

# %% [markdown]
# ## Animation, finally!
#
# Animations with *matplotlib* are... weird.
#
# To begin with, since I want to animate a timelapse, one frame for each unique time available in my dataset, I will create an array named `times` with each unique time in my dataset; I am turning these times to datetimes and making sure all of them are UTC too:

# %% gist="times_array.py"
times = [pd.to_datetime(time).replace(tzinfo=london_tz) for time in sorted(data_to_plot["query_time"].unique())]

print(times[0], times[-1])


# %% [markdown]
# *matplotlib* animations work in terms of frames, meaning you have to draw the entire content of your plot for each frame.
#
# In this case, I created a function called `create_frame` that receives two parameters: a `step` which is an integer that specifies which frame I am drawing next, and `ax` that represents the axes I will be drawing on.
#
# The function does the following:
#
#  1. Clear the axes using `cla`; this is important or otherwise our animation will get messy
#  2. For each `step`, I am getting the corresponding date from the `times` array I created above.
#  3. Use `get_colors_by_time` to get the sunlight gradient for that day
#  4. Choose the right colour for the previously selected time
#  5. Plot the map
#  6. Add the clock to the map
#

# %% gist="create_frame.py"
def create_frame(step, ax):
    ax.cla()
    selected_time = times[step]
    cycles_info = data_to_plot[data_to_plot["query_time"] == selected_time]
    colors = get_colors_by_time(selected_time)
    color = colors[selected_time]

    plot_map(ax, cycles_info, color)

    plot_clock(ax, selected_time)


# %% [markdown]
# Quick test for the `create_frame` function:

# %% gist="test_create_frame.py" image="single_entry.png" image="test_fig.png"
fig, ax = get_fig_and_ax()

create_frame(50, ax)

show_figure(fig)

# %% [markdown]
# Great! It works. Then we can actually create the animation.
#
# Using an instance of `FuncAnimation` which receives:
#
#  - `fig`, the figure it is supposed to be drawing on
#  - `create_frame`, the function that does all the drawing
#  - `frames`, which specifies how many frames our animation has. In this case, I want as many frames as the length of the `times` array)
#  - `fargs`, a tuple of extra arguments to the `create_frame` function, I am passing the axes instance in here
#
# Lastly, I call `save` on the `animation` variable, render the animation into an *mp4* file, at 10 frames per second, as specified with the `fps` argument.

# %% gist="create_animation.py"
from matplotlib.animation import FuncAnimation

fig, ax = get_fig_and_ax()

animation = FuncAnimation(fig, create_frame, frames=len(times), fargs=(ax,))

animation.save("animation.mp4", fps=15)

# %% [markdown]
# If all went well, you should see a video playing below:

# %% gist="show_animation.py"
from IPython.display import Video

Video("animation.mp4")

# %% [markdown]
# ## Conclusion and resources
#
# In this post, I shared with you how to: resample time series data, use third-party packages to get information about the sun's position and to work with colours, and finally, how to create matplotlib animations.
#
# As always, the code for this post [is available here](https://github.com/fferegrino/london-cycles-db/blob/main/animate.ipynb) along with [the full repo](https://github.com/fferegrino/london-cycles-db), the dataset is not yet available in Kaggle, but it will be soon (in the meantime,  you can find it on the repositry). Questions? comments? I am open for discussion on Twitter [at @io_exception](https://twitter.com/io_exception).

# %%
