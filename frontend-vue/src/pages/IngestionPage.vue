<template>
  <main class="page page-grid two-col">
    <section class="panel">
      <div class="panel-header">
        <h3>文件入库</h3>
        <span class="text-muted">上传后会清洗、过滤、分块并写入向量库</span>
      </div>
      <div class="panel-body">
        <section class="page-intro">
          <strong>上传真实业务文件开始测试。</strong>
          <p>支持 PDF、Word、Excel、CSV、JSONL、HTML 和图片。扫描件需要开启 OCR；大文件建议开启后台处理，避免页面等待过久。</p>
        </section>

        <el-upload
          v-model:file-list="fileList"
          drag
          multiple
          :auto-upload="false"
          :limit="20"
          class="upload-box"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽文件到这里，或点击选择</div>
          <template #tip>
            <div class="el-upload__tip">建议先用 1 到 3 个复杂文件验收，再批量处理。</div>
          </template>
        </el-upload>

        <div v-if="fileList.length" class="selection-summary">
          <el-icon><Files /></el-icon>
          <div>
            <strong>已选择 {{ fileList.length }} 个文件</strong>
            <span>{{ selectedNames }}</span>
          </div>
          <el-button link type="danger" @click="fileList = []">清空</el-button>
        </div>

        <el-form label-position="top" class="ingestion-form">
          <section class="option-grid">
            <label class="option-item">
              <span><strong>后台处理</strong><small>大文件和批量任务建议开启</small></span>
              <el-switch v-model="form.background" />
            </label>
            <label class="option-item">
              <span><strong>扫描件 OCR</strong><small>图片或不能复制文字时开启</small></span>
              <el-switch v-model="form.ocr_enabled" />
            </label>
            <label class="option-item">
              <span><strong>强制重建</strong><small>修改处理参数后重新入库</small></span>
              <el-switch v-model="form.force_reprocess" />
            </label>
          </section>

          <el-form-item v-if="form.ocr_enabled" label="OCR 语言">
            <el-input v-model="form.ocr_language" />
          </el-form-item>

          <el-collapse v-model="advancedPanels" class="advanced-settings">
            <el-collapse-item title="高级入库参数" name="advanced">
              <el-row :gutter="12">
                <el-col :xs="24" :sm="12"><el-form-item label="最大文件 MB"><el-input-number v-model="form.max_file_size_mb" :min="1" :max="1024" style="width: 100%" /></el-form-item></el-col>
                <el-col :xs="24" :sm="12"><el-form-item label="最大记录数"><el-input-number v-model="form.max_records" :min="1" style="width: 100%" /></el-form-item></el-col>
              </el-row>
              <el-form-item label="结构化数据文本字段">
                <el-input v-model="form.text_fields" placeholder="text,content,data.body" />
              </el-form-item>
              <p class="field-help">仅处理 CSV、JSONL 等结构化文件时需要指定文本字段；普通文档保持为空。</p>
            </el-collapse-item>
          </el-collapse>

          <div class="action-row submit-row">
            <el-button type="primary" size="large" :loading="uploading" :disabled="!fileList.length" @click="submit">
              {{ uploadButtonText }}
            </el-button>
            <span class="text-muted">{{ fileList.length ? "准备开始清洗和分块" : "请先选择文件" }}</span>
          </div>
        </el-form>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>入库结果</h3>
        <el-button v-if="lastResult" @click="lastResult = undefined">清空</el-button>
      </div>
      <div class="panel-body">
        <div v-if="uploading" class="processing-state">
          <span class="processing-kicker">正在提交文件</span>
          <strong>系统正在检查文件并创建入库任务</strong>
          <el-progress :percentage="50" :indeterminate="true" :duration="1.2" :show-text="false" />
          <p>包含 OCR 或较大文件时，处理会在任务中心继续运行。</p>
        </div>
        <div v-else-if="!lastResult" class="empty-guide">上传后，这里会显示任务状态、chunk 数、清洗报告和下一步操作。</div>
        <div v-else class="result-list">
          <MetricCard label="状态" :value="lastResult.status" :tag="lastResult.success ? 'success' : 'failed'" :tag-type="lastResult.success ? 'success' : 'danger'" />
          <MetricCard label="任务 ID" :value="lastResult.task_id" tag="task" tag-type="info" />
          <div class="result-item">
            <strong>{{ lastResult.message }}</strong>
            <p>如果是后台任务，请到任务中心查看进度；完成后进入文件管理和 RAG 测试台验收。</p>
            <div class="action-row result-actions">
              <el-button v-if="lastResult.task_id" type="primary" plain @click="emit('navigate', 'tasks')">查看任务进度</el-button>
              <el-button @click="emit('navigate', 'files')">检查入库文件</el-button>
              <el-button @click="emit('navigate', 'rag')">测试 RAG 回答</el-button>
            </div>
          </div>
          <JsonBlock :value="lastResult.stats" />
        </div>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import type { UploadUserFile } from "element-plus";
