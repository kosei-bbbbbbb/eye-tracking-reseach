from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# 設定
# ============================================================

# 確信度の分類基準
# 4以上：高確信
# 2以下：低確信
HIGH_CONFIDENCE = 4
LOW_CONFIDENCE = 2

# 難易度の表示順
CONDITION_ORDER = ["easy", "medium", "hard"]


# ============================================================
# CSVファイル選択
# ============================================================

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

input_csv = filedialog.askopenfilename(
    title="分析する回答データCSVを選択してください",
    filetypes=[
        ("CSVファイル", "*.csv"),
        ("すべてのファイル", "*.*")
    ]
)

root.destroy()

if not input_csv:
    print("ファイルが選択されなかったため終了します。")
    raise SystemExit


input_path = Path(input_csv)

print("=" * 60)
print("選択されたファイル")
print(input_path)
print("=" * 60)


# ============================================================
# 出力フォルダ作成
# ============================================================

OUTPUT_DIR = input_path.parent / "behavior_analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"\n分析結果の保存先:\n{OUTPUT_DIR}")


# ============================================================
# CSV読み込み
# ============================================================

df = pd.read_csv(input_csv)

print("\nCSV読み込み完了")
print(f"試行数   : {len(df)}")
print(f"被験者数 : {df['participant_id'].nunique()}")


# ============================================================
# 必要な列が存在するか確認
# ============================================================

required_columns = [
    "participant_id",
    "trial_id",
    "condition",
    "length",
    "reading_time_sec",
    "answer_time_sec",
    "correct_answer",
    "participant_answer",
    "correct",
    "understanding",
    "confidence"
]

missing_columns = [
    col for col in required_columns
    if col not in df.columns
]

if missing_columns:
    print("\nエラー：必要な列がありません。")
    print(missing_columns)
    raise SystemExit


# ============================================================
# 前処理
# ============================================================

# 読書速度（文字/秒）
df["reading_speed_char_per_sec"] = (
    df["length"] / df["reading_time_sec"]
)

# 正答率表示用
df["correct_percent"] = df["correct"] * 100


# ============================================================
# 状態分類
# ============================================================
#
# 正答 + 高確信 → appropriate_understanding
# 正答 + 低確信 → low_confidence_correct
# 誤答 + 高確信 → overconfidence
# 誤答 + 低確信 → non_understanding
# 確信度3など → other
#
# ============================================================

def classify_state(row):

    correct = row["correct"]
    confidence = row["confidence"]

    if correct == 1 and confidence >= HIGH_CONFIDENCE:
        return "appropriate_understanding"

    elif correct == 1 and confidence <= LOW_CONFIDENCE:
        return "low_confidence_correct"

    elif correct == 0 and confidence >= HIGH_CONFIDENCE:
        return "overconfidence"

    elif correct == 0 and confidence <= LOW_CONFIDENCE:
        return "non_understanding"

    else:
        return "other"


df["state"] = df.apply(classify_state, axis=1)


# ============================================================
# 1. 全体正答率
# ============================================================

overall_accuracy = df["correct"].mean() * 100

overall_summary = pd.DataFrame({
    "num_trials": [len(df)],
    "num_correct": [int(df["correct"].sum())],
    "num_incorrect": [int((df["correct"] == 0).sum())],
    "accuracy_percent": [overall_accuracy]
})

overall_summary.to_csv(
    OUTPUT_DIR / "01_overall_accuracy.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 1. 全体正答率 =====")
print(f"試行数 : {len(df)}")
print(f"正答数 : {int(df['correct'].sum())}")
print(f"誤答数 : {int((df['correct'] == 0).sum())}")
print(f"正答率 : {overall_accuracy:.1f}%")


# ============================================================
# 2. 難易度別正答率
# ============================================================

condition_accuracy = (
    df.groupby("condition")
    .agg(
        num_trials=("correct", "size"),
        num_correct=("correct", "sum"),
        accuracy=("correct", "mean")
    )
    .reset_index()
)

condition_accuracy["num_incorrect"] = (
    condition_accuracy["num_trials"]
    - condition_accuracy["num_correct"]
)

condition_accuracy["accuracy_percent"] = (
    condition_accuracy["accuracy"] * 100
)

condition_accuracy.to_csv(
    OUTPUT_DIR / "02_accuracy_by_condition.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 2. 難易度別正答率 =====")

for condition in CONDITION_ORDER:

    row = condition_accuracy[
        condition_accuracy["condition"] == condition
    ]

    if len(row) > 0:
        row = row.iloc[0]

        print(
            f"{condition:6s} : "
            f"{int(row['num_correct'])}/"
            f"{int(row['num_trials'])} "
            f"({row['accuracy_percent']:.1f}%)"
        )


