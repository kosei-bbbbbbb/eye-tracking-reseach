import csv
import os
import random
import time
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError


# =====================================
# API設定
# =====================================
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError(
        "GEMINI_API_KEYが設定されていません。\n"
        ".envファイルを確認してください。"
    )

client = genai.Client(api_key=API_KEY)


# =====================================
# ファイル設定
# =====================================
# livedoor_quiz.pyが存在するフォルダ
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

INPUT_CSV = os.path.join(
    BASE_DIR,
    "selected_articles.csv"
)

OUTPUT_CSV = os.path.join(
    BASE_DIR,
    "stimuli_with_quiz.csv"
)


# =====================================
# Gemini設定
# =====================================
MODEL_NAME = "gemini-2.5-flash"

# 1回の実行で新しく生成する問題数
# 最初は6件程度で確認する
# hard → medium → easyが2周分生成される
#
# 全件生成する場合は None にする
MAX_ARTICLES = 6

# 1記事あたりの再試行回数
MAX_RETRIES = 3

# API呼び出し間隔
API_WAIT_SECONDS = 3


# =====================================
# Geminiから受け取る形式
# =====================================
ChoiceType = Literal[
    "correct",
    "misunderstanding_1",
    "surface_match",
    "misunderstanding_2",
]


class QuizChoice(BaseModel):
    text: str = Field(
        description="選択肢の文章"
    )

    type: ChoiceType = Field(
        description="選択肢の種類"
    )


class Quiz(BaseModel):
    question: str = Field(
        description="本文の内容理解を問う問題"
    )

    choices: list[QuizChoice] = Field(
        description="4つの選択肢",
        min_length=4,
        max_length=4,
    )


# =====================================
# 出力CSVの列
# =====================================
# 実験プログラム側で使用する列名
OUTPUT_FIELDS = [
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
]


# =====================================
# スコアから難易度を決定
# =====================================
def get_condition(score_value: str) -> str:
    """
    jReadabilityスコアから難易度を決める。

    score < 2.5:
        hard

    2.5 <= score < 4.5:
        medium

    score >= 4.5:
        easy
    """

    try:
        score = float(score_value)

    except (TypeError, ValueError):
        raise ValueError(
            "jreadabilityを数値に変換できません。\n"
            f"値: {score_value}"
        )

    if score >= 4.5:
        return "easy"

    if score >= 2.5:
        return "medium"

    return "hard"


# =====================================
# ファイル確認
# =====================================
def check_input_file() -> None:
    """
    入力CSVが存在するか確認する。
    """

    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(
            "selected_articles.csvが見つかりません。\n"
            f"確認した場所: {INPUT_CSV}"
        )


# =====================================
# 入力CSVの列確認
# =====================================
def validate_input_columns(
    fieldnames: list[str] | None,
) -> None:
    """
    selected_articles.csvに必要な列があるか確認する。
    """

    if fieldnames is None:
        raise ValueError(
            "selected_articles.csvに"
            "ヘッダーがありません。"
        )

    required_columns = {
        "article_id",
        "category",
        "date",
        "title",
        "char_count",
        "jreadability",
        "url",
        "body",
    }

    missing_columns = (
        required_columns - set(fieldnames)
    )

    if missing_columns:
        raise ValueError(
            "selected_articles.csvに"
            "必要な列がありません。\n"
            f"不足している列: {missing_columns}"
        )


# =====================================
# 出力CSVを初期化
# =====================================
def initialize_output_csv() -> None:
    """
    出力CSVがない場合だけヘッダーを作成する。
    """

    if os.path.exists(OUTPUT_CSV):
        return

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()


# =====================================
# 既存CSVの列確認
# =====================================
def validate_output_columns() -> None:
    """
    既存のstimuli_with_quiz.csvが
    現在の形式と一致するか確認する。
    """

    if not os.path.exists(OUTPUT_CSV):
        return

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(
                "stimuli_with_quiz.csvに"
                "ヘッダーがありません。"
            )

        if reader.fieldnames != OUTPUT_FIELDS:
            raise ValueError(
                "既存のstimuli_with_quiz.csvの列が"
                "現在の形式と一致しません。\n"
                "古いstimuli_with_quiz.csvを削除してから"
                "再実行してください。\n\n"
                f"現在の列:\n{reader.fieldnames}\n\n"
                f"必要な列:\n{OUTPUT_FIELDS}"
            )


