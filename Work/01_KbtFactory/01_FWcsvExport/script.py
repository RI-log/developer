import requests
import csv
import datetime
import os
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
# 編集
# ==============================
# FortiGate情報
FGT_IP = "x.x.x.x"
API_TOKEN = "none"

# FortiGateログ保存先
# 検証機: memory
# 本番機: disk
LOG_DEVICE = "none"

# 保存先ディレクトリ指定
save_dir = r"none"

# 取得するログ件数 (MAX:5000)
LOG_ROWS = 5000

# 最大検索範囲 (分)
MAX_SEARCH_MINUTES = 60

# 日時フィルタ
USE_DATETIME_FILTER = True  # True or False

# 取得対象日時 "yyyy-mm-dd hh:mm"
START_DATETIME = "yyyy-mm-dd hh:mm"
END_DATETIME = "yyyy-mm-dd hh:mm"

# IPアドレスフィルタ
USE_IP_FILTER = False  # True or False

# 送信元IP
USE_SRCIP_FILTER = False  # True or False
SRC_IP = "x.x.x.x"

# 宛先IP
USE_DSTIP_FILTER = False  # True or False
DST_IP = "x.x.x.x"

# 取得対象ポリシーID指定
# ポリシーログ取得(個別)
GET_SINGLE_POLICY = True  # True or False
SINGLE_POLICY_ID = None

# ポリシーログ取得(範囲)
GET_POLICY_RANGE = False  # True or False
RANGE_START_POLICY_ID = None
RANGE_END_POLICY_ID = None

# CSV出力項目
required_fields = [
    "date",            # 日付
    "time",            # 時刻
    "srcip",           # 送信元
    "dstip",           # 宛先
    "policyid",        # ポリシーID
    "service",         # サービス
    "action",          # アクション
    "proto",           # プロトコル
    "dstport",         # 宛先ポート
    "dstmac"           # 宛先MAC
]

# ==============================
# ログ取得処理 ※編集禁止※
# ==============================

headers = {"Authorization": f"Bearer {API_TOKEN}"}

end_time = datetime.datetime.now()
timestamp_str = end_time.strftime("%Y%m%d%H%M%S")

# 再確認設定
RETRY_INTERVAL = 5
MAX_RETRY_COUNT = 12

# 取得件数上限
if LOG_ROWS < 1 or LOG_ROWS > 5000:
    raise ValueError(
        "LOG_ROWS は1以上5000以下で指定してください。"
    )

# 日時フィルタ
if USE_DATETIME_FILTER:
    try:
        jst = datetime.timezone(datetime.timedelta(hours=9))

        start_datetime = datetime.datetime.strptime(
            START_DATETIME,
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=jst)

        end_datetime = datetime.datetime.strptime(
            END_DATETIME,
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=jst)

    except ValueError:
        raise ValueError(
            "START_DATETIME と END_DATETIME は、"
            "\"yyyy-mm-dd hh:mm\" の形式で入力してください。"
        )

    if start_datetime > end_datetime:
        raise ValueError(
            "START_DATETIME は END_DATETIME 以前の日時を指定してください。"
        )

    # END_DATETIME+1分間
    end_datetime = end_datetime + datetime.timedelta(minutes=1)

    # 最大検索範囲
    search_minutes = (
        end_datetime - start_datetime
    ).total_seconds() / 60

    if search_minutes > MAX_SEARCH_MINUTES:
        raise ValueError(
            f"検索範囲は最大{MAX_SEARCH_MINUTES}分までです。"
        )

    start_timestamp_ms = int(start_datetime.timestamp() * 1000)
    end_timestamp_ms = int(end_datetime.timestamp() * 1000)

