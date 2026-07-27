<template>
  <el-container class="app-layout">
    <el-aside :width="sidebarCollapsed ? '76px' : '248px'" class="app-aside">
      <div class="brand">
        <span class="brand-mark">RAG</span>
        <div v-show="!sidebarCollapsed" class="brand-copy">
          <h1>Data Clean Console</h1>
          <p>复杂文件到可信 RAG 数据</p>
        </div>
      </div>

      <el-menu
        class="app-menu"
        :default-active="activePage"
        background-color="#101820"
        text-color="#d8e0ea"
        active-text-color="#ffffff"
        :collapse="sidebarCollapsed"
        @select="navigateTo"
      >
        <el-menu-item v-for="item in navItems" :key="item.key" :index="item.key">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <section v-show="!sidebarCollapsed" class="aside-note">
        <strong>当前目标</strong>
        把复杂文件处理成可检索、可追溯、可验证的 RAG 数据。先看入库，再看召回，最后看回答引用。
      </section>

      <el-tooltip :content="sidebarCollapsed ? '展开导航' : '收起导航'" placement="right">
        <el-button
          class="sidebar-toggle"
          :icon="sidebarCollapsed ? Expand : Fold"
          text
          :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'"
          @click="toggleSidebar"
        />
      </el-tooltip>
    </el-aside>

    <el-main class="app-main">
      <header class="topbar">
        <div class="topbar-heading">
          <el-button class="mobile-menu-button" :icon="Menu" circle aria-label="打开导航" @click="mobileNavVisible = true" />
          <div>
          <div class="eyebrow">工作台 / {{ pageTitle }}</div>
          <h2>{{ pageTitle }}</h2>
          <p class="topbar-subtitle">{{ pageSubtitle }}</p>
          </div>
        </div>
        <div class="status-row">
          <span class="service-status" :class="{ ready: health?.pipeline_ready }">
            <i /> API {{ health?.pipeline_ready ? "就绪" : "未连接" }}
          </span>
          <span class="service-status" :class="{ ready: metadataStatus?.enabled }">
            <i /> {{ metadataStatus?.type || "Metadata 未启用" }}
          </span>
          <span class="service-status" :class="{ ready: dbInfo?.db_type }">
            <i /> {{ dbInfo?.db_type || "向量库未知" }}
          </span>
          <el-tooltip content="刷新连接状态">
            <el-button :icon="Refresh" circle :loading="refreshing" aria-label="刷新连接状态" @click="refreshStatus(true)" />
          </el-tooltip>
          <el-button :icon="Connection" @click="connectionVisible = true">连接</el-button>
        </div>
      </header>

      <nav class="pipeline-rail" aria-label="数据处理流程">
        <button
          v-for="(stage, index) in pipelineStages"
          :key="stage.key"
          type="button"
          :class="{ active: activePage === stage.key }"
          @click="navigateTo(stage.key)"
        >
          <span class="rail-index">{{ index + 1 }}</span>
          <span><strong>{{ stage.label }}</strong><small>{{ stage.caption }}</small></span>
        </button>
      </nav>

      <transition name="page-fade" mode="out-in">
        <component
          :is="currentComponent"
          :key="activePage"
          @refresh-status="refreshStatus"
          @navigate="navigateTo"
        />
      </transition>
    </el-main>
  </el-container>

  <el-drawer v-model="mobileNavVisible" direction="ltr" size="min(84vw, 320px)" :with-header="false" class="mobile-nav-drawer">
    <div class="brand mobile-brand">
      <span class="brand-mark">RAG</span>
      <div class="brand-copy">
        <h1>Data Clean Console</h1>
        <p>复杂文件到可信 RAG 数据</p>
      </div>
    </div>
    <el-menu :default-active="activePage" class="mobile-nav-menu" @select="navigateTo">
      <el-menu-item v-for="item in navItems" :key="item.key" :index="item.key">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </el-menu-item>
    </el-menu>
  </el-drawer>

  <el-dialog v-model="connectionVisible" title="后端连接" width="min(520px, calc(100vw - 28px))">
    <el-form label-position="top">
      <el-form-item label="API 地址">
        <el-input v-model="connection.apiBase" placeholder="http://127.0.0.1:8131" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="connection.apiKey" type="password" show-password placeholder="未启用可留空" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="connectionVisible = false">取消</el-button>
      <el-button type="primary" @click="saveConnection">保存并刷新</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  Coin,
  Connection,
  DataAnalysis,
  Document,
  Expand,
  Files,
  Finished,
  Fold,
  MagicStick,
  Menu,
  Monitor,
  Refresh,
  Search,
  Setting,
  UploadFilled
} from "@element-plus/icons-vue";
import DashboardPage from "./pages/DashboardPage.vue";
import IngestionPage from "./pages/IngestionPage.vue";
import FilesPage from "./pages/FilesPage.vue";
import PreviewPage from "./pages/PreviewPage.vue";
import ChunkAuditPage from "./pages/ChunkAuditPage.vue";
import SearchPage from "./pages/SearchPage.vue";
import TasksPage from "./pages/TasksPage.vue";
import ReportsPage from "./pages/ReportsPage.vue";
import ConfigPage from "./pages/ConfigPage.vue";
import RagTestPage from "./pages/RagTestPage.vue";
import { backendApi, explainApiError, getApiBase, getApiKey, setApiBase, setApiKey } from "./services/api";
import type { DbInfoResponse, HealthResponse, MetadataStatusResponse } from "./types/api";

