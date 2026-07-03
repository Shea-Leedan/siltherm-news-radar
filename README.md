# Siltherm 行业新闻雷达

这是一个本地运行的 Streamlit 网页，用于把行业新闻快速转成外贸销售线索。

## 能做什么

- 输入关键词、新闻链接或新闻正文
- 自动提取摘要
- 自动分类到 EV / ESS / 户储 / AI数据中心 / 电力柜 / 工业热管理
- 给 Siltherm 销售相关性打 1-5 分
- 提取公司、项目、产品线和国家
- 推荐应该联系的岗位
- 生成 LinkedIn 建联话术和英文冷邮件草稿
- 导出 CSV，方便导入飞书多维表格

## 安装依赖

最简单的方法：双击 `打开网页.bat`。它会自动创建本地环境、安装依赖、启动网页并打开浏览器。

网页地址是：

```text
http://localhost:8501
```

这个地址是本地网址，只能在你这台电脑上打开。后续如果要发给同事或客户从外网访问，需要再部署到云端。

也可以手动运行。打开 PowerShell，进入本目录：

```powershell
cd "D:\Codex技能合集\Siltherm行业新闻雷达"
```

安装 Streamlit：

```powershell
python -m pip install -r requirements.txt
```

## 启动网页

```powershell
streamlit run app.py
```

启动后浏览器会打开本地网页。如果没有自动打开，可以访问：

```text
http://localhost:8501
```

## 使用建议

- 关键词模式会读取 Google News RSS，适合做每日新闻扫描。
- 新闻链接模式适合分析单篇新闻；如果网站无法抓取，请复制正文后使用“新闻正文”模式。
- CSV 会使用 UTF-8 BOM 编码，通常可以直接被飞书多维表格正确识别中文。
