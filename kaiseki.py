import pandas as pd

# 1. データの読み込み
# エクセル側（タスクデータ）
df_task = pd.read_csv("P001.csv") 
# Python側（視線データ：仮に gaze_P001.csv とします。タイムスタンプ列を 'timestamp' と想定）
df_gaze = pd.read_csv("gaze_P001.csv") 

# 同期したデータを格納するリスト
synced_gaze_data = []

# 2. 試行（trial）ごとにループを回して視線データを切り出す
for index, row in df_task.iterrows():
    trial_id = row['trial_id']
    condition = row['condition']
    start = row['text_start_time']
    end = row['text_end_time']
    
    # 視線データから、今回の試行の時間内のデータだけを抽出
    trial_gaze = df_gaze[(df_gaze['timestamp'] >= start) & (df_gaze['timestamp'] <= end)].copy()
    
    # 抽出した視線データに、タスクの情報（試行IDや難易度）を紐付ける
    trial_gaze['trial_id'] = trial_id
    trial_gaze['condition'] = condition
    
    synced_gaze_data.append(trial_gaze)

# 3. すべての試行の視線データを一つのデータフレームに結合
df_all_synced_gaze = pd.concat(synced_gaze_data, ignore_index=True)

# 同期済みデータを保存
df_all_synced_gaze.to_csv("P001_synced_gaze.csv", index=False)
print("同期が完了しました！")