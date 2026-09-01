# teruo — デモ動画 台本(撮影用メモ・提出物ではない)

想定尺: **編集後で3分30秒〜4分**(Devpost の上限は5分。3分にはこだわらない)。
シーン1〜6が本編、7は尺が余れば。

teruo の返答は Bedrock 経由なので毎回同じ文言にはならない。
台本の「見せたいこと」が画面に出ていればOK、出なければ撮り直す。

**CLI は全編英語**（プロンプト・ツール出力とも英語化済み）。入力も英語で打つ。
審査員はそのまま画面を読めるので、字幕が必要なのはナレーションを日本語で
録る場合だけ。英語ナレーションで録るなら字幕は不要になり編集が大幅に軽くなる。
どちらにするかは録音テストしてから決める。

## 編集方針(収録前に必ず読む)

コマンドは8本。Bedrock 経由の応答はツール呼び出し込みで1本5〜15秒かかるため、
**素材は編集後尺の倍以上回る前提**。以下で吸収する。

- **待ち時間はジャンプカットで切る。** 出力そのものは加工しない(捏造しなければ切るのは問題ない)
- **コマンドは打鍵せず、このファイルからコピペして貼り付ける。** 打鍵は映さない
- 各シーンの秒数はすべて**編集後の尺**
- ナレーションを日本語で録る場合のみ、英語字幕を全編に焼き込む
  （CLI 出力は英語なので、字幕はナレーションの訳だけでよい）

## 撮影前の準備

- **ターミナルのフォントを普段の1.5〜2倍に上げる。** 720p に落ちた時点で
  デフォルトサイズの等幅フォントは読めない。録画前に必ず確認
- state のスナップショットを取る:

```bash
# 撮影前に1回だけ
cp data/state.json data/state.original.json

# 各テイクの直前に毎回(シーン3のテイクはここから始める)
cp data/state.original.json data/state.json

python main.py
```

- **AWS キーは Replit Secrets に置く**（env に自動注入されるので、収録画面で export しない）。
  やむを得ずシェルで設定する場合は認証を別ウィンドウで済ませるか、収録用ウィンドウで
  `clear && printf '\033[3J'` を打ってスクロールバックごと消してから録画を始める。
  録画開始前に打っていても、スクロールバックを遡ると出る・history に残る・
  縦長ターミナルだと前の行が見えている。**収録ウィンドウでは一度もキーに触れないのが確実**
- ウィンドウ切り替えで他のファイル名・通知が写り込まないか確認
  （シーン2で architecture.svg を開く時の Finder・デスクトップ・ブラウザのタブも含む）

- **テイクを重ねると state が汚れる**ので、シーン単位でもスナップショットを分ける:

```bash
cp data/state.json data/state.after3.json   # シーン3がOKテイクで終わった直後
cp data/state.after3.json data/state.json   # シーン4の各テイクの直前に毎回
cp data/state.json data/state.after4.json   # シーン4がOKテイクで終わった直後
cp data/state.after4.json data/state.json   # シーン5の各テイクの直前に毎回
```

- カウンセリングも撮る場合は `INVENTORY_STATE_PATH=/tmp/demo-fresh.json python main.py`
  で空の状態から起動する(本体の state.json を汚さない)
- 実在の業者名を口にしない・映さない。仕入れ先は「A商店」(設計書10章)
- ライスボックスの肉110g等は仮置きの値。映すなら「仮の値」と一言添える

## シーン構成

### 1. つかみ(25秒・スライドか口頭)

冒頭の一言(技術の話より先。ここが impact と originality の根拠):

- "I ran a food truck for 6.5 years. Inventory never matched the books — I saw it every day."
- "Meat portions vary by who holds the tongs. Sauce isn't counted in grams — the real unit is 'servings per bottle.'"
- "So teruo splits consumption logic into 3 types."

（日本語ナレーションの場合の原稿:
「キッチンカーを6年半やっていました。在庫が帳簿どおりに減らないのを、毎日見ていました。
トングで盛る肉は人によって量が違う。しかもソースは g で数えない。
1本で何食もつか、が現場の数え方」→ teruo は係数ロジックを3系統に分けた、と宣言してデモへ）

### 2. アーキテクチャ図(10秒・静止画)

[architecture.svg](architecture.svg) を5秒以上映す(提出物の図をそのまま流用)。
見せたいこと: **これはスクリプトではなくエージェント。** Strands Agents SDK と
Amazon Bedrock の名前が画面に出ている状態で一言:

- "An agent, not a script — built on Strands Agents SDK + Amazon Bedrock."
- "Python does all the math. The AI only decides and explains."

### 3. 売上とユニット型の学習(90秒・本編の山)

