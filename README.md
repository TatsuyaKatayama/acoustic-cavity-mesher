# acoustic-cavity-mesher

機械アセンブリの簡略化と、音響FEM用の内部空間テトラメッシュ生成を自動化するプロジェクトです。Aは設計者向けのメッシュ生成、Bは簡略形状テンプレートの作成・改訂です。Bから実装します。

- [全体仕様と図](SPEC.md)
- [工程Bのセットアップと初期実装範囲](template-builder/README.md)

## インストール（CAD・Viewer Core・ビューアー・Codex）

このプラグインは、Codexが開いたローカルのチェックアウトで既存のCADコマンドを呼び出します。
先に同じPCに **Windows x64版Python 3.11** と **uv** を入れてください。Windows ARM64でも、
このプロジェクトで検証したのはx64版Pythonとx64版CADライブラリの組み合わせです。

1. このリポジトリをチェックアウトし、ルートをPowerShellで開きます。
2. 下のコマンドでCADエンジン、Viewer Core、Webビューアーを同じ仮想環境にインストールします。
3. リポジトリをCodexデスクトップで開きます。再起動してプラグイン一覧の
   **Acoustic Cavity Mesher** ソースから **acoustic-cavity-mesher** をインストールします。
   リポジトリ側のソース定義は `.agents/plugins/marketplace.json` です。
4. このプロジェクトの新しいチャットでプラグインを選択し、手元のSTEPを指定して
   「このSTEPでB1だけを実行して」と依頼します。
   [Codexのローカルプラグイン手順](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)

### CADとビューアーのセットアップ

| 役割 | インストールするもの |
| --- | --- |
| CAD処理 | CadQueryと、その依存のOCP（OCCT）。STEP/BREPの入出力、生成、形状演算に使用 |
| Viewer Core | OCP Viewer Core。比較・色分け表示用のCADデータ変換に使用 |
| ビューアー | OCP Viewer。配布物に含まれるthree-cad-viewerをブラウザで表示 |

```powershell
Set-Location .\template-builder
# インストール先が異なる場合はx64版Python 3.11の実際のパスに置き換える
uv venv --python 'C:\Program Files\Python311\python.exe' .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
& .\.venv\Scripts\python.exe -c "import cadquery, OCP, ocp_viewer, ocp_viewer_core; print('CAD and Web viewer OK')"
```

すでにこのプロジェクト用の `.venv` がある場合は、環境の作成を省略し、
`uv pip install` から実行します。依存ファイルにはCadQueryとWebビューアーを含みます。
この構成でSTEPを読み、CADを生成し、比較ビューを開けます。別のCADアプリや
ブラウザ拡張、npmの導入は不要です。PySide6は任意の旧Qt/AIS画面を使う場合に追加してください。
[Webビューアーの起動方法](template-builder/README.md#webビューアでcadを開く)

### Codex CLIから登録する場合

リポジトリのルートで実行します。この方法でも、新しいCodexチャットは同じチェックアウトで開きます。

```powershell
codex plugin marketplace add .
codex plugin add acoustic-cavity-mesher@acoustic-cavity-mesher-local
```

### ACPとPythonによる実行構成

最終構成は **Pythonが作業順・成果物・人の確認待ちを管理し、ACPで役割別のLLMを呼ぶマルチエージェント方式**です。作成担当が配置ごとのCadQueryコードを生成し、独立したチェッカーが検証します。CAD演算と表示は同じローカルCLIを使います。
Codexプラグインはローカルで工程を使う入口です。現在のACP実装はB3の1配置単位で試行でき、全工程の一括運転は今後の範囲です。ACPプロバイダーの設定は工程Bの手順を参照してください。
[ACPの設定と試行](template-builder/README.md#acpでpythonから役割エージェントを呼ぶ)

### ビューアーのライセンス

本リポジトリのMITライセンスは本リポジトリのコードに適用されます。
依存パッケージのビューアー本体はプラグインに同梱していません。OCP Viewerと
OCP Viewer CoreはApache-2.0、three-cad-viewerはMITです。それぞれの配布物に
含まれる著作権表示と第三者通知は、比較画面・B2レビュー画面の「ライセンス」から
閲覧できます。 [OCP Viewer](https://github.com/bernhard-42/ocp_viewer) · [OCP Viewer Core](https://github.com/bernhard-42/ocp-viewer-core) · [three-cad-viewer](https://github.com/bernhard-42/three-cad-viewer)

## アーキテクチャ

| 層 | 責務 |
|---|---|
| ワークフロー・エージェント | A・Bの工程順、部品単位の並列実行、作業者とチェッカーの割り当て、人の判断待ちと再開を扱う。初期の実行環境はCodex。 |
| インターフェース | 単一機能のCLIで処理を呼び出す。CAD閲覧・確認画像とB2レビューにはWebビューアーを使う。ファイルと構造化データで結果を受け渡す。 |
| アプリケーション | 部品抽出、フィット、差分計測、接合検査、メッシュ生成などのユースケースを実行する。 |
| ドメイン | 部品の配置、テンプレートのパラメータ、接合条件、判定結果、メッシュの領域・境界の意味を定義する。 |
| 技術アダプター | OCCT、CadQuery、Gmsh、pyNastranなどのライブラリと、CAD・解析ファイルの入出力を扱う。 |

ワークフローと確認画面はアプリケーションの操作を呼び出す。アプリケーションはドメインと入出力の契約に依存し、ライブラリ固有の型と処理はアダプターに置く。A・Bで共通の抽出や計測はリポジトリ内で共有し、B固有の実装は `template-builder/` に置く。

## ライセンス

[MIT License](LICENSE)
