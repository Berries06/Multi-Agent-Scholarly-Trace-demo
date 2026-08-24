import { GraphChart, RadarChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  GraphChart,
  RadarChart,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export { echarts }
