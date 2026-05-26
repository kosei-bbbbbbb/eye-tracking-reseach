import tkinter as tk

root = tk.Tk()
root.geometry("800x600")

label = tk.Label(
    root,
    text="おせーーー",
    font=("Meiryo", 24)
)
def next_text():
    label.config(text="あざす")
button = tk.Button(
    root,
    text="ボタン",
    font=("Meiryo", 24),
    command=next_text
)
label.pack()
button.pack()

root.mainloop()