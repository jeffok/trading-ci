# Schema 验证问题修复说明

## 问题描述

执行服务在处理 trade_plan 时出现错误：
```
Unresolvable: https://schemas.local/common/event-envelope.json
```

这是因为 JSON Schema 验证器尝试从网络获取 schema 文件，但 `schemas.local` 域名无法解析。

## 修复方案

已修复 `libs/mq/schema_validator.py`，使其能够：
1. 加载所有本地 schema 文件到内存
2. 创建自定义 RefResolver，将所有 `https://schemas.local/` 的引用映射到本地文件
3. 避免网络请求，完全使用本地 schema 文件

## 验证修复

修复后，需要重启执行服务：

```bash
# 重启执行服务
docker compose restart execution

# 查看日志确认没有 schema 错误
docker compose logs -f execution

# 重新测试
python scripts/e2e_smoke_test.py --inject-trade-plan --wait-seconds 20
```

## 如果仍有问题

如果修复后仍有问题，可以尝试：

1. **清除 Python 缓存**：
   ```bash
   find . -type d -name __pycache__ -exec rm -r {} +
   find . -type f -name "*.pyc" -delete
   ```

2. **重新构建 Docker 镜像**：
   ```bash
   docker compose build --no-cache execution
   docker compose up -d execution
   ```

3. **检查 schema 文件**：
   ```bash
   # 确保所有 schema 文件存在
   ls -la libs/schemas/common/
   ls -la libs/schemas/streams/
   ```
