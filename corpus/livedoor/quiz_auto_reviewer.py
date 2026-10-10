"""予備実験用4択問題のAI監査・修正ツール。元CSVは変更しません。"""
import csv
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from tkinter import Tk, filedialog, messagebox

from dotenv import load_dotenv
from google import genai
from google.genai import types

COLS = ['id','condition','score','length','text','question'] + [v for c in 'ABCD' for v in (f'choice_{c}',f'choice_{c}_type')] + ['correct_answer']
LETTERS = 'ABCD'
MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
MAX_ATTEMPTS = 3

PROMPT = '''あなたは日本語文章読解研究の刺激問題を査読する専門家です。文章読解直後に「問題を正しく解ける自信」を1～5で評価させ、その後4択を解く実験です。本文に忠実な問題と選択肢を作成してください。
絶対条件:
- text は改変しない（広告・関連記事など疑わしい箇所は flagged_text に報告するだけ）。
- 4択で正答は必ず一意。正答は本文から直接根拠を示せること。背景知識や未確認情報を必要としない。
- 問いは本文の主旨・因果・対比・筆者の見解など理解を問う。細かい固有名詞暗記・直接抜き出しを可能な範囲で避ける。
- 誤答3つはもっともらしいが本文に照らして明確に誤り。surface_match（本文の語句を用いるが結論は誤り）、misunderstanding_1（因果・関係の誤解）、misunderstanding_2（過度の一般化・立場の取り違え等）を各1つ。
- 選択肢の長さや断定調などから正答が浮かないようにする。
- 過信を誘発することを保証できない。予測は慎重に記載。
- 安全・倫理上の刺激として不適切、または元の文章の構造が悪い場合は replace_recommended=true とし理由を述べる。強引に正答を作らない。
- JSONのみを返す。形式は以下。
{"question":"...","correct_choice":"...","surface_match":"...","misunderstanding_1":"...","misunderstanding_2":"...","evidence":"本文からの短い根拠引用","issues":["..."],"flagged_text":["..."],"replace_recommended":false,"replace_reason":"","change_summary":"..."}
元データ:
'''

def normalize_condition(value):
    v = value.strip().lower()
    if v not in ('easy','medium','hard'):
        raise ValueError(f'不明な難易度: {value}')
    return v

def load_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or any(c not in reader.fieldnames for c in COLS):
            raise ValueError('必要な列がありません: ' + ', '.join(c for c in COLS if c not in (reader.fieldnames or [])))
        rows = list(reader)
    if not rows: raise ValueError('CSVにデータがありません')
    for i, row in enumerate(rows, 2):
        if not row['text'].strip(): raise ValueError(f'{i}行目のtextが空です')
        normalize_condition(row['condition'])
        if row['correct_answer'].strip().upper() not in LETTERS: raise ValueError(f'{i}行目の正答記号が不正です')
    return rows

def clean_json(s):
    s = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', s.strip(), flags=re.I)
    return json.loads(s)

def review(client, row):
    original = {k: row[k] for k in COLS}
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = client.models.generate_content(
                model=MODEL,
                contents=PROMPT + json.dumps(original, ensure_ascii=False),
                config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.2),
            )
            obj = clean_json(result.text or '')
            required = ('question','correct_choice','surface_match','misunderstanding_1','misunderstanding_2','evidence','issues','flagged_text','replace_recommended','replace_reason','change_summary')
            if any(k not in obj for k in required): raise ValueError('JSONの必須項目が不足')
            for k in required[:6]:
                if not isinstance(obj[k], str) or not obj[k].strip(): raise ValueError(f'{k} が空または文字列でない')
            for k in ('issues','flagged_text'):
                if not isinstance(obj[k], list): raise ValueError(f'{k} が配列でない')
            if not isinstance(obj['replace_recommended'], bool): raise ValueError('replace_recommended が真偽値でない')
            opts = [obj[k].strip() for k in ('correct_choice','surface_match','misunderstanding_1','misunderstanding_2')]
            if len(set(opts)) != 4: raise ValueError('重複する選択肢')
            return obj
        except Exception as exc:
            if attempt == MAX_ATTEMPTS - 1: raise RuntimeError(f'Gemini評価に失敗: {exc}') from exc
            time.sleep(2 ** attempt * 2)

