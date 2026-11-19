"""同期済みの視線から、画面別・試行別の特徴量を作る。

実行ボタン（引数なし）で動かすと、results 以下にある同期済みの日フォルダ
（sync/phase_windows.csv と sync/synced_gaze_samples.csv があるもの）をすべて集めて処理し、
results/features に出力する。1日目と2日目、複数の参加者をまとめて1つの表にする。

出力
  phase_summary.csv   画面（読書・問題前自信度・問題・問題後アンケート）ごとの特徴量
  trial_features.csv  1試行1行。行動ログ + 読書画面の特徴量(text_) + 打ち切り + 状態ラベル + 標準化値(z_)
  label_summary.csv   参加者・日・難易度ごとの件数
"""
import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path
from statistics import fmean, pstdev, pvariance
from tempfile import TemporaryDirectory

from sync_tobii_multi import KEY, PHASES, csv_rows, finite, identity, writer

SCRIPT_DIR = Path(__file__).resolve().parent

# ===== 設定 =====
RESULTS_DIR = SCRIPT_DIR / "results"      # 実験アプリと同じ保存先
DEFAULT_OUT = RESULTS_DIR / "features"    # 特徴量の出力先
SAMPLE_HZ = 60                            # アイトラッカーのサンプリング周波数
MIN_VALID_RATIO = 0.8                     # 有効な視線の割合がこれ未満の画面は low_valid_gaze
LINE_PITCH_PX = 60                        # 実験アプリの READING_LINE_PITCH_PX と同じ値
REGRESSION_MIN_PX = 32                    # 同じ行で1文字分（READING_FONT_PX）以上左へ戻ったら逆行
# 参加者×日ごとに標準化（z得点）する列。瞳孔径などは人や日によって基準値が違うため。
Z_COLUMNS = (
    "reading_time_sec", "answer_time_sec",
    "text_fixation_mean_ms", "text_fixations_per_sec", "text_regression_rate",
    "text_forward_saccade_mean_px", "text_pupil_mean_mm",
)

TIMEOUT_RE = re.compile(r"TEXT_\d+_TIMEOUT")
LABELS = ("overconfidence", "non_understanding", "appropriate_understanding",
          "low_confidence_correct", "other")


def classify(trial):
    """正誤 × 問題前の自信度で状態ラベルを付ける（自信度3は other）。"""
    confidence = int(trial["pre_question_confidence"])
    correct = int(trial["correct"])
    if correct not in (0, 1) or confidence not in range(1, 6):
        raise ValueError(f"試行{trial['trial_id']}: 正誤または問題前自信度が不正です。")
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


def reading_path(fixations):
    """注視の並びから、横書きの文章を読む動きの特徴量を計算する。

    隣り合う注視の移動を次のように分ける（座標は画面のピクセル）。
      - 縦に半行以上動き、下の行の左側へ移った    → 改行（line_returns）
      - 縦に半行以上上へ動いた                    → 前の行への逆行（line_regressions）
      - 同じ行で REGRESSION_MIN_PX 以上左へ戻った → 行内の逆行（within_line_regressions）
      - 同じ行で右へ進んだ                        → 順方向のサッカード
    """
    transitions = within = upward = returns = 0
    forward = []
    for a, b in zip(fixations, fixations[1:]):
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        transitions += 1
        if abs(dy) >= LINE_PITCH_PX / 2:
            if dy > 0 and dx < 0:
                returns += 1
            elif dy < 0:
                upward += 1
        elif dx <= -REGRESSION_MIN_PX:
            within += 1
        elif dx > 0:
            forward.append(dx)
    return {
        "fixation_transitions": transitions,
        "within_line_regressions": within,
        "line_regressions": upward,
        "line_returns": returns,
        "regression_rate": (within + upward) / transitions if transitions else None,
        "forward_saccade_mean_px": fmean(forward) if forward else None,
    }


