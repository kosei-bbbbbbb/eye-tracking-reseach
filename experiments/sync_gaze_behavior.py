"""
sync_gaze_events_three_phase.py

Tobii Pro Lab の視線データと P001_events.csv のイベントログを同期し、
各視線サンプルを trial_id × phase に割り当てるプログラム。

必須入力:
  1. Tobii Pro Lab export (.xlsx / .xls / .csv)
  2. イベントログ (.csv)
     必須列: timestamp, trial_id, phase, event_type
     event_type は start / end を想定

任意入力:
  3. 行動ログ (.csv)
     condition、正誤、確信度、理解度などのメタデータを結果へ付加するために使用。
     同期区間の作成には使用しない。

出力:
  - synced_gaze_samples.csv
  - trial_summary.csv
  - aligned_events.csv

引数を指定せずに実行すると、ファイル選択ダイアログが開く。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from zoneinfo import ZoneInfo

import pandas as pd


PHASE_ORDER = {"text": 0, "question": 1, "questionnaire": 2}


# ---------- 読み込み ----------

def read_table(path: str | Path, preserve_trial_id: bool = False) -> pd.DataFrame:
    """CSV / Excelを読み込む。trial_idは必要に応じて文字列として保持する。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    suffix = path.suffix.lower()
    dtype = {"trial_id": "string"} if preserve_trial_id else None

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=dtype)

    if suffix == ".csv":
        last_error: Exception | None = None
        for encoding in ["utf-8-sig", "utf-8", "cp932"]:
            try:
                return pd.read_csv(path, encoding=encoding, dtype=dtype)
            except UnicodeDecodeError as exc:
                last_error = exc
        if last_error:
            raise last_error

    raise ValueError(f"対応していない拡張子です: {suffix}")


def normalize_trial_id(series: pd.Series) -> pd.Series:
    """000形式を維持し、Excel由来の 0.0 なども3桁文字列へ整える。"""
    def convert(value: object) -> object:
        if pd.isna(value):
            return pd.NA
        text = str(value).strip()
        if not text:
            return pd.NA
        if text.endswith(".0"):
            text = text[:-2]
        if text.isdigit():
            return text.zfill(3)
        return text

    return series.map(convert).astype("string")


# ---------- Tobii時刻のUNIX秒変換 ----------

def parse_recording_start_unix(gaze_df: pd.DataFrame, timezone: str) -> float:
    required = ["Recording date", "Recording start time"]
    missing = [col for col in required if col not in gaze_df.columns]
    if missing:
        raise ValueError(f"Tobiiデータに必要列がありません: {missing}")

    date_values = gaze_df["Recording date"].dropna()
    time_values = gaze_df["Recording start time"].dropna()
    if date_values.empty or time_values.empty:
        raise ValueError("Recording date または Recording start time に有効な値がありません。")

    date_str = str(date_values.iloc[0])
    time_str = str(time_values.iloc[0])
    dt = pd.to_datetime(f"{date_str} {time_str}")

    if dt.tzinfo is None:
        dt = dt.tz_localize(ZoneInfo(timezone))
    else:
        dt = dt.tz_convert(ZoneInfo(timezone))

    return float(dt.timestamp())


def add_gaze_unix_time(
    gaze_df: pd.DataFrame,
    timezone: str = "Asia/Tokyo",
    time_shift_sec: float = 0.0,
    timestamp_unit: str = "auto",
) -> pd.DataFrame:
    if "Recording timestamp" not in gaze_df.columns:
        raise ValueError("Tobiiデータに 'Recording timestamp' 列がありません。")

    result = gaze_df.copy()
    recording_start_unix = parse_recording_start_unix(result, timezone)
    timestamp = pd.to_numeric(result["Recording timestamp"], errors="coerce")

    if timestamp_unit == "auto":
        max_timestamp = timestamp.dropna().max()
        if pd.isna(max_timestamp):
            divisor = 1_000_000
            detected_unit = "microseconds"
        elif max_timestamp > 100_000:
            divisor = 1_000_000
            detected_unit = "microseconds"
        else:
            divisor = 1
            detected_unit = "seconds"
    elif timestamp_unit == "microseconds":
        divisor = 1_000_000
        detected_unit = timestamp_unit
    elif timestamp_unit == "milliseconds":
        divisor = 1_000
        detected_unit = timestamp_unit
    elif timestamp_unit == "seconds":
        divisor = 1
        detected_unit = timestamp_unit
    else:
        raise ValueError("timestamp_unit は auto / microseconds / milliseconds / seconds のどれかです。")

    result["recording_time_sec"] = timestamp / divisor
    result["gaze_unix_time"] = recording_start_unix + result["recording_time_sec"] + time_shift_sec
    result["recording_start_unix"] = recording_start_unix
    result["time_shift_sec"] = time_shift_sec
    result["recording_timestamp_unit"] = detected_unit
    result["recording_timestamp_divisor"] = divisor
    return result


