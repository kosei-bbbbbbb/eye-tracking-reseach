"""起動後に刺激CSVのファイルを指定させ、その中身を15人分・2日分の出題CSVに分割する。"""

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

LEVELS = ("easy", "medium", "hard")
DAY_ONE_ORDERS = (
    ("easy", "medium", "hard"),
    ("medium", "hard", "easy"),
    ("hard", "easy", "medium"),
    ("hard", "medium", "easy"),
    ("easy", "hard", "medium"),
    ("medium", "easy", "hard"),
)
PER_LEVEL = 80  # 参加者の割付に使う1条件あたりの問題数(40問×2日)
REQUIRED = {
    "id", "condition", "text", "question", "choice_A", "choice_B",
    "choice_C", "choice_D", "correct_answer",
}


def read_stimuli(path):
    for encoding in ("utf-8-sig", "cp932"):
        try:
            with path.open(encoding=encoding, newline="") as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames or []
                if REQUIRED.difference(fields) or len(fields) != len(set(fields)):
                    raise ValueError("刺激CSVのヘッダーを確認してください。")
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("文字コードを判別できません(UTF-8かShift-JISにしてください)。")

    counts = Counter(row["condition"] for row in rows)
    if set(counts) != set(LEVELS) or len(set(counts.values())) != 1 or counts["easy"] < PER_LEVEL:
        raise ValueError(
            f"easy・medium・hardを同数(各{PER_LEVEL}問以上)にしてください。現在の件数: {dict(counts)}"
        )
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("ヘッダーと列数が一致しない行があります。")
        if any(not row[field].strip() for field in REQUIRED):
            raise ValueError("必須項目に空欄があります。")
        if row["correct_answer"].strip() not in {"A", "B", "C", "D"}:
            raise ValueError(f"ID {row['id']} の正答をA〜Dで指定してください。")
    if len({row["id"].strip() for row in rows}) != len(rows):
        raise ValueError("刺激CSVのIDが重複しています。")
    return fields, rows


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate(source, output, seed):
    fields, rows = read_stimuli(source)
    rng = random.Random(seed)
    pools = {level: [row for row in rows if row["condition"] == level] for level in LEVELS}
    for pool in pools.values():
        rng.shuffle(pool)
        del pool[PER_LEVEL:]  # 各条件が80問を超える場合は無作為に80問を使う
    # Three participants per cyclic order and two per reverse order on day 1.
    groups = [group for group in range(6) for _ in range(3 if group < 3 else 2)]
    rng.shuffle(groups)

    output.mkdir(parents=True, exist_ok=False)
    assignments = []
    for index, group in enumerate(groups):
        participant = f"P{index + 1:03d}"
        order = DAY_ONE_ORDERS[group]
        offset = index * 80 // 15
        rotated = {level: pool[offset:] + pool[:offset] for level, pool in pools.items()}
        for day, day_order in enumerate((order, order[::-1]), start=1):
            schedule = []
            start = (day - 1) * 40
            for level in day_order:
                block = rotated[level][start:start + 40]
                rng.shuffle(block)
                schedule.extend(block)
            filename = f"{participant}_day{day}.csv"
            write_csv(output / filename, fields, schedule)
            assignments.append({
                "participant_id": participant,
                "group": group + 1,
                "day": day,
                "block_1": day_order[0],
                "block_2": day_order[1],
                "block_3": day_order[2],
                "stimuli_file": filename,
            })
    write_csv(output / "participant_allocation.csv", list(assignments[0]), assignments)


def ask_file():
    """起動時にファイルのパスを尋ねる(ドラッグ&ドロップや引用符付きのパスも可)。"""
    while True:
        text = input("分割する刺激CSVのファイルを指定してください(パスを入力かドラッグ&ドロップ): ")
        path = Path(text.strip().strip("\"'")).expanduser()
        if path.is_file():
            return path
        print(f"ファイルが見つかりません: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stimuli", type=Path, nargs="?", help="省略すると起動後に尋ねます")
    parser.add_argument("--out", type=Path, default=None, help="出力先フォルダ(省略時は元ファイル名_split)")
    parser.add_argument("--seed", type=int, default=20261112)
    args = parser.parse_args()
    source = args.stimuli if args.stimuli else ask_file()
    output = args.out or source.with_name(f"{source.stem}_split")
    try:
        generate(source, output, args.seed)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"出題CSV 30件と参加者割付表を作成しました: {output}")


if __name__ == "__main__":
    main()
