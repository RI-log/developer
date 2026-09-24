#!/usr/bin/env python3

import csv
import gzip
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==============================
# 編集
# ==============================

# FortiGate情報
FGT_IP = "x.x.x.x"
API_TOKEN = "none"
VDOM = "root"

# Syslog保存先ディレクトリ指定
ARCHIVE_DIR = "none"

# 出力先
SAVE_DIR = "none"

# 解析対象日付 "yyyymmdd"
START_DATE = input(
    "開始日付を入力してください'最大31日'(yyyymmdd) > "
).strip()

END_DATE = input(
    "終了日付を入力してください'最大31日'(yyyymmdd) > "
).strip()

# 最大検索範囲 (日)
MAX_SEARCH_DAYS = 31

# 除外ポリシー番号
EXCLUDE_POLICY_IDS = {"0", "8", "201"}

# 使用中とみなすtrafficログのaction
USED_ACTIONS = {
    "accept",
    "close",
    "timeout",
}

# 全ポート許可とみなすサービス名
WILDCARD_SERVICE_NAMES = {
    "ALL",
    "ALL_TCP",
    "ALL_UDP",
    "ALL_ICMP",
}

# gzipログ文字コード
LOG_ENCODING = "utf-8"

# 出力CSV文字コード ※utf-8-sig推奨
CSV_ENCODING = "utf-8-sig"

# APIタイムアウト (秒)
API_TIMEOUT = 60


# ==============================
# ログ取得処理 ※編集禁止
# ==============================

# 正規表現
FIELD_PATTERN = re.compile(
    r'([A-Za-z0-9_.-]+)='
    r'("(?:\\.|[^"\\])*"|[^,\s]+)'
)

# proto番号と名称の対応
PROTO_NAME = {
    "6": "TCP",
    "17": "UDP",
    "1": "ICMP",
    "58": "ICMP6",
    "132": "SCTP",
}

# 全ポート許可
WILDCARD_PORT_RANGE = (1, 65535)


# 日付確認
def validate_date(date_text, field_name):

    try:
        return datetime.strptime(date_text, "%Y%m%d")

    except ValueError as error:
        raise ValueError(
            f"{field_name}は実在する日付を"
            "yyyymmdd形式で指定してください。"
            f"現在の設定値: {date_text}"
        ) from error


# 編集欄の設定確認
def validate_settings():

    if FGT_IP in ("", "x.x.x.x"):
        raise ValueError("FGT_IP を入力してください。")

    if API_TOKEN in ("", "none"):
        raise ValueError("API_TOKEN を入力してください。")


# 対象日付を1日ずつ取り出す
def iter_dates(start_datetime, end_datetime):

    current = start_datetime

    while current <= end_datetime:
        yield current
        current += timedelta(days=1)


# gzipファイルパス作成
def build_input_path(target_datetime):

    # ディレクトリ名 yyyy-mm-dd形式
    directory_date = target_datetime.strftime("%Y-%m-%d")

    # ファイル名 日付部分 yyyymmdd形式
    file_date = target_datetime.strftime("%Y%m%d")
    file_name = f"{FGT_IP}.log-{file_date}.gz"

    return os.path.join(
        ARCHIVE_DIR,
        directory_date,
        file_name,
    )


# CSVファイル名作成
def build_output_paths(start_date, end_date):

    execution_datetime = datetime.now().strftime("%Y%m%d%H%M%S")
    os.makedirs(SAVE_DIR, exist_ok=True)

    suffix = f"{start_date}_{end_date}_{execution_datetime}.csv"

    return {
        "configured": os.path.join(
            SAVE_DIR,
            f"fw_service_configured_{suffix}",
        ),
        "used": os.path.join(
            SAVE_DIR,
            f"fw_service_used_{suffix}",
        ),
        "unused": os.path.join(
            SAVE_DIR,
            f"fw_service_unused_{suffix}",
        ),
    }


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


# proto番号を名称へ変換
def normalize_proto(value):

    if value is None:
        return ""

    text = str(value).strip().upper()

    if text in PROTO_NAME.values():
        return text

    if text in PROTO_NAME:
        return PROTO_NAME[text]

    if text.isdigit():
        return f"IP/{text}"

    return text


