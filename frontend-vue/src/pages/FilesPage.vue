<template>
  <main class="page page-grid">
    <section class="page-intro">
      <strong>这里确认“文件是否真的进入知识库”。</strong>
      <p>重点看每个文件的状态、chunk 数和处理时间。chunk 数异常少，通常说明解析失败、质量过滤过严或文件内容本身不可读。</p>
    </section>

    <section class="metrics-grid">
      <MetricCard label="文件总数" :value="files?.total || 0" :tag="files?.backend || '-'" tag-type="info" />
      <MetricCard label="Chunk 总数" :value="chunkTotal" tag="chunks" tag-type="success" />
      <MetricCard label="Manifest" :value="files?.path || '-'" tag="path" tag-type="info" />
      <MetricCard label="过滤结果" :value="filteredFiles.length" tag="visible" tag-type="warning" />
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>文件历史</h3>
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="按文件名、类型搜索" style="width: 260px" />
          <el-button @click="load">刷新</el-button>
        </div>
      </div>
      <el-table :data="filteredFiles" height="620" empty-text="还没有文件。请先到文件入库页上传一份真实文件。">
        <el-table-column prop="filename" label="文件" min-width="260" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="90" />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatBytes(row.size_bytes || row.file_size_bytes) }}</template>
        </el-table-column>
        <el-table-column prop="document_count" label="文档" width="90" />
        <el-table-column prop="chunk_count" label="Chunk" width="90" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light">{{ row.status || "-" }}</el-tag></template>
        </el-table-column>
        <el-table-column label="处理时间" width="190">
          <template #default="{ row }">{{ formatUnixTime(row.processed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }"><el-button size="small" @click="showDetail(row)">详情</el-button></template>
        </el-table-column>
      </el-table>
    </section>
  </main>

  <el-drawer v-model="drawerVisible" title="文件详情" size="560px">
    <div v-if="selected" class="drawer-section">
      <MetricCard label="文件" :value="selected.filename" tag="file" tag-type="info" />
      <MetricCard label="Chunk 数" :value="selected.chunk_count" tag="chunk" tag-type="success" />
      <div class="empty-guide">
        详情用于排查入库结果。重点检查文件类型、chunk 数、处理状态、manifest 记录和 metadata 是否完整。
      </div>
      <JsonBlock :value="selected" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import JsonBlock from "../components/JsonBlock.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";
import { formatBytes, formatUnixTime, statusType } from "../services/format";
import type { FileListResponse, FileRecord } from "../types/api";

const files = ref<FileListResponse>();
const keyword = ref("");
const drawerVisible = ref(false);
const selected = ref<FileRecord>();

const chunkTotal = computed(() => (files.value?.files || []).reduce((sum, item) => sum + Number(item.chunk_count || 0), 0));
const filteredFiles = computed(() => {
  const query = keyword.value.trim().toLowerCase();
  const list = files.value?.files || [];
  if (!query) return list;
  return list.filter((item) => `${item.filename} ${item.file_type} ${item.status}`.toLowerCase().includes(query));
});

async function load() {
  try {
    files.value = await backendApi.files();
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

async function showDetail(row: FileRecord) {
  drawerVisible.value = true;
  selected.value = row;
  try {
    selected.value = await backendApi.fileDetail(row.file_key);
  } catch {
    selected.value = row;
  }
}

onMounted(load);
</script>
