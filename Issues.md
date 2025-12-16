# Phase 27/27.5 遗留问题清单

**日期**: 2025-12-16
**状态**: 记录中

---

## 🟡 中优先级

### 1. PQC 输入校验不足

**位置**: `src/server/mp2_e2ee.c:263`

**现状**: 服务端仅校验 PQC 公钥长度 (1184 字节)，未校验 ML-KEM-768 格式有效性。

**风险**: 恶意客户端可上传格式无效的垃圾数据，服务端无法检测。

**建议修复**:
```c
// 添加基础格式校验（检查前几个字节的结构）
// 或使用 liboqs 的 OQS_KEM_keypair() 进行解封装测试
```

**优先级**: 中 - 不影响正常功能，但影响安全性

---

### 2. PQC 私钥解密未实现

**位置**: `src/ming_drlms/core/e2ee_runtime.py:288-298`

**现状**: 混合加密 (`hybrid_encrypt`) 已实现，但解密路径需要 `_my_pqc_kem` 实例，当前仅记录警告。

**原因**: PQC 私钥需要从 `LocalKeyStore` 加载并导入到 `MLKEM768` 实例，但此逻辑未完成。

**建议修复**:
```python
# 在 E2EEngine.__init__() 中加载 PQC 私钥
pqc_priv = getattr(self._state, "pqc_private_key", None)
if pqc_priv:
    self._my_pqc_kem = MLKEM768()
    self._my_pqc_kem.import_secret_key(pqc_priv)
```

**优先级**: 中 - 混合加密已工作，解密路径待完善

---

## 🟢 低优先级

### 3. Schema 迁移机制

**位置**: `src/server/sqlite_schema.c:252-254`

**现状**: 使用 `PRAGMA table_info()` 检测列是否存在。

**建议**: 升级为 `PRAGMA user_version` 版本管理，更清晰的迁移历史。

**优先级**: 低 - 当前机制功能正常

---

### 4. 30 个 TUI 测试失败

**位置**: `tests/python/test_tui_*.py`

**现状**: 与 Phase 27 无关的 TUI 测试失败。

**建议**: 单独排查 TUI 测试问题。

**优先级**: 低 - 不影响 Phase 27 功能

---

## ✅ 已解决

### 5. liboqs 版本不兼容

**原状态**: vcpkg liboqs 0.12 与 liboqs-python 0.14 不兼容

**解决方案**: 使用 `scripts/install_liboqs.ps1` 手动构建 liboqs 0.15.0

**当前状态**: ✅ 已解决

---

## 环境变量更新

以下内容需要手动添加到 `.env.local`:

```bash
# =============================================================================
# Phase 27: liboqs 安装目录 (必需)
# =============================================================================
LIBOQS_DIR=D:\dogepy\pythonProject1\schoolworks\DRLMS\build_win\_deps\liboqs-install

# =============================================================================
# Phase 27: BIP39 助记词身份 (可选)
# =============================================================================
# DRLMS_MNEMONIC=abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
# DRLMS_MNEMONIC_PASSPHRASE=
```

---

## 参考文档

- [Phase27.md](./Phase27.md) - 完整 Phase 27 技术文档
- [Phase26-28_Roadmap.md](./Phase26-28_Roadmap.md) - 路线图
- [liboqs-install.mdx](./docs/zh/guides/liboqs-install.mdx) - liboqs 安装指南