# ポート1件を範囲へ変換
def parse_port_token(token):

    token = token.strip()

    if not token:
        return None

    # src:dst形式の場合は宛先ポートだけ使う
    dest = token.split(":")[-1]

    if "-" in dest:
        start_text, end_text = dest.split("-", 1)
        start_port = int(start_text)
        end_port = int(end_text)
    else:
        start_port = int(dest)
        end_port = int(dest)

    if start_port > end_port:
        start_port, end_port = end_port, start_port

    if start_port < 1 or end_port > 65535:
        raise ValueError(
            f"ポート範囲が不正です: {token}"
        )

    return (start_port, end_port)


# ポート範囲文字列を分解
def parse_portrange(portrange_text):

    ranges = []

    if not portrange_text:
        return ranges

    for token in str(portrange_text).split():
        parsed = parse_port_token(token)
        if parsed is not None:
            ranges.append(parsed)

    return ranges


# 連続するポート範囲を結合
def merge_ranges(ranges):

    if not ranges:
        return []

    ordered = sorted(ranges)
    merged = [list(ordered[0])]

    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]

        if start <= last_end + 1:
            merged[-1][1] = max(last_end, end)
        else:
            merged.append([start, end])

    return [(start, end) for start, end in merged]


# 1-65535かどうか確認
def is_wildcard_range(ranges):

    merged = merge_ranges(ranges)

    return merged == [WILDCARD_PORT_RANGE]


# ポート範囲を文字列へ変換
def format_ranges(ranges):

    if not ranges:
        return ""

    texts = []

    for start, end in merge_ranges(ranges):
        if start == end:
            texts.append(str(start))
        else:
            texts.append(f"{start}-{end}")

    return " ".join(texts)


# 設定ポートから使用ポートを除外
def subtract_used_ports(ranges, used_ports):

    unused = []

    for start, end in merge_ranges(ranges):
        cursor = start

        while cursor <= end:
            if cursor in used_ports:
                cursor += 1
                continue

            range_end = cursor

            while range_end <= end and range_end not in used_ports:
                range_end += 1

            unused.append((cursor, range_end - 1))
            cursor = range_end

    return unused


# メンバー名抽出
def member_names(members):

    names = []

    if not members:
        return names

    for member in members:
        if isinstance(member, dict):
            name = member.get("name", "")
        else:
            name = str(member)

        if name:
            names.append(name)

    return names


# FortiGate API取得
def cmdb_get(path):

    url = f"https://{FGT_IP}/api/v2/cmdb/{path}"

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
    }

    params = {
        "vdom": VDOM,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        verify=False,
        timeout=API_TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"FortiGate API取得に失敗しました。"
            f" path={path} status={response.status_code}"
            f" body={response.text[:500]}"
        )

    payload = response.json()

    if payload.get("status") not in (None, "success"):
        raise RuntimeError(
            f"FortiGate APIがエラーを返しました。"
            f" path={path} status={payload.get('status')}"
        )

    results = payload.get("results", [])

    if not isinstance(results, list):
        raise RuntimeError(
            f"FortiGate APIの応答形式が不正です。 path={path}"
        )

    return results


# サービス定義を名前引きできる形へ変換
def build_service_indexes(custom_services, service_groups):

    custom_map = {}
    group_map = {}

    for service in custom_services:
        name = service.get("name", "")
        if name:
            custom_map[name] = service

    for group in service_groups:
        name = group.get("name", "")
        if name:
            group_map[name] = member_names(group.get("member", []))

    return custom_map, group_map


# サービスからprotoとポート範囲を取得
def extract_service_ports(service):

    protocol = str(service.get("protocol", "")).upper()
    entries = []

    tcp_ranges = parse_portrange(service.get("tcp-portrange", ""))
    udp_ranges = parse_portrange(service.get("udp-portrange", ""))
    sctp_ranges = parse_portrange(service.get("sctp-portrange", ""))

    if tcp_ranges:
        entries.append(("TCP", tcp_ranges))

    if udp_ranges:
        entries.append(("UDP", udp_ranges))

    if sctp_ranges:
        entries.append(("SCTP", sctp_ranges))

    if entries:
        return entries

    if protocol in ("ICMP", "ICMP6"):
        return [(protocol, [])]

    protocol_number = service.get("protocol-number")

    if protocol in ("IP",) or protocol_number not in (None, "", 0, "0"):
        proto_name = normalize_proto(protocol_number)
        return [(proto_name or protocol or "IP", [])]

    return []


