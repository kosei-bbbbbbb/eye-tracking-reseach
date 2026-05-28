from google import genai
import os
from dotenv import load_dotenv
import jreadability

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

TARGET_MIN = 2.5
TARGET_MAX = 3.5
MAX_RETRY = 10
LENGTH = 400

for i in range(MAX_RETRY):

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""
        条件
        ・文長：{LENGTH}文字程度で誤差10%
        ・テーマ：専門性の高くない話題
        ・大学生向け
        
        """
    )

    text = response.text.strip()

    score = jreadability.jreadability.compute_readability(text)
    length = len(text)

    print(f"試行 {i+1}")
    print(f"score: {score}")
    print(f"length: {length}")
    print(text)
    print("-" * 50)

    if (
        TARGET_MIN <= score <= TARGET_MAX
        and LENGTH - 0.1*LENGTH <= length <= LENGTH + 0.1*LENGTH
    ):

        print("条件達成")

        # 4択問題生成
        quiz_response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"""
            次の文章に関する4択問題を1問作成してください。

            条件:
            ・内容一致問題
            ・4択はすべて文章
            ・正答
            ・誤解をされやすい誤答
            ・文章に出てきた単語を含む誤答
            ・明らかな誤答
            ・正答も明示

            文章:
            {text}
            """
        )

        quiz = quiz_response.text.strip()

        print("\n【4択問題】")
        print(quiz)

        break