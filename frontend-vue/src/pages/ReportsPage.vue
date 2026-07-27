<template>
  <main class="page page-grid">
    <section class="metrics-grid">
      <MetricCard label="批次数" :value="runs.length" :tag="enabled ? 'metadata' : 'disabled'" :tag-type="enabled ? 'success' : 'info'" />
      <MetricCard label="总输入" :value="totalInput" />
      <MetricCard label="总入库" :value="totalStored" tag="stored" tag-type="success" />
      <MetricCard label="成功率" :value="successRate" tag="quality" tag-type="warning" />
    </section>

    <section class="page-grid two-col">
      <section class="panel">
        <div class="panel-header">
          <h3>批次入库趋势</h3>
          <el-button @click="load">刷新</el-button>
        </div>
        <div class="panel-body"><ChartPanel :option="runOption" /></div>
      </section>

      <section class="panel">
        <div class="panel-header"><h3>过滤原因分布</h3></div>
        <div class="panel-body"><ChartPanel :option="reasonOption" /></div>
      </section>
    </section>

    <section class="panel">
      <div class="panel-header"><h3>验收摘要</h3></div>
      <div class="panel-body result-list">
        <article v-for="run in runs" :key="run.run_id" class="result-item">
          <div class="toolbar">
            <el-tag :type="statusType(run.status)" effect="light">{{ run.status }}</el-tag>
            <el-tag effect="light">input {{ run.input_count || 0 }}</el-tag>
            <el-tag type="success" effect="light">stored {{ run.stored_count || 0 }}</el-tag>
          </div>
          <p class="mono">{{ run.run_id }} / {{ formatUnixTime(run.finished_at) }}</p>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import ChartPanel from "../components/ChartPanel.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import { formatUnixTime, statusType } from "../services/format";
import type { MetadataRun } from "../types/api";

const enabled = ref(false);
const runs = ref<MetadataRun[]>([]);

const totalInput = computed(() => runs.value.reduce((sum, item) => sum + Number(item.input_count || 0), 0));
const totalStored = computed(() => runs.value.reduce((sum, item) => sum + Number(item.stored_count || 0), 0));
const successRate = computed(() => (totalInput.value ? `${Math.round(totalStored.value / totalInput.value * 100)}%` : "-"));

const runOption = computed(() => ({
  tooltip: {},
  legend: { top: 0 },
  grid: { left: 24, right: 16, top: 42, bottom: 24, containLabel: true },
  xAxis: { type: "category", data: runs.value.map((item) => item.run_id?.slice(0, 8) || "-") },
  yAxis: { type: "value" },
  series: [
    { name: "输入", type: "bar", data: runs.value.map((item) => item.input_count || 0), itemStyle: { color: "#2557a7" } },
    { name: "入库", type: "bar", data: runs.value.map((item) => item.stored_count || 0), itemStyle: { color: "#08736b" } }
  ]
}));

const reasonOption = computed(() => {
  const counts = new Map<string, number>();
  runs.value.forEach((run) => {
    const reasons = run.processing_report?.quality_summary?.reason_counts || {};
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
  try {
    const data = await backendApi.metadataRuns();
    enabled.value = data.enabled;
    runs.value = data.runs || [];
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

onMounted(load);
</script>
