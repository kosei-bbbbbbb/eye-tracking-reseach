"""同期済みの視線を4画面別および読解試行別に集計する。"""
import argparse
import csv
import math
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path
from statistics import fmean, pvariance
from tempfile import TemporaryDirectory

from sync_tobii import KEY, PHASES, csv_rows, finite, identity, writer

METRICS = (
    "eye_samples", "valid_gaze_samples", "observed_valid_gaze_ratio", "expected_samples",
    "valid_expected_ratio", "quality_flag", "movement_classified_samples",
    "fixation_count", "fixations_per_sec", "fixation_total_ms", "fixation_mean_ms",
    "first_fixation_x", "first_fixation_y", "first_fixation_sample_sec", "saccade_count",
    "pupil_samples", "pupil_mean_mm", "pupil_variance_mm2",
)
GROUP_FIELDS = ("participant_id", "session_day", "condition")


def classify(trial):
    confidence = int(trial["pre_question_confidence"])
    correct = int(trial["correct"])
    if correct not in (0, 1) or confidence not in range(1, 6):
        raise ValueError("正誤または問題前自信度が不正です。")
    if correct:
        if confidence >= 4:
            return "appropriate_understanding"
        if confidence <= 2:
            return "low_confidence_correct"
    elif confidence >= 4:
        return "overconfidence"
    elif confidence <= 2:
        return "non_understanding"
    return "other"


def valid_eye(value):
    return str(value or "").strip().casefold() in ("valid", "0", "0.0")


def metrics(samples, trial, window, hz, threshold):
    duration = float(window["phase_duration_sec"])
    width, height = float(trial["screen_width"]), float(trial["screen_height"])
    expected = hz * duration
    start, end = int(window["start_computer_us"]), int(window["end_computer_us"])
    period_us = 1_000_000 / hz
    valid_count, classified = 0, 0
    fixation_times = defaultdict(float)
    saccades = set()
    pupil = []
    first = (None, None, None)
    previous = None
    for i, row in enumerate(samples):
        stamp = int(row["computer_us"])
        if not start - 1 <= stamp <= end or (previous is not None and stamp <= previous):
            raise ValueError("同期済みの視線時刻が画面区間外にあるか、逆行しています。")
        previous = stamp
        x, y = finite(row["gaze_x"]), finite(row["gaze_y"])
        left, right = valid_eye(row["validity_left"]), valid_eye(row["validity_right"])
        has_validity = bool(row["validity_left"] or row["validity_right"])
        eye_ok = left or right or not has_validity
        gaze_ok = eye_ok and x is not None and y is not None and 0 <= x < width and 0 <= y < height
        valid_count += gaze_ok

        diameters = [v for v, ok in ((finite(row["pupil_left_mm"]), left),
                                    (finite(row["pupil_right_mm"]), right)) if ok and v is not None and v > 0]
        if diameters:
            pupil.append(fmean(diameters))

        movement, index = row["movement_type"].strip().casefold(), row["movement_index"]
        if not gaze_ok or not index or movement not in ("fixation", "saccade"):
            continue
        classified += 1
        if movement == "saccade":
            saccades.add(index)
            continue
        following = int(samples[i + 1]["computer_us"]) if i + 1 < len(samples) else end
        dwell = max(0, min(following - stamp, end - stamp, 1.5 * period_us)) / 1000
        if not fixation_times:
            fx, fy = finite(row["fixation_x"]), finite(row["fixation_y"])
            first = (x if fx is None else fx, y if fy is None else fy, (stamp - start) / 1_000_000)
        fixation_times[index] += dwell

    n = len(samples)
    valid_expected = valid_count / expected
    observed = valid_count / n if n else None
    if not n:
        flag = "no_samples"
    elif valid_expected < threshold or observed < threshold:
        flag = "low_valid_gaze"
    elif not classified:
        flag = "movement_unavailable"
    else:
        flag = "ok"

    return dict(zip(METRICS, (
        n, valid_count, observed, expected, valid_expected, flag, classified,
        len(fixation_times) if classified else None,
        len(fixation_times) / duration if classified else None,
        sum(fixation_times.values()) if classified else None,
        fmean(fixation_times.values()) if fixation_times else None,
        *first, len(saccades) if classified else None,
        len(pupil), fmean(pupil) if pupil else None, pvariance(pupil) if len(pupil) > 1 else None,
    )))


