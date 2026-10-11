#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_working_ip.py — 为「走代理打不开」的域名探测可用的真实 IP。

做法:
  1) 向多个公共 DoH 解析器查询 A / AAAA 记录;
  2) 对每个候选 IPv4 做直连 TCP + TLS 探测;
  3) 输出每个域名的可用 IP, 以及可直接粘贴到 Clash/mihomo 系客户端 hosts 的片段。

用法示例:
  python find_working_ip.py ping0.cc www.ping0.cc cdn.ping0.cc
  python find_working_ip.py --proxy http://127.0.0.1:7890 ping0.cc
  python find_working_ip.py --doh https://doh.pub/dns-query https://dns.google/resolve example.com

仅使用 Python 标准库, Windows / macOS / Linux 均可运行 (Python 3.7+)。
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_DOH = [
    "https://doh.pub/dns-query",
    "https://1.12.12.12/dns-query",
    "https://dns.alidns.com/resolve",
]

_FALLBACK_RE = re.compile(r'"data"\s*:\s*"([0-9a-fA-F:.]+)"')
# DoH 查询强制直连, 避免本机系统代理开启时改变语义
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def doh_query(doh_url: str, name: str, qtype: str, timeout: float) -> list:
    """向 DoH 服务器查询域名, 返回记录字符串列表; 失败抛异常。"""
    query = urllib.parse.urlencode({"name": name, "type": qtype})
    sep = "&" if "?" in doh_url else "?"
    req = urllib.request.Request(
        f"{doh_url}{sep}{query}",
        headers={"accept": "application/dns-json", "user-agent": "find-working-ip/1.0"},
    )
    with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except ValueError:
        return _FALLBACK_RE.findall(raw)
    want = 1 if qtype == "A" else 28
    out = []
    for ans in data.get("Answer") or []:
        if isinstance(ans, dict) and ans.get("type") == want and isinstance(ans.get("data"), str):
            out.append(ans["data"])
    if not out:
        out = _FALLBACK_RE.findall(raw)
    return out


def tcp_tls_test(ip: str, port: int, sni: str, timeout: float):
    """直连 TCP(+TLS 握手) 探测。返回 (grade, ms, note)。

    grade: "OK" = TCP+TLS 都通; "TCP" = 仅 TCP 通(TLS 未完成, 可能被本地网络干扰,
    经代理仍可能可用); "DEAD" = TCP 都不通。
    """
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except OSError as exc:
        return "DEAD", (time.monotonic() - t0) * 1000, f"TCP 失败({exc.__class__.__name__})"
    ms = (time.monotonic() - t0) * 1000
    if sni and port == 443:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(sock, server_hostname=sni):
                pass
        except OSError as exc:
            try:
                sock.close()
            except OSError:
                pass
            return "TCP", ms, f"TLS 未完成({exc.__class__.__name__}, 可能被本地网络干扰)"
        return "OK", ms, "TCP+TLS OK"
    else:
        sock.close()
        return "TCP", ms, "TCP OK"


def has_local_ipv6() -> bool:
    """粗略探测本机是否有可用 IPv6 出网能力。"""
    try:
        infos = socket.getaddrinfo("ipv6.google.com", 443, socket.AF_INET6)
    except OSError:
        return False
    if not infos:
        return False
    af, socktype, proto, _, sa = infos[0]
    sock = socket.socket(af, socktype, proto)
    sock.settimeout(3)
    try:
        sock.connect(sa)
        return True
    except OSError:
        return False
    finally:
        sock.close()


