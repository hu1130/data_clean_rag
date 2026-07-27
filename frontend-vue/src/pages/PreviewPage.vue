<template>
  <main class="page page-grid two-col">
    <section class="panel">
      <div class="panel-header">
        <h3>清洗预览</h3>
        <span class="text-muted">先预览，不写入向量库</span>
      </div>
      <div class="panel-body">
        <section class="page-intro">
          <strong>在入库前检查清洗规则是否合适。</strong>
          <p>这里不会写入向量库。适合用一段真实文本验证：是否过滤过严、是否保留标题和表格信息、chunk 是否足够完整。</p>
        </section>

        <el-form label-position="top">
          <el-form-item label="原始文本">
            <el-input v-model="text" type="textarea" :rows="14" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="最大 chunk"><el-input-number v-model="maxChunks" :min="1" :max="200" style="width: 100%" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="预览字符"><el-input-number v-model="maxChars" :min="50" :max="5000" style="width: 100%" /></el-form-item></el-col>
          </el-row>
          <el-button type="primary" :loading="loading" @click="runPreview">生成预览</el-button>
        </el-form>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>质量与 Chunk</h3>
        <el-tag effect="light">{{ result?.total_chunks || 0 }} chunks</el-tag>
      </div>
      <div class="panel-body page-grid">
        <section class="guide-grid">
          <div class="guide-item">
            <strong>拒绝数过高</strong>
            <p>检查文本是否太短、乱码、重复行太多，或 OCR 噪声比例过高。</p>
          </div>
          <div class="guide-item">
            <strong>chunk 太碎</strong>
            <p>适当增大 chunk_size 或降低 overlap，避免回答时上下文不完整。</p>
          </div>
          <div class="guide-item">
            <strong>chunk 太长</strong>
            <p>适当减小 chunk_size，让检索结果更聚焦，减少无关信息进入模型。</p>
          </div>
        </section>
        <section class="metrics-grid">
          <MetricCard label="评分数" :value="quality.scored_count" />
          <MetricCard label="拒绝数" :value="quality.rejected_count" tag="filter" tag-type="warning" />
          <MetricCard label="平均分" :value="quality.average_score" />
          <MetricCard label="输出 chunk" :value="result?.total_chunks || 0" />
        </section>
        <ChartPanel :option="reasonOption" />
        <div class="result-list">
          <div v-if="!result" class="empty-guide">
            点击“生成预览”后，这里会展示质量评分、过滤原因和即将入库的 chunk。
          </div>
          <article v-for="(chunk, index) in result?.chunks || []" :key="index" class="result-item">
            <strong>#{{ index + 1 }} {{ chunk.metadata?.chunk_id || "" }}</strong>
            <span class="text-muted">检查这段是否能单独支撑一个检索答案。</span>
            <p>{{ chunk.text }}</p>
            <el-tag v-if="chunk.metadata?.parent_id" size="small" effect="light">parent {{ chunk.metadata.parent_id }}</el-tag>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import ChartPanel from "../components/ChartPanel.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import type { PreviewResponse } from "../types/api";

const text = ref("这是用于预览清洗、质量过滤和分块的测试文本。它包含足够的句子长度，便于观察父子 chunk、质量评分和 metadata 保留情况。");
const maxChunks = ref(20);
const maxChars = ref(500);
const loading = ref(false);
const result = ref<PreviewResponse>();

const quality = computed(() => result.value?.stats?.quality_summary || {});
const reasonOption = computed(() => {
  const counts = quality.value.reason_counts || {};
  const entries = Object.entries(counts);
  return {
    tooltip: {},
    grid: { left: 24, right: 12, top: 20, bottom: 34, containLabel: true },
    xAxis: { type: "category", data: entries.map(([key]) => key), axisLabel: { interval: 0, rotate: 22 } },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: entries.map(([, value]) => Number(value)), itemStyle: { color: "#a15c07" } }]
  };
});

async function runPreview() {
  loading.value = true;
  try {
    result.value = await backendApi.preview({
      texts: [text.value],
      source_metadata: [{ filename: "preview.txt", file_type: ".txt" }],
      max_chunks: maxChunks.value,
      max_chars: maxChars.value
    });
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    loading.value = false;
  }
}
</script>
