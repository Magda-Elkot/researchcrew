# Local model files

Large model files live here **locally only**: everything in this folder except this README is
git-ignored (and excluded from Docker builds via `.dockerignore`). Never commit model weights:
GitHub rejects files over 100 MB.

| Folder | What | Source | Size |
|---|---|---|---|
| `bge-m3-onnx/` | BAAI/bge-m3 exported to ONNX (fp32, `XLMRobertaModel`; inputs `input_ids`, `attention_mask`; output `embeddings` [batch, 1024], already pooled) + tokenizer | Copied 2026-11-13 from the owner's SmartSearch2 project (`smartsearch/model/bge-m3-onnx`) | 2.2 GB |

**Not used by docs-mcp** (DECISIONS #43). Tested 2026-11-13 against the PyTorch vectors in Qdrant:
37% slower (weights exported as graph inputs, so ONNX Runtime can't optimise) and different vectors
(cosine 0.60–0.67; the export has its own pooling, not bge-m3's CLS pooling). docs-mcp keeps
`BAAI/bge-m3` via sentence-transformers. A correct export (CLS pooling, constant weights, maybe
int8) is an optional Phase 7 item.
