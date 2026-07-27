# Complex Sample Corpus

这组文件用于本地验证数据清洗、质量过滤、metadata、父子 chunk 和检索展示。

建议测试问题：

- 哪些样例包含 OCR 噪声？
- 合同付款条件是什么？
- 客服记录里有哪些退款问题？
- 产品手册如何描述安装步骤？
- 网页导出文件的主要公告是什么？

文件说明：

- `contract_terms.md`：章节型合同文本，适合验证父子 chunk 和标题路径。
- `customer_cases.csv`：客服记录，适合验证 CSV 行级 metadata。
- `nested_records.jsonl`：嵌套 JSONL，适合验证 `data.body` 字段读取。
- `ocr_noise_sample.txt`：模拟扫描 OCR 噪声和重复行。
- `web_export.html`：模拟网页导出，适合验证 HTML 清洗。