# サービス名を実ポートへ展開
def resolve_service(service_name, custom_map, group_map, visiting=None):

    if visiting is None:
        visiting = set()

    resolved = []

    if service_name in visiting:
        resolved.append({
            "service_name": service_name,
            "resolved_from": "circular",
            "proto": "",
            "ranges": [],
            "wildcard": False,
            "unresolved": True,
        })
        return resolved

    visiting.add(service_name)

    # ALL系サービス
    if service_name in WILDCARD_SERVICE_NAMES:
        proto = "ANY"

        if service_name == "ALL_TCP":
            proto = "TCP"
        elif service_name == "ALL_UDP":
            proto = "UDP"
        elif service_name == "ALL_SCTP":
            proto = "SCTP"
        elif service_name == "ALL_ICMP":
            proto = "ICMP"

        resolved.append({
            "service_name": service_name,
            "resolved_from": "wildcard",
            "proto": proto,
            "ranges": [WILDCARD_PORT_RANGE] if proto not in ("ICMP",) else [],
            "wildcard": True,
            "unresolved": False,
        })
        visiting.remove(service_name)
        return resolved

    # サービスグループはメンバーを再展開
    if service_name in group_map:
        for member_name in group_map[service_name]:
            resolved.extend(
                resolve_service(
                    member_name,
                    custom_map,
                    group_map,
                    visiting,
                )
            )

        visiting.remove(service_name)
        return resolved

    # 個別サービス
    if service_name in custom_map:
        for proto, ranges in extract_service_ports(custom_map[service_name]):
            wildcard = is_wildcard_range(ranges)
            resolved.append({
                "service_name": service_name,
                "resolved_from": "custom",
                "proto": proto,
                "ranges": ranges,
                "wildcard": wildcard,
                "unresolved": False,
            })

        visiting.remove(service_name)
        return resolved

    resolved.append({
        "service_name": service_name,
        "resolved_from": "unknown",
        "proto": "",
        "ranges": [],
        "wildcard": False,
        "unresolved": True,
    })

    visiting.remove(service_name)
    return resolved


# 対象ポリシーかどうか確認
def is_target_policy(policy):

    policy_id = str(policy.get("policyid", ""))

    if not policy_id:
        return False

    # 指定したポリシー番号を除外
    if policy_id in EXCLUDE_POLICY_IDS:
        return False

    # 無効ポリシーは対象外
    status = str(policy.get("status", "enable")).lower()

    if status != "enable":
        return False

    # 許可ポリシーのみ対象
    action = str(policy.get("action", "")).lower()

    if action != "accept":
        return False

    return True


# ポリシー設定ポート取得
def collect_configured_services():

    print("FortiGateからポリシーとサービス定義を取得しています。")

    # ポリシーとサービス定義を取得
    policies = cmdb_get("firewall/policy")
    custom_services = cmdb_get("firewall.service/custom")

    try:
        service_groups = cmdb_get("firewall.service/group")
    except RuntimeError as error:
        print(
            f"[警告] サービスグループの取得に失敗したため、"
            f"グループ展開なしで継続します。 {error}"
        )
        service_groups = []

    custom_map, group_map = build_service_indexes(
        custom_services,
        service_groups,
    )

    configured_rows = []
    policy_names = {}
    skipped_count = 0

    for policy in policies:
        if not is_target_policy(policy):
            skipped_count += 1
            continue

        policy_id = str(policy.get("policyid", ""))
        policy_name = policy.get("name", "")
        policy_names[policy_id] = policy_name

        # ポリシーに紐づくサービスをポートへ展開
        service_names = member_names(policy.get("service", []))

        if not service_names:
            configured_rows.append({
                "policyid": policy_id,
                "policy_name": policy_name,
                "policy_status": policy.get("status", ""),
                "policy_action": policy.get("action", ""),
                "service_name": "",
                "resolved_from": "empty",
                "proto": "",
                "port_start": "",
                "port_end": "",
                "port_range": "",
                "wildcard": "no",
                "unresolved": "yes",
            })
            continue

        for service_name in service_names:
            resolved_items = resolve_service(
                service_name,
                custom_map,
                group_map,
            )

            for item in resolved_items:
                ranges = item["ranges"]

                if not ranges:
                    configured_rows.append({
                        "policyid": policy_id,
                        "policy_name": policy_name,
                        "policy_status": policy.get("status", ""),
                        "policy_action": policy.get("action", ""),
                        "service_name": item["service_name"],
                        "resolved_from": item["resolved_from"],
                        "proto": item["proto"],
                        "port_start": "",
                        "port_end": "",
                        "port_range": "",
                        "wildcard": "yes" if item["wildcard"] else "no",
                        "unresolved": "yes" if item["unresolved"] else "no",
                    })
                    continue

                for start, end in merge_ranges(ranges):
                    configured_rows.append({
                        "policyid": policy_id,
                        "policy_name": policy_name,
                        "policy_status": policy.get("status", ""),
                        "policy_action": policy.get("action", ""),
                        "service_name": item["service_name"],
                        "resolved_from": item["resolved_from"],
                        "proto": item["proto"],
                        "port_start": start,
                        "port_end": end,
                        "port_range": format_ranges([(start, end)]),
                        "wildcard": "yes" if item["wildcard"] else "no",
                        "unresolved": "yes" if item["unresolved"] else "no",
                    })

    print(
        f"対象ポリシー数 : {len(policy_names):,}"
    )
    print(
        f"除外ポリシー数 : {skipped_count:,}"
    )
    print(
        f"設定ポート行数 : {len(configured_rows):,}"
    )

    return configured_rows, policy_names


