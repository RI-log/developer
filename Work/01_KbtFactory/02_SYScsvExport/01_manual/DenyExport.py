#!/usr/bin/env python3

import csv
import gzip
import os
import re
import sys
from datetime import datetime


# ==============================
# 編集
# ==============================

# 解析対象日付 "yyyymmdd"
TARGET_DATE = input(
    "対象日付を入力してください(yyyymmdd) > "
).strip()

# FortiGate情報
FGT_IP = "x.x.x.x"

# Syslog保存先ディレクトリ指定
ARCHIVE_DIR = "/data/archive"

# 出力先
SAVE_DIR = "/data/archive/01_csv/01_DenyExport"

# 除外ポリシー番号
EXCLUDE_POLICY_IDS = {"0", "8", "201"}

# gzipログ文字コード
LOG_ENCODING = "utf-8"

# 出力CSV文字コード ※utf-8-sig推奨
CSV_ENCODING = "utf-8-sig"


# ==============================
# ログ取得処理 ※編集禁止
# ==============================

# 正規表現
FIELD_PATTERN = re.compile(
    r'([A-Za-z0-9_.-]+)='
    r'("(?:\\.|[^"\\])*"|[^,\s]+)'
)


# CSV出力項目
CSV_FIELDS = [
    "date",
    "time",
    # "eventtime",
    # "tz",
    # "logid",
    # "type",
    "subtype",
    # "level",
    # "vd",
    "srcip",
    "srcname",
    "srcport",
    "srcintf",
    # "srcintfrole",
    "dstip",
    "dstport",
    "dstintf",
    # "dstintfrole",
    # "srccountry",
    # "dstcountry",
    # "sessionid",
    # "proto",
    "action",
    "policyid",
    # "policytype",
    # "poluuid",
    "service",
    # "trandisp",
    # "appcat",
    # "duration",
    "sentbyte",
    "rcvdbyte",
    "sentpkt",
    "rcvdpkt",
    # "sentdelta",
    # "rcvddelta",
    # "durationdelta",
    # "sentpktdelta",
    # "rcvdpktdelta",
    # "devtype",
    # "osname",
    # "srcswversion",
    # "unauthuser",
    # "unauthusersource",
    # "mastersrcmac",
    "srcmac",
    # "srcserver",
    # "dsthwvendor",
    # "dstdevtype",
    # "dstosname",
    # "dstswversion",
    # "dstunauthuser",
    # "dstunauthusersource",
    # "masterdstmac",
    "dstmac",
    # "dstserver",
]


# TARGET_DATE確認
def validate_target_date(target_date):

    try:
        datetime.strptime(target_date, "%Y%m%d")

    except ValueError as error:
        raise ValueError(
            "TARGET_DATEは実在する日付を"
            "yyyymmdd形式で指定してください。"
            f"現在の設定値: {target_date}"
        ) from error


# gzipファイルパス作成
def build_input_path(target_date):

    # yyyymmdd形式から日付オブジェクトへ変換
    target_datetime = datetime.strptime(
        target_date,
        "%Y%m%d",
    )

    # ディレクトリ名 yyyy-mm-dd形式
    directory_date = target_datetime.strftime("%Y-%m-%d")

    # ファイル名 日付部分 yyyymmdd形式
    file_name = f"{FGT_IP}.log-{target_date}.gz"

    input_path = os.path.join(
        ARCHIVE_DIR,
        directory_date,
        file_name,
    )

    return input_path


# CSVファイル名作成
def build_output_path(target_date):

    execution_datetime = datetime.now().strftime("%Y%m%d%H%M%S")

    output_file_name = (
        f"deny_logs_{target_date}_{execution_datetime}.csv"
    )

    return os.path.join(SAVE_DIR, output_file_name)


# ダブルクォート除去
def remove_quotes(value):

    if value is None:
        return ""

    value = value.strip()

    if (
        len(value) >= 2
        and value[0] == '"'
        and value[-1] == '"'
    ):
        # 前後のダブルクォートを除去
        value = value[1:-1]

        # ログ内でエスケープされた文字を戻す
        value = value.replace(r"\"", '"')
        value = value.replace(r"\\", "\\")

    return value


# key=value抽出
def parse_fortigate_log(line):

    fields = {}

    for match in FIELD_PATTERN.finditer(line):
        key = match.group(1)
        value = remove_quotes(match.group(2))

        fields[key] = value

    return fields


# 値の表記確認
def has_deny_action(line):

    lower_line = line.lower()

    return (
        "action=deny" in lower_line
        or 'action="deny"' in lower_line
    )


