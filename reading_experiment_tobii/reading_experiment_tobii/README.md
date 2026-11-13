# 2日間の読解実験とTobii視線解析

## 実験を行う

ZIPを展開し、Windowsの実験用PCで、この中の `reading_experiment_two_days.py` を実行します。元の2日間版に、Tobiiと照合するWindowsのQPC時刻（マイクロ秒）をイベントログに記録する処理を追加しています。1日目と2日目ともに、実験アプリとTobii Pro Labを同じWindows PCで動かしてください。

1. 各日の練習終了後、Tobiiのキャリブレーションを行い、Pro Labで録画を開始します。
2. 実験アプリの「録画開始済み・本実験を開始（SYNC）」を押します。
3. 1分の小休憩中は録画を続けます。1時間の休憩では録画を停止して保存し、再開時はキャリブレーション後に新規録画を開始してから「RESUME_SYNC」を押します。
4. 当日の実験終了画面が出たら、その区間の録画を停止して保存します。

Pro Labの録画名に参加者ID・日・区間番号を含めておくと、書き出し時に対応を確認できます。例は `P001_day1_seg01` です。

## Tobii Pro Labから書き出す

Data Exportで、録画1本につき1つのTSVを出力します。CSVとXLSXにも対応します。長時間録画にはTSVが適しています。タイムスタンプの単位は **microseconds（µs）** を指定します。以下は英語の列名です。

| 用途 | 列 |
|---|---|
| 同期に必須 | `Recording timestamp`、`Computer timestamp`、`Sensor`、`Recording name`、`Event` |
| 視線座標に必須 | `Gaze point X`、`Gaze point Y` |
| 停留とサッカード | `Eye movement type`、`Eye movement type index` |
| 最初の停留位置 | `Fixation point X`、`Fixation point Y` |
| 有効性・瞳孔径 | `Validity left`、`Validity right`、`Pupil diameter left`、`Pupil diameter right` |
| 録画の取り違えチェック | `Recording date UTC`、`Recording start time UTC` |

停留とサッカードはPro Labの分類結果を使います。たとえば予備実験と同じ **Tobii I-VT (Fixation)** を参加者・実施日でそろえます。録画の先頭と末尾を含む全区間を書き出し、`Event`列の `RecordingStart` と `RecordingEnd` を残してください。

## 1. 日ごとに同期する

プログラムが置いてあるフォルダをVS Codeで開き、ターミナルで実行します。下記はWindowsの例です。

1. 各日フォルダ（例 `results/P001/two_day/day1`）に、その日の書き出しを録画順に `tobii_01.tsv`、`tobii_02.tsv`、…という名前で置きます。録画の区切りは1時間休憩です。
2. 同期コマンドを各日に実行します。

```powershell
py sync_tobii.py --session "results/P001/two_day/day1"
py sync_tobii.py --session "results/P001/two_day/day2"
```

ファイル名を変えずに使う場合は、録画ごとに `--recording` を指定できます。

```powershell
py sync_tobii.py --session "results/P001/two_day/day1" --recording "1=C:/exports/Recording 1.tsv" --recording "2=C:/exports/Recording 2.tsv"
```

XLSXを読む場合のみ、事前に `py -m pip install openpyxl` を実行します。すでに `Recording timestamp` をミリ秒で書き出した場合は `--recording-unit ms` を加えます。別のPCで解析する場合は、対象の `results` フォルダも持っていきます。

各日の `sync` フォルダに次のファイルを出力します。

| ファイル | 内容 |
|---|---|
| `sync_report.csv` | 録画名、対応するファイル、同期方法、割り当てたサンプル数、サンプルがない画面数 |
| `aligned_events.csv` | 実験イベントを各Tobii録画の開始からの秒数に換算 |
| `phase_windows.csv` | 文章・問題前自信・問題・回答後アンケートそれぞれの開始・終了・サンプル数 |
| `synced_gaze_samples.csv` | 各画面に割り当てたEye Trackerのサンプル。時刻範囲は開始以上・終了未満 |

まず `sync_report.csv` で録画順と `method=qpc` を確認します。数試行をPro Labの録画で再生し、文章画面の切替と `aligned_events.csv` の `recording_sec` が対応するかも確認します。QPCでそろうのはソフトウェア側の時刻です。画面に実際に描画された瞬間との差は、この方法では測っていません。UTC情報がある場合は録画の取り違えを検出する補助に使います。

### 以前の2日間版ですでに収録した場合

旧版にはQPC列がありません。録画映像とTobiiの `MouseEvent` からアプリの **同じSYNCまたはRESUME_SYNCボタンを離したクリック** を特定できる場合に、対応する `Computer timestamp`（µs）を区間ごとに指定できます。

```powershell
py sync_tobii.py --session "results/P001/two_day/day1" --anchor "1=644167212772" --anchor "2=647898756321"
```

数字は例です。録画開始時刻を代用せず、実際のクリック時刻を使ってください。手動同期はクリックとアプリのイベント処理の時間差やPC時計の変動を含む近似で、出力上も `manual` と区別します。対応するクリックが特定できない録画については、この方法で同期時刻を確定できません。

## 2. 視線を解析する

```powershell
py analyze_gaze.py --session "results/P001/two_day/day1" --session "results/P001/two_day/day2" --out "analysis/P001"
```

複数の参加者をまとめる場合は、対象の `--session` を追加します。

| ファイル | 内容 |
|---|---|
| `trial_features.csv` | 1試行1行。行動ログ、教師ラベル、文章画面の視線特徴量 |
| `phase_summary.csv` | 1画面1行。各画面の視線特徴量と品質フラグ |
| `label_summary.csv` | 参加者・日・難易度ごとの正答率、ラベル件数、視線品質がOKの読解試行数 |

- 視線座標は画面内にあり、有効性の値がある場合は少なくとも片目が有効なサンプルを数えます。瞳孔径は有効な目の正の値をサンプルごとに平均し、画面内の平均・母分散を出します。
- 停留・サッカードはPro Labの分類とイベント番号から数えます。停留時間は当該画面に含まれる有効な停留サンプルの時間から推定し、長いサンプル欠損は加算しません。複数画面にまたがる同じ停留は、各画面の集計にそれぞれ現れる場合があります。
- 初期設定は60 Hz、品質フラグの閾値は0.80です。有効サンプル数を実際に届いたサンプル数と期待サンプル数の両方で割り、いずれかが閾値未満なら `low_valid_gaze` とします。分類情報が使えない画面は `movement_unavailable` とし、特徴量は空欄にします。低品質試行を自動で除外する処理は入れていません。必要に応じて `--sample-hz` と `--min-valid-ratio` で指定できます。
- ラベルは問題前自信度4〜5かつ誤答を `overconfidence`、1〜2かつ誤答を `non_understanding` とします。4〜5かつ正答は `appropriate_understanding`、1〜2かつ正答は `low_confidence_correct`、自信度3は `other` です。
- 読解中の視線だけで分類する場合は、`text_` の視線特徴量を候補にします。教師ラベルの算出に使った正誤・問題前自信度や、回答後アンケートを入力特徴量に入れると、評価時にラベルや回答後の情報が漏れます。新規参加者への汎化を評価する場合は、同じ人の2日分を同じグループとして分割します。
- 戻り読み率は、試行ごとの本文の行位置やスクロール位置がログにないため算出しません。左向きの移動には、次の行に移る通常の動きも含まれます。

仕様の参照先は [Tobii Pro Lab User Manual v1.207](https://s3.amazonaws.com/lynx.tobii/TobiiProLab_1_207_UserManual.pdf) の Computer timestamp (screen-based) と Data export information です。
