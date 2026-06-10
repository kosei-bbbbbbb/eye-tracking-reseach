import csv
import os
import random
import re  # 拡張パース用の正規表現モジュールを追加
from dotenv import load_dotenv
from google import genai

# =====================================
# API
# =====================================
load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

INPUT_CSV = "texts.csv"
OUTPUT_CSV = "stimuli_with_quiz.csv"

# =====================================
# 出力CSV (ヘッダー作成)
# =====================================
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
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
# 文章読み込みとループ処理
# =====================================
with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
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
・1つは文章中の単語を含む表表面的誤答
・1つは誤解しやすい誤答

各選択肢に以下のtypeを付与すること

correct
misunderstanding_1
surface_match
misunderstanding_2

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
""",
            )

        except Exception as e:
            print("問題生成失敗:", e)
            continue

        quiz = response.text.strip()
        lines = quiz.split("\n")

        question = ""
        choices = []  # (記号, 文章) を格納
        choice_types = []  # typeの文字列を格納
        correct_answer = ""

        # 【ここを修正・強化しました】
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 「問題:」の抽出（マークダウンの「### 問題:」や「**問題:**」にも対応）
            if "問題:" in line:
                question = line.split("問題:", 1)[1].strip()
                continue

            # 「正解:」の抽出
            if "正解:" in line:
                correct_answer = (
                    line.split("正解:", 1)[1].strip().replace("**", "")
                )
                continue

            # 選択肢（A. B. C. D.）の抽出（太字 **A.** や単なる A. に対応）
            choice_match = re.search(r"^\*?诈?([A-D])\.\*?诈?\s*(.*)", line)
            if choice_match:
                label = choice_match.group(1)
                content = choice_match.group(2).strip()
                choices.append((label, content))
                continue

            # 「type:」の抽出（大文字小文字、太字、記号交じりに対応）
            type_match = re.search(
                r"type:\s*\*?([a-zA-Z_]+)\*?", line, re.IGNORECASE
            )
            if type_match:
                choice_types.append(type_match.group(1).strip())
                continue

        # エラーチェックの強化
        if len(choices) != 4 or len(choice_types) != 4 or not correct_answer:
            print(
                f"パース失敗: choices={len(choices)}, types={len(choice_types)}, correct={correct_answer}"
            )
            continue

        # シャッフル処理
        combined = []
        for i in range(4):
            combined.append({
                "text": choices[i][1],
                "type": choice_types[i],
                "is_correct": choices[i][0] == correct_answer,
            })

        random.shuffle(combined)

        labels = ["A", "B", "C", "D"]
        final_correct = ""

        for i in range(4):
            if combined[i]["is_correct"]:
                final_correct = labels[i]

        # 出力CSVへの追記
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
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

        print("保存完了")

print("\n終了")