import pandas as pd
from datetime import datetime
import os
from pathlib import Path

# =========================
# ファイル読み込み
# =========================

BASE_DIR = Path(__file__).parent

behavior = pd.read_csv(BASE_DIR / "P001.csv")
gaze = pd.read_excel(BASE_DIR / "shitagaki Data export.xlsx")

# =========================
# Tobii時刻 → Unix時刻
# =========================

recording_date = str(gaze["Recording date"].iloc[0])
recording_start_time = str(gaze["Recording start time"].iloc[0])

recording_start = datetime.strptime(
    f"{recording_date} {recording_start_time}",
    "%Y/%m/%d %H:%M:%S.%f"
)

recording_start_unix = recording_start.timestamp()

gaze["unix_time"] = (
    recording_start_unix
    + gaze["Recording timestamp"] / 1000000.0
)

# =========================
# 出力フォルダ
# =========================

output_dir = "trial_data"
os.makedirs(output_dir, exist_ok=True)

# =========================
# trialごとに切り出し
# =========================

summary = []

for _, trial in behavior.iterrows():

    trial_id = trial["trial_id"]

    start_time = trial["text_start_time"]
    end_time = trial["text_end_time"]

    trial_gaze = gaze[
        (gaze["unix_time"] >= start_time)
        & (gaze["unix_time"] <= end_time)
    ].copy()

    save_path = os.path.join(
        output_dir,
        f"trial_{trial_id}.csv"
    )

    trial_gaze.to_csv(save_path, index=False)

    summary.append({
        "trial_id": trial_id,
        "condition": trial["condition"],
        "correct": trial["correct"],
        "confidence": trial["confidence"],
        "reading_time_sec": end_time - start_time,
        "gaze_samples": len(trial_gaze)
    })
print(gaze["unix_time"].min())
print(gaze["unix_time"].max())

print(behavior["text_start_time"].min())
print(behavior["text_end_time"].max())

print(gaze["Recording timestamp"].head())

print(gaze["Recording timestamp"].tail())
print(len(gaze))

duration = (
    gaze["Recording timestamp"].max()
    - gaze["Recording timestamp"].min()
)

print("duration raw =", duration)
print(gaze["Sensor"].value_counts())
print("difference =", behavior["text_start_time"].iloc[0] - recording_start_unix)
print(gaze["Event"].dropna().unique())
events = gaze[gaze["Event"].notna()]
print(events[["Recording timestamp","Computer timestamp","Event"]])

# =========================
# 確認用
# =========================

summary_df = pd.DataFrame(summary)

summary_df.to_csv(
    "trial_summary.csv",
    index=False
)

print(summary_df.head())
print("\n完了")