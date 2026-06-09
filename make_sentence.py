from google import genai
import os
from dotenv import load_dotenv
import jreadability
import csv
import random
from datetime import datetime

# =====================================
# 環境変数
# =====================================
load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# =====================================
# 条件
# =====================================
TARGET_MIN = 2.5
TARGET_MAX = 3.5
MAX_RETRY = 10
LENGTH = 500

CSV_FILE = "stimuli.csv"
CONDITIONS = [
    {
        "name": "easy",
        "min_score": 4.5,
        "max_score": 5.5,
        "target_count": 1,
        "prompt": """
        小学生でも理解できる平易な語彙を使う
        短い文を中心にする
        """
    },
    {
        "name": "medium",
        "min_score": 2.5,
        "max_score": 3.5,
        "target_count": 1,
        "prompt": """
        高校生,大学生向け
        やや抽象的な内容を含む
        """
    },
    {
        "name": "hard",
        "min_score": 1.5,
        "max_score": 2.5,
        "target_count": 1,
        "prompt": """
        学術的な語彙を用いる
        複雑な文構造を使う
        抽象概念を説明する
        """
    }
]

# =====================================
# CSV初期化
# =====================================
if not os.path.exists(CSV_FILE):

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:

        writer = csv.writer(f)

        writer.writerow([
    "id",
    "condition",
    "text",
    "score",
    "length",

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

    "generated_at"
])

# =====================================
# メイン
# =====================================
stimulus_id = 1

for condition in CONDITIONS:

    print("\n====================")
    print(f"開始: {condition['name']}")
    print("====================")

    saved_count = 0

    while saved_count < condition["target_count"]:

        try:

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"""
                条件
                次の条件を厳密に守ってください

                ・文長：{LENGTH}文字程度で誤差20%
                ・自然な日本語
                ・1段落

                難易度条件:
                {condition["prompt"]}
                """
            )

        except Exception as e:

            print("APIエラー:", e)
            continue

        text = response.text.strip()

        score = jreadability.jreadability.compute_readability(text)
        length = len(text)

        if not (
            condition["min_score"]
            <= score
            <= condition["max_score"]
        ):
            continue

        if not (
            LENGTH - int(LENGTH * 0.2)
            <= length
            <= LENGTH + int(LENGTH * 0.2)
        ):
            continue

        print(
            f"\n[{condition['name']}] "
            f"{saved_count+1}/{condition['target_count']}"
        )

        print(f"score: {score}")
        print(f"length: {length}")
        print(text)

        try:

            quiz_response = client.models.generate_content(
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

                さらに:
                ・各選択肢に type を付ける
                ・type は以下のみ使用

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

        quiz = quiz_response.text.strip()

        lines = quiz.split("\n")

        question = ""
        choices = []
        choice_types = []
        correct_answer = ""

        for line in lines:

            line = line.strip()

            if line.startswith("問題:"):

                question = line.replace("問題:", "").strip()

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
                    line.replace("type:", "").strip()
                )

            elif line.startswith("正解:"):

                correct_answer = (
                    line.replace("正解:", "").strip()
                )

        if len(choices) != 4:
            continue

        if len(choice_types) != 4:
            continue

        combined = []

        for idx in range(4):

            combined.append({
                "text": choices[idx][1],
                "type": choice_types[idx],
                "is_correct": (
                    choices[idx][0]
                    == correct_answer
                )
            })

        random.shuffle(combined)

        labels = ["A", "B", "C", "D"]

        final_correct = ""

        for idx in range(4):

            if combined[idx]["is_correct"]:
                final_correct = labels[idx]

        with open(
            CSV_FILE,
            "a",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.writer(f)

            writer.writerow([

                stimulus_id,

                condition["name"],

                text,
                score,
                length,

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

                datetime.now().isoformat()

            ])

        print("CSV保存完了")

        stimulus_id += 1
        saved_count += 1

    print(
        f"\n{condition['name']} 完了 "
        f"({saved_count}件)"
    )

print("\n全条件終了")