# ---------- イベントログから区間作成 ----------

def validate_event_columns(events_df: pd.DataFrame) -> None:
    required = ["timestamp", "trial_id", "phase", "event_type"]
    missing = [col for col in required if col not in events_df.columns]
    if missing:
        raise ValueError(
            f"イベントログに必要列がありません: {missing}\n"
            "必要列: timestamp, trial_id, phase, event_type"
        )


def prepare_events(events_df: pd.DataFrame) -> pd.DataFrame:
    validate_event_columns(events_df)
    events = events_df.copy()
    events["trial_id"] = normalize_trial_id(events["trial_id"])
    events["phase"] = events["phase"].astype("string").str.strip().str.lower()
    events["event_type"] = events["event_type"].astype("string").str.strip().str.lower()
    events["event_unix_time"] = pd.to_numeric(events["timestamp"], errors="coerce")

    invalid_timestamp = events["event_unix_time"].isna() & events["trial_id"].notna()
    if invalid_timestamp.any():
        rows = events.index[invalid_timestamp].tolist()[:5]
        raise ValueError(f"イベントログのtimestampを数値に変換できません。該当行例: {rows}")

    return events


def build_phase_intervals_from_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """start/endイベントを対応付け、trial_id × phase の同期区間を作る。"""
    events = prepare_events(events_df)

    target = events[
        events["trial_id"].notna()
        & events["phase"].isin(PHASE_ORDER)
        & events["event_type"].isin(["start", "end"])
    ].copy()

    if target.empty:
        raise ValueError("text/question/questionnaire の start/end イベントが見つかりません。")

    rows: list[dict[str, object]] = []
    errors: list[str] = []

    for (trial_id, phase), group in target.groupby(["trial_id", "phase"], sort=False):
        starts = group.loc[group["event_type"].eq("start"), "event_unix_time"].sort_values().tolist()
        ends = group.loc[group["event_type"].eq("end"), "event_unix_time"].sort_values().tolist()

        if len(starts) != 1 or len(ends) != 1:
            errors.append(
                f"trial_id={trial_id}, phase={phase}: start={len(starts)}件, end={len(ends)}件"
            )
            continue

        start = float(starts[0])
        end = float(ends[0])
        if end < start:
            errors.append(f"trial_id={trial_id}, phase={phase}: 終了時刻が開始時刻より前")
            continue

        rows.append({
            "trial_id": str(trial_id),
            "phase": str(phase),
            "phase_start_time": start,
            "phase_end_time": end,
            "phase_duration_sec": round(end - start, 3),
        })

    if errors:
        preview = "\n".join(errors[:10])
        raise ValueError(f"イベントのstart/end対応に問題があります:\n{preview}")

    intervals = pd.DataFrame(rows)
    if intervals.empty:
        raise ValueError("イベントログから同期区間を作成できませんでした。")

    intervals["phase_order"] = intervals["phase"].map(PHASE_ORDER)
    intervals = intervals.sort_values(["trial_id", "phase_order"]).drop(columns="phase_order")

    # 区間重複の簡易検査
    ordered = intervals.sort_values("phase_start_time").reset_index(drop=True)
    overlap = ordered["phase_start_time"].iloc[1:].reset_index(drop=True) < ordered["phase_end_time"].iloc[:-1].reset_index(drop=True)
    if overlap.any():
        idx = int(overlap[overlap].index[0])
        first = ordered.iloc[idx]
        second = ordered.iloc[idx + 1]
        raise ValueError(
            "イベント区間が重複しています: "
            f"{first['trial_id']}/{first['phase']} と {second['trial_id']}/{second['phase']}"
        )

    return intervals


# ---------- 同期 ----------

