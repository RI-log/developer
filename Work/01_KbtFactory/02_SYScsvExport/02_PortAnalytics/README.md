# 優先度低で手動実行

/data配下にある.logと同じストレージを使用することによるI/O競合が考えられるため、
以下のコマンドを実行して優先度を下げて実行することで安全に処理することができる。
また、実行完了に30時間以上かかると予想されるため、
screenを使ったバックグラウンド実行を推奨。

スクリプト格納場所：
/data/archive/00_script/02_PortAnalytics

対象スクリプト：
PortAnalytics.py

ログ出力場所：
/data/archive/01_csv/02_PortAnalytics

## 実行コマンド

バックグラウンドで低優先度実行
```bash
screen -S FW-PortAnalytics
nice -n 15 ionice -c 3 python3 PortAnalytics.py
```

実行後、以下の手順でデタッチする。
ctrl + A → D

実行中かどうかは以下のコマンドで確認できる。
```bash
screen -r FW-PortAnalytics
```

### 詳細

コマンドの意味は以下の通りです。

nice   : CPU処理の優先度
ionice : ディスクI/O処理の優先度


nice -n 15

-20 : 最優先
0   : デフォルト
15  : 低優先度
20  : 最低優先度


ionice -c 3

-c 1： Realtime
-c 2： Best-effort
-c 3： Idle
