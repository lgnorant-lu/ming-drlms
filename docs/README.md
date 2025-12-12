# DRLMS 文档站点

DRLMS (Distributed Real-time Log Monitoring System) 官方文档，使用 Mintlify 构建。

## 本地开发

### 安装 Mintlify CLI

```bash
npm i -g mintlify
```

### 启动开发服务器

```bash
cd docs
mintlify dev
```

访问 http://localhost:3000 查看文档。

## 目录结构

```
docs/
├── docs.json           # Mintlify 配置文件
├── zh/                 # 中文文档（默认语言）
│   ├── index.mdx       # 首页
│   ├── quickstart.mdx  # 快速开始
│   ├── installation.mdx
│   ├── setup/          # 环境配置
│   ├── guides/         # 用户指南
│   ├── architecture/   # 架构设计
│   ├── cli-reference/  # CLI 参考
│   ├── api-reference/  # API 参考
│   ├── security/       # 安全文档
│   ├── operations/     # 运维文档
│   ├── development/    # 开发文档
│   └── changelog/      # 更新日志
└── en/                 # 英文文档（待完善）
```

## 主题

采用星露谷风格主题：
- Primary: #5C9E31
- Light: #8BC34A
- Dark: #33691E

## 相关链接

- [DRLMS GitHub](https://github.com/lgnorant-lu/ming-drlms)
- [Mintlify 文档](https://mintlify.com/docs)
