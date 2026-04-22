"""Data Science component — appointment analytics using NumPy, Matplotlib, Seaborn."""

from __future__ import annotations

import io
import base64
from datetime import date, timedelta
from typing import Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend (no display required)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import pandas as pd


sns.set_theme(style="whitegrid", palette="muted")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _appointments_to_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["doctor_id", "doctor_name", "start_time", "date", "status"])
    df = pd.DataFrame(records)
    if "start_time" in df.columns:
        df["hour"] = pd.to_datetime(df["start_time"], format="%H:%M:%S", errors="coerce").dt.hour
    return df


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Analysis functions (NumPy)
# ---------------------------------------------------------------------------

def analyze_busiest_doctor(records: list[dict]) -> dict:
    """Return the doctor with the most appointments and booking stats."""
    df = _appointments_to_df(records)
    if df.empty or "doctor_id" not in df.columns:
        return {"busiest_doctor_id": None, "busiest_doctor_name": None, "appointment_count": 0}

    counts = df.groupby("doctor_id").size().reset_index(name="count")
    counts_arr = counts["count"].to_numpy()

    busiest_idx = int(np.argmax(counts_arr))
    busiest_row = counts.iloc[busiest_idx]

    doctor_name = None
    if "doctor_name" in df.columns:
        match = df[df["doctor_id"] == busiest_row["doctor_id"]]["doctor_name"]
        doctor_name = match.iloc[0] if not match.empty else None

    return {
        "busiest_doctor_id": busiest_row["doctor_id"],
        "busiest_doctor_name": doctor_name,
        "appointment_count": int(busiest_row["count"]),
        "mean_appointments_per_doctor": float(np.mean(counts_arr)),
        "std_appointments_per_doctor": float(np.std(counts_arr)),
    }


def predict_peak_hours(records: list[dict]) -> dict:
    """Predict peak booking hours using NumPy histogram analysis."""
    df = _appointments_to_df(records)
    if df.empty or "hour" not in df.columns:
        return {"peak_hour": None, "peak_hour_label": "N/A", "hour_distribution": {}}

    hours = df["hour"].dropna().to_numpy(dtype=int)
    if len(hours) == 0:
        return {"peak_hour": None, "peak_hour_label": "N/A", "hour_distribution": {}}

    counts, bin_edges = np.histogram(hours, bins=np.arange(8, 21))
    peak_idx = int(np.argmax(counts))
    peak_hour = int(bin_edges[peak_idx])

    distribution = {
        f"{int(bin_edges[i]):02d}:00": int(counts[i])
        for i in range(len(counts))
    }

    return {
        "peak_hour": peak_hour,
        "peak_hour_label": f"{peak_hour:02d}:00 – {peak_hour + 1:02d}:00",
        "hour_distribution": distribution,
    }


# ---------------------------------------------------------------------------
# Chart generators (Matplotlib + Seaborn)
# ---------------------------------------------------------------------------

def generate_appointments_by_hour_chart(records: list[dict]) -> str:
    """Bar chart of appointment counts by hour. Returns base64-encoded PNG."""
    df = _appointments_to_df(records)
    fig, ax = plt.subplots(figsize=(9, 4))

    if df.empty or "hour" not in df.columns or df["hour"].dropna().empty:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=13)
        ax.set_title("Appointments by Hour")
        return _fig_to_b64(fig)

    hour_counts = df.groupby("hour").size().reset_index(name="count")
    all_hours = pd.DataFrame({"hour": range(8, 20)})
    hour_counts = all_hours.merge(hour_counts, on="hour", how="left").fillna(0)
    hour_counts["count"] = hour_counts["count"].astype(int)

    peak_hour = int(hour_counts.loc[hour_counts["count"].idxmax(), "hour"])
    colors = ["#d86c5e" if h == peak_hour else "#1f7a78" for h in hour_counts["hour"]]

    sns.barplot(data=hour_counts, x="hour", y="count", palette=colors, ax=ax, legend=False)
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Appointments")
    ax.set_title("Appointment Distribution by Hour (Peak = red)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):02d}:00"))
    plt.xticks(rotation=45)
    fig.tight_layout()
    return _fig_to_b64(fig)


def generate_doctor_load_chart(records: list[dict]) -> str:
    """Horizontal bar chart showing appointment load per doctor. Returns base64 PNG."""
    df = _appointments_to_df(records)
    fig, ax = plt.subplots(figsize=(8, 4))

    if df.empty or "doctor_id" not in df.columns:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=13)
        ax.set_title("Doctor Load")
        return _fig_to_b64(fig)

    label_col = "doctor_name" if "doctor_name" in df.columns else "doctor_id"
    load = df.groupby(label_col).size().reset_index(name="count").sort_values("count", ascending=True)

    sns.barplot(data=load, y=label_col, x="count", color="#1f7a78", ax=ax, orient="h")
    ax.set_xlabel("Total Appointments")
    ax.set_ylabel("Doctor")
    ax.set_title("Appointment Load per Doctor")
    fig.tight_layout()
    return _fig_to_b64(fig)


def generate_status_pie_chart(records: list[dict]) -> str:
    """Pie chart of appointment statuses. Returns base64 PNG."""
    df = _appointments_to_df(records)
    fig, ax = plt.subplots(figsize=(5, 5))

    if df.empty or "status" not in df.columns:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=13)
        ax.set_title("Appointment Status")
        return _fig_to_b64(fig)

    status_counts = df["status"].value_counts()
    palette = sns.color_palette("Set2", len(status_counts))
    ax.pie(
        status_counts.values,
        labels=status_counts.index,
        colors=palette,
        autopct="%1.1f%%",
        startangle=140,
    )
    ax.set_title("Appointment Status Breakdown")
    fig.tight_layout()
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Full report generator
# ---------------------------------------------------------------------------

def generate_visualization_report(records: list[dict]) -> dict:
    """Run full DS analysis and return charts + stats as a single dict."""
    busiest = analyze_busiest_doctor(records)
    peak = predict_peak_hours(records)

    return {
        "busiest_doctor": busiest,
        "peak_hours": peak,
        "charts": {
            "appointments_by_hour": generate_appointments_by_hour_chart(records),
            "doctor_load": generate_doctor_load_chart(records),
            "status_breakdown": generate_status_pie_chart(records),
        },
    }
