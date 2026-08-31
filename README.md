# キッチンカー在庫エージェント

ホットドッグの売上からソーセージとパンの在庫を減らし、棚卸し差分から
消費係数を補正する、Tier 1専用の対話型CLIです。

## 必要な環境変数

Replit Secretsへ次を登録してください。値をコードや`.env`へ書かないでください。

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

通常の環境変数:

- `AWS_DEFAULT_REGION=us-west-2`

## 起動

```bash
python main.py
```

終了するには `exit` または `quit` と入力します。

## ファイル

- `main.py`: Strandsエージェントと対話ループ
- `tools.py`: `record_sales`、`record_count`、`get_stock_status`
- `store.py`: `data/state.json`の読み書き
- `data/state.json`: 在庫、レシピ、履歴