# =====================================
# 処理済み文章を取得
# =====================================
def get_processed_texts() -> set[str]:
    """
    出力CSVにすでに保存されている本文を取得する。

    再実行時に同じ文章を重複生成しないために使う。
    """

    if not os.path.exists(OUTPUT_CSV):
        return set()

    processed_texts = set()

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            text = row.get(
                "text",
                "",
            ).strip()

            if text:
                processed_texts.add(text)

    return processed_texts


# =====================================
# 次の刺激IDを取得
# =====================================
def get_next_stimulus_number() -> int:
    """
    既存CSVの最大IDの次の番号を返す。

    例:
    既存IDが000〜005なら6を返す。
    """

    if not os.path.exists(OUTPUT_CSV):
        return 0

    existing_numbers = []

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            stimulus_id = row.get(
                "id",
                "",
            ).strip()

            if stimulus_id.isdigit():
                existing_numbers.append(
                    int(stimulus_id)
                )

    if not existing_numbers:
        return 0

    return max(existing_numbers) + 1


# =====================================
# 難易度ごとに分類
# =====================================
def group_rows_by_condition(
    rows: list[dict],
) -> dict[str, list[dict]]:
    """
    文章をhard、medium、easyに分類する。

    各難易度内では元CSVの順番を維持する。
    """

    grouped_rows = {
        "hard": [],
        "medium": [],
        "easy": [],
    }

    invalid_count = 0

    for row_number, row in enumerate(
        rows,
        start=1,
    ):
        score_value = row.get(
            "jreadability",
            "",
        ).strip()

        try:
            condition = get_condition(
                score_value
            )

        except ValueError as e:
            print()
            print(
                f"スキップ: 入力CSVの行={row_number}"
            )
            print(e)

            invalid_count += 1
            continue

        # 後で利用できるように格納
        row["_condition"] = condition
        row["_source_row_number"] = row_number

        grouped_rows[condition].append(row)

    print()
    print("========== 難易度別の記事数 ==========")
    print(
        f"hard:   {len(grouped_rows['hard'])}件"
    )
    print(
        f"medium: {len(grouped_rows['medium'])}件"
    )
    print(
        f"easy:   {len(grouped_rows['easy'])}件"
    )
    print(
        f"スコア不正: {invalid_count}件"
    )

    return grouped_rows


# =====================================
# hard→medium→easyに並べる
# =====================================
def arrange_rows_by_condition(
    grouped_rows: dict[str, list[dict]],
) -> list[dict]:
    """
    hard、medium、easyを1件ずつ交互に並べる。

    出力例:
    hard 1件目
    medium 1件目
    easy 1件目
    hard 2件目
    medium 2件目
    easy 2件目
    ...

    ある難易度の記事がなくなった場合は、
    残っている難易度だけで続ける。
    """

    arranged_rows = []

    condition_order = [
        "hard",
        "medium",
        "easy",
    ]

    max_count = max(
        len(grouped_rows["hard"]),
        len(grouped_rows["medium"]),
        len(grouped_rows["easy"]),
    )

    for index in range(max_count):
        for condition in condition_order:
            condition_rows = grouped_rows[
                condition
            ]

            if index < len(condition_rows):
                arranged_rows.append(
                    condition_rows[index]
                )

    return arranged_rows


# =====================================
# 生成問題を検証
# =====================================
def validate_quiz(quiz: Quiz) -> None:
    """
    Geminiが生成した問題が
    指定形式を満たしているか確認する。
    """

    question = quiz.question.strip()

    if not question:
        raise ValueError(
            "問題文が空です。"
        )

    if len(quiz.choices) != 4:
        raise ValueError(
            "選択肢が4つではありません。\n"
            f"生成された数: {len(quiz.choices)}"
        )

    choice_types = [
        choice.type
        for choice in quiz.choices
    ]

    required_types = {
        "correct",
        "misunderstanding_1",
        "surface_match",
        "misunderstanding_2",
    }

    if set(choice_types) != required_types:
        raise ValueError(
            "選択肢typeが指定どおりではありません。\n"
            f"生成されたtype: {choice_types}"
        )

    if choice_types.count("correct") != 1:
        raise ValueError(
            "correctタイプが1つではありません。"
        )

    choice_texts = [
        choice.text.strip()
        for choice in quiz.choices
    ]

    if any(
        not text
        for text in choice_texts
    ):
        raise ValueError(
            "空の選択肢があります。"
        )

    if len(set(choice_texts)) != 4:
        raise ValueError(
            "重複している選択肢があります。"
        )