def metrics(samples, trial, window, hz, threshold):
    duration = float(window["phase_duration_sec"])
    width, height = float(trial["screen_width"]), float(trial["screen_height"])
    expected = hz * duration
    start, end = int(window["start_computer_us"]), int(window["end_computer_us"])
    period_us = 1_000_000 / hz
    valid_count = classified = 0
    fixations = {}
    saccades = set()
    pupil = []
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

        movement, index = (row["movement_type"] or "").strip().casefold(), row["movement_index"]
        if not gaze_ok or not index or movement not in ("fixation", "saccade"):
            continue
        classified += 1
        if movement == "saccade":
            saccades.add(index)
            continue
        following = int(samples[i + 1]["computer_us"]) if i + 1 < len(samples) else end
        dwell = max(0, min(following - stamp, end - stamp, 1.5 * period_us)) / 1000
        fixation = fixations.setdefault(index, {
            "start": stamp, "dwell": 0.0, "xs": [], "ys": [],
            "fx": finite(row["fixation_x"]), "fy": finite(row["fixation_y"]),
        })
        fixation["dwell"] += dwell
        fixation["xs"].append(x)
        fixation["ys"].append(y)

    # 注視ごとの位置は Tobii の fixation point、なければ視線座標の平均を使う。
    ordered = sorted(fixations.values(), key=lambda f: f["start"])
    for f in ordered:
        f["x"] = f["fx"] if f["fx"] is not None else fmean(f["xs"])
        f["y"] = f["fy"] if f["fy"] is not None else fmean(f["ys"])
    durations = [f["dwell"] for f in ordered]

    n = len(samples)
    valid_expected = valid_count / expected if expected else None
    observed = valid_count / n if n else None
    if not n:
        flag = "no_samples"
    elif valid_expected < threshold or observed < threshold:
        flag = "low_valid_gaze"
    elif not classified:
        flag = "movement_unavailable"
    else:
        flag = "ok"

    has_movement = bool(classified)
    first = ordered[0] if ordered else None
    result = {
        "eye_samples": n,
        "valid_gaze_samples": valid_count,
        "observed_valid_gaze_ratio": observed,
        "expected_samples": expected,
        "valid_expected_ratio": valid_expected,
        "quality_flag": flag,
        "movement_classified_samples": classified,
        "fixation_count": len(ordered) if has_movement else None,
        "fixations_per_sec": len(ordered) / duration if has_movement and duration else None,
        "fixation_total_ms": sum(durations) if has_movement else None,
        "fixation_mean_ms": fmean(durations) if durations else None,
        "fixation_sd_ms": pstdev(durations) if len(durations) > 1 else None,
        "fixation_max_ms": max(durations) if durations else None,
        "first_fixation_x": first["x"] if first else None,
        "first_fixation_y": first["y"] if first else None,
        "first_fixation_sample_sec": (first["start"] - start) / 1_000_000 if first else None,
        "saccade_count": len(saccades) if has_movement else None,
        "pupil_samples": len(pupil),
        "pupil_mean_mm": fmean(pupil) if pupil else None,
        "pupil_variance_mm2": pvariance(pupil) if len(pupil) > 1 else None,
    }
    path = reading_path(ordered)
    if not has_movement:
        path = dict.fromkeys(path)
    result.update(path)
    return result


def read_timeouts(session, prefix):
    """イベントログから、読書画面が時間切れで終わった試行IDを集める。"""
    events = session / f"{prefix}_events.csv"
    if not events.is_file():
        raise ValueError(f"イベントログがありません: {events}")
    return {row["trial_id"] for row in csv_rows(events) if TIMEOUT_RE.fullmatch(row["event"])}


def read_phases(session, hz, threshold):
    prefix = f"{session.parent.parent.name}_{session.name}"
    behavior_path = session / f"{prefix}.csv"
    if not behavior_path.is_file():
        raise ValueError(f"行動ログがありません: {behavior_path}")
    behavior = csv_rows(behavior_path)
    trial_cols = KEY[:2] + ("trial_id",)
    trials = {identity(row, trial_cols): row for row in behavior}
    if not trials or len(trials) != len(behavior):
        raise ValueError(f"{session} に重複試行または空の行動ログがあります。")
    timeouts = read_timeouts(session, prefix)
    windows = csv_rows(session / "sync" / "phase_windows.csv")
    observed = set()
    phase_rows, trial_rows = [], []
    with (session / "sync" / "synced_gaze_samples.csv").open(encoding="utf-8-sig", newline="") as stream:
        groups = groupby(csv.DictReader(stream), key=lambda row: identity(row, KEY))
        current = next(groups, None)
        for window in windows:
            key = identity(window, KEY)
            trial = trials.get(identity(window, trial_cols))
            phase = window["phase"]
            if (key in observed or phase not in PHASES or trial is None
                    or trial["recording_segment"] != window["recording_segment"]):
                raise ValueError(f"画面区間と行動ログが一致しません: 試行{window['trial_id']} {phase}")
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
                    **trial,
                    "state_label": classify(trial),
                    "text_timeout": int(trial["trial_id"] in timeouts),
                    "text_sync_method": window["sync_method"],
                    "text_phase_duration_sec": window["phase_duration_sec"],
                    **{f"text_{name}": value for name, value in values.items()},
                })
        if current is not None or len(observed) != len(trials) * len(PHASES):
            raise ValueError("同期ファイルに未対応の視線行または画面区間があります。")
    return phase_rows, trial_rows