def attach_trial_phase(gaze_df: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    """各視線サンプルへ trial_id と phase を付与する。"""
    if "Sensor" in gaze_df.columns:
        gaze = gaze_df[gaze_df["Sensor"].astype(str).str.strip().eq("Eye Tracker")].copy()
    else:
        gaze = gaze_df.copy()

    gaze = gaze[gaze["gaze_unix_time"].notna()].copy()
    matched_parts: list[pd.DataFrame] = []

    for interval in intervals.itertuples(index=False):
        start = float(interval.phase_start_time)
        end = float(interval.phase_end_time)
        part = gaze[
            gaze["gaze_unix_time"].ge(start)
            & gaze["gaze_unix_time"].le(end)
        ].copy()

        if part.empty:
            continue

        part["trial_id"] = str(interval.trial_id)
        part["phase"] = str(interval.phase)
        part["phase_start_time"] = start
        part["phase_end_time"] = end
        part["phase_duration_sec"] = float(interval.phase_duration_sec)
        part["trial_relative_time_sec"] = part["gaze_unix_time"] - start
        matched_parts.append(part)

    if not matched_parts:
        return pd.DataFrame()

    return pd.concat(matched_parts, ignore_index=True)


def merge_behavior_metadata(data: pd.DataFrame, behavior_df: pd.DataFrame | None) -> pd.DataFrame:
    """任意の行動ログから、trial_id単位のメタデータを付加する。"""
    if behavior_df is None or data.empty:
        return data
    if "trial_id" not in behavior_df.columns:
        raise ValueError("任意の行動ログに 'trial_id' 列がありません。")

    behavior = behavior_df.copy()
    behavior["trial_id"] = normalize_trial_id(behavior["trial_id"])

    if behavior["trial_id"].duplicated().any():
        duplicated = behavior.loc[behavior["trial_id"].duplicated(), "trial_id"].dropna().unique().tolist()
        raise ValueError(f"行動ログのtrial_idが重複しています: {duplicated[:10]}")

    # イベント由来の区間列と衝突しやすい時刻列は除外する
    exclude = {
        "text_start_time", "text_end_time",
        "question_start_time", "question_end_time",
        "questionnaire_start_time", "questionnaire_end_time",
        "text_start_offset", "text_end_offset",
        "question_start_offset", "question_end_offset",
        "questionnaire_start_offset", "questionnaire_end_offset",
    }
    metadata_cols = [col for col in behavior.columns if col == "trial_id" or col not in exclude]
    return data.merge(behavior[metadata_cols], on="trial_id", how="left", suffixes=("", "_behavior"))


# ---------- 要約特徴量 ----------

def count_fixations(group: pd.DataFrame) -> int:
    if "Eye movement type" not in group.columns:
        return 0

    fix = group[group["Eye movement type"].astype(str).str.lower().eq("fixation")].copy()
    if fix.empty:
        return 0

    for col in ["Eye movement type index", "Fixation index", "fixation_id"]:
        if col in fix.columns:
            return int(fix[col].dropna().nunique())
    return int(len(fix))


def mean_fixation_duration(group: pd.DataFrame) -> float | None:
    if "Eye movement type" in group.columns:
        fix = group[group["Eye movement type"].astype(str).str.lower().eq("fixation")].copy()
    else:
        fix = group.copy()

    if fix.empty:
        return None

    duration_col = next(
        (col for col in ["Eye movement event duration", "Fixation duration", "fixation_duration"] if col in fix.columns),
        None,
    )
    if duration_col is None:
        return None

    for col in ["Eye movement type index", "Fixation index", "fixation_id"]:
        if col in fix.columns:
            fix = fix.dropna(subset=[col]).drop_duplicates(subset=[col])
            break

    value = pd.to_numeric(fix[duration_col], errors="coerce").mean()
    return None if pd.isna(value) else float(value)


def make_trial_summary(
    synced_df: pd.DataFrame,
    intervals: pd.DataFrame,
    behavior_df: pd.DataFrame | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    if not synced_df.empty:
        for (trial_id, phase), group in synced_df.groupby(["trial_id", "phase"], sort=False):
            row: dict[str, object] = {
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
                row["both_valid_rate"] = float(both_valid.mean())
            rows.append(row)

    features = pd.DataFrame(rows)
    summary = intervals.copy()
    if features.empty:
        summary["gaze_samples"] = 0
        summary["fixation_count"] = 0
    else:
        summary = summary.merge(features, on=["trial_id", "phase"], how="left")
        summary["gaze_samples"] = summary["gaze_samples"].fillna(0).astype(int)
        summary["fixation_count"] = summary["fixation_count"].fillna(0).astype(int)

    summary["behavior_duration_sec"] = summary["phase_duration_sec"]
    summary = merge_behavior_metadata(summary, behavior_df)
    summary["phase_order"] = summary["phase"].map(PHASE_ORDER)
    return summary.sort_values(["trial_id", "phase_order"]).drop(columns="phase_order")


# ---------- ファイル選択 ----------

def select_paths_with_dialog() -> tuple[str, str, str | None, str]:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        gaze_path = filedialog.askopenfilename(
            title="Tobii視線データを選択してください",
            filetypes=[
                ("対応ファイル", "*.xlsx *.xls *.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not gaze_path:
            raise RuntimeError("視線データの選択がキャンセルされました。")

        events_path = filedialog.askopenfilename(
            title="イベントログ（例: P001_events.csv）を選択してください",
            filetypes=[("CSV", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not events_path:
            raise RuntimeError("イベントログの選択がキャンセルされました。")

        behavior_path: str | None = None
        use_behavior = messagebox.askyesno(
            "行動ログ",
            "condition・正誤・確信度などを付加するため、行動ログも使用しますか？\n"
            "同期だけなら［いいえ］で問題ありません。",
            parent=root,
        )
        if use_behavior:
            selected = filedialog.askopenfilename(
                title="任意の行動ログ（例: P001.csv）を選択してください",
                filetypes=[("CSV", "*.csv"), ("すべてのファイル", "*.*")],
            )
            if not selected:
                raise RuntimeError("行動ログの選択がキャンセルされました。")
            behavior_path = selected

        outdir = filedialog.askdirectory(
            title="出力先フォルダを選択してください",
            initialdir=str(Path(events_path).parent),
        )
        if not outdir:
            raise RuntimeError("出力先フォルダの選択がキャンセルされました。")

        return gaze_path, events_path, behavior_path, outdir
    finally:
        root.destroy()


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Tobii視線データとイベントログを同期する。"
            "行動ログはメタデータ付加用の任意入力。"
        )
    )
    parser.add_argument("--gaze", default=None, help="Tobii Pro Lab export .xlsx/.csv")
    parser.add_argument("--events", default=None, help="イベントログ .csv（必須）")
    parser.add_argument("--behavior", default=None, help="行動ログ .csv（任意）")
    parser.add_argument("--outdir", default=None, help="出力フォルダ")
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
    parser.add_argument("--dialog", action="store_true", help="ファイル選択画面を使用する。")
    args = parser.parse_args()

    if args.dialog or not args.gaze or not args.events:
        try:
            gaze_path, events_path, behavior_path, outdir_path = select_paths_with_dialog()
        except RuntimeError as exc:
            print(f"処理を中止しました: {exc}")
            return
    else:
        gaze_path = args.gaze
        events_path = args.events
        behavior_path = args.behavior
        outdir_path = args.outdir or "synced_output"

    outdir = Path(outdir_path)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        gaze_raw = read_table(gaze_path)
        events_raw = read_table(events_path, preserve_trial_id=True)
        behavior = read_table(behavior_path, preserve_trial_id=True) if behavior_path else None

        gaze = add_gaze_unix_time(
            gaze_raw,
            timezone=args.timezone,
            time_shift_sec=args.time_shift_sec,
            timestamp_unit=args.timestamp_unit,
        )
        prepared_events = prepare_events(events_raw)
        intervals = build_phase_intervals_from_events(prepared_events)
        synced = attach_trial_phase(gaze, intervals)
        synced = merge_behavior_metadata(synced, behavior)
        summary = make_trial_summary(synced, intervals, behavior)

        synced_path = outdir / "synced_gaze_samples.csv"
        summary_path = outdir / "trial_summary.csv"
        aligned_events_path = outdir / "aligned_events.csv"

        synced.to_csv(synced_path, index=False, encoding="utf-8-sig")
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        prepared_events.to_csv(aligned_events_path, index=False, encoding="utf-8-sig")

    except Exception as exc:
        print(f"エラー: {exc}")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("同期処理エラー", str(exc), parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return

    print("同期処理が完了しました。")
    print(f"視線データ: {gaze_path}")
    print(f"イベントログ: {events_path}")
    print(f"行動ログ（任意）: {behavior_path or '使用なし'}")
    print(f"出力先: {outdir.resolve()}")
    print(f"視線サンプル出力: {synced_path}")
    print(f"試行要約出力: {summary_path}")
    print(f"イベント出力: {aligned_events_path}")
    print(f"同期された視線サンプル数: {len(synced)}")

    if synced.empty:
        print("警告: 同期された視線サンプルが0です。")
        print("Tobii時刻とイベント時刻のずれを確認し、--time-shift-sec を調整してください。")
        print(f"Tobii視線時刻範囲: {gaze['gaze_unix_time'].min()} ～ {gaze['gaze_unix_time'].max()}")
        print(f"イベント区間範囲: {intervals['phase_start_time'].min()} ～ {intervals['phase_end_time'].max()}")
    else:
        columns = ["trial_id", "phase", "phase_duration_sec", "gaze_samples", "fixation_count"]
        print(summary[columns].to_string(index=False))

    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "同期処理完了",
            f"同期処理が完了しました。\n\n出力先:\n{outdir.resolve()}\n\n同期サンプル数: {len(synced)}",
            parent=root,
        )
        root.destroy()
    except tk.TclError:
        pass


if __name__ == "__main__":
    main()