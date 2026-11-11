import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, filedialog, simpledialog
import csv
import json
import re
from pathlib import Path
import os
import time
import random
import threading
try:
    import winsound
except ImportError:
    winsound = None
# 本文表示設定。負のフォントサイズを使い、Windowsのpt指定と区別する。

READING_TIME_LIMIT_SEC = 35
MAIN_DEFAULT_QUESTIONS = 240
BREAK_INTERVAL_SEC = 60 * 60  # 休憩を除いた本実験の経過時間
SHORT_BREAK_INTERVAL_SEC = 20 * 60  # 本実験の実働20分ごと
SHORT_BREAK_DURATION_SEC = 60  # 録画を継続する短い休憩
READING_WARNING_SECONDS = (15, 5)
READING_FONT_PX = 32
READING_LINE_PITCH_PX = 60
READING_MAX_WIDTH_PX = 1720
CONDITIONS = ("easy", "medium", "hard")
STIMULUS_COLUMNS = (
    "id", "condition", "score", "length", "text", "question",
    "choice_A", "choice_B", "choice_C", "choice_D", "correct_answer",
)
RESULTS_DIR = Path(__file__).resolve().parent / "results"

def make_qpc_clock():
    """Windows QPCをPro LabのComputer timestampと同じマイクロ秒で記録する。"""
    if os.name != "nt":
        return lambda: None
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    frequency = ctypes.c_longlong()
    if not kernel32.QueryPerformanceFrequency(ctypes.byref(frequency)):
        raise ctypes.WinError(ctypes.get_last_error())

    def read_qpc_us():
        ticks = ctypes.c_longlong()
        if not kernel32.QueryPerformanceCounter(ctypes.byref(ticks)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ticks.value * 1_000_000 // frequency.value

    return read_qpc_us


class Experiment:

    def __init__(self, root):

        self.root = root
        self.read_qpc_us = make_qpc_clock()

        self.root.title("Reading Experiment - 2日間実施版")

        print("=== 2日間実施版を実行中 ===")

        self.root.geometry("1000x700")

        # 画面全体を使い、大きな本文と行間を確保する。

        try:

            self.root.state("zoomed")

        except tk.TclError:

            self.root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")

        # Escキーで強制終了確認

        self.root.bind("<Escape>", self.force_exit)
        self.root.protocol("WM_DELETE_WINDOW", self.force_exit)

        self.current_trial = 0
        self.active_segment_start = None  # monotonic; 休憩終了後にリセット
        self.break_start_monotonic = None
        self.break_reason = None
        self.recording_segment = 0
        self.short_break_count = 0
        self.short_break_start_monotonic = None
        self.short_break_timer_job = None

        self.stimuli = []

        # 実験全体の開始時刻

        self.experiment_start_time = None

        # 文章画面の時刻

        self.text_start_time = None

        self.text_end_time = None

        self.reading_time_sec = None

        # 読書画面の経過時間表示用（計測にはmonotonicを使用）

        self.reading_start_monotonic = None

        self.reading_timer_job = None

        self.reading_timer_label = None

        # 問題前評価画面の時刻

        self.preconfidence_start_time = None

        self.preconfidence_end_time = None

        self.preconfidence_time_sec = None

        # 問題画面の時刻

        self.question_start_time = None

        self.question_end_time = None

        self.answer_time_sec = None

        # アンケート画面の時刻

        self.questionnaire_start_time = None

        self.questionnaire_end_time = None

        self.questionnaire_time_sec = None

        # 回答用変数

        self.selected_answer = tk.StringVar()

        self.pre_question_confidence = tk.IntVar()

        self.understanding = tk.IntVar()

        self.confidence = tk.IntVar()

        # 画面サイズも保存しておく

        self.screen_width = root.winfo_screenwidth()

        self.screen_height = root.winfo_screenheight()

        self.frame = None
        try:
            if not self.configure_session():
                self.root.destroy()
                return
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror("実験の準備エラー", str(exc), parent=self.root)
            self.root.destroy()
            return

        if self.session_day == 1:
            self.show_demographics_screen()
        else:
            self.show_practice_start_screen()

    def configure_session(self):
        participant = simpledialog.askstring(
            "参加者ID", "参加者IDを入力してください（例 P001）。", parent=self.root
        )
        if participant is None:
            return False
        match = re.fullmatch(r"P([0-9]{1,9})", participant.strip().upper())
        if not match or int(match[1]) == 0:
            raise ValueError("参加者IDはP001のような形式にしてください。")
        self.participant_number = int(match[1])
        self.participant_id = f"P{self.participant_number:03d}"
        self.session_day = simpledialog.askinteger(
            "実施日", "初日は1、2日目は2を入力してください。",
            minvalue=1, maxvalue=2, parent=self.root
        )
        if self.session_day is None:
            return False

        self.participant_dir = RESULTS_DIR / self.participant_id / "two_day"
        self.session_dir = self.participant_dir / f"day{self.session_day}"
        self.plan_path = self.participant_dir / f"{self.participant_id}_session_plan.json"
        self.demographics_path = self.participant_dir / f"{self.participant_id}_demographics.csv"
        self.session_prefix = f"{self.participant_id}_day{self.session_day}"
        if self.session_dir.exists():
            raise ValueError(
                f"{self.session_day}日目の保存先が既に存在します。"
                f"記録を確認してください。\n{self.session_dir}"
            )

        if self.session_day == 1:
            if not self.load_stimuli() or not self.load_practice_stimuli():
                return False
            days = self.apply_counterbalance()
            self.plan = {
                "participant_id": self.participant_id,
                "days": days,
                "practice": self.practice_stimuli,
            }
        else:
            self.plan = self.load_session_plan()
            self.load_day_one_results()

        today = self.plan["days"][self.session_day - 1]
        self.session_set = today["set"]
        self.main_stimuli = today["stimuli"]
        self.practice_stimuli = self.plan["practice"]
        self.root.title(
            f"Reading Experiment - {self.participant_id} / {self.session_day}日目 / "
            f"セット{self.session_set} / {len(self.main_stimuli)}問"
        )
        self.is_practice = True
        self.stimuli = self.practice_stimuli
        return True

    def load_session_plan(self):
        if not self.plan_path.is_file():
            raise ValueError("この参加者の初日の出題計画が見つかりません。")
        with self.plan_path.open(encoding="utf-8") as f:
            plan = json.load(f)
        try:
            if (plan["participant_id"] != self.participant_id
                    or len(plan["days"]) != 2
                    or {day["set"] for day in plan["days"]} != {"A", "B"}
                    or any(not day["stimuli"] for day in plan["days"])
                    or len(plan["practice"]) != 3):
                raise ValueError("保存した出題計画の内容が一致しません。")
            rows = plan["days"][0]["stimuli"] + plan["days"][1]["stimuli"] + plan["practice"]
            if (any(not all(isinstance(row[key], str) and row[key].strip()
                            for key in STIMULUS_COLUMNS) for row in rows)
                    or len({row["id"] for row in rows}) != len(rows)):
                raise ValueError("保存した出題計画に空欄または重複IDがあります。")
        except (KeyError, TypeError) as exc:
            raise ValueError("保存した出題計画を読み込めません。") from exc
        return plan

    def load_day_one_results(self):
        day_one = self.participant_dir / "day1"
        prefix = f"{self.participant_id}_day1"
        expected = [row["id"] for row in self.plan["days"][0]["stimuli"]]
        results = day_one / f"{prefix}.csv"
        events = day_one / f"{prefix}_events.csv"
        if not results.is_file() or not events.is_file():
            raise ValueError("初日の行動ログまたはイベントログが見つかりません。")
        with results.open(newline="", encoding="utf-8-sig") as f:
            actual = [(row.get("participant_id"), row.get("trial_id")) for row in csv.DictReader(f)]
        with events.open(newline="", encoding="utf-8-sig") as f:
            last_event = None
            for row in csv.DictReader(f):
                last_event = row.get("event")
        if (actual != [(self.participant_id, trial_id) for trial_id in expected]
                or last_event != "EXPERIMENT_END"):
            raise ValueError("初日の全試行が完了していません。初日の記録を確認してください。")
        with self.demographics_path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if (len(rows) != 1 or rows[0].get("participant_id") != self.participant_id
                or rows[0].get("gender") not in ("男性", "女性", "その他")):
            raise ValueError("初日の参加者情報を確認してください。")
        self.participant_age = int(rows[0].get("age") or 0)
        if not 1 <= self.participant_age <= 120:
            raise ValueError("初日の年齢の記録を確認してください。")
        self.participant_gender = rows[0]["gender"]

    def initialize_session_files(self):
        # mkdirで同じ参加者・同じ日の同時開始を防ぎ、既存の記録を保護する。
        self.session_dir.mkdir(parents=True, exist_ok=False)
        if self.session_day == 1:
            with self.plan_path.open("x", encoding="utf-8") as f:
                json.dump(self.plan, f, ensure_ascii=False, indent=2)
            with self.demographics_path.open("x", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["participant_id", "age", "gender"])
                writer.writerow([self.participant_id, self.participant_age, self.participant_gender])

        self.create_result_file()
        self.create_event_log()
        self.main_result_path = self.result_path
        self.main_event_log_path = self.event_log_path
        self.practice_result_path = self.session_dir / f"{self.session_prefix}_practice.csv"
        self.practice_event_log_path = self.session_dir / f"{self.session_prefix}_practice_events.csv"
        for source, dest in ((self.main_result_path, self.practice_result_path),
                             (self.main_event_log_path, self.practice_event_log_path)):
            with open(source, newline="", encoding="utf-8-sig") as src:
                header = next(csv.reader(src))
            with dest.open("x", newline="", encoding="utf-8-sig") as dst:
                csv.writer(dst).writerow(header)
        self.result_path = self.practice_result_path
        self.event_log_path = self.practice_event_log_path

    def show_demographics_screen(self):
        """練習開始前に参加者属性を1回だけ取得する（視線計測なし）。"""
        self.clear_frame()
        tk.Label(self.frame, text="参加者情報の入力", font=("Meiryo", 22, "bold")).pack(pady=(65, 18))
        tk.Label(self.frame, text="実験を始める前に、年齢と性別を回答してください。\n"
                 "回答は参加者IDと対応させて保存します。",
                 font=("Meiryo", 14), justify="center").pack(pady=12)

        form = tk.Frame(self.frame)
        form.pack(pady=25)
        tk.Label(form, text="年齢（満年齢）", font=("Meiryo", 15)).grid(row=0, column=0, sticky="e", padx=18, pady=18)
        self.age_entry = tk.Entry(form, width=8, font=("Meiryo", 16), justify="center")
        self.age_entry.grid(row=0, column=1, sticky="w", pady=18)
        tk.Label(form, text="歳", font=("Meiryo", 14)).grid(row=0, column=2, sticky="w", padx=8)

        tk.Label(form, text="性別", font=("Meiryo", 15)).grid(row=1, column=0, sticky="ne", padx=18, pady=18)
        self.gender_var = tk.StringVar(value="")
        gender_frame = tk.Frame(form)
        gender_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=10)
        for choice in ("男性", "女性", "その他"):
            tk.Radiobutton(gender_frame, text=choice, variable=self.gender_var,
                           value=choice, font=("Meiryo", 13)).pack(anchor="w", pady=3)

        tk.Button(self.frame, text="回答して練習へ進む", font=("Meiryo", 15),
                  command=self.save_demographics_and_continue).pack(pady=20)
        self.age_entry.focus_set()

    def save_demographics_and_continue(self):
        age_text = self.age_entry.get().strip()
        if not age_text.isascii() or not age_text.isdecimal():
            messagebox.showwarning("入力の確認", "年齢を数字で入力してください。", parent=self.root)
            return
        age = int(age_text)
        if not 1 <= age <= 120:
            messagebox.showwarning("入力の確認", "年齢は1～120歳で入力してください。", parent=self.root)
            return
        gender = self.gender_var.get()
        if gender not in ("男性", "女性", "その他"):
            messagebox.showwarning("入力の確認", "性別を選択してください。", parent=self.root)
            return

        self.participant_age = age
        self.participant_gender = gender
        self.show_practice_start_screen()

    def force_exit(self, event=None):

        if messagebox.askyesno("終了確認", "実験を終了しますか？"):

            self.root.destroy()

    def load_stimuli(self):

        csv_path = filedialog.askopenfilename(

            parent=self.root, title="刺激CSVを選択してください",

            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")]

        )

        if not csv_path:

            return False

        required = set(STIMULUS_COLUMNS)

        try:

            with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:

                reader = csv.DictReader(f)

                missing = required - set(reader.fieldnames or [])

                if missing:

                    raise ValueError("CSVに必要な列がありません: " + ", ".join(sorted(missing)))

                rows = [row for row in reader if any(row.values())]

            if not rows:

                raise ValueError("CSVに問題がありません。")

            ids = set()

            for line, row in enumerate(rows, start=2):

                if any(not (row.get(key) or "").strip() for key in required):

                    raise ValueError(f"CSV {line}行目: 必須項目に空欄があります。")

                row["id"] = row["id"].strip()

                row["condition"] = row["condition"].strip().lower()

                row["correct_answer"] = row["correct_answer"].strip().upper()

                if row["id"] in ids:

                    raise ValueError(f"問題IDが重複しています: {row['id']}")

                ids.add(row["id"])

                if row["condition"] not in ("easy", "medium", "hard"):

                    raise ValueError(f"CSV {line}行目: conditionはeasy/medium/hardにしてください。")

                if row["correct_answer"] not in ("A", "B", "C", "D"):

                    raise ValueError(f"CSV {line}行目: correct_answerはA/B/C/Dにしてください。")

            if len(rows) < 2:
                raise ValueError("2日間の実験には本実験用の問題が2問以上必要です。")

            self.stimuli = rows

        except (OSError, UnicodeError, csv.Error, ValueError) as exc:

            messagebox.showerror("読み込みエラー", str(exc), parent=self.root)

            return False

        self.num_questions = simpledialog.askinteger(

            "2日間の合計出題数",

            f"CSVには{len(rows)}問あります。2日間の合計出題数を入力してください。\n"
            "例 240問なら各日120問です。難易度の内訳はできるだけそろえます。",
            parent=self.root, initialvalue=min(MAIN_DEFAULT_QUESTIONS, len(rows)),
            minvalue=2, maxvalue=len(rows)
        )
        return self.num_questions is not None

    def load_practice_stimuli(self):
        """本実験と独立したCSVから難易度別に1問ずつ選ぶ。"""
        path = filedialog.askopenfilename(
            parent=self.root, title="練習用CSVを選択（easy/medium/hard各1問以上）",
            filetypes=[("CSVファイル", "*.csv")])
        if not path:
            return False
        required = set(STIMULUS_COLUMNS)
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError("練習CSVの必須列が不足しています: " + ", ".join(sorted(required - set(reader.fieldnames or []))))
                rows = list(reader)
            groups = {condition: [] for condition in CONDITIONS}
            main_ids = {r["id"] for r in self.stimuli}
            main_texts = {r["text"].strip() for r in self.stimuli}
            for row in rows:
                if any(not (row.get(k) or "").strip() for k in required):
                    raise ValueError("練習CSVに空欄があります")
                row["id"] = row["id"].strip()
                row["condition"] = row["condition"].strip().lower()
                row["correct_answer"] = row["correct_answer"].strip().upper()
                if row["condition"] not in groups or row["correct_answer"] not in ("A", "B", "C", "D"):
                    raise ValueError("練習CSVの難易度または正解記号が不正です")
                if row["id"] in main_ids or row["text"].strip() in main_texts:
                    raise ValueError("練習用と本実験用に重複するIDまたは本文があります")
                groups[row["condition"]].append(row)
            if any(not group for group in groups.values()):
                raise ValueError("練習用CSVにはeasy・medium・hardがそれぞれ1問以上必要です")
            self.practice_stimuli = [groups[k][0] for k in ("easy", "medium", "hard")]
            if len({r["id"] for r in self.practice_stimuli}) != 3:
                raise ValueError("練習3問のIDが重複しています")
            return True
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            messagebox.showerror("練習CSV読み込みエラー", str(exc), parent=self.root)
            return False

    def apply_counterbalance(self):
        # 共通シードで抽出・分割する。参加者IDは提示順だけに使う。
        rng = random.Random(2026)
        groups = {condition: [] for condition in CONDITIONS}
        for row in self.stimuli:
            groups[row["condition"]].append({key: row[key] for key in STIMULUS_COLUMNS})

        for group in groups.values():
            group.sort(key=lambda row: (0, int(row["id"]), row["id"])
                       if row["id"].isascii() and row["id"].isdecimal()
                       else (1, row["id"]))
            rng.shuffle(group)

        selected = {condition: [] for condition in CONDITIONS}
        remaining = self.num_questions
        while remaining:
            for condition, group in groups.items():
                index = len(selected[condition])
                if remaining and index < len(group):
                    selected[condition].append(group[index])
                    remaining -= 1

        sets = {name: {condition: [] for condition in CONDITIONS} for name in ("A", "B")}
        start_side = 0
        for condition, group in selected.items():
            # 近い文字数の文章を別々のセットへ入れ、余った1問は難易度間で交互に配る。
            group.sort(key=lambda row: len("".join(row["text"].splitlines())))
            for index, row in enumerate(group):
                name = ("A", "B")[(index + start_side) % 2]
                sets[name][condition].append(row)
            start_side = (start_side + len(group)) % 2

        patterns = [
            ("easy", "medium", "hard"), ("medium", "hard", "easy"),
            ("hard", "easy", "medium"), ("easy", "hard", "medium"),
            ("hard", "medium", "easy"), ("medium", "easy", "hard"),
        ]
        pattern_index = ((self.participant_number - 1) // 2) % len(patterns)
        for buckets in sets.values():
            for group in buckets.values():
                rng.shuffle(group)
                if pattern_index >= 3:
                    group.reverse()

        set_order = ("A", "B") if self.participant_number % 2 else ("B", "A")
        days = []
        for name in set_order:
            buckets = sets[name]
            order = [
                buckets[condition][index]
                for index in range(max(map(len, buckets.values())))
                for condition in patterns[pattern_index]
                if index < len(buckets[condition])
            ]
            days.append({"set": name, "stimuli": order})

        counts = {condition: len(group) for condition, group in selected.items()}
        if max(counts.values()) - min(counts.values()) > 1:
            summary = " / ".join(f"{key}: {count}問" for key, count in counts.items())
            messagebox.showwarning(
                "難易度の問題数",
                f"不足する難易度は他の難易度で補いました。\n2日間の合計 {summary}",
                parent=self.root
            )
        for day, plan in enumerate(days, start=1):
            buckets = sets[plan["set"]]
            summary = " / ".join(f"{key}: {len(group)}問" for key, group in buckets.items())
            print(f"{self.participant_id} {day}日目 / セット{plan['set']} / {summary}")
        return days

    def create_result_file(self):

        self.result_path = self.session_dir / f"{self.session_prefix}.csv"
        with self.result_path.open("x", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)

            writer.writerow([

                "participant_id",

                "age",

                "gender",

                "trial_id",

                "condition",

                "score",

                "length",

                "experiment_start_time",

                # absolute unix time

                "text_start_time",

                "text_end_time",

                "preconfidence_start_time",

                "preconfidence_end_time",

                "question_start_time",

                "question_end_time",

                "questionnaire_start_time",

                "questionnaire_end_time",

                # offset from experiment_start_time

                "text_start_offset",

                "text_end_offset",

                "preconfidence_start_offset",

                "preconfidence_end_offset",

                "question_start_offset",

                "question_end_offset",

                "questionnaire_start_offset",

                "questionnaire_end_offset",

                # duration

                "reading_time_sec",

                "preconfidence_time_sec",

                "answer_time_sec",

                "questionnaire_time_sec",

                # task result

                "correct_answer",

                "participant_answer",

                "correct",

                "pre_question_confidence",

                "understanding",

                "confidence",

                "screen_width",

                "screen_height",
                "session_day",
                "stimulus_set",
                "presentation_order",
                "recording_segment"

            ])

        plan_path = self.session_dir / f"{self.session_prefix}_selected_stimuli.csv"
        with plan_path.open("x", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["presentation_order", *STIMULUS_COLUMNS])
            writer.writeheader()
            for number, row in enumerate(self.main_stimuli, start=1):
                writer.writerow({"presentation_order": number, **row})

    def create_event_log(self):
        self.event_log_path = self.session_dir / f"{self.session_prefix}_events.csv"
        with self.event_log_path.open("x", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["timestamp", "offset_sec", "event", "trial_id", "phase", "event_type", "qpc_us"])

    def log_event(self, event_name, trial_id=None, phase=None, event_type=None):

        qpc_us = self.read_qpc_us()
        now = time.time()
        offset = 0.0 if self.experiment_start_time is None else now - self.experiment_start_time

        with open(self.event_log_path, "a", newline="", encoding="utf-8-sig") as f:

            writer = csv.writer(f)

            writer.writerow([

                now,

                round(offset, 3),

                event_name,

                trial_id,

                phase,

                event_type,
                qpc_us

            ])

    def stop_reading_timer(self):

        """画面切り替え時に古いタイマー更新を停止する。"""

        if self.reading_timer_job is not None:

            self.root.after_cancel(self.reading_timer_job)

            self.reading_timer_job = None

    def play_reading_sound(self, remaining):

        """Windowsのビープ音を別スレッドで鳴らし、GUIを止めない。"""

        if winsound is None:

            self.root.bell()

            return

        def play():

            try:

                winsound.Beep(880 if remaining == 15 else 1320, 180)

            except RuntimeError as exc:

                print(f"通知音の再生に失敗しました: {exc}")

        threading.Thread(target=play, daemon=True).start()

    def update_reading_timer(self):

        """時刻差で残り時間を判定。表示せず、15秒・5秒で各1回通知する。"""

        self.reading_timer_job = None

        if self.reading_start_monotonic is None:

            return

        remaining = READING_TIME_LIMIT_SEC - (time.monotonic() - self.reading_start_monotonic)

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        if remaining <= 0:

            self.log_event(f"TEXT_{trial_no}_TIMEOUT", trial_id=trial["id"],

                           phase="text", event_type="timeout")

            self.show_preconfidence()

            return

        for threshold in READING_WARNING_SECONDS:

            if remaining <= threshold and threshold not in self.reading_warnings_sent:

                self.reading_warnings_sent.add(threshold)

                self.log_event(f"TEXT_{trial_no}_AUDIO_REQUEST_REMAINING_{threshold}S",

                               trial_id=trial["id"], phase="text", event_type="audio_request")

                self.play_reading_sound(threshold)

        self.reading_timer_job = self.root.after(25, self.update_reading_timer)

    def clear_frame(self):

        self.stop_reading_timer()

        if self.frame:

            self.frame.destroy()

        self.frame = tk.Frame(self.root)

        self.frame.pack(fill="both", expand=True, padx=20, pady=20)
    def show_short_break_screen(self):
        """試行間の60秒休憩。Tobii録画は終了せず同じ録画を継続する。"""
        if self.short_break_start_monotonic is not None:
            return
        self.short_break_start_monotonic = time.monotonic()
        self.log_event("SHORT_BREAK_START", trial_id="", phase="short_break", event_type="start")
        self.clear_frame()
        tk.Label(self.frame, text=(
            "1分間の小休憩です。\n\n"
            f"完了: {self.current_trial} / {len(self.stimuli)} 問\n\n"
            "Tobiiの録画は停止しないでください。\n"
            "画面から目を離して休んでください。\n"
            "1分後に再開ボタンが有効になります。"),
            font=("Meiryo", 18), justify="center").pack(expand=True)
        self.short_break_remaining_label = tk.Label(self.frame, font=("Meiryo", 18))
        self.short_break_remaining_label.pack(pady=10)
        self.short_break_resume_button = tk.Button(
            self.frame, text="本実験を再開", font=("Meiryo", 15),
            command=self.resume_from_short_break, state="disabled")
        self.short_break_resume_button.pack(pady=20)
        self.update_short_break_timer()

    def update_short_break_timer(self):
        if self.short_break_start_monotonic is None:
            return
        import math
        remaining = max(0, math.ceil(SHORT_BREAK_DURATION_SEC - (
            time.monotonic() - self.short_break_start_monotonic)))
        self.short_break_remaining_label.config(text=f"残り {remaining} 秒")
        if remaining == 0:
            self.short_break_resume_button.config(state="normal")
            self.short_break_timer_job = None
        else:
            self.short_break_timer_job = self.root.after(200, self.update_short_break_timer)

    def resume_from_short_break(self):
        if self.short_break_start_monotonic is None:
            return
        elapsed = time.monotonic() - self.short_break_start_monotonic
        if elapsed < SHORT_BREAK_DURATION_SEC:
            return
        if self.short_break_timer_job is not None:
            self.root.after_cancel(self.short_break_timer_job)
            self.short_break_timer_job = None
        self.log_event("SHORT_BREAK_END", trial_id="", phase="short_break", event_type="end")
        # 休憩の経過時間は20分/60分の判定に含めない。
        self.active_segment_start += elapsed
        self.short_break_count += 1
        self.short_break_start_monotonic = None
        self.show_text()

    def show_break_screen(self, reason):
        """試行間で停止。Tobii側の録画操作は実験者が行う。"""
        self.break_reason = reason
        self.break_start_monotonic = time.monotonic()
        self.log_event("BREAK_START", trial_id="", phase="break", event_type=reason)
        self.log_event(f"RECORDING_SEGMENT_{self.recording_segment:02d}_END", trial_id="", phase="recording", event_type="end")
        self.clear_frame()
        reason_text = "実験時間が約1時間に達しました。"
        tk.Label(self.frame, text=(
            f"{reason_text}\n\n"
            f"完了: {self.current_trial} / {len(self.stimuli)} 問\n\n"
            "実験者はTobii Pro Labの現在の録画を終了・保存してください。\n"
            "参加者は離席して休憩できます。\n\n"
            "再開前には着席して、Tobiiのキャリブレーションを\n"
            "再実施してください。"),
            font=("Meiryo", 17), justify="center").pack(expand=True)
        tk.Button(self.frame, text="再キャリブレーション・録画再開の確認へ",
                  font=("Meiryo", 15), command=self.show_resume_check_screen).pack(pady=30)

    def show_resume_check_screen(self):
        """新しい録画開始前に視線計測の準備を確認する。"""
        if self.break_start_monotonic is None:
            return
        self.clear_frame()
        tk.Label(self.frame, text=(
            "本実験を再開する前の確認\n\n"
            "1. 参加者が元の位置に着席した\n"
            "2. Tobiiのキャリブレーションを再実施した\n"
            "3. Tobii Pro Labで新しい録画を開始した\n\n"
            "すべて完了したら、下のボタンを押してください。\n"
            "※このアプリはTobiiの録画を自動操作しません。"),
            font=("Meiryo", 17), justify="center").pack(expand=True)
        tk.Button(self.frame, text="新規録画開始済み・本実験を再開（RESUME_SYNC）",
                  font=("Meiryo", 15), command=self.resume_from_break).pack(pady=30)
        tk.Button(self.frame, text="休憩画面へ戻る", font=("Meiryo", 12),
                  command=lambda: self.show_break_wait_screen()).pack(pady=5)

    def show_break_wait_screen(self):
        """休憩開始イベントを重複記録せずに待機画面に戻る。"""
        self.clear_frame()
        tk.Label(self.frame, text="休憩中です。\n再開前にキャリブレーションを行ってください。",
                 font=("Meiryo", 18), justify="center").pack(expand=True)
        tk.Button(self.frame, text="再キャリブレーション・録画再開の確認へ",
                  font=("Meiryo", 15), command=self.show_resume_check_screen).pack(pady=30)

    def resume_from_break(self):
        if self.break_start_monotonic is None:
            return
        elapsed = time.monotonic() - self.break_start_monotonic
        # 新しい録画区間の先頭に、イベントログ上の時刻基準を残す。
        # Tobiiの録画終了・新規録画開始は実験者が手動で操作する。
        self.recording_segment += 1
        self.log_event("BREAK_END", trial_id="", phase="break", event_type=self.break_reason)
        self.log_event("RESUME_SYNC", trial_id="", phase="sync", event_type="resume_sync")
        self.log_event(f"RECORDING_SEGMENT_{self.recording_segment:02d}_START", trial_id="", phase="recording", event_type="start")
        print(f"休憩終了: {elapsed:.1f}秒 / 理由: {self.break_reason}")
        self.break_start_monotonic = None
        self.break_reason = None
        self.active_segment_start = time.monotonic()
        self.short_break_count = 0
        self.show_text()

    def show_practice_start_screen(self):
        """練習中はTobii録画を要求しない。"""
        self.clear_frame()
        tk.Label(
            self.frame,
            text=(f"{self.session_day}日目の実験（本試行 {len(self.main_stimuli)}問）\n\n"
                  "これから練習問題を3問行います。\nこの段階ではTobiiの録画は不要です。"),
            font=("Meiryo", 18), justify="center"
        ).pack(expand=True)
        tk.Button(
            self.frame, text="練習を開始", font=("Meiryo", 16),
            command=self.start_practice
        ).pack(pady=30)

    def start_practice(self):
        """練習用の基準時刻を記録するが、SYNCイベントは発行しない。"""
        try:
            self.initialize_session_files()
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror("保存エラー", f"{exc}\n保存先を確認してください。",
                                 parent=self.root)
            self.root.destroy()
            return
        self.experiment_start_time = time.time()
        self.log_event("PRACTICE_START", trial_id="", phase="practice", event_type="start")
        self.show_text()

    def show_practice_finished(self):
        self.clear_frame()
        tk.Label(
            self.frame,
            text=("練習3問が終了しました。\n\n"
                  "ここでTobiiのキャリブレーションを確認し、\n"
                  "Tobii Pro Labの録画を開始してください。\n\n"
                  "録画開始を確認してから下のボタンを押してください。"),
            font=("Meiryo", 18), justify="center"
        ).pack(expand=True)
        tk.Button(
            self.frame, text="録画開始済み・本実験を開始（SYNC）",
            font=("Meiryo", 16), command=self.begin_main_experiment
        ).pack(pady=30)

    def begin_main_experiment(self):
        """本実験ログに切り替え、基準時刻とSYNCイベントを記録する。"""
        self.is_practice = False
        self.stimuli = self.main_stimuli
        self.current_trial = 0
        self.result_path = self.main_result_path
        self.event_log_path = self.main_event_log_path
        self.experiment_start_time = time.time()
        self.recording_segment = 1
        self.log_event("SYNC", trial_id="", phase="sync", event_type="sync")
        self.log_event("RECORDING_SEGMENT_01_START", trial_id="", phase="recording", event_type="start")
        self.active_segment_start = time.monotonic()
        self.short_break_count = 0
        self.show_text()

    def show_text(self):

        self.clear_frame()

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        tk.Label(

            self.frame,

            text=f"{'練習' if self.is_practice else 'TRIAL'} {trial_no}",

            font=("Meiryo", 14, "bold")

        ).pack(pady=5)

        tk.Label(

            self.frame,

            text=f"{'練習' if self.is_practice else '文章'} {trial_no}/{len(self.stimuli)}",

            font=("Meiryo", 12)

        ).pack(pady=5)

        # 時間表示は置かず、通知音で残り時間を伝える。

        # ボタンの領域を先に確保し、本文が長くても画面外へ押し出さない。

        tk.Button(

            self.frame, text="読み終わった", font=("Meiryo", 12),

            command=self.show_preconfidence

        ).pack(side="bottom", pady=(10, 0))

        body_font = tkfont.Font(family="Meiryo", size=-READING_FONT_PX)

        # linespaceにはフォント固有の高さが含まれる。追加する余白との差を取る。

        extra_spacing = max(0, READING_LINE_PITCH_PX - body_font.metrics("linespace"))

        self.root.update_idletasks()

        body_width = min(READING_MAX_WIDTH_PX, max(200, self.frame.winfo_width() - 40))

        body = tk.Frame(self.frame, width=body_width)

        body.pack(fill="y", expand=True, pady=(0, 4))

        body.pack_propagate(False)

        scrollbar = tk.Scrollbar(body, orient="vertical")

        text_widget = tk.Text(

            body, wrap="char", font=body_font, width=1, height=1,

            spacing1=0, spacing2=extra_spacing, spacing3=extra_spacing,

            padx=16, pady=10, borderwidth=1, relief="solid",

            background="white", foreground="black", cursor="arrow",

            yscrollcommand=scrollbar.set

        )

        # Tkフォントを画面表示中保持する。

        text_widget.body_font = body_font

        text_widget.pack(side="left", fill="both", expand=True)

        scrollbar.config(command=text_widget.yview)

        # 元の改行を除去し、表示欄の右端だけで折り返す。

        # 英単語の途中にある改行は、単語の連結を避けるため空白にする。

        display_text = re.sub(r"(?<=[A-Za-z0-9])\r?\n(?=[A-Za-z0-9])", " ", trial["text"])

        display_text = "".join(display_text.splitlines())

        text_widget.insert("1.0", display_text)

        text_widget.config(state="disabled")

        self.root.update_idletasks()

        # 小さい画面や長文でも、末尾を隠したまま実験を進めない。

        if text_widget.yview()[1] < 0.999:

            scrollbar.pack(side="right", fill="y")

            messagebox.showwarning(

                "本文の表示範囲",

                "本文が1画面に収まりません。スクロールで全文を読めます。\n"

                "本実験前に、文章長・画面サイズ・本文表示設定を調整してください。"

            )

        # 描画と警告ダイアログが終わってから、計測と開始イベントをそろえる。

        self.root.update_idletasks()

        self.reading_warnings_sent = set()

        self.text_start_time = time.time()

        self.reading_start_monotonic = time.monotonic()

        self.log_event(

            f"TEXT_{trial_no}_START",

            trial_id=trial["id"],

            phase="text",

            event_type="start"

        )

        self.update_reading_timer()

    def show_preconfidence(self):

        # 手動終了と時間切れの二重遷移を防ぐ。

        if self.reading_start_monotonic is None:

            return

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.text_end_time = time.time()

        self.reading_time_sec = round(

            time.monotonic() - self.reading_start_monotonic, 3

        )

        self.stop_reading_timer()

        self.reading_timer_label = None

        self.reading_start_monotonic = None

        self.log_event(

            f"TEXT_{trial_no}_END",

            trial_id=trial["id"],

            phase="text",

            event_type="end"

        )

        self.clear_frame()

        self.pre_question_confidence.set(0)

        self.preconfidence_start_time = time.time()

        self.log_event(

            f"PRECONFIDENCE_{trial_no}_START",

            trial_id=trial["id"],

            phase="preconfidence",

            event_type="start"

        )

        tk.Label(

            self.frame,

            text="【問題前の自信度評価】",

            font=("Meiryo", 16, "bold")

        ).pack(pady=(30, 10))

        tk.Label(

            self.frame,

            text="この文章の内容に関する問題に、\n正しく答えられる自信はどの程度ありますか？",

            font=("Meiryo", 14),

            justify="center"

        ).pack(pady=(80, 10))

        tk.Label(

            self.frame,

            text="（この後に出題される問題を見る前の時点で回答してください）",

            font=("Meiryo", 11)

        ).pack(pady=(0, 20))

        preconfidence_frame = tk.Frame(self.frame)

        preconfidence_frame.pack(pady=5)

        preconfidence_labels = [

            (1, "1\nまったく\n自信がない"),

            (2, "2\nあまり\n自信がない"),

            (3, "3\nどちらとも\nいえない"),

            (4, "4\nやや\n自信がある"),

            (5, "5\n非常に\n自信がある")

        ]

        for value, label in preconfidence_labels:

            tk.Radiobutton(

                preconfidence_frame,

                text=label,

                variable=self.pre_question_confidence,

                value=value,

                font=("Meiryo", 11),

                justify="center",

                indicatoron=True,

                width=12

            ).pack(side="left", padx=8)

        tk.Button(

            self.frame,

            text="問題へ",

            font=("Meiryo", 12),

            command=self.finish_preconfidence

        ).pack(pady=35)

    def finish_preconfidence(self):

        if self.pre_question_confidence.get() == 0:

            messagebox.showwarning("警告", "問題に答えられる自信度を選択してください")

            return

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.preconfidence_end_time = time.time()

        self.preconfidence_time_sec = round(

            self.preconfidence_end_time - self.preconfidence_start_time, 3

        )

        self.log_event(

            f"PRECONFIDENCE_{trial_no}_END",

            trial_id=trial["id"],

            phase="preconfidence",

            event_type="end"

        )

        self.show_question()

    def show_question(self):

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.clear_frame()

        self.selected_answer.set("")

        self.question_start_time = time.time()

        self.log_event(

            f"QUESTION_{trial_no}_START",

            trial_id=trial["id"],

            phase="question",

            event_type="start"

        )

        tk.Label(

            self.frame,

            text=trial["question"],

            font=("Meiryo", 14),

            wraplength=900,

            justify="left"

        ).pack(pady=20)

        choices = [

            ("A", trial["choice_A"]),

            ("B", trial["choice_B"]),

            ("C", trial["choice_C"]),

            ("D", trial["choice_D"])

        ]

        for value, text in choices:

            tk.Radiobutton(

                self.frame,

                text=f"{value}. {text}",

                variable=self.selected_answer,

                value=value,

                font=("Meiryo", 12),

                wraplength=900,

                justify="left"

            ).pack(anchor="w", pady=8)

        tk.Button(

            self.frame,

            text="回答",

            font=("Meiryo", 12),

            command=self.show_questionnaire

        ).pack(pady=20)

    def show_questionnaire(self):

        if self.selected_answer.get() == "":

            messagebox.showwarning("警告", "選択肢を選んでください")

            return

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.question_end_time = time.time()

        self.answer_time_sec = round(

            self.question_end_time - self.question_start_time,

            3

        )

        self.log_event(

            f"QUESTION_{trial_no}_END",

            trial_id=trial["id"],

            phase="question",

            event_type="end"

        )

        self.clear_frame()

        self.questionnaire_start_time = time.time()

        self.log_event(

            f"QUESTIONNAIRE_{trial_no}_START",

            trial_id=trial["id"],

            phase="questionnaire",

            event_type="start"

        )

        tk.Label(

            self.frame,

            text="【問題後アンケート】",

            font=("Meiryo", 16, "bold")

        ).pack(pady=(5, 5))

        # 未選択を判定できるように、初期値は0にする

        self.understanding.set(0)

        self.confidence.set(0)

        # =========================

        # 理解度アンケート

        # =========================

        tk.Label(

            self.frame,

            text="内容をどの程度理解できましたか？",

            font=("Meiryo", 14)

        ).pack(pady=(20, 5))

        tk.Label(

            self.frame,

            text="（文章の内容を自分がどの程度理解できたと思うかで回答してください）",

            font=("Meiryo", 11)

        ).pack(pady=(0, 10))

        understanding_frame = tk.Frame(self.frame)

        understanding_frame.pack(pady=5)

        understanding_labels = [

            (1, "1\nほとんど\n理解できない"),

            (2, "2\n一部しか\n理解できない"),

            (3, "3\n半分程度\n理解できた"),

            (4, "4\nほとんど\n理解できた"),

            (5, "5\n十分\n理解できた")

        ]

        for value, label in understanding_labels:

            tk.Radiobutton(

                understanding_frame,

                text=label,

                variable=self.understanding,

                value=value,

                font=("Meiryo", 11),

                justify="center",

                indicatoron=True,

                width=12

            ).pack(side="left", padx=8)

        # =========================

        # 自信度アンケート

        # =========================

        tk.Label(

            self.frame,

            text="あなたの回答にどの程度自信がありますか？",

            font=("Meiryo", 14)

        ).pack(pady=(35, 5))

        tk.Label(

            self.frame,

            text="（回答が正しいと思う度合いで選択してください）",

            font=("Meiryo", 11)

        ).pack(pady=(0, 10))

        confidence_frame = tk.Frame(self.frame)

        confidence_frame.pack(pady=5)

        confidence_labels = [

            (1, "1\n完全な\n運任せ"),

            (2, "2\nあまり\n自信がない"),

            (3, "3\nどちらとも\nいえない"),

            (4, "4\nやや\n自信がある"),

            (5, "5\n正しいと\n確信している")

        ]

        for value, label in confidence_labels:

            tk.Radiobutton(

                confidence_frame,

                text=label,

                variable=self.confidence,

                value=value,

                font=("Meiryo", 11),

                justify="center",

                indicatoron=True,

                width=12

            ).pack(side="left", padx=8)

        tk.Button(

            self.frame,

            text="アンケートを回答して次の文章へ",

            font=("Meiryo", 12),

            command=self.save_and_next

        ).pack(pady=35)

    def save_and_next(self):

        if self.understanding.get() == 0:

            messagebox.showwarning("警告", "理解度を選択してください")

            return

        if self.confidence.get() == 0:

            messagebox.showwarning("警告", "自信度を選択してください")

            return

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.questionnaire_end_time = time.time()

        self.questionnaire_time_sec = round(

            self.questionnaire_end_time - self.questionnaire_start_time,

            3

        )

        self.log_event(

            f"QUESTIONNAIRE_{trial_no}_END",

            trial_id=trial["id"],

            phase="questionnaire",

            event_type="end"

        )

        answer = self.selected_answer.get()

        correct = 1 if answer == trial["correct_answer"] else 0

        text_start_offset = self.text_start_time - self.experiment_start_time

        text_end_offset = self.text_end_time - self.experiment_start_time

        preconfidence_start_offset = self.preconfidence_start_time - self.experiment_start_time

        preconfidence_end_offset = self.preconfidence_end_time - self.experiment_start_time

        question_start_offset = self.question_start_time - self.experiment_start_time

        question_end_offset = self.question_end_time - self.experiment_start_time

        questionnaire_start_offset = self.questionnaire_start_time - self.experiment_start_time

        questionnaire_end_offset = self.questionnaire_end_time - self.experiment_start_time

        with open(self.result_path, "a", newline="", encoding="utf-8-sig") as f:

            writer = csv.writer(f)

            writer.writerow([

                self.participant_id,

                self.participant_age,

                self.participant_gender,

                trial["id"],

                trial["condition"],

                trial["score"],

                trial["length"],

                self.experiment_start_time,

                self.text_start_time,

                self.text_end_time,

                self.preconfidence_start_time,

                self.preconfidence_end_time,

                self.question_start_time,

                self.question_end_time,

                self.questionnaire_start_time,

                self.questionnaire_end_time,

                round(text_start_offset, 3),

                round(text_end_offset, 3),

                round(preconfidence_start_offset, 3),

                round(preconfidence_end_offset, 3),

                round(question_start_offset, 3),

                round(question_end_offset, 3),

                round(questionnaire_start_offset, 3),

                round(questionnaire_end_offset, 3),

                self.reading_time_sec,

                self.preconfidence_time_sec,

                self.answer_time_sec,

                self.questionnaire_time_sec,

                trial["correct_answer"],

                answer,

                correct,

                self.pre_question_confidence.get(),

                self.understanding.get(),

                self.confidence.get(),

                self.screen_width,

                self.screen_height,
                self.session_day,
                "" if self.is_practice else self.session_set,
                trial_no,
                "" if self.is_practice else self.recording_segment

            ])

        self.current_trial += 1

        if self.current_trial >= len(self.stimuli):
            if self.is_practice:
                self.log_event("PRACTICE_END", trial_id="", phase="practice", event_type="end")
                self.show_practice_finished()
                return
            self.clear_frame()

            self.log_event(f"RECORDING_SEGMENT_{self.recording_segment:02d}_END", trial_id="", phase="recording", event_type="end")
            self.log_event(

                "EXPERIMENT_END",

                trial_id="",

                phase="experiment",

                event_type="end"

            )

            tk.Label(

                self.frame,

                text=(f"{self.session_day}日目の実験が終了しました。\n"
                      "実験者はTobii Pro Labの録画を終了・保存してください。\n\n"
                      + ("次回は同じ参加者IDで2日目を選択してください。"
                         if self.session_day == 1 else "ご協力ありがとうございました。")),

                font=("Meiryo", 18)

            ).pack(expand=True)

            return

        # 1時間の定期休憩は試行と試行の間で開始する。
        # 休憩時間は次の1時間の計測に含めない。
        if not self.is_practice:
            elapsed = time.monotonic() - self.active_segment_start
            if elapsed >= BREAK_INTERVAL_SEC:
                self.show_break_screen("scheduled")
                return
            if elapsed >= SHORT_BREAK_INTERVAL_SEC * (self.short_break_count + 1):
                self.show_short_break_screen()
                return
        self.show_text()

if __name__ == "__main__":

    root = tk.Tk()

    app = Experiment(root)

    root.mainloop()
