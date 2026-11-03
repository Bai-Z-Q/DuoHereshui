# 无卡公网演示：Cloudflare Tunnel / Tailscale Funnel

> 完全不需要信用卡，也不需要云服务器。  
> 代价：**运行项目的电脑必须保持开机联网**，关机或休眠后公网地址失效。

适合“先发给朋友看看”“面试演示”“临时测试”；不适合 24 小时正式服务。

## 方案对比

| 方案 | 账号 | 地址 | 电脑关机 | 适合 |
|---|---|---|---|---|
| Cloudflare Tunnel | 不需要（quick tunnel） | 随机 `*.trycloudflare.com` | ❌ | 最快、最省事 |
| Cloudflare Named Tunnel | 需要 Cloudflare 账号 + 域名 | 自己的域名 | ❌ | 想固定地址 |
| Tailscale Funnel | 需要 Tailscale 账号 | 固定 `*.ts.net` | ❌ | 想固定地址但没域名 |
| ngrok | 需要 ngrok 账号 | 随机地址 | ❌ | 临时 API 调试 |

---

## 一、Cloudflare Tunnel（推荐）

### 1. 启动项目

```powershell
cd "E:\个人医疗管家\backend"
& "E:\个人医疗管家\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

确认本机可访问：

```text
http://127.0.0.1:8000/health
```

### 2. 安装 cloudflared

```powershell
winget install --id Cloudflare.cloudflared
```

安装完重新打开一个 PowerShell 窗口。

### 3. 启动临时隧道

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

终端会输出：

```text
https://random-words-1234.trycloudflare.com
```

这个地址就是公网访问地址。

### 4. 保持运行

- 不要关闭后端窗口；
- 不要关闭 cloudflared 窗口；
- 关闭 Windows 自动睡眠：

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 10
```

恢复默认可用：

```powershell
powercfg /change standby-timeout-ac 15
```

### 5. 固定域名（可选）

需要：

- 一个 Cloudflare 账号；
- 一个自己的域名，并托管到 Cloudflare。

然后：

```powershell
cloudflared tunnel login
cloudflared tunnel create medical-assistant
cloudflared tunnel route dns medical-assistant health.example.com
```

再写 `config.yml`，运行命名隧道。这个方案地址固定，但仍然需要电脑开机。

---

## 二、Tailscale Funnel

### 1. 安装并登录

- 安装 [Tailscale](https://tailscale.com/download)；
- 用 GitHub/Google 登录；
- 执行：

```powershell
tailscale up
```

### 2. 启动 Funnel

```powershell
tailscale funnel 8000
```

会得到类似：

```text
https://your-pc.tailnet-name.ts.net
```

这个地址固定，比 quick tunnel 稳定。

### 3. 停止

```powershell
tailscale funnel --bg=false 8000
```

或直接在 Tailscale 管理台关闭 Funnel。

---

## 三、ngrok（临时备用）

```powershell
ngrok config add-authtoken <你的 token>
ngrok http 8000
```

免费版地址是随机的，首次访问可能有提示页；适合临时调试，不适合长期分享。

---

## 四、安全设置（务必做）

即使是临时演示，也不要把完整后台裸露在公网：

1. **注册开关**
   - 首次部署先允许注册，创建自己的账号；
   - 然后把 `REGISTRATION_ENABLED` 改成 `false`，或修改 `backend/.env` 后重启。

2. **模型配置**
   - 公网演示建议 `ALLOW_LLM_SETTINGS=false`，防止别人改全局 LLM 地址/Key；
   - 模型 Key 只放服务端环境变量。

3. **SECRET_KEY**
   - 不要用默认值；
   - 换成随机长字符串：

```powershell
& ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(48))"
```

4. **CORS**
   - 同源访问不需要 CORS；
   - 不要把 `CORS_ORIGINS` 设成 `"*"`。

5. **数据**
   - 不要放真实健康数据；
   - 不要暴露 PostgreSQL 端口；
   - Tunnel 只转发 8000，不要转发 5432。

6. **停止演示**
   - 关闭 cloudflared / tailscale / ngrok；
   - 关闭后端；
   - 地址立即失效。

---

## 五、限制

- 电脑关机、休眠、断网，地址就不可用；
- 家用宽带上行带宽有限，多人同时用会慢；
- 免费 quick tunnel 每次重启地址会变；
- 没有 SLA，不适合正式医疗业务；
- 如果电脑长期开机不划算，建议改用 Render（绑卡验证）或 Oracle Always Free（也需要绑卡验证）。

## 六、检查清单

- [ ] 后端本机 `/health` 正常
- [ ] cloudflared / tailscale 已启动
- [ ] 公网地址能打开首页
- [ ] 注册账号并关闭注册
- [ ] `ALLOW_LLM_SETTINGS=false`
- [ ] 使用演示数据
- [ ] 不转发数据库端口
- [ ] 知道如何停止隧道
