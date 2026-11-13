"""日別イベントログとTobii Pro Labの画面型録画を同期する。"""
import argparse
import csv
import math
import re
from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

PHASES = ("text", "preconfidence", "question", "questionnaire")
PHASE_RE = re.compile(r"(TEXT|PRECONFIDENCE|QUESTION|QUESTIONNAIRE)_(\d+)_(START|END)")
SEGMENT_RE = re.compile(r"RECORDING_SEGMENT_(\d+)_(START|END)")
KEY = ("participant_id", "session_day", "recording_segment", "trial_id", "phase")
SAMPLE_FIELDS = ("computer_us", "recording_sec", "phase_elapsed_sec", "gaze_x", "gaze_y",
                 "pupil_left_mm", "pupil_right_mm", "validity_left", "validity_right",
                 "movement_type", "movement_index", "fixation_x", "fixation_y")
SAMPLE_COLUMNS = {
    "gaze_x": "gaze point x", "gaze_y": "gaze point y",
    "pupil_left_mm": "pupil diameter left", "pupil_right_mm": "pupil diameter right",
    "validity_left": "validity left", "validity_right": "validity right",
    "movement_type": "eye movement type", "movement_index": "eye movement type index",
    "fixation_x": "fixation point x", "fixation_y": "fixation point y",
}
SUPPORTED = (".tsv", ".csv", ".xlsx")


def finite(value):
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def writer(stream, fields):
    output = csv.DictWriter(stream, fieldnames=fields)
    output.writeheader()
    return output


def identity(row, columns):
    return tuple(str(row[column]) for column in columns)