def read_phases(session, hz, threshold):
    prefix = f"{session.parent.parent.name}_{session.name}"
    behavior = csv_rows(session / f"{prefix}.csv")
    trial_cols = KEY[:2] + ("trial_id",)
    trials = {identity(row, trial_cols): row for row in behavior}
    if not trials or len(trials) != len(behavior):
        raise ValueError(f"{session} に重複試行または空の行動ログがあります。")
    windows = csv_rows(session / "sync" / "phase_windows.csv")
    observed = set()
    phase_rows, trial_rows = [], []
    with (session / "sync" / "synced_gaze_samples.csv").open(encoding="utf-8-sig", newline="") as stream:
        groups = groupby(csv.DictReader(stream), key=lambda row: identity(row, KEY))
        current = next(groups, None)
        for window in windows:
            key = identity(window, KEY)
            trial_key = identity(window, trial_cols)
            phase = window["phase"]
            trial = trials.get(trial_key)
            if (key in observed or phase not in PHASES or trial is None
                    or trial["recording_segment"] != window["recording_segment"]):
                raise ValueError("画面区間と行動ログが一致しません。")
            observed.add(key)
            samples = []
            if current is not None and current[0] == key:
                samples = list(current[1])
                current = next(groups, None)
            if len(samples) != int(window["sample_count"]):
                raise ValueError("同期ファイル間のサンプル数が一致しません。同期をやり直してください。")
            values = metrics(samples, trial, window, hz, threshold)
            phase_rows.append({**window, "condition": trial["condition"], **values})
            if phase == "text":
                trial_rows.append({
                    **trial, "state_label": classify(trial),
                    "text_sync_method": window["sync_method"], "text_phase_duration_sec": window["phase_duration_sec"],
                    **{f"text_{name}": value for name, value in values.items()},
                })
        if current is not None or len(observed) != len(trials) * len(PHASES):
            raise ValueError("同期ファイルに未対応の視線行または画面区間があります。")
    return phase_rows, trial_rows


def run(args):
    if not math.isfinite(args.sample_hz) or args.sample_hz <= 0 or not 0 <= args.min_valid_ratio <= 1:
        raise ValueError("サンプリング周波数は正の値、有効率の閾値は0～1を指定してください。")
    phases, trials, seen = [], [], set()
    for session in args.session:
        phase_rows, trial_rows = read_phases(session.resolve(), args.sample_hz, args.min_valid_ratio)
        keys = {identity(row, KEY[:2]) for row in trial_rows}
        if seen & keys or len(keys) != 1:
            raise ValueError("同じ参加者・実施日が重複しているか、同じフォルダに混在しています。")
        seen.update(keys)
        phases.extend(phase_rows)
        trials.extend(trial_rows)

    groups = defaultdict(Counter)
    for trial in trials:
        counter = groups[identity(trial, GROUP_FIELDS)]
        counter["total_trials"] += 1
        counter["correct_trials"] += int(trial["correct"])
        counter["text_quality_ok_trials"] += trial["text_quality_flag"] == "ok"
        counter[trial["state_label"]] += 1
    labels = ("overconfidence", "non_understanding", "appropriate_understanding", "low_confidence_correct", "other")
    summaries = []
    counts = ("total_trials", "correct_trials", "text_quality_ok_trials")
    for key, counter in sorted(groups.items()):
        summaries.append({**dict(zip(GROUP_FIELDS, key)), **{name: counter[name] for name in counts + labels},
                          "accuracy": counter["correct_trials"] / counter["total_trials"]})

    args.out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out) as temp:
        stage = Path(temp)
        for name, rows in (("phase_summary.csv", phases), ("trial_features.csv", trials),
                           ("label_summary.csv", summaries)):
            fields = list(dict.fromkeys(column for row in rows for column in row))
            with (stage / name).open("w", encoding="utf-8-sig", newline="") as stream:
                writer(stream, fields).writerows(rows)
        for name in ("phase_summary.csv", "trial_features.csv", "label_summary.csv"):
            (stage / name).replace(args.out / name)
    print(f"解析完了: {len(trials)}試行 / {len(phases)}画面 / {args.out.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, action="append", required=True, help="同期済み日フォルダ。複数回指定可能")
    parser.add_argument("--out", type=Path, required=True, help="解析結果の出力先")
    parser.add_argument("--sample-hz", type=float, default=60)
    parser.add_argument("--min-valid-ratio", type=float, default=0.8)
    try:
        run(parser.parse_args())
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        parser.exit(2, f"解析エラー: {exc}\n")
