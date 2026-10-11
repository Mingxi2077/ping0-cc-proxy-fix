# ping0.cc 走代理打不开？修复指南（Clash / mihomo 系客户端通用）

> **症状**：直连能打开、走代理打不开；报 `ERR_CONNECTION_CLOSED` / 「意外终止了连接」/ 502；
> 或者能打开但**渲染错乱**（样式丢失、页面露出 `{{ }}` 模板占位符）。
>
> **适用**：FlClash、Clash Verge Rev、Clash Meta for Android、Clash for Windows、Mihomo Party 等
> Clash / mihomo 系客户端（Windows / Android / macOS / Linux）。
>
> 本文以 **ping0.cc** 为实例；方法对「某站点被解析到坏 IP」这类问题**通用**。

---

## TL;DR（三件事）

| # | 做什么 | 一句话原理 |
|---|--------|-----------|
| 1 | **固定 hosts**（关键） | 把站点域名固定到实测可用的 IP，跳过出问题的解析环节 |
| 2 | **换 DNS** | 把阿里系 DNS 换成 DNSPod（`doh.pub` / `1.12.12.12`） |
| 3 | **换节点** | 个别节点出口会被目标站拒绝（实测：同一订阅里越南节点不通、香港节点正常） |

---

## 一、问题成因（实测复盘）

排查后发现是**多个因素叠加**，任何一个单独存在都可能让站点"时好时坏"：

1. **DNS 返回坏 IP**
   部分公共 DNS（实测阿里 `223.5.5.5` / `dns.alidns.com`）曾对 ping0.cc 返回**已失效的 IP**
   （`141.193.154.146`、`45.67.223.32`）。同一时间 DNSPod、114、Google、韩国 KT 都返回正确 IP
   （`104.218.235.243`）。且阿里 DNS 当时对部分其它域名（google / youtube / discord）也在返回明显错误的结果。

2. **双栈死记录（IPv6 陷阱）**
   站点发布了 AAAA 记录（`2604:9cc0:1c0e::a`），但该 IPv6 端点**不可用**；
   而多数代理链路没有可用 IPv6。解析一旦走到 v6 一侧就死路。

3. **节点侧解析（关键机制）**
   mihomo 在 `fake-ip` 模式下会把**域名原样交给代理节点解析**（SS 等协议传域名）。
   节点侧解析到坏 IP、或该节点出口被目标站拒绝 → 连接失败。
   证据：同一域名「**强制 IP 走节点 = 成功**，域名走节点 = 失败」。

4. **子域名全部中招 → 渲染错乱**
   站点的 JS/CSS/图片全在子域（cdn / map / ip.ping0.cc）上，同样连不上：
   `vue.min.js` 等资源加载失败 → 页面模板占位符裸露、样式全丢。

---

## 二、修复步骤

### 2.1 固定 hosts（关键，所有客户端通用）

本次实测可用的 IP（2026-10-11 验证）：

```yaml
hosts:
  ping0.cc: 104.218.235.243
  www.ping0.cc: 104.218.235.243
  cdn.ping0.cc: 172.67.188.46
  map.ping0.cc: 172.67.188.46
  ip.ping0.cc: 104.218.235.243
```

各客户端入口：

- **FlClash（Windows / Android）**：工具 → 基本配置 → Hosts → 添加
- **Clash Verge Rev**：设置 → Hosts（或通过订阅覆写 / 扩展脚本追加）
- **Clash Meta for Android / Clash for Android**：设置 → 覆写 → Hosts（不同版本入口名略有差异）
- **直接编辑生成配置**：在 `config.yaml` 的 `hosts:` 段加同名键值 —— 注意应用重建配置时可能被覆盖，
  优先使用客户端自带的 hosts 设置界面

写入后**重启核心**（FlClash：停止 → 启动；或重开应用）。

> 为什么固定 hosts 有效？hosts 命中后，客户端在拨号前就把**真实 IP**（而不是域名）发给节点，
> 相当于跳过了「本地解析」和「节点侧解析」两个环节，问题 1/2/3 一并绕开。

### 2.2 换 DNS（治本泛化，建议做）

把 `nameserver` 里的阿里 DoH 换掉：

```yaml
dns:
  nameserver:
    - https://doh.pub/dns-query
    - https://1.12.12.12/dns-query
```

- **FlClash**：工具 → 进阶配置 → DNS → 打开「覆写DNS」→ 修改「域名服务器」
- **Clash Verge Rev**：设置 → DNS → 覆写
- 顺手把 `fallback`（如果有 `tls://8.8.4.4` 这类）清空，避免回退探测引入干扰

### 2.3 换节点（还有问题就做）

先做延迟测试，再实际打开一次目标站；不通就换节点。

本次实测：**越南节点不通、香港节点正常**（同一订阅内）。这说明"节点出口 IP 会被目标站区别对待"，
不是订阅坏了。

---

## 三、自己诊断同类问题（命令 + 判读）

```bash
# 1) 直连 vs 代理 对照（最关键的一步）
curl -sS --noproxy '*' -o /dev/null -w 'direct: %{http_code} %{time_total}s\n' https://ping0.cc/
curl -sS -x http://127.0.0.1:7890 -o /dev/null -w 'proxy : %{http_code} %{time_total}s\n' https://ping0.cc/

# 2) 强制指定 IP（绕过"解析"环节，直接把 IP 交给节点连接）
curl -sS -x http://127.0.0.1:7890 --connect-to ping0.cc:443:104.218.235.243:443 \
     -o /dev/null -w 'force-ip: %{http_code} %{time_total}s\n' https://ping0.cc/

# 3) 多 DNS 对照（看是否有人返回坏记录）
nslookup ping0.cc 223.5.5.5
nslookup ping0.cc 119.29.29.29
curl -s 'https://doh.pub/dns-query?name=ping0.cc&type=A' -H 'accept: application/dns-json'
```

