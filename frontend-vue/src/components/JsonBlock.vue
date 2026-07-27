<template>
  <pre class="json-block">{{ content }}</pre>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { asJson } from "../services/format";

const props = defineProps<{
  value: unknown;
}>();

const content = computed(() => asJson(props.value));
</script>