# ============================================================
# 3. 難易度別理解度
# ============================================================

understanding_by_condition = (
    df.groupby("condition")
    .agg(
        num_trials=("understanding", "size"),
        mean_understanding=("understanding", "mean"),
        std_understanding=("understanding", "std")
    )
    .reset_index()
)

understanding_by_condition.to_csv(
    OUTPUT_DIR / "03_understanding_by_condition.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 3. 難易度別平均理解度 =====")

for condition in CONDITION_ORDER:

    row = understanding_by_condition[
        understanding_by_condition["condition"] == condition
    ]

    if len(row) > 0:
        row = row.iloc[0]

        print(
            f"{condition:6s} : "
            f"{row['mean_understanding']:.2f}"
        )


# ============================================================
# 4. 難易度別確信度
# ============================================================

confidence_by_condition = (
    df.groupby("condition")
    .agg(
        num_trials=("confidence", "size"),
        mean_confidence=("confidence", "mean"),
        std_confidence=("confidence", "std")
    )
    .reset_index()
)

confidence_by_condition.to_csv(
    OUTPUT_DIR / "04_confidence_by_condition.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 4. 難易度別平均確信度 =====")

for condition in CONDITION_ORDER:

    row = confidence_by_condition[
        confidence_by_condition["condition"] == condition
    ]

    if len(row) > 0:
        row = row.iloc[0]

        print(
            f"{condition:6s} : "
            f"{row['mean_confidence']:.2f}"
        )


# ============================================================
# 5. 難易度別 読書時間・読書速度
# ============================================================

reading_by_condition = (
    df.groupby("condition")
    .agg(
        num_trials=("trial_id", "size"),

        mean_reading_time_sec=(
            "reading_time_sec",
            "mean"
        ),

        std_reading_time_sec=(
            "reading_time_sec",
            "std"
        ),

        mean_reading_speed=(
            "reading_speed_char_per_sec",
            "mean"
        ),

        std_reading_speed=(
            "reading_speed_char_per_sec",
            "std"
        )
    )
    .reset_index()
)

reading_by_condition.to_csv(
    OUTPUT_DIR / "05_reading_by_condition.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 5. 難易度別読書時間・読書速度 =====")

for condition in CONDITION_ORDER:

    row = reading_by_condition[
        reading_by_condition["condition"] == condition
    ]

    if len(row) > 0:
        row = row.iloc[0]

        print(
            f"{condition:6s} : "
            f"読書時間 "
            f"{row['mean_reading_time_sec']:.2f} 秒 / "
            f"読書速度 "
            f"{row['mean_reading_speed']:.2f} 文字/秒"
        )


# ============================================================
# 6. 難易度別回答時間
# ============================================================

answer_time_by_condition = (
    df.groupby("condition")
    .agg(
        num_trials=("answer_time_sec", "size"),
        mean_answer_time_sec=("answer_time_sec", "mean"),
        std_answer_time_sec=("answer_time_sec", "std")
    )
    .reset_index()
)

answer_time_by_condition.to_csv(
    OUTPUT_DIR / "06_answer_time_by_condition.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 6. 難易度別平均回答時間 =====")

for condition in CONDITION_ORDER:

    row = answer_time_by_condition[
        answer_time_by_condition["condition"] == condition
    ]

    if len(row) > 0:
        row = row.iloc[0]

        print(
            f"{condition:6s} : "
            f"{row['mean_answer_time_sec']:.2f} 秒"
        )


# ============================================================
# 7. 正答 / 誤答別
# ============================================================

correctness_comparison = (
    df.groupby("correct")
    .agg(
        num_trials=("trial_id", "size"),

        mean_understanding=(
            "understanding",
            "mean"
        ),

        std_understanding=(
            "understanding",
            "std"
        ),

        mean_confidence=(
            "confidence",
            "mean"
        ),

        std_confidence=(
            "confidence",
            "std"
        ),

        mean_reading_time_sec=(
            "reading_time_sec",
            "mean"
        ),

        mean_reading_speed=(
            "reading_speed_char_per_sec",
            "mean"
        ),

        mean_answer_time_sec=(
            "answer_time_sec",
            "mean"
        )
    )
    .reset_index()
)

correctness_comparison["correct_label"] = (
    correctness_comparison["correct"].map({
        0: "incorrect",
        1: "correct"
    })
)

correctness_comparison.to_csv(
    OUTPUT_DIR / "07_correct_incorrect_comparison.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 7. 正答 / 誤答比較 =====")