```
> Sold 30 kebab sandwiches
> Just opened the sauce bottle we're using now
（売上を数回はさむ: Sold 20 kebab sandwiches など。編集で1〜2回分だけ残す）
> The sauce bottle is empty. Opened the next one
```

見せたいこと:
- 最初の売上の応答自体が明細になっていて、**減った品目と動かないソースが1画面に並ぶ**:

```
Recorded Kebab sandwich × 30.
- Kebab meat (chicken): 8500 → 6250g (down 2250g)
- Pita bread: 200 → 170 pcs (down 30 pcs)
- Yogurt sauce: stock unchanged (running total 30 servings)
- Wrap paper: 500 → 470 pcs (down 30 pcs)
- Napkin: 1000 → 970 pcs (down 30 pcs)
```

  ※ 明細は LLM を通さず **Python が直接印字する**（原則3「計算は Python、判断は AI」が
  そのまま画に出る）。毎テイク同じ形で必ず出るので、要約で消える心配はない。
  teruo の一言（"chicken has about 2 days left" 等）が明細の後に続く
- （任意・補強）"Show me the stock" で品目ごとの表示の違いを映す:
  チキンは "coefficient 1.00, learning (0/5 stock counts)"、ピタは "coefficient fixed"、
  ソースは "unlearned (waiting for the first empty unit)"
- 使い切りの瞬間に "50 servings from that bottle → ≈50 servings per bottle.
  3 bottles left (about 150 servings left)" が出る
- ナレーション: "No one can measure a half-used bottle. teruo learns only from
  the moment it runs empty."

### 4. 棚卸しと係数の上限(45秒)

```
> Counted the chicken: 6.1kg
```

見せたいこと: 係数が実測から更新される。
続けて、わざと大きくズレた実測を入れる:

```
> Chicken is down to just 4kg
```

→ "The coefficient has hit the cap of what portioning variance can explain
(recipe value ±4g/serving). I won't adjust it any further on my own." が出る。
ナレーション: "This closes the loophole: you can't train the coefficient by
under-reporting stock counts."

### 5. 月次突合(30秒)

シーン5だけ、1ヶ月分のシードデータで別起動する。
**state の切り替えは隠さず明言する**（3秒。不連続を編集で誤魔化さない。
シードが再現可能なことの説明にもなり、むしろ加点）:

ナレーション/字幕: "That was day one. Now switching to a state seeded with
one month of operation."

撮影直前に生成:

```bash
python scripts/seed_demo.py
INVENTORY_STATE_PATH=data/state.demo-month.json python main.py
```

```
> Reconcile August
```

（シードは実行日の「先月」1ヶ月分を作る。9月に撮るなら8月。
生成スクリプトの最後に突合結果がそのまま印字されるので、映る数字は事前に分かる）

見せたいこと: 仕入れ・レシピ理論消費・実測の差が食数つきで出る。
シードには盛りブレ+3%と未記録消費1.5kg×4回が埋め込んであり、画面には
"The gap vs. the physical count, 9,643g (short), is more than portioning
variance can explain (±4g/serving = 6,048g)" が出る。
月中の棚卸しでは "hit the cap" の警告が出るだけで総量は分からない——
月次で仕入れと突き合わせて初めて数字になる、という筋。ピタの紛失2枚も同じ表に出る。

（任意・5秒）"How do sales differ by venue?" → get_sales_summary がイベント / 単独を
分けて平均を出す。シードは土日を event で記録しているので実データが割れて出る。
業種テンプレではなく原則7がデータに入っている証拠として一瞬映す価値あり。

ナレーション:
- "Small skims hide inside daily thresholds. A month can't hide them:
  9.6 kg gap, only 6 kg explainable by portioning."
- "teruo never points at a person. It states facts and abnormal ranges only."

### 6. 締め(20秒)

- "teruo doesn't record who typed. Honest numbers never come from a system
  that punishes the person entering them."
- "Python calculates. AI decides. It only teaches."

最後のカットに GitHub の URL を必ず出す(スライドで静止5秒):
**https://github.com/handraisebyfifteen/teruo**

### 7. (尺が余れば)初回カウンセリング

空の状態で起動し、段階5の "When you use it, what do you count as one?" まで見せる。
同じ玉ねぎでも「1個ずつ」なら unit、「刻んで量る」なら weight になる分岐が
言葉ひとつで決まるところが画になる。上限5分まで余裕があれば入れる。

## 撮影後

```bash
cp data/state.original.json data/state.json
rm data/state.original.json data/state.after*.json
rm -f data/state.demo-month.json   # 再生成できる（scripts/seed_demo.py）
```
