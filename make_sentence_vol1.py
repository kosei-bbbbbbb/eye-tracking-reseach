from google import genai
import os
from dotenv import load_dotenv
import jreadability
import csv
from datetime import datetime

# =====================================
# API
# =====================================
load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# =====================================
# 設定
# =====================================
LENGTH = 500

CSV_FILE = "texts.csv"

CONDITIONS = [
    {
        "name": "medium",
        "min_score": 2.5,
        "max_score": 3.5,
        "target_count": 1,
        "prompt": """
        大学生向け
        やや抽象的な内容を含む
        """
    }
    
]

# =====================================
# CSV初期化
# =====================================
if not os.path.exists(CSV_FILE):

    with open(
        CSV_FILE,
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
            "generated_at"
        ])

# =====================================
# ID自動取得
# =====================================
stimulus_id = 1

if os.path.exists(CSV_FILE):

    with open(
        CSV_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        rows = list(reader)

        if rows:
            stimulus_id = int(rows[-1]["id"]) + 1

for condition in CONDITIONS:

    print("\n====================")
    print(condition["name"])
    print("====================")

    saved_count = 0

    while saved_count < condition["target_count"]:

        try:

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"""
                次の条件を守って文章を生成してください。

                ・500文字程度
                ・専門知識不要
                ・自然な日本語
                ・1段落

                難易度条件:
                {condition["prompt"]}
                """
            )

        except Exception as e:

            print("APIエラー:", e)

            if "RESOURCE_EXHAUSTED" in str(e):
                print("無料枠上限に到達")
                exit()

            continue

        text = response.text.strip()

        try:
            score = jreadability.jreadability.compute_readability(text)
        except:
            continue

        length = len(text)

        if not (
            condition["min_score"]
            <= score
            <= condition["max_score"]
        ):
            continue

        if not (
            LENGTH - 100
            <= length
            <= LENGTH + 100
        ):
            continue

        print(
            f"{condition['name']} "
            f"{saved_count+1}/{condition['target_count']} "
            f"score={score:.2f}"
        )

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
                score,
                length,
                text,
                datetime.now().isoformat()
            ])

        stimulus_id += 1
        saved_count += 1

print("\n完了")