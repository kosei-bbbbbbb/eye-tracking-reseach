import tkinter as tk

from tkinter import messagebox, filedialog, simpledialog

import csv

import os

import time
import random

class Experiment:

    def __init__(self, root):

        self.root = root

        self.root.title("Reading Experiment - PRECONFIDENCE VERSION")

        print("=== 問題前自信度あり版を実行中 ===")

        self.root.geometry("1000x700")

        # Escキーで強制終了確認

        self.root.bind("<Escape>", self.force_exit)

        self.current_trial = 0

        self.stimuli = []

        # 被験者ID。P002などに変える場合はここを変更する。

        self.participant_id = "P001"

        # 実験全体の開始時刻

        self.experiment_start_time = None

        # 文章画面の時刻

        self.text_start_time = None

        self.text_end_time = None

        self.reading_time_sec = None

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

        if not self.load_stimuli():
            self.root.destroy()
            return

        self.create_result_file()

        self.create_event_log()

        self.frame = None

        self.show_sync_screen()

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
        self.csv_path = csv_path
        required = {"id", "condition", "score", "length", "text", "question",
                    "choice_A", "choice_B", "choice_C", "choice_D", "correct_answer"}
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
            participant = self.participant_id.strip().upper()
            if not (participant.startswith("P") and participant[1:].isdigit()
                    and int(participant[1:]) > 0):
                raise ValueError("被験者IDはP001のような形式にしてください。")
            self.participant_id = participant
            self.participant_number = int(participant[1:])
            self.stimuli = rows
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            messagebox.showerror("読み込みエラー", str(exc), parent=self.root)
            return False
        self.num_questions = simpledialog.askinteger(
            "出題数の設定",
            f"CSVには{len(rows)}問あります。出題する問題数を入力してください。\n"
            "難易度ごとにできるだけ均等に選びます。\n"
            "3の倍数なら各難易度の問題数が同じになります。",
            parent=self.root, initialvalue=min(6, len(rows)),
            minvalue=1, maxvalue=len(rows)
        )
        if self.num_questions is None:
            return False
        self.apply_counterbalance()
        return True

    def apply_counterbalance(self):
        # 共通シード: 同じCSVと出題数なら、全被験者で同じ問題を選ぶ。
        # 選ぶ問題セットを変える場合はこの値を変更する。
        selection_seed = 2026
        rng = random.Random(selection_seed)
        groups = {condition: [] for condition in ("easy", "medium", "hard")}
        for row in self.stimuli:
            groups[row["condition"]].append(row)

        def sort_key(row):
            sid = row["id"]
            return (0, int(sid)) if sid.isdigit() else (1, sid)

        for group in groups.values():
            group.sort(key=sort_key)
            rng.shuffle(group)
        # 一巡につき各難易度1問。足りない難易度は他の難易度で補う。
        selected = {condition: [] for condition in groups}
        counts = {condition: 0 for condition in groups}
        remaining = self.num_questions
        while remaining:
            for condition in groups:
                if remaining and counts[condition] < len(groups[condition]):
                    selected[condition].append(groups[condition][counts[condition]])
                    counts[condition] += 1
                    remaining -= 1
        # 6問・各難易度2問の場合、従来の6種類の提示順に対応。
        patterns = [
            ("easy", "medium", "hard"), ("medium", "hard", "easy"),
            ("hard", "easy", "medium"), ("easy", "hard", "medium"),
            ("hard", "medium", "easy"), ("medium", "easy", "hard")
        ]
        pattern_index = (self.participant_number - 1) % len(patterns)
        if pattern_index >= 3:
            for group in selected.values():
                group.reverse()
        self.stimuli = []
        for index in range(max(counts.values())):
            for condition in patterns[pattern_index]:
                if index < len(selected[condition]):
                    self.stimuli.append(selected[condition][index])
        print("========== 提示順 ==========")
        print(f"被験者ID: {self.participant_id} / 出題数: {len(self.stimuli)}")
        print(f"抽出シード: {selection_seed} / 提示パターン: {pattern_index + 1}")
        print(f"Easy: {counts['easy']} / Medium: {counts['medium']} / Hard: {counts['hard']}")
        for number, row in enumerate(self.stimuli, start=1):
            print(f"{number}: ID={row['id']} / {row['condition']}")
        print("============================")
        if max(counts.values()) - min(counts.values()) > 1:
            messagebox.showwarning(
                "難易度の問題数", "CSV内の問題数が不足する難易度を、他の難易度で補いました。\n"
                f"Easy: {counts['easy']}問 / Medium: {counts['medium']}問 / Hard: {counts['hard']}問",
                parent=self.root
            )

    def create_result_file(self):

        # 被験者IDごとに保存先フォルダを分ける

        # 例: results/P001/P001.csv

        self.participant_dir = os.path.join("results", self.participant_id)

        os.makedirs(self.participant_dir, exist_ok=True)

        self.result_path = os.path.join(

            self.participant_dir,

            f"{self.participant_id}.csv"

        )

        if not os.path.exists(self.result_path):

            with open(self.result_path, "w", newline="", encoding="utf-8-sig") as f:

                writer = csv.writer(f)

                writer.writerow([

                    "participant_id",

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

                    "screen_height"

                ])

        plan_path = os.path.join(self.participant_dir, f"{self.participant_id}_selected_stimuli.csv")
        with open(plan_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["presentation_order"] + list(self.stimuli[0]))
            writer.writeheader()
            for number, row in enumerate(self.stimuli, start=1):
                writer.writerow({"presentation_order": number, **row})

    def create_event_log(self):

        # 被験者IDごとにイベントログも同じフォルダへ保存する

        # 例: results/P001/P001_events.csv

        self.event_log_path = os.path.join(

            self.participant_dir,

            f"{self.participant_id}_events.csv"

        )

        if not os.path.exists(self.event_log_path):

            with open(self.event_log_path, "w", newline="", encoding="utf-8-sig") as f:

                writer = csv.writer(f)

                writer.writerow([

                    "timestamp",

                    "offset_sec",

                    "event",

                    "trial_id",

                    "phase",

                    "event_type"

                ])

    def log_event(self, event_name, trial_id=None, phase=None, event_type=None):

        if self.experiment_start_time is None:

            now = time.time()

            offset = 0.0

        else:

            now = time.time()

            offset = now - self.experiment_start_time

        with open(self.event_log_path, "a", newline="", encoding="utf-8-sig") as f:

            writer = csv.writer(f)

            writer.writerow([

                now,

                round(offset, 3),

                event_name,

                trial_id,

                phase,

                event_type

            ])

    def clear_frame(self):

        if self.frame:

            self.frame.destroy()

        self.frame = tk.Frame(self.root)

        self.frame.pack(fill="both", expand=True, padx=20, pady=20)

    def show_sync_screen(self):

        self.clear_frame()

        tk.Label(

            self.frame,

            text="""

Tobii録画を開始してください

録画開始後に

SYNCボタンを押してください

""",

            font=("Meiryo", 16)

        ).pack(expand=True)

        tk.Button(

            self.frame,

            text="SYNC",

            font=("Meiryo", 18),

            command=self.start_experiment

        ).pack(pady=30)

    def start_experiment(self):

        self.experiment_start_time = time.time()

        self.log_event(

            "SYNC",

            trial_id="",

            phase="sync",

            event_type="sync"

        )

        self.show_text()

    def show_text(self):

        self.clear_frame()

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.text_start_time = time.time()

        self.log_event(

            f"TEXT_{trial_no}_START",

            trial_id=trial["id"],

            phase="text",

            event_type="start"

        )

        tk.Label(

            self.frame,

            text=f"TRIAL {trial_no}",

            font=("Meiryo", 14, "bold")

        ).pack(pady=5)

        tk.Label(

            self.frame,

            text=f"文章 {trial_no}/{len(self.stimuli)}",

            font=("Meiryo", 12)

        ).pack(pady=5)

        text_widget = tk.Text(

            self.frame,

            wrap="word",

            font=("Meiryo", 14),

            width=55,

            height=25

        )

        text_widget.pack(expand=True)

        text_widget.insert("1.0", trial["text"])

        text_widget.config(state="disabled")

        tk.Button(

            self.frame,

            text="読み終わった",

            font=("Meiryo", 12),

            command=self.show_preconfidence

        ).pack(pady=20)

    def show_preconfidence(self):

        trial = self.stimuli[self.current_trial]

        trial_no = self.current_trial + 1

        self.text_end_time = time.time()

        self.reading_time_sec = round(self.text_end_time - self.text_start_time, 3)

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

                self.screen_height

            ])

        self.current_trial += 1

        if self.current_trial >= len(self.stimuli):

            self.clear_frame()

            self.log_event(

                "EXPERIMENT_END",

                trial_id="",

                phase="experiment",

                event_type="end"

            )

            tk.Label(

                self.frame,

                text="実験終了です。\nご協力ありがとうございました。",

                font=("Meiryo", 18)

            ).pack(expand=True)

            return

        self.show_text()

if __name__ == "__main__":

    root = tk.Tk()

    app = Experiment(root)

    root.mainloop()