def proxy_https_check(proxy: str, domain: str, timeout: float):
    """通过本地代理真实访问一次, 返回 (ok, note)。"""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    req = urllib.request.Request(
        f"https://{domain}/",
        headers={"user-agent": "Mozilla/5.0 (find-working-ip)"},
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}"  # 服务端有响应即链路通
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="探测域名可用的真实 IP 并输出 hosts 片段 (用于修复「走代理打不开」)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("domains", nargs="+", help="要探测的域名, 如 ping0.cc")
    parser.add_argument("--doh", nargs="*", default=DEFAULT_DOH, help="DoH 服务器列表")
    parser.add_argument("--port", type=int, default=443, help="探测端口")
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="单次超时(秒)。直连 TLS 可能较慢/受干扰, 如全部显示 TLS 未完成可加大到 15",
    )
    parser.add_argument(
        "--proxy",
        help="可选: 修复后用本地代理做一次真实访问验证, 如 http://127.0.0.1:7890",
    )
    args = parser.parse_args(argv)

    print("== 1) 多解析器查询 (A 记录) ==")
    per_domain = {}
    for domain in args.domains:
        records = {}
        for doh in args.doh:
            host = urllib.parse.urlsplit(doh).netloc or doh
            try:
                ips = doh_query(doh, domain, "A", args.timeout)
                shown = ips if ips else "(空)"
                print(f"  {domain:24s} @ {host:22s} -> {shown}")
                for ip in ips:
                    records.setdefault(ip, set()).add(host)
            except Exception as exc:  # noqa: BLE001
                print(f"  {domain:24s} @ {host:22s} -> 查询失败: {exc}")
        per_domain[domain] = records

    print()
    print("== 2) AAAA 记录(仅提示) ==")
    for domain in args.domains:
        try:
            aaaa = doh_query(args.doh[0], domain, "AAAA", args.timeout)
        except Exception:  # noqa: BLE001
            aaaa = []
        if aaaa:
            print(f"  {domain:24s} AAAA = {aaaa}")
        else:
            print(f"  {domain:24s} 无 AAAA 记录")
    print(f"  本机直连 IPv6: {'可用' if has_local_ipv6() else '不可用(如需固定 IP, 优先用 IPv4)'}")

    print()
    print("== 3) 候选 IP 直连探测 (TCP/TLS) ==")
    print("   (说明: 经代理访问时实际由【节点】去连 IP; 本步骤的直连探测用于过滤死地址。")
    print("    本机网络对部分境外 IP 可能有干扰, 显示 'TLS 未完成' 但 TCP 通的 IP 通常仍可用。)")
    best = {}
    for domain, records in per_domain.items():
        rows = []
        if not records:
            print(f"  {domain:24s} 没有候选 IP (所有解析器都失败或为空)")
            continue
        for ip, sources in sorted(records.items()):
            grade, ms, note = tcp_tls_test(ip, args.port, domain, args.timeout)
            rows.append((grade, ms, ip, note, sorted(sources)))
            flag = {"OK": "OK    ", "TCP": "TCP-ONLY", "DEAD": "DEAD  "}[grade]
            print(
                f"  {domain:24s} {ip:18s} {flag} {ms:7.1f}ms  {note:34s} 来自 {', '.join(sorted(sources))}"
            )
        live = [r for r in rows if r[0] in ("OK", "TCP")]
        if live:
            # 优先 TCP+TLS 都通的, 其次按延迟
            live.sort(key=lambda r: (0 if r[0] == "OK" else 1, r[1]))
            best[domain] = live[0]

    print()
    print("== 4) 建议 hosts 片段 (粘贴到 Clash/mihomo 系客户端的 hosts 设置) ==")
    if not best:
        print("  (没有探测到可用 IP: 域名 A 记录本身可能有问题, 或本机网络受限)")
    else:
        print("hosts:")
        for domain in args.domains:
            if domain in best:
                grade, ms, ip, note, _ = best[domain]
                suffix = "" if grade == "OK" else "   # TCP 通(TLS 受本地干扰), 经代理一般可用"
                print(f"  {domain}: {ip}{suffix}")
        print()
        print("  提示: 同域名探到的其它可用 IP 可作为备用; CDN 类 IP 可能随时间变化, 失效后重跑本脚本。")

    if args.proxy:
        print()
        print(f"== 5) 通过代理实测 (--proxy {args.proxy}) ==")
        for domain in args.domains:
            ok, note = proxy_https_check(args.proxy, domain, max(args.timeout, 10.0))
            print(f"  {domain:24s} -> {'通过' if ok else '失败'} ({note})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
