#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ 聊天记录提取引擎 (V17, CLI 版)

从 NTQQ 解密数据库 (nt_msg_decrypted.db) 提取私聊记录为纯文本或 CSV。

用法:
    python extract.py                          # 交互模式(默认路径)
    python extract.py --db PATH --out DIR      # 指定数据库与输出目录
    python extract.py --contacts 123,456 --start 2020-01-01 --end 2021-01-01
    python extract.py --format csv --yes       # 非交互, 导出 CSV
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

# 解决 Windows 控制台编码可能导致的崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ================= 配置区(可被命令行参数覆盖) =================
DEFAULT_DB_PATH = r"C:\Users\27731\Desktop\nt_msg_decrypted.db"
DEFAULT_EXPORT_DIR = r"C:\Users\27731\Desktop\QQ聊天记录导出"
# ==============================================================


def extract_pure_chinese(blob_data):
    """从原始 blob 中提取纯中文文本, 过滤底层乱码标记。"""
    if not blob_data:
        return ""
    raw_text = blob_data.decode("utf-8", errors="ignore")
    items = re.findall(
        r"[\u4e00-\u9fa5]+[a-zA-Z0-9，。！？、~]*[\u4e00-\u9fa5]*", raw_text
    )

    clean_items = []
    for item in items:
        if any(bad in item.lower() for bad in ["rkey", "appid", "fileid", "download", "nt", "qq", "com"]):
            continue
        if re.search(r"[\u4e00-\u9fa5]", item):
            clean_items.append(item)

    result = "".join(clean_items).strip()
    # 切除底层乱码标记
    if result.startswith("判f"):
        result = result[2:]
    elif result.startswith("判"):
        result = result[1:]
    return result


def get_all_contacts(cursor):
    """枚举 c2c_msg_table 中所有联系人 (uid, qq)。"""
    try:
        cursor.execute(
            "SELECT DISTINCT `40021` as uid, `40033` as qq FROM c2c_msg_table WHERE `40021` IS NOT NULL"
        )
        return cursor.fetchall()
    except sqlite3.OperationalError as e:
        # 兼容不同版本的字段缺失
        if "column" in str(e).lower():
            cursor.execute(
                "SELECT DISTINCT `40021` as uid, '未知QQ' as qq FROM c2c_msg_table WHERE `40021` IS NOT NULL"
            )
            return cursor.fetchall()
        raise e


def parse_date(date_str, is_end_of_day=False):
    """解析 YYYY-MM-DD 为时间戳; 结束日期取当日 23:59:59。"""
    if not date_str or not date_str.strip():
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        if is_end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp())
    except ValueError:
        return None


def fetch_chat_rows(cursor, uid, start_ts=0, end_ts=None):
    """按联系人和时间范围取聊天记录行。"""
    if end_ts is None:
        end_ts = int(time.time() + 315360000)
    cursor.execute(
        "SELECT * FROM c2c_msg_table WHERE `40021` = ? AND `40050` >= ? AND `40050` <= ? ORDER BY `40050` ASC",
        (uid, start_ts, end_ts),
    )
    return cursor.fetchall()


def build_messages(rows, nickname):
    """把原始行转换为消息列表 [(time_str, sender, text), ...]。"""
    messages = []
    for row in rows:
        keys = row.keys()
        sender_uid = row["40020"] if "40020" in keys else ""
        peer_uid = row["40021"] if "40021" in keys else ""
        timestamp = row["40050"] if "40050" in keys else 0

        # 判断身份: 发送者 uid 等于对方 uid 时是对方, 否则是"我"
        if sender_uid and sender_uid == peer_uid:
            sender = nickname
        else:
            sender = "我"

        time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        text = (
            extract_pure_chinese(row["40800"])
            if "40800" in keys and isinstance(row["40800"], bytes)
            else ""
        )
        if text.strip():
            messages.append((time_str, sender, text))
    return messages


