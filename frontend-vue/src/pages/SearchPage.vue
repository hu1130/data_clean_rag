<template>
  <main class="page page-grid">
    <section class="page-intro">
      <strong>先测试召回，再测试大模型。</strong>
      <p>如果检索结果没有召回正确 chunk，RAG 回答也不会可靠。这里用于检查问题能否命中正确文件、页码、标题和父级上下文。</p>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>检索测试</h3>
        <span class="text-muted">验证清洗后的 chunk 是否能被召回</span>
      </div>
      <div class="panel-body">
        <el-form label-position="top">
          <el-row :gutter="12">
            <el-col :xs="24" :md="12"><el-form-item label="问题"><el-input v-model="query" clearable placeholder="例如：合同里付款条件是什么？" @keydown.enter="runSearch" /></el-form-item></el-col>
            <el-col :xs="24" :sm="8" :md="4"><el-form-item label="top_k"><el-input-number v-model="topK" :min="1" :max="50" style="width: 100%" /></el-form-item></el-col>
            <el-col :xs="24" :sm="16" :md="8"><el-form-item label="Metadata filter JSON"><el-input v-model="filterText" placeholder='{"filename":"a.pdf"}' /></el-form-item></el-col>
          </el-row>
          <p class="field-help">top_k 越大召回越多，但也会带来更多噪声。先用 5 到 10 验收，再根据业务调整。</p>
          <el-button type="primary" :loading="loading" :disabled="!query.trim()" @click="runSearch">测试召回</el-button>
        </el-form>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>召回结果</h3>
        <div class="toolbar">
          <el-tag effect="light">{{ results.length }} 条</el-tag>
          <el-button v-if="results.length" size="small" @click="emit('navigate', 'rag')">用大模型回答</el-button>
        </div>
      </div>
      <div class="panel-body result-list">
        <div v-if="loading" class="search-loading"><el-skeleton :rows="3" animated /></div>
        <div v-else-if="hasSearched && !results.length" class="empty-guide">没有找到匹配内容。请检查文件是否已经入库，或把问题改得更具体后重试。</div>
        <div v-else-if="!hasSearched" class="empty-guide">输入一个能在文件中找到答案的问题，系统会展示命中的 chunk、页码和父级上下文。</div>
        <article v-for="(item, index) in results" :key="item.id" class="result-item">
          <div class="toolbar">
            <span class="source-index">{{ index + 1 }}</span>
            <el-tag type="success" effect="light">score {{ item.score }}</el-tag>
            <el-tag v-if="item.metadata?.filename" effect="light">{{ item.metadata.filename }}</el-tag>
            <el-tag v-if="item.metadata?.page_number" type="warning" effect="light">page {{ item.metadata.page_number }}</el-tag>
            <el-tag v-if="item.parent_heading_path" type="info" effect="light">{{ item.parent_heading_path }}</el-tag>
            <el-tag v-if="item.parent_id" type="info" effect="light">parent {{ item.parent_id }}</el-tag>
          </div>
          <p>{{ item.child_text || item.text }}</p>
          <el-collapse v-if="item.parent_context">
            <el-collapse-item title="父 chunk 上下文">
              <p>{{ item.parent_context }}</p>
            </el-collapse-item>
          </el-collapse>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { backendApi, explainApiError } from "../services/api";
import type { SearchResult } from "../types/api";

const query = ref("");
const filterText = ref("");
const topK = ref(5);
const loading = ref(false);
const hasSearched = ref(false);
const results = ref<SearchResult[]>([]);
const emit = defineEmits<{ (event: "navigate", page: string): void }>();

async function runSearch() {
  if (!query.value.trim()) {
    ElMessage.warning("请输入问题");
    return;
  }
  let filters: Record<string, any> | null = null;
  if (filterText.value.trim()) {
    try {
      filters = JSON.parse(filterText.value);
    } catch {
      ElMessage.error("Metadata filter 不是合法 JSON");
      return;
    }
  }
  loading.value = true;
  hasSearched.value = true;
  results.value = [];
  try {
    const data = await backendApi.search({ query: query.value, top_k: topK.value, filters });
    results.value = data.results || [];
    results.value.length ? ElMessage.success(`召回 ${results.value.length} 条证据`) : ElMessage.warning("没有召回匹配证据");
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.search-loading {
  min-height: 190px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--soft);
}
</style>
