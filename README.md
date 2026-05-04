# TeoHeberg 广告任务自动化

> 动动小手点点 Star ⭐

基于 **Cloudflare Workers** 部署的 **TeoHeberg 每日广告任务**自动化脚本，自动完成 Linkvertise 广告、追踪积分变化，并通过 Telegram 推送通知。

---

## ✨ 最新优化

- ⚡ **降低子请求消耗**：单次最多执行 3 轮广告，定时任务每次只处理 1 个可执行账号，避免触发 Cloudflare Workers 免费计划限制  
- 🧠 **智能冷却机制**：  
  - 广告成功后冷却 24.5 小时  
  - 当一个账号额度用完时，设置短期冷却2小时，但之后广告成功，则切换到24.5小时冷却。（避免频繁无效请求）  
- 📊 **积分估算**：直接通过前后积分差值计算完成广告数，无需额外页面解析  
- 🖥️ **前端增强**：管理面板显示冷却状态、剩余冷却时间，自动禁用冷却中账号的执行按钮  

---

## 📌 功能说明

- ✅ 自动完成每日广告任务  
- ✅ 多账号管理，支持批量导入  
- ✅ 积分提取，Telegram 通知展示积分变化  
- ✅ 支持手动触发（网页管理面板 / API）  
- ✅ 支持定时 Cron 触发（建议每 5 分钟）  
- ✅ 前端界面支持账号增删、Cookie 手动更新、单账号执行、强制执行  
- ✅ 完整 API 接口，可集成到其他自动化流程  

---

## ⚠️ 注意事项

> ❗ 依赖已登录的 Cookie，**不提供自动登录功能**，需手动获取长期有效的 `remember_web`。  
> ❗ 登录时务必勾选 **Se souvenir de moi**（记住我），以获取长期 Cookie。  

---

## 📝 注册地址

👉 [https://manager.teoheberg.fr/](https://manager.teoheberg.fr/)

---

## 🚀 部署方式

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)，进入 Workers 页面  
2. 创建一个新的 Worker，将 [worker.js](./worker.js) 代码粘贴进去  
3. 创建 **KV 命名空间**（名称随意），在 Worker 设置中绑定变量名为 `TEOHEBERG_KV`  
4. 配置环境变量（见下表）  
5. 部署 Worker  

---

## 🔧 环境变量配置

| 变量名 | 说明 | 是否必须 |
|--------|------|----------|
| `AUTH_KEY` | 访问密钥，保护 API 和管理面板 | ✅ 是 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 否（不填则不通知） |
| `TELEGRAM_CHAT_ID` | 接收通知的 Chat ID | 否 |

### ⚙️ KV 绑定

在 Worker 设置 → Variables → KV Namespace Bindings 中添加：

| 变量名 | KV 命名空间 |
|--------|------------|
| `TEOHEBERG_KV` | 你创建的 KV |

---

## 📄 账号添加格式

在管理面板的文本框中，按以下格式输入（每行一个账号）：

```
邮箱或备注-----remember_web_xxx=...
```

**示例**：

```
admin@gmail.com-----remember_web_59ba3xxx89d=eyJpdiI6xxxiIn0%3D
大号-----remember_web_59ba3xxx89d=eyJpdiI6xxxiIn0%3D
```

多个账号可以一次粘贴多行，系统会自动解析。

---

## 🔍 如何获取 Cookie？

### 第 1 步：打开浏览器，先不要输入网址  
### 第 2 步：按 F12 打开开发者工具  
- 按键盘 **F12**（笔记本可能需要 `Fn + F12`）  
- 或者右键页面空白处 → “检查”  
- 你会看到屏幕右侧或下方出现一个调试面板，包含 Elements、Console、Network 等标签  

### 第 3 步：在地址栏输入网站  
- 输入 `https://manager.teoheberg.fr` 并回车，让页面加载  

### 第 4 步：登录账号（必须勾选“记住我”）  
- 输入邮箱和密码  
- **⚠️ 最重要的一步**：勾选 `Se souvenir de moi`（法语“记住我”）  
- 点击登录按钮  

### 第 5 步：找到 login 请求并提取 Cookie  
- 回到 F12 调试面板，点击 **Network** 标签  
- 如果登录后才打开 Network，里面可能是空的 → 按 **F5** 刷新页面  
- 在 Network 列表中找到名为 **login** 的请求（通常排在前面），点击它  
- 右侧弹出详细窗口，找到 **Request Headers** → 向下翻，找到 `Cookie:` 这一行  
- **只复制以 `remember_web_` 开头的部分**，例如：  

  ```
  remember_web_59ba3xxx89d=eyJpdiI6xxxiIn0%3D
  ```

### 第 6 步：保存成指定格式  

```
你的邮箱-----remember_web_59ba3xxx89d=eyJpdiI6xxxiIn0%3D
```

中间是 **5 个减号**。

> 📌 图片参考：![Cookie格式](img/Cookie.png)
> 📌 图片参考：![Cookie格式](img/Cookie2.png)

---

## ⏰ 定时任务（Cron）

在 Worker 的 **Triggers** 中添加 Cron 触发器，**建议每 5 分钟执行一次**，例如：

```
*/5 * * * *
```

> 含义：每隔 30 分钟自动触发一次，脚本会自动检测冷却状态，只处理可执行的账号（最多 1 个/次），完全安全且不会浪费子请求。

---

## 🌐 使用方式

### 1️⃣ 浏览器管理面板

直接访问 Worker 域名，输入 `AUTH_KEY` 即可进入管理界面：

```
https://你的域名
```

**功能包括**：
- 📊 查看账号列表、可执行账号数量和冷却状态  
- ✏️ 批量添加账号  
- 🗑️ 删除账号  
- ▶️ 手动执行单个账号（忽略冷却）  
- 🔄 手动执行所有可用账号（跳过冷却中的）  
- 🍪 弹窗手动更新 Cookie  

### 2️⃣ API 触发单个账号

```bash
curl "https://你的域名/run?email=admin@example.com&key=你的AUTH_KEY&force=true"
```
> 添加 `force=true` 可强制忽略冷却，立即执行。

### 3️⃣ API 触发所有账号

```bash
curl "https://你的域名/run-all?key=你的AUTH_KEY"
```
> 自动跳过冷却中的账号，每次只处理一个。

### 4️⃣ 查看账号列表

```bash
curl "https://你的域名/accounts?key=你的AUTH_KEY"
```

---

## 📸 效果展示

### 🔔 Telegram 通知效果

**任务完成时**：

```
✅ 广告任务已完成

账号：admin@example.com
积分：0,00 -> 6,00
广告：完成 3 次
下次执行：2026/5/5 12:30:00

TeoHeberg Daily Points
```

**额度用完时**：

```
⏳ 冷却中

账号：admin@example.com
积分：6,00
广告：今日额度已用完

TeoHeberg Daily Points
```

**Cookie 失效时**：

```
🚨 Cookie 已失效

账号：admin@example.com
状态：remember_web 已失效，需要手动更新
⚠️ 请尽快手动更新长期 Cookie

TeoHeberg Daily Points
```

---

## 💬 Telegram 通知说明

配置 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 后：

- ✅ 每次任务执行完毕自动推送积分变化  
- ✅ 额度已用完时提示冷却（并显示下次可执行时间）  
- ❌ 遇到 Cookie 失效、网络错误等会推送错误信息  

---

## ❤️ 支持项目

如果这个项目对你有帮助：  
👉 点个 **Star ⭐** 支持一下吧！

---

## ⚠️ 免责声明

本脚本仅供学习交流使用，使用者需遵守 TeoHeberg 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。
