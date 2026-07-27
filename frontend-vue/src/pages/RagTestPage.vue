<template>
  <main class="page page-grid two-col">
    <section class="panel">
      <div class="panel-header">
        <h3>RAG 测试台</h3>
        <span class="text-muted">检索召回后调用 DeepSeek</span>
      </div>
      <div class="panel-body">
        <section class="page-intro">
          <strong>测试回答前，先让系统找证据。</strong>
          <p>这里会先召回相关 chunk，再调用 DeepSeek。可靠回答必须能回到具体来源、页码或标题层级。</p>
        </section>

        <section class="acceptance-strip">
          <span><el-icon><CircleCheck /></el-icon>只使用召回资料</span>
          <span><el-icon><CircleCheck /></el-icon>关键结论带引用</span>
          <span><el-icon><CircleCheck /></el-icon>资料不足明确说明</span>
        </section>

        <el-form label-position="top">
          <el-form-item label="问题">
            <el-input
              v-model="question"
              type="textarea"
              :rows="4"
              maxlength="4000"
              show-word-limit
              placeholder="例如：这份合同的付款条件和违约风险是什么？"
              @keydown.ctrl.enter="askModel"
              @keydown.meta.enter="askModel"
            />
          </el-form-item>
          <div class="toolbar sample-row">
            <el-button v-for="sample in sampleQuestions" :key="sample" size="small" @click="question = sample">{{ sample }}</el-button>
          </div>

          <el-collapse v-model="advancedPanels" class="advanced-settings rag-settings">
            <el-collapse-item name="model">
              <template #title>
                <div class="settings-title">
                  <span>模型与检索设置</span>
                  <el-tag size="small" effect="plain">{{ llm.provider }} / {{ llm.model }}</el-tag>
                </div>
              </template>
              <el-row :gutter="12">
                <el-col :xs="24" :sm="12" :md="8">
                  <el-form-item label="模型服务">
                    <el-select v-model="llm.provider" @change="onProviderChange">
                      <el-option label="OpenAI" value="openai" />
                      <el-option label="DeepSeek" value="deepseek" />
                      <el-option label="OpenAI Compatible" value="openai_compatible" />
                      <el-option label="Ollama" value="ollama" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :sm="12" :md="8">
                  <el-form-item label="模型名称">
                    <el-input v-model="llm.model" />
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :sm="12" :md="8">
                  <el-form-item label="召回数量 top_k">
                    <el-input-number v-model="topK" :min="1" :max="20" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-row :gutter="12">
                <el-col :xs="24" :sm="12">
                  <el-form-item label="temperature">
                    <el-input-number v-model="temperature" :min="0" :max="2" :step="0.1" :precision="1" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :sm="12">
                  <el-form-item label="max_tokens">
                    <el-input-number v-model="maxTokens" :min="128" :max="8000" :step="128" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="Metadata filter JSON">
                <el-input v-model="filterText" placeholder='{"file_type":".pdf"}' />
              </el-form-item>
              <p class="field-help">有具体文件范围时再加 metadata 过滤；首次验收建议保持为空。</p>
            </el-collapse-item>
          </el-collapse>

          <div class="action-row ask-row">
            <el-button type="primary" size="large" :loading="loading" :disabled="!question.trim()" @click="askModel">检索并调用 DeepSeek</el-button>
            <span class="text-muted">将先检索证据，再生成回答</span>
          </div>
        </el-form>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>回答与证据</h3>
        <el-tag v-if="ragResponse" effect="light">{{ ragResponse.provider }} / {{ ragResponse.model }}</el-tag>
      </div>
      <div class="panel-body page-grid">
        <div v-if="loading" class="answer-loading">
          <span>正在检索知识库并生成回答</span>
          <el-skeleton :rows="5" animated />
        </div>
        <div v-else-if="!ragResponse && !errorText" class="empty-guide">
          还没有回答。先输入一个和已入库文件相关的问题，再点击“检索并调用 DeepSeek”。
        </div>
        <el-alert v-if="errorText" type="error" :title="errorText" :closable="false" show-icon />

        <section v-if="answer" class="answer-card">
          <div class="answer-card-header">
            <h4>模型回答</h4>
            <el-tooltip content="复制回答">
              <el-button :icon="CopyDocument" circle size="small" aria-label="复制回答" @click="copyAnswer" />
            </el-tooltip>
          </div>
          <pre>{{ answer }}</pre>
        </section>

        <el-descriptions v-if="ragResponse" :column="3" border size="small">
          <el-descriptions-item label="来源数">{{ ragResponse.total_sources }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ ragResponse.latency_ms }} ms</el-descriptions-item>
          <el-descriptions-item label="模型">{{ ragResponse.model }}</el-descriptions-item>
        </el-descriptions>

        <el-collapse v-if="ragResponse" class="response-details">
          <el-collapse-item title="查看 Prompt 与 Token 用量" name="prompt">
            <JsonBlock :value="{ prompt, usage: ragResponse.usage }" />
          </el-collapse-item>
        </el-collapse>

        <div class="result-list">
          <div v-if="results.length" class="result-list-title">
            <strong>引用来源</strong>
            <span class="text-muted">回答中的编号与下方证据一一对应</span>
          </div>
          <div v-else-if="ragResponse" class="empty-guide">本次没有召回证据。请先检查文件是否入库，再用更具体的问题重试。</div>
          <article v-for="(item, index) in results" :key="item.id" class="result-item source-item">
            <div class="toolbar">
              <span class="source-index">[{{ index + 1 }}]</span>
              <el-tag type="success" effect="light">score {{ item.score }}</el-tag>
              <el-tag v-if="item.metadata?.filename" effect="light">{{ item.metadata.filename }}</el-tag>
              <el-tag v-if="item.metadata?.page_number" type="info" effect="light">page {{ item.metadata.page_number }}</el-tag>
              <el-tag v-if="item.parent_heading_path" type="warning" effect="light">{{ item.parent_heading_path }}</el-tag>
            </div>
            <p class="source-excerpt">{{ item.child_text || item.text }}</p>
            <el-collapse v-if="item.parent_context">
              <el-collapse-item title="查看父 Chunk 上下文">
                <p>{{ item.parent_context }}</p>
              </el-collapse-item>
            </el-collapse>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { CircleCheck, CopyDocument } from "@element-plus/icons-vue";