@contextmanager
def tobii_rows(path):
    def normalized(rows):
        headers = [str(value or "").strip().casefold() for value in next(rows, ())]
        required = {"recording timestamp", "computer timestamp", "sensor", "recording name",
                    "event", "gaze point x", "gaze point y"}
        if not required.issubset(headers):
            raise ValueError(f"{path.name} の列が不足しています: {', '.join(sorted(required - set(headers)))}")
        yield headers
        yield from (dict(zip(headers, row)) for row in rows)

    if path.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("XLSXを使う場合は py -m pip install openpyxl を実行してください。") from exc
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = normalized(iter(book.worksheets[0].values))
            yield next(rows), rows
        finally:
            book.close()
    else:
        with path.open("rb") as stream:
            prefix = stream.read(4)
        encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        with path.open(encoding=encoding, newline="") as stream:
            rows = normalized(iter(csv.reader(stream, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")))
            yield next(rows), rows


def load_session(path):
    behavior_files = sorted(
    f for f in path.glob("P*_day[0-9]*.csv")
    if re.fullmatch(r"P\d+_day\d+\.csv", f.name)
)
    if len(behavior_files) != 1:
        raise ValueError("指定フォルダには P001_day1.csv などの行動ログを1つ置いてください。")
    behavior = csv_rows(behavior_files[0])
    if not behavior:
        raise ValueError("本実験の行動ログが空です。")
    participant, day = identity(behavior[0], KEY[:2])
    if behavior_files[0].name != f"{participant}_day{day}.csv":
        raise ValueError("行動ログのファイル名と参加者ID・日番号が一致しません。")
    trials = {row["trial_id"]: row for row in behavior}
    if len(trials) != len(behavior) or any(identity(row, KEY[:2]) != (participant, day) for row in behavior):
        raise ValueError("行動ログに複数の参加者・実施日または重複試行があります。")
    events = csv_rows(path / f"{participant}_day{day}_events.csv")
    if not events:
        raise ValueError("イベントログが空です。")
    segments, windows, phase_keys = {}, [], set()
    active, pending, marker = None, None, None
    for row in events:
        event = row["event"]
        segment_match = SEGMENT_RE.fullmatch(event)
        phase_match = PHASE_RE.fullmatch(event)
        if event in ("SYNC", "RESUME_SYNC"):
            if active is not None or marker is not None:
                raise ValueError("SYNCの位置が不正です。")
            marker = row
        if segment_match:
            number, action = int(segment_match[1]), segment_match[2]
            if action == "START":
                if active is not None or marker is None or number != len(segments) + 1:
                    raise ValueError("録画区間の開始順が不正です。")
                active = number
                segments[number] = {"anchor": marker, "start": row, "events": [marker], "windows": []}
                marker = None
            elif active != number or pending is not None:
                raise ValueError("録画区間の終了位置が不正です。")
        if active is None:
            if phase_match:
                raise ValueError("録画区間外に試行イベントがあります。")
            continue
        segment = segments[active]
        segment["events"].append(row)
        if phase_match:
            phase, order, action = phase_match[1].lower(), int(phase_match[2]), phase_match[3]
            trial = trials.get(row["trial_id"])
            if trial is None or (int(trial["presentation_order"]), int(trial["recording_segment"])) != (order, active):
                raise ValueError(f"行動ログとイベントログが一致しません: {event} / {row['trial_id']}")
            key = (row["trial_id"], phase)
            if action == "START" and pending is None and key not in phase_keys:
                pending = (key, row)
            elif action == "END" and pending is not None and pending[0] == key:
                window = dict(zip(KEY, (participant, day, active, *key)))
                window.update(start=pending[1], end=row)
                windows.append(window)
                segment["windows"].append(window)
                phase_keys.add(key)
                pending = None
            else:
                raise ValueError(f"試行画面の開始と終了が対応しません: {event}")
        if segment_match and segment_match[2] == "END":
            segment["end"] = row
            active = None
    if (active is not None or pending is not None or marker is not None
            or phase_keys != {(trial, phase) for trial in trials for phase in PHASES}):
        raise ValueError("録画区間または4画面のイベントが不足しています。")
    return segments


def assignments(items, convert):
    result = {}
    for item in items:
        key, value = item.split("=", 1)
        index = int(key)
        if index < 1 or index in result:
            raise ValueError("録画区間の番号は正の整数で、各区間を1回ずつ指定してください。")
        result[index] = convert(value)
    return result


def locate_recordings(session, segments, supplied):
    if set(supplied) - set(segments):
        raise ValueError("イベントログにない録画区間が指定されました。")
    files = {}
    for number in segments:
        candidates = [supplied[number]] if number in supplied else [
            session / f"tobii_{number:02d}{suffix}" for suffix in SUPPORTED
        ]
        found = [file for file in candidates if file.is_file() and file.suffix.lower() in SUPPORTED]
        if len(found) != 1:
            raise ValueError(f"区間{number}に対応するTSV・CSV・XLSXを1つ指定してください。")
        files[number] = found[0].resolve()
    if len(set(files.values())) != len(files):
        raise ValueError("同じTobiiファイルが複数の区間に指定されています。")
    return files


def clock_mapper(segment, manual_us):
    if manual_us is not None:
        if not math.isfinite(manual_us) or manual_us <= 0:
            raise ValueError("--anchorには対応するクリックの正のComputer timestamp（µs）を指定してください。")
        epoch = float(segment["anchor"]["timestamp"])
        return "manual", lambda event: manual_us + (float(event["timestamp"]) - epoch) * 1_000_000
    if any(finite(event.get("qpc_us")) is None for event in segment["events"]):
        raise ValueError("イベントログにWindows QPCがありません。収録済みなら同じSYNCクリックを確認して --anchor を指定してください。")
    return "qpc", lambda event: int(event["qpc_us"])


def recording_epoch(row):
    date, clock = row.get("recording date utc"), row.get("recording start time utc")
    if not date or not clock:
        return None
    try:
        instant = datetime.fromisoformat(f"{str(date).replace('/', '-').split()[0]}T{clock}")
        return instant.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def sync_segment(segment, number, path, manual_us, scale, samples, phases, events, reports, selected_name=None):
    method, qpc = clock_mapper(segment, manual_us)
    anchor = qpc(segment["anchor"])
    starts, ends = [], []
    for window in segment["windows"]:
        starts.append(qpc(window["start"]))
        ends.append(qpc(window["end"]))
    if not starts or any(start >= end for start, end in zip(starts, ends)) or any(
        previous > current for previous, current in zip(ends, starts[1:])
    ):
        raise ValueError(f"区間{number}の画面時刻が不正です。")

    counts = Counter()
    recording_name = origin = recording_end = first_eye = last_eye = None
    utc_difference = None
    with tobii_rows(path) as (headers, rows):
        for row in rows:
            name = str(row.get("recording name") or "").strip()
            if selected_name is not None and name != selected_name:
                continue
            if not name:
                if row.get("sensor") or row.get("event"):
                    raise ValueError(f"{path.name} に録画名の空欄があります。")
                continue
            if recording_name is None:
                recording_name = name
            if name != recording_name:
                raise ValueError(f"{path.name} に複数録画があります。--combined と --exclude を使ってください。")
            rt = finite(row.get("recording timestamp"))
            ct = finite(row.get("computer timestamp"))
            if row.get("event") == "RecordingStart":
                if origin is not None or ct is None or rt is None:
                    raise ValueError(f"{path.name} のRecordingStartが不正です。")
                origin = ct - rt * scale
                epoch = recording_epoch(row)
                if epoch is not None:
                    utc_difference = float(segment["anchor"]["timestamp"]) - (epoch + (anchor - origin) / 1_000_000)
                    if abs(utc_difference) > 5:
                        raise ValueError(f"{path.name} の録画開始UTCがアプリ時刻と{utc_difference:.1f}秒ずれています。対応する録画を確認してください。")
            if row.get("event") == "RecordingEnd":
                if recording_end is not None or ct is None:
                    raise ValueError(f"{path.name} のRecordingEndが不正です。")
                recording_end = ct
            if str(row.get("sensor") or "").strip().casefold() != "eye tracker":
                continue
            if origin is None or rt is None or ct is None:
                raise ValueError(f"{path.name} の視線行の時刻またはRecordingStartがありません。")
            if abs(ct - origin - rt * scale) > max(2000, scale):
                raise ValueError(f"{path.name} の時刻単位が一致しません。--recording-unit を確認してください。")
            if last_eye is not None and ct <= last_eye:
                raise ValueError(f"{path.name} の視線時刻が重複または逆行しています。")
            first_eye = ct if first_eye is None else first_eye
            last_eye = ct
            index = bisect_right(starts, ct) - 1
            if index < 0 or ct >= ends[index]:
                continue
            counts[index] += 1
            window = segment["windows"][index]
            values = {out: row.get(source) for out, source in SAMPLE_COLUMNS.items()}
            samples.writerow({**{key: window[key] for key in KEY}, **values,
                              "computer_us": int(ct), "recording_sec": rt * scale / 1_000_000,
                              "phase_elapsed_sec": round((ct - starts[index]) / 1_000_000, 6)})

    if (origin is None or recording_end is None or first_eye is None
            or not (origin <= anchor <= starts[0] < ends[-1] <= recording_end)
            or not sum(counts.values())):
        raise ValueError(f"{path.name} が区間{number}のSYNCと全試行時刻をカバーしていません。録画ファイルと単位を確認してください。")
    for index, window in enumerate(segment["windows"]):
        phases.writerow({**{key: window[key] for key in KEY},
                         "start_computer_us": round(starts[index]), "end_computer_us": round(ends[index]),
                         "phase_duration_sec": (ends[index] - starts[index]) / 1_000_000,
                         "sample_count": counts[index], "sync_method": method})
    for row in segment["events"]:
        event_us = qpc(row)
        events.writerow({"recording_segment": number, "event": row["event"], "trial_id": row["trial_id"],
                         "phase": row["phase"], "unix_timestamp": row["timestamp"],
                         "computer_us": round(event_us), "recording_sec": (event_us - origin) / 1_000_000})
    reports.writerow({"recording_segment": number, "recording_name": recording_name, "file": path.name,
                      "method": method, "sync_recording_sec": (anchor - origin) / 1_000_000,
                      "seconds_after_last_trial": (recording_end - ends[-1]) / 1_000_000,
                      "utc_difference_sec": utc_difference, "matched_samples": sum(counts.values()),
                      "phases_without_samples": len(starts) - len(counts),
                      "movement_columns": int({"eye movement type", "eye movement type index"} <= set(headers))})


def discover_recordings(path):
    """Excel/CSV/TSV内の録画名を初出順に収集する。"""
    found = []
    seen = set()
    with tobii_rows(path) as (_, rows):
        for row in rows:
            name = str(row.get("recording name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                found.append(name)
    return found


def choose_files(args, session, segments):
    if args.combined is None:
        files = choose_files(args, session, segments)
        return {number: (path, None) for number, path in files.items()}
    if args.recording:
        raise ValueError("--combined と --recording は同時指定できません。")
    path = args.combined.resolve()
    if not path.is_file():
        raise ValueError(f"Tobiiファイルがありません: {path}")
    names = [n for n in discover_recordings(path) if n not in args.exclude]
    if len(names) != len(segments):
        raise ValueError(
            f"有効な録画数 {len(names)} と実験側の録画区間数 {len(segments)} が一致しません。"
            f" 録画名: {names}。不要な録画は --exclude で指定してください。")
    print("録画の対応（開始順）:")
    for number, name in zip(sorted(segments), names):
        print(f"  区間{number} = {name}")
    return {number: (path, name) for number, name in zip(sorted(segments), names)}


def run(args):
    session = args.session.resolve()
    segments = load_session(session)
    files = choose_files(args, session, segments)
    anchors = assignments(args.anchor, float)
    if set(anchors) - set(segments):
        raise ValueError("--anchorにイベントログにない区間番号があります。")
    output = session / "sync"
    output.mkdir(exist_ok=True)
    schemas = {
        "synced_gaze_samples.csv": KEY + SAMPLE_FIELDS,
        "phase_windows.csv": KEY + ("start_computer_us", "end_computer_us", "phase_duration_sec", "sample_count", "sync_method"),
        "aligned_events.csv": ("recording_segment", "event", "trial_id", "phase", "unix_timestamp", "computer_us", "recording_sec"),
        "sync_report.csv": ("recording_segment", "recording_name", "file", "method", "sync_recording_sec",
                            "seconds_after_last_trial", "utc_difference_sec", "matched_samples",
                            "phases_without_samples", "movement_columns"),
    }
    from contextlib import ExitStack
    with TemporaryDirectory(dir=output) as temp:
        stage = Path(temp)
        with ExitStack() as stack:
            writers = [writer(stack.enter_context((stage / name).open("w", encoding="utf-8-sig", newline="")), fields)
                       for name, fields in schemas.items()]
            for number, segment in segments.items():
                path, name = files[number]
                sync_segment(segment, number, path, anchors.get(number),
                             1 if args.recording_unit == "us" else 1000, *writers,
                             selected_name=name)
        for name in schemas:
            (stage / name).replace(output / name)
    print(f"同期完了: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True, help="日別ログの入ったフォルダ")
    parser.add_argument("--combined", type=Path, help="複数録画を含むTobii Excel/CSV/TSV")
    parser.add_argument("--exclude", action="append", default=[], help="除外する録画名。複数指定可")
    parser.add_argument("--recording", action="append", default=[], metavar="区間=ファイル")
    parser.add_argument("--recording-unit", choices=("us", "ms"), default="us")
    parser.add_argument("--anchor", action="append", default=[], metavar="区間=Computer_timestamp_us")
    try:
        run(parser.parse_args())
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        parser.exit(2, f"同期エラー: {exc}\n")
