# 手動実行

/data配下にある.logと同じストレージを使用することによるI/O競合が考えられるため、
以下のコマンドを実行して優先度を下げて実行することで安全に処理することができる。

スクリプト格納場所：
/data/archive/00_script/01_DenyExport/01_manual

対象スクリプト：
DenyExport.py

ログ出力場所：
/data/archive/01_csv/01_DenyExport/deny_logs_*.csv

## 実行コマンド

低優先度で実行
```bash
nice -n 15 ionice -c 3 python3 DenyExport.py
```
※ファイルサイズが大きいため完了までに1時間程度かかります

### 解説

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

-----------------------------------------
# cron 定期実行

cronはWindowsで例えるとLinux版タスクスケジューラです。
cronで定期実行設定をすれば毎朝6時に実行されるので処理待ちがなくなります。
以下のコマンドで登録すれば定期実行で異常があった際はDenyExport.logに記録されます。

スクリプト格納場所：
/data/archive/00_script/01_DenyExport/02_cron

対象スクリプト：
DenyExportCron.cron

ログ出力場所：
/data/archive/01_csv/01_DenyExport/DenyExport.log
/data/archive/01_csv/01_DenyExport/deny_logs_*.log

## cron登録コマンド

cron登録
```bash
crontab /data/archive/00_script/01_DenyExport/02_cron/DenyExportCron.cron
```

登録確認
```bash
crontab -l
```

以下がcronファイルの設定内容以下になります。
DenyExportCron.cron
```bash
0 6 * * * /usr/bin/nice -n 15 /usr/bin/ionice -c 3 /usr/bin/python3 /data/archive/00_script/01_DenyExport/02_cron/DenyExportCron.py >> /data/archive/01_csv/01_DenyExport/DenyExport.log 2>&1

0 7 * * * /usr/bin/find /data/archive/01_csv/01_DenyExport -maxdepth 1 -type f -name 'deny_logs_*.csv' -mtime +729 -print -delete >> /data/archive/01_csv/01_DenyExport/DenyExportDelFiles.log 2>&1

```

## cron登録解除

DenyExportCron.cronで削除したい内容を削除して再度以下のコマンドを実行するだけで
cron登録内容が上書きされる。

cron登録解除
```bash
crontab /data/archive/00_script/01_DenyExport/02_cron/DenyExportCron.cron
```

cron登録全削除
```bash
crontab -r
```

### 解説

コマンドの意味：
・DenyExportCron.cron
0 6 * * *
分 時 日 月 曜日
↓
左から分,時,日,月,曜日の意味で、
" * "は全てという意味になります。
設定の値は以下となります。

```bash
分      : 0～59
時      : 0～23
日      : 1～31
月      : 1～12
曜日    : 0～7

0       : 日曜日
1       : 月曜日
2       : 火曜日
3       : 水曜日
4       : 木曜日
5       : 金曜日
6       : 土曜日
7       : 日曜日
```

```bash
" >> "   : 追記
" 2>&1 " : エラーと標準出力が対象
```

```bash
" -maxdepth 1 "            : 配下のサブディレクトリを検索しない
" -type f "                : 通常ファイルだけを対象にする
" -name 'deny_logs_*.csv' ": denyログCSVを対象
" -mtime +364 "            : 更新日時から丸365日以上経過
" -print "                 : 対象を表示
```
 