const activePage = ref("dashboard");
const connectionVisible = ref(false);
const mobileNavVisible = ref(false);
const sidebarCollapsed = ref(localStorage.getItem("sidebarCollapsed") === "true");
const refreshing = ref(false);
const health = ref<HealthResponse>();
const dbInfo = ref<DbInfoResponse>();
const metadataStatus = ref<MetadataStatusResponse>();

const connection = reactive({
  apiBase: getApiBase(),
  apiKey: getApiKey()
});

const navItems = [
  { key: "dashboard", label: "工作台", subtitle: "看系统是否就绪，并决定下一步该测哪里。", icon: Monitor, component: DashboardPage },
  { key: "ingestion", label: "文件入库", subtitle: "上传真实文件，生成可检索 chunk 和处理报告。", icon: UploadFilled, component: IngestionPage },
  { key: "files", label: "文件管理", subtitle: "确认文件是否入库、chunk 数是否合理。", icon: Files, component: FilesPage },
  { key: "preview", label: "清洗预览", subtitle: "写入向量库前，先检查过滤、去重和分块结果。", icon: MagicStick, component: PreviewPage },
  { key: "chunks", label: "Chunk 审计", subtitle: "检查页码、标题层级、父子 chunk 和 metadata 是否可靠。", icon: Document, component: ChunkAuditPage },
  { key: "search", label: "检索测试", subtitle: "先验证召回质量，再让大模型回答。", icon: Search, component: SearchPage },
  { key: "rag", label: "RAG 测试台", subtitle: "用 DeepSeek 检查回答是否基于证据并带引用。", icon: Coin, component: RagTestPage },
  { key: "tasks", label: "任务中心", subtitle: "查看后台入库、重试和失败原因。", icon: Finished, component: TasksPage },
  { key: "reports", label: "质量报告", subtitle: "查看清洗质量、过滤原因和验收记录。", icon: DataAnalysis, component: ReportsPage },
  { key: "config", label: "系统配置", subtitle: "调整清洗、分块、数据库和模型参数。", icon: Setting, component: ConfigPage }
];

const pipelineStages = [
  { key: "ingestion", label: "文件入库", caption: "上传与解析" },
  { key: "chunks", label: "Chunk 审计", caption: "检查结构" },
  { key: "search", label: "检索测试", caption: "验证召回" },
  { key: "rag", label: "RAG 问答", caption: "核对引用" }
];

const pageTitle = computed(() => navItems.find((item) => item.key === activePage.value)?.label || "工作台");
const pageSubtitle = computed(() => navItems.find((item) => item.key === activePage.value)?.subtitle || "");
const currentComponent = computed(() => navItems.find((item) => item.key === activePage.value)?.component || DashboardPage);

function navigateTo(page: string) {
  activePage.value = page;
  mobileNavVisible.value = false;
  localStorage.setItem("activePage", page);
  localStorage.setItem("sidebarCollapsed", String(sidebarCollapsed.value));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  localStorage.setItem("sidebarCollapsed", String(sidebarCollapsed.value));
}

async function refreshStatus(showMessage = false) {
  refreshing.value = true;
  try {
    const [healthData, dbData, metadataData] = await Promise.allSettled([
      backendApi.health(),
      backendApi.dbInfo(),
      backendApi.metadataStatus()
    ]);

    if (healthData.status === "fulfilled") health.value = healthData.value;
    if (dbData.status === "fulfilled") dbInfo.value = dbData.value;
    if (metadataData.status === "fulfilled") metadataStatus.value = metadataData.value;
    if (showMessage) {
      const connected = healthData.status === "fulfilled" && healthData.value.pipeline_ready;
      connected ? ElMessage.success("后端连接正常") : ElMessage.warning("后端尚未就绪，请检查连接地址");
    }
  } catch (error) {
    ElMessage.error(explainApiError(error));
  } finally {
    refreshing.value = false;
  }
}

async function saveConnection() {
  setApiBase(connection.apiBase);
  setApiKey(connection.apiKey);
  connectionVisible.value = false;
  await refreshStatus();
  ElMessage.success("连接配置已保存");
}

onMounted(() => {
  const savedPage = localStorage.getItem("activePage");
  if (savedPage && navItems.some((item) => item.key === savedPage)) activePage.value = savedPage;
  refreshStatus();
});
</script>