def export_txt(messages, nickname, export_dir):
    """导出为 txt, 返回文件路径; 无消息返回 None。"""
    if not messages:
        return None
    safe_nickname = re.sub(r'[\\/*?:"<>|]', "_", nickname)
    file_path = os.path.join(export_dir, f"{safe_nickname}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        for time_str, sender, text in messages:
            f.write(f"[{time_str}] 【{sender}】: {text}\n")
    return file_path


def export_csv(messages, nickname, export_dir):
    """导出为 CSV (time, sender, text), 返回文件路径; 无消息返回 None。"""
    if not messages:
        return None
    safe_nickname = re.sub(r'[\\/*?:"<>|]', "_", nickname)
    file_path = os.path.join(export_dir, f"{safe_nickname}.csv")
    with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["时间", "发送者", "内容"])
        writer.writerows(messages)
    return file_path


def process_contact(cursor, uid, qq_str, nickname, start_ts, end_ts, export_dir, fmt):
    """提取单个联系人并导出, 返回 (导出文件数, 消息数)。"""
    rows = fetch_chat_rows(cursor, uid, start_ts, end_ts)
    messages = build_messages(rows, nickname)
    if not messages:
        return 0, 0

    exporter = export_csv if fmt == "csv" else export_txt
    file_path = exporter(messages, nickname, export_dir)
    print(f"  成功导出: {os.path.basename(file_path)} ({len(messages)} 条对话)")
    return 1, len(messages)


def interactive_mode(db_path, export_dir, fmt):
    """原 V16 交互流程(无命令行参数时使用), 返回 (文件数, 消息数)。"""
    print("=" * 50)
    print("QQ 聊天记录提取引擎 V17 (交互模式)")
    print("=" * 50)

    if not os.path.exists(db_path):
        print(f"❌ 致命错误: 找不到数据库文件 {db_path}!")
        return 0, 0

    file_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"📊 正在读取文件... 当前文件大小为: {file_size_mb:.2f} MB")

    if not os.path.exists(export_dir):
        os.makedirs(export_dir)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    except Exception as e:
        print(f"❌ 连接失败! 请检查文件是否存在。 ({e})")
        return 0, 0

    # 检查表结构
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    if "c2c_msg_table" not in tables:
        print(f"\n❌ 错误: 在数据库中找不到私聊表 'c2c_msg_table'!")
        print(f"💡 【深度诊断报告】")
        print(f"  - 这个文件里一共只有 {len(tables)} 个表。")
        if len(tables) > 0:
            print(f"  - 里面装的表叫: {', '.join(tables[:5])}...")
        if file_size_mb == 0:
            print("\n🚨 破案了! 这个文件大小是 0.00 MB!")
            print("原因: 桌面上的真实文件可能带隐藏的 .db 后缀(实际叫 .db.db)。")
            print("Python 找不到对的人, 就自作主张新建了一个 0MB 的空壳。请去桌面把假文件删掉, 检查真文件的名字!")
        conn.close()
        return 0, 0

    print("✅ 数据库健康, 包含聊天表!\n")

    contacts = get_all_contacts(cursor)
    if not contacts:
        print("未在数据库中发现私聊记录。")
        conn.close()
        return 0, 0

    print("1. 提取所有人 (自动用 QQ 号命名)")
    print("2. 提取指定人 (可自定义昵称命名)")
    choice = input("\n请选择操作编号 (1 或 2): ").strip()

    target_list = []
    nickname_map = {}

    if choice == "2":
        qq_input = input("\n请输入要提取的 QQ 号 (多个用逗号分隔, 如果不确定填'未知QQ'): ").replace(" ", "").split(",")
        target_list = [c for c in contacts if str(c["qq"]) in qq_input or c["uid"] in qq_input]

        print("\n[设置昵称]")
        for t in target_list:
            qq_str = str(t["qq"])
            nick = input(f"给 QQ {qq_str} 设置备注 (直接回车默认): ").strip()
            nickname_map[qq_str] = nick if nick else qq_str
    else:
        target_list = contacts
        for t in target_list:
            nickname_map[str(t["qq"])] = str(t["qq"])

    print("\n[设置时间范围]")
    start_date = input("起始日期 (例 2020-01-01, 直接回车不限): ")
    end_date = input("结束日期 (例 2021-01-01, 直接回车不限): ")

    start_ts = parse_date(start_date) or 0
    end_ts = parse_date(end_date, True) or int(time.time() + 315360000)

    print(f"\n开始提取 {len(target_list)} 个好友的记录...\n")

    total_files, total_msgs = 0, 0
    for person in target_list:
        uid = person["uid"]
        qq_str = str(person["qq"])
        nickname = nickname_map.get(qq_str, qq_str)
        n_files, n_msgs = process_contact(cursor, uid, qq_str, nickname, start_ts, end_ts, export_dir, fmt)
        total_files += n_files
        total_msgs += n_msgs

    conn.close()
    print("\n" + "=" * 50)
    print(f"全部任务完成! 导出 {total_files} 个文件 / {total_msgs} 条消息 → {export_dir}")
    print("=" * 50)
    return total_files, total_msgs


