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
LENGTH = 400

CSV_FILE = "stimuli.csv"

# =====================================
# CSV初期化
# =====================================
if not os.path.exists(CSV_FILE):

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:

        writer = csv.writer(f)

        writer.writerow([
            "id",
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

for i in range(MAX_RETRY):

    # ---------------------------------
    # 文章生成
    # ---------------------------------
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""
        条件
        次の条件を厳密に守ってください
        ・文長：{LENGTH}文字程度で誤差20%
        ・テーマ：専門性の高くない話題
        ・自然な日本語
        ・説明調
        ・論説
        ・1段落
        """
    )

    text = response.text.strip()

    # ---------------------------------
    # readability
    # ---------------------------------
    score = jreadability.jreadability.compute_readability(text)
    length = len(text)

    print(f"\n試行 {i+1}")
    print(f"score: {score}")
    print(f"length: {length}")

    print(text)

    print("-" * 50)

    # ---------------------------------
    # 条件判定
    # ---------------------------------
    if (
        TARGET_MIN <= score <= TARGET_MAX
        and LENGTH - int(LENGTH * 0.2)
        <= length
        <= LENGTH + int(LENGTH * 0.2)
    ):

        print("条件達成")

        # =====================================
        # 4択問題生成
        # =====================================
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

        quiz = quiz_response.text.strip()

        print("\n【4択問題】")
        print(quiz)

        # =====================================
        # 問題解析
        # =====================================
        lines = quiz.split("\n")

        question = ""

        choices = []
        choice_types = []

        correct_answer = ""

        current_choice = ""

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

                current_choice = line[0]

                choice_text = line[2:].strip()

                choices.append((current_choice, choice_text))

            elif line.startswith("type:"):

                t = line.replace("type:", "").strip()

                choice_types.append(t)

            elif line.startswith("正解:"):

                correct_answer = line.replace("正解:", "").strip()

        # =====================================
        # 選択肢シャッフル
        # =====================================
        combined = []

        for idx in range(4):

            combined.append({
                "text": choices[idx][1],
                "type": choice_types[idx],
                "is_correct": (
                    choices[idx][0] == correct_answer
                )
            })

        random.shuffle(combined)

        labels = ["A", "B", "C", "D"]

        final_correct = ""

        for idx in range(4):

            if combined[idx]["is_correct"]:

                final_correct = labels[idx]

        # =====================================
        # CSV保存
        # =====================================
        with open(
            CSV_FILE,
            "a",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.writer(f)

            writer.writerow([

                stimulus_id,

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

        print("\nCSV保存完了")

        stimulus_id += 1

        break

print("\n処理終了")