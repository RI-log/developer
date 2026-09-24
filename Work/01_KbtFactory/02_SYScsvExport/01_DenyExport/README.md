# 優先度低で手動実行

/data配下にある.logと同じストレージを使用することによるI/O競合が考えられるため、
以下のコマンドを実行して優先度を下げて実行することで安全に処理することができる。

スクリプト格納場所：
/data/archive/00_script/01_DenyExport/01_manual

対象スクリプト：
DenyExport.py

ログ出力場所：
/data/archive/01_csv/01_DenyExport

## 実行コマンド

低優先度で実行
```bash
nice -n 15 ionice -c 3 python3 DenyExport.py
```
※ファイルサイズが大きいため完了までに1時間程度かかります

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

# cronで定期実行

cronはWindowsで例えるとLinux版タスクスケジューラです。
cronで定期実行設定をすれば毎朝6時に実行されるので処理待ちがなくなります。
以下のコマンドで登録すれば定期実行で異常があった際はDenyExport.logに記録されます。

スクリプト格納場所：
/data/archive/00_script/01_DenyExport/02_cron

対象スクリプト：
DenyExportCron.cron

ログ出力場所：
/data/archive/01_csv/01_DenyExport

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
```

cron登録を解除する場合は以下のコマンドで解除できる。

cron登録解除
```bash
crontab -l | grep -vF '/data/archive/00_script/01_DenyExport/02_cron/DenyExportCron.py' | crontab -
```
