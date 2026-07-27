<template>
  <section class="metric-card">
    <div>
      <span>{{ label }}</span>
      <strong>{{ value ?? "-" }}</strong>
    </div>
    <el-tag v-if="tag" :type="tagType" effect="light">{{ tag }}</el-tag>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  label: string;
  value: string | number | boolean | undefined;
  tag?: string;
  tagType?: "success" | "warning" | "danger" | "info";
}>();
</script>