# =====================================
# Geminiで問題生成
# =====================================
def generate_quiz(
    text: str,
    title: str,
) -> Quiz:
    """
    記事本文から4択問題を1問生成する。
    """

    prompt = f"""
以下の記事を読んだ人を対象とする、
内容理解問題を1問作成してください。

【作問の目的】
単なる単語、固有名詞、数値の暗記ではなく、
記事の要点、因果関係、主体、目的、立場、
出来事同士の関係を理解しているかを測定します。

【問題文の条件】
・本文を読めば正解を一意に判断できること
・本文にない外部知識を必要としないこと
・本文の主要な内容について問うこと
・細かすぎる固有名詞や数値の暗記だけを問わないこと
・曖昧な問題を作らないこと
・複数の選択肢が正解にならないこと
・問題文だけから正解を推測できないこと
・問題文に正解の表現をそのまま含めないこと
・本文に明記された内容、または本文から直接推論できる内容を問うこと
・問題文は自然な日本語の疑問文または選択問題文にすること

【選択肢】
以下の4種類を必ず1つずつ作成してください。

1. correct
本文の内容と一致する唯一の正答です。

2. misunderstanding_1
本文の主体、目的、原因と結果、立場などを
取り違えた場合に選びやすい誤答です。

3. surface_match
本文中に実際に登場する単語や表現を含みますが、
問題への回答としては不適切な表面的誤答です。

4. misunderstanding_2
misunderstanding_1とは異なる種類の理解の誤りに
基づく誤答です。

【選択肢全体の条件】
・4つとも自然な日本語の文章にすること
・4つの長さをできるだけそろえること
・4つの文体と具体性をそろえること
・正答だけを長くしたり詳しくしたりしないこと
・正答だけが不自然に分かりやすくならないようにすること
・正答だけが本文と同じ表現にならないようにすること
・「必ず」「完全に」「一切」「絶対に」などの
  極端な表現を避けること
・明らかに無関係な誤答を作らないこと
・誤答にも一定のもっともらしさを持たせること
・選択肢にA、B、C、Dなどの記号を付けないこと
・選択肢にtype名を書かないこと
・正解位置を示さないこと
・4つすべてを文章形式にすること

記事タイトル:
{title}

記事本文:
{text}
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=Quiz,
        ),
    )

    if response.parsed is not None:
        quiz = response.parsed

    else:
        if not response.text:
            raise ValueError(
                "Geminiから空の応答が返されました。"
            )

        quiz = Quiz.model_validate_json(
            response.text
        )

    validate_quiz(quiz)

    return quiz


# =====================================
# CSVへ保存
# =====================================
def save_quiz(
    source_row: dict,
    quiz: Quiz,
    stimulus_number: int,
) -> tuple[str, str]:
    """
    選択肢をランダムに並べ、
    実験プログラム用CSVへ保存する。
    """

    shuffled_choices = list(
        quiz.choices
    )

    random.shuffle(
        shuffled_choices
    )

    labels = [
        "A",
        "B",
        "C",
        "D",
    ]

    correct_answer = ""

    for index, choice in enumerate(
        shuffled_choices
    ):
        if choice.type == "correct":
            correct_answer = labels[index]
            break

    if not correct_answer:
        raise ValueError(
            "正解選択肢が見つかりません。"
        )

    # 000、001、002...の形式
    stimulus_id = f"{stimulus_number:03d}"

    score = source_row[
        "jreadability"
    ].strip()

    condition = get_condition(score)

    output_row = {
        "id": stimulus_id,
        "condition": condition,
        "score": score,
        "length": source_row[
            "char_count"
        ].strip(),
        "text": source_row[
            "body"
        ].strip(),
        "question": quiz.question.strip(),

        "choice_A": (
            shuffled_choices[0].text.strip()
        ),
        "choice_A_type": (
            shuffled_choices[0].type
        ),

        "choice_B": (
            shuffled_choices[1].text.strip()
        ),
        "choice_B_type": (
            shuffled_choices[1].type
        ),

        "choice_C": (
            shuffled_choices[2].text.strip()
        ),
        "choice_C_type": (
            shuffled_choices[2].type
        ),

        "choice_D": (
            shuffled_choices[3].text.strip()
        ),
        "choice_D_type": (
            shuffled_choices[3].type
        ),

        "correct_answer": correct_answer,
    }

    with open(
        OUTPUT_CSV,
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writerow(
            output_row
        )

    return stimulus_id, correct_answer


# =====================================
# メイン処理
# =====================================
def main() -> None:
    check_input_file()
    validate_output_columns()
    initialize_output_csv()

    processed_texts = get_processed_texts()

    next_stimulus_number = (
        get_next_stimulus_number()
    )

    success_count = 0
    failure_count = 0
    skipped_count = 0

    print()
    print("========== 設定 ==========")
    print(f"入力CSV: {INPUT_CSV}")
    print(f"出力CSV: {OUTPUT_CSV}")
    print(
        "次の刺激ID: "
        f"{next_stimulus_number:03d}"
    )
    print(
        "今回の生成数: "
        f"{MAX_ARTICLES}"
    )

    # =====================================
    # 入力CSVを読み込む
    # =====================================
    with open(
        INPUT_CSV,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        validate_input_columns(
            reader.fieldnames
        )

        source_rows = list(reader)

    # =====================================
    # 難易度ごとに分類
    # =====================================
    grouped_rows = group_rows_by_condition(
        source_rows
    )

    # =====================================
    # hard → medium → easyに並べる
    # =====================================
    arranged_rows = arrange_rows_by_condition(
        grouped_rows
    )

    print()
    print(
        "生成順: hard → medium → easy "
        "→ hard → medium → easy ..."
    )

    # =====================================
    # 問題生成
    # =====================================
    for order_number, row in enumerate(
        arranged_rows,
        start=1,
    ):
        if (
            MAX_ARTICLES is not None
            and success_count >= MAX_ARTICLES
        ):
            break

        source_row_number = row.get(
            "_source_row_number",
            "",
        )

        source_article_id = row.get(
            "article_id",
            "",
        ).strip()

        title = row.get(
            "title",
            "",
        ).strip()

        text = row.get(
            "body",
            "",
        ).strip()

        score = row.get(
            "jreadability",
            "",
        ).strip()

        condition = get_condition(score)

        # 本文が空の場合
        if not text:
            print()
            print(
                f"スキップ: 元CSV行={source_row_number}"
            )
            print(
                "理由: 本文が空です。"
            )

            skipped_count += 1
            continue

        # すでに問題生成済みの場合
        if text in processed_texts:
            print()
            print(
                f"スキップ: article_id="
                f"{source_article_id}"
            )
            print(
                "理由: すでに問題生成済みです。"
            )

            skipped_count += 1
            continue

        print()
        print(
            "================================"
        )
        print(
            f"生成順番号: {order_number}"
        )
        print(
            f"元CSV行: {source_row_number}"
        )
        print(
            f"元記事ID: {source_article_id}"
        )
        print(
            f"予定刺激ID: "
            f"{next_stimulus_number:03d}"
        )
        print(
            f"condition: {condition}"
        )
        print(
            f"score: {score}"
        )
        print(
            f"title: {title}"
        )

        quiz = None

        # =================================
        # API呼び出し
        # =================================
        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):
            try:
                quiz = generate_quiz(
                    text=text,
                    title=title,
                )

                break

            except (
                ValidationError,
                ValueError,
            ) as e:
                print()
                print(
                    "生成内容エラー: "
                    f"{attempt}/{MAX_RETRIES}"
                )
                print(e)

            except Exception as e:
                print()
                print(
                    "APIエラー: "
                    f"{attempt}/{MAX_RETRIES}"
                )
                print(e)

            if attempt < MAX_RETRIES:
                wait_seconds = attempt * 5

                print(
                    f"{wait_seconds}秒後に"
                    "再試行します。"
                )

                time.sleep(
                    wait_seconds
                )

        if quiz is None:
            print()
            print(
                "生成失敗: "
                f"article_id={source_article_id}"
            )

            failure_count += 1
            continue

        # =================================
        # CSV保存
        # =================================
        try:
            stimulus_id, correct_answer = (
                save_quiz(
                    source_row=row,
                    quiz=quiz,
                    stimulus_number=(
                        next_stimulus_number
                    ),
                )
            )

        except Exception as e:
            print()
            print(
                "保存失敗: "
                f"article_id={source_article_id}"
            )
            print(e)

            failure_count += 1
            continue

        processed_texts.add(
            text
        )

        success_count += 1
        next_stimulus_number += 1

        print()
        print(
            f"保存完了: ID={stimulus_id}"
        )
        print(
            f"condition: {condition}"
        )
        print(
            f"score: {score}"
        )
        print(
            f"正解: {correct_answer}"
        )

        # APIを短時間に連続で呼ばない
        time.sleep(
            API_WAIT_SECONDS
        )

    print()
    print(
        "========== 処理終了 =========="
    )
    print(
        f"新規生成成功: {success_count}"
    )
    print(
        f"生成失敗: {failure_count}"
    )
    print(
        f"スキップ: {skipped_count}"
    )
    print(
        f"次回開始ID: "
        f"{next_stimulus_number:03d}"
    )
    print(
        f"保存先: {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()