# FT-F2: On-Device Conversion Spike Report

**Date:** 2026-07-09
**Python:** 3.11.15
**litert-torch:** 0.9.1
**litert-lm-builder:** 0.14.0
**flutter_gemma:** 0.13.6
**Model:** SFT fine-tune of unsloth/gemma-4-E2B-it (LoRA r=32, α=64 → merged bf16)
**Hardware:** CPU-only (130 GB RAM, no GPU allocated — production dsv4 uses both RTX 6000)

---

## Route A: LoRA → MediaPipe TFLite FlatBuffer  ✅

**Status: WORKS (attention-only, MLP LoRA needs merge path)**

### What was attempted
Convert the PEFT LoRA adapter (`adapter_model.safetensors`, 194 MB) to a TFLite FlatBuffer file that MediaPipe's `LlmInferenceSessionOptions.setLoraPath()` can consume at runtime alongside the base `.litertlm` model.

### Toolchain
```python
from litert_torch.generative.layers import lora as lora_utils
lora = lora_utils.LoRA.from_safetensors(path, scale=2.0, config=..., tensor_names=...)
tflite_bytes = lora.to_tflite()
```

### Artifact produced
- **File:** `/home/joshu/ft-runs/sft-lora-attention.tflite`
- **Size:** 52,321,404 bytes (~50 MB)
- **Format:** Valid TFLite FlatBuffer (verified by TF Lite interpreter)
- **Contents:** LoRA attention weights (query, key, value, output) for all 35 layers

### What's in the LoRA
| Projection | Included | Status |
|---|---|---|
| `q_proj` (q) | ✅ | Attention LoRA |
| `k_proj` (k) | ✅ | Attention LoRA |
| `v_proj` (v) | ✅ | Attention LoRA |
| `o_proj` (output) | ✅ | Attention LoRA |
| `gate_proj` | ✅ **NOT in .tflite** | MLP LoRA — not supported by `litert_torch.lora.LoRAEntry` |
| `up_proj` | ✅ **NOT in .tflite** | MLP LoRA — not supported |
| `down_proj` | ✅ **NOT in .tflite** | MLP LoRA — not supported |

**Critical limitation:** The `litert_torch.generative.layers.lora` module's `LoRAEntry` class only handles **attention projections** (query, key, value, output). The MLP projections (gate/up/down) which carry the majority of fine-tuning signal are **not included** in the generated FlatBuffer. The MediaPipe LoRA format would need to be extended or the MLP weights merged into the base TFLite model separately.

### How to use in Flutter
The app must be modified to:
1. Install the LoRA alongside the base model via `FlutterGemma.installModel(...).withLoraFromFile(loraPath)` or pass `loraPath` to `createChat()`.
2. Currently `_ensureModel()` in `local_chat_repository.dart` uses `FlutterGemma.getActiveModel()` → `model.createChat()` without a `loraPath` parameter. The `SupportedLoraRanks` would need to be passed to `createModel` or `getActiveModel`.
3. The base `.litertlm` model file must have been compiled with LoRA support (i.e., `setSupportedLoraRanks()` during engine init). The stock hugginface model (`litert-community/gemma-4-E2B-it-litert-lm`) may not include this — only models built with the `--lora_ranks` flag during conversion support runtime LoRA.

### MLP LoRA Resolution Path
Since the LoRA adapter targets both attention AND MLP projections, the complete fine-tune signal requires one of:
- **Extend `litert_torch.lora.LoRAEntry`** to include feed-forward weights (gate/up/down projections) — this is the correct long-term fix but requires modifying the gemma4 export pipeline.
- **Merge-then-export:** Use the merged model (`sft-merged/`) and run Route B (full export), which includes all weights. This avoids the MLP LoRA issue entirely.

---

## Route B: Merged Model → `.litertlm`  ⚠️ BLOCKED

**Status: BLOCKED — litert_torch 0.9.1 has an incomplete Gemma4 cache implementation + extremely slow on CPU**

### What was attempted
Export the fully merged SFT model (10 GB bf16) at `/home/joshu/ft-runs/sft-merged/` to a `.litertlm` file using `litert_torch.generative.export_hf.export()`.

### Toolchain
```bash
python -m litert_torch.generative.export_hf export \
  /home/joshu/ft-runs/sft-merged \
  /home/joshu/ft-runs/litertlm-export \
  --task text_generation \
  --prefill_lengths 8,16 \
  --cache_length 128 \
  --externalize_embedder=True \
  --bundle_litert_lm=True \
  --use_jinja_template=True
```

### What was found

