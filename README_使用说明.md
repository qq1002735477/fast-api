# 短链接服务 API 使用说明

## 一、什么是这个项目？

这是一个**短链接服务的后端 API**，可以把长网址变成短网址，并统计点击数据。

## 二、如何使用？

### 方式1：使用 API 测试工具（推荐新手）

下载 **Apifox** 或 **Postman**，导入 API 文档进行测试。

1. 访问 http://127.0.0.1:8000/api/schema/ 下载 OpenAPI 规范文件
2. 在 Apifox/Postman 中导入这个文件
3. 就可以看到所有接口并测试了

### 方式2：使用命令行 curl

### 方式3：写一个前端网页调用这些 API

---

## 三、API 使用流程

### 第1步：注册用户

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "email": "test@example.com", "password": "Test123456"}'
```

返回示例：
```json
{
  "id": 1,
  "username": "testuser",
  "email": "test@example.com",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

### 第2步：登录获取 Token

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "Test123456"}'
```

返回的 `access` 就是你的令牌，后续请求都要带上它。

### 第3步：创建短链接

```bash
curl -X POST http://127.0.0.1:8000/api/links/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的access令牌" \
  -d '{"original_url": "https://www.baidu.com/s?wd=hello+world"}'
```

返回示例：
```json
{
  "id": 1,
  "short_code": "abc123",
  "original_url": "https://www.baidu.com/s?wd=hello+world",
  "short_url": "http://127.0.0.1:8000/r/abc123",
  "click_count": 0,
  "created_at": "2026-01-15T15:30:00Z"
}
```

### 第4步：使用短链接

直接在浏览器访问：**http://127.0.0.1:8000/r/abc123**

会自动跳转到原始的百度搜索页面！

### 第5步：查看统计数据

```bash
curl -X GET http://127.0.0.1:8000/api/links/abc123/stats/ \
  -H "Authorization: Bearer 你的access令牌"
```

---

## 四、所有 API 接口一览

| 功能 | 方法 | 地址 | 需要登录 |
|------|------|------|----------|
| 注册 | POST | /api/auth/register/ | ❌ |
| 登录 | POST | /api/auth/login/ | ❌ |
| 刷新令牌 | POST | /api/auth/token/refresh/ | ❌ |
| 创建短链接 | POST | /api/links/ | ✅ |
| 获取我的短链接列表 | GET | /api/links/ | ✅ |
| 获取单个短链接 | GET | /api/links/{short_code}/ | ✅ |
| 删除短链接 | DELETE | /api/links/{short_code}/ | ✅ |
| 查看统计 | GET | /api/links/{short_code}/stats/ | ✅ |
| 批量创建 | POST | /api/links/batch/ | ✅ |
| 创建分组 | POST | /api/groups/ | ✅ |
| 创建标签 | POST | /api/tags/ | ✅ |
| 短链接跳转 | GET | /r/{short_code} | ❌ |

---

## 五、想要网页界面？

这个项目只是后端 API，如果你想要网页界面，有两个选择：

### 选择1：使用 Django Admin 后台（已有）

访问 http://127.0.0.1:8000/admin/
- 用户名：admin
- 密码：admin123

可以在这里管理用户、查看链接数据。

### 选择2：自己写一个前端

用 Vue.js 或 React 写一个网页，调用这些 API。

前端代码示例（JavaScript）：
```javascript
// 登录
const response = await fetch('http://127.0.0.1:8000/api/auth/login/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'testuser', password: 'Test123456' })
});
const data = await response.json();
const token = data.access;

// 创建短链接
const linkResponse = await fetch('http://127.0.0.1:8000/api/links/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({ original_url: 'https://www.example.com/very/long/url' })
});
const linkData = await linkResponse.json();
console.log('短链接:', linkData.short_url);
```

---

## 六、启动服务

每次使用前需要启动：

1. **启动 Memurai (Redis)**：确保 Memurai 服务在运行

2. **启动 Django 服务器**：
```cmd
python manage.py runserver
```

3. **启动 Celery（可选，用于异步任务）**：
```cmd
celery -A urlshortener worker -l info -P solo
```

---

## 七、常见问题

**Q: 为什么请求返回 401？**
A: 你没有登录或令牌过期了，需要重新登录获取新的 access 令牌。

**Q: 为什么请求返回 429？**
A: 请求太频繁了，等一分钟再试。

**Q: 短链接跳转不了？**
A: 确保 Django 服务器在运行，访问地址是 http://127.0.0.1:8000/r/短码
