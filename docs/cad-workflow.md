# 音響FEM用の簡略形状テンプレート作成

このディレクトリには、CADの抽出、簡略化、独立検査、再組み立てと内部空間の検証ツールを置く。

## 初期の構成

| 場所 | 使用するもの |
|---|---|
| Windows 11 | 既存のCodexとPowerShell。CodexはこのディレクトリでPythonの単一機能コマンドを実行する。 |
| このディレクトリの `.venv` | `uv venv` で既存のWindows x64版 Python 3.11を指定し、`uv pip` でCadQueryとその依存のOCPを入れる。OCP経由でOCCTの形状・XDE APIを使う。 |
| Windowsの確認画面 | OCCT AIS。レビューの画面を試作するときに、同じ環境へQtのPythonバインディングを入れる。まずPySide6とAISのウィンドウ表示・面選択が動くか確認する。 |
| WSL | Bの初期開発はWindows側で進める。Linuxでのバッチ実行が必要になった場合に、WSL内に別のPython環境を作る。 |

このPCはWindows ARM64で、導入済みのPython 3.11.9はWindows x64版（`win-amd64`）。Windows向けOCPのx64 wheelを使うため、このPythonを明示して仮想環境を作る。OCCTはCadQueryの依存経由で導入する。

## Windowsでの手動セットアップ

導入済みの `uv` を使用する。PowerShellで、カレントディレクトリが親の `cad-rebuilder` の場合に以下を実行する。

```powershell

uv venv --python 'C:\Program Files\Python311\python.exe' .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
& .\.venv\Scripts\python.exe -c "import cadquery as cq; from OCP.STEPCAFControl import STEPCAFControl_Reader; from OCP.AIS import AIS_Shape; print(cq.Workplane('XY').box(1, 1, 1).val().Volume())"
```

最後のコマンドで単位立方体の体積（およそ1）が出れば、基本の形状生成とXDE・AISモジュールの読み込みを確認できる。AISの描画と面選択は、GUI試作時にWindowsの対話セッションで確認する。

## STEPアセンブリから部品と配置を抽出する

リポジトリのルート で実行する。抽出担当が最初のコマンドを実行し、抽出チェッカーが元のSTEPと出力ディレクトリを受け取って、別のコマンドで照合する。

```powershell
& .\.venv\Scripts\python.exe .\tools\extract_assembly.py .\machine.step .\b1-output
& .\.venv\Scripts\python.exe .\tools\check_assembly.py .\machine.step .\b1-output
```

- 抽出には新しい出力ディレクトリ名を指定する。`assembly.json` に配置ごとのID、親ID、名前、親基準と全体基準の変換行列を記録する。`parts/` のBREPは部品ローカル座標で保存し、同一のBREPは複数配置から参照できる。
- 座標はmm。変換は行優先の3×4行列で、左3列が線形変換、最後の列が並進。配置IDは同じ入力STEPの中で使う。
- 照合は元のSTEPを読み直し、配置の欠落・重複、名前・親子関係・変換の差、形状ファイルの欠落・変更を報告する。JSONの状態と終了コードは `ok` が0、`ng` が2、入力・実行エラーが1。
- 実機の入力と出力はGitの管理外に置く。上の出力ディレクトリ名 `b1-output` はGitで除外する。

## WebビューアでCADを開く

通常のCAD閲覧とCodexの画像確認には、OCP Viewer（three-cad-viewer）を使う。
セットアップ時にOCP ViewerとViewer Coreは導入済み。Qtはこの用途には不要。
CADツールの仮想環境で次のコマンドを実行する。

```powershell
& .\.venv\Scripts\python.exe -m ocp_viewer --host 127.0.0.1 --port 3939
```

