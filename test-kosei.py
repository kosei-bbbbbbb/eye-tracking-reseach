import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_excel("Project15 Data export.xlsx")

fixations = df[df["Eye movement type"] == "Fixation"]

# 散布図
plt.scatter(
    fixations["Fixation point X"],
    fixations["Fixation point Y"],
    s=fixations["Eye movement event duration"] / 10
)

plt.gca().invert_yaxis()
plt.show()

# fixation duration分布
plt.hist(
    fixations["Eye movement event duration"],
    bins=30
)

plt.xlabel("Fixation Duration (ms)")
plt.ylabel("Count")

plt.show()