# syslogから使用ポート集計
def collect_used_ports(start_datetime, end_datetime, policy_names):

    used = defaultdict(lambda: defaultdict(int))
    processed_files = 0
    missing_files = 0
    processed_lines = 0
    matched_lines = 0

    for target_datetime in iter_dates(start_datetime, end_datetime):
        input_gzip = build_input_path(target_datetime)

        # 対象gzipファイル確認
        if not os.path.exists(input_gzip):
            missing_files += 1
            print(
                f"[警告] gzipが存在しません: {input_gzip}"
            )
            continue

        if not os.path.isfile(input_gzip):
            missing_files += 1
            print(
                f"[警告] ファイルではありません: {input_gzip}"
            )
            continue

        processed_files += 1
        print(f"解析中: {input_gzip}")

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

                if "dstport=" not in line:
                    continue

                # key=value形式解析
                fields = parse_fortigate_log(line)

                policy_id = fields.get("policyid", "")

                # 指定したポリシー番号を除外
                if not policy_id or policy_id in EXCLUDE_POLICY_IDS:
                    continue

                # 有効かつ許可の対象ポリシー以外は除外
                if policy_id not in policy_names:
                    continue

                action = fields.get("action", "").strip().lower()

                if USED_ACTIONS and action not in USED_ACTIONS:
                    continue

                dstport = fields.get("dstport", "").strip()

                if not dstport.isdigit():
                    continue

                port = int(dstport)

                if port < 1 or port > 65535:
                    continue

                proto = normalize_proto(fields.get("proto", ""))

                used[(policy_id, proto)][port] += 1
                matched_lines += 1

    print("")
    print(f"解析gzip数     : {processed_files:,}")
    print(f"欠落gzip数     : {missing_files:,}")
    print(f"処理ログ行数   : {processed_lines:,}")
    print(f"使用ポート件数 : {matched_lines:,}")

    return used


# 使用ポートCSV行作成
def build_used_rows(used, policy_names):

    rows = []

    for (policy_id, proto), port_counts in used.items():
        for port, hit_count in sorted(port_counts.items()):
            rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "proto": proto,
                "dstport": port,
                "hit_count": hit_count,
            })

    rows.sort(
        key=lambda row: (
            int(row["policyid"]) if str(row["policyid"]).isdigit() else 0,
            row["proto"],
            int(row["dstport"]),
        )
    )

    return rows