# IPアドレスフィルタ
if USE_IP_FILTER:
    if not USE_SRCIP_FILTER and not USE_DSTIP_FILTER:
        raise ValueError(
            "USE_IP_FILTER が True の場合は、"
            "USE_SRCIP_FILTER または USE_DSTIP_FILTER を True にしてください。"
        )

    if USE_SRCIP_FILTER and SRC_IP in ("", "x.x.x.x"):
        raise ValueError(
            "SRC_IP を入力してください。"
        )

    if USE_DSTIP_FILTER and DST_IP in ("", "x.x.x.x"):
        raise ValueError(
            "DST_IP を入力してください。"
        )

# ディレクトリ作成
os.makedirs(save_dir, exist_ok=True)

# ポリシーID取得
if GET_SINGLE_POLICY and not GET_POLICY_RANGE:
    policy_ids = [SINGLE_POLICY_ID]
elif GET_POLICY_RANGE and not GET_SINGLE_POLICY:
    policy_ids = range(RANGE_START_POLICY_ID, RANGE_END_POLICY_ID + 1)
else:
    raise ValueError(
        "GET_SINGLE_POLICY と GET_POLICY_RANGE は、どちらか一方だけ True にしてください。"
    )

# ログ取得処理
for policy_id in policy_ids:
    url = f"https://{FGT_IP}/api/v2/log/{LOG_DEVICE}/traffic/forward"

    params = [
        ("filter", f"policyid=={policy_id}"),
        ("rows", str(LOG_ROWS))
    ]

    if USE_DATETIME_FILTER:
        params.extend([
            ("filter", f"_metadata.timestamp>={start_timestamp_ms}"),
            ("filter", f"_metadata.timestamp<{end_timestamp_ms}")
        ])

    if USE_IP_FILTER:
        if USE_SRCIP_FILTER:
            params.append(("filter", f"srcip=={SRC_IP}"))
        if USE_DSTIP_FILTER:
            params.append(("filter", f"dstip=={DST_IP}"))

    response = requests.get(
        url,
        headers=headers,
        params=params,
        verify=False
    )

    if response.status_code == 200:
        data = response.json()

        # 再確認
        retry_count = 0

        while not data.get("ready", False) and retry_count < MAX_RETRY_COUNT:
            session_id = data.get("session_id")

            if session_id is None:
                break

            retry_count += 1

            print(
                f"ポリシーID {policy_id} のログを検索中です。"
                f"再確認 {retry_count}/{MAX_RETRY_COUNT}"
            )

            time.sleep(RETRY_INTERVAL)

            retry_params = params + [
                ("session_id", str(session_id))
            ]

            response = requests.get(
                url,
                headers=headers,
                params=retry_params,
                verify=False
            )

            if response.status_code != 200:
                break

            data = response.json()

        if response.status_code != 200:
            print(
                f"Error for policy {policy_id}: {response.status_code}"
            )
            print(
                response.text
            )
            continue

        logs = data.get("results", [])

        print(
            f"ready={data.get('ready')}, "
            f"percent={data.get('percent_logs_processed')}, "
            f"取得件数={len(logs)}"
        )

        # エラー処理
        if not data.get("ready", False):
            print(
                f"ポリシーID {policy_id} のログ検索は"
                f"{RETRY_INTERVAL * MAX_RETRY_COUNT}秒以内に完了しませんでした。"
            )
            print(
                "時間範囲または取得件数を小さくして再実行してください。"
            )
            continue

        if logs:
            filename = os.path.join(save_dir, f"policy_logs_{policy_id}_{timestamp_str}.csv")

            with open(filename, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=required_fields)
                writer.writeheader()

                for entry in logs:
                    filtered_entry = {key: entry.get(key, "") for key in required_fields}
                    writer.writerow(filtered_entry)

            print(
                f"ポリシーID {policy_id} のログを {filename} に保存しました。"
            )
        else:
            print(
                f"ポリシーID {policy_id} のログはありませんでした。"
            )

    else:
        print(
            f"Error for policy {policy_id}: {response.status_code}"
        )
        print(
            response.text
        )
