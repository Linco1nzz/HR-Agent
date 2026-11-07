<script setup lang="ts">
import { computed, type Component } from 'vue'

import {
  Briefcase,
  Clock,
  InfoFilled,
  Plus,
  TrendCharts,
  UserFilled,
} from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'

import BaseChart from '@/components/BaseChart.vue'
import { useAuthStore } from '@/stores/auth'

interface StatItem {
  label: string
  value: string
  unit: string
  trend: string
  trendLabel: string
  trendTone: 'up' | 'down' | 'neutral'
  icon: Component
  tone: 'blue' | 'green' | 'amber' | 'violet'
}

interface TodoItem {
  title: string
  meta: string
  tag: string
  tagType: 'primary' | 'success' | 'warning' | 'info'
}

const auth = useAuthStore()

const displayName = computed(() => auth.user?.full_name?.trim() || auth.user?.username || '同事')

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const today = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
}).format(new Date())

const stats: StatItem[] = [
  {
    label: '在职员工',
    value: '1,286',
    unit: '人',
    trend: '+3.2%',
    trendLabel: '较上月',
    trendTone: 'up',
    icon: UserFilled,
    tone: 'blue',
  },
  {
    label: '本月入职',
    value: '32',
    unit: '人',
    trend: '+8.1%',
    trendLabel: '较上月',
    trendTone: 'up',
    icon: Plus,
    tone: 'green',
  },
  {
    label: '待处理审批',
    value: '8',
    unit: '项',
    trend: '3 项即将超时',
    trendLabel: '',
    trendTone: 'neutral',
    icon: Clock,
    tone: 'amber',
  },
  {
    label: '招聘中职位',
    value: '12',
    unit: '个',
    trend: '覆盖 5 个部门',
    trendLabel: '',
    trendTone: 'neutral',
    icon: Briefcase,
    tone: 'violet',
  },
]

const todos: TodoItem[] = [
  {
    title: '张伟的转正审批',
    meta: '人才发展部 · 今天 18:00 截止',
    tag: '待审批',
    tagType: 'warning',
  },
  {
    title: '技术中心 3 月招聘需求',
    meta: '招聘计划 · 等待部门负责人确认',
    tag: '待确认',
    tagType: 'primary',
  },
  {
    title: '员工年度体检名单确认',
    meta: '员工关怀 · 本周五前完成',
    tag: '进行中',
    tagType: 'info',
  },
  {
    title: '2 月薪资异动复核',
    meta: '薪酬福利 · 已提交财务',
    tag: '待复核',
    tagType: 'success',
  },
]

const activities = [
  { name: '李娜', action: '更新了组织架构与汇报关系', time: '10 分钟前', color: '#2563eb' },
  { name: '陈晨', action: '完成了 5 位候选人的面试反馈', time: '1 小时前', color: '#7c3aed' },
  { name: '王磊', action: '提交了本月人员编制调整申请', time: '3 小时前', color: '#0d9488' },
  { name: '刘洋', action: '新增了 12 名新员工入职档案', time: '昨天 17:24', color: '#ea580c' },
]

const headcountOption: EChartsOption = {
  color: ['#2563eb', '#94a3b8'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#0f172a',
    borderWidth: 0,
    padding: [10, 14],
    textStyle: { color: '#f8fafc', fontSize: 12 },
  },
  legend: {
    top: 0,
    right: 0,
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 18,
    textStyle: { color: '#64748b', fontSize: 12 },
  },
  grid: { top: 44, right: 12, bottom: 0, left: 8, containLabel: true },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
    axisLine: { lineStyle: { color: '#e2e8f0' } },
    axisTick: { show: false },
    axisLabel: { color: '#94a3b8', fontSize: 11, margin: 12 },
  },
  yAxis: {
    type: 'value',
    min: 1000,
    splitNumber: 4,
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#94a3b8', fontSize: 11 },
  },
  series: [
    {
      name: '在职人数',
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: false,
      lineStyle: { width: 3, color: '#2563eb' },
      itemStyle: { color: '#2563eb', borderColor: '#ffffff', borderWidth: 2 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(37, 99, 235, 0.24)' },
            { offset: 1, color: 'rgba(37, 99, 235, 0.01)' },
          ],
        },
      },
      data: [1120, 1145, 1168, 1182, 1175, 1204, 1226, 1240, 1238, 1258, 1270, 1286],
    },
    {
      name: '编制人数',
      type: 'line',
      smooth: true,
      symbol: 'none',
      itemStyle: { color: '#94a3b8' },
      lineStyle: { width: 2, type: 'dashed', color: '#94a3b8' },
      data: [1200, 1210, 1220, 1230, 1240, 1250, 1260, 1270, 1280, 1290, 1300, 1320],
    },
  ],
}

