# 音響FEM用の簡略形状テンプレート作成

このディレクトリは工程Bの実装用。全体仕様とSVGは親ディレクトリの [SPEC.md](../SPEC.md) を参照する。

## 初期の構成

| 場所 | 使用するもの |
|---|---|
| Windows 11 | 既存のCodexとPowerShell。CodexはこのディレクトリでPythonの単一機能コマンドを実行する。 |
| このディレクトリの `.venv` | `uv venv` で既存のWindows x64版 Python 3.11を指定し、`uv pip` でCadQueryとその依存のOCPを入れる。OCP経由でOCCTの形状・XDE APIを使う。 |
| Windowsの確認画面 | OCCT AIS。B2の画面を試作するときに、同じ環境へQtのPythonバインディングを入れる。まずPySide6とAISのウィンドウ表示・面選択が動くか確認する。 |
| WSL | Bの初期開発はWindows側で進める。Linuxでのバッチ実行が必要になった場合に、WSL内に別のPython環境を作る。 |

このPCはWindows ARM64で、導入済みのPython 3.11.9はWindows x64版（`win-amd64`）。Windows向けOCPのx64 wheelを使うため、このPythonを明示して仮想環境を作る。OCCTはCadQueryの依存経由で導入する。Gmsh、pyNastran、CalculiXは工程Aに着手する段階で導入する。

## Windowsでの手動セットアップ

導入済みの `uv` を使用する。PowerShellで、カレントディレクトリが親の `like3d` の場合に以下を実行する。

```powershell
Set-Location .\template-builder
uv venv --python 'C:\Program Files\Python311\python.exe' .venv
uv pip install --python .\.venv\Scripts\python.exe cadquery
& .\.venv\Scripts\python.exe -c "import cadquery as cq; from OCP.STEPCAFControl import STEPCAFControl_Reader; from OCP.AIS import AIS_Shape; print(cq.Workplane('XY').box(1, 1, 1).val().Volume())"
```

最後のコマンドで単位立方体の体積（およそ1）が出れば、基本の形状生成とXDE・AISモジュールの読み込みを確認できる。AISの描画と面選択は、GUI試作時にWindowsの対話セッションで確認する。

## B1の実行

`template-builder/` で実行する。抽出担当が最初のコマンドを実行し、抽出チェッカーが元のSTEPと出力ディレクトリを受け取って、別のコマンドで照合する。

```powershell
& .\.venv\Scripts\python.exe .\extract_assembly.py .\machine.step .\b1-output
& .\.venv\Scripts\python.exe .\check_assembly.py .\machine.step .\b1-output
```

- 抽出には新しい出力ディレクトリ名を指定する。`assembly.json` に配置ごとのID、親ID、名前、親基準と全体基準の変換行列を記録する。`parts/` のBREPは部品ローカル座標で保存し、同一のBREPは複数配置から参照できる。
- 座標はmm。変換は行優先の3×4行列で、左3列が線形変換、最後の列が並進。配置IDは同じ入力STEPの中で使う。
- 照合は元のSTEPを読み直し、配置の欠落・重複、名前・親子関係・変換の差、形状ファイルの欠落・変更を報告する。JSONの状態と終了コードは `ok` が0、`ng` が2、入力・実行エラーが1。
- 実機の入力と出力はGitの管理外に置く。上の出力ディレクトリ名 `b1-output` はGitで除外する。

## B2の試作画面

Windowsの対話セッションで、B1の抽出結果をOCCT AISに表示する。Qtの依存は同じ仮想環境に入れる。

```powershell
uv pip install --python .\.venv\Scripts\python.exe PySide6-Essentials
& .\.venv\Scripts\python.exe .\review_faces.py .\b1-output .\b1-output\face-pair.json
```

異なる部品の面を左クリックで1面ずつ選ぶと、両面がオレンジ色になる。右ドラッグで回転、ホイールで拡大・縮小できる。「保存」を押してから同じコマンドで開くと、選択した面ペアを再表示する。

### 接合面候補を自動提案する

```powershell
& .\.venv\Scripts\python.exe .\propose_contacts.py .\b1-output .\b1-output\contacts.json --max-gap-mm 0.1 --min-overlap-mm2 0.01
& .\.venv\Scripts\python.exe .\review_faces.py .\b1-output .\b1-output\face-pair.json --candidates .\b1-output\contacts.json
```

しきい値は例。対象モデルに合わせて、最大隙間をmm、最小重なり面積をmm²で指定する。候補は、別部品の平行な平面同士で、法線が逆向き、面間の隙間が範囲内、投影した面の重なりが指定面積以上の組とする。辺・点だけの接触は候補から除く。

画面上部の候補一覧に隙間と重なり面積を表示する。候補を選ぶと両面がオレンジ色になり、向かい合って隠れる面は下部の表示切り替えで片側ずつ確認できる。手動で選び直す操作も使える。

候補ファイルには複数の候補を出力する。画面で保存できるレビュー結果は1組。面参照は部品配置IDとBREPの面インデックスで、候補とレビュー結果を元のB1マニフェストにひもづける。曲面の候補生成、複数面をまとめた接合、寸法変更をまたぐ面の追跡は後続で扱う。

## 最初の実装範囲

1. **B1 抽出**。STEPアセンブリ1件から部品と配置を取得し、部品名・配置ID・単位を一覧に出す。対象部品と周辺部品を後続処理へ渡せるようにする。
2. **B2 接合候補とレビュー**。元の配置から、距離・向き・重なりで接合面候補を抽出する。AISで両側の面を同色にし、確認・修正した面ペアと期待する隙間をJSONで保存する。
3. **B3–B6 テンプレートと検証**。履歴を持つCadQueryテンプレートを試しフィットし、再組み立て時の接合検査と円筒差し引き後の空間検査を経て登録する。

Codexからは作業とチェックを別の呼び出しにし、ファイルで成果物を渡す。人による確認はAISで行い、保存した結果を後続工程で読む。最初の入力はSTEPとし、Parasolid直接入力は親の仕様にある検証項目として扱う。

[CadQueryのインストール資料](https://cadquery.readthedocs.io/en/stable/installation.html) · [OCPの配布ファイル](https://pypi.org/project/cadquery-ocp/#files) · [OCCT AISの可視化ガイド](https://occt3d.com/dev/doc/overview/html/occt_user_guides__visualization.html)