def allocate_letters(rows, seed):
    """全体のA～D正答数の差を最大1にする。"""
    rng = random.Random(seed)
    letters = list(LETTERS) * (len(rows)//4) + list(LETTERS)[:len(rows)%4]
    rng.shuffle(letters)
    return letters, rng

def build_row(original, obj, correct_letter, rng):
    out = dict(original)
    out['question'] = obj['question'].strip()
    by_type = {'correct':obj['correct_choice'], 'surface_match':obj['surface_match'], 'misunderstanding_1':obj['misunderstanding_1'], 'misunderstanding_2':obj['misunderstanding_2']}
    other = [k for k in by_type if k != 'correct']
    rng.shuffle(other)
    for letter, typ in zip((c for c in LETTERS if c != correct_letter), other):
        out[f'choice_{letter}'] = by_type[typ].strip()
        out[f'choice_{letter}_type'] = typ
    out[f'choice_{correct_letter}'] = by_type['correct'].strip()
    out[f'choice_{correct_letter}_type'] = 'correct'
    out['correct_answer'] = correct_letter
    out['length'] = str(len(out['text']))
    return out

def write_csv(path, rows, fields):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)

def main():
    load_dotenv()
    root = Tk(); root.withdraw()
    path = filedialog.askopenfilename(title='問題CSVを選択', filetypes=[('CSV files','*.csv')])
    if not path: return
    try:
        rows = load_rows(path)
        if not os.getenv('GEMINI_API_KEY'): raise ValueError('GEMINI_API_KEYが設定されていません。.envを確認してください。')
        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        outdir = Path(path).parent / (Path(path).stem + '_reviewed')
        outdir.mkdir(exist_ok=True)
        seed = 20261010
        letters, rng = allocate_letters(rows, seed)
        fixed, reports = [], []
        for i, (row, letter) in enumerate(zip(rows, letters), 1):
            print(f'[{i}/{len(rows)}] ID={row["id"]} を評価中...', flush=True)
            try:
                obj = review(client, row)
                updated = build_row(row, obj, letter, rng)
                status = '要差し替え' if obj['replace_recommended'] else 'AI修正済み・人手確認待ち'
                fixed.append(updated)
                reports.append({'id':row['id'], 'condition':row['condition'], 'status':status, 'issues':' / '.join(map(str,obj['issues'])), 'flagged_text':' / '.join(map(str,obj['flagged_text'])), 'replace_reason':obj['replace_reason'], 'evidence':obj['evidence'], 'change_summary':obj['change_summary'], 'old_question':row['question'], 'new_question':updated['question'], 'old_correct':row['correct_answer'], 'new_correct':updated['correct_answer']})
            except Exception as exc:
                print(f'  エラー: {exc}。元問題を保持します。', file=sys.stderr)
                fixed.append(dict(row))
                reports.append({'id':row['id'],'condition':row['condition'],'status':'API失敗・未修正','issues':str(exc)})
            # 中断に備え、各問題ごとに保存
            write_csv(outdir/'stimuli_revised.csv', fixed, COLS)
            write_csv(outdir/'review_report.csv', reports, ['id','condition','status','issues','flagged_text','replace_reason','evidence','change_summary','old_question','new_question','old_correct','new_correct'])
        summary = {'count':len(fixed), 'difficulty':dict(Counter(r['condition'] for r in fixed)), 'correct_positions':dict(Counter(r['correct_answer'] for r in fixed)), 'statuses':dict(Counter(r['status'] for r in reports)), 'seed':seed, 'note':'AI評価は正答の妥当性や過信誘発を保証しません。人手確認後に実験に使用してください。'}
        (outdir/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        messagebox.showinfo('完了', f'保存先: {outdir}\n※要差し替えとAPI失敗を必ず確認してください。')
    except Exception as exc:
        messagebox.showerror('エラー', str(exc))
        raise
    finally:
        root.destroy()

if __name__ == '__main__':
    main()
