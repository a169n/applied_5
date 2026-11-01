"""SNR sweep figure for the practical report. Usage: make_figure.py <snr_sweep.csv> <out.png>"""

import csv
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BLUE, INK, GRID = "#2a78d6", "#3b3b38", "#e4e3df"
PANELS = [
    ("recall", "Recall", None, "linear"),
    ("loc_err_km", "Location error (km)", "loc_err_km", "log"),
]


def main(src: str, out: str) -> None:
    with open(src) as f:
        rows = list(csv.DictReader(f))
    snr = [float(r["snr"]) for r in rows]
    plt.rcParams.update({"font.size": 8, "text.color": INK, "axes.labelcolor": INK})
    fig, axes = plt.subplots(1, 2, figsize=(4.4, 2.0), layout="constrained")
    for ax, (col, title, label_col, yscale) in zip(axes, PANELS, strict=True):
        y = [float(r[col]) for r in rows]
        ax.plot(snr, y, color=BLUE, lw=2, marker="o", ms=5, mec="white", mew=1)
        ax.set(xlabel="SNR", yscale=yscale)
        ax.set_title(title, fontsize=8, loc="left")
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.tick_params(colors=INK, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        if label_col:  # label the ends only: the range is the point
            ax.annotate(f"{y[0]:.2f} km", (snr[0], y[0]), xytext=(6, 0), textcoords="offset points")
            ax.annotate(
                f"{y[-1]:.2f} km",
                (snr[-1], y[-1]),
                xytext=(-8, 7),
                textcoords="offset points",
                ha="right",
            )
    fig.savefig(out, dpi=300)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
