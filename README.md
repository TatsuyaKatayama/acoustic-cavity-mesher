# CAD Rebuilder

STEPアセンブリから、接合や必要な開口を保った簡略CADを再構築し、音響解析用の空間CADを作成・検証するツールです。Codexの親エージェントが案件の進行と承認を管理し、担当と独立チェッカーに短い作業を割り当てます。

## セットアップ

Windows x64版Python 3.11と `uv` を用意し、リポジトリのルートで実行します。Pythonのパスはインストール先に合わせてください。

```powershell
uv venv --python 'C:\Program Files\Python311\python.exe' .venv
$python = '.\.venv\Scripts\python.exe'
uv pip install --python $python -r requirements.txt
& $python .\tools\workspace.py init
```

`requirements.txt` にはCAD処理のCadQueryと、比較・レビュー用のWebビューアーが含まれます。初期化すると標準プロファイルが `local/profile/` に複製され、再初期化では不足ファイルが補われます。

## 案件を始める・再開する

元のSTEPを `local/input/` に置き、案件フォルダを作ります。

```powershell
& $python .\tools\workspace.py start .\local\input\stepassy_a.step --analysis acoustics
```

Codexでこのリポジトリを開き、`local/cases/stepassy_a/` を指定して案件の開始を依頼します。案件の窓口は `local/profile/agents/coordinator/AGENT.md` で定義しています。中断後は同じ案件フォルダを指定して再開を依頼できます。次に着手できる作業をCLIで確認する場合は、次を実行します。

```powershell
& $python .\local\profile\workflows\python\advance_case.py .\local\cases\stepassy_a status
```

Pythonの `status` は保存済みの成果物から次に進める作業を判定し、`dispatch` はその作業の指示と参照先を返します。担当の起動、CAD処理、画面の提示、結果の登録は、親エージェントが各工程の手順に沿って行います。

以下は案件の進行順です。各工程で使えるツールと、担当が行う作業の境界は [実装済みの範囲](docs/case-workflow.md#実装済みの範囲) を参照してください。

| 工程 | 作業 |
|---|---|
| B1 | STEPから部品・配置を抽出し、抽出担当が元STEPと照合する |
| B2 | 接合・簡略化案を独立検査し、提示可の配置から承認を受ける。全配置の承認後に全体を最終確認する |
| B3–B4 | 配置ごとに簡略CADを再構築し、独立チェッカーがフィットと簡略化適合性を評価する |
| B5.1–B5.3 | 再組立、空間CADの生成、必要な修正と再検証を行う。親が結果をまとめ、空間CADと作成履歴のパスを提示する |
| B6 | 記憶反映担当が案件の知見を整理し、ユーザーが採用した改善を反映・検証する |

## Codexプラグイン

Codexで **CAD Rebuilder** ソースから `cad-rebuilder` をインストールします。CLIから登録する場合は、リポジトリのルートで実行します。

```powershell
codex plugin marketplace add .
codex plugin add cad-rebuilder@cad-rebuilder-local
```

## リポジトリ構成

| パス | 内容 |
|---|---|
| `tools/` | CAD処理、検査、レビュー画面、案件初期化のCLI |
| `templates/profile/` | 初期化に使う標準のエージェント定義、技能、ワークフロー |
| `local/profile/` | 案件で使い、ユーザーが育てるプロファイル。短い工程手順は `workflows/base/`、Pythonの進行管理は `workflows/python/` |
| `local/input/`、`local/cases/`、`local/part-rules/` | 元STEP、案件のレビュー・成果物・`improvements.md`、再利用する部品方針 |

`local/` はGit管理外です。

## ドキュメントとライセンス

- [CAD案件の進行と再開](docs/case-workflow.md)
- [CADツールとビューアーの使い方](docs/cad-workflow.md)
- [仕様書](docs/SPEC.md)
- [MIT License](LICENSE)。ビューアー依存ライブラリのライセンスは画面の「ライセンス」から確認できます。
