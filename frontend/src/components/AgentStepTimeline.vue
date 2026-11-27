<script setup lang="ts">
import type { Component } from 'vue'

import { CircleCheck, CircleClose, Clock, Loading, Remove, Warning } from '@element-plus/icons-vue'

import type { AgentStep, AgentStepStatus, AgentTaskStatus } from '@/api/types'

const props = defineProps<{
  steps: AgentStep[]
  /** 当前步骤下标，用于高亮。 */
  currentStepIndex?: number
  taskStatus?: AgentTaskStatus | null
}>()

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const STATUS_LABELS: Record<AgentStepStatus, { label: string; tag: TagType; icon: Component }> = {
  pending: { label: '待执行', tag: 'info', icon: Clock },
  running: { label: '执行中', tag: 'primary', icon: Loading },
  waiting_confirm: { label: '待确认', tag: 'warning', icon: Warning },
  completed: { label: '已完成', tag: 'success', icon: CircleCheck },
  failed: { label: '失败', tag: 'danger', icon: CircleClose },
  skipped: { label: '已跳过', tag: 'info', icon: Remove },
  cancelled: { label: '已取消', tag: 'info', icon: CircleClose },
}

function statusLabel(value: AgentStepStatus): string {
  return STATUS_LABELS[value].label
}

function statusTag(value: AgentStepStatus): TagType {
  return STATUS_LABELS[value].tag
}

function statusIcon(value: AgentStepStatus): Component {
  return STATUS_LABELS[value].icon
}

/** 当前步骤是否处于执行中（含「已排到的待执行步骤」）。 */
function isSpinning(step: AgentStep): boolean {
  if (step.status === 'running') return true
  if (step.status !== 'pending') return false
  const active = props.taskStatus === 'created' || props.taskStatus === 'running'
  return active && step.step_index === props.currentStepIndex
}

function isCurrent(step: AgentStep): boolean {
  return step.step_index === props.currentStepIndex && props.taskStatus !== 'completed'
}
</script>

<template>
  <div class="agent-timeline">
    <div
      v-for="step in steps"
      :key="step.step_index"
      class="agent-step"
      :class="[
        `agent-step--${step.status}`,
        { 'is-current': isCurrent(step), 'is-spinning': isSpinning(step) },
      ]"
    >
      <div class="agent-step__marker">
        <el-icon :size="14">
          <component :is="isSpinning(step) ? Loading : statusIcon(step.status)" />
        </el-icon>
      </div>

      <div class="agent-step__body">
        <div class="agent-step__head">
          <span class="agent-step__name">{{ step.name || step.tool }}</span>
          <el-tag size="small" :type="statusTag(step.status)" effect="plain" round>
            {{ statusLabel(step.status) }}
          </el-tag>
          <span class="agent-step__tool">{{ step.tool }}</span>
        </div>

        <p v-if="step.summary && !step.result_preview" class="agent-step__summary">
          {{ step.summary }}
        </p>
        <p v-if="step.result_preview" class="agent-step__preview" :title="step.result_preview">
          {{ step.result_preview }}
        </p>
        <p v-if="step.error" class="agent-step__error">{{ step.error }}</p>
      </div>
    </div>

    <p v-if="!steps.length" class="agent-timeline__empty">正在规划执行步骤…</p>
  </div>
</template>

<style scoped>
.agent-timeline {
  display: flex;
  flex-direction: column;
}

.agent-step {
  position: relative;
  display: flex;
  gap: 10px;
  padding-bottom: 14px;
}

.agent-step:last-child {
  padding-bottom: 0;
}

/* 竖向连接线 */
.agent-step:not(:last-child)::before {
  position: absolute;
  top: 24px;
  bottom: 4px;
  left: 11px;
  width: 1px;
  content: '';
  background: #e2e8f0;
}

.agent-step__marker {
  z-index: 1;
  display: grid;
  flex: none;
  place-items: center;
  width: 23px;
  height: 23px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 50%;
}

.agent-step--running .agent-step__marker {
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.28);
}

.agent-step--waiting_confirm .agent-step__marker {
  color: #b45309;
  background: #fef3c7;
}

.agent-step--completed .agent-step__marker {
  color: #059669;
  background: #d1fae5;
}

.agent-step--failed .agent-step__marker {
  color: #dc2626;
  background: #fee2e2;
}

.agent-step--cancelled .agent-step__marker,
.agent-step--skipped .agent-step__marker {
  color: #94a3b8;
  background: #f1f5f9;
}

.agent-step.is-spinning .agent-step__marker .el-icon {
  animation: agent-step-spin 1s linear infinite;
}

@keyframes agent-step-spin {
  to {
    transform: rotate(360deg);
  }
}

.agent-step__body {
  flex: 1;
  min-width: 0;
  padding-top: 1px;
}

.agent-step__head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.agent-step__name {
  font-size: 12.5px;
  font-weight: 650;
  color: #1e293b;
}

.agent-step.is-current .agent-step__name {
  color: #1d4ed8;
}

.agent-step__tool {
  overflow: hidden;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10.5px;
  color: #b0bac9;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-step__summary,
.agent-step__preview {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.65;
  color: #64748b;
  overflow-wrap: anywhere;
}

.agent-step__preview {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.agent-step__error {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.65;
  color: #dc2626;
}

.agent-timeline__empty {
  font-size: 11.5px;
  color: #94a3b8;
}
</style>
