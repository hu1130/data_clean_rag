<template>
  <main class="page page-grid">
    <section class="panel">
      <div class="panel-header">
        <h3>任务队列</h3>
        <div class="toolbar">
          <el-switch v-model="autoRefresh" active-text="自动刷新" />
          <el-button @click="load">刷新</el-button>
        </div>
      </div>
      <el-table :data="tasks" height="680" empty-text="暂无任务">
        <el-table-column prop="task_id" label="任务 ID" min-width="220" show-overflow-tooltip />
        <el-table-column prop="action" label="类型" min-width="150" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="Number(row.progress?.percent || 0)" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="尝试" width="90">
          <template #default="{ row }">{{ row.attempts || 0 }}/{{ row.max_attempts || 1 }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="190">
          <template #default="{ row }">{{ formatUnixTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }"><el-button size="small" @click="showDetail(row)">报告</el-button></template>
        </el-table-column>
      </el-table>
    </section>
  </main>

  <el-drawer v-model="drawerVisible" title="任务报告" size="620px">
    <div v-if="selected" class="drawer-section">
      <MetricCard label="状态" :value="selected.status" :tag="selected.action" :tag-type="statusType(selected.status)" />
      <el-alert v-if="selected.error" type="error" :title="selected.error" show-icon :closable="false" />
      <JsonBlock :value="selected.stats || selected" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import JsonBlock from "../components/JsonBlock.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import { formatUnixTime, statusType } from "../services/format";
import type { TaskRecord } from "../types/api";

const tasks = ref<TaskRecord[]>([]);
const drawerVisible = ref(false);
const selected = ref<TaskRecord>();
const autoRefresh = ref(true);
let timer: number | undefined;

async function load() {
  try {
    tasks.value = await backendApi.tasks();
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

async function showDetail(row: TaskRecord) {
  drawerVisible.value = true;
  selected.value = row;
  try {
    selected.value = await backendApi.taskDetail(row.task_id);
  } catch {
    selected.value = row;
  }
}

function setupTimer() {
  if (timer) window.clearInterval(timer);
  if (autoRefresh.value) timer = window.setInterval(load, 3000);
}

watch(autoRefresh, setupTimer);
onMounted(() => {
  load();
  setupTimer();
});
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>
