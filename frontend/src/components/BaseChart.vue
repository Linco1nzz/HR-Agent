<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { EChartsOption } from 'echarts'
import * as echarts from 'echarts/core'
import type { EChartsType } from 'echarts/core'

import '@/plugins/echarts'

const props = withDefaults(
  defineProps<{
    option: EChartsOption
    height?: string
    label?: string
  }>(),
  {
    height: '320px',
    label: '数据图表',
  },
)

const container = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

function render(): void {
  chart?.setOption(props.option, { notMerge: true })
}

onMounted(() => {
  if (!container.value) {
    return
  }

  chart = echarts.init(container.value, undefined, { renderer: 'canvas' })
  render()

  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(container.value)
})

watch(
  () => props.option,
  () => render(),
  { deep: true },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="container" class="base-chart" :style="{ height }" role="img" :aria-label="label" />
</template>

<style scoped>
.base-chart {
  width: 100%;
  min-height: 200px;
}
</style>