def add_z_scores(trials):
    """参加者×日ごとに z 得点を付ける。平均と標準偏差は quality_flag が ok の試行から求める。"""
    groups = defaultdict(list)
    for trial in trials:
        groups[identity(trial, KEY[:2])].append(trial)
    for rows in groups.values():
        for column in Z_COLUMNS:
            reference = [finite(r.get(column)) for r in rows if r["text_quality_flag"] == "ok"]
            reference = [v for v in reference if v is not None]
            mean = fmean(reference) if reference else None
            sd = pstdev(reference) if len(reference) > 1 else 0
            for r in rows:
                value = finite(r.get(column))
                r[f"z_{column}"] = (value - mean) / sd if value is not None and sd else None


def summarize(trials):
    groups = defaultdict(Counter)
    for trial in trials:
        counter = groups[(trial["participant_id"], trial["session_day"], trial["condition"])]
        counter["total_trials"] += 1
        counter["correct_trials"] += int(trial["correct"])
        counter["text_quality_ok_trials"] += trial["text_quality_flag"] == "ok"
        counter["text_timeout_trials"] += trial["text_timeout"]
        counter[trial["state_label"]] += 1
    counts = ("total_trials", "correct_trials", "text_quality_ok_trials", "text_timeout_trials")
    return [{"participant_id": p, "session_day": d, "condition": c,
             **{name: counter[name] for name in counts + LABELS},
             "accuracy": counter["correct_trials"] / counter["total_trials"]}
            for (p, d, c), counter in sorted(groups.items())]


def run(args):
    if not math.isfinite(args.sample_hz) or args.sample_hz <= 0 or not 0 <= args.min_valid_ratio <= 1:
        raise ValueError("サンプリング周波数は正の値、有効率の閾値は0～1を指定してください。")
    phases, trials, seen = [], [], set()
    for session in args.session:
        session = session.resolve()
        print(f"処理中: {session}")
        try:
            phase_rows, trial_rows = read_phases(session, args.sample_hz, args.min_valid_ratio)
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(f"{session}: {exc}") from exc
        keys = {identity(row, KEY[:2]) for row in trial_rows}
        if seen & keys or len(keys) != 1:
            raise ValueError("同じ参加者・実施日が重複しているか、同じフォルダに混在しています。")
        seen.update(keys)
        phases.extend(phase_rows)
        trials.extend(trial_rows)
    add_z_scores(trials)

    args.out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out) as temp:
        stage = Path(temp)
        outputs = (("phase_summary.csv", phases), ("trial_features.csv", trials),
                   ("label_summary.csv", summarize(trials)))
        for name, rows in outputs:
            fields = list(dict.fromkeys(column for row in rows for column in row))
            with (stage / name).open("w", encoding="utf-8-sig", newline="") as stream:
                writer(stream, fields).writerows(rows)
        for name, _ in outputs:
            (stage / name).replace(args.out / name)

    labels = Counter(t["state_label"] for t in trials)
    print(f"解析完了: {len(seen)}日分 / {len(trials)}試行 / {len(phases)}画面 / {args.out.resolve()}")
    print("  読書画面の quality ok:", sum(t["text_quality_flag"] == "ok" for t in trials),
          "/ 時間切れ:", sum(t["text_timeout"] for t in trials))
    print("  状態ラベル:", ", ".join(f"{name} {labels[name]}" for name in LABELS))


def discover_sessions(root):
    """results/P***/two_day/day* のうち、同期済みの日フォルダを集める。"""
    found, skipped = [], []
    for day in sorted(root.glob("P*/two_day/day*")):
        if not day.is_dir():
            continue
        sync = day / "sync"
        if (sync / "phase_windows.csv").is_file() and (sync / "synced_gaze_samples.csv").is_file():
            found.append(day)
        else:
            skipped.append(day)
    return found, skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, action="append", default=[],
                        help="同期済みの日フォルダ。複数回指定可。省略すると results 以下を自動で探す")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="出力先フォルダ")
    parser.add_argument("--sample-hz", type=float, default=SAMPLE_HZ)
    parser.add_argument("--min-valid-ratio", type=float, default=MIN_VALID_RATIO)
    args = parser.parse_args()
    try:
        if not args.session:
            args.session, skipped = discover_sessions(RESULTS_DIR)
            for day in skipped:
                print(f"同期前のためスキップ: {day}")
            if not args.session:
                raise ValueError(f"{RESULTS_DIR} に同期済みの日フォルダがありません。"
                                 "先に sync_tobii_multi.py を実行してください。")
        run(args)
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        parser.exit(2, f"解析エラー: {exc}\n")
