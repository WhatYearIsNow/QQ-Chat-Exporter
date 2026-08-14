# -*- coding: utf-8 -*-
"""extract.py 单元测试

构造内存 SQLite 数据库模拟 c2c_msg_table, 验证:
- extract_pure_chinese 文本清洗
- get_all_contacts 联系人枚举
- parse_date 日期解析
- build_messages 消息构建与身份判断
- export_txt / export_csv 导出

运行: python -m pytest tests/ -v
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

# 让测试可以 import 项目根目录的 extract.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract  # noqa: E402


# ---------- 工具函数: 构造 mock 数据库 / 临时目录 ----------

def make_tmp():
    """创建测试用临时目录(位于项目内, 避免沙箱外写权限问题)。"""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".testtmp")
    case = os.path.join(base, "case-%d" % os.getpid())
    os.makedirs(case, exist_ok=True)
    return case


def rm_tmp(path):
    shutil.rmtree(path, ignore_errors=True)


def make_db():
    """返回 (conn, cursor), 建好 c2c_msg_table 并插入测试数据。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE c2c_msg_table (
            `40020` INTEGER,  -- 发送者 uid
            `40021` INTEGER,  -- 对方 uid
            `40033` TEXT,     -- 对方 QQ 号
            `40050` INTEGER,  -- 时间戳
            `40800` BLOB      -- 消息内容 blob
        )"""
    )

    def ts(date_str, hour=12):
        dt = datetime.strptime(f"{date_str} {hour}:00:00", "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())

    # 联系人 A: uid=1001, qq='123456'
    # 联系人 B: uid=1002, qq='654321'
    rows = [
        # (sender_uid, peer_uid, qq, timestamp, blob)
        (1001, 1001, "123456", ts("2020-05-01"), "你好，我是测试".encode("utf-8")),
        (1001, 1001, "123456", ts("2020-05-02"), "明天见".encode("utf-8")),
        (0, 1001, "123456", ts("2020-05-03"), "我发的一条消息".encode("utf-8")),
        (1002, 1002, "654321", ts("2020-06-01"), "另一位的消息".encode("utf-8")),
        # 含乱码标记的 blob
        (1001, 1001, "123456", ts("2020-05-04"), "判f正常文本".encode("utf-8")),
        # 空内容
        (1001, 1001, "123456", ts("2020-05-05"), b""),
    ]
    cursor.executemany(
        "INSERT INTO c2c_msg_table VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    return conn, cursor


# ---------- 测试用例 ----------

class TestExtractPureChinese:
    def test_normal_text(self):
        assert extract.extract_pure_chinese("你好世界".encode("utf-8")) == "你好世界"

    def test_filters_junk(self):
        # rkey/appid 等标记应被过滤
        blob = "some rkey=abc 真实文本".encode("utf-8")
        result = extract.extract_pure_chinese(blob)
        assert "rkey" not in result
        assert "真实文本" in result

    def test_strips_prefix_marker(self):
        assert extract.extract_pure_chinese("判f正常文本".encode("utf-8")) == "正常文本"

    def test_empty_blob(self):
        assert extract.extract_pure_chinese(None) == ""
        assert extract.extract_pure_chinese(b"") == ""


class TestGetAllContacts:
    def test_returns_distinct_contacts(self):
        conn, cursor = make_db()
        contacts = extract.get_all_contacts(cursor)
        qqs = sorted(str(c["qq"]) for c in contacts)
        assert qqs == ["123456", "654321"]
        conn.close()

    def test_fallback_on_missing_column(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE c2c_msg_table (`40021` INTEGER)")
        cursor.execute("INSERT INTO c2c_msg_table VALUES (1001)")
        conn.commit()
        contacts = extract.get_all_contacts(cursor)
        assert len(contacts) == 1
        assert contacts[0]["qq"] == "未知QQ"
        conn.close()


class TestParseDate:
    def test_parses_start(self):
        ts = extract.parse_date("2020-01-01")
        assert ts is not None
        assert ts > 0

    def test_parses_end_of_day(self):
        start = extract.parse_date("2020-01-01")
        end = extract.parse_date("2020-01-01", True)
        assert end - start == 86399  # 23:59:59

    def test_invalid_date_returns_none(self):
        assert extract.parse_date("not-a-date") is None
        assert extract.parse_date("") is None
        assert extract.parse_date(None) is None


class TestBuildMessages:
    def test_identity_and_sender(self):
        conn, cursor = make_db()
        rows = extract.fetch_chat_rows(cursor, 1001, 0)
        messages = extract.build_messages(rows, "测试好友")
        # 6 条原始记录中 1 条空 blob 被跳过 → 4 条
        assert len(messages) == 4
        # 对方发言 → sender=昵称; 自己发言 → sender=我
        assert messages[0][1] == "测试好友"
        assert messages[2][1] == "我"
        # 时间格式
        assert messages[0][0] == "2020-05-01 12:00:00"
        conn.close()

    def test_fetch_with_time_range(self):
        conn, cursor = make_db()
        start = extract.parse_date("2020-05-02")
        end = extract.parse_date("2020-05-03", True)
        rows = extract.fetch_chat_rows(cursor, 1001, start, end)
        messages = extract.build_messages(rows, "测试好友")
        assert len(messages) == 2  # 05-02 和 05-03
        conn.close()


class TestExport:
    def test_export_txt(self):
        conn, cursor = make_db()
        rows = extract.fetch_chat_rows(cursor, 1001, 0)
        messages = extract.build_messages(rows, "测试好友")
        tmp = make_tmp()
        try:
            path = extract.export_txt(messages, "测试好友", tmp)
            assert path and os.path.exists(path)
            content = open(path, encoding="utf-8").read()
            assert "【测试好友】" in content
            assert "【我】" in content
        finally:
            rm_tmp(tmp)
        conn.close()

    def test_export_csv(self):
        conn, cursor = make_db()
        rows = extract.fetch_chat_rows(cursor, 1001, 0)
        messages = extract.build_messages(rows, "测试好友")
        tmp = make_tmp()
        try:
            path = extract.export_csv(messages, "测试好友", tmp)
            assert path and os.path.exists(path)
            content = open(path, encoding="utf-8-sig").read()
            assert "时间,发送者,内容" in content
            assert "测试好友" in content
        finally:
            rm_tmp(tmp)
        conn.close()

    def test_export_none_when_empty(self):
        tmp = make_tmp()
        try:
            assert extract.export_txt([], "无人", tmp) is None
            assert extract.export_csv([], "无人", tmp) is None
        finally:
            rm_tmp(tmp)

    def test_safe_filename(self):
        conn, cursor = make_db()
        rows = extract.fetch_chat_rows(cursor, 1001, 0)
        messages = extract.build_messages(rows, "坏/名字")
        tmp = make_tmp()
        try:
            path = extract.export_txt(messages, "坏/名字", tmp)
            assert path and "/" not in os.path.basename(path)
            assert os.path.exists(path)
        finally:
            rm_tmp(tmp)
        conn.close()


class TestProcessContact:
    def test_returns_counts(self):
        conn, cursor = make_db()
        tmp = make_tmp()
        try:
            n_files, n_msgs = extract.process_contact(
                cursor, 1001, "123456", "测试好友", 0, None, tmp, "txt"
            )
            assert n_files == 1
            assert n_msgs == 4
        finally:
            rm_tmp(tmp)
        conn.close()

    def test_empty_contact(self):
        conn, cursor = make_db()
        tmp = make_tmp()
        try:
            n_files, n_msgs = extract.process_contact(
                cursor, 9999, "000000", "不存在", 0, None, tmp, "txt"
            )
            assert n_files == 0
            assert n_msgs == 0
        finally:
            rm_tmp(tmp)
        conn.close()