# 未使用ポート突合
def build_unused_rows(configured_rows, used, policy_names):

    grouped = defaultdict(list)

    for row in configured_rows:
        key = (
            row["policyid"],
            row["service_name"],
            row["proto"],
            row["resolved_from"],
            row["wildcard"],
            row["unresolved"],
        )
        grouped[key].append(row)

    unused_rows = []

    for key, rows in grouped.items():
        policy_id, service_name, proto, resolved_from, wildcard, unresolved = key

        ranges = []

        for row in rows:
            if row["port_start"] == "" or row["port_end"] == "":
                continue

            ranges.append((int(row["port_start"]), int(row["port_end"])))

        used_for_policy = {}

        if proto == "ANY":
            for (used_policy_id, used_proto), port_counts in used.items():
                if used_policy_id == policy_id:
                    for port, hit_count in port_counts.items():
                        used_for_policy[port] = used_for_policy.get(port, 0) + hit_count
        else:
            used_for_policy = used.get((policy_id, proto), {})

        used_ports = set(used_for_policy)
        used_count = sum(used_for_policy.values())
        used_unique = len(used_ports)

        # 解決できないサービス / 全ポート許可 / L4なし
        if unresolved == "yes":
            unused_rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "service_name": service_name,
                "proto": proto,
                "unused_port_start": "",
                "unused_port_end": "",
                "unused_port_range": "",
                "unused_port_count": "",
                "configured_port_range": format_ranges(ranges),
                "used_unique_ports": used_unique,
                "used_hit_count": used_count,
                "wildcard": wildcard,
                "result": "unresolved",
                "note": "サービス定義を解決できませんでした。",
            })
            continue

        if wildcard == "yes" or is_wildcard_range(ranges):
            unused_rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "service_name": service_name,
                "proto": proto,
                "unused_port_start": "",
                "unused_port_end": "",
                "unused_port_range": "",
                "unused_port_count": "",
                "configured_port_range": format_ranges(ranges) or "ALL",
                "used_unique_ports": used_unique,
                "used_hit_count": used_count,
                "wildcard": "yes",
                "result": "wildcard",
                "note": "全ポート許可のため未使用ポートの展開は省略しました。used CSVを確認してください。",
            })
            continue

        if not ranges:
            unused_rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "service_name": service_name,
                "proto": proto,
                "unused_port_start": "",
                "unused_port_end": "",
                "unused_port_range": "",
                "unused_port_count": "",
                "configured_port_range": "",
                "used_unique_ports": used_unique,
                "used_hit_count": used_count,
                "wildcard": wildcard,
                "result": "no_l4_port",
                "note": "ICMP/IPサービスなどL4ポートを持たない定義です。",
            })
            continue

        # 設定ポートから使用ポートを除いた範囲を作成
        unused_ranges = subtract_used_ports(ranges, used_ports)

        if not unused_ranges:
            unused_rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "service_name": service_name,
                "proto": proto,
                "unused_port_start": "",
                "unused_port_end": "",
                "unused_port_range": "",
                "unused_port_count": 0,
                "configured_port_range": format_ranges(ranges),
                "used_unique_ports": used_unique,
                "used_hit_count": used_count,
                "wildcard": wildcard,
                "result": "all_used",
                "note": "設定ポートは解析期間内にすべて使用されていました。",
            })
            continue

        for start, end in unused_ranges:
            unused_rows.append({
                "policyid": policy_id,
                "policy_name": policy_names.get(policy_id, ""),
                "service_name": service_name,
                "proto": proto,
                "unused_port_start": start,
                "unused_port_end": end,
                "unused_port_range": format_ranges([(start, end)]),
                "unused_port_count": end - start + 1,
                "configured_port_range": format_ranges(ranges),
                "used_unique_ports": used_unique,
                "used_hit_count": used_count,
                "wildcard": wildcard,
                "result": "unused",
                "note": "設定されているが解析期間内に使用されていません。",
            })

    unused_rows.sort(
        key=lambda row: (
            int(row["policyid"]) if str(row["policyid"]).isdigit() else 0,
            row["service_name"],
            row["proto"],
            row["unused_port_start"] if row["unused_port_start"] != "" else -1,
        )
    )

    return unused_rows


