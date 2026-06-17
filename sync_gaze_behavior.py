"""
sync_gaze_behavior_three_phase.py

Tobii Pro Lab の視線データと、Tkinter等で保存した行動ログを
タイムスタンプで同期し、試行ごとの視線データを3状態に分けるプログラム。

3状態:
  - text: 文章読解画面
  - question: 問題・選択肢画面
  - questionnaire: 理解度・確信度アンケート画面

想定入力:
  1. Tobii Pro Lab export: .xlsx または .csv
     必須列: Recording timestamp, Recording date, Recording start time
     推奨列: Sensor, Gaze point X, Gaze point Y, Eye movement type, ...
  2. 行動ログ: .csv
     必須列:
       trial_id,
       text_start_time, text_end_time,
       question_start_time, question_end_time,
       questionnaire_start_time, questionnaire_end_time
     これらは Python time.time() で記録した UNIX秒を想定。
  3. イベントログ: .csv 任意
     必須列: timestamp, offset_sec, event
     推奨列: trial_id, phase, event_type

出力:
  - synced_gaze_samples.csv
      各視線サンプルに trial_id / phase(text, question, questionnaire) を付与したもの
  - trial_summary.csv
      trial_id × phase ごとの視線サンプル数、valid率、fixation数などの要約
  - aligned_events.csv
      イベントログを指定した場合のみ、イベントを同じ基準で保存

使い方例:
  python sync_gaze_behavior_three_phase.py \
      --gaze "results/P001/shitagaki Data export (2).xlsx" \
      --behavior "results/P001/P001.csv" \
      --events "results/P001/P001_events.csv" \
      --outdir "results/P001/synced_output"

注意:
  Tobii PC と実験提示PCの時刻が完全に一致していない場合は、
  --time-shift-sec で補正する。

  例: 視線時刻が行動ログより 0.8 秒早いなら
      --time-shift-sec 0.8

  gaze_unix_time = recording_start_unix + Recording timestamp秒 + time_shift_sec
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


# ---------- 読み込み ----------

def read_table(path: str | Path) -> pd.DataFrame:
    """csv / xlsx を拡張子で判定して読み込む。"""
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    if path.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path)

    if path.suffix.lower() == ".csv":
        for enc in ["utf-8-sig", "utf-8", "cp932"]:
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path)

    raise ValueError(f"対応していない拡張子です: {path.suffix}")


# ---------- Tobii時刻のUNIX秒変換 ----------

def parse_recording_start_unix(gaze_df: pd.DataFrame, timezone: str) -> float:
    """
    Tobii export の Recording date + Recording start time から録画開始UNIX秒を作る。
    例: Recording date = 2026/06/17, Recording start time = 11:08:39.466
    """
    required = ["Recording date", "Recording start time"]
    missing = [c for c in required if c not in gaze_df.columns]
    if missing:
        raise ValueError(f"Tobiiデータに必要列がありません: {missing}")

    date_str = str(gaze_df["Recording date"].dropna().iloc[0])
    time_str = str(gaze_df["Recording start time"].dropna().iloc[0])

    dt = pd.to_datetime(f"{date_str} {time_str}")
    dt = dt.tz_localize(ZoneInfo(timezone))
    return dt.timestamp()


def add_gaze_unix_time(
    gaze_df: pd.DataFrame,
    timezone: str = "Asia/Tokyo",
    time_shift_sec: float = 0.0,
    timestamp_unit: str = "auto",
) -> pd.DataFrame:
    """
    Tobiiの Recording timestamp を秒に直し、UNIX秒を追加する。

    Tobii Pro Lab export の Recording timestamp は通常 microseconds。
    ただし環境差に備えて timestamp_unit=auto で大きさから推定する。
    """
    if "Recording timestamp" not in gaze_df.columns:
        raise ValueError("Tobiiデータに 'Recording timestamp' 列がありません。")

    gaze_df = gaze_df.copy()
    recording_start_unix = parse_recording_start_unix(gaze_df, timezone)

    ts = pd.to_numeric(gaze_df["Recording timestamp"], errors="coerce")

    if timestamp_unit == "auto":
        max_ts = ts.dropna().max()
        # 数十分の記録で 1e9 以上なら microseconds とみなす。
        # 秒単位なら通常 0〜数千程度。
        if pd.isna(max_ts):
            divisor = 1_000_000
        elif max_ts > 100_000:
            divisor = 1_000_000
        else:
            divisor = 1
    elif timestamp_unit == "microseconds":
        divisor = 1_000_000
    elif timestamp_unit == "milliseconds":
        divisor = 1_000
    elif timestamp_unit == "seconds":
        divisor = 1
    else:
        raise ValueError("timestamp_unit は auto / microseconds / milliseconds / seconds のどれかです。")

    gaze_df["recording_time_sec"] = ts / divisor
    gaze_df["gaze_unix_time"] = recording_start_unix + gaze_df["recording_time_sec"] + time_shift_sec
    gaze_df["recording_start_unix"] = recording_start_unix
    gaze_df["time_shift_sec"] = time_shift_sec
    gaze_df["recording_timestamp_unit"] = timestamp_unit
    gaze_df["recording_timestamp_divisor"] = divisor

    return gaze_df


# ---------- 行動ログの検証 ----------

def validate_behavior_columns(behavior_df: pd.DataFrame) -> None:
    required = [
        "trial_id",
        "text_start_time",
        "text_end_time",
        "question_start_time",
        "question_end_time",
        "questionnaire_start_time",
        "questionnaire_end_time",
    ]
    missing = [c for c in required if c not in behavior_df.columns]
    if missing:
        raise ValueError(
            "行動ログに必要列がありません: "
            f"{missing}\n"
            "3画面版の実験プログラムで作成した P001.csv を指定してください。"
        )


def build_phase_intervals(behavior_df: pd.DataFrame) -> pd.DataFrame:
    """行動ログから trial_id × phase の開始・終了時刻テーブルを作る。"""
    validate_behavior_columns(behavior_df)

    rows = []
    phase_specs = [
        ("text", "text_start_time", "text_end_time"),
        ("question", "question_start_time", "question_end_time"),
        ("questionnaire", "questionnaire_start_time", "questionnaire_end_time"),
    ]

    for _, trial in behavior_df.iterrows():
        trial_id = trial["trial_id"]
        for phase, start_col, end_col in phase_specs:
            start = pd.to_numeric(trial[start_col], errors="coerce")
            end = pd.to_numeric(trial[end_col], errors="coerce")

            if pd.isna(start) or pd.isna(end):
                continue
            if float(end) < float(start):
                raise ValueError(
                    f"trial_id={trial_id}, phase={phase} で終了時刻が開始時刻より前です。"
                )

            rows.append({
                "trial_id": trial_id,
                "phase": phase,
                "phase_start_time": float(start),
                "phase_end_time": float(end),
                "phase_duration_sec": round(float(end) - float(start), 3),
            })

    return pd.DataFrame(rows)


# ---------- 同期 ----------

def attach_trial_phase(gaze_df: pd.DataFrame, behavior_df: pd.DataFrame) -> pd.DataFrame:
    """
    gaze_unix_time が各試行の text / question / questionnaire 区間に入るかを判定し、
    trial_id と phase を付与する。
    """
    validate_behavior_columns(behavior_df)
    intervals = build_phase_intervals(behavior_df)

    # Tobiiのイベント行などを除き、Eye Tracker の行だけを使う。
    # Sensor列が無い場合は全行を対象にする。
    if "Sensor" in gaze_df.columns:
        gaze = gaze_df[gaze_df["Sensor"].eq("Eye Tracker")].copy()
    else:
        gaze = gaze_df.copy()

    matched_parts = []

    for _, interval in intervals.iterrows():
        trial_id = interval["trial_id"]
        phase = interval["phase"]
        start = float(interval["phase_start_time"])
        end = float(interval["phase_end_time"])

        part = gaze[
            (gaze["gaze_unix_time"] >= start)
            & (gaze["gaze_unix_time"] <= end)
        ].copy()

        if part.empty:
            continue

        part["trial_id"] = trial_id
        part["phase"] = phase
        part["phase_start_time"] = start
        part["phase_end_time"] = end
        part["phase_duration_sec"] = round(end - start, 3)
        part["trial_relative_time_sec"] = part["gaze_unix_time"] - start

        matched_parts.append(part)

    if not matched_parts:
        return pd.DataFrame()

    synced = pd.concat(matched_parts, ignore_index=True)

    # 行動ログの条件・正誤・確信度などを付ける。
    # 時刻列はphase側に持たせているので、重複を避ける。
    time_cols = [
        "text_start_time", "text_end_time",
        "question_start_time", "question_end_time",
        "questionnaire_start_time", "questionnaire_end_time",
        "text_start_offset", "text_end_offset",
        "question_start_offset", "question_end_offset",
        "questionnaire_start_offset", "questionnaire_end_offset",
    ]
    meta_cols = [c for c in behavior_df.columns if c not in time_cols]

    synced = synced.merge(
        behavior_df[meta_cols],
        on="trial_id",
        how="left",
        suffixes=("", "_behavior"),
    )

    return synced


# ---------- 要約特徴量 ----------

def count_fixations(group: pd.DataFrame) -> int:
    """fixation数をなるべくイベント単位で数える。"""
    if "Eye movement type" not in group.columns:
        return 0

    fix = group[group["Eye movement type"].astype(str).str.lower().eq("fixation")].copy()
    if fix.empty:
        return 0

    for idx_col in ["Eye movement type index", "Fixation index", "fixation_id"]:
        if idx_col in fix.columns:
            return int(fix[idx_col].dropna().nunique())

    # index列がない場合はサンプル数。厳密にはfixation数ではない。
    return int(len(fix))


def mean_fixation_duration(group: pd.DataFrame) -> float | None:
    """平均fixation durationを計算する。"""
    if "Eye movement type" in group.columns:
        fix = group[group["Eye movement type"].astype(str).str.lower().eq("fixation")].copy()
    else:
        fix = group.copy()

    if fix.empty:
        return None

    duration_col = None
    for col in ["Eye movement event duration", "Fixation duration", "fixation_duration"]:
        if col in fix.columns:
            duration_col = col
            break

    if duration_col is None:
        return None

    # 同一fixationが複数行に出る場合があるので、index列があれば重複を除く。
    for idx_col in ["Eye movement type index", "Fixation index", "fixation_id"]:
        if idx_col in fix.columns:
            fix = fix.dropna(subset=[idx_col]).drop_duplicates(subset=[idx_col])
            break

    return pd.to_numeric(fix[duration_col], errors="coerce").mean()


def make_trial_summary(synced_df: pd.DataFrame, behavior_df: pd.DataFrame) -> pd.DataFrame:
    """trial_id × phase ごとの簡単な視線特徴量を作る。"""
    validate_behavior_columns(behavior_df)
    intervals = build_phase_intervals(behavior_df)

    if synced_df.empty:
        summary = intervals.copy()
        summary["gaze_samples"] = 0
        return summary

    group_cols = ["trial_id", "phase"]

    rows = []
    for (trial_id, phase), group in synced_df.groupby(group_cols):
        row = {
            "trial_id": trial_id,
            "phase": phase,
            "gaze_samples": int(group["gaze_unix_time"].count()),
            "first_gaze_unix_time": group["gaze_unix_time"].min(),
            "last_gaze_unix_time": group["gaze_unix_time"].max(),
            "fixation_count": count_fixations(group),
            "mean_fixation_duration_ms": mean_fixation_duration(group),
        }

        if "Gaze point X" in group.columns:
            row["mean_gaze_x"] = pd.to_numeric(group["Gaze point X"], errors="coerce").mean()
        if "Gaze point Y" in group.columns:
            row["mean_gaze_y"] = pd.to_numeric(group["Gaze point Y"], errors="coerce").mean()

        if "Validity left" in group.columns and "Validity right" in group.columns:
            both_valid = (
                group["Validity left"].astype(str).str.lower().eq("valid")
                & group["Validity right"].astype(str).str.lower().eq("valid")
            )
            row["both_valid_rate"] = both_valid.mean()

        rows.append(row)

    summary = pd.DataFrame(rows)

    # サンプル0のphaseも残すため、intervalsをベースに結合する。
    summary = intervals.merge(summary, on=["trial_id", "phase"], how="left")
    summary["gaze_samples"] = summary["gaze_samples"].fillna(0).astype(int)
    summary["fixation_count"] = summary["fixation_count"].fillna(0).astype(int)

    # 行動ログを結合
    summary = summary.merge(behavior_df, on="trial_id", how="left")

    # 解析で使いやすいphase別の行動時間
    duration_map = {
        "text": "reading_time_sec",
        "question": "answer_time_sec",
        "questionnaire": "questionnaire_time_sec",
    }
    summary["behavior_duration_sec"] = summary.apply(
        lambda r: r[duration_map.get(r["phase"], "")] if duration_map.get(r["phase"], "") in summary.columns else r["phase_duration_sec"],
        axis=1,
    )

    return summary.sort_values(["trial_id", "phase"])


# ---------- イベントログ ----------

def align_events(events_path: str | Path | None) -> pd.DataFrame | None:
    """
    Python側イベントログを読み込む。
    すでに timestamp が UNIX秒ならそのまま使う。
    """
    if events_path is None:
        return None

    events = read_table(events_path)
    if "timestamp" not in events.columns:
        raise ValueError("イベントログに 'timestamp' 列がありません。")

    events = events.copy()
    events["event_unix_time"] = pd.to_numeric(events["timestamp"], errors="coerce")
    return events


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tobii視線データと3画面版の行動ログをタイムスタンプで同期する。"
    )
    parser.add_argument("--gaze", required=True, help="Tobii Pro Lab export .xlsx/.csv")
    parser.add_argument("--behavior", required=True, help="3画面版の行動ログ .csv")
    parser.add_argument("--events", default=None, help="イベントログ .csv 任意")
    parser.add_argument("--outdir", default="synced_output", help="出力フォルダ")
    parser.add_argument("--timezone", default="Asia/Tokyo", help="Tobii録画開始時刻のタイムゾーン")
    parser.add_argument(
        "--time-shift-sec",
        type=float,
        default=0.0,
        help="Tobii時刻に加える補正秒。PC時刻ズレがある場合に使う。",
    )
    parser.add_argument(
        "--timestamp-unit",
        default="auto",
        choices=["auto", "microseconds", "milliseconds", "seconds"],
        help="Recording timestamp の単位。通常は auto でよい。",
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    gaze_raw = read_table(args.gaze)
    behavior = read_table(args.behavior)

    gaze = add_gaze_unix_time(
        gaze_raw,
        timezone=args.timezone,
        time_shift_sec=args.time_shift_sec,
        timestamp_unit=args.timestamp_unit,
    )

    synced = attach_trial_phase(gaze, behavior)
    summary = make_trial_summary(synced, behavior)

    synced_path = outdir / "synced_gaze_samples.csv"
    summary_path = outdir / "trial_summary.csv"

    synced.to_csv(synced_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    events = align_events(args.events)
    if events is not None:
        events_path = outdir / "aligned_events.csv"
        events.to_csv(events_path, index=False, encoding="utf-8-sig")
    else:
        events_path = None

    print("同期処理が完了しました。")
    print(f"視線サンプル出力: {synced_path}")
    print(f"試行要約出力: {summary_path}")
    if events_path:
        print(f"イベント出力: {events_path}")
    print(f"同期された視線サンプル数: {len(synced)}")

    if len(synced) == 0:
        print("警告: 同期された視線サンプルが0です。")
        print("PC時刻がずれている可能性があります。--time-shift-sec を調整してください。")
    else:
        display_cols = ["trial_id", "phase", "phase_duration_sec", "gaze_samples", "fixation_count"]
        display_cols = [c for c in display_cols if c in summary.columns]
        print(summary[display_cols].to_string(index=False))


if __name__ == "__main__":
    main()
