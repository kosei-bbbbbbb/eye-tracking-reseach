import csv
import os
import random
import re
from dotenv import load_dotenv
from google import genai

# =====================================
# API
# =====================================
load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

INPUT_CSV = "texts.csv"
OUTPUT_CSV = "stimuli_with_quiz.csv"

# =====================================
# 出力CSVが存在しない場合だけヘッダー作成
# =====================================
if not os.path.exists(OUTPUT_CSV):

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "id",
            "condition",
            "score",
            "length",
            "text",
            "question",

            "choice_A",
            "choice_A_type",

            "choice_B",
            "choice_B_type",

            "choice_C",
            "choice_C_type",

            "choice_D",
            "choice_D_type",

            "correct_answer",
        ])

# =====================================
# すでに問題生成済みのIDを取得
# =====================================
existing_ids = set()

if os.path.exists(OUTPUT_CSV):

    with open(
        OUTPUT_CSV,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            if row.get("id"):
                existing_ids.add(row["id"])

print("既存の問題ID:", existing_ids)

# =====================================
# texts.csv を読み込み
# =====================================
with open(
    INPUT_CSV,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)

    for row in reader:

        # =====================================
        # すでに問題があるIDはスキップ
        # =====================================
        if row["id"] in existing_ids:

            print(
                f"id={row['id']} は生成済みなのでスキップ"
            )

            continue

        text = row["text"]

        print(
            f"\n新規問題生成中 id={row['id']}"
        )

        # =====================================
        # Geminiで問題生成
        # =====================================
        try:

            response = client.models.generate_content(

                model="gemini-2.5-flash",

                contents=f"""
次の文章に関する4択問題を1問作成してください。

条件:

・内容理解を必要とする問題
・4択
・選択肢はすべて自然な文章
・誤答に極端な表現を含めない
・本文を丁寧に読めば一意に正解できる
・表面的に読むと誤答しやすい問題にする

選択肢条件:

・1つは正答
・1つは本文内容を誤って解釈した誤答
・1つは文章中の単語を含む表面的な誤答
・1つは別の誤解に基づく誤答

各選択肢に以下のtypeを1つだけ付けること:

correct
misunderstanding_1
surface_match
misunderstanding_2

必ず次の形式で出力してください。

問題: xxx

A. xxx
type: correct

B. xxx
type: misunderstanding_1

C. xxx
type: surface_match

D. xxx
type: misunderstanding_2

正解: A

文章:
{text}
"""
            )

        except Exception as e:

            print(
                "問題生成失敗:",
                e
            )

            continue

        quiz = response.text.strip()

        # =====================================
        # Geminiの出力を解析
        # =====================================
        lines = quiz.split("\n")

        question = ""
        choices = []
        choice_types = []
        correct_answer = ""

        for line in lines:

            line = line.strip()

            if not line:
                continue

            # -----------------------------
            # 問題
            # -----------------------------
            if "問題:" in line:

                question = (
                    line.split(
                        "問題:",
                        1
                    )[1]
                    .replace("**", "")
                    .strip()
                )

                continue

            # -----------------------------
            # 正解
            # -----------------------------
            if "正解:" in line:

                correct_answer = (
                    line.split(
                        "正解:",
                        1
                    )[1]
                    .replace("**", "")
                    .strip()
                )

                # 「A.」などになった場合にも対応
                if correct_answer:
                    correct_answer = correct_answer[0]

                continue

            # -----------------------------
            # 選択肢
            # A. xxx
            # **A.** xxx
            # に対応
            # -----------------------------
            choice_match = re.search(
                r"^\**([A-D])\.\**\s*(.*)",
                line
            )

            if choice_match:

                label = choice_match.group(1)

                content = (
                    choice_match
                    .group(2)
                    .replace("**", "")
                    .strip()
                )

                choices.append(
                    (
                        label,
                        content
                    )
                )

                continue

            # -----------------------------
            # type
            # -----------------------------
            type_match = re.search(
                r"type\s*:\s*\**([a-zA-Z0-9_]+)\**",
                line,
                re.IGNORECASE
            )

            if type_match:

                choice_types.append(
                    type_match
                    .group(1)
                    .strip()
                )

                continue

        # =====================================
        # パースチェック
        # =====================================
        if (
            len(choices) != 4
            or len(choice_types) != 4
            or not question
            or not correct_answer
        ):

            print("パース失敗")

            print(
                f"question={question}"
            )

            print(
                f"choices={len(choices)}"
            )

            print(
                f"types={len(choice_types)}"
            )

            print(
                f"correct={correct_answer}"
            )

            print("\nGemini出力:")
            print(quiz)

            continue

        # =====================================
        # 選択肢とtypeをまとめる
        # =====================================
        combined = []

        for i in range(4):

            combined.append({

                "text":
                    choices[i][1],

                "type":
                    choice_types[i],

                "is_correct":
                    choices[i][0]
                    == correct_answer

            })

        # =====================================
        # A〜Dの位置をランダム化
        # =====================================
        random.shuffle(combined)

        labels = [
            "A",
            "B",
            "C",
            "D"
        ]

        final_correct = ""

        for i in range(4):

            if combined[i]["is_correct"]:

                final_correct = labels[i]

                break

        if not final_correct:

            print(
                "正解選択肢を特定できませんでした"
            )

            continue

        # =====================================
        # CSVに追記
        # =====================================
        with open(
            OUTPUT_CSV,
            "a",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.writer(f)

            writer.writerow([

                row["id"],
                row["condition"],
                row["score"],
                row["length"],
                row["text"],

                question,

                combined[0]["text"],
                combined[0]["type"],

                combined[1]["text"],
                combined[1]["type"],

                combined[2]["text"],
                combined[2]["type"],

                combined[3]["text"],
                combined[3]["type"],

                final_correct,

            ])

        print(
            f"id={row['id']} 保存完了"
        )

        # 今回生成したIDも既存扱いにする
        existing_ids.add(row["id"])

print("\n全処理終了")