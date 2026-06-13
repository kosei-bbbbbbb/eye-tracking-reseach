import tkinter as tk
from tkinter import messagebox
import csv
import os
import time


class Experiment:

    def __init__(self, root):

        self.root = root
        self.root.title("Reading Experiment")
        self.root.geometry("1000x700")

        self.current_trial = 0
        self.stimuli = []

        self.participant_id = "P001"

        self.text_start_time = None
        self.text_end_time = None

        self.selected_answer = tk.StringVar()
        self.understanding = tk.IntVar()
        self.confidence = tk.IntVar()

        self.question_start_time = None

        self.load_stimuli()

        self.create_result_file()

        self.frame = None

        self.show_text()

    # -----------------------------
    # stimuli読み込み
    # -----------------------------
    def load_stimuli(self):

        with open(
            "stimuli_with_quiz.csv",
            "r",
            encoding="utf-8-sig"
        ) as f:

            reader = csv.DictReader(f)
            self.stimuli = list(reader)

    # -----------------------------
    # resultsファイル作成（改良版）
    # -----------------------------
    def create_result_file(self):

        os.makedirs("results", exist_ok=True)

        self.result_path = f"results/{self.participant_id}.csv"

        if not os.path.exists(self.result_path):

            with open(
                self.result_path,
                "w",
                newline="",
                encoding="utf-8-sig"
            ) as f:

                writer = csv.writer(f)

                writer.writerow([
                    "participant_id",
                    "trial_id",
                    "condition",
                    "score",
                    "length",
                    "text_start_time",
                    "text_end_time",
                    "question_start_time",
                    "question_end_time",
                    "correct_answer",
                    "participant_answer",
                    "correct",
                    "response_time_sec",
                    "understanding",
                    "confidence"
                ])

    # -----------------------------
    # UIクリア
    # -----------------------------
    def clear_frame(self):

        if self.frame:
            self.frame.destroy()

        self.frame = tk.Frame(self.root)
        self.frame.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20
        )

    # -----------------------------
    # 本文表示
    # -----------------------------
    def show_text(self):

        self.clear_frame()

        trial = self.stimuli[self.current_trial]

        self.text_start_time = time.time()

        tk.Label(
            self.frame,
            text=f"TRIAL {self.current_trial + 1}",
            font=("Meiryo", 14, "bold")
        ).pack(pady=5)

        tk.Label(
            self.frame,
            text=f"文章 {self.current_trial + 1}/{len(self.stimuli)}",
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
            text="問題へ",
            font=("Meiryo", 12),
            command=self.show_question
        ).pack(pady=20)

    # -----------------------------
    # 問題表示
    # -----------------------------
    def show_question(self):

        self.text_end_time = time.time()

        self.clear_frame()

        trial = self.stimuli[self.current_trial]

        self.selected_answer.set("")

        self.question_start_time = time.time()

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

    # -----------------------------
    # 質問＋メタ認知
    # -----------------------------
    def show_questionnaire(self):

        if self.selected_answer.get() == "":
            messagebox.showwarning("警告", "選択肢を選んでください")
            return

        self.response_time = round(
            time.time() - self.question_start_time,
            3
        )

        self.question_end_time = time.time()

        self.clear_frame()

        self.understanding.set(3)
        self.confidence.set(3)

        tk.Label(
            self.frame,
            text="内容をどの程度理解できましたか？",
            font=("Meiryo", 14)
        ).pack(pady=10)

        tk.Scale(
            self.frame,
            from_=1,
            to=5,
            orient="horizontal",
            variable=self.understanding,
            length=300
        ).pack()

        tk.Label(
            self.frame,
            text="自分の回答にどの程度自信がありますか？",
            font=("Meiryo", 14)
        ).pack(pady=20)

        tk.Scale(
            self.frame,
            from_=1,
            to=5,
            orient="horizontal",
            variable=self.confidence,
            length=300
        ).pack()

        tk.Button(
            self.frame,
            text="次へ",
            font=("Meiryo", 12),
            command=self.save_and_next
        ).pack(pady=30)

    # -----------------------------
    # 保存
    # -----------------------------
    def save_and_next(self):

        trial = self.stimuli[self.current_trial]
        answer = self.selected_answer.get()

        correct = 1 if answer == trial["correct_answer"] else 0

        with open(
            self.result_path,
            "a",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.writer(f)

            writer.writerow([
                self.participant_id,
                trial["id"],
                trial["condition"],
                trial["score"],
                trial["length"],
                self.text_start_time,
                self.text_end_time,
                self.question_start_time,
                self.question_end_time,
                trial["correct_answer"],
                answer,
                correct,
                self.response_time,
                self.understanding.get(),
                self.confidence.get()
            ])

        self.current_trial += 1

        if self.current_trial >= len(self.stimuli):

            self.clear_frame()

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