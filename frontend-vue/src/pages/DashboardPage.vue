<template>
  <main class="page page-grid">
    <section class="page-intro intro-actions">
      <div>
        <strong>把复杂文件处理成可检索、可追溯、可验证的 RAG 数据。</strong>
        <p>建议按顺序验收：先确认文件入库成功，再检查清洗质量和 chunk metadata，最后用检索和 DeepSeek 回答验证效果。</p>
      </div>
      <el-button type="primary" :icon="UploadFilled" @click="emit('navigate', 'ingestion')">开始文件入库</el-button>
    </section>

    <section class="workflow">
      <button v-for="step in workflow" :key="step.id" type="button" @click="emit('navigate', step.page)">
        <span>{{ step.id }}</span>
        <strong>{{ step.title }}</strong>
        <p>{{ step.desc }}</p>
      </button>
    </section>

    <section class="metrics-grid">
      <MetricCard label="文件数" :value="files?.total || 0" tag="manifest" tag-type="info" />
      <MetricCard label="Chunk 数" :value="chunkTotal" tag="vector" tag-type="success" />
      <MetricCard label="运行任务" :value="tasks.length" tag="queue" tag-type="warning" />
      <MetricCard label="Metadata 批次" :value="metadataRuns.length" :tag="metadataEnabled ? 'enabled' : 'disabled'" :tag-type="metadataEnabled ? 'success' : 'info'" />
    </section>

    <section class="page-grid two-col">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-header-inline">
            <strong>最近任务</strong>
            <el-button size="small" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
          </div>
        </template>
        <el-table :data="tasks.slice(0, 6)" height="322" empty-text="暂无任务">
          <el-table-column prop="action" label="类型" min-width="140" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" effect="light">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" min-width="180">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.progress?.percent || 0)" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="180">
            <template #default="{ row }">{{ formatUnixTime(row.updated_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="panel-header-inline">
            <strong>质量概览</strong>
            <span class="text-muted">来自最近处理报告</span>
          </div>
        </template>
        <ChartPanel :option="qualityOption" />
      </el-card>
    </section>

    <section class="page-grid two-col">
      <el-card shadow="never" class="panel-card">
        <template #header><strong>最近文件</strong></template>
        <el-table :data="files?.files.slice(0, 8) || []" height="300" empty-text="暂无文件">
          <el-table-column prop="filename" label="文件" min-width="220" show-overflow-tooltip />
          <el-table-column prop="file_type" label="类型" width="90" />
          <el-table-column prop="chunk_count" label="Chunk" width="90" />
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ formatUnixTime(row.processed_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header><strong>下一步建议</strong></template>
        <div class="result-list">
          <div class="result-item">
            <strong>1. 先上传真实文件</strong>
            <p>优先用 PDF、Word 或 Excel 这种结构复杂的文件测试，才能暴露表头、页码、标题层级和 OCR 问题。</p>
            <el-button link type="primary" @click="emit('navigate', 'ingestion')">去文件入库</el-button>
          </div>
          <div class="result-item">
            <strong>2. 再看 chunk 和质量过滤</strong>
            <p>如果过滤过多，去清洗预览看原因；如果召回上下文不完整，去 Chunk 审计看父子 chunk。</p>
            <el-button link type="primary" @click="emit('navigate', 'chunks')">去 Chunk 审计</el-button>
          </div>
          <div class="result-item">
            <strong>3. 最后测试 RAG 回答</strong>
            <p>进入 RAG 测试台，确认回答带引用，并且引用来源能支撑结论。</p>
            <el-button link type="primary" @click="emit('navigate', 'rag')">去 RAG 测试台</el-button>
          </div>
        </div>
      </el-card>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Refresh, UploadFilled } from "@element-plus/icons-vue";
import ChartPanel from "../components/ChartPanel.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import { formatUnixTime, statusType } from "../services/format";
import type { FileListResponse, MetadataRun, TaskRecord } from "../types/api";

const files = ref<FileListResponse>();
const tasks = ref<TaskRecord[]>([]);
const metadataRuns = ref<MetadataRun[]>([]);
const metadataEnabled = ref(false);
const loading = ref(false);
const emit = defineEmits<{ (event: "navigate", page: string): void }>();

const workflow = [
  { id: "01", title: "入库", desc: "上传文件，解析 PDF / Word / Excel / CSV / 图片 OCR", page: "ingestion" },
  { id: "02", title: "清洗", desc: "过滤乱码、重复、过短、OCR 噪声和低质量内容", page: "preview" },
  { id: "03", title: "分块", desc: "保留标题层级、页码、表格字段和父子 chunk", page: "chunks" },
  { id: "04", title: "验证", desc: "先看召回，再看 DeepSeek 回答是否有可靠引用", page: "rag" }
];

const chunkTotal = computed(() => (files.value?.files || []).reduce((sum, item) => sum + Number(item.chunk_count || 0), 0));

const qualityOption = computed(() => {
  const counts = new Map<string, number>();
  tasks.value.forEach((task) => {
    const reasons = task.stats?.processing_report?.quality_summary?.reason_counts || {};
    Object.entries(reasons).forEach(([key, value]) => counts.set(key, (counts.get(key) || 0) + Number(value || 0)));
  });
  const entries = Array.from(counts.entries());
  return {
    tooltip: {},
    grid: { left: 24, right: 12, top: 20, bottom: 34, containLabel: true },
    xAxis: { type: "category", data: entries.map(([key]) => key), axisLabel: { interval: 0, rotate: 22 } },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: entries.map(([, value]) => value), itemStyle: { color: "#a15c07" } }]
  };
});

async function load() {
  loading.value = true;
  try {
    const [fileData, taskData, metadataData] = await Promise.all([
      backendApi.files(),
      backendApi.tasks(),
      backendApi.metadataRuns()
    ]);
    files.value = fileData;
    tasks.value = taskData;
    metadataRuns.value = metadataData.runs || [];
    metadataEnabled.value = metadataData.enabled;
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.panel-card {
  border-radius: var(--radius);
}

.panel-header-inline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
