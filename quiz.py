from google import genai
import os
from dotenv import load_dotenv
import csv
import random

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
# 出力CSV
# =====================================
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

        "correct_answer"
    ])

# =====================================
# 文章読み込み
# =====================================
with open(
    INPUT_CSV,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)

    for row in reader:

        text = row["text"]

        print(f"\n処理中 id={row['id']}")

        try:

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"""
次の文章に関する4択問題を1問作成してください。

条件:
・内容理解を必要とする問題
・4択
・選択肢はすべて文章

選択肢条件:
・1つは正答
・1つは誤解しやすい誤答
・1つは文章中の単語を含む表面的誤答
・1つは明らかな誤答

各選択肢に以下のtypeを付与すること

correct
misunderstanding
surface_match
obvious_wrong

出力形式:

問題: xxx

A. xxx
type: xxx

B. xxx
type: xxx

C. xxx
type: xxx

D. xxx
type: xxx

正解: A

文章:
{text}
"""
            )

        except Exception as e:

            print("問題生成失敗:", e)
            continue

        quiz = response.text.strip()

        lines = quiz.split("\n")

        question = ""
        choices = []
        choice_types = []
        correct_answer = ""

        for line in lines:

            line = line.strip()

            if line.startswith("問題:"):

                question = line.replace(
                    "問題:",
                    ""
                ).strip()

            elif (
                line.startswith("A.")
                or line.startswith("B.")
                or line.startswith("C.")
                or line.startswith("D.")
            ):

                choices.append(
                    (
                        line[0],
                        line[2:].strip()
                    )
                )

            elif line.startswith("type:"):

                choice_types.append(
                    line.replace(
                        "type:",
                        ""
                    ).strip()
                )

            elif line.startswith("正解:"):

                correct_answer = (
                    line.replace(
                        "正解:",
                        ""
                    ).strip()
                )

        if len(choices) != 4:

            print("選択肢数異常")
            continue

        if len(choice_types) != 4:

            print("type数異常")
            continue

        combined = []

        for i in range(4):

            combined.append({
                "text": choices[i][1],
                "type": choice_types[i],
                "is_correct":
                    choices[i][0]
                    == correct_answer
            })

        random.shuffle(combined)

        labels = ["A", "B", "C", "D"]

        final_correct = ""

        for i in range(4):

            if combined[i]["is_correct"]:

                final_correct = labels[i]

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

                final_correct
            ])

        print("保存完了")

print("\n終了")