<template>
  <main class="page page-grid two-col">
    <section class="panel">
      <div class="panel-header">
        <h3>Metadata 批次</h3>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="panel-body">
        <section class="page-intro">
          <strong>这里检查 chunk 是否带着足够上下文。</strong>
          <p>复杂文件重点看页码、标题层级、表格字段、parent_id 和文本预览。如果这里缺信息，RAG 引用就很难可靠。</p>
        </section>
      </div>
      <el-table :data="runs" height="560" empty-text="metadata_db 未启用或暂无批次。请先完成文件入库。">
        <el-table-column prop="run_id" label="Run ID" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="input_count" label="输入" width="90" />
        <el-table-column prop="stored_count" label="入库" width="90" />
        <el-table-column label="完成时间" width="180">
          <template #default="{ row }">{{ formatUnixTime(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }"><el-button size="small" @click="showRun(row.run_id)">审计</el-button></template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>Chunk 审计</h3>
        <el-tag effect="light">{{ chunks.length }} chunks</el-tag>
      </div>
      <div class="panel-body result-list">
        <el-empty v-if="!runDetail" description="选择一个批次查看 chunk metadata" />
        <article v-for="(chunk, index) in chunks" :key="chunk.chunk_id || index" class="result-item">
          <div class="toolbar">
            <el-tag type="success" effect="light">#{{ index + 1 }}</el-tag>
            <el-tag v-if="chunk.filename || chunk.file_key" effect="light">{{ chunk.filename || chunk.file_key }}</el-tag>
            <el-tag v-if="chunk.page_number || chunk.metadata?.page_number" type="warning" effect="light">page {{ chunk.page_number || chunk.metadata?.page_number }}</el-tag>
            <el-tag v-if="chunk.heading_path || chunk.metadata?.heading_path" type="info" effect="light">{{ chunk.heading_path || chunk.metadata?.heading_path }}</el-tag>
            <el-tag v-if="chunk.parent_id" type="info" effect="light">parent {{ chunk.parent_id }}</el-tag>
          </div>
          <p>{{ chunk.text_preview || chunk.text || "" }}</p>
          <JsonBlock :value="chunk.metadata || chunk" />
        </article>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import JsonBlock from "../components/JsonBlock.vue";
import { backendApi, explainApiError } from "../services/api";
import { formatUnixTime, statusType } from "../services/format";
import type { MetadataRun } from "../types/api";

const runs = ref<MetadataRun[]>([]);
const runDetail = ref<Record<string, any>>();

const chunks = computed<Record<string, any>[]>(() => runDetail.value?.chunks || []);

async function load() {
  try {
    const data = await backendApi.metadataRuns();
    runs.value = data.runs || [];
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

async function showRun(runId: string) {
  try {
    runDetail.value = await backendApi.metadataRunDetail(runId);
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

onMounted(load);
</script>