# CSVファイル作成
def write_csv(path, fieldnames, rows):

    with open(
        path,
        mode="w",
        encoding=CSV_ENCODING,
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        # 項目名出力
        writer.writeheader()
        writer.writerows(rows)


# 未使用ポート件数表示
def print_unused_summary(unused_rows):

    unused_only = [
        row for row in unused_rows
        if row["result"] == "unused"
    ]

    print("")
    print("未使用ポートサマリ")
    print("-" * 60)
    print(f"未使用ポート行数: {len(unused_only):,}")

    if not unused_only:
        print("解析期間内に未使用と判定されたポートはありません。")
        return

    by_policy = defaultdict(int)

    for row in unused_only:
        count = row["unused_port_count"]
        if count == "":
            continue
        by_policy[row["policyid"]] += int(count)

    for policy_id, count in sorted(
        by_policy.items(),
        key=lambda item: int(item[0]) if item[0].isdigit() else 0,
    ):
        print(f"policyid {policy_id}: 未使用ポート {count:,} 個")


# メイン処理
def main():

    try:
        # 編集欄の設定確認
        validate_settings()

        # START_DATE / END_DATE確認
        start_datetime = validate_date(START_DATE, "START_DATE")
        end_datetime = validate_date(END_DATE, "END_DATE")

        if start_datetime > end_datetime:
            raise ValueError(
                "START_DATE は END_DATE 以前の日付を指定してください。"
            )

        search_days = (end_datetime - start_datetime).days + 1

        if search_days > MAX_SEARCH_DAYS:
            raise ValueError(
                f"検索範囲は最大{MAX_SEARCH_DAYS}日までです。"
            )

        output_paths = build_output_paths(START_DATE, END_DATE)

        print("FortiGate サービスポート突合処理")
        print("=" * 60)
        print(f"対象期間       : {START_DATE} - {END_DATE}")
        print(f"FortiGate      : {FGT_IP}")
        print(f"VDOM           : {VDOM}")
        print("対象ポリシー   : 有効かつ許可(accept)の全ポリシー")
        print(f"入力gzip規則   : {ARCHIVE_DIR}/yyyy-mm-dd/{FGT_IP}.log-yyyymmdd.gz")
        print(f"除外ポリシー   : {', '.join(sorted(EXCLUDE_POLICY_IDS))}")
        print("")

        # ポリシー設定ポート取得
        configured_rows, policy_names = collect_configured_services()

        if not policy_names:
            print(
                "[エラー] 対象ポリシーがありません。",
                file=sys.stderr,
            )
            sys.exit(1)

        print("")

        # syslogから使用ポート集計
        used = collect_used_ports(
            start_datetime,
            end_datetime,
            policy_names,
        )
        used_rows = build_used_rows(used, policy_names)

        # 未使用ポート突合
        unused_rows = build_unused_rows(configured_rows, used, policy_names)

        # CSV出力
        write_csv(
            output_paths["configured"],
            [
                "policyid",
                "policy_name",
                "policy_status",
                "policy_action",
                "service_name",
                "resolved_from",
                "proto",
                "port_start",
                "port_end",
                "port_range",
                "wildcard",
                "unresolved",
            ],
            configured_rows,
        )

        write_csv(
            output_paths["used"],
            [
                "policyid",
                "policy_name",
                "proto",
                "dstport",
                "hit_count",
            ],
            used_rows,
        )

        write_csv(
            output_paths["unused"],
            [
                "policyid",
                "policy_name",
                "service_name",
                "proto",
                "unused_port_start",
                "unused_port_end",
                "unused_port_range",
                "unused_port_count",
                "configured_port_range",
                "used_unique_ports",
                "used_hit_count",
                "wildcard",
                "result",
                "note",
            ],
            unused_rows,
        )

        print("")
        print("処理が完了しました。")
        print(f"設定ポートCSV  : {os.path.abspath(output_paths['configured'])}")
        print(f"使用ポートCSV  : {os.path.abspath(output_paths['used'])}")
        print(f"未使用ポートCSV: {os.path.abspath(output_paths['unused'])}")
        print_unused_summary(unused_rows)

    # エラー処理
    except ValueError as error:
        print(
            f"[設定エラー] {error}",
            file=sys.stderr,
        )
        sys.exit(1)

    except requests.exceptions.RequestException as error:
        print(
            "[APIエラー] FortiGateへの接続、または"
            "API通信に失敗しました。",
            file=sys.stderr,
        )
        print(
            f"[詳細] {error}",
            file=sys.stderr,
        )
        sys.exit(5)

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

    except RuntimeError as error:
        print(
            f"[実行エラー] {error}",
            file=sys.stderr,
        )
        sys.exit(5)

    except KeyboardInterrupt:
        print(
            "\nユーザー操作によって処理を中断しました。",
            file=sys.stderr,
        )
        sys.exit(130)


if __name__ == "__main__":
    main()