for _, row in correctness_comparison.iterrows():

    print(
        f"{row['correct_label']} : "
        f"理解度={row['mean_understanding']:.2f}, "
        f"確信度={row['mean_confidence']:.2f}, "
        f"読書時間={row['mean_reading_time_sec']:.2f}秒, "
        f"回答時間={row['mean_answer_time_sec']:.2f}秒"
    )


# ============================================================
# 8. 各試行の状態分類
# ============================================================

state_trials = df[
    [
        "participant_id",
        "trial_id",
        "condition",
        "score",
        "length",
        "correct_answer",
        "participant_answer",
        "correct",
        "understanding",
        "confidence",
        "reading_time_sec",
        "reading_speed_char_per_sec",
        "answer_time_sec",
        "state"
    ]
].copy()

state_trials.to_csv(
    OUTPUT_DIR / "08_trial_state_classification.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 8. 各試行の状態 =====")

print(
    state_trials[
        [
            "participant_id",
            "trial_id",
            "condition",
            "correct",
            "understanding",
            "confidence",
            "state"
        ]
    ].to_string(index=False)
)


# ============================================================
# 9. 状態別件数
# ============================================================

state_order = [
    "appropriate_understanding",
    "low_confidence_correct",
    "overconfidence",
    "non_understanding",
    "other"
]

state_counts = (
    df["state"]
    .value_counts()
    .reindex(state_order, fill_value=0)
    .rename_axis("state")
    .reset_index(name="count")
)

state_counts["percent"] = (
    state_counts["count"] / len(df) * 100
)

state_counts.to_csv(
    OUTPUT_DIR / "09_state_counts.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n===== 9. 状態別件数 =====")

for _, row in state_counts.iterrows():

    print(
        f"{row['state']:27s} : "
        f"{int(row['count'])} "
        f"({row['percent']:.1f}%)"
    )


# ============================================================
# 10. 難易度 × 状態
# ============================================================

condition_state = pd.crosstab(
    df["condition"],
    df["state"]
)

condition_state = condition_state.reindex(
    index=CONDITION_ORDER,
    fill_value=0
)

condition_state = condition_state.reindex(
    columns=state_order,
    fill_value=0
)

condition_state.to_csv(
    OUTPUT_DIR / "10_condition_state_counts.csv",
    encoding="utf-8-sig"
)

print("\n===== 難易度 × 状態 =====")
print(condition_state)


# ============================================================
# 11. 被験者別正答率
# ============================================================

participant_accuracy = (
    df.groupby("participant_id")
    .agg(
        num_trials=("trial_id", "size"),
        num_correct=("correct", "sum"),
        accuracy=("correct", "mean")
    )
    .reset_index()
)

participant_accuracy["accuracy_percent"] = (
    participant_accuracy["accuracy"] * 100
)