import { Files, UploadFilled } from "@element-plus/icons-vue";
import JsonBlock from "../components/JsonBlock.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import type { ProcessResponse } from "../types/api";

const emit = defineEmits<{
  (event: "refresh-status"): void;
  (event: "navigate", page: string): void;
}>();
const fileList = ref<UploadUserFile[]>([]);
const uploading = ref(false);
const lastResult = ref<ProcessResponse>();
const advancedPanels = ref<string[]>([]);

const form = reactive({
  background: true,
  ocr_enabled: false,
  force_reprocess: false,
  ocr_language: "chi_sim+eng",
  max_file_size_mb: 100,
  text_fields: "",
  max_records: undefined as number | undefined
});

const selectedNames = computed(() => {
  const names = fileList.value.map((item) => item.name);
  return names.length > 3 ? `${names.slice(0, 3).join("、")} 等` : names.join("、");
});
const uploadButtonText = computed(() => fileList.value.length ? `上传 ${fileList.value.length} 个文件并开始入库` : "上传并开始入库");

async function submit() {
  if (!fileList.value.length) {
    ElMessage.warning("请先选择文件");
    return;
  }

  const data = new FormData();
  fileList.value.forEach((item) => {
    const raw = item.raw;
    if (raw) data.append("files", raw);
  });
  Object.entries(form).forEach(([key, value]) => {
    if (value !== undefined && value !== "") data.append(key, String(value));
  });

  uploading.value = true;
  try {
    lastResult.value = await backendApi.uploadFiles(data);
    ElMessage.success("入库请求已提交");
    emit("refresh-status");
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    uploading.value = false;
  }
}
</script>

<style scoped>
.upload-box {
  margin: 16px 0;
}

.ingestion-form {
  display: grid;
  gap: 14px;
  margin-top: 12px;
}

.selection-summary {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #acd3cd;
  border-radius: var(--radius);
  background: #f2faf8;
  color: var(--teal-dark);
}

.selection-summary .el-icon {
  font-size: 22px;
}

.selection-summary strong,
.selection-summary span {
  display: block;
}

.selection-summary strong {
  font-size: 12px;
}

.selection-summary span {
  margin-top: 2px;
  overflow: hidden;
  color: var(--muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.option-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 68px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--soft);
  cursor: pointer;
}

.option-item strong,
.option-item small {
  display: block;
}

.option-item strong {
  color: var(--ink);
  font-size: 12px;
}

.option-item small {
  margin-top: 3px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.4;
}

.advanced-settings {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0 12px;
}

.submit-row {
  padding-top: 2px;
}

.processing-state {
  display: grid;
  gap: 12px;
  min-height: 210px;
  align-content: center;
  padding: 24px;
  border: 1px solid #acd3cd;
  border-radius: var(--radius);
  background: #f2faf8;
}

.processing-state strong {
  color: #174741;
  font-size: 16px;
}

.processing-state p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.processing-kicker {
  color: var(--teal-dark);
  font-family: Bahnschrift, "Cascadia Mono", monospace;
  font-size: 11px;
}

.result-actions {
  margin-top: 12px;
}

@media (max-width: 760px) {
  .option-grid {
    grid-template-columns: 1fr;
  }

  .submit-row .el-button {
    width: 100%;
  }
}
</style>
