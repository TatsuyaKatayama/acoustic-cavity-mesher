# CAD Rebuilder

機械アセンブリのCADを簡略化し、音響解析に使う内部空間を抽出・検証するプロジェクトです。

- [CADツールのセットアップと使い方](docs/cad-workflow.md)
- [仕様書と工程・技能の図](docs/SPEC.md)

## ローカル案件を始める

セットアップ後、リポジトリのルートで実行します。

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python .\tools\workspace.py init
# 元のSTEPを local/input/ に置いてから実行する
& $python .\tools\workspace.py start .\local\input\stepassy_a.step --analysis acoustics
```

初期化は `templates/profile/` から不足ファイルを補い、既存のユーザー定義を保持します。
案件開始は `local/cases/stepassy_a/` に案件設定、レビュー・成果物の保存先、
`improvements.md` を作成します。STEP抽出とレビュー以降は
[作業手順](docs/cad-workflow.md)に従って進めます。
案件の続行は [中断・再開できる案件手順](docs/case-workflow.md) を参照してください。
`trial_rebuild_step_part.py` は確定済みの入力を用いた従来の単一部品試行です。
既存の仮想環境を使う場合は、コマンドの `.venv` を `template-builder/.venv` に読み替えます。

旧案件と部品ルールは従来の `template-builder/b1-output/` にあります。
新規案件の部品ルールの既定保存先は `local/part-rules/` です。

## インストール（CAD・Viewer Core・ビューアー・Codex）

このプラグインは、Codexが開いたローカルのチェックアウトで既存のCADコマンドを呼び出します。
先に同じPCに **Windows x64版Python 3.11** と **uv** を入れてください。Windows ARM64でも、
このプロジェクトで検証したのはx64版Pythonとx64版CADライブラリの組み合わせです。

1. このリポジトリをチェックアウトし、ルートをPowerShellで開きます。
2. 下のコマンドでCADエンジン、Viewer Core、Webビューアーを同じ仮想環境にインストールします。
3. リポジトリをCodexデスクトップで開きます。再起動してプラグイン一覧の
   **CAD Rebuilder** ソースから **cad-rebuilder** をインストールします。
   リポジトリ側のソース定義は `.agents/plugins/marketplace.json` です。
4. このプロジェクトの新しいチャットでプラグインを選択し、手元のSTEPを指定して
   「このSTEPから部品と配置を抽出して」と依頼します。
   [Codexのローカルプラグイン手順](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)

### CADとビューアーのセットアップ

| 役割 | インストールするもの |
| --- | --- |
| CAD処理 | CadQueryと、その依存のOCP（OCCT）。STEP/BREPの入出力、生成、形状演算に使用 |
| Viewer Core | OCP Viewer Core。比較・色分け表示用のCADデータ変換に使用 |
| ビューアー | OCP Viewer。配布物に含まれるthree-cad-viewerをブラウザで表示 |

```powershell

# インストール先が異なる場合はx64版Python 3.11の実際のパスに置き換える
uv venv --python 'C:\Program Files\Python311\python.exe' .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
& .\.venv\Scripts\python.exe -c "import cadquery, OCP, ocp_viewer, ocp_viewer_core; print('CAD and Web viewer OK')"
```

すでにこのプロジェクト用の `.venv` がある場合は、環境の作成を省略し、
`uv pip install` から実行します。依存ファイルにはCadQueryとWebビューアーを含みます。
この構成でSTEPを読み、CADを生成し、比較ビューを開けます。別のCADアプリや
ブラウザ拡張、npmの導入は不要です。PySide6は任意の旧Qt/AIS画面を使う場合に追加してください。
[Webビューアーの起動方法](docs/cad-workflow.md#webビューアでcadを開く)

### Codex CLIから登録する場合

リポジトリのルートで実行します。この方法でも、新しいCodexチャットは同じチェックアウトで開きます。

```powershell
codex plugin marketplace add .
codex plugin add cad-rebuilder@cad-rebuilder-local
```

### 親エージェントと短いワークフロー

親エージェントがユーザーとの対話、承認、差し戻し、再開を担当します。
工程別の手順は `profile/workflows/base/`、実行可能な次の作業を判定するPythonは
`profile/workflows/python/` にあります。担当とチェッカーは、割り当てられた作業の
技能とツールを使い、結果を案件フォルダに保存します。
従来の単一部品ACP試行も利用できます。 [ACPの設定と試行](docs/cad-workflow.md#acpでpythonから役割エージェントを呼ぶ)

### ビューアーのライセンス

本リポジトリのMITライセンスは本リポジトリのコードに適用されます。
依存パッケージのビューアー本体はプラグインに同梱していません。OCP Viewerと
OCP Viewer CoreはApache-2.0、three-cad-viewerはMITです。それぞれの配布物に
含まれる著作権表示と第三者通知は、比較画面・接合・簡略化レビュー画面の「ライセンス」から
閲覧できます。 [OCP Viewer](https://github.com/bernhard-42/ocp_viewer) · [OCP Viewer Core](https://github.com/bernhard-42/ocp-viewer-core) · [three-cad-viewer](https://github.com/bernhard-42/three-cad-viewer)

## アーキテクチャ

| 層 | 責務 |
|---|---|
| ワークフロー・エージェント | 案件の進行、担当割り当て、人の判断待ち、成果物からの再開を扱う。初期の実行環境はCodex。 |
| インターフェース | 単一機能のCLIで処理を呼び出す。CAD閲覧・確認画像と接合・簡略化レビューにはWebビューアーを使う。ファイルと構造化データで結果を受け渡す。 |
| アプリケーション | 部品抽出、フィット、差分計測、接合検査、内部空間の抽出などのユースケースを実行する。 |
| ドメイン | 部品の配置、テンプレートのパラメータ、接合条件、判定結果、メッシュの領域・境界の意味を定義する。 |
| 技術アダプター | OCCT、CadQueryなどのライブラリと、CAD・解析ファイルの入出力を扱う。 |

ワークフローと確認画面はアプリケーションの操作を呼び出す。アプリケーションはドメインと入出力の契約に依存し、ライブラリ固有の型と処理はアダプターに置く。CAD処理の実装は `tools/` に置く。

## ライセンス

[MIT License](LICENSE)