**结果判读表**：

| 直连 | 强制 IP 走代理 | 域名走代理 | 结论 |
|------|--------------|-----------|------|
| ✅ | ✅ | ❌ | **解析问题** → 用 hosts 固定 IP（本指南主要场景） |
| ✅ | ❌ | ❌ | **节点出口问题** → 换节点 |
| ❌ | — | — | 站点故障或本机网络问题 → 换网络 / 等站点恢复 |

> 浏览器里还可以打开 F12 → Network，看**失败资源集中在哪个域名**（如 `cdn.ping0.cc` 全红），
> 一目了然定位是主域还是 CDN 子域的问题。

---

## 四、自动化脚本

### `scripts/find_working_ip.py` — 探测可用 IP（跨平台，纯标准库）

```bash
# 探测域名，输出可直接粘贴的 hosts 片段
python scripts/find_working_ip.py ping0.cc www.ping0.cc cdn.ping0.cc

# 常用参数
python scripts/find_working_ip.py --doh https://doh.pub/dns-query https://dns.google/resolve example.com
python scripts/find_working_ip.py --proxy http://127.0.0.1:7890 ping0.cc   # 顺手做一次代理实测
```

它会：多解析器查询 → 直连 TCP+TLS 探测每个候选 IP → 输出可用 IP 和 hosts 片段。

### `scripts/patch_flclash_windows.py` — 一键写入 FlClash（Windows）

```bash
# 先完全退出 FlClash（含托盘），然后：
python scripts/patch_flclash_windows.py ping0.cc=104.218.235.243 cdn.ping0.cc=172.67.188.46

# 其它用法
python scripts/patch_flclash_windows.py --show                        # 查看当前 hosts
python scripts/patch_flclash_windows.py --file hosts.txt              # 从文件批量导入
python scripts/patch_flclash_windows.py --remove ping0.cc             # 删除某条
python scripts/patch_flclash_windows.py --dry-run ...                 # 只预览不写入
```

特性：自动定位 `%APPDATA%\com.follow\clash\shared_preferences.json`、自动备份、检测 FlClash 是否在运行。
写完重新打开 FlClash 启动核心即可。

### 自动化可行性结论

| 环节 | 可行性 | 说明 |
|------|--------|------|
| 探测可用 IP | ✅ 全自动 | 跨平台脚本（本节附） |
| 写入 FlClash 配置 | ✅ 自动（Windows） | 需先退出 FlClash；脚本自动备份 |
| 安卓端写入 | ⚠️ 半自动 | 应用私有目录无 root 不可写；走「备份→PC 改→恢复」或 UI 手动添加，几步点击 |
| 更换节点 | ❌ 建议手动 | 哪个节点可用与出口 IP 强相关，需实际测试 |
| 长期免维护 | ❌ | 站点换 IP 后需重新探测更新 hosts（脚本重跑一次即可） |

---

## 五、FAQ

**Q1：为什么 hosts 不写系统 hosts 文件？**
系统 hosts 只对"直连"的程序生效；走代理时域名交给客户端 / 节点解析，系统 hosts 不参与。
所以要在**客户端**里做 hosts（本指南方案）。除非你不走代理直连，那系统 hosts 才有用。

**Q2：hosts 会被订阅更新覆盖吗？**
不会。hosts 存在客户端全局配置层，与订阅 profile 无关。

**Q3：站点换了服务器 IP 之后呢？**
重跑 `find_working_ip.py`，把新的可用 IP 更新进去（1 分钟）。

**Q4：为什么不干脆让整个站走直连（绕过代理）？**
也是一种办法，但：① 直连时该站解析可能同样抽风；② 部分网络环境直连该站很慢。
hosts 固定 + 走代理更稳。而且"按域名加直连规则"只解决主域，**子域（CDN）不走直连照样渲染坏**，
不如 hosts 一次性处理干净。

**Q5：对其它安卓设备 / PC 有效吗？**
有效，条件相同：**装了 Clash / mihomo 系客户端**。修的是客户端内的配置，与系统无关。
非 Clash 系客户端（v2rayN 等）大多没有 hosts 直通能力，需要系统级 hosts + 直连，或换客户端。

**Q6：为什么有的节点行、有的不行？**
节点出口 IP 被目标站 / 中间设备区别对待（风控、机房段封禁等）。
先延迟测试，再实际访问验证。

---

## 附录：本次排查的关键证据（节选）

- **多 DNS 对照**（2026-10-11）：阿里 DNS 返回 `141.193.154.146`（死地址）；
  DNSPod / 114 / Google / 韩国 KT 返回 `104.218.235.243`（可用）。
- **强制 IP 对照**：`--connect-to ping0.cc:443:104.218.235.243` 经代理 = 200；
  域名方式经代理 = TLS 握手失败。→ 实锤"解析/节点侧解析"环节有问题。
- **节点对照**：越南节点访问该站失败，香港节点成功（同订阅、同时间）。
- **页面资源统计**：修复前 `cdn.ping0.cc` 的 76 个资源 100% 失败（含 vue.min.js / 全部 CSS），
  修复后全部 200，页面完整渲染。

---

## 免责声明

- 本项目为网络故障排查经验分享，所有 IP 为个人实测记录，**可能随时失效**，请以实测为准。
- 请在遵守当地法律法规的前提下使用网络工具。
- 不同客户端版本界面可能有差异，路径以官方文档为准。

## License

MIT
