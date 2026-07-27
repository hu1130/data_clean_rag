<template>
  <main class="page page-grid two-col">
    <section class="panel">
      <div class="panel-header">
        <h3>系统诊断</h3>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="panel-body page-grid">
        <section class="metrics-grid">
          <MetricCard label="Pipeline" :value="diagnostics?.pipeline?.ready" />
          <MetricCard label="向量库" :value="diagnostics?.pipeline?.vector_db" />
          <MetricCard label="Embedding" :value="diagnostics?.pipeline?.embedding?.provider" />
          <MetricCard label="Metadata DB" :value="diagnostics?.pipeline?.metadata_db?.type" />
        </section>
        <JsonBlock :value="diagnostics" />
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>配置管理</h3>
        <el-button @click="loadConfig">读取配置</el-button>
      </div>
      <div class="panel-body page-grid">
        <el-alert type="warning" title="配置会递归合并并重新初始化 pipeline。修改数据库、向量库、embedding 参数前先确认依赖已安装。" :closable="false" show-icon />
        <el-form label-position="top">
          <el-form-item label="配置片段 JSON">
            <el-input v-model="patchText" type="textarea" :rows="10" placeholder='{"chunking":{"chunk_size":256}}' />
          </el-form-item>
          <el-button type="primary" :loading="saving" @click="applyPatch">应用配置</el-button>
        </el-form>
        <JsonBlock :value="config" />
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import JsonBlock from "../components/JsonBlock.vue";
import MetricCard from "../components/MetricCard.vue";
import { backendApi, explainApiError } from "../services/api";

const emit = defineEmits<{ (event: "refresh-status"): void }>();
const diagnostics = ref<Record<string, any>>();
const config = ref<Record<string, any>>();
const patchText = ref('{"chunking":{"chunk_size":256}}');
const saving = ref(false);

async function load() {
  try {
    diagnostics.value = (await backendApi.diagnostics()).diagnostics;
    await loadConfig();
  } catch (error) {
    ElMessage.error(explainApiError(error));
  }
}

async function loadConfig() {
  const data = await backendApi.config();
  config.value = data.config;
}

async function applyPatch() {
  let patch: Record<string, any>;
  try {
    patch = JSON.parse(patchText.value);
  } catch {
    ElMessage.error("配置片段不是合法 JSON");
    return;
  }
  saving.value = true;
  try {
    await backendApi.updateConfig(patch);
    ElMessage.success("配置已应用");
    emit("refresh-status");
    await load();
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
