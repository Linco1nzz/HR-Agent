// ECharts 按需注册：新增图表类型时在这里补充，避免把整个 echarts 打进产物。
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
