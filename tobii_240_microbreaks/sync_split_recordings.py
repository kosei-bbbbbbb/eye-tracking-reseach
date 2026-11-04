# -*- coding: utf-8 -*-
"""複数のTobii Pro Lab録画を、休憩を挟む1つの本実験ログに同期する。

例:
 python sync_split_recordings.py --gaze-dir results/P002/tobii_recordings \
   --events results/P002/P002_events.csv --behavior results/P002/P002.csv \
   --outdir results/P002/synced

録画ファイルは録画開始日時順に並べ、SYNC/RESUME_SYNCの区間と1対1で対応付ける。
録画ファイルの欠落・時刻の大きな不一致・区間の視線欠落はエラーにする。
"""
import argparse
from pathlib import Path
import importlib.util
import sys
import pandas as pd

BASE = Path(__file__).with_name('sync_gaze_events_4phase_base.py')
spec = importlib.util.spec_from_file_location('sync_gaze_base', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def event_segments(events):
    ev = base.prepare_events(events).sort_values('event_unix_time')
    starts = ev[ev['event'].astype(str).isin(['SYNC', 'RESUME_SYNC'])]
    if starts.empty:
        raise ValueError('SYNC/RESUME_SYNCイベントがありません。')
    end_events = ev[ev['event'].astype(str).isin(['BREAK_START', 'EXPERIMENT_END'])]
    segments = []
    for i, row in enumerate(starts.itertuples(index=False), 1):
        start = float(row.event_unix_time)
        ends = end_events[end_events['event_unix_time'] > start]
        if ends.empty:
            raise ValueError(f'録画区間{i}にBREAK_STARTまたはEXPERIMENT_ENDがありません。')
        end = float(ends.iloc[0]['event_unix_time'])
        segments.append((i, start, end))
    for a, b in zip(segments, segments[1:]):
        if a[2] > b[1]:
            raise ValueError('録画区間が重複しています。')
    return segments, ev


def run(args):
    paths = [Path(p) for p in (args.gaze or [])]
    if args.gaze_dir:
        directory = Path(args.gaze_dir)
        paths += sorted([*directory.glob('*.xlsx'), *directory.glob('*.csv')])
    paths = list(dict.fromkeys(paths))
    if not paths:
        raise ValueError('録画ファイルがありません。--gaze-dir または --gaze を指定してください。')
    events_raw = base.read_table(args.events, preserve_trial_id=True)
    behavior = base.read_table(args.behavior, preserve_trial_id=True) if args.behavior else None
    segments, events = event_segments(events_raw)
    intervals = base.build_phase_intervals_from_events(events)
    if len(paths) != len(segments):
        raise ValueError(f'録画ファイル{len(paths)}個、録画区間{len(segments)}個で数が一致しません。'
                         ' 休憩後の録画の保存漏れ、または余分な録画を確認してください。')
    recordings = []
    for path in paths:
        raw = base.read_table(path)
        gaze = base.add_gaze_unix_time(raw, timezone=args.timezone,
                                      time_shift_sec=args.time_shift_sec,
                                      timestamp_unit=args.timestamp_unit)
        if 'Sensor' in gaze.columns:
            gaze = gaze[gaze['Sensor'].astype(str).str.strip().eq('Eye Tracker')].copy()
        gaze = gaze[gaze['gaze_unix_time'].notna()].copy()
        if gaze.empty:
            raise ValueError(f'{path.name}: 有効なEye Tracker時刻がありません。')
        recordings.append((float(gaze['gaze_unix_time'].min()), path, gaze))
    recordings.sort(key=lambda item: item[0])
    synced_parts, interval_parts, quality_rows = [], [], []
    for (number, start, end), (_, path, gaze) in zip(segments, recordings):
        segment_intervals = intervals[(intervals['phase_start_time'] >= start)
                                      & (intervals['phase_end_time'] <= end)].copy()
        if segment_intervals.empty:
            raise ValueError(f'区間{number}: 対応する試行がありません。')
        # 半開区間で扱うことで隣接するフェーズ境界で二重割当しない。
        # 基本関数の <= end を使う前に end の境界サンプルを除外する。
        matched = base.attach_trial_phase(gaze, segment_intervals)
        if not matched.empty:
            matched = matched[matched['gaze_unix_time'] < matched['phase_end_time']].copy()
            matched['recording_segment'] = number
            matched['recording_file'] = path.name
            synced_parts.append(matched)
        interval_parts.append(segment_intervals.assign(recording_segment=number, recording_file=path.name))
        gaze_min, gaze_max = float(gaze['gaze_unix_time'].min()), float(gaze['gaze_unix_time'].max())
        first = float(segment_intervals['phase_start_time'].min())
        last = float(segment_intervals['phase_end_time'].max())
        if first < gaze_min - args.tolerance_sec or last > gaze_max + args.tolerance_sec:
            raise ValueError(f'区間{number}と録画 {path.name} の時刻範囲が一致しません。'
                             f' 試行 {first:.3f}～{last:.3f}, 視線 {gaze_min:.3f}～{gaze_max:.3f}。'
                             ' ファイル順序、時刻設定、録画開始・終了操作を確認してください。')
        quality_rows.append({'recording_segment': number, 'recording_file': path.name,
                             'gaze_first_unix': gaze_min, 'gaze_last_unix': gaze_max,
                             'segment_start_unix': start, 'segment_end_unix': end,
                             'trial_count': segment_intervals['trial_id'].nunique(),
                             'synced_samples': len(matched)})
    all_intervals = pd.concat(interval_parts, ignore_index=True)
    synced = pd.concat(synced_parts, ignore_index=True) if synced_parts else pd.DataFrame()
    if synced.empty:
        raise ValueError('同期できた視線サンプルがありません。')
    if synced.duplicated(subset=['recording_segment', 'gaze_unix_time', 'trial_id', 'phase']).any():
        print('注意: 同一時刻の視線サンプルがあります。元データの重複を確認してください。')
    # 各フェーズに視線サンプルがあるかを確認。短いフェーズでもゼロは要確認。
    observed = synced.groupby(['trial_id', 'phase']).size()
    missing = [(r.trial_id, r.phase) for r in all_intervals.itertuples(index=False)
               if observed.get((r.trial_id, r.phase), 0) == 0]
    if missing:
        raise ValueError(f'視線サンプルが0件のフェーズがあります: {missing[:10]}。'
                         '録画の開始・終了や同期時刻を確認してください。')
    synced = base.merge_behavior_metadata(synced, behavior)
    summary = base.make_trial_summary(synced, all_intervals, behavior)
    segment_meta = all_intervals[['trial_id', 'phase', 'recording_segment', 'recording_file']]
    summary = summary.merge(segment_meta, on=['trial_id', 'phase'], how='left', validate='one_to_one')
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    synced.to_csv(out / 'synced_gaze_samples.csv', index=False, encoding='utf-8-sig')
    summary.to_csv(out / 'trial_summary.csv', index=False, encoding='utf-8-sig')
    events.to_csv(out / 'aligned_events.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(quality_rows).to_csv(out / 'recording_segments.csv', index=False, encoding='utf-8-sig')
    print(f'同期完了: {len(recordings)}録画、{summary.trial_id.nunique()}試行、{len(synced)}視線サンプル')
    print(f'出力先: {out.resolve()}')
    print(pd.DataFrame(quality_rows).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gaze-dir', help='本実験の録画ファイルだけを入れたフォルダ')
    parser.add_argument('--gaze', nargs='+', help='録画ファイルを直接複数指定')
    parser.add_argument('--events', required=True, help='本実験用 Pxxx_events.csv')
    parser.add_argument('--behavior', help='本実験用 Pxxx.csv')
    parser.add_argument('--outdir', required=True)
    parser.add_argument('--timezone', default='Asia/Tokyo')
    parser.add_argument('--timestamp-unit', default='microseconds',
                        choices=['microseconds', 'milliseconds', 'seconds', 'auto'])
    parser.add_argument('--time-shift-sec', type=float, default=0.0)
    parser.add_argument('--tolerance-sec', type=float, default=2.0)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print('同期エラー:', exc, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