const departmentOption: EChartsOption = {
  color: ['#2563eb', '#38bdf8', '#8b5cf6', '#f59e0b', '#94a3b8'],
  tooltip: {
    trigger: 'item',
    backgroundColor: '#0f172a',
    borderWidth: 0,
    padding: [10, 14],
    textStyle: { color: '#f8fafc', fontSize: 12 },
    formatter: '{b}<br/>{c} 人 · {d}%',
  },
  legend: {
    bottom: 0,
    left: 'center',
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 14,
    textStyle: { color: '#64748b', fontSize: 11 },
  },
  series: [
    {
      name: '部门分布',
      type: 'pie',
      radius: ['46%', '70%'],
      center: ['50%', '43%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#ffffff', borderWidth: 2, borderRadius: 4 },
      label: { show: false },
      emphasis: {
        scale: true,
        scaleSize: 6,
        label: { show: false },
      },
      data: [
        { value: 486, name: '产品研发' },
        { value: 282, name: '市场运营' },
        { value: 214, name: '客户成功' },
        { value: 176, name: '职能支持' },
        { value: 128, name: '其他' },
      ],
    },
  ],
}
</script>

<template>
  <div class="dashboard">
    <section class="welcome">
      <div class="welcome__text">
        <p class="welcome__date">{{ today }}</p>
        <h1>{{ greeting }}，{{ displayName }}</h1>
        <p class="welcome__description">这里是今天的组织概览，关键人才数据与待办事项已为你汇总。</p>
      </div>
      <el-tag class="welcome__tag" type="info" effect="plain" round>
        <el-icon><InfoFilled /></el-icon>
        演示数据
      </el-tag>
    </section>

    <section class="stats" aria-label="关键指标">
      <article
        v-for="stat in stats"
        :key="stat.label"
        class="stat-card"
        :class="`stat-card--${stat.tone}`"
      >
        <div class="stat-card__icon">
          <el-icon :size="21"><component :is="stat.icon" /></el-icon>
        </div>
        <div class="stat-card__body">
          <p class="stat-card__label">{{ stat.label }}</p>
          <p class="stat-card__value">
            {{ stat.value }}
            <small>{{ stat.unit }}</small>
          </p>
          <p class="stat-card__trend" :class="`is-${stat.trendTone}`">
            <span v-if="stat.trendLabel">{{ stat.trendLabel }}</span>
            {{ stat.trend }}
          </p>
        </div>
      </article>
    </section>

    <section class="dashboard__grid">
      <article class="panel panel--trend">
        <header class="panel__header">
          <div>
            <h2>人员规模趋势</h2>
            <p>近 12 个月在职人数与编制对比</p>
          </div>
          <el-icon class="panel__header-icon"><TrendCharts /></el-icon>
        </header>
        <BaseChart
          :option="headcountOption"
          height="310px"
          label="近 12 个月在职人数与编制人数趋势折线图"
        />
      </article>

      <article class="panel panel--department">
        <header class="panel__header">
          <div>
            <h2>部门人员分布</h2>
            <p>当前在职员工的部门构成</p>
          </div>
        </header>
        <BaseChart :option="departmentOption" height="310px" label="在职员工部门人员分布环形图" />
      </article>

      <article class="panel panel--todos">
        <header class="panel__header">
          <div>
            <h2>今日待办</h2>
            <p>需要你关注的事项</p>
          </div>
          <span class="panel__count">{{ todos.length }}</span>
        </header>

        <ul class="todo-list">
          <li v-for="todo in todos" :key="todo.title" class="todo">
            <span class="todo__dot" />
            <div class="todo__body">
              <p class="todo__title">{{ todo.title }}</p>
              <p class="todo__meta">{{ todo.meta }}</p>
            </div>
            <el-tag :type="todo.tagType" size="small" effect="light" round>
              {{ todo.tag }}
            </el-tag>
          </li>
        </ul>
      </article>

      <article class="panel panel--activity">
        <header class="panel__header">
          <div>
            <h2>团队动态</h2>
            <p>最近的协作与变更记录</p>
          </div>
        </header>

        <ul class="activity-list">
          <li v-for="activity in activities" :key="activity.action" class="activity">
            <el-avatar :size="34" :style="{ background: activity.color }">
              {{ activity.name.slice(0, 1) }}
            </el-avatar>
            <div class="activity__body">
              <p>
                <strong>{{ activity.name }}</strong> {{ activity.action }}
              </p>
              <span>{{ activity.time }}</span>
            </div>
          </li>
        </ul>
      </article>
    </section>

    <p class="dashboard__note">
      <el-icon><InfoFilled /></el-icon>
      当前指标与图表为演示数据；登录、会话与用户信息已接入真实后端接口。
    </p>
  </div>
