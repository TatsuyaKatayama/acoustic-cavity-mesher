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

### 複数候補をレビューしてB3へ渡す

```powershell
& .\.venv\Scripts\python.exe .\review_contacts.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json
& .\.venv\Scripts\python.exe .\export_template_inputs.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json .\b1-output\b3-input.json
```

- AISの候補一覧から1件選択し、未確認・採用・除外を指定する。面が違う場合は差し替える側を選んでCAD面をクリックする。一覧の隙間と重なり面積は提案時の値。
- 採用した接合には「塞ぐ」（目標隙間0 mm）または「隙間を残す」（正の目標隙間）と許容差を指定する。隙間を残す場合は、許容差を目標値より小さくし、許容範囲に0 mmが入らないようにする。
- 「レビュー保存」で現在の候補と簡略化メモを保存し、別の候補へ進む。再起動時に同じファイルを指定すると、判断・修正した面・接合条件を復元する。
- 全件判断済みなら、出力CLIが採用面ペアと接合条件だけを `b3-input.json` の `contact_constraints` に書き出す。簡略化部品の寸法目安5〜200 mm、5 mm以下の形状の扱い、例外や残す形状を記したメモは `simplification_guidance` に入る。5 mmは目安として記録し、必要な形状の採否は個別に決める。

面参照には部品配置IDとBREPの面インデックスを使う。レビュー結果は、元のB1マニフェストと提案ファイルにひもづく。曲面候補、複数面を一つの接合とする扱い、寸法変更をまたぐ面追跡は後続で扱う。

## B3の履歴付きテンプレートを生成する

初期テンプレートの対象は平面で取り付けるブロック1種類。XY面を取付基準にし、本体を+Z方向に作り、上面から必要な貫通穴を空ける。元の詳細部品はB2の面参照を検証するために使用し、簡略ソリッドは入力寸法から新規生成する。現在の簡略化レベルは `default`。

`dimensions.json` の例。値はすべてmm、穴の位置は本体の中心を基準とする。

```json
{
  "length": 30,
  "width": 20,
  "height": 10,
  "hole_diameter": 3,
  "hole_x": 2,
  "hole_y": -1
}
```

```powershell
& .\.venv\Scripts\python.exe .\build_template.py .\b1-output .\b1-output\b3-input.json '1/1' .\b1-output\dimensions.json .\b1-output\template --map-face '1=mounting_plane'
```

`'1/1'` は対象部品の配置ID、`'1=mounting_plane'` は採用した候補ID 1の詳細面をテンプレートの取付面に対応づける例。対象部品の採用済み接合条件ごとに `--map-face` を指定する。この対応はB3の作業担当が明示し、出力時に面参照と、生成した形状で名前付き面を一意に特定できることを確認する。

新しい出力ディレクトリに、再生成用のCadQueryコード、各操作後のBREP、最終形状、寸法・基準・名前付き面・接合条件を含む `template.json` を保存する。面インデックスは生成したBREPに対応し、再生成時は `mounting_plane` の名前から解決する。貫通穴は必要形状として定義し、径が5 mm以下でも作成する。詳細CADから寸法を読み取る試しフィットはB4で行う。

## B4の試しフィットと照合

取付ブロック1種類を対象に、B3の名前付き取付面に対応する詳細CAD面から取付平面と法線を得る。面内の向きは担当がアセンブリ座標の `--world-x` で指定する。取付平面上に投影した方向をテンプレートの+Xとし、その座標系で測った本体外形の中心を面内原点にする。外形寸法と、取付面の法線に沿う1つの貫通穴の径・中心を測り、B3の履歴から形状を新規生成する。

```powershell
& .\.venv\Scripts\python.exe .\trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --world-x 1 0 0
& .\.venv\Scripts\python.exe .\check_trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --length-tolerance-mm 0.01 --max-error-cc 0.01
& .\.venv\Scripts\python.exe .\preview_fit.py .\b1-output .\b1-output\fit
```

方向としきい値は例。 `fitted.brep` はアセンブリの絶対座標で保存する。`fit.json` には計測寸法、テンプレートから絶対座標への変換、名前付き面の参照、B2の接合条件を記録する。3番目のコマンドは必要に応じてWindowsのAIS画面で詳細形状と簡略形状を重ねて見るために使う。

別のチェッカーが、元の詳細CADと出力BREPを読み直して2段階で判定する。

1. **フィット到達度**。外形、取付面の位置と向き、穴寸法と中心の誤差を確認する。
2. **部品単体の簡略化適合**。詳細・簡略ソリッドの差から、追加される空間と失われる空間の体積をそれぞれccで報告する。その合計が指定上限以上ならNGとする。円筒から差し引いたアセンブリ全体の空間や相手部品との隙間はB5で確認する。

照合はJSONを標準出力に出し、終了コードはOKが0、NGが2、入力・実行エラーが1。円筒側面が高さ全体にわたる貫通穴を1つ特定できる取付ブロックを対象とする。穴を一意に特定できない場合などは入力エラーを返す。

## B5の再組み立てと空間検証

B1の元配置とB4の絶対座標BREPを使い、対象部品1つを簡略形状に置き換える。ほかの部品はB1の形状・配置を使う。接合面はB2から引き継いだ参照で照合し、正を隙間、負を食い込みとして記録する。重なり面積は元の詳細面ペアに対する比で判定し、対象部品と周辺部品のソリッド同士の食い込み体積も確認する。