[ローカルビューア](http://127.0.0.1:3939)をブラウザで開き、別のPowerShellからモデルを送る。

```powershell
& .\.venv\Scripts\python.exe .\tools\view_cad.py ..\test-data\rotary-compressor-test.step --png .\b1-output\compressor.png
```

STEPアセンブリと絶対座標のBREPを表示できる。PNG保存にはビューアに接続したブラウザが必要。画像確認はCodexがPNGを読み、定量判定には従来のOCCT計測結果を使う。レビューの面参照・判断の保存には、下記の専用Webレビュー画面を使う。

### 詳細・簡易の視点同期

同じ絶対座標の詳細・簡易ファイルを渡す。ローカルの比較ページが開き、左に詳細、右に簡易を表示する。回転・パン・ズームを同期し、表示・非表示は各側のツリーで操作できる。

各ビューの「ID確認」を押し、面やエッジをクリックすると、部品パスと選択要素のIDが表示される。選択フィルターで面またはエッジに絞り込める。表示IDは読み込んだモデル内でのビューアの参照番号で、STEPファイルの `#番号` や抽出データの形状番号とは別に扱う。

```powershell
& .\.venv\Scripts\python.exe .\tools\compare_cad.py .\b1-output\comparison\detailed.brep .\b1-output\comparison\simplified.brep
```

既定のURLは [比較画面](http://127.0.0.1:3940/)。比較画面はインストール済みのthree-cad-viewerを2つ埋め込む。形状変換では OCP Viewer Core の内部オフラインAPIを使うため、更新時は互換性を確認する。動作確認済みの組み合わせは `ocp-viewer 1.3.0` と `ocp-viewer-core 1.2.0`。

- 辺そのものの長さ、穴径、面積、体積を見るには、上部の「形状プロパティ」を押して対応する要素を1つ選ぶ。ビューポート右上のフィルターで Vertex／Edge／Face／Solid を指定できる。
- 2要素間を測るには「距離計測」を押して同じビューで2要素を選ぶ。既定は最短距離。2つ目を Shift を押しながら選ぶと中心間距離になる。「操作に戻る」で計測モードを解除する。
- 比較画面の数値はビューアの表示メッシュに基づく。OCCTによる合否判定には従来の検査CLIを使う。

## 接合面・簡略化レビュー画面（Web）

候補生成と人の承認は別の操作にする。リポジトリのルート で実行する。

```powershell
& .\.venv\Scripts\python.exe .\tools\propose_contacts.py .\b1-output .\b1-output\contacts.json --max-gap-mm 0.1 --min-overlap-mm2 0.01
& .\.venv\Scripts\python.exe .\tools\review_contacts_web.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json
```

既定URLは [Webレビュー](http://127.0.0.1:3941/)。`--port` でポートを変更でき、`--no-browser` ならサーバーだけを起動する。CodexのタブでもこのURLを開ける。Pythonプロセスを起動したまま使い、終了はCtrl+C。通常の比較・断面画面（3940）とは別サーバー。

- 候補一覧に部品名と未確認・採用・除外を表示し、両側の対象面をオレンジ色で強調する。対象2部品・片側・全体の表示、アセンブリツリー、X/Y/Z断面と断面位置を使って確認する。断面は表示面を切るもので、厳密な断面ソリッドを生成しない。
- 「1面目／2面目をクリックで差し替え」を選んでCAD面をクリックする。判断は未確認に戻り、修正面の隙間・重なりをOCCTで再計測する。Web表示のメッシュ計測を合否判定には使わない。
- 各表示リーフは抽出したBREPの1面から生成し、表示パスから `[部品配置ID, BREP面インデックス]` へ対応づける。ビューア内部の要素番号をSTEPの#番号や抽出データの面番号として解釈しない。標準の表示メッシュを作れない面だけ細かい分割で再試行する。これは表示用の再分割で、詳細CADの編集ではない。それでも表示できない面は画面で列挙し、その面を含む採用保存を拒否する。
- 採用時は「塞ぐ」または「隙間を残す」、目標隙間と許容差を指定し、「レビュー保存」を押す。隙間保持時は許容差を目標値より小さくする。簡略化メモも同時に保存する。別候補へ移る前に変更を保存するか戻す。
- 判断・修正面・条件を既存のレビューJSON形式で保存し、同じCLIで再起動すると復元する。別タブが先に保存した場合は上書きを拒否する。抽出データ・候補のハッシュが変わった場合も拒否する。保存先はCLIで指定したローカルファイルに限定する。
- この画面では接合と簡略化を確認し、接合候補生成や形状作成用の出力を自動実行しない。承認は人が行う。接合と簡略化の両方を確認・確定したら `export_template_inputs.py` を別途実行する。既存接合候補の面修正には対応するが、新しい接合行の手動追加は未対応。

### 接合案・簡略化案の統合確認

現在のレビュー画面は、接合案と簡略化案を合わせた部品単位の確認工程とする。
TOPから配置順に最初から色分けして表示し、左の「承認して次の部品へ」で
接合条件と三分類方針を一緒に承認する。部品ごとの承認履歴は
`review.part-confirmations.json` に保存し、以前の版も保持する。
「TOPの面3は残す」などの修正や接合面の変更はチャットで指示する。
修正で表示内容のハッシュが変わるとその部品は未承認に戻る。
全配置の承認がそろうと `confirmed-b2-<id>/` に接合レビュー、簡略化レビュー、
形状作成用の入力を新規保存する。形状作成は自動実行しない。
以下の接合・簡略化の分離は内部データ/APIの説明であり、二段階のUI操作は要求しない。
空間メッシュ用に空隙を埋める場合は、ケースの `fill-preview.json` に配置IDと消える元CAD面番号を記録する。統合確認では充填を先に適用し、その面を含む接合条件を両部品の提案から解除したうえで、残った接合面を保護する。変更した提案は再承認する。

#### 部品ごとのルールを蓄積する

担当は自然言語で受けた保持・簡略化ルールを `b2_part_rules.py` で保存する。
既定保存先はGit管理外の `local/part-rules/`。入力原文、意味上の対象と処置・理由、
元形状ハッシュ、未解決事項、draft/approved/retired状態を版ごとに保存し、旧版は上書きしない。
ルールは1回のレビュー出力とは独立しているため、別の試行でも蓄積した判断を参照できる。

```powershell
& .\.venv\Scripts\python.exe .\tools\b2_part_rules.py save --bundle .\b1-output\case --part '1/1' --policy .\b1-output\policy.json
& .\.venv\Scripts\python.exe .\tools\b2_part_rules.py show --bundle .\b1-output\case --part '1/1'
& .\.venv\Scripts\python.exe .\tools\b2_part_rules.py list
```

policy.jsonには `instruction`（原文）、`interpretation`（target/action/reasonを持つ配列）、
任意の `open_questions` と `face_overrides`（face_index/decision/reason）を記録する。
targetは「主要壁」「局所的な凹凸」「必要な開口」などの意味上の対象であり、面種とは別に扱う。
actionはprotect/preserve/approximate/omit_candidate/ask。未指定の許容差は推測せず未解決として残す。
`--status approved` は人がルールを承認した際だけ指定し、廃止は新しいretired版で記録する。

提案CLIは同じ部品名の意味上のルールを自動で読み込む。表記はUnicode正規化・前後空白除去・
大文字小文字を統一する。寸法や形状が変わっても考え方を引き継ぎ、追加指示の原文を履歴に蓄積する。
同じ意味上のtargetへの追記は最新の解釈へ更新し、それ以外のtargetのルールは保持する。
同一形状だけに限定する場合は保存時に `--exact-geometry` を指定する。
別名称を含む部品群に共用する場合は保存・参照で `--family` / `--rule-family` を明示する。
面ID対応は同一形状かつapprovedの場合だけ提案へ適用し、接合候補と内向き円筒面の保護を優先する。
意味上のルールは提案の `part_rules` に原文と履歴参照を添付するが、局所凹凸の認識・
意味から面への対応は担当の作業として残る。自然言語を自動で認識済みと扱わない。
ルールの承認は、そのケースの簡略化の面セットの承認や形状作成の開始を意味しない。

通常の操作はCodexチャットでの自然言語指示とする。担当が提案をチャットに要約し、
人は部品名・機能・例外で指示する。担当が面参照とセットへの対応を記録し、曖昧な点だけ
確認する。CAD画面の左ペインには部品選択と色分けのみを表示し、ログ・長い一覧・
面やセットの承認フォームを並べない。下記の詳細レビューAPIは担当側の記録に使用できる。
画面で色分けを見ただけでは承認にはならない。
簡略化の確認後も、チャットで接合面の選び直し・条件変更を指示できる。
変更前の接合レビューと簡略化レビューを `.before-contact-<hash>.json` に保存する。
接合条件や対応面が変わると現在の簡略化判断はstaleになり、再検討する。
過去の判断を消去したり、変更後の条件に自動承認として転用したりしない。

まず担当が部品ごとの「残す・簡略化して残す・省略する」案、面参照、理由、
要確認事項を提示する。人に最初から全ての面を分類させない。
接合判断の前でも未承認案を作成・閲覧でき、その場合は未確定の接合候補も保護する。
Web画面の「簡略化案を色で見る」は全体または選択部品の色付き案を表示する。
部品別の三分類・理由はチャットと成果物で提示する。左ペインには並べない。
「Face IDを調べる」を有効にして面をクリックすると、部品名・配置ID・BREP面IDを
画面右下に表示し、コピーできる。これはビューア内部の要素番号やSTEPの#番号とは別の
抽出したBREPの面参照であり、選択のたびに表示を置き換える。提案を見るだけでは判断を変更しない。

```powershell
& .\.venv\Scripts\python.exe .\tools\b2_propose_part.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json all .\b1-output\simplification-proposal.json
```

`all` は全配置を含む提案であり、各配置の接合条件は別々に記録する。
担当は一括提案APIで全配置または1部品の三分類案を取得し、チャットで方針を確認する。
明示された判断をレビューへ反映する際は保存済み判断と接合面を保持し、変更前の
レビューを別ファイルへ退避する。面ごとのUI承認は求めない。
円錐・トーラスをC/R候補とする分類は暫定の幾何ヒューリスティックで、機能形状を
省略してよいと証明するものではない。曲面や開口の機能が不明な箇所は理由と面参照を
添えて確認する。提案JSONは承認済みレビューの代わりに作成入力として使えない。

1. 担当が接合候補を選別し、必要隙間などで迷うものをチャットで質問する。
2. 担当が簡略化案を提示し、人は部品名・機能・例外で指示する。必要ならCAD表示とFace IDで対象を特定する。
3. 担当が面集合に対応づけて判断を保存し、未解決事項と方針の要約を返す。
4. 人の確定指示後にレビューを確定する。作成担当への受け渡しは別工程とし、詳細CADは編集しない。

削除提案の初期ルールは、平面の面内幅（平面のUV範囲の短い側）、円筒面の直径、軸方向幅が目安寸法以下の面。回転した部品でも平面の面内幅を使う。これは小形状を見つけるためのヒューリスティックであり、面の小ささだけで省略可能とは判断しない。面の分割、長穴、穴・開口の連なりをフィーチャーとして自動認識する機能や、その他の曲面の自動削除提案は未対応。周辺の面と併せて確認し、まとめて扱う形状は同一セットに含める。

簡略化セットは同じ部品の1面以上からなる。「残す」「省略する」は部品ごとに各1セット、「簡略化して残す」は複数セットを使える。別セットの面を指定して保存すると、元のセットの他の面を保持して対象面だけを移動する。部品をまたぐセットや面の重複所有は拒否し、接合面は「残す」に固定する。既存セットを選んで編集でき、「セットを解除して再確認する」で解除すると、そのセットに属していた自動提案は未確認へ戻る。

| 分類 | 作成担当へ渡す参照 |
|---|---|
| 残す | 抽出データの部品配置ID＋BREPエッジインデックス、曲線種別、長さ・端点、円弧の中心・半径等。新規スケッチの根拠として使う。 |
| 簡略化して残す | 面参照、平面の位置・法線、円筒の軸・半径・内外向き等と、任意の近似方針。詳細なエッジや細かな作成操作は参照として渡さない。 |
| 省略する | 作成用のエッジ・面形状の参照は渡さない。元の面IDは判断の追跡用にのみ残す。 |

省略面だけが持つエッジは参照外にする。残す面と共有するエッジは、残す面側の根拠で参照できる。未分類面と保護接合面は部品ごとの既定の保持セットに含め、その輪郭の参照を保持する。BREPエッジインデックスもビューアのEdge番号やSTEPの#番号とは別の参照で、元の抽出データのハッシュにひもづく。

「簡略化して残す」では近似方針を「未指定・形状作成時に検討」「体積をできるだけ維持」「外形範囲をできるだけ維持」から任意に選び、方針のメモを保存する。押出方法・勾配・C面・Rなど細かな作成操作は指定しない。C面・Rを省略する `detail_policy: omit_chamfers_and_fillets` を記録する。接合面・必要な開口の保護は、体積などの目標より優先する。

体積維持は目標であり、セットの面が閉じた領域を構成するとは限らないため、面集合から架空のセット体積や許容差を決めない。具体的な近似形状・基準・寸法・履歴は形状作成、体積を比較する範囲・許容差・空間の増減は独立検査以降で確認する。今回の機能は簡略化の方針決定・レビュー・受け渡しまでで、近似ソリッドは生成しない。

接合面は削除提案から除外し、省略するための面参照変更も受け付けない。ファイルを改ざんして保護面を削除対象にした場合も、保存・形状作成用の出力の検証で拒否する。接合面の参照・採否・条件を後から変更すると旧簡略化判断は無効になり、出力を停止する。提案を明示的に作り直す際は、旧判断を `.previous-<hash>.json` に保持してから未確認の提案を生成する。

簡略化は接合面レビューと別の `review.simplification.json` に保存する（接合レビューが `review-web.json` なら `review-web.simplification.json`）。`--simplification-review` で別の保存先も指定できる。接合判断の意味内容のハッシュ、保護面、提案理由・計測値、各面の判断、名前付き `sets`、メモ、確定状態を保存し、再起動で復元する。旧形式のkeep/omit判断はファイルを書き換えず読み込み、部品ごとの単一セットへ統合して表示する。保存時に新形式を記録する。「簡略化して残す」は明示的セットを必須とするが、近似方針は未指定でもよい。旧作成操作付きセットも所属面・採否を保持して読み込むが、旧操作は作成担当へ渡さず、方針を未指定として扱う。保存し直したセットは新しい方針形式になる。別タブ保存の競合も拒否する。

画面を使わず削除提案だけを作る場合は、単一機能CLIを使う。接合面レビューが完了している必要がある。新しい出力ファイルを指定し、Webサーバーの `--simplification-review` にそのパスを渡してレビューする。

```powershell
& .\.venv\Scripts\python.exe .\tools\propose_simplification.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json .\b1-output\review.simplification.json --threshold-mm 5
```

three-cad-viewerの変換は `ocp-viewer-core` の内部オフラインAPIを使うため、更新時は明示的面対応と表示を再検証する。検証済みのバージョンは上記比較画面と同じ。

### 既存のQt/AISレビュー

Windowsの対話セッションで、抽出したCADをOCCT AISに表示する。Qtの依存は同じ仮想環境に入れる。

```powershell
uv pip install --python .\.venv\Scripts\python.exe PySide6-Essentials
& .\.venv\Scripts\python.exe .\tools\review_faces.py .\b1-output .\b1-output\face-pair.json
```

異なる部品の面を左クリックで1面ずつ選ぶと、両面がオレンジ色になる。「保存」を押してから同じコマンドで開くと、選択した面ペアを再表示する。

左のアセンブリツリーで、部品・サブアセンブリ・全体をチェックボックスで表示／非表示にできる。同じ部品形状を複数配置している場合も、それぞれの配置を個別に切り替えられる。面ペアを片側表示するときも、ツリーで非表示にした部品は非表示のままになる。

モデルは陰影付きで表示し、CAD面の境界エッジをAIS標準機能で重ねる。

| 操作 | タッチパッド・キーボード | マウス |
|---|---|---|
| 回転 | Ctrlを押しながら左ドラッグ | 右ドラッグ |
| パン | Shiftを押しながら左ドラッグ | 中ドラッグ |
| ズーム | 2本指で上下スクロール、または3Dビューにフォーカスして `+`／`-` | ホイール |
| 全体表示 | 3Dビューにフォーカスして `F`、または全体表示ボタン | 全体表示ボタン |

### 接合面候補を自動提案する

```powershell
& .\.venv\Scripts\python.exe .\tools\propose_contacts.py .\b1-output .\b1-output\contacts.json --max-gap-mm 0.1 --min-overlap-mm2 0.01
& .\.venv\Scripts\python.exe .\tools\review_faces.py .\b1-output .\b1-output\face-pair.json --candidates .\b1-output\contacts.json
```

しきい値は例。対象モデルに合わせて、最大隙間をmm、最小重なり面積をmm²で指定する。候補は別部品の向かい合う面で、次を対象にする。辺・点だけの接触と食い込みは除外する。

- 平面：平行・逆向き法線、面間隙間が範囲内、投影したトリム面の共通面積が指定以上。
- 円筒面：同軸（反対向きの軸表現も可）の内壁と外壁。内壁半径−外壁半径を隙間とし、外壁側の小さい半径へ投影したトリム面の共通面積を用いる。軸方向・円周方向の部分重なりや穴を保持して計測する。軸一致の許容差は1e-7 mm、軸角度は1e-7 rad。左右手系と面の向きを考慮する。

非同軸円筒、円錐、球面、自由曲面、平面と円筒面の組は未対応。1接合を構成する複数面は独立した候補で、接合グループ化は未対応。候補には追加フィールド `contact_type` (`planar` / `cylindrical`) を記録する。候補IDは各候補ファイルの並び順に依存するため、旧ファイルのレビューを新しい候補へ転用しない。

画面上部の候補一覧に隙間と重なり面積を表示する。候補を選ぶと両面がオレンジ色になり、向かい合って隠れる面は下部の表示切り替えで片側ずつ確認できる。手動で選び直す操作も使える。

### 複数候補をレビューして作成担当へ渡す

```powershell
& .\.venv\Scripts\python.exe .\tools\review_contacts.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json
# 接合面の判断後、Web画面の「2 簡略化」で判断を保存・確定する
& .\.venv\Scripts\python.exe .\tools\review_contacts_web.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json
& .\.venv\Scripts\python.exe .\tools\export_template_inputs.py .\b1-output .\b1-output\contacts.json .\b1-output\review.json .\b1-output\b3-input.json
```

- AISの候補一覧から1件選択し、未確認・採用・除外を指定する。面が違う場合は差し替える側を選んでCAD面をクリックする。一覧の隙間と重なり面積は提案時の値。
- 採用した接合には「塞ぐ」（目標隙間0 mm）または「隙間を残す」（正の目標隙間）と許容差を指定する。隙間を残す場合は、許容差を目標値より小さくし、許容範囲に0 mmが入らないようにする。
- 「レビュー保存」で現在の候補と簡略化メモを保存し、別の候補へ進む。再起動時に同じファイルを指定すると、判断・修正した面・接合条件を復元する。
- 接合面全件判断済み、かつ簡略化レビューの全提案判断・確定済みなら、出力CLIが採用面ペアと接合条件を `b3-input.json` の `contact_constraints` に書き出す。`simplification_guidance.face_review` に保護する接合面、省略する面、明示的に残す面、既定の残す方針、実際の目安寸法、簡略化メモを渡す。実際の簡略形状は履歴付きで新規生成する。片方のレビューだけでは出力しない。既存の接合面レビューJSONはそのまま利用できるが、作成担当へ渡す前に簡略化レビューを追加する必要がある。

面参照には部品配置IDとBREPの面インデックスを使う。レビュー結果は、元の抽出データマニフェストと提案ファイルにひもづく。出力時は修正後の採用面を再計測し、`contact_constraints` に `contact_type` と `source_measurement` を追加する。未確認・対応外・面積のない面ペアは出力しない。Webでの保存・再読込と出力経路は合成CADで検証し、実機入力の承認をテストで代行しない。

円筒対応は接合候補の抽出・レビュー・受け渡しまで。既存の取付ブロック用の生成・照合・接合検査は平面取付を対象とし、円筒対応テンプレートや検査へ自動的に拡張されるものではない。複数面の接合グループ化、その他の曲面、寸法変更をまたぐ面追跡は後続で扱う。

## 形状作成の単一部品マルチエージェントワークフロー

最初の実装は1部品を「進行役 → 作成担当 → チェッカー → 進行役の集約」で処理する。Python CLIはLLMを起動しない。進行役（Codexなど）が役割ごとの別エージェントに生成された指示ファイルを渡して呼び出し、成果物を回収する。将来の並列化はこのワークフローを部品ごとに実行する。役割のIDは別々に指定し、必要なら `--strategy` で戦略担当を割り当てる。

接合面の全件判断と簡略化案の確定が前提。割当時と各段階で元レビューから受け渡しを再照合するため、未確定・変更済みレビューでは開始／再開しない。実機の判断を合成テストで代行しない。

```powershell
# 進行役：既存の出力CLIでレビュー受け渡しを出力してから、1部品を割り当てる
& .\.venv\Scripts\python.exe .\tools\b3_prepare.py .\b1-output .\b1-output\b3-input.json '1/1' .\b1-output\b3-workflow --candidates .\b1-output\contacts.json --review .\b1-output\review.json --simplification-review .\b1-output\review.simplification.json --coordinator coordinator-agent --worker creation-agent --checker check-agent
# LLM作成担当：task.jsonと抽出データから寸法を確認し、この配置のpart.pyとplan.jsonを作る
& .\.venv\Scripts\python.exe .\tools\b3_build.py .\b1-output\b3-workflow\task.json .\b1-output\b3-workflow\plan.json .\b1-output\b3-workflow\attempt-001 --python-source .\b1-output\b3-workflow\part.py
# 別のチェッカー：モデルを修正せず、新しいレポートに検査結果を記録する
& .\.venv\Scripts\python.exe .\tools\b3_check.py .\b1-output\b3-workflow\task.json .\b1-output\b3-workflow\attempt-001 .\b1-output\b3-workflow\check-001.json
# 進行役：結果を照合・集約する。独立検査へは自動遷移しない
& .\.venv\Scripts\python.exe .\tools\b3_collect.py .\b1-output\b3-workflow\task.json .\b1-output\b3-workflow\attempt-001 .\b1-output\b3-workflow\check-001.json .\b1-output\b3-workflow\result-001.json
```

`task.json` は元の抽出データ、承認済みの作成入力、元レビューのハッシュ、対象の面セット、接合条件、元配置、担当IDを保持する。元の絶対座標で新規生成する。`coordinator.txt` / `worker.txt` / `checker.txt` は役割への指示で、担当とチェッカーは自分で相手の作業を兼ねない。役割IDの記録はOSのアクセス制御ではなく、進行役が実際に別エージェントへ割り振る。

標準の部品別手順では、LLM作成担当が配置ごとに `part.py` を書く。回転、スケッチ押し出し、ロフトなど必要なCadQuery操作を選び、承認済みの保持面・接合・開口と今回計測した寸法を使う。詳細CADの読み込みや直接編集は行わない。スクリプトの `build_history()` は工程ごとに `(step_id, model)` を返すジェネレーターで、各形状は絶対座標・mmの有効な単一ソリッドとする。対応する `plan.json` は `schema_version: 1` と `operations` を持ち、各工程に `id`、`source_faces`、`rationale` を記録する。

`--python-source` は内容を確認済みのローカルPythonを作成工程で実行する。コードは `generated.py` として保存し、履歴とハッシュを検査に渡す。独立チェッカーは部品コードを実行せず、保存された形状・履歴とレビュー条件を検査する。独立リプレイの対象外であることは、フィット・外観・体積の独立検査判定とは別に記録する。

既存の宣言型プランは `--python-source` を省略して実行できる。この場合は寸法付き箱・円筒の新規作成と和・差に対応する。以下は宣言型プランの例。

```json
{
  "schema_version": 1,
  "operations": [{
    "id": "body", "operation": "box", "combine": "new",
    "parameters": {"length_mm": 30, "width_mm": 20, "height_mm": 10},
    "frame": {"origin_mm": [0,0,0], "x_direction": [1,0,0], "normal": [0,0,1]},
    "source_faces": [["1/1", 1]],
    "rationale": "残す面の位置・向きと計測寸法を基準に新規生成"
  }],
  "policy_checks": []
}
```

担当は省略面を寸法・基準の参照に使わない。省略面と共有する辺は残す側の面を根拠として扱う。出力は単一の有効ソリッド、各操作後BREP、最終 `final.brep`、寸法と操作順を含む再生成用 `generated.py`、出所・ハッシュを持つ `artifact.json`。失敗時は完成品として保存せず、既存の試行を上書きしない。

チェッカーは「残す」元トリム面領域が同じ向きの出力境界に含まれるか確認する。面を延長して元のエッジが変わることは許容する。初期の包含検査は平面・円筒面に対応し、未対応曲面は要レビュー。方針が体積維持なら `policy_checks` に `{ "set_id": "対象セットID", "scope": "whole_part", "max_volume_difference_mm3": 0.01 }`、外形範囲維持なら `max_envelope_difference_mm` を明示する。評価は元部品全体との比較で、セットの体積を推測しない。方針未指定・評価範囲／許容差未定義は要レビュー。自由文の方針メモも内容を報告して意味の確認を別途要求し、数値条件の通過だけで遵守済みとはしない。履歴形状は担当コードを実行せず、独立した限定プラン解釈で各操作を再生成して対称差を照合する。

省略面が作成参照に含まれないことは機械検査するが、幾何フィーチャーの省略意図まで一般には証明できないため、人の確認事項として報告する。体積維持だけで合格とはしない。生成物の履歴・参照の検査は、独立したフィット・簡略化適合性や再組み立て後の空間検査を代替しない。チェッカー終了コードはok=0、ng/needs_review=2、入力・実行エラー=1。進行役の集約結果はchecked／return_to_worker／review_requiredとなる。NGは新しいattemptで担当へ差し戻す。

```powershell
$env:PYTHONPATH = "$PWD\tools;$PWD\templates\profile\workflows"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_b3_*.py'
```

## 履歴付きテンプレートを生成する

初期テンプレートの対象は平面で取り付けるブロック1種類。XY面を取付基準にし、本体を+Z方向に作り、上面から必要な貫通穴を空ける。元の詳細部品はレビューの面参照を検証するために使用し、簡略ソリッドは入力寸法から新規生成する。現在の簡略化レベルは `default`。

現行 `build_template.py` の取付ブロック生成器は、新しいレビューセットのエッジ保持・面近似・省略方針を実行する機能を持たない。対象部品のセットを含む受け渡しは、方針を黙って無視せず入力エラーとして停止する。セット対応のテンプレートと基準・寸法を定義してから形状作成へ進む。従来のセット参照を持たない入力向けの取付ブロック生成は維持する。

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
& .\.venv\Scripts\python.exe .\tools\build_template.py .\b1-output .\b1-output\b3-input.json '1/1' .\b1-output\dimensions.json .\b1-output\template --map-face '1=mounting_plane'
```

`'1/1'` は対象部品の配置ID、`'1=mounting_plane'` は採用した候補ID 1の詳細面をテンプレートの取付面に対応づける例。対象部品の採用済み接合条件ごとに `--map-face` を指定する。この対応は形状の作成担当が明示し、出力時に面参照と、生成した形状で名前付き面を一意に特定できることを確認する。

新しい出力ディレクトリに、再生成用のCadQueryコード、各操作後のBREP、最終形状、寸法・基準・名前付き面・接合条件を含む `template.json` を保存する。面インデックスは生成したBREPに対応し、再生成時は `mounting_plane` の名前から解決する。貫通穴は必要形状として定義し、径が5 mm以下でも作成する。詳細CADから寸法を読み取る試しフィットは独立検査で行う。

## 試しフィットと独立検査

取付ブロック1種類を対象に、生成形状の名前付き取付面に対応する詳細CAD面から取付平面と法線を得る。面内の向きは担当がアセンブリ座標の `--world-x` で指定する。取付平面上に投影した方向をテンプレートの+Xとし、その座標系で測った本体外形の中心を面内原点にする。外形寸法と、取付面の法線に沿う1つの貫通穴の径・中心を測り、形状の作成履歴から形状を新規生成する。

```powershell
& .\.venv\Scripts\python.exe .\tools\trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --world-x 1 0 0
& .\.venv\Scripts\python.exe .\tools\check_trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --length-tolerance-mm 0.01 --max-error-cc 0.01
& .\.venv\Scripts\python.exe .\tools\preview_fit.py .\b1-output .\b1-output\fit
```

方向としきい値は例。 `fitted.brep` はアセンブリの絶対座標で保存する。`fit.json` には計測寸法、テンプレートから絶対座標への変換、名前付き面の参照、レビューの接合条件を記録する。3番目のコマンドは必要に応じてWindowsのAIS画面で詳細形状と簡略形状を重ねて見るために使う。

別のチェッカーが、元の詳細CADと出力BREPを読み直して2段階で判定する。

1. **フィット到達度**。外形、取付面の位置と向き、穴寸法と中心の誤差を確認する。
2. **部品単体の簡略化適合**。詳細・簡略ソリッドの差から、追加される空間と失われる空間の体積をそれぞれccで報告する。その合計が指定上限以上ならNGとする。円筒から差し引いたアセンブリ全体の空間や相手部品との隙間は再組み立てと空間検証で確認する。

照合はJSONを標準出力に出し、終了コードはOKが0、NGが2、入力・実行エラーが1。円筒側面が高さ全体にわたる貫通穴を1つ特定できる取付ブロックを対象とする。穴を一意に特定できない場合などは入力エラーを返す。

## 微小面・微小辺の共通計測

`measure_features.py` はBREPの最小面積と最短エッジ長を計測する。各最小値には、
入力BREP内の1始まりの面またはエッジ番号と重心座標（mm）が付く。退化エッジは
計測から除外し、件数を別途記録する。

```powershell
& .\.venv\Scripts\python.exe .\tools\measure_features.py .\b1-output\model.brep
```

- **接合・簡略化レビュー**の部品別・全体提案は各配置の詳細形状を `feature_measurements` に記録する。省略方針を確認するための情報で、既存の5 mm目安と面の保持・承認規則はそのまま使う。
- **独立検査**の `b4_check_rebuild.py` は詳細形状と簡略形状について、同じ計測を `feature_measurements` に記録する。フィット・体積に加え、再生成で生じた微小形状を独立確認する。
- **空間検証**では差し引き後の空間を計測する。判定に使う値は `space-config.json` の `min_face_area_mm2` と `min_edge_length_mm` で設定する。

単体CLI、提案CLI、独立検査CLIで `--min-face-area-mm2` または
`--min-edge-length-mm` を指定すると、その値を下回る面・エッジも列挙する。
省略時は最小値を計測し、しきい値による抽出は行わない。提案・独立検査の該当一覧は確認用。

短辺と、その辺を含む面を確認するには `view_short_edges.py` を使う。
指定長**以下**の非退化エッジと、それを含む面のBREP内番号をJSONに出力する。
`--port 0` を付けるとローカル比較ビューで該当面を橙に着色する。

```powershell
& .\.venv\Scripts\python.exe .\tools\view_short_edges.py .\b1-output\model.brep --edge-limit-mm 5 --port 0
```

## 再組み立てと空間検証

1. **再組み立ての確認**では、配置・向き、接合、開口と干渉を確認する。干渉は詳細形状での有無と簡略化後の共通体積を記録し、意図した充填や摺動部を含めて必要な箇所は人が判断する。
2. **空間抽出と検証**では、確認済みの配置から空間を抽出する。まず個別ソリッドを一括で差し引き、必要な場合は対象の組だけの融合を試す。有効な空間、外部への漏れ、連通、孤立成分、微小面・短辺を確認する。短辺の確認には、空間側ID、隣接面の由来、交差する部品や円筒・境界工具を記録する。由来の確認にはブーリアン履歴と境界計測を用い、未特定の箇所は明記する。
3. **微小形状の修正**では、短辺などの修正候補を別に保存する。修正前後の体積変化を計測し、空間差分を再実行して同じ条件で検証する。配置や接合条件が変わるときは再組み立ての確認に戻る。

短辺と微小面の目安は対象のメッシュ条件またはレビュー指示で決める。部品の省略候補を選ぶレビューの5 mm目安とは別に扱う。

配置済みの2つのBREPを一体化できるかは `check_same_domain.py` で試行する。
単一ソリッドとして融合できるかと、両部品に由来する面を同一支持面として
まとめられたかを別々に記録する。入力は同じ絶対座標系で指定する。

```powershell
& .\.venv\Scripts\python.exe .\tools\check_same_domain.py .\a.brep .\b.brep --report .\b1-output\fusion-check.json
```

`--trial-brep` を指定した場合は、有効な単一ソリッドになった試行形状を新規保存する。

下記の既存CLIは単一部品を置き換える試行用。アセンブリ全体を検証するときは、
選択済みの簡略形状を全配置で使い、詳細側と簡略側の対応、入力ハッシュ、
干渉・連通・修正の記録をケース成果物として保存する。

抽出時の配置と検査済みの絶対座標BREPを使い、対象部品1つを簡略形状に置き換える。ほかの部品は抽出データの形状・配置を使う。接合面はレビューから引き継いだ参照で照合し、正を隙間、負を食い込みとして記録する。重なり面積は元の詳細面ペアに対する比で判定し、対象部品と周辺部品のソリッド同士の食い込み体積も確認する。

```powershell
& .\.venv\Scripts\python.exe .\tools\check_reassembly.py .\b1-output .\b1-output\fit .\b1-output\reassembly-check.json --min-overlap-ratio 0.95 --max-interference-mm3 0.01
& .\.venv\Scripts\python.exe .\tools\build_trial_space.py .\b1-output .\b1-output\fit .\b1-output\reassembly-check.json .\b1-output\space-config.json .\b1-output\trial-space
& .\.venv\Scripts\python.exe .\tools\check_trial_space.py .\b1-output\space-config.json .\b1-output\trial-space .\b1-output\space-check.json
```

2番目のコマンドは、同じ抽出データ・簡略形状に対する接合チェックのOKレポートを要求する。円筒から再組み立てに使った全ソリッドと、指定があれば外側埋め用のBREPを差し引き、`space.brep` と由来を記録した `space.json` を出力する。

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

## テンプレート登録

独立検査のフィット・簡略化判定、再組み立て時の接合・空間検査がすべてOKの場合に登録する。フィット照合は `--report` でJSONを保存する。過去のレポートで登録用の照合情報が不足する場合は、現在の照合CLIでレポートを作り直す。

```powershell
& .\.venv\Scripts\python.exe .\tools\check_trial_fit.py .\b1-output .\b1-output\template .\b1-output\fit --length-tolerance-mm 0.01 --max-error-cc 0.01 --report .\b1-output\fit-check.json
& .\.venv\Scripts\python.exe .\tools\register_template.py .\b1-output .\b1-output\template .\b1-output\fit .\b1-output\trial-space .\b1-output\registry --version 1 --fit-report .\b1-output\fit-check.json --contact-report .\b1-output\reassembly-check.json --space-report .\b1-output\space-check.json --space-config .\b1-output\space-config.json
```

登録先は例では `b1-output/registry/mounting_block/v1/`。同じ版は上書きできない。テンプレートのCadQueryコード、`registration.json`、生成・検査・再組み立ての記録、判定レポート、空間設定を保存する。抽出、作成、独立検査、空間検証の対応をハッシュで照合するため、別の実行のレポートや生成物では登録できない。元CADと検証用BREPは元の検証ディレクトリに保管する。

`registration.json` には、対象にできる形状、パラメータの成立条件、実際に通過した寸法、名前付き面、成果物のハッシュを記録する。初期版は1回の検証につき1寸法セットを保存し、そのケースを実績とする。検査結果に基づいて改訂する場合は、該当モデルで独立検査・空間検証を再実行し、必要に応じて `--regression-case` で元のNG記録の識別子を残す。

## Codexから呼び出す入口

Codexは、上記の単一機能CLIをローカルのPython環境で実行し、BREPとJSONを工程間で渡す。抽出、接合候補生成、形状作成用の出力、テンプレート生成、フィット、検査、登録はGUIなしで呼び出せる。チェック系CLIはOK・NGを終了コードで、測定値や問題箇所をJSONで返す。

レビューの候補承認・差し替えはローカルWeb画面（または既存Qt/AIS）で行い、保存したレビューJSONを出力CLIへ渡す。Webサーバーはレビューの状態取得・面計測・レビュー保存のAPIを備える。汎用のカメラ遠隔操作APIやMCPサーバーは用意していない。Python関数は処理の実装に使っており、自動処理の入口は各CLIと成果物ファイルとする。

### レビューの回帰テスト

```powershell
$env:PYTHONPATH = "$PWD\tools;$PWD\templates\profile\workflows"
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_b2_*.py' -v
```

合成形状で平面・円筒のトリム面積、隙間、除外条件、面対応、レビュー修正・保存・復元、未確認ガード、受け渡しを確認する。HTTPテストは一時的なループバックサーバーを起動する。実機CAD・生成物はGit管理外のまま保持する。

## 最初の実装範囲

1. **抽出**。STEPアセンブリ1件から部品と配置を取得し、部品名・配置ID・単位を一覧に出す。対象部品と周辺部品を後続処理へ渡せるようにする。
2. **接合候補とレビュー**。元の配置から、距離・向き・重なりで平面・同軸円筒の接合候補を抽出する。Web（または既存AIS）で両側の面を同色にし、確認・修正した面ペアと期待する隙間をJSONで保存する。
3. **テンプレート作成と検証**。履歴を持つCadQueryテンプレートを試しフィットし、再組み立て時の接合検査と円筒差し引き後の空間検査を経て登録する。

Codexからは作業とチェックを別の呼び出しにし、ファイルで成果物を渡す。人による確認はWeb画面またはAISで行い、保存した結果を後続工程で読む。最初の入力はSTEPとし、Parasolid直接入力は親の仕様にある検証項目として扱う。

[CadQueryのインストール資料](https://cadquery.readthedocs.io/en/stable/installation.html) · [OCPの配布ファイル](https://pypi.org/project/cadquery-ocp/#files) · [OCCT AISの可視化ガイド](https://occt3d.com/dev/doc/overview/html/occt_user_guides__visualization.html)

## ACPでPythonから役割エージェントを呼ぶ

簡略形状の作成では不要な面・エッジ・フィーチャーを減らす。保持面の領域、接合、開口、指定された体積許容差を制約とする。保持面を延長してつなぎ、その幾何に必要な勾配を付ける。段差を残す場合は満たすべき制約と根拠を示す。作成担当は提出前に、同じ方法で数えた詳細・簡略形状の面数とエッジ数、および同じ視点と必要な断面で確認した所見を記録する。チェッカーは数と外観の所見を独立に確認し、確認できなかった項目を報告する。

`b3_acp.py` はACP v1のJSON-RPC/UTF-8 NDJSON stdioで役割を呼び分ける。Kiro CLIの `kiro-cli acp` など、明示した実行ファイル引数配列を設定する。各呼出しは独立プロセス・セッションで、進行役→担当→チェッカー→進行役の順に1部品を処理する。担当が構造化JSONの寸法プランを返し、Python側が単一機能の作成・検査CLI相当の処理を呼ぶ。チェッカーの文章判断で機械検査NGや要レビューを合格へ上書きしない。

設定JSONはschema_version=1、rolesのcoordinator/worker/checkerそれぞれに `argv: [実行ファイルの絶対パス, 引数...]` を持つ。任意の `model` はプロバイダーがsession/newで公開したIDだけを指定できる。シェル文字列や任意コマンドの自動許可は使わない。設定・認証・実CADの実行記録はGit管理外に置く。

```powershell
# 接続だけ検査（CADやタスクのプロンプトは送らない）
& .\.venv\Scripts\python.exe .\tools\b3_acp.py --probe .\b1-output\provider.json
# 元レビューと設定を検証するだけ。エージェントは起動しない
& .\.venv\Scripts\python.exe .\tools\b3_acp.py .\b1-output\b3-workflow\task.json .\b1-output\provider.json .\b1-output\acp-run
# 実際の役割呼出しと形状作成・検査
& .\.venv\Scripts\python.exe .\tools\b3_acp.py .\b1-output\b3-workflow\task.json .\b1-output\provider.json .\b1-output\acp-run --run
```

クライアントのファイル・ターミナル機能は広告せず、権限要求はキャンセルして停止・記録する。プロバイダー自身のツール制限は別設定であり、プロンプトや別セッションはOSサンドボックスを代替しない。最終進行役の後にも元レビューと成果物の改変を検査する。実行記録・モデルID・検査結果を保持し、タイムアウト／取消／不正応答／認証失敗を成功に見せない。プロトコル根拠：[ACP v1](https://agentclientprotocol.com/protocol/v1/transports)、[Kiro ACP](https://kiro.dev/docs/cli/acp/)。

## FHなどの試行と登録候補

元レビューを変更せず、ユーザーから試行を委任された判断は別ファイルに `review_mode: provisional_trial` として記録する。これは人の最終承認ではない。Webレビューは `?part=配置ID` で対象部品へ絞れ、未承認の簡略化案を読取専用でプレビューできる。円錐・トーラスをC/R候補とする案は、小面しきい値による既存提案とは別のヒューリスティックで、形状意図を確定しない。`b2_propose_part.py bundle candidates review part_id output` で提案だけを新規保存できる。

`b3_fh_build.py task dimensions output` は寸法付きFH試行テンプレートを新規生成する。実機寸法の既定値はコードに埋め込まない。長穴・穴・リング・ボス・ポケットを履歴付きで組み、C/Rは作成しない。特殊テンプレートの独立プラン再生は未対応として作成結果の検査で要確認にする。

- `b4_check_rebuild.py task artifact report --max-error-mm3 値`：保持面を含むフィット成立／到達度と、追加・減少空間の適合を分ける。非ゼロ差で最適フィット済みとは断定しない。
- `b5_check_rebuild.py task artifact report`：元の絶対座標で平面・円筒の接合と全部品との食い込みを確認する。
- `b5_build_rebuild_space.py task artifact config output`：明示した円筒内で詳細・再組立後の空間、増加・減少空間、成分数、微小面・辺を出力する。差分体積の保存則も照合し、不整合な生の差分値は信頼できる判定値に使わない。領域・外側埋め・漏れの期待値が未定義なら要レビューを残す。
- `b6_create_candidate.py task artifact output --b3-report ... --b4-report ... --contact-report ... --space-report ... --space ...`：全証拠を束ねる登録候補。NGも隠さず保持し、`registered: false`、人の最終承認待ちとして保存する。既存の正式登録CLIの合格条件を緩めない。

試行用の閾値と承認待ちはレポートに記録する。独立検査や空間検証がNGでも調査・比較用の成果物は作れるが、正式登録や本番解析への合格を意味しない。

### Role definitions and shared skills

The role definitions live in `local/profile/agents/<role>/AGENT.md`. Each `Skill: name` line
loads `skills/<name>/SKILL.md` from the shared store. assignment files and ACP prompts use the same loader.
The independent-check skill belongs to the checker.

To load the independent checker's instructions, run
`.venv/Scripts/python.exe agent_roles.py b4-checker` from this directory and
pass the output with the task and artifact paths. The numerical CLI
`b4_check_rebuild.py` uses the three measurement methods in order and the 5% criterion by default.
An explicit --max-error-mm3 retains the legacy direct-only mode. The checker
reviews the recorded measurement and makes a separate visual judgment.
