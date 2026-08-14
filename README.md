# QQ 聊天记录导出工具

从本地 NTQQ 解密数据库(`nt_msg_decrypted.db`)提取 QQ 私聊记录为纯文本或 CSV 的命令行工具。

## 功能

- 连接 `c2c_msg_table` 私聊表,提取全部联系人或指定 QQ 的聊天记录
- 纯中文文本清洗(过滤 rkey/appid 等底层乱码标记)
- 支持时间范围过滤、自定义昵称命名
- 输出格式:`txt`(默认)或 `csv`
- CLI 参数化,可脚本化、可自动化

## 安装

纯标准库,无需第三方依赖(测试需要 `pytest`):

```powershell
python -m pip install pytest   # 仅运行测试时需要
```

## 用法

### CLI 模式(推荐)

```powershell
# 提取全部联系人到默认目录
python extract.py --db D:\path\to\nt_msg_decrypted.db

# 指定输出目录 + CSV 格式
python extract.py --db D:\msg.db --out D:\out --format csv

# 只提取指定 QQ, 限定时间范围
python extract.py --db D:\msg.db --contacts 123456,789012 --start 2020-01-01 --end 2021-01-01
```

### 交互模式(向后兼容 V16)

```powershell
python extract.py            # 用默认路径进入交互菜单
python extract.py --interactive
```

### 参数表

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--db` | 数据库路径 | `C:\Users\27731\Desktop\nt_msg_decrypted.db` |
| `--out` | 输出目录 | `C:\Users\27731\Desktop\QQ聊天记录导出` |
| `--contacts` | 指定 QQ 号,逗号分隔 | 全部联系人 |
| `--start` | 起始日期 `YYYY-MM-DD` | 不限 |
| `--end` | 结束日期 `YYYY-MM-DD` | 不限 |
| `--format` | `txt` 或 `csv` | `txt` |
| `--interactive` | 强制交互模式 | 否 |

## 测试

```powershell
python -m pytest tests/ -v
```

17 个用例覆盖:文本清洗、联系人枚举、日期解析、消息构建(身份判断)、TXT/CSV 导出、文件名安全、空数据与时间范围过滤。

## 目录结构

```text
.
├── extract.py            主程序(CLI + 交互双模式)
├── tests/
│   └── test_extract.py   单元测试(mock 数据库)
├── README.md
└── .gitignore
```

## 数据来源说明

- `nt_msg_decrypted.db`:NTQQ 本地数据库解密产物(需先用对应工具解密),属个人隐私数据,**不进入本仓库**
- 导出路径默认在桌面,可自行修改

## 注意事项

- 数据库与导出的聊天记录属个人隐私,仅限本人使用,请勿公开或传播
- 本工具仅用于个人学习资料的整理与备份
