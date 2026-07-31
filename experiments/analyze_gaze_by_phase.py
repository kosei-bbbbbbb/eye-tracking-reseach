"""
analyze_gaze_three_phase.py

3状態（text / question / questionnaire）に同期済みの視線データを解析するプログラム。

想定入力:
- synced_gaze_samples.csv
    sync_gaze_behavior_three_phase.py で作成した同期済み視線データ
    必須: trial_id, phase
- trial_summary.csv
    sync_gaze_behavior_three_phase.py で作成した試行×phase要約
    必須: trial_id, phase

作るもの:
1. trial × phase ごとの視線散布図
2. phaseごとの区間時間グラフ
3. phaseごとのfixation数グラフ
4. phaseごとの平均fixation時間グラフ
5. 解析結果CSV basic_gaze_features_three_phase.csv

使い方:
python analyze_gaze_three_phase.py --input_dir "results/P001/synced_output" --out_dir "analysis/P001_three_phase"

または直接指定:
python analyze_gaze_three_phase.py ^
  --gaze "results/P001/synced_output/synced_gaze_samples.csv" ^
  --summary "results/P001/synced_output/trial_summary.csv" ^
  --out_dir "analysis/P001_three_phase"
"""

import argparse
from pathlib import Path
import warnings
import tkinter as tk
from tkinter import filedialog, messagebox

import pandas as pd
import matplotlib.pyplot as plt


PHASE_ORDER = {
    "text": 0,
    "reading": 0,
    "read": 0,
    "文章": 0,

    "question": 1,
    "answering": 1,
    "answer": 1,
    "問題": 1,
    "回答": 1,

    "questionnaire": 2,
    "survey": 2,
    "questionnaire_answering": 2,
    "アンケート": 2,
}

PHASE_LABEL = {
    "text": "T",
    "question": "Q",
    "questionnaire": "S",
}


def find_col(df, candidates, required=True):
    """候補名の中から、dfに存在する列を返す。"""
    for col in candidates:
        if col in df.columns:
            return col
    if required:
        raise KeyError(
            f"必要な列が見つかりません。候補: {candidates}\n"
            f"実際の列: {list(df.columns)}"
        )
    return None


