# CAD案件の進行と再開

親エージェントは案件を開き、Pythonの状態管理と短い工程手順を使って担当者に作業を渡す。B1で抽出を自己照合し、B2は配置別の提案・独立検査・承認を順に記録する。B3は全配置の承認後の全体確認を待つ。B3作成は自己確認までとし、B4で独立検査する。B5は各工程の担当と独立チェッカーが結果を返し、最後に親が空間CADと作成履歴を提示する。B6は案件記録の振り返り、ユーザーが採用した改善の反映と検証、親の完了報告で終わる。

リポジトリのルートから実行する。

```powershell
$python = '.\.venv\Scripts\python.exe'
$advance = '.\local\profile\workflows\python\advance_case.py'
$case = '.\local\cases\stepassy_a'
& $python $advance $case status
& $python $advance $case dispatch TICKET
& $python $advance $case record TICKET ok --evidence "$case\artifacts\report.json"
```

- `status` は着手できるタスク、担当、許容する結果、依存する記録を返す。`dispatch` は1タスクの手順と役割指示を返す。親がその指示を担当に渡す。LLMの起動には、利用中のエージェント実行環境を使う。
- `record` は進行役が結果を登録する。B1では確認済み配置IDごとに `--placement`、B2の配置別タスクでは `--proposal-revision` を付ける。B2の配置別承認は既存レビューで記録し、該当版を含む確認JSONのスナップショットを添える。全体承認ではユーザーの最終確認とB3引き渡しを保存する。
- 中断したら新しいチャットで案件フォルダを指定し、再度 `status` を実行する。差し戻しは `reopen TASK_KEY` で原因工程の結果を退避する。結果は版ごとの別ファイルに記録し、承認済みの証拠は上書きしない。
- 既存のローカルプロファイルは `tools/workspace.py init` を再実行すると追加ファイルが補われる。編集済みの役割定義は標準版との差分を確認し、必要な更新を取り込む。
