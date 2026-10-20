analyze_behavior_preconfidence.py 出力・使い方説明書
作成日：2026年10月19日
対象：今回提供された analyze_behavior_preconfidence.py（プログラム自体の変更なし）

1．何をするプログラムか
回答データCSVを1つ読み込み、正答率、自己評価、読解時間、回答時間、
問題前自信度に基づく状態分類を集計します。
出力は、ターミナル表示、CSVファイル、PNG画像の3種類です。
視線データの同期・停留解析・機械学習による分類は行いません。

2．使い方と保存場所
(1) pandas、matplotlibが入ったPython環境で実行します。
    python analyze_behavior_preconfidence.py
(2) ファイル選択画面で、実験の回答データCSVを選びます。
    Tobiiの視線CSVやイベントログではありません。
(3) 選択したCSVと同じフォルダに behavior_analysis が作られます。
    その中にCSVとグラフが保存されます。
    例：results/P001/P001.csvを選択
        → results/P001/behavior_analysis/ に保存
(4) ターミナルに「分析完了」が表示されれば処理終了です。
    グラフは画面に表示するのではなく、画像として保存されます。
    ファイル選択をキャンセルすると終了します。

注意：同じ入力フォルダで再実行すると、同名の出力ファイルは上書きされます。
条件により生成されないグラフがあるため、過去の実行結果が残る可能性もあります。

3．入力CSVの列
participant_id             参加者ID
trial_id                   試行ID（1文章・1問を1試行として扱う）
condition                  難易度。easy / medium / hardを想定
score                      文章の難易度スコア（出力に引き継ぐ）
length                     文章の文字数
reading_time_sec           記録された文章読解時間（秒）
answer_time_sec            記録された問題回答時間（秒）
correct_answer             正解の選択肢
participant_answer         参加者が選んだ選択肢
correct                    正誤。正答=1、誤答=0
pre_question_confidence    問題前自信度（1～5を想定）
understanding              自己評価による理解度（1～5を想定）
confidence                 問題回答後の確信度（1～5を想定）

重要：scoreは事前の必須列チェックには含まれていませんが、
試行一覧の出力で使われるため、実際には必要です。
正誤はcorrect列をそのまま使います。正解と参加者の回答から再判定しません。
時間の測定開始・終了がいつかは、実験プログラム側の記録仕様に依存します。
この分析プログラムでは時間を再測定しません。

4．ターミナルに表示される内容
・選択したCSV、保存先、読み込んだ試行数、参加者数
・全体の正答数・誤答数・正答率
・難易度別の正答率
・難易度別の平均理解度
・難易度別の平均問題後確信度、平均問題前自信度
・難易度別の平均読解時間、平均読書速度
・難易度別の平均回答時間
・正答試行／誤答試行それぞれの平均自己評価・時間など
・各試行の正誤、自己評価、状態ラベル
・状態別の件数と割合、難易度×状態の件数
・最後に全体正答率、状態内訳、保存先を再表示

参加者別正答率はCSVに保存されますが、専用の集計表示はありません。
ターミナルの表示内容をまとめたテキストファイルは自動保存しません。

5．CSV出力一覧（計13ファイル）

01_overall_accuracy.csv
  全体の試行数(num_trials)、正答数(num_correct)、誤答数(num_incorrect)、
  正答率(accuracy_percent)。

02_accuracy_by_condition.csv
  難易度別の試行数・正答数・誤答数・正答率。
  accuracyは0～1、accuracy_percentは0～100の表記です。

03_understanding_by_condition.csv
  難易度別の理解度の平均(mean_understanding)と標準偏差
  (std_understanding)、試行数。

04_confidence_by_condition.csv
  難易度別の問題後確信度の平均(mean_confidence)と標準偏差
  (std_confidence)、試行数。

04a_pre_question_confidence_by_condition.csv
  難易度別の問題前自信度の平均(mean_pre_question_confidence)と
  標準偏差(std_pre_question_confidence)、試行数。

05_reading_by_condition.csv
  難易度別の試行数、平均読解時間(mean_reading_time_sec)、
  読解時間の標準偏差(std_reading_time_sec)、
  平均読書速度(mean_reading_speed)、読書速度の標準偏差
  (std_reading_speed)。時間は秒、速度は文字/秒です。
  「1問当たり平均何秒読んだか」を確認する中心的なファイルです。

06_answer_time_by_condition.csv
  難易度別の平均回答時間(mean_answer_time_sec)、
  標準偏差(std_answer_time_sec)、試行数。単位は秒です。

07_correct_incorrect_comparison.csv
  正答／誤答別の試行数、理解度・問題前自信度・問題後確信度の平均と
  標準偏差、平均読解時間・平均読書速度・平均回答時間。
  correct_labelのcorrectは正答、incorrectは誤答です。

08_trial_state_classification.csv
  各試行の参加者ID、試行ID、難易度、score、文字数、正解、選択回答、
  正誤、問題前自信度、理解度、問題後確信度、読解時間、読書速度、
  回答時間、状態(state)の一覧です。
  「どの試行が過信候補だったか」を確認するときに使います。

09_state_counts.csv
  状態別の件数(count)と全試行に占める割合(percent)。
  例：12試行中1件なら8.3%。人数ではなく試行件数です。

10_condition_state_counts.csv
  行が難易度、列が状態の件数表。割合ではありません。
  easy / medium / hardの3行にそろえて出力します。

11_accuracy_by_participant.csv
  参加者別の試行数、正答数、正答率（0～1と百分率）。
  1人分のCSVを入力した場合は、その人の1行だけになります。

