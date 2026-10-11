#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_flclash_windows.py — 把 hosts 固定写入 Windows 版 FlClash 的配置。

特性:
  * 自动定位 %APPDATA%\\com.follow\\clash\\shared_preferences.json
  * 执行前检查 FlClash 是否已退出(避免写入被应用回写覆盖), 可用 --force 跳过
  * 自动生成带时间戳的备份
  * 幂等: 重复执行只是覆盖同样的键

用法:
  python patch_flclash_windows.py ping0.cc=104.218.235.243 www.ping0.cc=104.218.235.243
  python patch_flclash_windows.py --file hosts.txt        # 每行 "域名=IP" 或 "域名 IP", # 为注释
  python patch_flclash_windows.py --show                  # 只显示当前 hosts
  python patch_flclash_windows.py --remove ping0.cc       # 删除某个键
  python patch_flclash_windows.py --dry-run ...           # 只预览不写入

完成后请手动重新打开 FlClash 并启动核心。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

PREF_REL = os.path.join("com.follow", "clash", "shared_preferences.json")


def default_prefs_path() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("未找到 %APPDATA%（此脚本面向 Windows 版 FlClash）")
    return os.path.join(appdata, PREF_REL)


def flclash_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq FlClash.exe"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=20,
        )
        return "FlClash.exe" in (out.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def load_config(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        outer = json.load(fh)
    cfg = outer.get("flutter.config")
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    if not isinstance(cfg, dict):
        sys.exit("配置结构异常：flutter.config 不是对象")
    return outer, cfg


def save_config(path: str, outer: dict, cfg: dict) -> None:
    outer["flutter.config"] = json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(outer, fh, ensure_ascii=False, separators=(",", ":"))


def parse_pairs(items) -> dict:
    pairs = {}
    for item in items:
        item = item.strip()
        if not item or item.startswith("#"):
            continue
        if "=" in item:
            key, value = item.split("=", 1)
        elif " " in item:
            key, value = item.split(None, 1)
        else:
            sys.exit(f"无法解析条目: {item!r}（正确格式: 域名=IP）")
        pairs[key.strip()] = value.strip()
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="把 hosts 固定写入 Windows 版 FlClash 配置（写入前请退出 FlClash）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("pairs", nargs="*", help="域名=IP，可多个")
    parser.add_argument("--file", help="从文件读取（每行: 域名=IP 或 '域名 IP'，# 开头为注释）")
    parser.add_argument("--remove", nargs="*", default=[], help="删除指定域名的 hosts 记录")
    parser.add_argument("--show", action="store_true", help="只显示当前 hosts")
    parser.add_argument("--prefs", help="自定义 shared_preferences.json 路径（高级/测试用）")
    parser.add_argument("--force", action="store_true", help="即使检测到 FlClash 正在运行也继续")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入的内容，不落盘")
    args = parser.parse_args(argv)

    path = args.prefs or default_prefs_path()
    if not os.path.exists(path):
        sys.exit(f"未找到配置文件: {path}\n(请确认已安装并至少运行过一次 FlClash)")

    outer, cfg = load_config(path)
    patch = cfg.setdefault("patchClashConfig", {})
    hosts = patch.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        sys.exit("hosts 字段类型异常，已中止")
    hosts = dict(hosts)

    if args.show and not args.pairs and not args.file and not args.remove:
        print(f"配置文件: {path}")
        print(json.dumps(hosts, ensure_ascii=False, indent=2))
        return 0

    updates = dict(parse_pairs(args.pairs))
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            updates.update(parse_pairs(fh.readlines()))

    changed = False
    for key, value in updates.items():
        if hosts.get(key) != value:
            hosts[key] = value
            changed = True
    for key in args.remove:
        if key in hosts:
            del hosts[key]
            changed = True

    print("修改后的 hosts:")
    print(json.dumps(hosts, ensure_ascii=False, indent=2))
    if not changed:
        print("(无变化)")
        return 0
    if args.dry_run:
        print("dry-run: 未写入")
        return 0
    if flclash_running() and not args.force:
        sys.exit(
            "检测到 FlClash 正在运行。请先完全退出 FlClash（含托盘图标），\n"
            "或加 --force 强制写入。注意：运行中写入的修改可能被应用回写覆盖。"
        )

    backup = path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup)
    patch["hosts"] = hosts
    save_config(path, outer, cfg)
    print(f"已写入: {path}")
    print(f"备份:   {backup}")
    print("请重新打开 FlClash 并启动核心以生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