import JsonBlock from "../components/JsonBlock.vue";
import { backendApi, explainApiError } from "../services/api";
import type { RagAskResponse, SearchResult } from "../types/api";

const defaultModels: Record<string, string> = {
  openai: "gpt-4.1-mini",
  deepseek: "deepseek-v4-flash",
  openai_compatible: "local-model",
  ollama: "llama3.1"
};

const sampleQuestions = [
  "概括文件的核心结论",
  "找出风险与限制",
  "按来源汇总关键字段"
];

const question = ref("");
const filterText = ref("");
const topK = ref(5);
const temperature = ref(Number(localStorage.getItem("ragTemperature") || 0.2));
const maxTokens = ref(Number(localStorage.getItem("ragMaxTokens") || 800));
const loading = ref(false);
const errorText = ref("");
const results = ref<SearchResult[]>([]);
const ragResponse = ref<RagAskResponse | null>(null);
const advancedPanels = ref<string[]>([]);
const savedProvider = localStorage.getItem("ragProvider") || "deepseek";
const savedModel = localStorage.getItem("ragModel");
const initialModel = savedProvider === "deepseek" && (!savedModel || savedModel === "deepseek-chat")
  ? "deepseek-v4-flash"
  : savedModel || defaultModels[savedProvider] || "deepseek-v4-flash";
const llm = reactive({
  provider: savedProvider,
  model: initialModel
});

const answer = computed(() => ragResponse.value?.answer || "");
const prompt = computed(() => ragResponse.value?.prompt || "");

function onProviderChange(provider: string) {
  if (!llm.model || Object.values(defaultModels).includes(llm.model)) {
    llm.model = defaultModels[provider] || "";
  }
}

function parseFilters() {
  if (!filterText.value.trim()) return null;
  return JSON.parse(filterText.value) as Record<string, any>;
}

async function askModel() {
  if (!question.value.trim()) {
    ElMessage.warning("请输入问题");
    return;
  }

  let filters: Record<string, any> | null = null;
  try {
    filters = parseFilters();
  } catch {
    ElMessage.error("Metadata filter 不是合法 JSON");
    return;
  }

  localStorage.setItem("ragProvider", llm.provider);
  localStorage.setItem("ragModel", llm.model);
  localStorage.setItem("ragTemperature", String(temperature.value));
  localStorage.setItem("ragMaxTokens", String(maxTokens.value));

  loading.value = true;
  errorText.value = "";
  ragResponse.value = null;
  results.value = [];
  try {
    const data = await backendApi.ragAsk({
      question: question.value,
      top_k: topK.value,
      filters,
      provider: llm.provider,
      model: llm.model,
      temperature: temperature.value,
      max_tokens: maxTokens.value
    });
    ragResponse.value = data;
    results.value = data.sources || [];
    data.sources?.length ? ElMessage.success("回答和引用已生成") : ElMessage.warning("回答已生成，但没有召回引用来源");
  } catch (error) {
    const message = explainApiError(error);
    errorText.value = message;
    ElMessage.error(message);
  } finally {
    loading.value = false;
  }
}

async function copyAnswer() {
  if (!answer.value) return;
  try {
    await navigator.clipboard.writeText(answer.value);
    ElMessage.success("回答已复制");
  } catch {
    ElMessage.error("复制失败，请手动选择回答内容");
  }
}
</script>

<style scoped>
.sample-row {
  margin: -8px 0 14px;
}

.acceptance-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 12px 0 16px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--soft);
}

.acceptance-strip span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--muted);
  font-size: 11px;
}

.acceptance-strip .el-icon {
  color: var(--teal);
}

.rag-settings {
  margin: 4px 0 14px;
}

.settings-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.settings-title .el-tag {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ask-row {
  margin-top: 4px;
}

.answer-loading {
  display: grid;
  gap: 16px;
  min-height: 220px;
  align-content: center;
  padding: 22px;
  border: 1px solid #acd3cd;
  border-radius: var(--radius);
  background: #f4fbfa;
}

.answer-loading > span {
  color: var(--teal-dark);
  font-size: 13px;
  font-weight: 600;
}

.response-details {
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.source-excerpt {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
}

@media (max-width: 760px) {
  .ask-row .el-button {
    width: 100%;
  }

  .settings-title .el-tag {
    display: none;
  }
}
</style>