all_trials_with_analysis.csv
  入力CSVの全列に、次の分析列を追加した試行データです。
  reading_speed_char_per_sec：文字数÷読解時間（文字/秒）
  correct_percent：correct×100（通常は正答100、誤答0）
  state：問題前自信度と正誤から付けた状態ラベル
  同名の列が入力にある場合、その分析列は再計算されます。

6．グラフ出力一覧（最大12ファイル、PNG・300dpi）
graph_01_accuracy_by_condition.png
  難易度別正答率の棒グラフ（%）。
graph_02_understanding_by_condition.png
  難易度別平均理解度の棒グラフ。
graph_03_confidence_by_condition.png
  難易度別平均問題後確信度の棒グラフ。
graph_03a_pre_question_confidence_by_condition.png
  難易度別平均問題前自信度の棒グラフ。
graph_04_reading_time_by_condition.png
  難易度別平均読解時間の棒グラフ（秒）。
graph_05_reading_speed_by_condition.png
  難易度別平均読書速度の棒グラフ（文字/秒）。
graph_06_answer_time_by_condition.png
  難易度別平均回答時間の棒グラフ（秒）。
graph_07_state_counts.png
  状態別試行件数の棒グラフ。
graph_08_pre_vs_post_confidence.png
  横軸＝問題前自信度、縦軸＝問題後確信度の散布図。
  丸＝正答、×＝誤答。同じ値の点は重なり、全件数は読み取れません。
graph_09_reading_time_preconfidence.png
  横軸＝読解時間（秒）、縦軸＝問題前自信度の散布図。
  正誤や状態による色分けはありません。
graph_10_reading_speed_correctness.png
  正答／誤答別の読書速度の箱ひげ図。
graph_11_answer_time_correctness.png
  正答／誤答別の回答時間の箱ひげ図。

箱ひげ図は、正答・誤答の少なくとも片方に該当指標の非欠損データが
あるときだけ保存されます。片方だけなら、その群だけが表示されます。
棒グラフに標準偏差や信頼区間のエラーバーはありません。
グラフの見出しや軸ラベルは英語です。

7．状態ラベルの正確な判定基準
このプログラムは「問題前自信度」を使います。
問題後確信度(confidence)や理解度(understanding)は判定に使いません。

appropriate_understanding：正答(correct=1)かつ問題前自信度4以上
  → 正答・高自信の試行
low_confidence_correct：正答(correct=1)かつ問題前自信度2以下
  → 正答・低自信の試行
 overconfidence：誤答(correct=0)かつ問題前自信度4以上
  → 過信候補の試行
non_understanding：誤答(correct=0)かつ問題前自信度2以下
  → 未理解候補の試行
other：上記以外
  → 通常は問題前自信度3の試行。自信度や正誤の欠損なども入り得ます。

例：誤答、問題前自信度5、問題後確信度2
    → overconfidence（回答後に自信が下がっていても判定は変わらない）
例：誤答、問題前自信度2、問題後確信度5
    → non_understanding

閾値は冒頭のHIGH_CONFIDENCE=4、LOW_CONFIDENCE=2で指定されています。
1～5の範囲チェックはないため、範囲外の数値でも大小比較で分類されます。
研究ではラベル名を心理状態の確定診断とみなさず、操作的な分類として扱ってください。
1問の誤答だけで文章全体の未理解を、正答だけで十分な理解を断定できません。

8．平均の計算方法と読み方
・平均読解時間＝対象試行のreading_time_secの算術平均。
・各試行の読書速度＝length÷reading_time_sec。
・平均読書速度＝各試行の読書速度の算術平均。
  「全文字数の合計÷全読解時間の合計」とは計算方法が異なります。
・標準偏差(std)はpandas標準の標本標準偏差です。
  有効値が1件しかない場合は算出できず、CSVでは空欄になります。
・平均や標準偏差は欠損値を除外しますが、num_trialsは行数を数えます。
  試行数と実際に平均に使われた件数が一致しない場合があります。
・複数人分のデータを1つのCSVにまとめると、難易度別集計などは全員の
  試行をまとめて計算します。参加者ごとに平均してから平均する方式では
  ないため、試行の多い参加者の影響が大きくなります。

9．現在は出力しないもの
・全難易度をまとめた1問当たりの平均読解時間
・全体平均回答時間、実験全体の所要時間
・参加者別の平均読解時間、文章・問題ごとの正答率集計
・過信／未理解など状態別の平均読解時間・平均視線特徴量
・fixation数、平均fixation時間、回帰率などの視線指標
・統計検定、相関係数、信頼区間、分類器の学習・評価
必要な列があるデータでも、上記が自動で集計されるわけではありません。

10．利用上の注意と確認順序
まず01で正答率、09で状態の件数、08で該当試行を確認します。
次に05で平均読解時間、06で回答時間、10で難易度と状態の偏りを見ます。

正答率が高いことだけで刺激が不適切とは確定できませんが、過信候補と
未理解候補が少ない場合、その比較に必要なデータが集まっていません。
難易度間の違いは、文章長、問題の難しさ、参加者差にも影響されます。
本プログラムはこれらを統計的に調整しません。

不正な正誤値・自信度、重複試行、外れ値、時間0以下は自動修正・除外
しません。時間0では読書速度が無限大になることがあります。
列の型や値の妥当性は入力側で確認してください。

参加者IDは必須列チェックより前に使われます。participant_idがないと
独自のエラー案内より前に停止する場合があります。
古いmatplotlibでは箱ひげ図のtick_labels指定で停止する場合があります。
途中で停止すると、それまでのCSV・画像だけが残るため、ファイルの存在
だけで正常終了と判断せず、ターミナルの「分析完了」を確認してください。
