import { GraphChart, RadarChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  GraphChart,
  RadarChart,
  ScatterChart,
  GridComponent,
  DataZoomComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

export { echarts }