</template>

<style scoped>
.dashboard {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
}

.welcome {
  display: flex;
  gap: 18px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}

.welcome__date {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 500;
  color: #94a3b8;
}

.welcome h1 {
  font-size: clamp(24px, 2.4vw, 32px);
  font-weight: 700;
  letter-spacing: -0.8px;
  color: #0f172a;
}

.welcome__description {
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}

.welcome__tag {
  flex: none;
  margin-top: 4px;
}

.welcome__tag :deep(.el-tag__content) {
  display: flex;
  gap: 5px;
  align-items: center;
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.stat-card {
  display: flex;
  gap: 15px;
  align-items: flex-start;
  padding: 20px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--app-shadow);
}

.stat-card__icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
}

.stat-card--blue .stat-card__icon {
  color: #2563eb;
  background: #eff6ff;
}

.stat-card--green .stat-card__icon {
  color: #0d9488;
  background: #ecfdf5;
}

.stat-card--amber .stat-card__icon {
  color: #d97706;
  background: #fffbeb;
}

.stat-card--violet .stat-card__icon {
  color: #7c3aed;
  background: #f5f3ff;
}

.stat-card__body {
  min-width: 0;
}

.stat-card__label {
  font-size: 12px;
  color: #64748b;
}

.stat-card__value {
  margin-top: 4px;
  font-size: 27px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.8px;
  color: #0f172a;
}

.stat-card__value small {
  margin-left: 3px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0;
  color: #94a3b8;
}

.stat-card__trend {
  margin-top: 7px;
  font-size: 11px;
  color: #94a3b8;
}

.stat-card__trend span {
  margin-right: 4px;
  color: #94a3b8;
}

.stat-card__trend.is-up {
  color: #059669;
}

.stat-card__trend.is-down {
  color: #dc2626;
}

.stat-card__trend.is-neutral {
  color: #d97706;
}

.dashboard__grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 18px;
}

.panel {
  padding: 22px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.panel--trend {
  grid-column: span 8;
}

.panel--department {
  grid-column: span 4;
}

.panel--todos {
  grid-column: span 7;
}

.panel--activity {
  grid-column: span 5;
}

.panel__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.panel__header h2 {
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
}

.panel__header p {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}

.panel__header-icon {
  color: #cbd5e1;
  font-size: 20px;
}

.panel__count {
  display: grid;
  place-items: center;
  min-width: 26px;
  height: 26px;
  font-size: 12px;
  font-weight: 600;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 8px;
}

.todo-list,
.activity-list {
  display: flex;
  flex-direction: column;
  padding: 0;
  margin: 0;
  list-style: none;
}

.todo {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 13px 0;
  border-bottom: 1px solid #f1f5f9;
}

.todo:first-child {
  padding-top: 4px;
}

.todo:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.todo__dot {
  flex: none;
  width: 7px;
  height: 7px;
  background: #2563eb;
  border-radius: 50%;
  box-shadow: 0 0 0 4px #eff6ff;
}

.todo__body {
  flex: 1;
  min-width: 0;
}

.todo__title {
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo__meta {
  margin-top: 3px;
  overflow: hidden;
  font-size: 11px;
  color: #94a3b8;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.activity:first-child {
  padding-top: 4px;
}

.activity:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.activity__body {
  min-width: 0;
}

.activity__body p {
  font-size: 12.5px;
  line-height: 1.55;
  color: #475569;
}

.activity__body strong {
  font-weight: 600;
  color: #1e293b;
}

.activity__body span {
  font-size: 11px;
  color: #94a3b8;
}

.dashboard__note {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  margin-top: 22px;
  font-size: 11px;
  color: #94a3b8;
}

@media (max-width: 1200px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel--trend,
  .panel--department,
  .panel--todos,
  .panel--activity {
    grid-column: span 6;
  }
}

@media (max-width: 760px) {
  .welcome {
    flex-direction: column;
    gap: 10px;
  }

  .stats {
    grid-template-columns: 1fr;
  }

  .panel--trend,
  .panel--department,
  .panel--todos,
  .panel--activity {
    grid-column: 1 / -1;
  }
}
</style>
