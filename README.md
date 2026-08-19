# OmniX Company Aggregate Skill

面向 OmniX 单一无版本 Market Intelligence OpenAPI 的安全客户端。它在 GETO 本地 ResearchBundle 验证完成、且用户明确同意后，解析强身份并创建或更新完整 Company Aggregate。

业务能力包括 Company list/read/resolve/create/update/patch/soft-delete/restore，具体操作面以运行时 OpenAPI 为准。

配置：

```bash
export OMNIX_API_BASE_URL="https://<your-omnix-host>"
export OMNIX_API_KEY="omx_live_xxx"
```

不要把真实 Key 写入仓库、Prompt、日志、company.json、progress.md 或报告。

验证：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/omnix_market.py capabilities
```

实际 method、path、DTO 和枚举始终以运行时 OpenAPI 为准。
