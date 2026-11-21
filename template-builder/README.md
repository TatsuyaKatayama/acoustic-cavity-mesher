# 音響FEM用の簡略形状テンプレート作成

このディレクトリは工程Bの実装用。全体仕様とSVGは親ディレクトリの [SPEC.md](../SPEC.md) を参照する。

## 初期の構成

| 場所 | 使用するもの |
|---|---|
| Windows 11 | 既存のCodexとPowerShell。CodexはこのディレクトリでPythonの単一機能コマンドを実行する。 |
| このディレクトリの `.venv` | 既存のWindows x64版 Python 3.11を使い、CadQueryとその依存のOCPを入れる。OCP経由でOCCTの形状・XDE APIを使う。 |
| Windowsの確認画面 | OCCT AIS。B2の画面を試作するときに、同じ環境へQtのPythonバインディングを入れる。まずPySide6とAISのウィンドウ表示・面選択が動くか確認する。 |
| WSL | Bの初期開発はWindows側で進める。Linuxでのバッチ実行が必要になった場合に、WSL内に別のPython環境を作る。 |

このPCはWindows ARM64で、導入済みのPython 3.11.9はWindows x64版（`win-amd64`）。Windows向けOCPのx64 wheelを使うため、このPythonを明示して仮想環境を作る。OCCTはCadQueryの依存経由で導入する。Gmsh、pyNastran、CalculiXは工程Aに着手する段階で導入する。

## Windowsでの手動セットアップ

PowerShellで、カレントディレクトリが親の `like3d` の場合に以下を実行する。

```powershell
Set-Location .\template-builder
& 'C:\Program Files\Python311\python.exe' -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install cadquery
& .\.venv\Scripts\python.exe -c "import cadquery as cq; from OCP.STEPCAFControl import STEPCAFControl_Reader; from OCP.AIS import AIS_Shape; print(cq.Workplane('XY').box(1, 1, 1).val().Volume())"
```

最後のコマンドで単位立方体の体積（およそ1）が出れば、基本の形状生成とXDE・AISモジュールの読み込みを確認できる。AISの描画と面選択は、GUI試作時にWindowsの対話セッションで確認する。

## 最初の実装範囲

1. **B1 抽出**。STEPアセンブリ1件から部品と配置を取得し、部品名・配置ID・単位を一覧に出す。対象部品と周辺部品を後続処理へ渡せるようにする。
2. **B2 接合候補とレビュー**。元の配置から、距離・向き・重なりで接合面候補を抽出する。AISで両側の面を同色にし、確認・修正した面ペアと期待する隙間をJSONで保存する。
3. **B3–B6 テンプレートと検証**。履歴を持つCadQueryテンプレートを試しフィットし、再組み立て時の接合検査と円筒差し引き後の空間検査を経て登録する。

Codexからは作業とチェックを別の呼び出しにし、ファイルで成果物を渡す。人による確認はAISで行い、保存した結果を後続工程で読む。最初の入力はSTEPとし、Parasolid直接入力は親の仕様にある検証項目として扱う。

[CadQueryのインストール資料](https://cadquery.readthedocs.io/en/stable/installation.html) · [OCPの配布ファイル](https://pypi.org/project/cadquery-ocp/#files) · [OCCT AISの可視化ガイド](https://occt3d.com/dev/doc/overview/html/occt_user_guides__visualization.html)
