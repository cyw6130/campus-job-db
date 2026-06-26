# 逆向招聘站列表 API：方法论

核心思路：这些招聘页几乎都是 SPA，列表是前端 POST 一个 JSON 接口拿回来渲染的。直接调那个接口，能一举解决翻页、规模筛选、结构化三件事，而且**完全不碰浏览器**——没有 `chrome.debugger` 冲突，没有分页组件的前端 bug，比 OpenCLI 方案更快更稳。

## 动作链

### 1. 打开页面，抓网络请求

```bash
opencli browser <s> open "<URL>"; sleep 1
opencli browser <s> network    # 列出请求；噪音多，往下筛
```

坑：`network` 从某个时间点起捕获，首屏请求可能漏。漏了就先 `network` 再触发一次新请求（点筛选/翻页/reload）让接口重发。

### 2. 从噪音里认出列表接口

挑**主站自己域名**（不是 `apm-fe`/`spider-tracker`/`*-monitor` 这种第三方监控域名）下、路径含 **list/query/search/page/position/job** 的那条。

### 3. 看响应确认

```bash
opencli browser <s> network --detail "POST <那条的 key>"
```

响应里有 `total/pageNum/pageSize/totalPage` + `list[{结构化字段}]` 就对了。

### 4. 抓真实请求体（关键，别猜参数）

`--detail` 只给响应 body，请求 body 要 hook 出来：

```js
// opencli browser <s> eval "<下面这段>"
window.__cap=[];
const oO=XMLHttpRequest.prototype.open,oS=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open=function(m,u){this.__u=u;return oO.apply(this,arguments)};
XMLHttpRequest.prototype.send=function(b){try{if(String(this.__u).includes('<接口路径关键词>'))window.__cap.push(b)}catch(e){};return oS.apply(this,arguments)};
const of=window.fetch;
window.fetch=function(...a){try{if(String(a[0]).includes('<接口路径关键词>'))window.__cap.push(a[1]&&a[1].body)}catch(e){};return of.apply(this,a)};
'hooked'
```

挂完钩子**触发一次真实查询**（点任意筛选/翻页），再 `eval "JSON.stringify(window.__cap)"` 读出前端真发的 body。外层包装字段（比如某个 `recruitType:"campus"`）是猜不到的，必须这样抓。

### 5. 验证接口是否需要登录态

**很多公开招聘页的列表接口本身不需要任何 cookie**——直接 `curl` 裸调测一下：

```bash
curl -s -X POST "<接口URL>" \
  -H "Content-Type: application/json" \
  -H "Referer: <页面URL>" \
  -H "User-Agent: Mozilla/5.0 ..." \
  -d '<抓到的真实请求体>'
```

如果返回正常数据（不是登录跳转/权限错误），说明可以**完全脱离浏览器**，用纯 `curl`/`urllib` 跑——这是最佳情况，直接用 `scripts/fetch_api_paginated.py`。
如果必须带 cookie/有签名头（`x-sign`/`x-s`/`nonce` 等动态签名），见下面「需要登录态或签名时」。

### 6. 用脚本拉全量

```bash
python3 scripts/fetch_api_paginated.py \
  --url "<接口URL>" --body-template '<真实body，去掉page/size字段>' \
  --page-field pageNum --size-field pageSize --page-size 10 \
  --data-path data.list --total-path data.totalPage --id-field positionId \
  --referer "<页面URL>" --out /tmp/raw.json
```

`--page-size` 别设太大，有些接口设上限会拒绝（实测 `300` 被拒，`50` 稳），不行就调小。

## 需要登录态或签名时

如果接口必须带 cookie 或动态签名头（前端 JS 算出来的，离线伪造不了），就**不能用纯 curl**，要在浏览器页面上下文里发 `fetch`（同源自动带 cookie/签名）：

```js
// opencli browser <s> eval "<下面这段>"
window.__jobs=null;
(async()=>{
  const out=[]; let page=1,tp=1;
  do{
    const r=await fetch('<接口URL>',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({/*照抄真身*/ pageNum:page, pageSize:50})});
    const d=await r.json(); tp=d.data.totalPage; out.push(...d.data.list); page++;
    await new Promise(s=>setTimeout(s,300));   // 礼貌延迟
  }while(page<=tp);
  window.__jobs=out;
})(); 'looping'
```
跑完 `eval "JSON.stringify(window.__jobs)"` 导出，存盘交给后面步骤。这种情况仍然不需要点分页 UI，只是 fetch 调用本身留在浏览器里。

## 接口形态的几种变体

- **REST + 干净 JSON**（最常见）：照抄 body 改页码即可。
- **GraphQL**（单一 `/graphql` 端点）：hook 出真实 body（是个 query 字符串 + variables），改 variables 里的 `page`/`offset`。
- **游标分页**（响应给 `nextCursor` 而非页码）：循环用上一次返回的 cursor 作为下一次请求参数，直到为空。

## 反爬礼貌

循环请求加 200–500ms 延迟，别瞬间打几十页；遇到 429/验证码就退避，不要无限重试。

## 找不到 API 时

完全没有 list 类 XHR（纯服务端渲染，HTML 首屏带全部数据）→ 更简单，直接抓 HTML / 改 URL 参数翻页，不需要这套方法论。
有 XHR 但调不通（强签名、风控）→ 退回 `SKILL.md` 第 2b 步的 OpenCLI DOM 提取。