```powershell
& .\.venv\Scripts\python.exe .\check_reassembly.py .\b1-output .\b1-output\fit .\b1-output\reassembly-check.json --min-overlap-ratio 0.95 --max-interference-mm3 0.01
& .\.venv\Scripts\python.exe .\build_trial_space.py .\b1-output .\b1-output\fit .\b1-output\reassembly-check.json .\b1-output\space-config.json .\b1-output\trial-space
& .\.venv\Scripts\python.exe .\check_trial_space.py .\b1-output\space-config.json .\b1-output\trial-space .\b1-output\space-check.json
```

2番目のコマンドは、同じB1・B4に対する接合チェックのOKレポートを要求する。円筒から再組み立てに使った全ソリッドと、指定があれば外側埋め用のBREPを差し引き、`space.brep` と由来を記録した `space.json` を出力する。

`space-config.json` の例。円筒と検査点はアセンブリの絶対座標で指定する。しきい値と座標は対象モデルに合わせて決める。

```json
{
  "schema_version": 1,
  "length_unit": "mm",
  "cylinder": {"origin_mm": [0, 0, 0], "axis": [0, 0, 1], "radius_mm": 50, "height_mm": 100},
  "outside_fill_breps": [],
  "air_regions": [{"name": "cavity", "probes_mm": [[0, 0, 20], [0, 0, 80]]}],
  "exterior_probes_mm": [[48, 0, 50]],
  "min_face_area_mm2": 0.01,
  "min_edge_length_mm": 0.05
}
```

- 同じ `air_regions` グループの点は同じ空間成分に入ることを確認する。開口の連通を見る場合は、開口内とその両側に点を置く。別グループ同士の意図しない連通と、検査点で説明できない空間成分もNGにする。
- `exterior_probes_mm` には、円筒内でケーシングや外側埋めが占めるべき位置を指定する。差し引き後に空気が残っていればNG。外側埋め用BREPの相対パスは設定ファイルを基準とし、形状は絶対座標で用意する。
- 微小面・微小辺は、それぞれ独立した面積・長さしきい値で検出する。0を指定した項目は無効になる。簡略化の5 mm目安とは用途が異なる。
- 検査の終了コードはOKが0、NGが2、入力・実行エラーが1。漏れ・開口の判定は指定点と空間成分に基づく。開口の幅や断面積の計測は別途必要。

## B6のテンプレート登録

B4のフィット・簡略化判定、B5の接合・空間検査がすべてOKの場合に登録する。B4照合は `--report` でJSONを保存する。過去のレポートで登録用の照合情報が不足する場合は、現在の照合CLIでレポートを作り直す。

```powershell
& .\.venv\Scripts\python.exe .\check_trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --length-tolerance-mm 0.01 --max-error-cc 0.01 --report .\b1-output\fit-check.json
& .\.venv\Scripts\python.exe .\register_template.py .\b1-output .\b1-output\template .\b1-output\fit .\b1-output\trial-space .\b1-output\registry --version 1 --fit-report .\b1-output\fit-check.json --contact-report .\b1-output\reassembly-check.json --space-report .\b1-output\space-check.json --space-config .\b1-output\space-config.json
```

登録先は例では `b1-output/registry/mounting_block/v1/`。同じ版は上書きできない。テンプレートのCadQueryコード、`registration.json`、B3〜B5の記録、判定レポート、空間設定を保存する。B1・B3・B4・B5の対応をハッシュで照合するため、別の実行のレポートや生成物では登録できない。元CADと検証用BREPは元の検証ディレクトリに保管する。

`registration.json` には、対象にできる形状、パラメータの成立条件、実際に通過した寸法、名前付き面、成果物のハッシュを記録する。初期版は1回の検証につき1寸法セットを保存し、そのケースを実績とする。AのNGを受けた改訂では、該当モデルでB4・B5を再実行し、必要に応じて `--regression-case` で元のNG記録の識別子を残す。

## 最初の実装範囲

1. **B1 抽出**。STEPアセンブリ1件から部品と配置を取得し、部品名・配置ID・単位を一覧に出す。対象部品と周辺部品を後続処理へ渡せるようにする。
2. **B2 接合候補とレビュー**。元の配置から、距離・向き・重なりで接合面候補を抽出する。AISで両側の面を同色にし、確認・修正した面ペアと期待する隙間をJSONで保存する。
3. **B3–B6 テンプレートと検証**。履歴を持つCadQueryテンプレートを試しフィットし、再組み立て時の接合検査と円筒差し引き後の空間検査を経て登録する。

Codexからは作業とチェックを別の呼び出しにし、ファイルで成果物を渡す。人による確認はAISで行い、保存した結果を後続工程で読む。最初の入力はSTEPとし、Parasolid直接入力は親の仕様にある検証項目として扱う。

[CadQueryのインストール資料](https://cadquery.readthedocs.io/en/stable/installation.html) · [OCPの配布ファイル](https://pypi.org/project/cadquery-ocp/#files) · [OCCT AISの可視化ガイド](https://occt3d.com/dev/doc/overview/html/occt_user_guides__visualization.html)
