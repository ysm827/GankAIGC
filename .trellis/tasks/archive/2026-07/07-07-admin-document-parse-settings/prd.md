# 后台文档解析设置与 TXT 上传支持

## Goal

让管理员能在后台直接配置文档解析/MinerU 相关参数，并让用户上传 PDF、Word(.docx)、Markdown(.md/.markdown)、TXT 时得到清晰、稳定的解析体验。

## Confirmed Facts

- 当前后台已有「系统配置」页，前端组件为 `package/frontend/src/components/ConfigManager.jsx`，后端接口为 `GET/POST /api/admin/config`。
- 当前上传白名单为 `.docx`, `.pdf`, `.md`, `.markdown`，未开放 `.txt`。
- 当前 GankAIGC 只把 MinerU 接入为 PDF 高精度解析器；DOCX 使用 `python-docx`，失败回退 MarkItDown；Markdown 本地解析。
- MinerU 官方 README 宣称支持 PDF、DOCX、PPTX、XLSX、图片、网页，但本次按推荐不扩展 DOCX/PPTX/XLSX/图片/网页到 MinerU。
- 用户选择推荐方案：PDF 继续用 MinerU/MarkItDown，DOCX/MD/TXT 本地解析，`.doc` 暂不支持并提示转 `.docx`。

## Requirements

1. 后台管理 → 系统配置新增「文档解析设置」卡片。
2. 文档解析设置必须说明：MinerU 当前主要用于 PDF；Word(.docx)、Markdown、TXT 使用本地解析链路，不消耗 MinerU 额度。
3. 后台可查看/保存以下配置：
   - `PDF_STRUCTURE_ENGINE`：`mineru` / `markitdown`
   - `MINERU_BASE_URL`
   - `MINERU_API_TOKEN`（保存后脱敏，只显示后四位；留空不覆盖旧 token）
   - `MINERU_MODEL_VERSION`
   - `MINERU_ENABLE_FORMULA`
   - `MINERU_ENABLE_TABLE`
   - `MINERU_IS_OCR`
   - `MINERU_LANGUAGE`
   - `MINERU_TIMEOUT_SECONDS`
   - `MINERU_POLL_INTERVAL_SECONDS`
4. 上传解析新增 `.txt` 支持。
5. TXT 使用本地纯文本解析，不走 MinerU。
6. `.doc` 仍不支持；错误提示要明确要求另存为 `.docx`。
7. 前端上传提示和文件选择范围更新为 PDF、Word(.docx)、Markdown(.md/.markdown)、TXT。
8. 不新增 MinerU 连接测试按钮，不新增 DOCX 走 MinerU 的开关。

## Acceptance Criteria

- [ ] 管理员打开后台「系统配置」能看到「文档解析设置」卡片。
- [ ] `GET /api/admin/config` 返回 `document_parse` 摘要，包含 MinerU token 是否已设置和后四位。
- [ ] `POST /api/admin/config` 能保存文档解析配置；`MINERU_API_TOKEN` 留空不会清空旧 token。
- [ ] 保存 `PDF_STRUCTURE_ENGINE=mineru` 或 `markitdown` 后，后端运行时配置能热更新。
- [ ] 上传 `.txt` 文件能解析成正文文本，返回 `document_format="txt"`、`parse_engine="plain_text"`。
- [ ] 上传 `.doc` 返回明确错误：暂不支持老版 Word(.doc)，请另存为 .docx 后上传。
- [ ] 前端上传提示包含 `PDF、Word(.docx)、Markdown(.md/.markdown)、TXT`。
- [ ] 原有 PDF MinerU、PDF MarkItDown、DOCX、Markdown 路径不回退。
- [ ] 前端构建成功并同步 `package/static`。

## Out of Scope

- DOCX 默认走 MinerU。
- `.doc` 自动转换 `.docx`。
- PPTX/XLSX/图片/网页上传解析。
- MinerU 测试 PDF 上传工具。