participant_accuracy.to_csv(
    OUTPUT_DIR / "11_accuracy_by_participant.csv",
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# 全試行データ保存
# ============================================================

df.to_csv(
    OUTPUT_DIR / "all_trials_with_analysis.csv",
    index=False,
    encoding="utf-8-sig"
)


# ============================================================
# グラフ用関数
# ============================================================

def condition_reindex(data, value_column):

    temp = (
        data
        .set_index("condition")
        .reindex(CONDITION_ORDER)
    )

    return temp[value_column]


# ============================================================
# グラフ1
# 難易度別正答率
# ============================================================

values = condition_reindex(
    condition_accuracy,
    "accuracy_percent"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.ylim(0, 100)

plt.xlabel("Condition")
plt.ylabel("Accuracy (%)")
plt.title("Accuracy by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_01_accuracy_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ2
# 難易度別理解度
# ============================================================

values = condition_reindex(
    understanding_by_condition,
    "mean_understanding"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.ylim(0, 5)

plt.xlabel("Condition")
plt.ylabel("Mean Understanding")
plt.title("Understanding by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_02_understanding_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ3
# 難易度別確信度
# ============================================================

values = condition_reindex(
    confidence_by_condition,
    "mean_confidence"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.ylim(0, 5)

plt.xlabel("Condition")
plt.ylabel("Mean Confidence")
plt.title("Confidence by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_03_confidence_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ4
# 難易度別読書時間
# ============================================================

values = condition_reindex(
    reading_by_condition,
    "mean_reading_time_sec"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.xlabel("Condition")
plt.ylabel("Reading Time (sec)")
plt.title("Reading Time by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_04_reading_time_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ5
# 難易度別読書速度
# ============================================================

values = condition_reindex(
    reading_by_condition,
    "mean_reading_speed"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.xlabel("Condition")
plt.ylabel("Characters / sec")
plt.title("Reading Speed by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_05_reading_speed_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ6
# 難易度別回答時間
# ============================================================

values = condition_reindex(
    answer_time_by_condition,
    "mean_answer_time_sec"
)

plt.figure(figsize=(7, 5))

plt.bar(
    CONDITION_ORDER,
    values
)

plt.xlabel("Condition")
plt.ylabel("Answer Time (sec)")
plt.title("Answer Time by Condition")

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_06_answer_time_by_condition.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ7
# 状態別件数
# ============================================================

plt.figure(figsize=(10, 5))

plt.bar(
    state_counts["state"],
    state_counts["count"]
)

plt.xlabel("State")
plt.ylabel("Number of Trials")
plt.title("Number of Trials by State")

plt.xticks(
    rotation=20,
    ha="right"
)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_07_state_counts.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ8
# 理解度 × 確信度
# ============================================================

plt.figure(figsize=(7, 6))

correct_df = df[df["correct"] == 1]
incorrect_df = df[df["correct"] == 0]

plt.scatter(
    correct_df["understanding"],
    correct_df["confidence"],
    marker="o",
    s=80,
    label="Correct"
)

plt.scatter(
    incorrect_df["understanding"],
    incorrect_df["confidence"],
    marker="x",
    s=100,
    label="Incorrect"
)

plt.xlim(0.5, 5.5)
plt.ylim(0.5, 5.5)

plt.xticks([1, 2, 3, 4, 5])
plt.yticks([1, 2, 3, 4, 5])

plt.xlabel("Understanding")
plt.ylabel("Confidence")
plt.title("Understanding vs Confidence")

plt.legend()

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_08_understanding_confidence.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ9
# 読書時間 × 確信度
# ============================================================

plt.figure(figsize=(7, 5))

plt.scatter(
    df["reading_time_sec"],
    df["confidence"],
    s=80
)

plt.xlabel("Reading Time (sec)")
plt.ylabel("Confidence")
plt.title("Reading Time vs Confidence")

plt.yticks([1, 2, 3, 4, 5])

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "graph_09_reading_time_confidence.png",
    dpi=300
)

plt.close()


# ============================================================
# グラフ10
# 読書速度 × 正誤
# ============================================================

correct_speed = (
    df[df["correct"] == 1]
    ["reading_speed_char_per_sec"]
    .dropna()
)

incorrect_speed = (
    df[df["correct"] == 0]
    ["reading_speed_char_per_sec"]
    .dropna()
)

box_data = []
box_labels = []

if len(correct_speed) > 0:
    box_data.append(correct_speed)
    box_labels.append("Correct")

if len(incorrect_speed) > 0:
    box_data.append(incorrect_speed)
    box_labels.append("Incorrect")

if box_data:

    plt.figure(figsize=(7, 5))

    plt.boxplot(
        box_data,
        tick_labels=box_labels
    )

    plt.ylabel("Characters / sec")
    plt.title("Reading Speed by Correctness")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "graph_10_reading_speed_correctness.png",
        dpi=300
    )

    plt.close()


# ============================================================
# グラフ11
# 回答時間 × 正誤
# ============================================================

correct_answer_time = (
    df[df["correct"] == 1]
    ["answer_time_sec"]
    .dropna()
)

incorrect_answer_time = (
    df[df["correct"] == 0]
    ["answer_time_sec"]
    .dropna()
)

box_data = []
box_labels = []

if len(correct_answer_time) > 0:
    box_data.append(correct_answer_time)
    box_labels.append("Correct")

if len(incorrect_answer_time) > 0:
    box_data.append(incorrect_answer_time)
    box_labels.append("Incorrect")

if box_data:

    plt.figure(figsize=(7, 5))

    plt.boxplot(
        box_data,
        tick_labels=box_labels
    )

    plt.ylabel("Answer Time (sec)")
    plt.title("Answer Time by Correctness")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "graph_11_answer_time_correctness.png",
        dpi=300
    )

    plt.close()


# ============================================================
# 終了
# ============================================================

print("\n" + "=" * 60)
print("分析完了")
print("=" * 60)

print(f"\n全体正答率 : {overall_accuracy:.1f}%")

print("\n状態内訳")

for _, row in state_counts.iterrows():

    print(
        f"{row['state']:27s} : "
        f"{int(row['count'])} "
        f"({row['percent']:.1f}%)"
    )

print("\n分析結果の保存先:")
print(OUTPUT_DIR)

print("\nCSVとグラフの保存が完了しました。")