# deny一致確認(大文字と小文字の区別なし)
def is_deny_log(fields):

    action = fields.get("action", "")

    return action.strip().lower() == "deny"


# deny抽出
def extract_deny_logs(input_gzip, output_csv):

    processed_lines = 0
    deny_count = 0
    excluded_count = 0

    # 出力先ディレクトリ取得
    output_parent = os.path.dirname(output_csv)

    # 出力先ディレクトリが存在しない場合に作成処理
    os.makedirs(output_parent, exist_ok=True)

    # CSVファイル作成
    with open(
        output_csv,
        mode="w",
        encoding=CSV_ENCODING,
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
            extrasaction="ignore",
        )

        # 項目名出力
        writer.writeheader()

        # gzipテキストモード展開(解凍なし)
        with gzip.open(
            input_gzip,
            mode="rt",
            encoding=LOG_ENCODING,
            errors="replace",
        ) as log_file:

            # gzip内のログを1行ずつ処理
            for line in log_file:
                processed_lines += 1

                if not has_deny_action(line):
                    continue

                # key=value形式解析
                fields = parse_fortigate_log(line)

                # deny一致再確認
                if not is_deny_log(fields):
                    continue

                # 指定したポリシー番号を除外
                if fields.get("policyid", "") in EXCLUDE_POLICY_IDS:
                    excluded_count += 1
                    continue

                deny_count += 1

                csv_row = {
                    field_name: fields.get(field_name, "")
                    for field_name in CSV_FIELDS
                }

                writer.writerow(csv_row)

    print("")
    print("処理が完了しました。")
    print(f"対象日付       : {TARGET_DATE}")
    print(f"入力gzip       : {input_gzip}")
    print(f"処理ログ行数   : {processed_lines:,}")
    print(f"ポリシー除外件数: {excluded_count:,}")
    print(f"deny出力件数   : {deny_count:,}")
    print(f"出力CSV        : {os.path.abspath(output_csv)}")


# メイン処理
def main():

    try:
        # TARGET_DATE確認
        validate_target_date(TARGET_DATE)

        input_gzip = build_input_path(TARGET_DATE)
        output_csv = build_output_path(TARGET_DATE)

        print("FortiGate denyログ抽出処理")
        print("=" * 60)
        print(f"対象日付       : {TARGET_DATE}")
        print(f"除外ポリシー   : {', '.join(sorted(EXCLUDE_POLICY_IDS))}")
        print(f"入力gzip       : {input_gzip}")
        print(f"出力CSV        : {os.path.abspath(output_csv)}")
        print("")

        # 対象gzipファイル確認
        if not os.path.exists(input_gzip):
            print(
                "[エラー] 対象のgzipファイルが存在しません。",
                file=sys.stderr,
            )
            print(
                f"[確認したパス] {input_gzip}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not os.path.isfile(input_gzip):
            print(
                "[エラー] 対象パスはファイルではありません。",
                file=sys.stderr,
            )
            print(
                f"[対象パス] {input_gzip}",
                file=sys.stderr,
            )
            sys.exit(1)

        # denyログ抽出
        extract_deny_logs(
            input_gzip=input_gzip,
            output_csv=output_csv,
        )

    # エラー処理
    except ValueError as error:
        print(
            f"[設定エラー] {error}",
            file=sys.stderr,
        )
        sys.exit(1)

    except PermissionError as error:
        print(
            "[権限エラー] gzipファイルの読み取り、または"
            "CSVファイルの書き込み権限がありません。",
            file=sys.stderr,
        )
        print(
            f"[詳細] {error}",
            file=sys.stderr,
        )
        sys.exit(2)

    except gzip.BadGzipFile as error:
        print(
            "[gzipエラー] 対象ファイルが"
            "正常なgzip形式ではありません。",
            file=sys.stderr,
        )
        print(
            f"[詳細] {error}",
            file=sys.stderr,
        )
        sys.exit(3)

    except EOFError as error:
        print(
            "[gzipエラー] gzipファイルが途中で終了しています。"
            "ファイルが破損している可能性があります。",
            file=sys.stderr,
        )
        print(
            f"[詳細] {error}",
            file=sys.stderr,
        )
        sys.exit(3)

    except OSError as error:
        print(
            f"[ファイルエラー] {error}",
            file=sys.stderr,
        )
        sys.exit(4)

    except KeyboardInterrupt:
        print(
            "\nユーザー操作によって処理を中断しました。",
            file=sys.stderr,
        )
        sys.exit(130)


if __name__ == "__main__":
    main()
