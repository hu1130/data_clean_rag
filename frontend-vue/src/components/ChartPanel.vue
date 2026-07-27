<template>
  <div ref="chartRef" class="chart-panel"></div>
</template>

<script setup lang="ts">
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  option: Record<string, any>;
}>();

const chartRef = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

function render() {
  if (!chartRef.value) return;
  if (!chart) chart = echarts.init(chartRef.value);
  chart.setOption(props.option, true);
}

function resize() {
  chart?.resize();
}

onMounted(() => {
  render();
  window.addEventListener("resize", resize);
});

watch(() => props.option, render, { deep: true });

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  chart?.dispose();
});
</script>
