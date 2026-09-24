# 微专业就业成效追踪系统

维护毕业生、学院、微专业、就业去向、企业跟进和预警记录，支持按届次与组织维度追踪就业成效并保留分析依据。

## 运行约定

服务端代码位于 `app` 目录，默认使用项目目录中的 SQLite 文件。配置通过环境变量提供，导入演示数据前请确认数据库位置可写。

## 测试

在项目根目录执行：

```bash
python3 -m unittest discover -s tests -v
```

## 编译检查

在项目根目录执行：

```bash
python3 -m compileall -q app tests
```

## 启动服务

准备依赖后可执行 `uvicorn main:app --host 127.0.0.1 --port 8000`，根路径与 `/health` 返回服务状态，接口文档位于 `/docs`。