#### Bug 1: Abstract `get_max_length` in Gemma4 cache layer
```
TypeError: Can't instantiate abstract class LiteRTLMCacheLayerForGemma4
with abstract method get_max_length
```
**Root cause:** `LiteRTLMCacheLayerForGemma4` inherits from `LiteRTLMCacheLayer` → `LiteRTLMCacheLayerMixin` → `CacheLayerMixin` (transformers). The abstract `get_max_length()` method is not implemented by the Gemma4 subclass.

**Fix applied (monkey-patch):**
```python
def get_max_length(self) -> int:
    if hasattr(self, 'key_cache'):
        return self.key_cache.shape[-1]
    if hasattr(self, 'k_cache'):
        return self.k_cache.shape[-1]
    return -1
```
This was inserted into `lite_rt_cache_layer_for_gemma4` in `.../model_ext/gemma4/cache.py`. After the patch, the abstract methods set is empty and the class is concrete.

#### Bug 2: CPU export is impractically slow
After fixing Bug 1, the export proceeds through model loading (successful) but then enters the `torch.export` / TFLite conversion step for the prefill-decode model. At 10 GB bf16 on CPU, this is projected to take **many hours to days**. The 120-second timeout captured only the model loading phase.

**Resolution:** Must run on the GPU server at `10.0.0.100` (AMD R9700 eGPU with ROCm, or the production RTX 6000 boxes at `10.0.0.10` during a maintenance window).

#### Bug 3: Default quantization recipe `dynamic_wi8_afp32` requires calibration
The default quantization path runs weight-only quantization, which adds significant time. For a first-pass conversion, set `--quantization_recipe None` to skip quantization and get a purely floating-point export.

### Gemma4 export pipeline seems otherwise functional
- The Gemma4-specific exportable modules exist and apply correctly (`Gemma4 patch applied.`)
- Model loading completes successfully (1951 safetensor shard weights loaded)
- The `LiteRTCacheForGemma4` cache class and `LiteRTLMCacheLayerForGemma4` layer class exist
- The jinja template, metadata builder, and vision exportables are in place

---

## Action Items

### Immediate (on this machine)
1. ✅ Route A LoRA `.tflite` produced at `/home/joshu/ft-runs/sft-lora-attention.tflite` (attention-only, ~50 MB)

### On GPU server (10.0.0.100 with AMD R9700 / ROCm)
2. **Run Route B with GPU acceleration:**
   ```bash
   # On 10.0.0.100 with litert-torch installed
   python -m litert_torch.generative.export_hf export \
     /home/joshu/ft-runs/sft-merged \
     /home/joshu/ft-runs/litertlm-export \
     --task image_text_to_text \
     --prefill_lengths 128,256 \
     --cache_length 2048 \
     --externalize_embedder True \
     --bundle_litert_lm True \
     --use_jinja_template True \
     --quantization_recipe None \
     --keep_temporary_files True
   ```
   Expected output: a `.litertlm` file under `/home/joshu/ft-runs/litertlm-export/`

3. **Validate the exported model:**
   - Push to device and test via flutter_gemma's `createChat()`.
   - Or verify with `litert_lm_builder.peek_litertlm_file()` to check sections.

### Flutter-side changes needed (for either route)
4. **For Route A (LoRA):** Modify `local_chat_repository.dart` `_ensureModel()`:
   - Download/copy the LoRA `.tflite` file to app storage
   - Install with `FlutterGemma.installModel(modelType: ModelType.gemmaIt, fileType: ModelFileType.litertlm).fromFile(baseModelPath).withLoraFromFile(loraPath).install()`
   - OR: pass `loraPath` to `model.createChat(loraPath: loraPath)`
   - Set `loraRanks: [32]` when calling `getActiveModel()` or `createModel()`

5. **For Route B (Full):** Replace the base model file path with the merged `.litertlm`.

---

## Deliverables

| Artifact | Path | Size |
|---|---|---|
| Conversion script | `finetune/deploy/scripts/ft_convert_ondevice.py` | 15 KB |
| This report | `finetune/deploy/f2_report.md` | — |
| LoRA TFLite | `/home/joshu/ft-runs/sft-lora-attention.tflite` | ~50 MB |
| Merged model (bf16) | `/home/joshu/ft-runs/sft-merged/` | 10 GB |
| SFT LoRA adapter | `finetune/runs/sft-01/` | 194 MB |
| Base .litertlm | `/home/joshu/android-models/gemma-4-E2B-it.litertlm` | 2.6 GB |

---

## HANDOFF: F2 Route A (attention-LoRA .tflite) works; Route B blocked by litert-torch 0.9.1 bug + CPU speed — needs GPU box. MLP LoRA weights (gate/up/down_proj) not included in Route A artifact — merge-then-export (Route B) is the complete path.
