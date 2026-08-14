import sqlite3
import re
import os
from datetime import datetime
import time
import sys

# 解决 Windows 控制台编码可能导致的崩溃
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# ================= 配置区 =================
# 回归最直接的固定路径
DB_PATH = r"C:\Users\27731\Desktop\nt_msg_decrypted.db"
EXPORT_DIR = r"C:\Users\27731\Desktop\QQ聊天记录导出"
# ==========================================

def extract_pure_chinese(blob_data):
    if not blob_data: return ""
    raw_text = blob_data.decode('utf-8', errors='ignore')
    items = re.findall(r'[\u4e00-\u9fa5]+[a-zA-Z0-9，。！？、~]*[\u4e00-\u9fa5]*', raw_text)
    
    clean_items = []
    for item in items:
        if any(bad in item.lower() for bad in ['rkey', 'appid', 'fileid', 'download', 'nt', 'qq', 'com']):
            continue
        if re.search(r'[\u4e00-\u9fa5]', item):
            clean_items.append(item)
            
    result = "".join(clean_items).strip()
    # 切除底层乱码标记
    if result.startswith("判f"): result = result[2:]
    elif result.startswith("判"): result = result[1:]
    return result

def get_all_contacts(cursor):
    try:
        cursor.execute("SELECT DISTINCT `40021` as uid, `40033` as qq FROM c2c_msg_table WHERE `40021` IS NOT NULL")
        return cursor.fetchall()
    except sqlite3.OperationalError as e:
        # 兼容不同版本的字段缺失
        if "column" in str(e).lower():
            cursor.execute("SELECT DISTINCT `40021` as uid, '未知QQ' as qq FROM c2c_msg_table WHERE `40021` IS NOT NULL")
            return cursor.fetchall()
        raise e

def parse_date(date_str, is_end_of_day=False):
    if not date_str.strip(): return None
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        if is_end_of_day: dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp())
    except ValueError:
        return None

def main():
    print("="*50)
    print("QQ 聊天记录提取引擎 V16 (诊断直达版)")
    print("="*50)

    # 1. 物理探伤：检查文件到底多大
    if not os.path.exists(DB_PATH):
        print(f"❌ 致命错误：桌面上根本没有 {DB_PATH} 这个文件！")
        return
        
    file_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"📊 正在读取文件... 当前文件大小为: {file_size_mb:.2f} MB")

    if not os.path.exists(EXPORT_DIR):
        os.makedirs(EXPORT_DIR)

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  
        cursor = conn.cursor()
    except Exception as e:
        print(f"❌ 连接失败！请检查文件是否存在。")
        return

    # 2. X光透视：看看里面到底装了什么表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    if 'c2c_msg_table' not in tables:
        print(f"\n❌ 错误：在数据库中找不到私聊表 'c2c_msg_table'！")
        print(f"💡 【深度诊断报告】")
        print(f"  - 这个文件里一共只有 {len(tables)} 个表。")
        if len(tables) > 0:
            print(f"  - 里面装的表叫: {', '.join(tables[:5])}...")
        
        if file_size_mb == 0:
            print("\n🚨 破案了！这个文件大小是 0.00 MB！")
            print("原因：你桌面上真正的文件可能带了隐藏的 .db 后缀（实际叫 .db.db）。")
            print("Python 找不到对的人，就自作主张在桌面上新建了一个 0MB 的空壳。请去桌面把那个 0KB 的假文件删掉，检查真文件的名字！")
        return

    print("✅ 数据库健康，包含聊天表！\n")

    contacts = get_all_contacts(cursor)
    if not contacts:
        print("未在数据库中发现私聊记录。")
        return

    print("1. 提取所有人 (自动用 QQ 号命名)")
    print("2. 提取指定人 (可自定义昵称命名)")
    choice = input("\n请选择操作编号 (1 或 2): ").strip()

    target_list = []
    nickname_map = {}

    if choice == "2":
        qq_input = input("\n请输入要提取的 QQ 号 (多个用逗号分隔，如果不确定填'未知QQ'): ").replace(" ", "").split(",")
        target_list = [c for c in contacts if str(c['qq']) in qq_input or c['uid'] in qq_input]
        
        print("\n[设置昵称]")
        for t in target_list:
            qq_str = str(t['qq'])
            nick = input(f"给 QQ {qq_str} 设置备注 (直接回车默认): ").strip()
            nickname_map[qq_str] = nick if nick else qq_str
    else:
        target_list = contacts
        for t in target_list:
            qq_str = str(t['qq'])
            nickname_map[qq_str] = qq_str

    print("\n[设置时间范围]")
    start_date = input("起始日期 (例 2020-01-01，直接回车不限): ")
    end_date = input("结束日期 (例 2021-01-01，直接回车不限): ")
    
    start_ts = parse_date(start_date) or 0
    end_ts = parse_date(end_date, True) or int(time.time() + 315360000)

    print(f"\n开始提取 {len(target_list)} 个好友的记录...\n")

    for person in target_list:
        uid = person['uid']
        qq_str = str(person['qq'])
        nickname = nickname_map.get(qq_str, qq_str)
        
        safe_nickname = re.sub(r'[\\/*?:"<>|]', "_", nickname)
        filename = f"{safe_nickname}.txt"
        
        cursor.execute("SELECT * FROM c2c_msg_table WHERE `40021` = ? AND `40050` >= ? AND `40050` <= ? ORDER BY `40050` ASC", (uid, start_ts, end_ts))
        rows = cursor.fetchall()
        chat_data = []
        
        for row in rows:
            keys = row.keys()
            sender_uid = row["40020"] if "40020" in keys else ""
            peer_uid = row["40021"] if "40021" in keys else ""
            timestamp = row["40050"] if "40050" in keys else 0
            
            # 判断身份
            if sender_uid and sender_uid == peer_uid:
                sender = f"{nickname}"
            else:
                sender = "我"
            
            time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            text = extract_pure_chinese(row["40800"]) if "40800" in keys and isinstance(row["40800"], bytes) else ""
            
            if text.strip():
                chat_data.append(f"[{time_str}] 【{sender}】: {text}\n")
        
        if chat_data:
            file_path = os.path.join(EXPORT_DIR, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(chat_data)
            print(f"  成功导出: {filename} ({len(chat_data)} 条对话)")
        else:
            print(f"  跳过: {nickname} (所选时间段内无文字记录)")

    conn.close()
    print("\n" + "="*50)
    print(f"全部任务完美收工！保存在: {EXPORT_DIR}")
    print("="*50)

if __name__ == "__main__":
    main()