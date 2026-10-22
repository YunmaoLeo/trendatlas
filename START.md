# 启动 Trend Atlas

## 首次安装

在终端运行：

```bash
cd /Users/lejieliu/Documents/stocks/stocktrend-lab
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 每次启动

```bash
cd /Users/lejieliu/Documents/stocks/stocktrend-lab
.venv/bin/uvicorn stocktrend.api:app --host 127.0.0.1 --port 8001
```

保持终端窗口打开，然后访问 [http://127.0.0.1:8001](http://127.0.0.1:8001)。如果 8001 已被占用，可把命令里的 `8001` 换成其他空闲端口，并访问对应地址。

## 停止

回到运行服务的终端，按 `Ctrl+C`。终端显示服务退出后，页面便无法继续访问。