def read_csv_safely(path):
    """日本語環境で文字化けしにくいようにCSVを読む。"""
    for enc in ["utf-8-sig", "utf-8", "cp932"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def prepare_paths(args):
    if args.input_dir is not None:
        input_dir = Path(args.input_dir)
        gaze_path = input_dir / "synced_gaze_samples.csv"
        summary_path = input_dir / "trial_summary.csv"
    else:
        gaze_path = Path(args.gaze)
        summary_path = Path(args.summary)

    if not gaze_path.exists():
        raise FileNotFoundError(f"視線データが見つかりません: {gaze_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"trial_summaryが見つかりません: {summary_path}")

    return gaze_path, summary_path




def select_paths_with_dialog():
    """同期済み視線データ、trial_summary、出力先をGUIで選択する。"""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        gaze_path = filedialog.askopenfilename(
            title="synced_gaze_samples.csvを選択してください",
            filetypes=[("CSV", "*.csv"), ("すべてのファイル", "*.*")],
            parent=root,
        )
        if not gaze_path:
            raise RuntimeError("視線データの選択がキャンセルされました。")

        gaze_path = Path(gaze_path)

        # 通常は同じフォルダにあるtrial_summary.csvを自動で使う。
        auto_summary = gaze_path.parent / "trial_summary.csv"
        if auto_summary.exists():
            summary_path = auto_summary
        else:
            selected_summary = filedialog.askopenfilename(
                title="trial_summary.csvを選択してください",
                initialdir=str(gaze_path.parent),
                filetypes=[("CSV", "*.csv"), ("すべてのファイル", "*.*")],
                parent=root,
            )
            if not selected_summary:
                raise RuntimeError("trial_summary.csvの選択がキャンセルされました。")
            summary_path = Path(selected_summary)

        default_out = gaze_path.parent / "analysis_output_three_phase"
        out_dir = filedialog.askdirectory(
            title="解析結果の出力先フォルダを選択してください",
            initialdir=str(gaze_path.parent),
            parent=root,
        )
        if not out_dir:
            # キャンセル時は同期済みデータと同じ場所に既定フォルダを作る。
            out_dir = str(default_out)

        return gaze_path, summary_path, Path(out_dir)
    finally:
        root.destroy()


def show_error_dialog(message):
    """GUIが利用できる場合にエラーを表示する。"""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("解析エラー", str(message), parent=root)
        root.destroy()
    except tk.TclError:
        pass


def show_complete_dialog(out_dir, feature_path, row_count):
    """GUIが利用できる場合に完了メッセージを表示する。"""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(
            "解析完了",
            f"解析が完了しました。\n\n出力先:\n{out_dir.resolve()}\n\n特徴量CSV:\n{feature_path.name}\n\n行数: {row_count}",
            parent=root,
        )
        root.destroy()
    except tk.TclError:
        pass


def normalize_phase_value(value):
    """phase表記を text / question / questionnaire に寄せる。"""
    s = str(value).strip().lower()

    if s in ["text", "reading", "read", "text_reading", "文章"]:
        return "text"
    if s in ["question", "answering", "answer", "question_answering", "問題", "回答"]:
        return "question"
    if s in ["questionnaire", "survey", "questionnaire_answering", "アンケート"]:
        return "questionnaire"

    return s


def add_normalized_phase(df):
    """phase列を追加または正規化する。"""
    phase_col = find_col(df, ["phase", "Phase", "section", "period"], required=False)

    if phase_col is None:
        warnings.warn(
            "phase列がないため、全データを phase='all' として扱います。"
            "3状態解析にはなりません。"
        )
        df = df.copy()
        df["phase"] = "all"
        return df

    df = df.copy()
    df["phase"] = df[phase_col].map(normalize_phase_value)
    return df


def sort_features(df):
    df = df.copy()
    df["_phase_order"] = df["phase"].map(PHASE_ORDER).fillna(99)
    df = df.sort_values(["trial_id", "_phase_order", "phase"]).drop(columns=["_phase_order"])
    return df


def get_gaze_xy_columns(gaze_df):
    """Tobiiの座標列を自動判定する。"""
    x_col = find_col(
        gaze_df,
        [
            "Gaze point X",
            "Gaze point X [DACS px]",
            "Gaze point X (MCSnorm)",
            "Fixation point X",
            "Fixation point X [DACS px]",
            "Fixation point X (MCSnorm)",
        ],
    )
    y_col = find_col(
        gaze_df,
        [
            "Gaze point Y",
            "Gaze point Y [DACS px]",
            "Gaze point Y (MCSnorm)",
            "Fixation point Y",
            "Fixation point Y [DACS px]",
            "Fixation point Y (MCSnorm)",
        ],
    )
    return x_col, y_col


def make_trial_phase_scatter_plots(gaze_df, out_dir):
    """trial × phase ごとの視線散布図を保存する。"""
    trial_col = find_col(gaze_df, ["trial_id", "trial", "Trial"])
    gaze_df = add_normalized_phase(gaze_df)

    x_col, y_col = get_gaze_xy_columns(gaze_df)

    use_invert_y = "MCSnorm" not in y_col

    scatter_dir = out_dir / "trial_phase_scatter"
    scatter_dir.mkdir(parents=True, exist_ok=True)

    for (trial_id, phase), tdf in gaze_df.groupby([trial_col, "phase"], dropna=False):
        plot_df = tdf[[x_col, y_col]].copy()
        plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors="coerce")
        plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")
        plot_df = plot_df.dropna()

        if plot_df.empty:
            continue

        plt.figure(figsize=(8, 5))
        plt.scatter(plot_df[x_col], plot_df[y_col], s=3, alpha=0.5)
        plt.title(f"Trial {trial_id} {phase} gaze scatter")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        if use_invert_y:
            plt.gca().invert_yaxis()
        plt.tight_layout()

        safe_phase = str(phase).replace("/", "_").replace("\\", "_")
        plt.savefig(scatter_dir / f"trial_{trial_id}_{safe_phase}_scatter.png", dpi=200)
        plt.close()

    return scatter_dir


def compute_fixation_features_by_phase(gaze_df):
    """trial × phase ごとのfixation数と平均fixation時間を計算する。"""
    trial_col = find_col(gaze_df, ["trial_id", "trial", "Trial"])
    df = add_normalized_phase(gaze_df)

    eye_type_col = find_col(
        df,
        ["Eye movement type", "eye_movement_type", "Eye movement type name"],
        required=False,
    )
    fix_index_col = find_col(
        df,
        ["Eye movement type index", "fixation_id", "Fixation index", "Fixation ID"],
        required=False,
    )
    duration_col = find_col(
        df,
        ["Eye movement event duration", "Fixation duration", "fixation_duration"],
        required=False,
    )

    if eye_type_col is not None:
        fix_df = df[df[eye_type_col].astype(str).str.lower().str.contains("fixation", na=False)].copy()
    else:
        fix_df = df.copy()
        warnings.warn("Eye movement type列がないため、全サンプルをfixation候補として扱います。")

    rows = []

    for (trial_id, phase), _tdf in df.groupby([trial_col, "phase"], dropna=False):
        tfix = fix_df[(fix_df[trial_col] == trial_id) & (fix_df["phase"] == phase)].copy()

        if tfix.empty:
            fixation_count = 0
            mean_fixation_duration = pd.NA
        elif fix_index_col is not None:
            # Tobiiでは同一fixationが複数サンプル行に繰り返し出るので、indexで重複排除する。
            unique_fix = tfix.dropna(subset=[fix_index_col]).drop_duplicates(
                subset=[trial_col, "phase", fix_index_col]
            )
            fixation_count = int(unique_fix.shape[0])
            if duration_col is not None:
                mean_fixation_duration = pd.to_numeric(unique_fix[duration_col], errors="coerce").mean()
            else:
                mean_fixation_duration = pd.NA
        else:
            # fixation indexがない場合はサンプル数に近い。厳密なfixation数ではない。
            fixation_count = int(tfix.shape[0])
            if duration_col is not None:
                mean_fixation_duration = pd.to_numeric(tfix[duration_col], errors="coerce").mean()
            else:
                mean_fixation_duration = pd.NA
            warnings.warn(
                "Eye movement type index列がないため、fixation数ではなく"
                "fixationサンプル数に近い値になります。"
            )

        rows.append(
            {
                "trial_id": trial_id,
                "phase": phase,
                "fixation_count": fixation_count,
                "mean_fixation_duration_ms": mean_fixation_duration,
            }
        )

    return sort_features(pd.DataFrame(rows))


def add_duration_sec(base):
    """phaseごとの時間を duration_sec として追加する。"""
    base = base.copy()

    # sync側のsummaryで duration_sec がすでにあればそれを優先する。
    if "duration_sec" in base.columns:
        base["duration_sec"] = pd.to_numeric(base["duration_sec"], errors="coerce")
        return base

    def pick_duration(row):
        phase = normalize_phase_value(row.get("phase"))

        # trial_summaryに phase_start/end がある場合
        start_col = f"{phase}_start_time"
        end_col = f"{phase}_end_time"
        if start_col in base.columns and end_col in base.columns:
            start = pd.to_numeric(row.get(start_col), errors="coerce")
            end = pd.to_numeric(row.get(end_col), errors="coerce")
            if pd.notna(start) and pd.notna(end):
                return end - start

        # 行動ログ由来の代表列
        if phase == "text" and "reading_time_sec" in base.columns:
            return row.get("reading_time_sec")
        if phase == "question" and "answer_time_sec" in base.columns:
            return row.get("answer_time_sec")
        if phase == "questionnaire" and "questionnaire_time_sec" in base.columns:
            return row.get("questionnaire_time_sec")

        # gazeの最初と最後から推定
        if "first_gaze_unix_time" in base.columns and "last_gaze_unix_time" in base.columns:
            first = pd.to_numeric(row.get("first_gaze_unix_time"), errors="coerce")
            last = pd.to_numeric(row.get("last_gaze_unix_time"), errors="coerce")
            if pd.notna(first) and pd.notna(last):
                return last - first

        return pd.NA

    base["duration_sec"] = base.apply(pick_duration, axis=1)
    return base


def build_feature_table_three_phase(gaze_df, summary_df):
    """trial_summaryとfixation特徴量を、trial_id × phaseで結合する。"""
    trial_col_summary = find_col(summary_df, ["trial_id", "trial", "Trial"])
    summary = add_normalized_phase(summary_df)

    keep_cols = [trial_col_summary, "phase"]
    candidate_cols = [
        "participant_id",
        "condition",
        "score",
        "length",
        "reading_time_sec",
        "answer_time_sec",
        "questionnaire_time_sec",
        "correct",
        "understanding",
        "confidence",
        "gaze_samples",
        "fixation_samples",
        "both_valid_rate",
        "first_gaze_unix_time",
        "last_gaze_unix_time",
        "mean_gaze_x",
        "mean_gaze_y",
        "mean_eye_movement_duration",
        "text_start_time",
        "text_end_time",
        "question_start_time",
        "question_end_time",
        "questionnaire_start_time",
        "questionnaire_end_time",
        "text_start_offset",
        "text_end_offset",
        "question_start_offset",
        "question_end_offset",
        "questionnaire_start_offset",
        "questionnaire_end_offset",
    ]

    for col in candidate_cols:
        if col in summary.columns and col not in keep_cols:
            keep_cols.append(col)

    base = summary[keep_cols].copy()
    if trial_col_summary != "trial_id":
        base = base.rename(columns={trial_col_summary: "trial_id"})

    base = add_duration_sec(base)

    fix_features = compute_fixation_features_by_phase(gaze_df)
    features = pd.merge(base, fix_features, on=["trial_id", "phase"], how="left")

    # text区間だけ読書速度を計算する。question/questionnaireでは意味が薄いので空にする。
    if "length" in features.columns and "duration_sec" in features.columns:
        length = pd.to_numeric(features["length"], errors="coerce")
        duration = pd.to_numeric(features["duration_sec"], errors="coerce")
        features["reading_speed_chars_per_sec"] = pd.NA
        mask = features["phase"].astype(str).str.lower().eq("text")
        features.loc[mask, "reading_speed_chars_per_sec"] = length[mask] / duration[mask].replace(0, pd.NA)

    return sort_features(features)


def bar_plot(features, y_col, title, ylabel, out_path):
    if y_col not in features.columns:
        warnings.warn(f"{y_col}列がないため、{title}は作成しません。")
        return

    df = features.copy()
    df[y_col] = pd.to_numeric(df[y_col], errors="coerce")
    df = df.dropna(subset=[y_col])
    if df.empty:
        warnings.warn(f"{y_col}がすべて空のため、{title}は作成しません。")
        return

    labels = []
    for _, row in df.iterrows():
        phase = str(row["phase"])
        phase_short = PHASE_LABEL.get(phase, phase)
        label = f"T{row['trial_id']}\n{phase_short}"
        labels.append(label)

    plt.figure(figsize=(14, 5))
    plt.bar(labels, df[y_col])
    plt.title(title)
    plt.xlabel("Trial / phase (T=text, Q=question, S=questionnaire)")
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def make_summary_plots(features, out_dir):
    bar_plot(
        features,
        "duration_sec",
        "Duration by trial and phase",
        "Duration (sec)",
        out_dir / "duration_by_trial_phase.png",
    )
    bar_plot(
        features,
        "fixation_count",
        "Fixation count by trial and phase",
        "Fixation count",
        out_dir / "fixation_count_by_trial_phase.png",
    )
    bar_plot(
        features,
        "mean_fixation_duration_ms",
        "Mean fixation duration by trial and phase",
        "Mean fixation duration (ms)",
        out_dir / "mean_fixation_duration_by_trial_phase.png",
    )


def make_phase_average_plots(features, out_dir):
    """phaseごとの平均を見る補助グラフ。"""
    numeric_cols = ["duration_sec", "fixation_count", "mean_fixation_duration_ms"]

    for col in numeric_cols:
        if col not in features.columns:
            continue
        tmp = features.copy()
        tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
        tmp = tmp.dropna(subset=[col])
        if tmp.empty:
            continue

        avg = tmp.groupby("phase", as_index=False)[col].mean()
        avg["_phase_order"] = avg["phase"].map(PHASE_ORDER).fillna(99)
        avg = avg.sort_values("_phase_order")

        labels = [PHASE_LABEL.get(p, p) for p in avg["phase"]]
        plt.figure(figsize=(6, 4))
        plt.bar(labels, avg[col])
        plt.title(f"Average {col} by phase")
        plt.xlabel("Phase (T=text, Q=question, S=questionnaire)")
        plt.ylabel(col)
        plt.tight_layout()
        plt.savefig(out_dir / f"average_{col}_by_phase.png", dpi=200)
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "3状態に同期済みの視線データを解析する。"
            "引数を指定しない場合はファイル選択画面を表示する。"
        )
    )
    parser.add_argument(
        "--input_dir",
        default=None,
        help="synced_gaze_samples.csv と trial_summary.csv が入ったフォルダ",
    )
    parser.add_argument("--gaze", default=None, help="synced_gaze_samples.csv のパス")
    parser.add_argument("--summary", default=None, help="trial_summary.csv のパス")
    parser.add_argument("--out_dir", default=None, help="出力先フォルダ")
    parser.add_argument(
        "--dialog",
        action="store_true",
        help="引数が指定されていてもファイル選択画面を使用する。",
    )
    args = parser.parse_args()

    use_dialog = args.dialog or (
        args.input_dir is None
        and args.gaze is None
        and args.summary is None
    )

    try:
        if use_dialog:
            gaze_path, summary_path, out_dir = select_paths_with_dialog()
        else:
            if args.input_dir is None and (args.gaze is None or args.summary is None):
                raise ValueError(
                    "--input_dir、または --gaze と --summary の両方を指定してください。"
                )

            gaze_path, summary_path = prepare_paths(args)
            out_dir = Path(args.out_dir or "analysis_output_three_phase")

        out_dir.mkdir(parents=True, exist_ok=True)

        gaze_df = read_csv_safely(gaze_path)
        summary_df = read_csv_safely(summary_path)

        scatter_dir = make_trial_phase_scatter_plots(gaze_df, out_dir)
        features = build_feature_table_three_phase(gaze_df, summary_df)

        feature_path = out_dir / "basic_gaze_features_three_phase.csv"
        features.to_csv(feature_path, index=False, encoding="utf-8-sig")

        make_summary_plots(features, out_dir)
        make_phase_average_plots(features, out_dir)

    except RuntimeError as exc:
        print(f"処理を中止しました: {exc}")
        return
    except Exception as exc:
        print(f"エラー: {exc}")
        show_error_dialog(exc)
        return

    print("解析が完了しました。")
    print(f"同期済み視線データ: {gaze_path}")
    print(f"試行要約データ: {summary_path}")
    print(f"出力先: {out_dir.resolve()}")
    print(f"Trial×phaseごとの散布図: {scatter_dir}")
    print(f"特徴量CSV: {feature_path}")
    print(f"特徴量の行数: {len(features)}")
    print("作成される主な画像:")
    print("- duration_by_trial_phase.png")
    print("- fixation_count_by_trial_phase.png")
    print("- mean_fixation_duration_by_trial_phase.png")
    print("- average_duration_sec_by_phase.png")
    print("- average_fixation_count_by_phase.png")
    print("- average_mean_fixation_duration_ms_by_phase.png")

    if len(features) > 0:
        print("\n行数確認:")
        print(features.groupby("phase").size().to_string())

    show_complete_dialog(out_dir, feature_path, len(features))


if __name__ == "__main__":
    main()