def cli_mode(args):
    """命令行模式: 提取所有联系人(或指定), 非交互。"""
    print("=" * 50)
    print("QQ 聊天记录提取引擎 V17 (CLI 模式)")
    print("=" * 50)

    if not os.path.exists(args.db):
        print(f"❌ 致命错误: 找不到数据库文件 {args.db}!")
        return 1

    file_size_mb = os.path.getsize(args.db) / (1024 * 1024)
    print(f"📊 数据库大小: {file_size_mb:.2f} MB")

    if not os.path.exists(args.out):
        os.makedirs(args.out)

    try:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    except Exception as e:
        print(f"❌ 连接失败! ({e})")
        return 1

    # 检查表结构
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    if "c2c_msg_table" not in tables:
        print(f"❌ 错误: 找不到私聊表 'c2c_msg_table' (表: {tables[:5]})")
        conn.close()
        return 1

    contacts = get_all_contacts(cursor)
    if not contacts:
        print("未在数据库中发现私聊记录。")
        conn.close()
        return 1

    # 过滤目标联系人
    if args.contacts:
        wanted = [c.strip() for c in args.contacts.split(",") if c.strip()]
        target_list = [c for c in contacts if str(c["qq"]) in wanted or c["uid"] in wanted]
        if not target_list:
            print(f"❌ 指定的联系人 {wanted} 未在数据库中找到。")
            conn.close()
            return 1
    else:
        target_list = contacts

    start_ts = parse_date(args.start) or 0
    end_ts = parse_date(args.end, True) or int(time.time() + 315360000)

    print(f"目标: {len(target_list)} 个联系人 | 格式: {args.format} | 时间: {args.start or '不限'} ~ {args.end or '不限'}\n")

    total_files, total_msgs = 0, 0
    for person in target_list:
        uid = person["uid"]
        qq_str = str(person["qq"])
        # CLI 模式直接用 QQ 号命名(可用 --nickname 覆盖见 README)
        nickname = qq_str
        n_files, n_msgs = process_contact(cursor, uid, qq_str, nickname, start_ts, end_ts, args.out, args.format)
        total_files += n_files
        total_msgs += n_msgs

    conn.close()
    print("\n" + "=" * 50)
    print(f"完成! 导出 {total_files} 个文件 / {total_msgs} 条消息 → {args.out}")
    print("=" * 50)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="从 NTQQ 解密数据库提取私聊记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python extract.py                              # 交互模式\n"
            "  python extract.py --db D:\\msg.db --out D:\\out   # 指定路径\n"
            "  python extract.py --contacts 123,456 --format csv\n"
        ),
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help=f"数据库路径 (默认: {DEFAULT_DB_PATH})")
    parser.add_argument("--out", default=DEFAULT_EXPORT_DIR, help=f"输出目录 (默认: {DEFAULT_EXPORT_DIR})")
    parser.add_argument("--contacts", default="", help="指定 QQ 号, 逗号分隔 (默认: 全部)")
    parser.add_argument("--start", default="", help="起始日期 YYYY-MM-DD (默认: 不限)")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD (默认: 不限)")
    parser.add_argument("--format", choices=["txt", "csv"], default="txt", help="输出格式 (默认: txt)")
    parser.add_argument("--interactive", action="store_true", help="强制交互模式")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.interactive or not (args.db != DEFAULT_DB_PATH or args.contacts or args.start or args.end):
        # 未提供任何有效参数 → 交互模式(向后兼容)
        interactive_mode(args.db, args.out, args.format)
    else:
        cli_mode(args)


if __name__ == "__main__":
    main()
