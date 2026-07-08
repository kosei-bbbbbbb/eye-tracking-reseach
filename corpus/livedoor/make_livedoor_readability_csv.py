import csv
import re
import jreadability
from pathlib import Path

BASE_DIR = Path(__file__).parent
TEXT_DIR = BASE_DIR / "text"
OUTPUT_CSV = BASE_DIR / "livedoor_readability.csv"

MIN_CHARS = 400
MAX_CHARS = 600


def read_article(file_path):
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    if len(lines) < 4:
        return None

    url = lines[0].strip()
    date = lines[1].strip()
    title = lines[2].strip()
    body = "\n".join(lines[3:]).strip()
    body = re.sub(r"\s+", " ", body)

    return url, date, title, body


def calc_jreadability(text):
    try:
        return jreadability.jreadability.compute_readability(text)
    except Exception as e:
        print("jReadability計算エラー:", e)
        return None

    except Exception as e:
        print("jReadability計算エラー:", e)
        return None


def main():
    txt_files = list(TEXT_DIR.glob("*/*.txt"))
    print("txtファイル数:", len(txt_files))
    rows = []

    for file_path in txt_files:
        if file_path.name == "LICENSE.txt":
            continue

        article = read_article(file_path)
        if article is None:
            continue

        url, date, title, body = article
        category = file_path.parent.name
        article_id = file_path.stem
        char_count = len(body)

        if not (MIN_CHARS <= char_count <= MAX_CHARS):
            continue

        readability = calc_jreadability(body)

        rows.append({
            "article_id": article_id,
            "category": category,
            "date": date,
            "title": title,
            "char_count": char_count,
            "jreadability": readability,
            "url": url,
            "body": body,
        })

    rows.sort(key=lambda x: (x["jreadability"] is None, x["jreadability"]))

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "article_id",
                "category",
                "date",
                "title",
                "char_count",
                "jreadability",
                "url",
                "body",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("完了:", OUTPUT_CSV)
    print("抽出記事数:", len(rows))


if __name__ == "__main__":
    main()